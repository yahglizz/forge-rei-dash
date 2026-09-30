// Orion's 3D office and browser voice controls; all assignments use the real office API.
const { useState: useStateOO, useEffect: useEffectOO, useRef: useRefOO } = React;

function OrionOfficeFloor({ state, selected, onSelect, mode }) {
  const host = useRefOO(null), latest = useRefOO(null);
  const [status, setStatus] = useStateOO('Loading Orion…');
  const [focus, setFocus] = useStateOO(false);
  latest.current = { ...(state || {}), selected, orionMode: mode, focusOrion: focus };
  useEffectOO(() => {
    let dead = false, dispose;
    window.loadOrionOfficeScene().then(m => {
      if (!dead) return m.createOfficeScene(host.current, () => latest.current, onSelect, s => { if (!dead) setStatus(s); });
    }).then(cleanup => { if (dead && cleanup) cleanup(); else dispose = cleanup; })
      .catch(e => { console.warn('Orion office:', e); if (!dead) setStatus('3D is unavailable in this browser. Use Pixel view.'); });
    return () => { dead = true; if (dispose) dispose(); };
  }, []);
  return <div className="orion-stage">
    <div ref={host} className="orion-canvas" />
    <div className="orion-camera-controls orion-controls"><button className="btn" aria-pressed={!focus} onClick={() => setFocus(false)}>Whole office</button><button className="btn" aria-pressed={focus} onClick={() => setFocus(true)}>Focus Orion</button></div>
    <div className="orion-stage-caption"><span>ORION / COMMAND OFFICE</span><span role="status">{status === 'Ready' ? 'Live agent activity' : status}</span></div>
  </div>;
}

function OrionOfficePanel({ state, onMode, onRefresh }) {
  const [text, setText] = useStateOO(''), [msgs, setMsgs] = useStateOO([]);
  const [busy, setBusy] = useStateOO(false), [error, setError] = useStateOO('');
  const [proposal, setProposal] = useStateOO(null), [voice, setVoice] = useStateOO(false);
  const [listening, setListening] = useStateOO(false), [speaking, setSpeaking] = useStateOO(false);
  const recognition = useRefOO(null), mounted = useRefOO(true), end = useRefOO(null), inFlight = useRefOO(false);
  const agents = ((state && state.departments) || []).flatMap(d => d.agents || []);
  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  useEffectOO(() => {
    window.apiGet('/api/hub/history?agent=orion').then(d => { if (mounted.current) setMsgs(Array.isArray(d.messages) ? d.messages : []); }).catch(() => {});
    return () => {
      mounted.current = false;
      if (recognition.current) recognition.current.abort();
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      onMode('idle');
    };
  }, []);
  useEffectOO(() => { if (end.current) end.current.scrollIntoView({ block: 'nearest' }); }, [msgs, busy]);
  function say(reply) {
    if (!voice || !window.speechSynthesis) { onMode('idle'); return; }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(reply); utterance.rate = 1.02;
    utterance.onstart = () => { if (mounted.current) { setSpeaking(true); onMode('speaking'); } };
    utterance.onend = utterance.onerror = () => { if (mounted.current) { setSpeaking(false); onMode('idle'); } };
    window.speechSynthesis.speak(utterance);
  }
  function stopSpeech() { window.speechSynthesis.cancel(); setSpeaking(false); onMode('idle'); }
  function listen() {
    if (listening) { if (recognition.current) recognition.current.stop(); return; }
    if (!Speech) return;
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    const r = new Speech(); recognition.current = r; r.lang = 'en-US'; r.interimResults = false;
    r.onresult = e => { if (mounted.current) setText(e.results[0][0].transcript); };
    r.onerror = e => { if (mounted.current) setError('Microphone: ' + e.error + '. You can type your message.'); };
    r.onend = () => { if (mounted.current) setListening(false); };
    setError(''); setListening(true);
    try { r.start(); } catch (e) { setListening(false); setError(String(e.message || e)); }
  }
  async function send(plan = false) {
    const message = text.trim(); if (!message || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); onMode('thinking');
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    setSpeaking(false); setText(''); setMsgs(m => m.concat([{ role: 'user', text: message }]));
    try {
      const d = await window.apiPost(plan ? '/api/office/plan' : '/api/hub/chat', plan ? { message } : { agentId: 'orion', message });
      if (!mounted.current) return;
      if (d.error || d.needsKey) throw new Error(d.error || d.reply || 'Orion needs an AI key.');
      const reply = plan ? d.summary : d.reply;
      setMsgs(m => m.concat([{ role: 'agent', text: reply }]));
      if (plan) setProposal({ ...d, request: message });
      say(reply || 'Ready.');
    } catch (e) { if (mounted.current) { setError(String(e.message || e)); setText(message); onMode('idle'); } }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }
  async function approve() {
    if (!proposal || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    const remaining = [], accepted = [];
    // Each successful assignment is removed immediately: retry never repeats an accepted job.
    for (const assignment of proposal.assignments) {
      try {
        const d = await window.apiPost('/api/office/task', { ...assignment, directedBy: 'orion', note: (assignment.note + '\nOwner request: ' + proposal.request).slice(0, 4000) });
        if (d.error || !d.jobId) throw new Error(d.error || 'No job was created');
        accepted.push(assignment.agentId);
      } catch (e) { remaining.push(assignment); if (mounted.current) setError(String(e.message || e)); }
      if (!mounted.current) break;
    }
    if (mounted.current) {
      setProposal(remaining.length ? { ...proposal, assignments: remaining } : null);
      if (accepted.length) setMsgs(m => m.concat([{ role: 'agent', text: 'Assignments started: ' + accepted.map(id => (agents.find(a => a.id === id) || {}).name || id).join(', ') + '. Watch their live progress on the floor.' }]));
      onRefresh(); setBusy(false);
    }
    inFlight.current = false;
  }
  return <div className="card orion-panel">
    <div className="orion-panel-head"><img src="/assets/orion/preview.png" alt="Orion, your kid CEO character" /><div><strong>Talk to Orion</strong><div className="faint">Chief of Staff · your live team</div></div></div>
    <div className="orion-conversation" aria-live="polite">
      {!msgs.length && <div className="faint">Ask what needs attention, or tell Orion what you want the team to work on.</div>}
      {msgs.map((m, i) => <div className={'orion-message ' + (m.role === 'user' ? 'mine' : '')} key={i}><small>{m.role === 'user' ? 'You' : 'Orion'}</small><div>{m.text}</div></div>)}
      {busy && <div className="faint" role="status">Orion is working…</div>}<div ref={end} />
    </div>
    {proposal && <div className="orion-plan"><strong>Review assignments</strong>{proposal.assignments.map(a => <div key={a.agentId}><b>{(agents.find(x => x.id === a.agentId) || {}).name || a.agentId}</b><p>{a.title}</p>{a.note && <small>{a.note}</small>}</div>)}
      <div className="orion-controls"><button className="btn btn-primary" disabled={busy || !proposal.assignments.length} onClick={approve}>Approve & assign</button><button className="btn" disabled={busy} onClick={() => setProposal(null)}>Dismiss</button></div></div>}
    {error && <div role="alert" className="hub-error">{error}</div>}
    <textarea className="input" aria-label="Message Orion" rows={2} maxLength={4000} value={text} onChange={e => setText(e.target.value)} placeholder="Orion, what needs attention today?" onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(); }} />
    <div className="orion-controls"><button className="btn btn-primary" disabled={busy || !text.trim()} onClick={() => send()}>Send</button><button className="btn" disabled={busy || !text.trim()} onClick={() => send(true)}>Plan team tasks</button>{Speech && <button className="btn" aria-pressed={listening} disabled={busy} onClick={listen}>{listening ? 'Stop mic' : 'Microphone'}</button>}</div>
    <div className="orion-controls"><label className="faint"><input type="checkbox" checked={voice} disabled={!window.speechSynthesis} onChange={e => { setVoice(e.target.checked); if (!e.target.checked) stopSpeech(); }} /> Spoken replies</label>{speaking && <button className="btn" onClick={stopSpeech}>Stop speaking</button>}</div>
    {!Speech && <small className="faint">Microphone dictation is unavailable here; type to chat.</small>}
  </div>;
}
Object.assign(window, { OrionOfficeFloor, OrionOfficePanel });
