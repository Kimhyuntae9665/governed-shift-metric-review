# Runbook

Use Python3.10+ on Linux, standard library only. Start python3 -m metric_review.server --port 19084. Use localhost browser; remote users can use their own approved SSH localhost forwarding instead of exposing the server. No firewall/VPN/service change is required.

Data files are immutable synthetic snapshots verified by data/freeze_manifest.json. Do not alter a JSON and regenerate a hash merely to bypass stale checks. A new dataset/catalog needs separately reviewed and frozen expected numerical contract. Startup/test/publication excludes private data/metrics.sqlite3 and artifacts.

Sessions are in memory; after an owned app restart select demo identity again. Other-site identity legitimately has no data. Permission403 and expired-auth401 are separate API outcomes. Review status is receipt acknowledgement, not approval of plant operations.

Model proposal is optional; direct metric/shift selection keeps CPU workflow available. Use only existing localhost Ollama with qwen3:4b. Our clients default to the same user-writable ~/.cache/ax-lab/runtime/inference.lock. A documented absolute AX_LAB_INFERENCE_LOCK may override it for every collaborating client; parent must be private user-owned, file regular owner-only. Clone depth has no effect.

An HTTP timeout does NOT prove model server cancellation. The client records inference.lock.blocked before releasing its lease and fails closed across later requests/clones. Do not retry or infer completion merely from a loaded model in /api/ps. Verify completion of the exact owned request using available server/request evidence. Only after confirmed completion, explicitly remove that exact owned barrier and restart the affected application process; never stop an unrelated workload. If barrier write failed, keep the affected process alive because its retained file descriptor is the fallback lease. No automatic recovery is implemented.

Tests use temporary SQLite/data directories and mock model transport. python3 -m unittest discover -s tests -v does not require GPU. Optional development routing evaluation is scripts/evaluate_routing.py --output artifacts/new-routing-evaluation.json; it refuses overwriting that output, serializes model calls and stops after a timeout. It reads evaluator cases but sends only each query and fixed routing definitions to the model.

Browser driver requires an existing sandboxed Chrome CDP endpoint on localhost19085; it opens/closes only its own tab. python3 scripts/browser_check.py --cdp http://127.0.0.1:19085 . It does not install or start a new browser/model. Public screenshots are synthetic UI viewport captures without remote account/path/auth information.

Storage remains intentionally small; no model download, vector database or external benchmark dataset is needed. If the development host has less than3GiB free, pause disk-growing work and report it; never delete unapproved files.
