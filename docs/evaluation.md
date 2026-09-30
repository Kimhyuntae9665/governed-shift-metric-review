# Evaluation manifest

Numerical gold and input snapshot were frozen before implementation/model use at source commit483ca9b250e2a37befcce0d36084e1ab70e04e81. Raw bytes are governed by data/freeze_manifest.json; routing queries were separately frozen before live calls with SHA256557015b4b5d482bf62e834fe0a2dc7be29c4d30772c2d8d693d6242423e67af3. Runtime never reads evaluations/gold.json or routing_cases.json.

## Distinct denominators

- Python unittest74 = 23 frozen numerical gold cases +51 other engineering regressions. The23 are included, not added again.
- Browser11 declared numerical scenarios,97 assertions,16 CPU screenshots; display-boundary checks are not extra benchmark cases. Native AX naming/focus/Escape checks included. See UI document and browser-checks.json.
- Routing8 predeclared development queries =4 intended metric cases +4 policy/authorization guards. The same queries were reused during repair; no independent heldout measurement.
- Live GPU18requests =4 initial multi-field +4 complete-intent enum +4 metric-only with parser bug +4 final metric-only +2 actual UI recordings. Repeated calls on four queries are not18 independent test cases.
- Final four metric proposals match4/4 declared metric IDs; their explicit shifts match after CPU parser repair. The final adapter's four guard cases use no model calls. Fixed keyword baseline matches2/4 metric+scope cases and the guards. This small development comparison is not a general semantic retrieval or factory accuracy claim.
- Two UI recordings each invoked one real optional route, followed by human-confirmation controls and deterministic calculation/review. Published final video uses the second recording to show the below-fold proposal clearly.

## Retained development failures

| Phase | Actual GPU requests | Complete declared metric+scope match |
|---|---:|---:|
| Initial four-field JSON |4|0/4; internally contradictory JSON rejected |
| Complete-intent enum |4|1/4 |
| Metric-only enum before escaped-parser repair |4|2/4 (metric IDs4/4; server scope parser wrong) |
| Final metric-only with explicit scope parser |4|4/4 |

Third-phase parser source accidentally contained doubled backslash regex escapes. Direct Korean/English scope regression caught and fixed this implementation error; it is not attributed to the model.

Final adapter measured request latencies2.163s,0.544s,0.496s,0.522s. Observed GPU peak across development sweeps3584MiB, sampled at0.5s; resource samples and individual raw response fields are preserved. Peak sampling is not a guarantee for all contexts. RAM MemAvailable samples and derived before/after summary are in report files; the lowest sampled available memory was24,932,824KiB (about23.78GiB). UI recording metrics are separate in media provenance.

Ollama0.17.7 actual response fields recorded: load_duration,prompt_eval_count,prompt_eval_duration,eval_count,eval_duration,total_duration,done_reason. No prompt_eval_cached_count assumed. thinking_chars0 in observed constrained output does not verify free-text thinking-off or cache hits. keep_alive30s is not prefix-cache evidence. No new model/download/driver change.

## Reproduce CPU only

python3 -m unittest discover -s tests -v
node --check static/app.js

For live routing use existing localhost Ollama plus documented shared inference lease, then scripts/evaluate_routing.py --output artifacts/fresh-routing.json. The output path must be new. This deliberately reruns the same development queries and must be labeled accordingly.

This suite is a synthetic numerical/engineering validation, not a manufacturing expert benchmark, industry performance study or OEE improvement estimate.

Source display follow-up:97 main browser assertions/16 CPU captures plus4 separate isolated real HTTP source-boundary assertions/1 capture. The frozen project sources and23 numerical gold cases are unchanged. No model request was made; this is display/integrity coverage, not model accuracy.
