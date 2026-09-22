# Pilot Audit - 2026-09-07; Staircase Scope Updated 2026-09-17

Read-only IFC/reference audit before enabling pooled experiments. No paid agent
runs were used. This is not a claim that the code or references are bug-free.

## Results

| Pilot | Finding | Use in comparisons |
| --- | --- | --- |
| `slab_thickness__mall_v2` | 112 IFC anchors match 112 labels; regenerated provenance matches the stored case; 100 PASS, 12 ALERT, zero FAIL | Coverage, missing-data and false-positive control only |
| `doors_windows_storey__condo` | Independent traversal of raw fills, voids, containment and aggregation relationships matches every label: 208 PASS, 4 FAIL across 212 anchors | Usable for this recorded-relationship check; not expert regulatory certification |
| `staircase_width_v8` | 49 of 59 IFC stairs have workbook labels: 27 PASS, 22 FAIL. The other ten are explicitly unscored, not PASS or NA | New audited subset-policy runs are eligible for comparisons; accuracy applies to the 49 annotated stairs only |

All 43 case JSON files passed structural checks: known labels, no duplicate
violation IDs, nonempty rules and consistency between stored FAIL sets and
violation lists. This initial pilot audit did not semantically review non-pilot
references. The full-catalogue review below supersedes that limitation, with
explicit distinctions between source agreement and physical correctness.

## Unresolved Risks

- Ten staircase outcomes remain unannotated. The explicit scoring policy fixes
  the scope conflict, not the missing expert judgments or clear-width geometry.
  Subset scores must not be presented as full-population regulatory accuracy.
- Slab v2 is a project adjudication of recorded thickness fields. Agreeing fields
  can originate from the same exporter. It has no failure examples and cannot
  establish violation recall. The original slab reference remains invalid legacy.
- Completion checks verify submission structure, not measurement correctness.
  Correct-looking labels can still be unsupported. Custom scopes may be unverified.
- Existing F1/precision conventions can look perfect for an empty violation set.
  Existing union averages exclude missing submissions. The database preserves raw
  metrics, includes failed attempts in completion rates and shows measurement N.
- Skill reuse creates changing conditions. Stored skill fingerprints separate
  those configurations, and skills-enabled runs are outside the default comparison
  filter. No skills were deleted or disabled silently.
- Provider-default sampling, cache accounting and sequential mode order remain
  limitations. Tokens are stored as reported, not converted into guessed cost.

## Fixed During Audit

On 2026-09-17, staircase reference metadata gained `annotated-subset-v1`: the
exact ten unannotated IFC IDs, population 59, and IFC SHA-256. CLI/GUI scoring and
Harness 3 feedback exclude only these IDs from agreement metrics. Invalid extra
IDs and missing authored labels still incur penalties. Completion still requires
all 59 stairs; perfect subset agreement cannot request early finalization of a
partial submission. No expert labels were changed or invented.

The workbook importer reproduces this metadata. The audit verifies workbook
agreement, exact labelled-plus-unscored IFC coverage, and the model fingerprint
before assigning `expert-subset-checked`. New non-training configurations can
enter comparisons; old logs, scores and database rows are unchanged and stay
separate through reference/code fingerprints. Under the old policy, an otherwise
matching full-population report was capped at 49/59 = 0.831 union accuracy.

The scorer previously called every UNKNOWN an abstention, including the fallback
UNKNOWN for a run with no parseable verdict. Deliberate abstention now additionally
requires `parse_ok`. Historical logs and scores are unchanged; new code fingerprints
prevent pooling the old and new checker versions as identical configurations.

## Reproduce

From the workspace root, using the project environment:

```powershell
.\.venv\Scripts\python.exe acc_agent/benchmark_audit.py
.\.venv\Scripts\python.exe -m unittest discover -s acc_agent/tests -t acc_agent -p "test_*.py" -v
```

The audit reads resolved IFC paths and the staircase expert workbook. Missing
models/workbooks are reported as unverified, not successful checks. Live-file tests
are skipped when their local IFC fixtures are unavailable.

## Full Catalogue Review - 2026-09-17

**Verdict: the catalogue is not ready to be treated as 43 correct regulatory
benchmarks.** Twelve cases should be held out because of demonstrated reference
or task-definition defects. Other cases range from useful recorded-data checks
to weak controls or references that still require geometric adjudication.

This review changed no labels, rules, application code, audit eligibility flags,
or historical results. Recommendations below are not replacement annotations.

### Verification Performed

- Inspected all 43 JSON cases, containing 2,425 label entries across reused
  models and rules. All models were available at the 12 referenced IFC paths.
- All labelled GlobalIds resolve. All explicit class scopes have exact coverage,
  accounting for the staircase's ten declared unscored IDs. Exit access and
  headroom have no explicit class scope in their prompts.
- All 37 simple-rule cases reproduce their stored labels and rule text using
  their original producers, including the intentionally retained legacy mall
  slab reference. Mall slab v2 also reproduces. Reproduction is not independent
  validation of the producer.
- All four imported cases exactly match their workbook buckets and requirement
  text; no duplicate GUID rows were found for the imported clauses. This proves
  faithful import, not that the workbook judgments are physically correct.
- Independently recalculated the door-width case with IFC unit conversion and
  traversed raw fills, voids, containment and aggregation relations for all five
  door/window-storey cases. Every label agrees.
- Examined available stair dimension/count properties across all eight models.
  Alternative values found for the same measurement agree. Native flight
  RiserHeight, TreadLength and NumberOfRisers attributes are absent in these
  files; they do not independently corroborate the property sets.
- Processed meshes for all 284 stair flights for riser-height sanity checks.
  No discrepancy above 2 mm was found where repeated horizontal step levels
  supported a comparison. This is not a certified reconstruction of every riser.
- Tread geometry supported a regular-step centroid check on 227 flights. Of the
  other 57, 21 curved/spiral flights were deliberately not measured by that
  method and 36 lacked enough regular steps. One mall PASS had a centroid-step
  difference (345.458 versus recorded 275 mm), not a demonstrated label change.
  Tapered treads require the correct regulatory measurement line.
- Reviewed every FAIL flight in the four landing cases containing failures,
  including meshes and parent/child decomposition. Reviewed slab properties and
  layer quantities across every model, with mesh checks on suspect slabs.
- Checked the local BCA Approved Document V7.08, including E.2.4, E.3.4.1-3 and
  E.3.5.2 (PDF pages 40, 42 and 43), and inspected source workbook explanations.

Limitations: this is a read-only engineering audit, not expert certification.
No full independent clear-width, headroom collision, egress routing or planter
externalisation measurement was completed. No paid LLM runs were made. The
extended checks used offline inspection snippets; the command above still
automates structural checks and the three pilots, not every semantic check here.

### Findings Requiring Action

**1. Landing references confuse staircase totals with flight counts and ignore
an explicit exception.** The producer in [simple_rules.py](simple_rules.py#L317)
compares the first recorded count with 18 without inspecting the parent stair.

- `landing_interval_e352__mall`: 16 FAIL flights belong to four stair assemblies.
  Each assembly has four flight children and three slab landings; its total of
  27 risers is repeated on every flight. The flight meshes have 1-11 upward
  horizontal tread levels, not 27 risers per run. Example flight
  `01eK4dY8KgZrmkBHlrvLQn` has 11 top levels at 170 mm spacing and a 2070 mm
  vertical mesh extent. The seventeenth FAIL is a spiral stair, explicitly
  exempt from E.3.5.2. Do not use the stored 17 failures as violation truth.
- `landing_interval_e352__scdf_5`: all six FAIL flights belong to three stairs
  with two flights and two slab landings each. The parent total of 21 is repeated
  on both children. Meshes have 9-10 horizontal tread levels per child. The six
  FAILs are not supported as runs exceeding 18 risers.
- `landing_interval_e352__stair_v8` and `__stair_obos`: respectively 12 and 8
  FAIL flights have parents explicitly typed SPIRAL_STAIR. These violate the
  prompt's own exemption. They should not be FAIL under this clause; the final
  NA/applicability mapping should be adjudicated, not inferred from this report.
- Across these cases, 21 stored FAIL entries ignore the spiral exception and
  another 22 use repeated whole-stair totals. Entries overlap between model
  versions, so these are not 43 independent physical defects.

**2. Slab references repeat the depth/thickness problem outside the mall.**
The fixed lookup in [simple_rules.py](simple_rules.py#L338) is not a reliable
interpretation of all exporters' fields.

- `slab_thickness__condo`: all 16 ALERT elements have recorded explicit
  thickness. Ten have 150-300 mm values and six have 20/25 mm roof values.
  The latter are not automatically PASS: they expose the arbitrary 100 mm lower
  bound and the inclusion of thin roofs in an all-IfcSlab scope. Example
  `0DhS1aHnP5Ggz0zjnSD0EC` has Construction.Default Thickness = 200 mm;
  `18tJH0s6HA7QlNk3BYSypH` has 25 mm. The existing 1200 mm transfer-slab FAIL
  agrees with explicit fields and mesh thickness, but is only a failure of the
  chosen plausibility range, not evidence of a building-code violation.
- `slab_thickness__stair_obos`: all four FAILs read Depth = 1200 mm from
  landings whose local mesh short dimension is 201 mm. Example
  `2WUftTkg92EQYKeFufTBFj` has a roughly 1096 x 1205 x 201 mm mesh.
- `slab_thickness__scdf_5`: all five FAILs use depths of 2913-4200 mm.
  Three are landings with mesh vertical extents around 230-236 mm; two are
  ramp slabs with a 150 mm short dimension and recorded quantity Length =
  150 mm. These are strong plan-depth/thickness contradictions, not a licence
  to treat a bounding-box axis as universal thickness.
- `slab_thickness__scdf_3`: at least three ALERT floors have explicit nested
  layer quantities, Concrete, Precast / Width = 200 mm. The reference ignores
  this evidence. Example `3b4vt0v098e9GrdqLF_Vt4` also has a 200 mm mesh extent.
- Legacy `slab_thickness__mall` remains invalid: 15 FAILs and 23 ALERTs
  contradict agreeing explicit thickness fields. V2 preserves the other 12
  ALERTs under its recorded-data-only policy. Geometry existing for an ALERT
  does not by itself invalidate that policy.

Do not fix this by searching for every property containing "thickness": condo
landings also contain Treads.Tread Thickness = 0 alongside a 300 mm monolithic
slab thickness. Component thickness and total slab thickness are different data.

**3. The headroom workbook is not an independently trustworthy physical oracle.**
[ground_truth/headroom_condo_c32.json](ground_truth/headroom_condo_c32.json)
labels 155 doors and 17 stairs, but the task refers to rooms and circulation
spaces and the IFC also contains 33 unlabelled spaces.

All 155 doors have SGPset_Door.ClearHeight = 2000 mm. Eight doors are marked PASS
with the explanation "Door ClearHeight 2000mm >= 2000mm" despite OverallHeight
and mesh height of 650-1980 mm. For example `1nSmWqczX4NuhcdHuXv57J` has a
1500 mm door mesh and recorded dimensional height; `0IZdbWeT17wQXDgNfHPEgv`
has a 1980 mm mesh and 1960 mm panel height. Four short elements are refuse-chute
hoppers; a side gate may not bound overhead clearance. These need applicability
judgments, not eight automatic FAIL replacements. The source explanations do
not record such exemptions. The stair FAIL's claimed 1390 mm clearance was not
independently reconstructed. Hold this case until scope and conflicting evidence
are adjudicated.

**4. Exit access is underspecified and incompletely annotated.**
[ground_truth/exit_requirements_v0.json](ground_truth/exit_requirements_v0.json)
contains a clause cut off at "other tenanted s" and no stated reporting class.
Only 39 of 123 IfcSpace elements are labelled; the other 84 include offices,
reception areas, function rooms and meeting rooms, not only circulation/exit
facilities. There is no explicit subset policy. The reference messages also
depend on electromechanical locking and indirect access conditions omitted from
the prompt. Import is faithful, but a complete, fair test needs the full clause,
an operational space scope, and adjudicated or explicitly unscored remaining IDs.

**5. Planter GFA is a classification problem presented as a violation test.**
[ground_truth/planter_box_gfa.json](ground_truth/planter_box_gfa.json) supplies
neither numerical conditions nor a definition of PASS/FAIL. Workbook messages
use PASS = excluded from GFA and FAIL = included in GFA, based on width at most
1000 mm, depth at least 500 mm and externalisation for communal planter boxes.
GFA inclusion does not itself mean a regulatory violation. State an explicit
eligibility-for-exclusion task or use a GFA classification output; supply the
applicable rule and measurement definitions before interpreting these labels.

### Complete Case Inventory

Counts are the current stored labels, not proposed corrected values. P = PASS,
F = FAIL, A = ALERT; there are no stored NA or MANUAL_CHECK outcomes in this
catalogue. "Supported" means supported for the stated narrow data task, not
certified physical compliance. "Control" means useful for a limited baseline,
not a stand-alone violation-detection benchmark. "Review" means more evidence
or a clearer policy is needed. "Hold" means a demonstrated defect blocks use.

| Case | P | F | A | Reference Assessment And Logical Use |
| --- | ---: | ---: | ---: | --- |
| [door_width_planterbox](ground_truth/door_width_planterbox.json) | 27 | 7 | 0 | Supported as an OverallWidth threshold baseline, not actual clear-opening measurement. |
| [doors_windows_storey__condo](ground_truth/doors_windows_storey__condo.json) | 208 | 4 | 0 | Supported by independent relationships. Useful BIM-consistency test; highly imbalanced. |
| [doors_windows_storey__mall](ground_truth/doors_windows_storey__mall.json) | 216 | 1 | 0 | Supported by independent relationships. Useful second model; very few failures. |
| [doors_windows_storey__planterbox](ground_truth/doors_windows_storey__planterbox.json) | 48 | 0 | 0 | Supported relationship labels; false-positive control only. |
| [doors_windows_storey__scdf_3](ground_truth/doors_windows_storey__scdf_3.json) | 61 | 0 | 0 | Supported relationship labels; false-positive control only. |
| [doors_windows_storey__scdf_5](ground_truth/doors_windows_storey__scdf_5.json) | 120 | 0 | 0 | Supported relationship labels; false-positive control only. |
| [exit_requirements_v0](ground_truth/exit_requirements_v0.json) | 36 | 3 | 0 | Hold: truncated rule, omitted conditions, 39/123 spaces labelled, no explicit mask. |
| [headroom_condo_c32](ground_truth/headroom_condo_c32.json) | 171 | 1 | 0 | Hold: scope mismatch and eight contradictory door-height explanations; workbook matching is insufficient. |
| [landing_interval_e352__condo](ground_truth/landing_interval_e352__condo.json) | 30 | 0 | 0 | Recorded-count control; no observed exemption defect, but actual landing continuity is not certified. |
| [landing_interval_e352__mall](ground_truth/landing_interval_e352__mall.json) | 61 | 17 | 0 | Hold: 16 parent-total errors and one ignored spiral exemption. |
| [landing_interval_e352__planterbox](ground_truth/landing_interval_e352__planterbox.json) | 2 | 0 | 0 | Tiny recorded-count control, not a useful standalone experiment. |
| [landing_interval_e352__scdf_3](ground_truth/landing_interval_e352__scdf_3.json) | 3 | 0 | 0 | Tiny recorded-count control; no violation examples. |
| [landing_interval_e352__scdf_5](ground_truth/landing_interval_e352__scdf_5.json) | 67 | 6 | 0 | Hold: all six FAILs use parent totals on separated flights. |
| [landing_interval_e352__stair_industrial](ground_truth/landing_interval_e352__stair_industrial.json) | 0 | 0 | 1 | One missing-count/abstention control, not compliance-accuracy evidence. |
| [landing_interval_e352__stair_obos](ground_truth/landing_interval_e352__stair_obos.json) | 14 | 16 | 0 | Hold: eight spiral FAILs; remaining physical counts need adjudication; overlaps v8. |
| [landing_interval_e352__stair_v8](ground_truth/landing_interval_e352__stair_v8.json) | 25 | 42 | 0 | Hold: twelve spiral FAILs; remaining physical counts need adjudication. |
| [planter_box_gfa](ground_truth/planter_box_gfa.json) | 1 | 7 | 0 | Hold: undefined criteria and GFA-inclusion labels presented as violations. |
| [riser_height_e341__condo](ground_truth/riser_height_e341__condo.json) | 30 | 0 | 0 | Property-consistent, mesh sanity check found no contradiction; negative control. |
| [riser_height_e341__mall](ground_truth/riser_height_e341__mall.json) | 77 | 1 | 0 | Supported recorded-height candidate with mesh corroboration where measurable; one failure only. |
| [riser_height_e341__planterbox](ground_truth/riser_height_e341__planterbox.json) | 2 | 0 | 0 | Supported narrow check; tiny negative control. |
| [riser_height_e341__scdf_3](ground_truth/riser_height_e341__scdf_3.json) | 3 | 0 | 0 | Supported narrow check; tiny negative control. |
| [riser_height_e341__scdf_5](ground_truth/riser_height_e341__scdf_5.json) | 73 | 0 | 0 | No property/mesh-height contradiction found; negative control. |
| [riser_height_e341__stair_industrial](ground_truth/riser_height_e341__stair_industrial.json) | 1 | 0 | 0 | One 150 mm example; smoke test only. |
| [riser_height_e341__stair_obos](ground_truth/riser_height_e341__stair_obos.json) | 30 | 0 | 0 | Negative control; every flight ID overlaps v8 training data. |
| [riser_height_e341__stair_v8](ground_truth/riser_height_e341__stair_v8.json) | 66 | 1 | 0 | Supported recorded-height candidate; one 200 mm failure, not a broad reliability test. |
| [slab_thickness__condo](ground_truth/slab_thickness__condo.json) | 183 | 1 | 16 | Hold: all 16 ALERTs overlook explicit thickness; arbitrary bound treats valid thin roofs/transfer slabs as suspect. |
| [slab_thickness__mall](ground_truth/slab_thickness__mall.json) | 62 | 15 | 35 | Hold as invalid legacy: 15 false depth-based FAILs and 23 overlooked thickness records. |
| [slab_thickness__mall_v2](ground_truth/slab_thickness__mall_v2.json) | 100 | 0 | 12 | Supported documented recorded-thickness adjudication; missing-data/false-positive control, not recall. |
| [slab_thickness__planterbox](ground_truth/slab_thickness__planterbox.json) | 25 | 0 | 3 | Review the recorded-versus-derived thickness policy; no FAILs, at most a control. |
| [slab_thickness__scdf_3](ground_truth/slab_thickness__scdf_3.json) | 47 | 0 | 6 | Hold: at least three ALERTs overlook recorded layer quantities; other thickness interpretations need review. |
| [slab_thickness__scdf_5](ground_truth/slab_thickness__scdf_5.json) | 18 | 5 | 41 | Hold: all five FAILs have depth/thickness evidence conflicts. |
| [slab_thickness__stair_industrial](ground_truth/slab_thickness__stair_industrial.json) | 2 | 0 | 0 | Agreeing recorded fields; tiny control under an artificial BIM range. |
| [slab_thickness__stair_obos](ground_truth/slab_thickness__stair_obos.json) | 7 | 4 | 5 | Hold: all four FAILs confuse plan depth with thin landing geometry. |
| [slab_thickness__stair_v8](ground_truth/slab_thickness__stair_v8.json) | 8 | 0 | 18 | Source-consistent recorded-data control; physical thickness not independently certified. |
| [staircase_width_v8](ground_truth/staircase_width_v8.json) | 27 | 22 | 0 | Review/retain as source-backed class-3 candidate: explicit 49/59 subset, but clear-width geometry is not independently certified. |
| [tread_width_e342__condo](ground_truth/tread_width_e342__condo.json) | 29 | 1 | 0 | Supported under the supplied common-stair assumption; regular mesh checks agree where measurable. |
| [tread_width_e342__mall](ground_truth/tread_width_e342__mall.json) | 42 | 36 | 0 | Promising mixed case, but review tapered/spiral measurement and unmeasured short runs before certification. |
| [tread_width_e342__planterbox](ground_truth/tread_width_e342__planterbox.json) | 2 | 0 | 0 | Recorded and regular-step geometry agree; tiny negative control. |
| [tread_width_e342__scdf_3](ground_truth/tread_width_e342__scdf_3.json) | 3 | 0 | 0 | Source-consistent; tiny negative control. |
| [tread_width_e342__scdf_5](ground_truth/tread_width_e342__scdf_5.json) | 73 | 0 | 0 | Recorded and regular-step geometry agree; negative control only. |
| [tread_width_e342__stair_industrial](ground_truth/tread_width_e342__stair_industrial.json) | 1 | 0 | 0 | One 300 mm example against 250 mm; does not test the building-type threshold distinction. |
| [tread_width_e342__stair_obos](ground_truth/tread_width_e342__stair_obos.json) | 0 | 30 | 0 | Review: all-FAIL, eight spiral flights need measurement at the correct line, and all IDs overlap v8. |
| [tread_width_e342__stair_v8](ground_truth/tread_width_e342__stair_v8.json) | 0 | 67 | 0 | Review: all-FAIL and twelve spiral flights; cannot test false-positive discrimination alone. |

### Are These Logical Experiments?

**Yes, for some narrow tasks; no, as an undifferentiated regulatory benchmark.**

- The catalogue has only eight rule families, not 43 independent requirements.
  Several families reuse the same elements, geometry and exporter assumptions.
  Group experiments by rule/model and distinguish repeats from independent
  buildings. Do not pool element labels across families as independent samples.
- Twenty-two cases have zero FAILs. Seventeen are all PASS, two others are all
  FAIL, and one is all ALERT. Those 20 single-label cases admit constant-label
  strategies. Negative controls are useful alongside mixed cases, not as proof
  of violation recall or reasoning ability. The all-ALERT industrial landing
  case principally tests abstention under the current completion policy.
- The OBOS validation model reuses all 30 flight IDs from the v8 training model,
  with identical riser/tread/landing labels for those flights. Its 16 slab IDs
  also overlap v8, but six slab outcomes differ with exported property coverage.
  Treat these as related model versions, not a clean train/validation split.
  The current per-model runner does not itself train on this split, but any
  claimed held-out generalization would be compromised.
- Slab thickness 100-1000 mm and same-storey hosting are chosen BIM-validation
  policies, not general building regulations. A 1200 mm transfer slab or a
  25 mm roof need not be bad engineering. A same-storey mismatch can flag model
  consistency without proving unsafe construction.
- Door OverallWidth is an explicit benchmark proxy, not unobstructed clear
  opening. The 0.5 mm tolerance is sensible but should be stated consistently
  with the prompt: a strict raw `< 900` comparison flags 16 doors, while the
  reference correctly treats nine of these as nominal-900 floating-point noise.
- Riser and tread thresholds match the cited clauses, conditional on use and
  applicability. Building-use/common-stair context is supplied as a benchmark
  assumption, not verified by model names alone. No case exercises the 225 mm
  in-unit branch; the single industrial 300 mm tread passes both 250 and 275 mm
  thresholds, so it cannot detect a wrong industrial threshold.
- E.3.4.3 requires tapered treads to be measured 500 mm from the narrow end.
  Repeated exported TreadLength, TreadLengthAtOffset and TreadLengthAtInnerSide
  values do not establish that geometry. Room-use exceptions in E.2.4 also need
  declared applicability for claims of full regulatory compliance.
- The current landing producer is a property threshold despite its class-2
  label. Validating actual flight/landing connectivity would make it a meaningful
  relational task. Complexity should describe the implemented problem, not
  merely the clause title.
- Completion and full reference agreement do not establish measurement
  correctness. A workbook and two agreeing properties can still repeat one
  exporter assumption. The previous staircase fix resolved scoring scope only;
  it did not independently certify the 49 physical clear-width judgments.

### Recommended Use

1. Keep door width as a simple execution/scoring baseline; use condo and mall
   host-storey checks for recorded relational consistency. Keep their negative
   models as controls rather than reporting each as a separate contribution.
2. Keep mall slab v2 as a declared missing-data/false-positive control, not the
   primary evidence of regulatory detection. Keep the legacy mall case out.
3. Prioritize adjudication of mall tread width as a mixed dimension case and
   staircase clear width as the geometry-intensive case. Condo tread width and
   mall/v8 riser height are useful secondary recorded-data cases, but have just
   one failure each.
4. Hold the twelve marked cases until their owning rule/reference designs are
   corrected. Fix actual-flight scope and spiral applicability together; define
   total slab thickness and source-conflict policy once; restore full exit and
   GFA task definitions; adjudicate headroom applicability and conflicting data.
   Do not automatically regenerate guesses or alter historical scores.
5. Before thesis sweeps, freeze accepted rules, references, provenance and
   applicability. Separate related model versions across any claimed held-out
   evaluation, and report per-case completion plus class-specific performance.