# Case study: LeadFlow AI (portfolio demo)

**Problem.** Small B2B teams lose hours every week reading inbound leads, deciding which deserve a call, copying them into a CRM sheet and drafting first replies. Hot leads wait behind spam and job applications.

**Approach.** Cheap deterministic checks run first: validation, phone normalization, deduplication by email and message hash, and spam heuristics. Only leads that survive them reach an LLM, which must return a schema-validated classification. Invalid output is retried with exponential backoff and then dead-lettered, never dropped. Routing decisions (hot, HR, archive) are plain, tested code, not prompt text.

**Architecture.** Ports and adapters in typed Python: a FastAPI webhook and a CLI feed one pipeline. `LLMProvider` (Anthropic, OpenAI, offline fake), `CrmSink` (SQLite, CSV, Google Sheets) and `Notifier` (console, Slack) can each be swapped. An importable n8n workflow connects a form to the API, Sheets and Slack.

**Result (offline demo, not a client project).** I ran it on 40 fictional leads with a deterministic fake model and deliberate fault injection: 4 invalid, 4 duplicates and 4 spam leads were stopped before any model call, 27 were classified, 1 was dead-lettered, and 6 were flagged hot. The run took 1.0 s, most of it injected backoff. 45 automated tests pass.

**What I'd do in production.** Measure classification accuracy on labelled real leads before trusting the model. Move state to Postgres and add a replay tool for the dead-letter queue. Add PII retention rules, auth on the webhook, and tracing with cost per lead.
