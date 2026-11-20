# FinGuard UX Enhancements

This document describes the user-experience improvements added to the FinGuard frontend: what changed, why, where the code lives, and how to check it.

The work adds to the existing features. It does not rewrite them. Business logic, API calls, the authentication flow, onboarding rules and the selfie verification algorithm are unchanged. The changes are:

- new components
- one new stylesheet, loaded after the existing styles
- small, targeted edits where the new pieces plug in

---

## Summary

| # | Request | What was done | Main files |
|---|---------|---------------|------------|
| 1 | The registration card changes height from page to page | Every auth view (Create account, Sign in and the MFA step) now uses a card of the same size. The onboarding card also keeps the same size across its setup steps. | `frontend/src/ux-enhancements.css` §1 |
| 2 | Replace the generic AI-looking icons in the dashboard sidebar | Added a purpose-drawn **FinGuard iconography system** and used it in the sidebar, top bar and brand mark. The "sparkles" icon is gone. | `frontend/src/components/icons/FinIcons.jsx`, `Shell.jsx`, `Auth.jsx` |
| 3 | Make selfie verification consistent and easy to use | Added a stage tracker, a camera frame that keeps a fixed size, pre-check tips, an automatic 3-second start, direction arrows, step dots, a time-remaining bar and clearer cancel and status messages | `frontend/src/pages/onboarding/LiveSelfie.jsx`, `ux-enhancements.css` §3 |
| 4 | Standard font sizes on the registration and account-creation forms | Labels are now 14px, inputs 16px, body text 15px, buttons 16px and headings 22–28px. Before, sizes ran from 9px to 12px. | `ux-enhancements.css` §4 |
| 6 | Back buttons so users can recover from mistakes | Added a reusable `BackButton`. It appears on the auth page, in the MFA step, in the onboarding header, on the email step ("change phone number") and in the dashboard top bar. | `frontend/src/components/BackButton.jsx`, `Auth.jsx`, `Onboarding.jsx`, `Shell.jsx` |

---

## 1. Consistent card size

**Problem.** The auth card shrank to fit its content. "Create account" has three fields and a password note, while "Sign in" has two fields, so the card jumped in size when the user switched tabs. A small entry animation (`auth-enter`) made the jump look worse. The onboarding card also grew and shrank from one setup step to the next.

**Solution** (`frontend/src/ux-enhancements.css`, section 1):

- `.auth-panel` is a flex column with `min-height: 950px`. That is tall enough for the longest view, "Create account" with the Google option. Content sits at the top, and the legal line stays at the bottom with `margin-top: auto`, so the card's outline never moves.
- The `auth-enter` nudge animation is turned off for the card.
- `.onboarding-card` is a flex column with `min-height: 760px`. Its footer stays at the bottom, so the Phone, Email, Photograph and Personal-details steps all use the same card.
- On screens narrower than 600px, the minimum heights are removed so small phones don't scroll through empty space.

## 2. FinGuard iconography system

**Problem.** The sidebar used generic stock icons, including a "sparkles" icon for the assistant, so the dashboard looked templated.

**Solution.** `frontend/src/components/icons/FinIcons.jsx` is a small icon set drawn for FinGuard. All icons follow the same rules:

- a 24 × 24 grid with 2px safe padding
- a 1.75 stroke with round caps and joins, drawn in `currentColor` so each icon takes the colour of its link
- one **duotone accent** per icon, filled at 18% opacity, which gives the set a consistent branded look
- the same props as lucide-react (`<Icon size={18} />`), so they replace the old icons directly
- decorative by default (`aria-hidden`). Pass `title` to give an icon an accessible name.

| Icon | Used for | Motif |
|------|----------|-------|
| `FiOverview` | Overview | Dashboard tiles with a highlighted summary tile |
| `FiPayments` | Payments | Bank card with a contactless mark |
| `FiTransfer` | Send money & history | Two accounts with opposed arrows |
| `FiDeposit` | M-Pesa deposits | Phone receiving money |
| `FiInsights` | Insights | Rising bars and a trend line |
| `FiSavings` | Savings | Jar with a coin going in |
| `FiSecurity` | Security | Shield with a keyhole |
| `FiWallet` | Wallet controls | Wallet with a clasp |
| `FiDevices` | Devices & sessions | Laptop and phone |
| `FiAlerts` | Security events | Bell with an alert mark |
| `FiAssistant` | AI Assistant | Conversation bubble (replaces "sparkles") |
| `FiHelp` | Help card | Lifebuoy |
| `FiBrand` | Logo mark | Shield with a check |
| `FiMenu`, `FiClose`, `FiChevronDown`, `FiBack`, `FiSignOut`, `FiBell` | Navigation controls | Line-only versions |

In `Shell.jsx`, active sidebar items show their icon in FinGuard mint (`#7fe0c3`). To add an icon, copy an existing one, keep the 24px grid and stroke width, and add one shape with `{...tone}` as its accent.

## 3. Live-selfie experience

The capture and verification logic is unchanged: random head-movement challenge, server-side frame analysis, frame limits and stopping the camera when the tab is hidden. Only the experience around it changed.

| Improvement | Why it helps |
|-------------|--------------|
| **4-stage tracker**: Get ready → Position face → Follow prompts → Checking | The user always knows where they are and what comes next. |
| **Fixed camera frame**: the 4:3 frame is always shown | The page no longer jumps when the camera starts or stops. Before the camera starts, the frame shows a face outline. |
| **Pre-check tips** inside the frame: light, glasses and hats, eye-level device | Fewer failed attempts caused by bad lighting or a bad angle. |
| **Browser prompt hint**: "choose **Allow**" | Reduces accidental camera denials. |
| **Automatic start**: once the face has been positioned well, a 3-second countdown starts the check. Losing the clear view cancels the countdown. | The user doesn't have to look away from the camera to find a button. "Start the check now" still works. |
| **Direction arrow** (↑ ← →) with a pulse, plus **step dots** | Each instruction can be understood at a glance. |
| **Time-remaining bar** for the 25-second recording window | The user knows how much time is left. |
| **Clear cancel**: "Cancel and go back" | Safe exit at any point. The camera stops right away. |
| **"Checking" state** with a spinner and a "keep this page open" note | Fewer page closes while the comparison runs. |
| Hint colours: neutral while positioning, green when ready | Instant feedback. |
| Bigger text and buttons, with full-width buttons on mobile | Easier to read and tap. |
| `prefers-reduced-motion` respected | Accessibility. |

## 4. Standard font sizes

Section 4 of the stylesheet raises the sizes on the registration, sign-in and onboarding screens only. Dashboard screens are unchanged.

| Element | Before | After |
|---------|--------|-------|
| Field labels | 10px | **14px** |
| Inputs | 11–12px | **16px** (also stops iOS from zooming in on focus) |
| Descriptions and body text | 11–12px | **15px** |
| Buttons | 12px | **16px**, minimum height 48–50px |
| Tabs, switch links, notices, errors | 9–11px | **13–14px** |
| Headings | 20–25px | **22–28px** |
| Legal and small print | 9px | **12px** |

## 6. Back buttons

`frontend/src/components/BackButton.jsx` is a single reusable control:

- If the user has in-app history, it goes back one step (`navigate(-1)`).
- If the user landed directly on the page from a bookmark, new tab or refresh, it goes to a `fallback` route instead, so it never sends them off the site.
- `to` sends the user to a fixed route, and `onClick` lets a page handle an internal step.

| Location | Label | Behaviour |
|----------|-------|-----------|
| Auth card header | **Back to home** | Goes to the previous page, or the landing page (`/`) if there isn't one |
| MFA one-time-code step | **Use a different account** | Returns to the email/username and password form and clears the code |
| Onboarding header | **Back** | Goes to the previous page, or `/`. On mobile only the icon shows. |
| Onboarding email step | **Back: change phone number** | Reopens the phone step so the user can fix a wrong number. The backend already allows a new phone code at this stage. |
| Reopened phone step | **Back to email verification** | Returns to the email step if the user didn't change anything |
| Dashboard top bar (every page except Overview) | **Back** | Goes to the previous page, or `/overview`. On narrow screens only the icon shows. |

The onboarding steps after email (photograph and personal details) are controlled by the server. Users can't go back past email verification, because the backend doesn't allow a verified step to be undone. Within the selfie step, "Cancel and go back" returns to the start of that step.

---

## Files

**New**

- `frontend/src/components/icons/FinIcons.jsx`: the FinGuard icon set
- `frontend/src/components/BackButton.jsx`: the reusable back control
- `frontend/src/ux-enhancements.css`: the new style layer, in five sections that match this document
- `frontend/src/__tests__/UxEnhancements.test.jsx`: tests for the back buttons and icons

**Edited** (small, targeted)

- `frontend/src/main.jsx`: imports `ux-enhancements.css` after the existing stylesheets
- `frontend/src/components/Shell.jsx`: sidebar and top bar icons now come from FinIcons, and a Back button was added to the top bar
- `frontend/src/pages/Auth.jsx`: Back to home, the MFA "Use a different account" button, and the brand icon instead of sparkles
- `frontend/src/pages/Onboarding.jsx`: header Back button, and the email-step "change phone number" back path
- `frontend/src/pages/onboarding/LiveSelfie.jsx`: the new presentation layer described in section 3. The capture and verification logic is unchanged.

## Verification

```bash
cd frontend
npm test        # 41 tests, including 5 new ones in UxEnhancements.test.jsx
npm run build   # production build
```

Manual checks:

1. Open `/auth?mode=register` and switch between **Create account** and **Sign in**. The card's outline stays the same.
2. Sign in and open any dashboard page. The sidebar uses the new icons, and **Back** appears in the top bar.
3. In onboarding, on the email step, click **Back: change phone number** and then **Back to email verification**.
4. In the photograph step, start the live selfie. Check the stage tracker, the 3-second countdown, the arrows and dots, the time bar, and **Cancel and go back**.
