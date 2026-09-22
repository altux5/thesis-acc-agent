import unittest
from unittest.mock import Mock

from executor import _BoundedOutput
from kernel_executor import KernelCodeExecutor


class ExecutorSubmissionTests(unittest.TestCase):
    def executor(self, **settings):
        executor = KernelCodeExecutor(timeout=30, **settings)
        self.addCleanup(executor.close)
        return executor

    def test_retired_skills_cannot_be_enabled_but_local_functions_still_work(self):
        for stateful in (True, False):
            with self.subTest(stateful=stateful):
                library = Mock(enabled=True)
                executor = self.executor(stateful=stateful, skill_library=library)
                self.assertIsNone(executor.skill_library)
                self.assertEqual(executor.skill_prompt_section(), "")
                output = executor.run(
                    'def local_helper(value):\n    return value * 2\n'
                    'report_labels({"anchor": "PASS"})\n'
                    'print("save_skill" in globals())'
                )
                self.assertEqual(output, "False")
                self.assertEqual(executor.reported_labels, {"anchor": "PASS"})
                output = executor.run("print(local_helper(3))")
                if stateful:
                    self.assertEqual(output, "6")
                else:
                    self.assertIn("NameError", output)
                self.assertEqual(library.mock_calls, [])

    def test_capture_memory_is_bounded_but_error_details_remain_visible(self):
        buffer = _BoundedOutput(60)
        self.assertEqual(buffer.write("a" * 10000), 10000)
        buffer.writelines(["b" * 10000, "c" * 10000])
        self.assertEqual(len(buffer.getvalue()), 60)
        self.assertEqual(buffer.dropped_chars, 29940)
        executor = self.executor(output_char_limit=60)
        output = executor.run('print("x" * 300)\nraise ValueError("actual failure")')
        self.assertIn("ValueError: actual failure", output)
        self.assertIn("[truncated", output)
        self.assertTrue(executor.last_execution["error"])
        self.assertTrue(executor.last_execution["truncated"])
        self.assertLess(len(output), 6300)

    def test_system_exit_is_a_failed_attempt_not_process_exit(self):
        for stateful in (True, False):
            with self.subTest(stateful=stateful):
                executor = self.executor(stateful=stateful)
                output = executor.run('report_labels({"anchor":"PASS"})\nraise SystemExit(7)')
                self.assertIn("SystemExit: 7", output)
                self.assertTrue(executor.last_error)
                self.assertFalse(executor.labels_valid)
                self.assertEqual(executor.reported_labels, {})
                self.assertEqual(executor.run('print("alive")'), "alive")
                self.assertFalse(executor.last_execution["error"])
                self.assertFalse(executor.labels_valid)

    def test_keyboard_interrupt_restarts_worker_and_invalidates_labels(self):
        executor = self.executor()
        executor.run('report_labels({"anchor":"PASS"})')
        # The retired in-process executor propagated KeyboardInterrupt to the host.
        # with self.assertRaises(KeyboardInterrupt):
        #     executor.run('raise KeyboardInterrupt()')
        output = executor.run('raise KeyboardInterrupt()')
        self.assertIn("KeyboardInterrupt", output)
        self.assertTrue(executor.last_execution["kernel_restarted"])
        self.assertFalse(executor.labels_valid)
        self.assertEqual(executor.reported_labels, {})
        self.assertEqual(executor.run('print("alive")'), "alive")

    def test_reports_commit_together_only_on_success(self):
        executor = self.executor()
        executor.run('report_labels({"first":"PASS"})\nreport_labels({"second":"FAIL"})')
        self.assertEqual(executor.reported_labels, {"second": "FAIL"})
        self.assertEqual(executor.label_reports, 2)
        self.assertTrue(executor.labels_valid)
        executor.run('report_labels({"third":"PASS"})\nraise ValueError("failed")')
        self.assertEqual(executor.reported_labels, {})
        self.assertEqual(executor.label_reports, 2)
        self.assertFalse(executor.labels_valid)
        executor.run('print("success without labels")')
        self.assertFalse(executor.labels_valid)

    def test_successful_empty_report_remains_distinguishable_from_missing(self):
        executor = self.executor(stateful=False)
        executor.run('report_labels({})')
        self.assertTrue(executor.labels_valid)
        executor.run('print(1)')
        self.assertTrue(executor.labels_valid)
        executor.run('raise ValueError("failed")')
        executor.run('print(1)')
        self.assertFalse(executor.labels_valid)

    def test_mapping_is_copied_and_failed_normalization_invalidates_submission(self):
        executor = self.executor()
        executor.run('labels = {"anchor":"PASS"}\nreport_labels(labels)\nlabels["anchor"] = "FAIL"')
        self.assertEqual(executor.reported_labels, {"anchor": "PASS"})
        executor.run('report_labels({"anchor":"invalid"})')
        self.assertFalse(executor.labels_valid)
        self.assertEqual(executor.reported_labels, {})


if __name__ == "__main__":
    unittest.main()