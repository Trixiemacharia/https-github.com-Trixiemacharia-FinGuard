/**
 * FinGuard iconography system.
 *
 * A small, purpose-drawn icon set used by the dashboard sidebar and navigation chrome instead of generic
 * stock icons. Every icon follows the same rules so the set reads as one family:
 *
 *  - 24 × 24 grid, 2px safe padding, drawn on whole/half pixels.
 *  - 1.75 stroke, round caps and joins, `currentColor` so icons inherit the text colour of their link.
 *  - One "duotone" accent shape per icon filled at 18% opacity (`.fi-tone`) for a soft, branded finish.
 *  - Same call signature as lucide-react (`<Icon size={18} />`) so they drop into existing markup.
 */

function FinIcon({ size = 20, strokeWidth = 1.75, title, className = '', children, ...rest }) {
  return <svg
    xmlns="http://www.w3.org/2000/svg"
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    className={`fin-icon ${className}`.trim()}
    aria-hidden={title ? undefined : 'true'}
    role={title ? 'img' : undefined}
    focusable="false"
    {...rest}
  >
    {title && <title>{title}</title>}
    {children}
  </svg>;
}

const tone = { fill: 'currentColor', fillOpacity: 0.18, stroke: 'none' };

/** Overview – a dashboard of tiles with one highlighted summary tile. */
export const FiOverview = (p) => <FinIcon {...p}>
  <rect x="3.5" y="3.5" width="7" height="9" rx="2" {...tone} />
  <rect x="3.5" y="3.5" width="7" height="9" rx="2" />
  <rect x="13.5" y="3.5" width="7" height="5" rx="2" />
  <rect x="13.5" y="11.5" width="7" height="9" rx="2" />
  <rect x="3.5" y="15.5" width="7" height="5" rx="2" />
</FinIcon>;

/** Payments – a bank card with a contactless mark. */
export const FiPayments = (p) => <FinIcon {...p}>
  <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
  <path d="M2.5 9.5h19" />
  <rect x="2.5" y="5" width="19" height="4.5" rx="2" {...tone} />
  <path d="M6 15h4" />
  <path d="M15.5 13.6a2 2 0 0 1 0 2.8M17.6 12.4a3.8 3.8 0 0 1 0 5.2" />
</FinIcon>;

/** Send money – two opposed arrows between two accounts. */
export const FiTransfer = (p) => <FinIcon {...p}>
  <circle cx="5" cy="7" r="2.5" {...tone} />
  <circle cx="5" cy="7" r="2.5" />
  <circle cx="19" cy="17" r="2.5" />
  <path d="M9.5 7h10m-3-3 3 3-3 3" />
  <path d="M14.5 17h-10m3 3-3-3 3-3" />
</FinIcon>;

/** M-Pesa deposit – a phone receiving money. */
export const FiDeposit = (p) => <FinIcon {...p}>
  <rect x="6" y="2.5" width="12" height="19" rx="2.5" />
  <rect x="8.5" y="6" width="7" height="8" rx="1.2" {...tone} />
  <path d="M12 6.5v6m-2.5-2.5 2.5 2.5 2.5-2.5" />
  <path d="M10.5 18.5h3" />
</FinIcon>;

/** Insights – rising bars with a trend line. */
export const FiInsights = (p) => <FinIcon {...p}>
  <path d="M3.5 20.5h17" />
  <rect x="5" y="13" width="3" height="5" rx="1" {...tone} />
  <rect x="5" y="13" width="3" height="5" rx="1" />
  <rect x="10.5" y="10" width="3" height="8" rx="1" />
  <rect x="16" y="7" width="3" height="11" rx="1" />
  <path d="M4.5 9.5 9 6l4 2 6.5-4.5" />
</FinIcon>;

/** Savings – a vault-style jar with a coin going in. */
export const FiSavings = (p) => <FinIcon {...p}>
  <path d="M6 8.5h12l-.9 10.2A2 2 0 0 1 15.1 20.5H8.9a2 2 0 0 1-2-1.8L6 8.5Z" {...tone} />
  <path d="M6 8.5h12l-.9 10.2A2 2 0 0 1 15.1 20.5H8.9a2 2 0 0 1-2-1.8L6 8.5Z" />
  <path d="M5 8.5h14" />
  <circle cx="12" cy="4.5" r="2" />
  <path d="M10 14.5h4M12 12.5v4" />
</FinIcon>;

/** Security – a shield with a keyhole. */
export const FiSecurity = (p) => <FinIcon {...p}>
  <path d="M12 2.8 19.5 5.6v5.6c0 4.6-3.1 8.4-7.5 10-4.4-1.6-7.5-5.4-7.5-10V5.6L12 2.8Z" {...tone} />
  <path d="M12 2.8 19.5 5.6v5.6c0 4.6-3.1 8.4-7.5 10-4.4-1.6-7.5-5.4-7.5-10V5.6L12 2.8Z" />
  <circle cx="12" cy="10.5" r="1.8" />
  <path d="M12 12.3v3.2" />
</FinIcon>;

/** Wallet controls – a wallet with a lock clasp. */
export const FiWallet = (p) => <FinIcon {...p}>
  <path d="M4 7.5V6a2 2 0 0 1 2-2h11" />
  <rect x="3.5" y="7.5" width="17" height="12.5" rx="2.5" />
  <path d="M20.5 11.5h-4a2 2 0 0 0 0 4h4v-4Z" {...tone} />
  <path d="M20.5 11.5h-4a2 2 0 0 0 0 4h4" />
  <circle cx="16.8" cy="13.5" r=".6" fill="currentColor" />
</FinIcon>;

/** Devices & sessions – a laptop and a phone. */
export const FiDevices = (p) => <FinIcon {...p}>
  <rect x="2.5" y="4.5" width="14" height="10" rx="1.8" {...tone} />
  <rect x="2.5" y="4.5" width="14" height="10" rx="1.8" />
  <path d="M1.5 18h10" />
  <rect x="15.5" y="9" width="7" height="11.5" rx="1.8" />
  <path d="M18.3 18h1.4" />
</FinIcon>;

/** Security events – a bell with an alert pulse. */
export const FiAlerts = (p) => <FinIcon {...p}>
  <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15l1.5-2Z" {...tone} />
  <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15l1.5-2Z" />
  <path d="M10 21h4" />
  <path d="M12 8.5v3.5" /><circle cx="12" cy="14.6" r=".5" fill="currentColor" />
</FinIcon>;

/** Assistant – a conversation bubble with a guiding compass point (money helper, not a "magic" sparkle). */
export const FiAssistant = (p) => <FinIcon {...p}>
  <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5v-8Z" {...tone} />
  <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 4v-4A2.5 2.5 0 0 1 4 13.5v-8Z" />
  <path d="M8.5 9.5h.01M12 9.5h.01M15.5 9.5h.01" strokeWidth="2.4" />
</FinIcon>;

/** Help – a lifebuoy. */
export const FiHelp = (p) => <FinIcon {...p}>
  <circle cx="12" cy="12" r="8.5" />
  <circle cx="12" cy="12" r="3.5" {...tone} />
  <circle cx="12" cy="12" r="3.5" />
  <path d="m6 6 3.5 3.5M14.5 14.5 18 18M18 6l-3.5 3.5M9.5 14.5 6 18" />
</FinIcon>;

/** Brand mark – FinGuard shield with a check. */
export const FiBrand = (p) => <FinIcon {...p}>
  <path d="M12 2.8 19.5 5.6v5.6c0 4.6-3.1 8.4-7.5 10-4.4-1.6-7.5-5.4-7.5-10V5.6L12 2.8Z" />
  <path d="m8.8 11.8 2.2 2.2 4.2-4.4" />
</FinIcon>;

/** Navigation chrome. */
export const FiMenu = (p) => <FinIcon {...p}><path d="M4 7h16M4 12h10M4 17h16" /></FinIcon>;
export const FiClose = (p) => <FinIcon {...p}><path d="m6 6 12 12M18 6 6 18" /></FinIcon>;
export const FiChevronDown = (p) => <FinIcon {...p}><path d="m6.5 9.5 5.5 5.5 5.5-5.5" /></FinIcon>;
export const FiBack = (p) => <FinIcon {...p}><path d="M19.5 12h-15m6-6-6 6 6 6" /></FinIcon>;
export const FiSignOut = (p) => <FinIcon {...p}>
  <path d="M14 4.5h3.5a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H14" />
  <path d="M10 8 6 12l4 4M6 12h9.5" />
</FinIcon>;
export const FiBell = (p) => <FinIcon {...p}>
  <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15l1.5-2Z" />
  <path d="M10 21h4" />
</FinIcon>;
