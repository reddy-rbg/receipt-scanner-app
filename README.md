# ReceiptAI

ReceiptAI is a monorepo for the receipt scanner mobile app and its FastAPI backend.

## Repository Layout

```text
ReceiptScanner/
  mobile/    Expo / React Native app
  backend/   FastAPI API, Supabase, Claude scanning, AI agent
```

## Mobile App

From the repository root:

```powershell
cd mobile
```

Install and run:

```powershell
npm install
npx expo start --lan -c
```

The mobile app should only use public/frontend-safe environment variables. Never put Supabase service role keys in `mobile/`.

## Backend

From the repository root:

```powershell
cd backend
```

Run locally:

```powershell
.\run-local-backend.ps1
```

Backend environment variables belong in backend-only environments:

```env
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_SERVICE_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

Do not commit `.env`.

## Deployment

Railway should deploy from:

```text
backend/
```

Expo/EAS should build from:

```text
mobile/
```

Production backend:

```text
https://web-production-3605f4.up.railway.app
```

Health check:

```text
https://web-production-3605f4.up.railway.app/agent-health
```

## Agent Architecture

The backend separates the agent into focused modules:

```text
backend/app/services/agent.py                 orchestrator
backend/app/services/agent_architecture.py    evidence gate and answer contract
backend/app/services/agent_general.py         general advice mode
backend/app/services/agent_analytics.py       analytics routing
backend/app/services/receipt_intelligence.py  deterministic receipt Q&A
```

Receipt fact answers must be backed by receipt evidence. General advice is allowed, but it must not claim purchase facts unless receipt evidence was retrieved.
