// Wholesaler Toolkit — Contracts UI (Phase 4).
// Sandboxed DocuSign only: every envelope send or void requires an explicit
// operator review. This page never exposes credentials or production controls.
const { useState: useStateCT, useEffect: useEffectCT, useMemo: useMemoCT } = React;

const CT_GREEN = "#22C55E", CT_BLUE = "#4F7CFF", CT_ORANGE = "#F59E0B", CT_RED = "#EF4444", CT_FAINT = "#64748B";
const CT_INPUT = {
  background: "var(--card-2)", border: "1px solid var(--border)", borderRadius: 8,
  padding: "9px 10px", color: "var(--text)", fontSize: 13, fontFamily: "inherit", width: "100%",
};

function CTstatusMeta(status) {
  const value = String(status || "pending").toLowerCase();
  if (value === "completed" || value === "signed") return { color: CT_GREEN, label: value };
  if (value === "sent") return { color: CT_BLUE, label: "awaiting signature" };
  if (value === "voided") return { color: CT_FAINT, label: "voided" };
  return { color: CT_ORANGE, label: "review needed" };
}

function CTStatusPill({ status }) {
  const meta = CTstatusMeta(status);
  return <span className="pill" style={{ color: meta.color, background: meta.color + "1c", border: "1px solid " + meta.color + "3b", fontSize: 10.5 }}>{meta.label}</span>;
}

function CTtime(value) {
  return value ? new Date(value).toLocaleString([], { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "—";
}

function CTDealPicker({ deals, templates, selectedId, templateType, onDeal, onTemplate, onCreate, busy }) {
  const templateRows = templates || [];
  const noDeals = !(deals || []).length;
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div><div className="faint" style={{ fontSize: 11, letterSpacing: 0.5, textTransform: "uppercase" }}>1 · Contract picker</div><div style={{ fontWeight: 700, fontSize: 16, marginTop: 4 }}>Prepare a sandbox contract for review</div><div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>Templates are read from the configured DocuSign demo account. No template is created or edited here.</div></div>
      {noDeals ? <div style={{ padding: "12px 0", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)", fontSize: 12.5 }}><div className="faint">No saved deals yet. Save a Deal Calc first, then return here to prefill a contract.</div><button className="tab" onClick={() => window.GoTo && window.GoTo("DealCalc")} style={{ marginTop: 9, minHeight: 38 }}>Open Deal Calc</button></div> : <>
        <label className="faint" style={{ fontSize: 11.5 }}>Deal<select value={selectedId} onChange={(event) => onDeal(event.target.value)} style={{ ...CT_INPUT, marginTop: 5 }}><option value="">Select a saved deal</option>{deals.map((deal) => <option key={deal.contactId} value={deal.contactId}>{deal.name || deal.contactId}{deal.address ? " · " + deal.address : ""}</option>)}</select></label>
        <label className="faint" style={{ fontSize: 11.5 }}>DocuSign template<select value={templateType} onChange={(event) => onTemplate(event.target.value)} style={{ ...CT_INPUT, marginTop: 5 }}>{templateRows.map((template) => <option key={template.type} value={template.type}>{template.name}{template.configured ? "" : " · not configured"}</option>)}</select></label>
        {templateRows.length > 0 && <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{templateRows.map((template) => <span key={template.type} className="pill" style={{ color: template.configured ? CT_GREEN : CT_FAINT, background: (template.configured ? CT_GREEN : CT_FAINT) + "15", border: "1px solid " + (template.configured ? CT_GREEN : CT_FAINT) + "32", fontSize: 10.5 }}>{template.type.toUpperCase()} · {template.configured ? "ready" : "needs template ID"}</span>)}</div>}
        <button className="tab active" onClick={onCreate} disabled={busy || !selectedId} style={{ alignSelf: "flex-start", minHeight: 42 }}>{busy ? "Preparing…" : "Generate & review"}</button>
      </>}
    </div>
  );
}

function CTPrefillPreview({ contract, onApprove, onVoid, onRefresh, checking }) {
  const Icons = window.Icons;
  if (!contract) return <div className="card card-pad" style={{ minHeight: 260, display: "grid", placeItems: "center", textAlign: "center" }}><div><div className="empty-ico" style={{ margin: "0 auto 12px" }}><Icons.Doc size={23} /></div><div style={{ fontWeight: 650 }}>Select a deal to preview its contract</div><div className="faint" style={{ fontSize: 12.5, marginTop: 5 }}>The review shows the exact fields that will prefill the selected template.</div></div></div>;
  const prefill = contract.prefill || {};
  const terms = prefill.terms || {};
  const state = String(contract.status || "pending");
  const canApprove = state === "pending";
  const canVoid = state === "pending" || state === "sent";
  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 15 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}><div><div className="faint" style={{ fontSize: 11, letterSpacing: 0.5, textTransform: "uppercase" }}>2 · Prefill preview</div><div style={{ fontSize: 17, fontWeight: 700, marginTop: 4 }}>{contract.dealName || contract.dealId}</div><div className="faint" style={{ fontSize: 12, marginTop: 3 }}>{contract.templateName} · {contract.address || prefill.propertyAddress || "Address pending"}</div></div><CTStatusPill status={state} /></div>
      {contract.templateType === "assignment" ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 9 }}>
          <CTField label="Assignee (signs)" value={prefill.signerName} /><CTField label="Assignee email" value={prefill.signerEmail} /><CTField label="Assignor" value={(prefill.tabs || {}).assignor_name} /><CTField label="Property" value={prefill.propertyAddress} /><CTField label="Assignment fee" value={prefill.assignmentFee} /><CTField label="Original purchase price" value={prefill.purchasePrice} /><CTField label="Original contract date" value={(prefill.tabs || {}).original_contract_date} /><CTField label="Closing date" value={terms.closingDate} />
        </div>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 9 }}>
          <CTField label="Signer" value={prefill.signerName} /><CTField label="Signer email" value={prefill.signerEmail} /><CTField label="Buyer" value={prefill.buyerName} /><CTField label="Property" value={prefill.propertyAddress} /><CTField label="Purchase price" value={prefill.purchasePrice} /><CTField label="Earnest money" value={terms.earnestMoney} /><CTField label="Closing date" value={terms.closingDate} /><CTField label="Title company" value={terms.titleCompany} />
        </div>
      )}
      {contract.sendError && <div style={{ color: CT_RED, background: CT_RED + "13", border: "1px solid " + CT_RED + "34", padding: "9px 11px", borderRadius: 9, fontSize: 12.5 }}>Last send attempt: {contract.sendError}</div>}
      {contract.envelopeId && <div className="faint mono" style={{ fontSize: 11 }}>Sandbox envelope: {contract.envelopeId}</div>}
      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 13, display: "flex", flexWrap: "wrap", gap: 8 }}>
        {canApprove && <button className="tab active" onClick={onApprove} style={{ minHeight: 40, display: "inline-flex", alignItems: "center", gap: 7 }}><Icons.Send size={14} /> Send for signature</button>}
        {state === "sent" && <button className="tab" onClick={onRefresh} disabled={checking} style={{ minHeight: 40 }}>{checking ? "Checking…" : "Check DocuSign status"}</button>}
        {canVoid && <button className="tab" onClick={onVoid} style={{ minHeight: 40, color: CT_RED }}>Void contract</button>}
        {!canApprove && state !== "sent" && <span className="faint" style={{ fontSize: 12, alignSelf: "center" }}>Lifecycle updates are recorded from DocuSign; this version never creates a duplicate envelope.</span>}
      </div>
    </div>
  );
}

function CTField({ label, value }) {
  return <div style={{ padding: 10, border: "1px solid var(--border)", borderRadius: 9, background: "var(--card-2)", minWidth: 0 }}><div className="faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.35 }}>{label}</div><div style={{ fontSize: 12.5, lineHeight: 1.35, fontWeight: 550, marginTop: 4, overflowWrap: "anywhere" }}>{value || "—"}</div></div>;
}

function CTApprovalModal({ contract, mode, onClose, onDone }) {
  const [operatorId, setOperatorId] = useStateCT("");
  const [reason, setReason] = useStateCT("");
  const [busy, setBusy] = useStateCT(false);
  const [error, setError] = useStateCT(null);
  const isVoid = mode === "void";
  const heading = isVoid ? "Reject & void contract" : "Approve sandbox send";
  const action = isVoid ? "Void contract" : "Approve & send";
  async function submit() {
    if (!isVoid && !operatorId.trim()) { setError("Enter the operator ID that reviewed this contract."); return; }
    const confirmation = isVoid ? "Void this contract in the sandbox?" : "Send this contract through DocuSign's sandbox to " + ((contract.prefill || {}).signerEmail || "the signer") + "?";
    if (!window.confirm(confirmation)) return;
    setBusy(true); setError(null);
    try {
      const response = await window.apiPost(isVoid ? "/api/toolkit/contracts/void" : "/api/toolkit/contracts/send", isVoid ? { dealId: contract.dealId, reason } : { dealId: contract.dealId, operatorId, reason });
      onDone(response.contract || response);
      onClose();
    } catch (err) { setError(err.message || String(err)); }
    finally { setBusy(false); }
  }
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 72, background: "rgba(3,8,18,0.72)", display: "grid", placeItems: "center", padding: 16 }}><div onClick={(event) => event.stopPropagation()} className="card" style={{ width: 500, maxWidth: "100%", padding: 20 }}><div className="faint" style={{ fontSize: 11, letterSpacing: 0.5, textTransform: "uppercase" }}>{isVoid ? "Operator decision" : "Required approval"}</div><h2 style={{ fontSize: 19, marginTop: 4 }}>{heading}</h2><p className="faint" style={{ fontSize: 12.5, lineHeight: 1.5, marginTop: 6 }}>{isVoid ? "This records the void locally and, if it was already sent, asks only the DocuSign sandbox to void its envelope." : "This is the final operator gate. It sends one sandbox envelope; production is disabled."}</p>{!isVoid && <label className="faint" style={{ display: "block", fontSize: 11.5, marginTop: 14 }}>Operator ID<input value={operatorId} onChange={(event) => setOperatorId(event.target.value)} placeholder="Your name or operator ID" style={{ ...CT_INPUT, marginTop: 5 }} /></label>}<label className="faint" style={{ display: "block", fontSize: 11.5, marginTop: 13 }}>{isVoid ? "Reason for void" : "Approval note (optional)"}<textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} placeholder={isVoid ? "Why is this contract being voided?" : "Review notes for the contract ledger"} style={{ ...CT_INPUT, marginTop: 5, resize: "vertical", lineHeight: 1.45 }} /></label>{error && <div style={{ color: CT_RED, fontSize: 12.5, marginTop: 10 }}>{error}</div>}<div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}><button className="tab" onClick={onClose} disabled={busy} style={{ minHeight: 40 }}>Cancel</button><button className="tab active" onClick={submit} disabled={busy} style={{ minHeight: 40, background: isVoid ? CT_RED : undefined }}>{busy ? "Submitting…" : action}</button></div></div></div>
  );
}

function CTContractList({ contracts, activeId, onSelect }) {
  const rows = contracts || [];
  return (
    <div className="card" style={{ overflow: "hidden" }}><div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", gap: 10 }}><div style={{ fontWeight: 700, fontSize: 14 }}>Contract ledger</div><span className="faint tabnum" style={{ fontSize: 12 }}>{rows.length}</span></div>{!rows.length ? <div className="empty"><img src="assets/empty-contracts.png" alt="Empty contracts illustration" style={{ width: "min(160px, 60vw)", height: "auto", opacity: 0.85 }} /><div style={{ fontWeight: 650, color: "var(--text)" }}>No contracts yet</div><div style={{ fontSize: 12 }}>Use the picker to create a reviewable sandbox draft.</div></div> : <div style={{ overflowX: "auto" }}><table className="lead-table" style={{ minWidth: 720 }}><thead><tr><th>Deal</th><th>Template</th><th>Status</th><th>Updated</th><th></th></tr></thead><tbody>{rows.map((contract) => <tr key={contract.dealId} style={{ background: activeId === contract.dealId ? "rgba(79,124,255,0.07)" : "transparent" }}><td><div style={{ fontWeight: 600 }}>{contract.dealName || contract.dealId}</div><div className="faint" style={{ fontSize: 11 }}>{contract.address || "—"}</div></td><td>{contract.templateName}</td><td><CTStatusPill status={contract.status} /></td><td className="faint" style={{ fontSize: 12 }}>{CTtime(contract.updatedAt)}</td><td><button className="tab" onClick={() => onSelect(contract)} style={{ minHeight: 34 }}>View</button></td></tr>)}</tbody></table></div>}</div>
  );
}

// Quick Send — upload YOUR contract file once, then fire it to any seller with
// name/email/address/price. DocuSign (sandbox) emails the signing link; the
// envelope records into the same ledger below.
function CTQuickSend({ onSent }) {
  const Icons = window.Icons;
  const tpl = window.useApi("/api/toolkit/contracts/mytemplates", { interval: 60000 });
  const templates = (tpl.data && tpl.data.templates) || [];
  const [picked, setPicked] = useStateCT("");
  const [uploading, setUploading] = useStateCT(false);
  const [form, setForm] = useStateCT({ sellerName: "", sellerEmail: "", address: "", price: "", closingDate: "", notes: "" });
  const [sending, setSending] = useStateCT(false);
  const [note, setNote] = useStateCT(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const activeTpl = templates.find((t) => t.id === picked) || null;
  const canSend = activeTpl && form.sellerName.trim() && form.sellerEmail.includes("@") && !sending;

  function onFile(files) {
    const f = (files || [])[0];
    if (!f) return;
    setUploading(true); setNote(null);
    const rd = new FileReader();
    rd.onerror = () => { setUploading(false); setNote({ ok: false, text: "Couldn't read that file." }); };
    rd.onload = async () => {
      try {
        const r = await window.apiPost("/api/toolkit/contracts/template/upload",
          { name: f.name.replace(/\.(pdf|docx?|)$/i, ""), file: rd.result });
        if (r && r.ok) { tpl.refresh(); setPicked(r.template.id); setNote({ ok: true, text: "Template saved." }); }
        else setNote({ ok: false, text: (r && r.error) || "Upload failed." });
      } catch (e) { setNote({ ok: false, text: e.message || "Upload failed." }); }
      setUploading(false);
    };
    rd.readAsDataURL(f);
  }

  async function delTpl(t) {
    if (!window.confirm('Delete template "' + t.name + '"?')) return;
    try {
      await window.apiPost("/api/toolkit/contracts/template/delete", { id: t.id });
      if (picked === t.id) setPicked("");
      tpl.refresh();
    } catch (e) { setNote({ ok: false, text: e.message }); }
  }

  async function send() {
    if (!canSend) return;
    const op = window.prompt('Email "' + activeTpl.name + '" to ' + form.sellerName.trim()
      + " <" + form.sellerEmail.trim() + ">?\n\nType YOUR name to approve the send:");
    if (!op || !op.trim()) return;
    setSending(true); setNote(null);
    try {
      const r = await window.apiPost("/api/toolkit/contracts/quicksend",
        { templateId: activeTpl.id, operatorId: op.trim(),
          sellerName: form.sellerName.trim(), sellerEmail: form.sellerEmail.trim(),
          address: form.address.trim(), price: form.price.trim(),
          closingDate: form.closingDate.trim(), notes: form.notes.trim() });
      if (r && r.ok) {
        setNote({ ok: true, text: "Sent — DocuSign emailed " + form.sellerEmail.trim() + ". It's in the ledger below." });
        setForm({ sellerName: "", sellerEmail: "", address: "", price: "", closingDate: "", notes: "" });
        if (onSent) onSent();
      } else setNote({ ok: false, text: (r && r.error) || "Send failed." });
    } catch (e) { setNote({ ok: false, text: e.message || "Send failed." }); }
    setSending(false);
  }

  return (
    <div className="card card-pad" style={{ display: "flex", flexDirection: "column", gap: 13 }}>
      <div>
        <div className="faint" style={{ fontSize: 11, letterSpacing: 0.5, textTransform: "uppercase" }}>Quick send · your own contract</div>
        <div style={{ fontWeight: 700, fontSize: 16, marginTop: 4 }}>Upload a template → email a seller in seconds</div>
        <div className="faint" style={{ fontSize: 12.5, marginTop: 4 }}>The seller signs free-form on your document (no field mapping). Price + closing ride in the email.</div>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {templates.map((t) => (
          <span key={t.id} className="pill"
            onClick={() => setPicked(t.id)}
            style={{ cursor: "pointer", fontSize: 11, display: "inline-flex", alignItems: "center", gap: 6,
              color: picked === t.id ? "#fff" : "var(--text-2)",
              background: picked === t.id ? CT_BLUE : "var(--card-2)",
              border: "1px solid " + (picked === t.id ? CT_BLUE : "var(--border)") }}>
            {t.name} · {(t.ext || "pdf").toUpperCase()}
            <span onClick={(e) => { e.stopPropagation(); delTpl(t); }} style={{ opacity: 0.75, fontWeight: 800 }}>✕</span>
          </span>
        ))}
        <label className="tab" style={{ minHeight: 34, display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <Icons.Doc size={13} /> {uploading ? "Uploading…" : "Upload template"}
          <input type="file" accept="application/pdf,.pdf,.doc,.docx" style={{ display: "none" }}
            onChange={(e) => { onFile(e.target.files); e.target.value = ""; }} />
        </label>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 9 }}>
        <input value={form.sellerName} onChange={set("sellerName")} placeholder="Seller full name" style={CT_INPUT} />
        <input value={form.sellerEmail} onChange={set("sellerEmail")} placeholder="Seller email" style={CT_INPUT} />
        <input value={form.address} onChange={set("address")} placeholder="Property address" style={CT_INPUT} />
        <input value={form.price} onChange={set("price")} placeholder="Price ($)" style={CT_INPUT} />
        <input value={form.closingDate} onChange={set("closingDate")} placeholder="Closing date" style={CT_INPUT} />
        <input value={form.notes} onChange={set("notes")} placeholder="Email note (optional)" style={CT_INPUT} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button className="tab active" onClick={send} disabled={!canSend}
          style={{ minHeight: 42, display: "inline-flex", alignItems: "center", gap: 7 }}>
          <Icons.Send size={14} /> {sending ? "Sending…" : "Email contract for signature"}
        </button>
        {note && <span style={{ fontSize: 12.5, color: note.ok ? CT_GREEN : CT_RED }}>{note.ok ? "✓ " : ""}{note.text}</span>}
      </div>
    </div>
  );
}

function CTContractsPage() {
  const Icons = window.Icons;
  const contractsApi = window.useApi("/api/toolkit/contracts/list", { interval: 20000 });
  const templatesApi = window.useApi("/api/toolkit/contracts/templates", { interval: 60000 });
  const dealsApi = window.useApi("/api/deals/list", { interval: 30000 });
  const [selectedDealId, setSelectedDealId] = useStateCT("");
  const [templateType, setTemplateType] = useStateCT("sfr");
  const [activeContract, setActiveContract] = useStateCT(null);
  const [decisionMode, setDecisionMode] = useStateCT(null);
  const [creating, setCreating] = useStateCT(false);
  const [checking, setChecking] = useStateCT(false);
  const [message, setMessage] = useStateCT(null);
  const contracts = (contractsApi.data && contractsApi.data.contracts) || [];
  const templates = (templatesApi.data && templatesApi.data.templates) || [];
  const deals = (dealsApi.data && dealsApi.data.deals) || [];
  const selectedDeal = useMemoCT(() => deals.find((deal) => String(deal.contactId) === String(selectedDealId)) || null, [deals, selectedDealId]);

  useEffectCT(() => { if (!selectedDealId && deals.length) setSelectedDealId(String(deals[0].contactId)); }, [deals.length, selectedDealId]);
  useEffectCT(() => { if (!templates.some((template) => template.type === templateType) && templates.length) setTemplateType(templates[0].type); }, [templates, templateType]);
  useEffectCT(() => { if (!activeContract && contracts.length) setActiveContract(contracts[0]); }, [contracts, activeContract]);

  function refreshAll() { contractsApi.refresh(); templatesApi.refresh(); dealsApi.refresh(); }
  function selectedContract(record) { setActiveContract(record); setMessage(null); }
  async function create() {
    if (!selectedDeal) return;
    setCreating(true); setMessage(null);
    try {
      const response = await window.apiPost("/api/toolkit/contracts/create", { dealId: selectedDeal.contactId, deal: selectedDeal, templateType, approvalRequired: true });
      selectedContract(response); refreshAll(); setMessage({ ok: true, text: "Draft created. Review the prefilled fields before approval." });
    } catch (err) { setMessage({ ok: false, text: err.message || String(err) }); }
    finally { setCreating(false); }
  }
  async function checkStatus() {
    if (!activeContract) return;
    setChecking(true); setMessage(null);
    try {
      const response = await window.apiGet("/api/toolkit/contracts/status?dealId=" + encodeURIComponent(activeContract.dealId));
      if (response.contract) selectedContract(response.contract);
      refreshAll(); setMessage({ ok: true, text: response.checked ? "Sandbox status checked." : "No envelope requires a status check yet." });
    } catch (err) { setMessage({ ok: false, text: err.message || String(err) }); }
    finally { setChecking(false); }
  }
  function decisionDone(record) { selectedContract(record); refreshAll(); setMessage({ ok: true, text: record.status === "voided" ? "Contract voided." : "Sandbox envelope sent for signature." }); }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}><div><h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: "-0.5px" }}>Contracts</h1><p className="faint" style={{ fontSize: 13.5, marginTop: 4 }}>Template-based DocuSign e-signature · operator-approved · sandbox only</p></div><div style={{ display: "flex", alignItems: "center", gap: 8 }}><span className="pill" style={{ color: CT_ORANGE, background: CT_ORANGE + "18", border: "1px solid " + CT_ORANGE + "35", fontSize: 10.5 }}>Sandbox only</span><button className="tab" onClick={refreshAll} style={{ minHeight: 36, display: "inline-flex", alignItems: "center", gap: 6 }}><Icons.Activity size={13} /> Refresh</button></div></div>
      <div style={{ padding: "10px 13px", borderRadius: 11, background: CT_ORANGE + "12", border: "1px solid " + CT_ORANGE + "35", fontSize: 12.5, color: "var(--text-2)" }}>Production DocuSign is intentionally disabled until RSA key rotation and secure box-secret setup are complete. No credential is stored or displayed in this dashboard.</div>
      {(contractsApi.error || templatesApi.error || dealsApi.error) && <window.ErrorRow error={contractsApi.error || templatesApi.error || dealsApi.error} onRetry={refreshAll} />}
      {message && <div style={{ padding: "10px 12px", borderRadius: 10, color: message.ok ? CT_GREEN : CT_RED, border: "1px solid " + (message.ok ? CT_GREEN : CT_RED) + "36", background: (message.ok ? CT_GREEN : CT_RED) + "12", fontSize: 12.5 }}>{message.text}</div>}
      <CTQuickSend onSent={refreshAll} />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 0.78fr) minmax(0, 1.22fr)", gap: 16, alignItems: "start" }}><CTDealPicker deals={deals} templates={templates} selectedId={selectedDealId} templateType={templateType} onDeal={setSelectedDealId} onTemplate={setTemplateType} onCreate={create} busy={creating} /><CTPrefillPreview contract={activeContract} onApprove={() => setDecisionMode("send")} onVoid={() => setDecisionMode("void")} onRefresh={checkStatus} checking={checking} /></div>
      <CTContractList contracts={contracts} activeId={activeContract && activeContract.dealId} onSelect={selectedContract} />
      {decisionMode && activeContract && <CTApprovalModal contract={activeContract} mode={decisionMode} onClose={() => setDecisionMode(null)} onDone={decisionDone} />}
    </div>
  );
}

Object.assign(window, { CTContractsPage });
