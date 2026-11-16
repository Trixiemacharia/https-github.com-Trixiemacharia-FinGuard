# FinGuard enhancement implementation map

## Existing architecture

- Frontend: React + Vite, React Router, local CSS, Lucide icons; API requests and cookie-backed JWT refresh live in `frontend/src/api/`.
- Authentication: custom Django user with email uniqueness, JWT access tokens, HttpOnly refresh cookie, optional MFA, Google sign-in, and DRF serializers in `fintech/apps/users/`.
- Wallet: `Wallet`, `Beneficiary`, and `Transaction` models in `fintech/apps/wallets/`; ledger/service layer owns balance changes and checks frozen wallets and transaction risk.
- Payments: Daraja STK initiation and callback handling in `fintech/apps/payments/`; callback confirmation, idempotency, and payment status models already exist.
- Fraud/security: fraud review and event notifications in `fintech/apps/fraud/`; Redis/Celery configuration in project settings and `fintech/fintech/celery.py`.
- Routes: current frontend root is the authenticated overview; API prefix is `/api/v1/`. Existing endpoint inventory is in `BACKEND_INTEGRATION_INVENTORY.md`.

## Existing features to preserve

- Login, registration, MFA, Google auth, token refresh/logout.
- Wallet balance, internal transfers, transaction history, beneficiary management, ledger, frozen-wallet transfer checks.
- M-Pesa STK push, provider callback, payment history/status, idempotency.
- Fraud review, customer notifications, and live transaction events.

## Missing features identified

- Public landing page, persistent English/Kiswahili translations, and combined sign-in/create-account presentation.
- Onboarding profile, phone number collection, selfie upload, personal details, application review/approval.
- Customer-facing wallet freeze/emergency controls.
- Savings, categorized insights, forecasts, calendar, recurring detection, financial reports, and tool-grounded assistant APIs.

## Change sequence

1. Add the public landing and authentication presentation while preserving current auth API calls and dashboard pages.
2. Add onboarding records and endpoints using the existing user model and authentication conventions.
3. Add customer security controls around existing wallet freeze enforcement.
4. Extend financial features incrementally against the existing ledger and transaction data; do not fabricate provider or financial data.

## Implemented in this enhancement pass

- Public English/Kiswahili landing page with persisted selector, banking hero imagery, six feature cards, and responsive `HOW IT WORKS` sequence.
- Shared sign-in/create-account presentation; existing JWT/MFA registration and sign-in calls are reused.
- New-user onboarding profile and ordered phone/email verification, photo, details and account review API; automatic approval requires verified contact details, a submitted photograph, valid details and a configured clear risk screening result. Flagged or unconfigured screening stays pending for staff review.
- Wallet freeze/unfreeze endpoint, persisted security event, and existing customer outbox notification. Wallet and payment initiation remains server-enforced.
- Current-user endpoint restores the username in the dashboard after refresh.
- Insights, savings, recurring detection, financial calendar, monthly reports, AI assistant, emergency session revocation, and configurable transaction approvals remain follow-on work; these APIs were absent during the audit.

## Integration constraints

- Keep money movement in existing wallet/payment services and ledger.
- Keep Daraja callbacks server-to-server and only credit on validated provider callbacks.
- Expose unsupported channels as unavailable integration boundaries.
- Scope all new financial data to the authenticated owner.
- Avoid claiming biometric/ID verification; selfie upload is only a submitted photograph.
