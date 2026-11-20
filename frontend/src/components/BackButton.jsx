import { useLocation, useNavigate } from 'react-router-dom';
import { FiBack } from './icons/FinIcons.jsx';

/**
 * Reusable "Back" control.
 *
 * Goes to the previous page in this tab's history when there is one. When the user landed directly on the page
 * (new tab, bookmark, refresh after redirect) there is no in-app history, so it goes to `fallback` instead of
 * leaving the site. Pass `to` to always go to a fixed page, or `onClick` to handle the step yourself.
 */
export function BackButton({ to, fallback = '/', label = 'Back', onClick, className = '' }) {
  const navigate = useNavigate();
  const location = useLocation();
  function goBack() {
    if (onClick) { onClick(); return; }
    if (to) { navigate(to); return; }
    // react-router stores its own history index; key 'default' means this is the first entry in the app.
    const idx = typeof window !== 'undefined' ? window.history.state?.idx : undefined;
    if ((typeof idx === 'number' && idx > 0) || (idx === undefined && location.key !== 'default')) navigate(-1);
    else navigate(fallback, { replace: true });
  }
  return <button type="button" className={`back-button ${className}`.trim()} onClick={goBack}>
    <FiBack size={16} /><span>{label}</span>
  </button>;
}
