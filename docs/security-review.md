# Independent scoped review

An independent gpt-6-astra / low reviewer read the actual P04 domain, API, routing, SQLite review transaction, shared inference lease and final UI. The reviewer did not execute tests, browser actions or GPU requests.

Three Medium findings were fixed before publication:
1. Approval truthiness could accept a string false or integer. Cycle approval now requires exact bool.
2. Filtering a bad latest revision before identity selection could fall back to an older value. Latest eligible identity revision now precedes join-key validation; malformed/new out-of-scope revision quarantines without fallback.
3. Store-local thread locks alone did not serialize separate SQLite connections. BEGIN IMMEDIATE now encloses freshness, existing review lookup, insert and audit; separate-connection regression verifies one creation and one duplicate.

The reviewer re-read each fix, corresponding regressions and saved final UI browser evidence; no residual High/Medium was identified within that scope. Exact public staged/history secret scanning and CI are separate publication checks. This is not a comprehensive penetration test or production security certification.

Demo identities are not trustworthy enterprise authentication. Runtime remains loopback-only with Host/Origin/body budget/static allowlist checks. No production source connector, SQL endpoint, shell execution, source write or arbitrary tool is available. One synthetic authorized site and empty other-site profile demonstrate scope separation.

A bounded follow-up read the final metric-only enum router and explicit scope parser after development failures. The reviewer confirmed authorized/query policy checks precede calls, extra/unknown fields are rejected, no source/gold/tool input is provided, and failures do not silently become keyword success. No additional High/Medium was found. A missing explicit shift proposes combined and still requires human application. This follow-up also did not execute model/tests.
