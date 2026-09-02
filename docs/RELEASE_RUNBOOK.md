# ReceiptAI Production Release Runbook

Use this runbook for every production release. A release is ready only when all
automated checks pass and every external checkbox below has evidence.

## 0. Pass the AI staging gate

Create a separate Railway staging environment from
`backend/staging.env.example`. It enables prompt caching, structured outputs,
strict tools, and the Haiku-to-Sonnet scan cascade while retaining the existing
Sonnet model as the fallback. Run:

```powershell
cd backend
python evaluate_ai_staging.py --offline
python evaluate_ai_staging.py
```

Do not promote the optimization flags to production unless both commands and
the full quality gate pass. The live evaluation uses synthetic data only.

## 1. Configure Railway

Set the backend root directory to `/backend`, then configure:

```env
APP_ENV=production
PUBLIC_BASE_URL=https://web-production-3605f4.up.railway.app
PASSWORD_RESET_REDIRECT_URL=https://web-production-3605f4.up.railway.app/reset-password/
CORS_ALLOWED_ORIGINS=https://web-production-3605f4.up.railway.app
SUPPORT_EMAIL=support@receiptai.app
LOG_JSON=true
```

Also set the real `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, and
`SUPABASE_SERVICE_KEY`. Never copy their values into source control.

Set the Railway health-check path to:

```text
/health/ready
```

Production startup intentionally fails if a required value is missing, a public
URL is not HTTPS, the service and anonymous Supabase keys are identical, or
wildcard CORS is enabled.

## 2. Apply and verify Supabase migrations

Apply every `backend/supabase_*.sql` file in the Supabase SQL Editor. The files
are idempotent and may safely be reapplied.

From a trusted local shell containing the production environment variables:

```powershell
cd backend
python verify_release.py
```

The verifier checks the deployed health endpoints, public privacy/support pages,
required Supabase tables, and receipt identifier columns. It never prints secret
values.

## 3. Run repository quality gates

GitHub Actions runs these checks on pull requests and pushes to `main`. Before a
release, require the `backend` and `mobile` jobs to pass.

Local equivalent:

```powershell
cd backend
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q app main.py verify_release.py
pytest -q
python verify_release.py --offline

cd ..\mobile
npm ci
npm audit --omit=dev --audit-level=critical
npm run lint
npx tsc --noEmit
npx expo-doctor
npx expo export --platform all --output-dir .release-export --clear
```

Review `docs/SECURITY_EXCEPTIONS.md` when assessing non-critical npm audit
findings. A critical advisory or an expired exception blocks release.

## 4. Verify public and store metadata

- [ ] `support@receiptai.app` receives mail and is monitored.
- [ ] `/privacy/`, `/support/`, and `/delete-account/` are publicly reachable over HTTPS.
- [ ] The same privacy URL, support URL, support email, and legal entity details
      are entered in App Store Connect and Google Play Console.
- [ ] Apple privacy answers and Google Play Data Safety answers match
      `docs/PRIVACY_POLICY.md`.
- [ ] Supabase Auth allows the production password-reset redirect URL.
- [ ] Apple and Google signing credentials are active and access is documented.

## 5. Physical-device release smoke test

Install the exact signed production candidate—not Expo Go—on at least one
supported Android device and one supported iPhone.

- [ ] New account, email confirmation if enabled, sign-in, refresh, and sign-out.
- [ ] Forgot-password link opens the hosted page and the new password works.
- [ ] Camera receipt scan, gallery image scan, and multi-page PDF scan.
- [ ] Duplicate receipt detection and receipt correction/deletion.
- [ ] Agent receipt question returns evidence and does not invent purchases.
- [ ] Guest scan isolation and 24-hour retention behavior.
- [ ] Microphone permission, denied-permission behavior, and voice question.
- [ ] Notification permission, denied-permission behavior, and update check.
- [ ] Account deletion removes receipt data and prevents subsequent sign-in.
- [ ] Privacy policy, support website, and support email open from the app.

Record device model, operating-system version, app build/version, tester, date,
and pass/fail evidence in the release ticket.

## 6. Build and release

```powershell
cd mobile
npx eas-cli build --profile production --platform all
```

Install the generated candidates and complete section 5. Submit only the tested
artifacts. Roll out gradually, monitor `/ops/` issues and token usage, and stop
the rollout if authentication, ownership isolation, scanning, or account
deletion regresses.
