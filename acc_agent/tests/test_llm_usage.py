import contextlib
import json
import unittest
from unittest.mock import Mock, patch

from anthropic.types import Message
from langchain_core.messages import AIMessage

from agent import CodeActAgent, usage_record
from kernel_executor import KernelCodeExecutor
from llm import load_llm, model_identity, with_reasoning


class LLMUsageTests(unittest.TestCase):
    def model(self, provider):
        with patch.dict("os.environ", {"PROVIDER": provider, "MINIMAX_API_KEY": "offline-test",
                                      "OPENROUTER_API_KEY": "offline-test", "MODEL": "fixture"}):
            return load_llm()

    def test_minimax_totals_include_cache_once(self):
        model = with_reasoning(self.model("minimax"), True)
        response = Message(id="fixture", type="message", role="assistant", model="fixture",
                           content=[{"type": "tool_use", "id": "action", "name": "run_python", "input": {"code": "print(1)"}}],
                           stop_reason="max_tokens", usage={"input_tokens": 100, "output_tokens": 20,
                           "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50})
        with patch.object(model._client.messages.with_raw_response, "create") as create:
            create.return_value.parse.return_value = response
            message = model.invoke("fixture request")
        usage = usage_record(message)
        self.assertEqual(usage["prompt_tokens"], 1050)
        self.assertEqual(usage["completion_tokens"], 20)
        self.assertEqual(usage["cache_read_input_tokens"], 900)
        self.assertEqual(usage["cache_creation_input_tokens"], 50)
        self.assertTrue(usage["truncated"])
        self.assertEqual(message.tool_calls[0]["args"], {"code": "print(1)"})
        self.assertEqual(create.call_args.kwargs["thinking"], {"type": "adaptive"})
        self.assertEqual(model.max_retries, 0)
        self.assertEqual(model.default_request_timeout, 180)

    def test_openrouter_cache_is_already_in_input_total(self):
        model = with_reasoning(self.model("openrouter"), False)
        response = {"choices": [{"message": {"role": "assistant", "content": "reply"}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 20, "total_tokens": 1020,
                              "prompt_tokens_details": {"cached_tokens": 900}}}
        with patch.object(model.client.chat, "send", return_value=response) as send:
            message = model.invoke("fixture request")
        usage = usage_record(message)
        self.assertEqual(usage["prompt_tokens"], 1000)
        self.assertEqual(usage["cache_read_input_tokens"], 900)
        self.assertTrue(usage["truncated"])
        self.assertEqual(send.call_args.kwargs["reasoning"], {"enabled": False})
        self.assertEqual(model.max_retries, 0)
        self.assertEqual(model.request_timeout, 180_000)  # OpenRouter SDK timeout is in milliseconds

    def test_openrouter_claude_requests_prompt_caching(self):
        import httpx
        bodies = []

        def reply(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 0, "model": "fixture",
                                             "system_fingerprint": None,
                                             "choices": [{"index": 0, "message": {"role": "assistant", "content": "reply"},
                                                          "finish_reason": "stop"}],
                                             "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}})

        for name, cached in (("anthropic/claude-sonnet-5.5", True), ("minimax/minimax-m3", False)):
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "offline-test"}):
                model = load_llm(name, "openrouter")
            model.client.sdk_configuration.client = httpx.Client(transport=httpx.MockTransport(reply))
            model.bind_tools([{"type": "function", "function": {"name": "run_python", "parameters": {}}}],
                             tool_choice="any").invoke("fixture request")
            self.assertEqual(bodies[-1].get("cache_control"), {"type": "ephemeral"} if cached else None)
            # Claude 5.x rejects forced tool use; MiniMax keeps it.
            self.assertEqual(bodies[-1].get("tool_choice"), None if cached else "required")

    def test_missing_usage_is_explicit_not_a_measured_zero(self):
        usage = usage_record(AIMessage(content="reply"))
        self.assertFalse(usage["usage_reported"])
        self.assertIsNone(usage["prompt_tokens"])
        self.assertFalse(usage["truncated"])

    def test_factory_identity_and_missing_credentials(self):
        for provider in ("minimax", "openrouter"):
            self.assertEqual(model_identity(self.model(provider)), {"provider": provider, "model": "fixture"})
        with patch.dict("os.environ", {"PROVIDER": "minimax", "MINIMAX_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "MINIMAX_API_KEY"):
                load_llm()

    def test_explicit_provider_overrides_environment(self):
        with patch.dict("os.environ", {"PROVIDER": "minimax", "MINIMAX_API_KEY": "offline-test",
                                      "OPENROUTER_API_KEY": "offline-test", "MODEL": ""}):
            self.assertEqual(model_identity(load_llm(provider="openrouter")),
                             {"provider": "openrouter", "model": "minimax/minimax-m3"})
            self.assertEqual(model_identity(load_llm()), {"provider": "minimax", "model": "MiniMax-M3"})

    def test_complete_agent_roundtrip_through_both_native_adapters(self):
        calls = [
            ("run_python", {"code": 'report_labels({"anchor": "PASS"})'}, "execute"),
            ("FinalReport", {"verdict": "COMPLIANT", "violations": [], "reason": ""}, "final"),
        ]
        for provider in ("minimax", "openrouter"):
            with self.subTest(provider=provider), contextlib.ExitStack() as stack:
                stack.enter_context(patch("tracing.get_client", return_value=None))
                stack.enter_context(patch("agent.discover_scope", return_value=({"anchor"}, "offline scope")))
                model = self.model(provider)
                executor = KernelCodeExecutor(timeout=30)
                stack.callback(executor.close)
                if provider == "minimax":
                    responses = [Message(id=call_id, type="message", role="assistant", model="fixture",
                                         content=[{"type": "thinking", "thinking": f"reasoning {call_id}", "signature": "sig"},
                                                  {"type": "tool_use", "name": name, "id": call_id, "input": arguments}],
                                         stop_reason="tool_use", usage={"input_tokens": 100, "output_tokens": 20})
                                 for name, arguments, call_id in calls]
                    transport = stack.enter_context(patch.object(model._client.messages.with_raw_response, "create",
                        side_effect=[Mock(parse=Mock(return_value=response)) for response in responses]))
                else:
                    responses = [{"choices": [{"message": {"role": "assistant", "content": "", "reasoning": f"reasoning {call_id}",
                        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]},
                        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}
                        for name, arguments, call_id in calls]
                    transport = stack.enter_context(patch.object(model.client.chat, "send", side_effect=responses))
                result = CodeActAgent(model, executor, max_iterations=2, env_primer=False).check("Judge anchor", "unused.ifc")
                self.assertEqual(result.completion_status, "complete")
                self.assertEqual(result.labels, {"anchor": "PASS"})
                self.assertEqual(result.prompt_tokens, 200)
                self.assertEqual(transport.call_count, 2)
                schemas = transport.call_args_list[0].kwargs["tools"]
                names = {schema.get("name") or schema["function"]["name"] for schema in schemas}
                self.assertEqual(names, {"run_python", "FinalReport"})
                # Interleaved thinking requires earlier reasoning in history; tool results are plain text.
                sent = json.dumps(transport.call_args_list[1].kwargs["messages"], default=str)
                self.assertIn("reasoning execute", sent)
                self.assertIn(json.dumps(result.execution_records[0]["output"])[1:-1], sent)
                self.assertNotIn("labels_valid", sent)


if __name__ == "__main__":
    unittest.main()