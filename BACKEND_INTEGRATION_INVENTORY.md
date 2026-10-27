# FinGuard backend integration inventory

Inspected from the Django source under `fintech/`. URL prefix is `/api/v1/` unless a path below says otherwise. Default REST authentication is JWT Bearer; default permission is authenticated. DRF errors use `detail` and/or field keyed validation arrays. No frontend currently exists in the workspace.

## Backend structure and configuration

- Django apps: `users`, `core`, `wallets`, `payments`, `fraud`.
- Project routes: `fintech/fintech/urls.py`; REST Framework/SimpleJWT and Channels configured in `fintech/fintech/settings.py`.
- Roles are Django groups, not a user `role` field: ordinary customer permissions derive from authentication; `FRAUD_ANALYST` has `wallets.review_transaction`; `FRAUD_ADMIN` additionally has `fraud.assign_case`. No user-profile or role-discovery endpoint exists.
- Access JWT lifetime is 30 minutes. Refresh JWT lifetime is 7 days, rotated and blacklisted after rotation, stored only in HttpOnly `refresh_token` cookie scoped to `/api/v1/auth/`. Access JWT is returned in JSON and sent as `Authorization: Bearer …`. Cookie refresh requests require credentials. Refresh endpoint is `/api/v1/auth/token/refresh/`; logout requires access JWT. SimpleJWT generic routes `/api/token/` and `/api/token/refresh/` are also mounted, but frontend should use the custom cookie-based refresh contract.
- CORS middleware/settings are absent. `FRONTEND_URL` defaults through environment (example `http://localhost:5173`) for Google OAuth redirect. Cross-origin cookie refresh needs backend CORS support and an explicit trusted origin if frontend and API use different origins.
- No OpenAPI/Swagger configuration or API schema was found. No server-side dashboard summary, current-user profile, password reset, mark-read notifications, support tickets, audit-log API, wallet freeze API, or beneficiary lookup API exists.
- Backend does not expose a Daraja callback to the browser; callback is provider-to-server only. Frontend must only call the authenticated STK initiation and payment status/list endpoints.

## Endpoint inventory

| Feature | Endpoint and method | Auth / permissions | Request | Response and errors | Frontend use |
|---|---|---|---|---|---|
| Health | `GET /api/v1/health/` | Public (`AllowAny`) | — | Health payload defined by `HealthCheckView`; non-2xx server errors | Connection status |
| Register | `POST /api/v1/auth/register/` | Public; auth throttle 10/min | `{username,email,password}` | `201 {user:{id,username,email},access}` and HttpOnly refresh cookie; `400` field errors; `429` throttle | Registration |
| Login | `POST /api/v1/auth/login/` | Public; auth throttle | `{identifier,password}` | `200 {user,access}` plus cookie, or `{mfa_required:true,mfa_token}`; invalid credentials `400 {detail}`; lockout/throttle `429` | Login and MFA handoff |
| MFA verify | `POST /api/v1/auth/mfa/verify/` | Public; auth throttle | `{mfa_token,otp_code}` | `200 {user,access}` + cookie; invalid/expired challenge `401 {detail}`; validation `400` | OTP challenge |
| Google token auth | `POST /api/v1/auth/google/` | Public; auth throttle | `{id_token}` | `200/201 {user,access}` + cookie; invalid token `401`; verified-email conflict `409` | Optional Google token sign-in |
| Google OAuth browser flow | `GET /accounts/google/login/` then redirect `/api/v1/auth/google/finish/`; `POST /api/v1/auth/google/exchange/` | OAuth flow public; exchange public/throttled | exchange `{code}` | Redirect to frontend `/auth/callback?code=…`; exchange returns `{user,access}` + cookie; invalid/expired code `401`, missing `400` | Optional OAuth callback. Handoff code is single-use, 60 seconds |
| Refresh | `POST /api/v1/auth/token/refresh/` | Public, refresh cookie required | Empty JSON/body | `{access}` and rotated HttpOnly cookie; absent/invalid refresh `401 {detail}` | Single-flight session refresh |
| Logout | `POST /api/v1/auth/logout/` | Bearer JWT | Empty body; cookie sent | `200 {detail}` and refresh cookie deletion; unauthenticated `401` | Logout |
| Wallet | `GET /api/v1/wallet/` | Bearer JWT; own wallet ensured | — | `{account_number,balance,currency,is_frozen}`; auth/server errors | Wallet card and status |
| Beneficiaries | `GET/POST /api/v1/wallet/beneficiaries/` | Bearer JWT; owner-scoped; throttle 20/min | create `{nickname,account_number}` | list is an unpaginated array of `{id,nickname,account_number,account_name,created_at}`; create `201` object; validation `400` | Beneficiary management and transfer recipient |
| Beneficiary detail | `GET/PATCH/DELETE /api/v1/wallet/beneficiaries/{uuid}/` | Bearer JWT; owner-scoped | PATCH `{nickname}` only | Object, update object, or `204`; invalid/foreign id `404`; validation `400` | Edit nickname or remove saved beneficiary |
| Transfer | `POST /api/v1/wallet/transfer/` | Bearer JWT; own beneficiary; throttle 10/min | Header `Idempotency-Key` (required, max 64); `{beneficiary:<uuid>,amount,description?}` | `201` new or `200` replay `{transaction,balance}`; `202` review pending with `detail`; missing key/body `400`; insufficient/blocked/frozen/limit errors `403`; rejected transfers can include reference/code. Serializer validates minimum and decimal precision. | Review then submit transfer; preserve key for same logical retry; reconcile uncertain outcome via transaction history/status |
| Transactions | `GET /api/v1/wallet/transactions/` | Bearer JWT; own wallet scoping | optional `direction=sent|received`, `status`, `type`, `from=YYYY-MM-DD`, `to=YYYY-MM-DD`, `page`, `page_size` (20 default, max 100) | DRF page `{count,next,previous,results}`; each result `{id,reference,type,direction,counterparty:{account_number,name}|null,amount,currency,status,description,created_at}`; invalid filters `400` | History, filters, pagination; received side only shows completed credits |
| Transaction detail | `GET /api/v1/wallet/transactions/{uuid}/` | Bearer JWT; participant-scoped | — | Same transaction representation; foreign/missing id `404` | Detail and uncertain transfer reconciliation |
| M-Pesa STK push | `POST /api/v1/payments/mpesa/stk/` | Bearer JWT; own active wallet; throttle 5/min | Header `Idempotency-Key` (8–64 alphanumeric, `_`, `-`); `{amount,phone_number}` | `202` new or `200` replay: `{id,status,amount,currency,phone_number,mpesa_receipt_number,result_desc,created_at,updated_at}`; `400` validation/key/no wallet; `403` frozen; `422` changed request for reused key; `429` throttle | Initiate deposit; use server status, do not represent timeout as failure |
| M-Pesa payments | `GET /api/v1/payments/mpesa/payments/`, `GET …/{uuid}/` | Bearer JWT; user-scoped | Detail id; list has no custom pagination/filter | List of payment representations; detail same; foreign/missing id `404`. Statuses include `pending`, `processing`, `successful`, `failed`, `cancelled`, `timed_out`, `needs_review`. Phone is masked. | Payment history and explicit status refresh |
| Provider callback | `POST /api/v1/payments/mpesa/callback/{secret}/` | Provider callback secret + optional IP allowlist; not user-facing | Daraja payload | `{ResultCode,ResultDesc}`; malformed `400`; wrong secret/IP `404` | No frontend action |
| Fraud cases | `GET /api/v1/fraud/cases/` | Bearer JWT + `wallets.review_transaction` permission | filters `status,kind,priority,category,type,from,to,search`; page/page_size | DRF page of `{reference,kind,status,priority,created_at,resolved_at,transaction:{reference,type,amount,currency,status,created_at},risk:{score,category,recommended_action,triggered_rules}}`; validation `400`, permission `403` | Analyst case queue |
| Fraud case detail | `GET /api/v1/fraud/cases/{reference}/` | Fraud analyst permission | — | Case list fields plus `reasons`, `reviews`, `recent_history`; foreign/missing `404`, forbidden `403` | Analyst investigation |
| Fraud review | `POST /api/v1/fraud/cases/{reference}/review/` | Fraud analyst permission | `{decision:"approve"|"reject",reason}` (5–500 chars) | Updated case detail; validation `400`, permission `403`, service conflict/status errors include `{detail,code}` | Confirmed analyst decision |
| Fraud analytics | `GET /api/v1/fraud/analytics/?days=30` | Fraud analyst permission | days 1–90 | `{days,cases_by_status,assessments_by_category}`; bad days `400`; forbidden `403` | Analyst overview |
| Fraud alerts recovery | `GET /api/v1/fraud/alerts/?after=<event id>` | Fraud analyst permission | cursor `after` (default 0) | `{events:[{id,type,payload,at}]}`, max 100; bad cursor `400` | Missed analyst notifications; dedupe by id |
| Customer notifications recovery | `GET /api/v1/fraud/notifications/?after=<event id>` | Bearer JWT, own-user scoped | cursor `after` | Same event list; no mark-read/filter endpoint | Customer notification feed and reconnect recovery |
| WebSocket ticket | `POST /api/v1/fraud/ws-ticket/` | Bearer JWT | Empty body | `{ticket,expires_in:30}` | Obtain short-lived one-use ticket before socket connection |
| Customer socket | `ws(s)://<host>/ws/transactions/?ticket=<ticket>` | Ticket middleware; ticket one-use; authenticated user bound to own customer group | Server-push only | `{id,type,payload,at}` | Wallet/transaction/customer event notices; reconcile via REST |
| Analyst socket | `ws(s)://<host>/ws/fraud/?ticket=<ticket>` | One-use ticket and `wallets.review_transaction` permission | Server-push only | Same event shape | Fraud alert updates; reconnect with backoff and recover through alerts REST |

## Integration gaps and constraints

- No CORS configuration is present. If frontend is served on a different origin, cookie-based refresh requires backend CORS configuration (`credentials` and exact frontend origin) and compatible cookie security settings. This frontend cannot enable that from browser code.
- No current-user endpoint means the client only knows user identity from auth responses until the next login; no role/group listing exists. Analyst UI can be reached explicitly or exposed based on a `403` response, but server permission remains authoritative.
- No server dashboard aggregation endpoint: use wallet + bounded recent transaction page + unread/event recovery; avoid fake stats.
- Customer notifications are an event recovery stream; no read/unread semantics. The audit log model has no REST endpoint.
- No password reset, ticket/support, freeze/unfreeze wallet, transfer cancellation, or payment cancellation/status-query endpoint beyond GET payment detail.
- STK payment status list has no pagination parameters wired. UI should display returned records and avoid fabricating pages.
- Errors use standard DRF JSON field errors and `detail`; app-specific conflicts may additionally return `code` and `reference`. `401`, `403`, `404`, `409`, `422`, `429`, and `5xx` should retain status and a normalized message.
- WebSocket uses ticket query parameter, not JWT. Socket host/origin allowlisting depends on `ALLOWED_HOSTS`; ticket TTL 30 seconds and one-time use.
