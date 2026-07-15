// dropship_orders.jsx — Orders (Shopify) + Customers/Support (Otto: fulfillment + reply drafts).
const { useState: useStateDso } = React;

function DsoBadge({ value, map }) {
  const color = (map || {})[value] || "#64748B";
  return <span className="pill" style={{ color, background: color + "22" }}>{value || "—"}</span>;
}

function DropshipOrders() {
  const orders = window.DsUseResource("/orders", null, 30000);
  const rows = (orders.data && orders.data.orders) || [];
  const configured = orders.data && orders.data.configured;
  const unfulfilled = (orders.data && orders.data.unfulfilled) || 0;
  const finMap = { paid: "#22C55E", pending: "#F4B860", refunded: "#F87171", voided: "#64748B" };
  const fulMap = { fulfilled: "#22C55E", unfulfilled: "#F4B860", partial: "#38BDF8" };
  return <div className="dc-page">
    <window.DsPageHead title="Orders" copy="Live orders from Shopify. Fulfilling / editing an order stays your action — the crew only flags." />
    <div className="dc-kpi-grid"><window.DsKpi label="Orders pulled" value={rows.length} sub={configured ? "recent" : "connect Shopify"} icon="Orders"/><window.DsKpi label="Unfulfilled" value={unfulfilled} sub="need shipping" icon="Suppliers" color={unfulfilled ? "#F4B860" : "#22C55E"}/></div>
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Recent orders</div><div className="faint">{configured ? "from your store" : "Add Shopify keys in dropship.env"}</div></div><b>{rows.length}</b></div>
      <window.DsState loading={orders.loading} error={orders.error} empty={!rows.length} icon="Orders" title={configured ? "No orders" : "Shopify not connected"} copy={configured ? "No recent orders returned." : "Add SHOPIFY_STORE_DOMAIN + SHOPIFY_ADMIN_TOKEN to pull orders."}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Order</th><th>Customer</th><th>Total</th><th>Payment</th><th>Fulfillment</th><th>Items</th></tr></thead><tbody>{rows.map((o) => <tr key={o.id}><td>{o.name}</td><td>{(o.customer || "").trim() || "—"}</td><td className="tabnum">{o.total != null ? "$" + o.total : "—"}</td><td><DsoBadge value={o.financialStatus} map={finMap}/></td><td><DsoBadge value={o.fulfillmentStatus} map={fulMap}/></td><td className="tabnum">{o.items}</td></tr>)}</tbody></table></div>
      </window.DsState>
    </div>
  </div>;
}

function DsoResult({ result }) {
  if (!result) return null;
  if (result.raw) return <pre className="dc-pre">{result.raw}</pre>;
  const risks = result.risks || []; const drafts = result.drafts || []; const notes = result.notes || [];
  return <div>
    {result.headline && <div className="dc-eyebrow" style={{ marginBottom: 8 }}>{result.headline}</div>}
    {risks.length > 0 && <div className="dc-alert-list">{risks.map((r, i) => <div key={i}><span className={"dc-severity " + ((r.urgency || "info").toLowerCase())}/><div><b>{r.kind}: {r.detail}</b><small>{r.recommend}</small></div></div>)}</div>}
    {drafts.map((d, i) => <div key={i} className="card card-pad" style={{ marginTop: 10 }}><div className="faint" style={{ marginBottom: 6 }}>Draft reply {d.grounded === false ? "(⚠ not fully grounded)" : ""}</div><div>{d.reply}</div></div>)}
    {notes.length > 0 && <ul className="dc-notes">{notes.map((n, i) => <li key={i}>{n}</li>)}</ul>}
  </div>;
}

function DropshipSupport() {
  const overview = window.DsUseResource("/otto/overview", null, 30000);
  const [ticket, setTicket] = useStateDso("");
  const [busy, setBusy] = useStateDso(false);
  const [result, setResult] = useStateDso(null);
  const [err, setErr] = useStateDso("");
  const st = overview.data || {};
  const run = async (withTicket) => {
    setBusy(true); setErr(""); setResult(null);
    try { const r = await window.DsRequest("/otto/run", { body: withTicket ? { ticket } : {} }); setResult(r.result || r); overview.refresh(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const last = st.lastResult || null;
  return <div className="dc-page">
    <window.DsPageHead title="Customers & Support" copy="Otto watches fulfillment and drafts replies. Every reply is a proposal — you send it." actions={<button className="dc-outline" disabled={busy} onClick={() => run(false)}>{busy ? "Reading…" : "Check fulfillment"}</button>} />
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Draft a support reply</div><div className="faint">Paste a customer message — Otto grounds the reply in the order data</div></div>{st.aiReady === false && <span className="dc-error-text">Add a Claude key</span>}</div>
      <textarea className="dc-textarea" rows="4" value={ticket} onChange={(e) => setTicket(e.target.value)} placeholder="e.g. 'Where is my order #1023? It's been 10 days.'" />
      <div className="dc-modal-actions"><button className="dc-primary" disabled={busy || !ticket.trim()} onClick={() => run(true)}>{busy ? "Drafting…" : "Draft reply (proposal)"}</button></div>
      {err && <div className="dc-form-error">{err}</div>}
    </div>
    {(result || last) && <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Otto's read</div><div className="faint">proposal — nothing sent</div></div></div><DsoResult result={result || last} /></div>}
  </div>;
}

Object.assign(window, { DropshipOrders, DropshipSupport });
