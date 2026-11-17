import { useCallback, useEffect, useRef, useState } from 'react';
import { Camera, CameraOff, CheckCircle2, ImagePlus, Loader2, RefreshCw, ScanFace, ShieldCheck, Upload, XCircle } from 'lucide-react';
import { onboardingApi } from '../../api/services.js';

const MAX_PHOTO_BYTES = 5 * 1024 * 1024;
const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const MAX_UPLOAD_FRAMES = 24;
const PROMPTS = { straight: 'Look straight at the camera', left: 'Turn your head slightly to your left', right: 'Turn your head slightly to your right' };
const HINTS = {
  no_face: 'We can’t see your face. Centre yourself in the oval.', multiple_faces: 'Only you should be in view.',
  move_closer: 'Move a little closer.', centre_face: 'Centre your face in the oval.', more_light: 'Find brighter, even light.',
  hold_still: 'Hold still for a moment.',
};
const OUTCOME_TITLES = {
  FACE_NOT_DETECTED: 'We couldn’t see your face', MULTIPLE_FACES: 'More than one face was visible', FACE_MISMATCH: 'Your selfie didn’t match your photo',
  LIVENESS_FAILED: 'The live check wasn’t completed', IMAGE_QUALITY_FAILED: 'The image quality was too low',
};

// --- consent ---------------------------------------------------------------------------------------------------------

export function ConsentPanel({ onAccept, busy }) {
  const [checked, setChecked] = useState(false);
  return <div className="ob-panel">
    <span className="ob-step-icon"><ShieldCheck size={20} /></span>
    <h2>How we use your photos</h2>
    <ul className="ob-notice">
      <li>We ask for a photo of you and a short live selfie to confirm the photo is really you and that a real person is present.</li>
      <li>Both are checked on FinGuard’s own servers. Nothing is sent to other companies.</li>
      <li>Your photo is stored encrypted only until the check finishes, then deleted. If a person must review your check, the images are kept encrypted for up to 7 days and then deleted.</li>
      <li>We keep only the result: pass or fail, the date, and the reason if it failed. We never keep a face template.</li>
      <li>This is an automated screening check, not a guarantee. If it can’t confirm you, a person reviews it instead of rejecting you automatically.</li>
    </ul>
    <label className="ob-check"><input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} /> I agree to FinGuard processing my photo and live selfie for identity verification as described above.</label>
    <button className="ob-btn primary" disabled={!checked || busy} onClick={onAccept}>{busy ? 'Saving…' : 'Continue'}</button>
  </div>;
}

// --- photo upload ----------------------------------------------------------------------------------------------------

export function PhotoUpload({ token, onAccepted, attemptsLeft }) {
  const [file, setFile] = useState(null); const [preview, setPreview] = useState('');
  const [dragging, setDragging] = useState(false); const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);
  const input = useRef(null);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  function choose(candidate) {
    setProblem(null);
    if (!candidate) return;
    if (!PHOTO_TYPES.includes(candidate.type)) { setProblem({ message: 'Use a JPEG, PNG or WebP photo.' }); return; }
    if (candidate.size > MAX_PHOTO_BYTES) { setProblem({ message: 'That file is over 5 MB. Choose a smaller photo.' }); return; }
    setFile(candidate); setPreview(URL.createObjectURL(candidate));
  }
  async function submit() {
    setBusy(true); setProblem(null);
    try { const { data } = await onboardingApi.photo(token, file); onAccepted(data); }
    catch (e) { setProblem({ message: e.data?.message || e.data?.detail || e.message, attemptsLeft: e.data?.attempts_left }); }
    finally { setBusy(false); }
  }
  return <div className="ob-panel">
    <span className="ob-step-icon"><ImagePlus size={20} /></span>
    <h2>Verify your identity</h2>
    <p className="ob-lead">Upload a clear photograph of yourself. We’ll use a live selfie to confirm that the photograph belongs to you.</p>
    <ul className="ob-tips"><li>Only you, facing the camera</li><li>Your whole face visible: no sunglasses, hat or mask</li><li>Good, even light and in focus</li></ul>
    {!file ? <div className={`ob-drop ${dragging ? 'over' : ''}`} role="button" tabIndex={0} aria-label="Upload a photo: drop a file here or press Enter to choose one"
      onClick={() => input.current?.click()} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.current?.click(); } }}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files?.[0]); }}>
      <Upload size={22} /><strong>Drop your photo here</strong><span>or click to choose · JPEG, PNG or WebP up to 5 MB</span>
    </div> : <div className="ob-preview">
      <img src={preview} alt="Selected photograph preview" />
      <div><strong>{file.name}</strong><span>{(file.size / 1024 / 1024).toFixed(1)} MB</span>
        <button className="ob-btn ghost" onClick={() => { setFile(null); setPreview(''); setProblem(null); }} disabled={busy}><RefreshCw size={14} /> Replace image</button></div>
    </div>}
    <input ref={input} type="file" accept={PHOTO_TYPES.join(',')} hidden aria-label="Choose photo" onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ''; }} />
    {problem && <div className="ob-alert error" role="alert"><XCircle size={16} /><div><strong>{problem.message}</strong>{problem.attemptsLeft !== undefined && <span>{problem.attemptsLeft} attempt{problem.attemptsLeft === 1 ? '' : 's'} left</span>}</div></div>}
    <button className="ob-btn primary" disabled={!file || busy} onClick={submit}>{busy ? <><Loader2 size={16} className="ob-spin" /> Checking your photo…</> : 'Check photo'}</button>
    {attemptsLeft !== undefined && attemptsLeft < 6 && <p className="ob-muted">{attemptsLeft} photo attempt{attemptsLeft === 1 ? '' : 's'} left.</p>}
  </div>;
}

// --- live selfie + liveness ----------------------------------------------------------------------------------------------

function grab(video, canvas, width) {
  const scale = width / video.videoWidth;
  canvas.width = width; canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height); // unmirrored, as the camera sees
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85));
}

function evenly(items, max) {
  if (items.length <= max) return items;
  return Array.from({ length: max }, (_, i) => items[Math.round(i * (items.length - 1) / (max - 1))]);
}

export function CameraCheck({ token, onResult, onChangePhoto }) {
  const video = useRef(null); const canvas = useRef(null); const stream = useRef(null); const timers = useRef([]);
  const [phase, setPhase] = useState('intro'); // intro | requesting | denied | unavailable | positioning | challenge | comparing | error
  const [hint, setHint] = useState(''); const [ready, setReady] = useState(false);
  const [steps, setSteps] = useState([]); const [stepIndex, setStepIndex] = useState(0); const [error, setError] = useState('');

  const mounted = useRef(true);
  const stop = useCallback(() => {
    timers.current.forEach((id) => { clearInterval(id); clearTimeout(id); }); timers.current = [];
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
  }, []);
  useEffect(() => {
    const onHide = () => { if (document.hidden) { stop(); setPhase((p) => (['positioning', 'challenge'].includes(p) ? 'intro' : p)); } };
    document.addEventListener('visibilitychange', onHide);
    mounted.current = true;
    return () => { mounted.current = false; document.removeEventListener('visibilitychange', onHide); stop(); };
  }, [stop]);

  async function start() {
    setError(''); setReady(false); setHint('');
    if (!navigator.mediaDevices?.getUserMedia) { setPhase('unavailable'); return; }
    setPhase('requesting');
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
    } catch (e) {
      setPhase(e?.name === 'NotAllowedError' || e?.name === 'SecurityError' ? 'denied' : 'unavailable');
      return;
    }
    setPhase('positioning');
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
        const { data } = await onboardingApi.preview(token, await grab(video.current, canvas.current, 320));
        streak = data.ready && data.pose === 'straight' ? streak + 1 : 0;
        setReady(streak >= 2);
        setHint(data.ready ? (data.pose === 'straight' ? 'Looks good. Hold still.' : 'Look straight at the camera.') : HINTS[data.hints[0]] || '');
      } catch { /* positioning hints are best effort */ } finally { busy = false; }
    }, 800);
    return () => clearInterval(id);
  }, [phase, token]);

  async function runChallenge() {
    setError('');
    let challenge;
    try { challenge = (await onboardingApi.challenge(token)).data; }
    catch (e) { setError(e.data?.detail || e.message); return; }
    setSteps(challenge.steps); setStepIndex(0); setPhase('challenge');
    const frames = []; let index = 0; let busy = false; let finished = false;
    const finish = async () => {
      if (finished || !mounted.current) return; finished = true;
      stop(); setPhase('comparing');
      try { const { data } = await onboardingApi.verify(token, challenge.challenge_id, evenly(frames, MAX_UPLOAD_FRAMES)); onResult(data); }
      catch (e) { if (e.data?.outcome) onResult(e.data); else { setError(e.data?.detail || e.message); setPhase('error'); } }
    };
    timers.current.push(setInterval(async () => {
      if (video.current?.videoWidth) frames.push(await grab(video.current, canvas.current, 480));
    }, 400));
    timers.current.push(setInterval(async () => {
      if (busy || !frames.length) return;
      busy = true;
      try {
        const { data } = await onboardingApi.preview(token, frames[frames.length - 1]);
        if (data.pose === challenge.steps[index]) {
          index += 1; setStepIndex(index);
          if (index >= challenge.steps.length) setTimeout(finish, 700);
        }
      } catch { /* the server re-checks every frame on submit */ } finally { busy = false; }
    }, 700));
    timers.current.push(setTimeout(finish, 25000)); // the server decides; this only bounds the recording
  }

  const live = ['positioning', 'challenge'].includes(phase);
  return <div className="ob-panel">
    <span className="ob-step-icon"><ScanFace size={20} /></span>
    <h2>Live selfie check</h2>
    <p className="ob-lead">We’ll ask you to move your head in a random order. This confirms a real person is present and matches your face to your photo.</p>
    <div className={`ob-camera ${live ? 'live' : ''}`}>
      {live ? <video ref={video} playsInline muted aria-label="Camera preview" /> : <div className="ob-camera-placeholder">{phase === 'comparing' ? <><Loader2 size={28} className="ob-spin" /><strong>Comparing your selfie with your photo…</strong></> : phase === 'denied' ? <><CameraOff size={28} /><strong>Camera access was blocked</strong></> : phase === 'unavailable' ? <><CameraOff size={28} /><strong>No camera available</strong></> : <><Camera size={28} /><strong>Your camera turns on only for this step</strong></>}</div>}
      {live && <div className={`ob-oval ${ready || phase === 'challenge' ? 'ok' : ''}`} aria-hidden="true" />}
      {phase === 'challenge' && <div className="ob-prompt" aria-live="assertive"><strong>{PROMPTS[steps[stepIndex]] || 'Done, hold on…'}</strong>
        <ol className="ob-steps-mini">{steps.map((s, i) => <li key={`${s}-${i}`} className={i < stepIndex ? 'done' : i === stepIndex ? 'current' : ''}>{s}</li>)}</ol></div>}
    </div>
    <canvas ref={canvas} hidden />
    {phase === 'positioning' && <p className="ob-hint" aria-live="polite">{hint || 'Centre your face in the oval…'}</p>}
    {phase === 'denied' && <div className="ob-alert error"><XCircle size={16} /><div><strong>Allow camera access to continue.</strong><span>Click the camera icon in your browser’s address bar, allow access, then try again.</span></div></div>}
    {phase === 'unavailable' && <div className="ob-alert error"><XCircle size={16} /><div><strong>We couldn’t use a camera on this device.</strong><span>It may be in use by another app. You can also continue on your phone: open FinGuard there and continue with Google. Your progress is saved for 24 hours.</span></div></div>}
    {error && <div className="ob-alert error" role="alert"><XCircle size={16} /><div><strong>{error}</strong></div></div>}
    <div className="ob-actions">
      {['intro', 'denied', 'unavailable', 'error'].includes(phase) && <button className="ob-btn primary" onClick={start}><Camera size={16} /> {phase === 'intro' ? 'Turn on camera' : 'Try again'}</button>}
      {phase === 'positioning' && <button className="ob-btn primary" disabled={!ready} onClick={runChallenge}>{ready ? 'Start the check' : 'Waiting for a clear view…'}</button>}
      {live && <button className="ob-btn ghost" onClick={() => { stop(); setPhase('intro'); }}>Cancel</button>}
      {['intro', 'denied', 'unavailable', 'error'].includes(phase) && <button className="ob-btn ghost" onClick={onChangePhoto}>Use a different photo</button>}
    </div>
    <p className="ob-muted">This is a lightweight automated check, not a guarantee. If it can’t confirm you, a person reviews it.</p>
  </div>;
}

export function OutcomePanel({ result, onRetry }) {
  const verified = result.outcome === 'VERIFIED'; const review = result.outcome === 'MANUAL_REVIEW';
  return <div className="ob-panel center">
    <span className={`ob-result-icon ${verified ? 'good' : review ? 'info' : 'bad'}`}>{verified ? <CheckCircle2 size={30} /> : review ? <ShieldCheck size={30} /> : <XCircle size={30} />}</span>
    <h2>{verified ? 'Identity verified' : review ? 'We’ll review your verification' : OUTCOME_TITLES[result.outcome] || 'Verification didn’t complete'}</h2>
    <p className="ob-lead">{result.message}</p>
    {!verified && !review && <><p className="ob-muted">{result.attempts_left} attempt{result.attempts_left === 1 ? '' : 's'} left.</p><button className="ob-btn primary" onClick={onRetry}>Try again</button></>}
  </div>;
}
