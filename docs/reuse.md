# Reuse boundaries

P04 is an independent project; no P01/P02/P03 source was changed to build it.

- metric_review/llm.py copies the bounded local JSON transport and explicit shared-runtime lease/barrier from rfq-commercial-review-workbench source checkpoint23820f300340df07a5c6f017cfb5c06b05a68607. The offer extraction function was not copied.
- metric_review/server.py adapts that project's standard-library HTTP allowlist/budget/Host/Origin scaffolding. P04 endpoint contracts are independent.
- scripts/browser_check.py uses the previously developed standard-library CDP/WebSocket transport pattern. P04 numerical and provenance assertions are independent.
- Domain, snapshots, scope manifest, metric catalog, arithmetic gold, intent router, receipt core and UI are original P04 work under MIT.
- No enterprise architecture, n8n template code/JSON, model weights or third-party frontend framework is bundled.

Projects do not import one another at runtime. Our separate Ollama clients coordinate only through the documented user-owned shared inference lock. Future changes do not implicitly update other project copies.
