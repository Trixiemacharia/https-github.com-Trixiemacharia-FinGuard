import { useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Activity, ArrowDownLeft, ArrowLeftRight, Bell, ChevronDown, CircleHelp, LayoutDashboard, LogOut, Menu, ShieldCheck, WalletCards, X, CreditCard, ChartNoAxesCombined, PiggyBank, Sparkles } from 'lucide-react';
import { useAuth } from '../context/AuthContext.jsx';
import { useLiveEvents } from '../hooks/useLiveEvents.js';

const links = [
  { to: '/overview', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/payments', label: 'Payments', icon: CreditCard, children: [{ to: '/transactions', label: 'Send money & history', icon: ArrowLeftRight }, { to: '/payments', label: 'M-Pesa deposits', icon: ArrowDownLeft }] },
  { to: '/insights', label: 'Insights', icon: ChartNoAxesCombined },
  { to: '/savings', label: 'Savings', icon: PiggyBank },
  { to: '/wallet', label: 'Security', icon: ShieldCheck, children: [{ to: '/wallet', label: 'Wallet controls', icon: WalletCards }, { to: '/security/sessions', label: 'Devices & sessions', icon: Activity }, { to: '/notifications', label: 'Security events', icon: Bell }] },
  { to: '/assistant', label: 'AI Assistant', icon: Sparkles },
];

export function Shell() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [newEvents, setNewEvents] = useState(0);
  const [menu, setMenu] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const live = useLiveEvents({ enabled: true, onEvent: () => setNewEvents((n) => n + 1) });
  const title = location.pathname === '/transactions' ? 'Payments' : location.pathname === '/payments' ? 'Payments' : location.pathname.startsWith('/wallet') || location.pathname.startsWith('/security') || location.pathname === '/fraud' || location.pathname === '/notifications' ? 'Security' : links.find((link) => link.to === location.pathname)?.label || 'FinGuard';
  const close = () => setOpen(false);
  return <div className="app-shell">
    {open && <button className="mobile-shade" aria-label="Close navigation" onClick={close} />}
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      <div className="brand"><div className="brand-symbol"><ShieldCheck size={19} /></div><span>fin<span>guard</span></span><button className="sidebar-close" onClick={close} aria-label="Close menu"><X size={18} /></button></div>
      <div className="workspace-label">YOUR FINANCES</div>
      <nav className="side-nav" aria-label="Main navigation">{links.map(({ to, label, icon: Icon, end, children }) => <div className="nav-group" key={label}><NavLink to={to} end={end} onClick={close} className={({ isActive }) => `nav-item ${isActive || (children && (location.pathname === to || children.some((child) => child.to === location.pathname))) ? 'active' : ''}`}><Icon size={18} /><span>{label}</span>{label === 'Payments' && newEvents > 0 && <i className="nav-dot" />}</NavLink>{children && <div className="nav-sub-links">{children.filter((child) => child.to !== to).map(({ to: childTo, label: childLabel, icon: ChildIcon }) => <NavLink key={childTo} to={childTo} onClick={close} className={({ isActive }) => `nav-sub-item ${isActive ? 'active' : ''}`}><ChildIcon size={14}/><span>{childLabel}</span></NavLink>)}</div>}</div>)}</nav>
      <div className="nav-divider" />
      <div className="sidebar-bottom">
        <div className="help-card"><div className="help-icon"><CircleHelp size={16} /></div><strong>Need a hand?</strong><p>Visit your support centre for account guidance.</p><button onClick={() => window.alert('Support tickets are not available in this backend yet.')}>Explore help <span>↗</span></button></div>
        <div className="sidebar-foot"><span className={`connection-dot ${live === 'connected' ? 'online' : ''}`} /><span>{live === 'connected' ? 'Live connection' : 'Secure connection'}</span><span className="sidebar-version">v1.0</span></div>
      </div>
    </aside>
    <div className="main-frame">
      <header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={20} /></button><div className="breadcrumbs"><span>FinGuard</span><span className="crumb-slash">/</span><strong>{title}</strong></div></div>
        <div className="topbar-right"><span className={`live-state ${live === 'connected' ? 'is-live' : ''}`}><i /> {live === 'connected' ? 'Live' : 'Protected'}</span><button className="icon-button notification-button" aria-label={`${newEvents} new activity notifications`} onClick={() => navigate('/notifications')}><Bell size={18} />{newEvents > 0 && <i className="notification-dot" />}</button><div className="topbar-separator" /><div className="user-menu-wrap"><button className="user-menu" onClick={() => setMenu(!menu)} aria-expanded={menu}><span className="avatar">{(user?.username || 'A').slice(0, 1).toUpperCase()}</span><span className="user-meta"><strong>{user?.username || 'My account'}</strong><small>FinGuard account</small></span><ChevronDown size={15} /></button>{menu && <div className="dropdown"><div className="dropdown-label">Signed in{user?.email ? ` as ${user.email}` : ''}</div><button onClick={async () => { setMenu(false); await logout(); navigate('/login'); }}><LogOut size={15} /> Sign out</button></div>}</div></div>
      </header>
      <main className="content"><Outlet /></main>
      <footer className="app-footer"><span><ShieldCheck size={14} /> Your account is protected with FinGuard</span><span>For your security, never share your password or one-time code.</span></footer>
    </div>
  </div>;
}
