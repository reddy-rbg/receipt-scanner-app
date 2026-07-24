<div align="center">

<img src="./assets/readme/receiptai-flow.svg" alt="ReceiptAI animated product flow" width="100%" />

# ReceiptAI

### A receipt scanner and shopping intelligence agent that answers from real purchase evidence.

<p>
  <img alt="Expo" src="https://img.shields.io/badge/Mobile-Expo-7C6AFF?style=for-the-badge&logo=expo&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/API-FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
  <img alt="Supabase" src="https://img.shields.io/badge/Data-Supabase-3FCF8E?style=for-the-badge&logo=supabase&logoColor=white" />
  <img alt="Railway" src="https://img.shields.io/badge/Deploy-Railway-111827?style=for-the-badge&logo=railway&logoColor=white" />
  <img alt="Hybrid AI" src="https://img.shields.io/badge/AI-Hybrid%20Parser%20%2B%20Claude-8C7CFF?style=for-the-badge" />
  <img alt="RBAC" src="https://img.shields.io/badge/Security-RBAC%20Scoped-62E6C8?style=for-the-badge" />
</p>

<p>
  <b>Scan receipts</b> -> <b>optimize extraction cost</b> -> <b>save purchase memory</b> -> <b>ask the AI Agent</b> -> <b>get evidence-backed answers</b>
</p>

</div>

---

## Why ReceiptAI Exists

ReceiptAI turns messy receipts into a personal shopping memory. It helps answer practical questions like:

- What did I buy from Walmart?
- Which store gives me the best price for rice, milk, or vegetables?
- How much did I spend this month?
- Did I actually buy this item before?
- What should I buy next based on my receipt history?

The important rule is simple:

```text
No receipt evidence -> no purchase claim.
```

## Product Highlights

| Capability | What it means |
| --- | --- |
| Receipt scanning | Upload receipt images or PDFs and extract structured purchase data |
| Hybrid PDF extraction | Digital table PDFs are parsed deterministically first; weak parses fall back to Claude Vision |
| Purchase memory | Store receipts, line items, totals, stores, dates, quantities, and guest sessions |
| Discounts and savings | Discounts are preserved as receipt evidence and surfaced in receipts, memory, and reports |
| AI Agent | Ask about prices, stores, item history, spending, comparisons, and shopping plans |
| Evidence gate | Receipt facts must come from saved receipt evidence, not model guesses |
| General advice | Food, shopping, and savings advice is supported without pretending it came from receipts |
| Secure operations | Backend-enforced roles, customer scopes, receipt assignments, support grants, and audit logs |
| Operations console | Separate role-aware web dashboard for administrators, support staff, auditors, receipt editors, and token monitoring |
| Token usage dashboard | Day/week/month/year AI token utilization by model, operation, file type, and recent scan events |
| Account recovery | Hosted password-reset flow that returns users safely to the deployed application |
| Mobile first | Built for Expo Go, local LAN testing, and future app-store builds |

## Architecture At A Glance

<img src="./assets/readme/receiptai-architecture.svg" alt="ReceiptAI production architecture diagram" width="100%" />

The architecture is split into four clean layers:

1. **Surfaces** — Expo mobile app for customers and the operations console for admins/support.
2. **Secure backend** — FastAPI handles auth, RBAC, scan routing, and the Agent.
3. **Extraction intelligence** — deterministic PDF/table parsing first, Claude fallback only when needed.
4. **Purchase memory** — Supabase stores receipts, item rows, RBAC state, and AI token usage.

## Repository Layout

```text
ReceiptScanner/
  mobile/                 Expo / React Native app
  backend/                FastAPI backend
    app/
      routes/             Auth, receipt, query, and agent routes
      services/           Scanning, storage, retrieval, and agent logic
    ops_dashboard/        Role-aware operations web console
    reset_password/       Hosted password-recovery page
    main.py               FastAPI entrypoint
    requirements.txt      Python dependencies
    Procfile              Railway start command
    nixpacks.toml         Railway build config
    supabase_*.sql        Supabase migrations
  docs/RBAC.md            Access-control roles, scopes, and deployment guide
  assets/readme/          README visuals
```

## Hybrid Scanning and Token Optimization

ReceiptAI now uses a production-safe hybrid extraction strategy:

```text
Upload PDF/image
  -> detect file type
  -> try deterministic extraction for digital text/table PDFs
  -> validate rows, prices, pages, vendor, and confidence
  -> save directly only when the parse is strong
  -> fall back to Claude Vision when the parse looks incomplete
  -> store receipt evidence, structured rows, savings/discounts, and token metrics
```

This keeps costs low without silently trusting weak table extraction.

| Document type | First path | Fallback path |
| --- | --- | --- |
| Digital price list / table PDF | Backend text/table parser | Claude Vision if page or row confidence is low |
| Normal photographed receipt | Claude Vision scan | Validation error if unreadable |
| Multi-page receipt photos | Combined page scan | Validation and duplicate checks |
| Duplicate upload | Existing receipt by hash | No extra model call |

The parser records a `parse_audit` with page count, rows per page, marker count,
warnings, confidence, and whether the document was accepted without AI. Token
usage events are logged separately so the operations console can show which
files and models are driving cost.

## Agent Brain

The Agent is structured so it can feel conversational while staying grounded.

Each chat turn now creates one typed `IntentPlan` from the raw question. The
same plan is passed through retrieval and answer generation, so execution does
not reinterpret or rewrite the user's intent. Receipt data uses short TTL
caches with mutation invalidation, and blocking model/database work runs off
the FastAPI event loop. The returned `rag_trace.workflow` includes stage
timings and the exact intent plan used for the answer.

| Module | Responsibility |
| --- | --- |
| `backend/app/services/agent.py` | Main orchestrator |
| `backend/app/services/agent_contracts.py` | Typed intent plan shared by planning and execution |
| `backend/app/services/agent_architecture.py` | Evidence gate, answer contract, trace metadata |
| `backend/app/services/agent_general.py` | General shopping and food advice mode |
| `backend/app/services/agent_analytics.py` | Spending, summary, and trend routing |
| `backend/app/services/receipt_intelligence.py` | Deterministic receipt Q&A and item matching |

Receipt fact answers are allowed only when matching receipt evidence is found.

Production retrieval counts unique purchase occasions rather than duplicated
evidence rows. Purchase-history answers therefore align their headline count,
listed events, and receipt evidence. The current single-pass orchestration also
avoids repeated interpretation and unnecessary response waits.

## Memory and Savings Intelligence

The Memory tab is designed to be useful even without asking the Agent. It tracks:

- item-level price memory and repeat purchase history;
- spending, category, and monthly trends;
- discounts and `total_savings` captured from receipts;
- store-wise savings in the Spending view;
- shopping opportunities based on observed lowest/usual/good-deal prices.

Discount lines stay grounded in the receipt evidence. If a receipt has a coupon,
markdown, reward, or negative line item, the backend preserves that discount and
the mobile app can surface it in receipt detail and monthly memory.

## Production Access Control

ReceiptAI uses backend-enforced role-based access control (RBAC). The mobile app
and operations console may hide unavailable controls, but the FastAPI backend is
always the security boundary.

| Role | Production access |
| --- | --- |
| `platform_admin` | Full platform administration, customer data, roles, settings, and audit |
| `master_user` | Cross-customer receipts, reports, analytics, support approval, and audit |
| `customer_owner` | Members, receipts, analytics, corrections, and support approval for one customer |
| `customer_user` | Only receipts and purchase history owned by that user |
| `support_agent` | No customer data by default; approved, scoped, time-limited access only |
| `receipt_editor` | Correct assigned customers or receipts; cannot delete receipts or manage users |
| `auditor` | Read-only access to assigned receipt and audit scopes |
| `service_account` | Explicitly scoped scan/reprocessing access for trusted backend jobs |

Cross-user receipt access requires a global role, customer role, active support
grant, or active receipt assignment. Unknown and unauthorized receipts return the
same not-found response so the API does not reveal another customer's data.

### Operations Console

The deployed backend serves the separate operations console at:

```text
https://web-production-3605f4.up.railway.app/ops/
```

Authorized users can:

- Create and activate/deactivate operator accounts.
- Assign customer-scoped roles and inspect effective permissions.
- Search authorized receipts and correct receipt headers or line items.
- Assign one receipt, selected receipts, a date range, month, year, or all
  authorized receipts to a Receipt Editor.
- Create and revoke time-limited support access.
- Monitor AI token usage by day, week, month, year, model, operation, file type,
  and recent scan events.
- Review security-sensitive activity in the audit log.

See [`docs/RBAC.md`](docs/RBAC.md) for the complete role matrix, deployment
steps, support workflow, and launch verification checklist.

### Password Recovery

Password recovery is hosted by the production backend at:

```text
https://web-production-3605f4.up.railway.app/reset-password/
```

Set `PASSWORD_RESET_REDIRECT_URL` to this deployed route and add the same URL to
the Supabase Auth redirect allowlist.

## Run Locally

### Mobile App

```powershell
cd mobile
npm install
npx expo start --lan -c
```

Use `--lan` when testing with Expo Go on a phone connected to the same Wi-Fi network.

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

Local API:

```text
http://127.0.0.1:8000
```

FastAPI docs:

```text
http://127.0.0.1:8000/docs
```

## Environment Variables

Backend-only secrets belong in Railway or `backend/.env`. Never put service keys in `mobile/`.

```env
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_KEY=
ANTHROPIC_API_KEY=
GOOGLE_SEARCH_API_KEY=
GOOGLE_SEARCH_ENGINE_ID=
RBAC_BOOTSTRAP_ADMIN_USER_IDS=
PASSWORD_RESET_REDIRECT_URL=https://web-production-3605f4.up.railway.app/reset-password/
MAX_PDF_SCAN_PAGES=16
MAX_SCAN_IMAGE_PAGES=8
MAX_SCAN_OUTPUT_TOKENS=16000
MAX_SCAN_IMAGE_LONG_EDGE=1800
SCAN_IMAGE_JPEG_QUALITY=82
AI_INPUT_COST_PER_MILLION_TOKENS=
AI_OUTPUT_COST_PER_MILLION_TOKENS=
LOG_LEVEL=INFO
LOG_JSON=false
SLOW_REQUEST_MS=3000
LOG_CLIENT_ERROR_EVENTS=false
```

Important:

- `SUPABASE_SERVICE_KEY` is backend-only.
- `RBAC_BOOTSTRAP_ADMIN_USER_IDS` is an optional comma-separated list of
  Supabase user UUIDs used only to bootstrap the first platform administrator.
- `PASSWORD_RESET_REDIRECT_URL` must also be allowed in Supabase Auth settings.
- `MAX_PDF_SCAN_PAGES`, `MAX_SCAN_IMAGE_PAGES`, and `MAX_SCAN_OUTPUT_TOKENS`
  control large scan limits and should be adjusted carefully.
- `MAX_SCAN_IMAGE_LONG_EDGE` and `SCAN_IMAGE_JPEG_QUALITY` control the
  photo/gallery scan optimizer. Receipt photos are cropped/enhanced, capped to
  this long edge, and logged as `image_preprocess_v1` in token usage metadata.
- `AI_INPUT_COST_PER_MILLION_TOKENS` and `AI_OUTPUT_COST_PER_MILLION_TOKENS`
  are optional; when set, the operations console estimates AI cost in USD.
- `LOG_LEVEL` and `LOG_JSON` control backend log verbosity and whether Railway
  logs are human-readable or JSON formatted.
- `SLOW_REQUEST_MS` controls when a backend request becomes a warning in the
  operations Issues dashboard. `LOG_CLIENT_ERROR_EVENTS=true` also records 4xx
  client/API responses as warnings when you need deeper debugging.
- Mobile code should use only public/frontend-safe variables.
- Do not commit `.env` files.

## Supabase Setup

Run these migrations once in the Supabase SQL Editor:

```text
backend/supabase_receipt_items.sql
backend/supabase_item_aliases.sql
backend/supabase_agent_conversations.sql
backend/supabase_receipt_identifiers.sql
backend/supabase_rbac.sql
backend/supabase_token_usage.sql
backend/supabase_error_events.sql
```

These create:

- `receipt_items` for fast structured item retrieval.
- `receipt_item_aliases` for taught meanings such as `goat = mutton`.
- RBAC customers, role assignments, support grants, receipt assignments, and
  audit events for scoped operations access.
- `ai_token_usage` for the operations token dashboard.
- `app_error_events` for the operations Issues dashboard, including backend
  errors, warnings, slow requests, request IDs, source, metadata, and stack
  context where available.

## API Highlights

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/auth/signup` | Create account |
| `POST` | `/auth/login` | Sign in |
| `POST` | `/scan-receipt` | Scan authenticated receipt |
| `POST` | `/guest/scan-receipt` | Scan guest receipt |
| `GET` | `/receipts` | List receipts |
| `GET` | `/summary` | Spending summary |
| `POST` | `/agent` | Ask the AI Agent |
| `POST` | `/agent/chat` | Chat-style Agent request |
| `GET` | `/agent-health` | Verify deployed backend build and config |
| `GET` | `/rbac/me` | Return the current operator's roles, scopes, and permissions |
| `POST` | `/rbac/users` | Create an operator account and initial role |
| `POST` | `/rbac/receipt-assignments/bulk` | Assign filtered receipt work to a Receipt Editor |
| `GET` | `/rbac/audit` | Read authorized security audit events |
| `GET` | `/rbac/token-usage` | Read authorized AI token utilization dashboard data |
| `GET` | `/rbac/error-events` | Read authorized backend Issues dashboard data |

## Deployment

### Railway Backend

Railway should point to this repository:

```text
reddy-rbg/receipt-scanner-app
```

Use these Railway source settings:

```text
Branch: main
Root Directory: /backend
```

Health check:

```text
https://web-production-3605f4.up.railway.app/health/ready
```

The production process fails startup when required secrets are missing, public
URLs are not HTTPS, wildcard CORS is enabled, or the Supabase service key is
not distinct from the anonymous key. See
[`docs/RELEASE_RUNBOOK.md`](docs/RELEASE_RUNBOOK.md) for the complete
deployment, migration verification, device smoke-test, and store-release gate.

After deploying backend changes, open `/ops/` with an authorized operator
account and verify:

- receipt scanning still saves normal receipts;
- digital table PDFs show optimized parser usage in Token usage;
- low-confidence PDFs fall back to Claude instead of silently saving weak data;
- `/rbac/token-usage?period=month` returns dashboard data after the SQL migration.

### Expo App

Expo/EAS should build from:

```text
mobile/
```

## Quality Gates

The backend includes hard-scenario tests for typo-heavy questions, missing punctuation, item matching, store matching, spending summaries, and evidence gating.

```powershell
cd backend
python test_receipt_intelligence_v2.py
python test_agent_hard_scenarios.py
python test_agent_quality_gate.py
python test_rbac_authorization.py
python test_ops_dashboard.py
python test_password_reset.py
```

Focused checks used for the current production documentation:

```powershell
cd backend
python -m py_compile app/services/claude.py app/services/token_usage.py app/routes/receipts.py app/routes/rbac.py
python test_receipt_intelligence_v2.py
python test_ops_dashboard.py
```

Mobile type check:

```powershell
cd mobile
npx tsc --noEmit
```

## Git Workflow

Commit from the monorepo root using repository-relative paths:

```powershell
git status
git add README.md assets/readme backend mobile
git commit -m "Describe your change"
git push
```

## License

Copyright (c) 2026 Ajay Kumar Reddy Poreddy. All rights reserved.

This repository and the ReceiptAI project are proprietary and confidential. No permission is granted to copy, clone, fork, distribute, modify, reuse, commercialize, or create derivative works from this codebase, design, architecture, workflows, or product concept without prior written permission from the owner. Patent and copyright protections may apply.
