# ReceiptAI Privacy Policy

Effective date: July 1, 2026

ReceiptAI processes receipt images and PDFs to extract purchase information such as merchant, date, items, prices, totals, and labeled transaction identifiers. Authenticated data is associated with the user's account. Guest data is associated with an opaque guest session and is configured to expire after 24 hours.

## Data processors

- Supabase provides authentication and database storage.
- Anthropic processes receipt content and selected agent requests needed to extract or answer questions.
- Expo provides application build and update infrastructure.

ReceiptAI does not sell personal data or use receipt data for advertising. Personal receipt answers are scoped to the authenticated account or guest session.

## Device permissions

Camera/photo access is used only when the user selects or captures a receipt. Microphone and speech-recognition access is used only for voice questions. Notification permission is optional.

## Retention and deletion

Authenticated users can delete individual receipts and can request account deletion in the app. Account deletion removes associated receipt data and the authentication account. Guest receipts expire after 24 hours. Conversation history can be cleared from the Agent tab.

## Security

Access and refresh tokens are stored using the operating system's secure credential storage. Backend receipt operations enforce account or guest-session ownership. No system can guarantee absolute security.

## Contact

Privacy and support requests can be sent to `support@receiptai.app`.

Public policy URL: `https://web-production-3605f4.up.railway.app/privacy/`

Public support URL: `https://web-production-3605f4.up.railway.app/support/`
