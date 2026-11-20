# FinGuard

FinGuard is a secure digital-wallet platform. Its main parts are:

- a Django REST + Channels backend in `fintech/`
- a React + Vite frontend in `frontend/`

Users create an account, verify their phone number and email, verify their identity with a photograph and a live selfie, and are then approved for a wallet. In the wallet they can send money, make M-Pesa deposits, check insights, manage savings, and control security with live fraud alerts.

This README explains how to install, run and use the system. Related documents:

- [UX_ENHANCEMENTS.md](UX_ENHANCEMENTS.md): the latest user-experience improvements (consistent cards, FinGuard iconography, selfie flow, font sizes, back buttons)
- [IMPLEMENTATION_MAP.md](IMPLEMENTATION_MAP.md): architecture and feature map
- [BACKEND_INTEGRATION_INVENTORY.md](BACKEND_INTEGRATION_INVENTORY.md): API endpoint inventory
- [frontend/README.md](frontend/README.md): frontend-specific notes
- `fintech/FRAUD_SYSTEM.md`: how fraud detection works

---

## 1. Architecture

```
Browser ──► Vite dev server :5173 ──(proxy /api, /accounts, /ws)──► Django/Daphne :8000
                                                                     │
                                       MySQL ◄───────────────────────┤
                                       Redis (cache, channels, broker)◄┤
                                       Celery worker + beat ◄─────────┘ (emails, scheduled jobs)
```

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API | Django 6, Django REST Framework, SimpleJWT | Auth, onboarding, wallets, payments, fraud, insights, savings, assistant |
| Realtime | Django Channels + Daphne | Live transaction and fraud events over WebSocket |
| Background jobs | Celery + Redis | OTP emails, scheduled jobs |
| Database | MySQL (SQLite in tests) | Persistent data |
| Identity | OpenCV (headless) | Photo quality, live-selfie and face-match checks |
| Frontend | React, React Router, Chart.js, Vite | Customer web app |

## 2. Prerequisites

- Python 3.12 or newer, with `pip` and `venv`
- Node.js 20 or newer, with npm
- MySQL 8 (or MariaDB) server and client headers (`libmysqlclient-dev` / `default-libmysqlclient-dev`)
- Redis 6 or newer, running on `127.0.0.1:6379`
- A webcam, for the live-selfie step

## 3. Backend setup (`fintech/`)

```bash
cd fintech
python3 -m venv ../venv
source ../venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then edit .env (see below)
```

### Recommended `.env` values for local development

```ini
DEBUG=True
SECRET_KEY=any-long-random-string
REFRESH_COOKIE_SECURE=False     # local http, no HTTPS
CSRF_COOKIE_SECURE=False
SESSION_COOKIE_SECURE=False
FRONTEND_URL=http://localhost:5173

DB_NAME=fintech
DB_USER=fintech
DB_PASSWORD=your-db-password
DB_HOST=127.0.0.1
DB_PORT=3306

# Development delivery: verification codes and links are printed to the terminal logs (see section 6)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
SMS_BACKEND=apps.users.sms.ConsoleSMSBackend
```

> `ConsoleSMSBackend` refuses to run unless `DEBUG=True`. In production, set `SMS_BACKEND=apps.users.sms.AfricasTalkingBackend` with `AT_USERNAME` / `AT_API_KEY`, and configure a real SMTP `EMAIL_BACKEND`.

### Database, identity models and admin user

```bash
# create the MySQL database and user first, e.g.
#   CREATE DATABASE fintech CHARACTER SET utf8mb4;
#   CREATE USER 'fintech'@'localhost' IDENTIFIED BY 'your-db-password';
#   GRANT ALL ON fintech.* TO 'fintech'@'localhost';

python manage.py migrate
python manage.py download_identity_models    # one-time: face models used by the selfie check
python manage.py createsuperuser             # staff account for /admin and manual reviews
```

## 4. Frontend setup (`frontend/`)

```bash
cd frontend
npm install
cp .env.example .env     # VITE_API_BASE_URL=http://localhost:8000/api/v1, VITE_WS_BASE_URL=ws://localhost:8000
```

## 5. Running the system

Open **four terminals** and keep them all running.

| Terminal | Command | What it does |
|----------|---------|--------------|
| 1 | `redis-server` (or `sudo systemctl start redis`) | Cache, WebSocket channel layer, Celery broker |
| 2 | `cd fintech && source ../venv/bin/activate && python manage.py runserver` | Django API + WebSockets on **http://localhost:8000**. **SMS codes and email verification links are printed here.** |
| 3 | `cd fintech && source ../venv/bin/activate && celery -A fintech worker -l info` | Background jobs. **Sign-in (MFA) code emails are printed here.** |
| 4 | `cd frontend && npm run dev` | Web app on **http://localhost:5173** |

Recommended: run `celery -A fintech beat -l info` in a fifth terminal. It runs the scheduled jobs: reconciling pending M-Pesa payments, processing scheduled savings, and purging expired identity images.

Then open **http://localhost:5173**.

## 6. Getting verification codes from the terminal logs (development)

In development, FinGuard does **not** send real SMS or email. Every code and link is written to the **terminal logs** instead, so you can copy it from there.

### Phone verification code (onboarding step 1)

1. On the onboarding page, enter a phone number and click **Send code**.
2. Look in **terminal 2** (`python manage.py runserver`). You'll see a line like this:

   ```
   WARNING ... Development onboarding SMS verification code: 482913
   ```

3. Enter the 6-digit number (`482913` in this example) in **Verification code** and click **Verify phone**.

The code expires after **5 minutes** and allows **5 attempts**. You can request a new code every 60 seconds.

### Email verification (onboarding step 2)

Email is verified with a single-use **link** rather than a typed code.

1. Click **Send verification email**.
2. Look in **terminal 2** for this line:

   ```
   WARNING ... DEVELOPMENT ONLY: email verification link for user_id=5: http://localhost:5173/onboarding?email_token=AbC123...
   ```

3. Copy the full URL into the same browser where you're signed in. The page will show **"Email address verified."**

The link is valid for **30 minutes**. The full email is also printed to the same terminal by the console email backend, but that copy is quoted-printable encoded (`=3D`, broken lines), so use the decoded `DEVELOPMENT ONLY` line above. You can also choose **verify instantly with your Google account** if Google sign-in is configured.

### Sign-in one-time code (MFA)

If MFA is turned on for an account, signing in asks for a one-time code. That code is sent by email through Celery, so it appears in **terminal 3** (the Celery worker) as a printed email:

```
Subject: Your verification code
Your verification code is 731058. It expires in 5 minutes.
```

> If no code appears, check that the right terminal is running, that `DEBUG=True`, and that `SMS_BACKEND=apps.users.sms.ConsoleSMSBackend` / `EMAIL_BACKEND=...console.EmailBackend` are set in `fintech/.env`. Restart `runserver` after you edit `.env`.

## 7. Using FinGuard: user walkthrough

### 7.1 Create an account or sign in

1. On the landing page, click **Get started** or **Sign in**.
2. Use the tabs to switch between **Create account** and **Sign in**. The card keeps the same size on both tabs.
3. To create an account, enter a **username**, **email address** and **password**, then click **Create account**.
4. Navigation:
   - **Back to home**, at the top of the card, returns to the landing page.
   - On the MFA step, **Use a different account** returns to the sign-in form.

### 7.2 Onboarding (account setup)

A progress tracker shows the four steps: **Phone → Email → Photograph → Personal details**. Your progress is saved on the server, so you can sign out and come back later.

| Step | What to do | Notes |
|------|-----------|-------|
| 1. Phone | Enter your number (`07XX…`, `2547…` or `+2547…`), click **Send code**, then enter the code from **terminal 2** | You can request a new code after 60 seconds |
| 2. Email | Click **Send verification email**, then open the link from **terminal 2** | Entered the wrong number? Click **Back: change phone number** |
| 3. Photograph | Accept the consent, upload a clear photo of your face (JPEG/PNG/WebP, up to 5 MB), then do the **live selfie** | See 7.3 |
| 4. Personal details | Address, county, town, occupation and monthly earnings, then **Submit application** | Approved automatically when screening is clear. Otherwise it goes to staff review. |

**Back** in the onboarding header returns to the previous page. **Sign out** keeps your progress.

### 7.3 Live selfie: tips

1. Click **Start live selfie** and choose **Allow** when the browser asks for the camera.
2. **Position face**: centre your face in the oval. When the oval turns green, the check starts automatically after a 3-second countdown. You can also click **Start the check now**.
3. **Follow prompts**: follow the arrow on screen (look straight, turn left, turn right). The dots show your progress and the bar shows the time left (25 seconds).
4. **Checking**: keep the page open while your selfie is compared with your photograph.
5. Click **Cancel and go back** at any time to stop the camera and start again.

For the best result, face a window or lamp, remove sunglasses and hats, and hold the device at eye level. If automatic checking can't confirm you, a staff member reviews the attempt.

### 7.4 Dashboard

The sidebar uses the FinGuard icon set:

- **Overview**: balance, recent activity and quick actions
- **Payments**:
  - **Send money & history**: internal transfers and transaction history
  - **M-Pesa deposits**: STK push top-ups
- **Insights**: spending categories, trends, calendar and exportable reports
- **Savings**: goals, rules, move-money and planning
- **Security**:
  - **Wallet controls**: freeze or unfreeze, and beneficiaries
  - **Devices & sessions**
  - **Security events**
- **AI Assistant**: answers questions using your real account data

**Back** in the top bar (on every page except Overview) returns to the previous screen. The bell opens security events. Use the account menu to sign out.

### 7.5 Staff and admin

- Use `http://localhost:8000/admin/` with the superuser to review onboarding applications that need manual review, selfie checks and fraud cases.
- Users who are allowed to review fraud can also open `/fraud` in the web app.

## 8. Tests and builds

```bash
# Frontend
cd frontend
npm test            # Vitest + React Testing Library
npm run build       # production bundle in frontend/dist

# Backend
cd fintech
source ../venv/bin/activate
pytest              # uses fintech/test_settings.py (SQLite)
```

## 9. Troubleshooting

| Symptom | Fix |
|---------|-----|
| "SMS delivery is not configured" | Set `SMS_BACKEND=apps.users.sms.ConsoleSMSBackend` and `DEBUG=True`, then restart `runserver` |
| "Console SMS backend is development-only…" | `DEBUG` is not `True` in `fintech/.env` |
| "Please wait before requesting another code" | Wait 60 seconds between requests |
| Email link says invalid or expired | Links last 30 minutes and work once. Request a new one and open it in the browser where you're signed in. |
| No MFA code appears | Start the Celery worker (terminal 3) and look there |
| Signed out after refreshing the page | For local HTTP, set `REFRESH_COOKIE_SECURE=False` (and the other `*_SECURE` settings) |
| Camera blocked or unavailable | Allow the camera in the browser's address bar and close other apps using the camera, or finish this step on your phone |
| WebSocket shows "Protected" instead of "Live" | Make sure Redis is running and `ALLOWED_HOSTS` includes `localhost` |
| `mysqlclient` fails to install | Install the MySQL client development headers first |

## 10. Security notes

- Verification codes and links are printed to the logs **only** with the development backends and `DEBUG=True`. Never use these settings in production.
- Access tokens are kept in memory only. The refresh token is an HttpOnly cookie.
- Identity photos are encrypted at rest and deleted after the check. Only the result is kept.
- Never commit `.env` files or real credentials.
