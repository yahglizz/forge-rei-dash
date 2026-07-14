// daycare_blast.jsx — Family Text Blast: SMS to parents' phones via GoHighLevel.
// Reaches families who never open the parent app. Every send is operator-gated:
// nothing goes out until the owner reads the real rendered texts and confirms.
const { useState: useStateDcb, useMemo: useMemoDcb } = React;

const DCB_TOKENS = [
  { token: "{first_name}", hint: "Maria" },
  { token: "{child}", hint: "Ava and Noah" },
  { token: "{center}", hint: "your center's name" },
];

function DcbSegments({ text, max }) {
  const length = (text || "").length;
  const segments = length ? Math.ceil(length / 160) : 0;
  const over = length > max;
  return <small className={over ? "dc-error-text" : "faint"}>{length}/{max} characters · {segments} SMS segment{segments === 1 ? "" : "s"}{over ? " — too long" : ""}</small>;
}

function DcbSendModal({ blast, sending, onClose, onConfirm }) {
  const recipients = blast.recipients || [];
  return <window.DcxModal title={"Send to " + recipients.length + " famil" + (recipients.length === 1 ? "y" : "ies") + "?"} copy="This texts real phone numbers through GoHighLevel. Read the messages below — this is exactly what each family receives." onClose={onClose}>
    <div className="dc-form-hint warn"><window.Icons.Bell size={14}/> Outward action. Nothing has been sent yet.</div>
    {blast.skippedOptOut > 0 && <div className="dc-form-hint">{blast.skippedOptOut} opted-out famil{blast.skippedOptOut === 1 ? "y is" : "ies are"} being skipped.</div>}
    <div className="dc-blast-preview">
      {recipients.map((person) => <div className="dc-blast-bubble" key={person.key}>
        <div className="dc-blast-bubble-head"><b>{person.name}</b><small>{person.phone}</small></div>
        <p>{person.text}</p>
      </div>)}
    </div>
    <div className="dc-modal-actions">
      <button className="dc-quiet" onClick={onClose}>Cancel</button>
      <button className="dc-primary" disabled={sending} onClick={onConfirm}>
        <window.Icons.Send size={14}/> {sending ? "Sending…" : "Send to " + recipients.length + " famil" + (recipients.length === 1 ? "y" : "ies")}
      </button>
    </div>
  </window.DcxModal>;
}

function DaycareBlast() {
  const [room, setRoom] = useStateDcb("");
  const blastResource = window.DcxUseResource(room ? "/blast?classroom=" + encodeURIComponent(room) : "/blast", null, 20000);
  const payload = (blastResource.data && !Array.isArray(blastResource.data)) ? blastResource.data : {};
  const audience = payload.audience || [];
  const classrooms = payload.classrooms || [];
  const blasts = payload.blasts || [];
  const optOuts = payload.optOuts || [];
  const missingPhone = payload.missingPhone || [];
  const ghl = payload.ghl || {};
  const maxChars = payload.maxChars || 480;
  const connected = Boolean(ghl.connected);

  const [title, setTitle] = useStateDcb("");
  const [template, setTemplate] = useStateDcb("");
  const [staged, setStaged] = useStateDcb(null);
  const [sending, setSending] = useStateDcb(false);
  const [busy, setBusy] = useStateDcb(false);
  const [error, setError] = useStateDcb("");
  const [flash, setFlash] = useStateDcb("");

  const roomName = useMemoDcb(() => {
    const match = classrooms.find((entry) => String(entry.id) === String(room));
    return match ? match.name : "All families";
  }, [room, classrooms]);

  // Local mirror of the server's renderer so the composer previews without a round-trip.
  const sample = audience[0];
  const preview = useMemoDcb(() => {
    if (!sample) return "";
    const kids = sample.children || [];
    const child = kids.length === 1 ? kids[0] : (kids.length === 2 ? kids[0] + " and " + kids[1] : (kids.length ? kids.slice(0, -1).join(", ") + ", and " + kids[kids.length - 1] : "your little one"));
    return (template || "")
      .replace(/\{first_name\}/g, sample.firstName || "there")
      .replace(/\{name\}/g, sample.name || "Family")
      .replace(/\{child(ren)?\}/g, child)
      .replace(/\{center\}/g, payload.centerName || "A Touch of Blessings");
  }, [template, sample, payload.centerName]);

  const insert = (token) => setTemplate((current) => (current ? current + " " : "") + token);

  const stage = async () => {
    setError("");
    if (!title.trim() || !template.trim()) { setError("Give the blast a name and write the message."); return; }
    setBusy(true);
    try {
      const created = await window.DcxRequest("/blast/create", { body: {
        title: title.trim(), template: template.trim(),
        classroom_id: room || null, audience_label: roomName,
      }});
      if (created.error) { setError(created.error); return; }
      setStaged(created.blast || created);
    } catch (requestError) { setError(requestError.message); }
    finally { setBusy(false); }
  };

  const confirmSend = async () => {
    setSending(true);
    try {
      const result = await window.DcxRequest("/blast/send", { body: { blast_id: staged.id } });
      const summary = result.summary || {};
      setStaged(null); setTitle(""); setTemplate("");
      setFlash("Sent to " + (summary.sent || 0) + " famil" + ((summary.sent === 1) ? "y" : "ies") + (summary.failed ? " · " + summary.failed + " failed" : "") + (summary.skipped ? " · " + summary.skipped + " skipped" : ""));
      blastResource.refresh();
    } catch (requestError) { setError(requestError.message); }
    finally { setSending(false); }
  };

  const cancelStaged = async () => {
    try { await window.DcxRequest("/blast/cancel", { body: { blast_id: staged.id } }); } catch (_) { /* queued-only cleanup */ }
    setStaged(null); blastResource.refresh();
  };

  const toggleOptOut = async (phone, name, optedOut) => {
    try {
      await window.DcxRequest("/blast/optout", { body: { phone, name, opted_out: optedOut } });
      blastResource.refresh();
    } catch (requestError) { window.alert(requestError.message); }
  };

  return <div className="dc-page">
    <window.DcxPageHead title="Text Blast" eyebrow="FAMILIES · SMS" copy="Text every family's phone through GoHighLevel — reaches parents who never open the app."/>

    {!connected && <div className="card card-pad dc-form-hint warn">
      <window.Icons.Bell size={14}/> GoHighLevel isn't connected — {ghl.detail || "add GHL_API_KEY + GHL_LOCATION_ID to daycare.env"}. You can draft a blast, but sending is disabled until it's wired.
    </div>}
    {flash && <div className="card card-pad dc-saved">{flash}</div>}

    <div className="dc-main-grid">
      <section>
        <div className="card card-pad">
          <div className="dc-panel-head">
            <div><div className="card-title">Compose</div><div className="faint">Goes to phones, not the app inbox</div></div>
            <span className="dc-week">{audience.length} famil{audience.length === 1 ? "y" : "ies"} · {roomName}</span>
          </div>
          {error && <div className="dc-form-error">{error}</div>}
          <div className="dc-form-grid">
            <window.DcxField label="Blast name" wide>
              <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Snow day closure"/>
            </window.DcxField>
            <window.DcxField label="Audience" wide>
              <select value={room} onChange={(event) => setRoom(event.target.value)}>
                <option value="">All families ({payload.totalFamilies || 0})</option>
                {classrooms.map((entry) => <option key={entry.id} value={entry.id}>{entry.name} ({entry.families})</option>)}
              </select>
            </window.DcxField>
            <window.DcxField label="Message" wide>
              <textarea rows="5" value={template} onChange={(event) => setTemplate(event.target.value)} placeholder="Hi {first_name}, the center is closed today for snow. {child} can return tomorrow at our normal time. — {center}"/>
              <DcbSegments text={template} max={maxChars}/>
            </window.DcxField>
          </div>
          <div className="dc-blast-tokens">
            <small className="faint">Insert:</small>
            {DCB_TOKENS.map((entry) => <button key={entry.token} className="dc-quiet" onClick={() => insert(entry.token)} title={"becomes: " + entry.hint}>{entry.token}</button>)}
          </div>
          {preview && <div className="dc-blast-bubble sample">
            <div className="dc-blast-bubble-head"><b>Preview — {sample.name}</b><small>{sample.phone}</small></div>
            <p>{preview}</p>
          </div>}
          <div className="dc-settings-actions">
            <button className="dc-primary" disabled={busy || !audience.length || !connected} onClick={stage}>
              <window.Icons.Send size={14}/> {busy ? "Preparing…" : "Review " + audience.length + " message" + (audience.length === 1 ? "" : "s")}
            </button>
          </div>
        </div>

        <div className="dc-section-title"><b>Sent blasts</b><span>{blasts.length}</span></div>
        <window.DcxState loading={blastResource.loading} error={blastResource.error} onRetry={blastResource.refresh} empty={!blasts.length} icon="Send" title="No blasts yet" copy="Your first family text blast will show up here with per-family delivery status."/>
        <div className="dc-announcement-list">
          {blasts.map((entry) => {
            const sent = (entry.recipients || []).filter((person) => person.status === "sent" || person.status === "stub-sent").length;
            const failed = (entry.recipients || []).filter((person) => person.status === "failed").length;
            return <article className="card card-pad" key={entry.id}>
              <div className="dc-announcement-head">
                <div><h3>{entry.title}</h3><small>{entry.audience} · {window.DcxDate(entry.createdAt, true)}</small></div>
                <span className={"dc-week " + (entry.status === "sent" ? "" : entry.status)}>{entry.status}</span>
              </div>
              <p>{entry.template}</p>
              <small className="faint">{sent} delivered{failed ? " · " + failed + " failed" : ""}{entry.skippedOptOut ? " · " + entry.skippedOptOut + " opted out" : ""}</small>
            </article>;
          })}
        </div>
      </section>

      <aside>
        <div className="dc-section-title"><b>Do not text</b><span>{optOuts.length}</span></div>
        <div className="card card-pad">
          <p className="faint">Families here are skipped by every blast. Add anyone who asks to stop.</p>
          {optOuts.map((entry) => <div className="dc-row-actions" key={entry.key} style={{ justifyContent: "space-between" }}>
            <span>{entry.name || entry.phone}</span>
            <button onClick={() => toggleOptOut(entry.phone, entry.name, false)}>Allow again</button>
          </div>)}
          {!optOuts.length && <small className="faint">Nobody opted out.</small>}
          <div className="dc-section-title" style={{ marginTop: 12 }}><b>Add</b></div>
          {audience.map((person) => <div className="dc-row-actions" key={person.key} style={{ justifyContent: "space-between" }}>
            <span>{person.name}</span>
            <button className="danger" onClick={() => toggleOptOut(person.phone, person.name, true)}>Stop texts</button>
          </div>)}
        </div>

        {missingPhone.length > 0 && <div>
          <div className="dc-section-title"><b>No phone on file</b><span>{missingPhone.length}</span></div>
          <div className="card card-pad">
            <p className="faint">These families can't be reached by text — add a phone on their profile.</p>
            {missingPhone.map((entry, index) => <div key={index}><b>{entry.guardianName}</b> <small className="faint">({entry.childName})</small></div>)}
          </div>
        </div>}
      </aside>
    </div>

    {staged && <DcbSendModal blast={staged} sending={sending} onClose={cancelStaged} onConfirm={confirmSend}/>}
  </div>;
}

Object.assign(window, { DaycareBlast });
