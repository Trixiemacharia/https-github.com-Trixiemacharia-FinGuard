import { useEffect, useRef, useState } from 'react';
import { fraudApi } from '../api/services.js';

export function useLiveEvents({ enabled, analyst = false, onEvent }) {
  const [state, setState] = useState('offline');
  const cursor = useRef(0);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  useEffect(() => {
    if (!enabled) return undefined;
    let stopped = false;
    let socket;
    let timer;
    let attempts = 0;
    const restCatchup = async () => {
      const result = analyst ? await fraudApi.alerts(cursor.current) : await fraudApi.notifications(cursor.current);
      for (const event of result.data.events || []) {
        if (event.id > cursor.current) cursor.current = event.id;
      }
    };
    const connect = async () => {
      try {
        const { data } = await fraudApi.wsTicket();
        if (stopped) return;
        const base = (import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000').replace(/\/$/, '');
        socket = new WebSocket(`${base}/ws/${analyst ? 'fraud' : 'transactions'}/?ticket=${encodeURIComponent(data.ticket)}`);
        setState('connecting');
        socket.onopen = () => { attempts = 0; setState('connected'); restCatchup().catch(() => {}); };
        socket.onmessage = (message) => {
          try { const event = JSON.parse(message.data); if (Number(event.id) > cursor.current) { cursor.current = Number(event.id); onEventRef.current?.(event); } }
          catch { /* Ignore malformed server event and keep the connection alive. */ }
        };
        socket.onerror = () => socket.close();
        socket.onclose = () => {
          if (stopped) return;
          setState('offline');
          const delay = Math.min(30000, 800 * (2 ** attempts++)) * (0.75 + Math.random() * 0.5);
          timer = setTimeout(connect, delay);
        };
      } catch {
        setState('offline');
        const delay = Math.min(30000, 800 * (2 ** attempts++)) * (0.75 + Math.random() * 0.5);
        timer = setTimeout(connect, delay);
      }
    };
    connect();
    return () => { stopped = true; clearTimeout(timer); socket?.close(); };
  }, [enabled, analyst]);
  return state;
}
