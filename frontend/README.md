# FinGuard frontend

Responsive React/Vite frontend for the Django FinGuard API in `../fintech`. It uses JavaScript and standard CSS. Financial balances and statuses are always read from backend responses; the interface does not simulate successful payments or transfers.

## Requirements and setup

- Node.js 20 or newer and npm.
- Start the Django backend separately (default API URL: `http://localhost:8000/api/v1`).
- Copy `.env.example` to `.env` and set `VITE_API_BASE_URL` and `VITE_WS_BASE_URL` for your backend.
- From this directory run `npm install`, then `npm run dev`.
- `npm run build` creates the production bundle in `dist/`; `npm run preview` serves that bundle locally.
- `npm test` runs the Vitest/React Testing Library authentication flow tests.

## API and authentication

The API client is centralized in `src/api/client.js`; feature services live in `src/api/services.js`. API paths, payloads, permissions, and current gaps are recorded in [../BACKEND_INTEGRATION_INVENTORY.md](../BACKEND_INTEGRATION_INVENTORY.md).

The backend returns a 30-minute access JWT in JSON and a seven-day rotating refresh JWT in an HttpOnly cookie. The frontend keeps the access JWT in memory only, sends it as a Bearer token, and uses a single-flight cookie refresh after `401`. Logout clears the client token and calls the backend. MFA is supported by the backend login response. Registration and login do not persist passwords or OTPs. A refreshed session has no profile endpoint, so the interface uses a generic account label until the next login response supplies the username.

The WebSocket hook requests a short-lived, single-use ticket from `/fraud/ws-ticket/`; the JWT is never put in a socket URL. Customer event recovery uses `/fraud/notifications/`, and analyst recovery uses `/fraud/alerts/`. Events are deduplicated by ID and treated as prompts to refresh authoritative REST data. WebSocket reconnection uses exponential backoff and jitter.

## Backend setup requirements and limitations

The Django backend currently has no CORS configuration. When frontend and API are on different origins, configure the backend to allow the exact frontend origin with credentials; refresh cookies must remain compatible with the deployment's HTTPS/SameSite setup. This browser application cannot configure server CORS. Set Django `FRONTEND_URL` to the frontend origin for Google OAuth handoff. `ALLOWED_HOSTS` must include the WebSocket host.

Existing screens cover authentication, wallet, beneficiaries, transaction history/transfers, M-Pesa STK deposit/history, backend event notifications, and fraud case review for users permitted by the backend. The backend does not expose a profile endpoint, dashboard summary, password reset, customer support, mark-read notifications, wallet freeze/unfreeze, or audit log API. Fraud access cannot be inferred from a profile role, so the analyst page asks the backend and renders its `403` response. The backend has no transfer status lookup by idempotency key; retrying a transfer reuses its key, while transaction records remain server-authoritative. Payment history is returned without explicit pagination.

## Verification

Run `npm test` and `npm run build` for the current frontend checks. The automated suite covers login success, MFA handoff, and server error presentation. API integration requires the backend, its database/Redis dependencies, and compatible origin settings; no live backend/browser integration check is included yet.
