import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Camera } from 'lucide-react';
import { identityApi } from '../../api/services.js';
import './identity.css';

const MAX_UPLOAD_FRAMES = 24;
const PROMPTS = { straight: 'Look straight at the camera', left: 'Turn your head slightly to your left', right: 'Turn your head slightly to your right' };
const HINTS = {
  no_face: 'We can’t see your face. Centre yourself in the oval.', multiple_faces: 'Only you should be in view.',
  move_closer: 'Move a little closer.', centre_face: 'Centre your face in the oval.', more_light: 'Find brighter, even light.',
  hold_still: 'Hold still for a moment.',
};

function grab(video, canvas, width) {
  const scale = width / video.videoWidth;
  canvas.width = width; canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height); // unmirrored, as the camera sees
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85));
}
const evenly = (items, max) => (items.length <= max ? items
  : Array.from({ length: max }, (_, i) => items[Math.round(i * (items.length - 1) / (max - 1))]));

/**
 * Live selfie with a randomized head-movement challenge. The browser only captures frames; the server analyses
 * every frame, checks the challenge and compares the face with the uploaded photograph. The camera runs only
 * while this step is active and stops on completion, cancellation, leaving the page or hiding the tab.
 */
export function LiveSelfie({ onResult, onError }) {
  const video = useRef(null); const canvas = useRef(null); const stream = useRef(null);
  const timers = useRef([]); const mounted = useRef(true);
  const [phase, setPhase] = useState('intro'); // intro | requesting | denied | unavailable | positioning | challenge | comparing
  const [hint, setHint] = useState(''); const [ready, setReady] = useState(false);
  const [steps, setSteps] = useState([]); const [stepIndex, setStepIndex] = useState(0);

  const stop = useCallback(() => {
    timers.current.forEach((id) => { clearInterval(id); clearTimeout(id); }); timers.current = [];
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }, []);
  useEffect(() => {
    mounted.current = true;
    const onHide = () => { if (document.hidden) { stop(); setPhase((p) => (['positioning', 'challenge'].includes(p) ? 'intro' : p)); } };
    document.addEventListener('visibilitychange', onHide);
    return () => { mounted.current = false; document.removeEventListener('visibilitychange', onHide); stop(); };
  }, [stop]);

  async function start() {
    setReady(false); setHint('');
    if (!navigator.mediaDevices?.getUserMedia) { setPhase('unavailable'); return; }
    setPhase('requesting');
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
      setPhase('positioning');
    } catch (e) {
      setPhase(e?.name === 'NotAllowedError' || e?.name === 'SecurityError' ? 'denied' : 'unavailable');
    }
  }

  // Attach the stream and run positioning feedback once the <video> element exists.
  useEffect(() => {
    if (phase !== 'positioning' || !stream.current || !video.current) return undefined;
    if (video.current.srcObject !== stream.current) { video.current.srcObject = stream.current; video.current.play().catch(() => {}); }
    let streak = 0; let busy = false;
    const id = setInterval(async () => {
      if (busy || !video.current?.videoWidth) return;
      busy = true;
      try {
        const { data } = await identityApi.preview(await grab(video.current, canvas.current, 320));
        streak = data.ready && data.pose === 'straight' ? streak + 1 : 0;
        setReady(streak >= 2);
        setHint(data.ready ? (data.pose === 'straight' ? 'Looks good. Hold still.' : 'Look straight at the camera.') : HINTS[data.hints[0]] || '');
      } catch { /* positioning hints are best effort */ } finally { busy = false; }
    }, 800);
    return () => clearInterval(id);
  }, [phase]);

  async function runChallenge() {
    let challenge;
    try { challenge = (await identityApi.challenge()).data; } catch (e) { onError(e.data?.detail || e.message); return; }
    setSteps(challenge.steps); setStepIndex(0); setPhase('challenge');
    const frames = []; let index = 0; let busy = false; let finished = false;
    const finish = async () => {
      if (finished || !mounted.current) return; finished = true;
      stop(); setPhase('comparing');
      try { onResult((await identityApi.verify(challenge.challenge_id, evenly(frames, MAX_UPLOAD_FRAMES))).data); }
      catch (e) { if (e.data?.outcome) onResult(e.data); else onError(e.data?.detail || e.message); }
      if (mounted.current) setPhase('intro');
    };
    timers.current.push(setInterval(async () => {
      if (video.current?.videoWidth) frames.push(await grab(video.current, canvas.current, 480));
    }, 400));
    timers.current.push(setInterval(async () => {
      if (busy || !frames.length) return;
      busy = true;
      try {
        const { data } = await identityApi.preview(frames[frames.length - 1]);
        if (data.pose === challenge.steps[index]) {
          index += 1; setStepIndex(index);
          if (index >= challenge.steps.length) timers.current.push(setTimeout(finish, 700));
        }
      } catch { /* the server re-checks every frame on submit */ } finally { busy = false; }
    }, 700));
    timers.current.push(setTimeout(finish, 25000)); // bounds the recording; the server decides
  }

  const live = ['positioning', 'challenge'].includes(phase);
  return <div className="live-selfie">
    <p className="live-selfie-intro">Next, take a live selfie. We’ll ask you to move your head in a random order, then compare your face with the photograph. The camera is used only for this check.</p>
    {(live || phase === 'comparing') && <div className="live-selfie-camera">
      {live ? <video ref={video} playsInline muted aria-label="Camera preview" /> : <span className="live-selfie-status">Comparing your selfie with your photograph…</span>}
      {live && <div className={`live-selfie-oval ${ready || phase === 'challenge' ? 'ok' : ''}`} aria-hidden="true" />}
      {phase === 'challenge' && <div className="live-selfie-prompt" aria-live="assertive"><strong>{PROMPTS[steps[stepIndex]] || 'Done, hold on…'}</strong>
        <span>Step {Math.min(stepIndex + 1, steps.length)} of {steps.length}</span></div>}
    </div>}
    <canvas ref={canvas} hidden />
    {phase === 'positioning' && <p className="live-selfie-hint" aria-live="polite">{hint || 'Centre your face in the oval…'}</p>}
    {phase === 'denied' && <div className="form-error" role="alert">Camera access was blocked. Allow camera access in your browser’s address bar, then try again.</div>}
    {phase === 'unavailable' && <div className="form-error" role="alert">We couldn’t use a camera on this device (it may be in use by another app). You can sign in on your phone to finish this step; your progress is saved.</div>}
    <div className="live-selfie-actions">
      {['intro', 'denied', 'unavailable'].includes(phase) && <button type="button" className="primary-button" onClick={start}><Camera size={15} /> {phase === 'intro' ? 'Start live selfie' : 'Try again'}</button>}
      {phase === 'requesting' && <button type="button" className="primary-button" disabled>Waiting for camera permission…</button>}
      {phase === 'positioning' && <button type="button" className="primary-button" disabled={!ready} onClick={runChallenge}>{ready ? <>Start the check <ArrowRight size={15} /></> : 'Waiting for a clear view…'}</button>}
      {live && <button type="button" className="text-button" onClick={() => { stop(); setPhase('intro'); }}>Cancel</button>}
    </div>
    <small className="live-selfie-note">A lightweight automated check, not a guarantee against sophisticated spoofing. If it can’t confirm you, a person reviews it.</small>
  </div>;
}
