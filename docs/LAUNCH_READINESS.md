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

## Required Supabase migrations

Run these files in the Supabase SQL editor before the production build is released:

1. `backend/supabase_agent_conversations.sql`
2. `backend/supabase_receipt_identifiers.sql`
3. Confirm all previously documented RLS, receipt item, alias, feedback, and vector migrations are applied.

## External launch blockers

- Publish the privacy policy at a public HTTPS URL.
- Provide a public support URL and support email.
- Complete Apple privacy answers and Google Play Data Safety declarations.
- Confirm Apple Developer and Google Play signing/submission credentials.
- Run physical-device smoke tests for camera, PDF upload, microphone, notifications, login refresh, account deletion, and receipt ownership.
- Build and install version 1.0.3 because SecureStore is a native dependency.

## Known non-blocking limitations

- Original receipt image/PDF binaries are not yet retained in Supabase Storage; evidence currently opens the structured saved receipt. Add private Storage retention only with an explicit retention policy.
- Some npm audit findings remain in Expo/React Native development tooling. Resolving them requires a major Expo SDK upgrade and should not be forced immediately before release.
- In-process rate limiting is instance-local. Move limits to Redis or an API gateway when traffic grows beyond a single Railway instance.
