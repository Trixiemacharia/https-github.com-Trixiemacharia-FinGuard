import { useEffect, useRef, useState } from 'react';

// Google Identity Services, Google's official sign-in library. The ID token it returns is verified on the server.
const GIS_SRC = 'https://accounts.google.com/gsi/client';
let gisPromise = null;

export function loadGoogleIdentity() {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (!gisPromise) {
    gisPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = GIS_SRC; script.async = true; script.defer = true;
      script.onload = resolve;
      script.onerror = () => { gisPromise = null; script.remove(); reject(new Error('Google sign-in could not load.')); };
      document.head.appendChild(script);
    });
  }
  return gisPromise;
}

/** Renders Google's own button. `nonce` must come from the server; Google embeds it in the signed ID token. */
export function GoogleButton({ clientId, nonce, onCredential, onLoadError, text = 'continue_with' }) {
  const target = useRef(null);
  const handlers = useRef({ onCredential, onLoadError });
  handlers.current = { onCredential, onLoadError };
  const [state, setState] = useState('loading');
  useEffect(() => {
    if (!clientId) return undefined;
    let live = true;
    setState('loading');
    loadGoogleIdentity().then(() => {
      if (!live || !target.current) return;
      window.google.accounts.id.initialize({
        client_id: clientId, nonce, ux_mode: 'popup', itp_support: true, cancel_on_tap_outside: true,
        callback: (response) => handlers.current.onCredential(response.credential),
      });
      target.current.innerHTML = '';
      window.google.accounts.id.renderButton(target.current, { theme: 'outline', size: 'large', text, shape: 'rectangular', logo_alignment: 'left', width: 320 });
      setState('ready');
    }).catch(() => { if (live) { setState('failed'); handlers.current.onLoadError?.(); } });
    return () => { live = false; };
  }, [clientId, nonce, text]);
  return <div className="ob-google">
    <div ref={target} className="ob-google-slot" aria-busy={state === 'loading'} />
    {state === 'loading' && <span className="ob-muted">Connecting to Google…</span>}
    {state === 'failed' && <span className="ob-muted">Google sign-in couldn’t load. Check your connection.</span>}
  </div>;
}
