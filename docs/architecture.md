# Architecture

Runtime reads four frozen JSON files: MES count export, shift-time export, explicit expected-scope manifest, approved metric catalog. data/freeze_manifest.json verifies SHA256 bytes. evaluations/gold.json and routing_cases.json are evaluator-only; the HTTP server/domain/router never loads them.

Authentication is server-created demonstration identity/session, not SSO. Authorized site filtering precedes metric source selection and optional model routing. Fixed dataset, business date, cutoff, metric ID and shift scope selectors are validated; no arbitrary SQL or shell endpoint exists.

The deterministic domain selects latest eligible record revisions after explicit source-record issued_at cutoff, quarantines same-revision conflict without old fallback, checks exact join keys and scope completeness, converts approved s/min units, and computes Fraction numerator/denominator sums. Missing inputs and zero denominators remain undefined. Counts and time completeness are independent, so availability may survive missing good counts while OEE is unavailable.

SQLite persists arithmetic receipts and audit events. Fingerprint includes snapshot hash, exact selectors and rule version. Review confirmation is an acknowledgement of this receipt, not factory-performance certification. BEGIN IMMEDIATE encloses freshness/read/idempotence/write across separate Store connections. Runtime database files are private and excluded from Git.

Optional model is a metric-name classifier. Its finite JSON enum is decoded on the server; explicit shift scope is a deterministic parser. Human acknowledgement applies the proposal without altering dataset/calendar date/cutoff; a separate button invokes exact arithmetic. No source rows, evaluation gold, join keys, SQL or tools are sent to Qwen.

Private shared advisory lease serializes our local clients across projects. HTTP timeout latches a durable barrier because server cancellation cannot be assumed. This is Linux single-user process coordination, not a distributed production lock.
