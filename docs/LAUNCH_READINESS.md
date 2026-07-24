# ReceiptAI Launch Readiness

## Completed in the stabilization audit

- Single-pass typed agent intent planning with evidence gating.
- Regression coverage for noisy language, typos, synonyms, multi-item questions, and follow-ups.
- Owner-scoped receipt listing, filtering, editing, deletion, summaries, memory, and agent retrieval.
- Unsafe unscoped legacy query routes retired.
- Validated opaque guest sessions and restored guest receipt listing.
- Login persistence, refresh-token flow, and operating-system secure token storage.
- Persistent agent session identifiers and optional Supabase conversation history.
- Receipt scan size/rate limits and agent rate limits.
- Purchase-date filtering uses the printed purchase date rather than upload date.
- Labeled transaction, receipt, invoice, and order identifiers added to the extraction contract.
- Android/iOS version 1.0.3 build metadata prepared.
- Runtime dependencies pinned and validated in a clean environment.
- GitHub Actions quality gates for backend tests, compilation, mobile lint, and
  TypeScript validation.
- Production startup fails closed for missing secrets, unsafe wildcard CORS,
  non-HTTPS public URLs, or a reused Supabase service key.
- Public `/privacy/` and `/support/` pages are hosted by the backend.
- Offline and deployed release verification is available through
  `backend/verify_release.py`.

## Required Supabase migrations

Run these files in the Supabase SQL editor before the production build is released:

1. `backend/supabase_agent_conversations.sql`
2. `backend/supabase_receipt_identifiers.sql`
3. Confirm all previously documented RLS, receipt item, alias, feedback, and vector migrations are applied.

## External release gates

- Deploy the current backend so `/privacy/`, `/support/`, and `/health/ready`
  are publicly available over HTTPS.
- Confirm `support@receiptai.app` receives mail and is monitored.
- Complete Apple privacy answers and Google Play Data Safety declarations.
- Confirm Apple Developer and Google Play signing/submission credentials.
- Run physical-device smoke tests for camera, PDF upload, microphone, notifications, login refresh, account deletion, and receipt ownership.
- Build and install version 1.0.3 because SecureStore is a native dependency.

Follow `docs/RELEASE_RUNBOOK.md` and retain evidence for every external gate.

## Known non-blocking limitations

- Original receipt image/PDF binaries are not yet retained in Supabase Storage; evidence currently opens the structured saved receipt. Add private Storage retention only with an explicit retention policy.
- Two high-severity npm advisory families remain in Expo/React Native
  build/development tooling. All non-breaking fixes are applied; remediation
  requires an Expo 57 migration. The time-bounded risk acceptance and controls
  are documented in `docs/SECURITY_EXCEPTIONS.md`.
- In-process rate limiting is instance-local. Move limits to Redis or an API gateway when traffic grows beyond a single Railway instance.
