// dropship_products.jsx — Products (live catalog + research watchlist), Inventory, Suppliers.
const { useState: useStateDsp } = React;

const DSP_STAGES = ["idea", "researching", "testing", "winner", "killed"];

function DspWatchModal({ item, onClose, onSaved }) {
  const [form, setForm] = useStateDsp(item || { name: "", stage: "idea", supplier: "", cost: "", price: "", sourceUrl: "", angle: "", notes: "" });
  const [busy, setBusy] = useStateDsp(false);
  const [err, setErr] = useStateDsp("");
  const save = async () => {
    if (!form.name.trim()) { setErr("Name required"); return; }
    setBusy(true); setErr("");
    try { await window.DsRequest("/watchlist/save", { body: form }); onSaved(); onClose(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  return <window.DsModal title={item && item.id ? "Edit product idea" : "Add product idea"} onClose={onClose}>
    {err && <div className="dc-form-error">{err}</div>}
    <div className="dc-form-grid">
      <window.DsField label="Product name"><input autoFocus value={form.name} onChange={set("name")} /></window.DsField>
      <window.DsField label="Stage"><select value={form.stage} onChange={set("stage")}>{DSP_STAGES.map((s) => <option key={s} value={s}>{s}</option>)}</select></window.DsField>
      <window.DsField label="Supplier"><input value={form.supplier} onChange={set("supplier")} placeholder="AutoDS / CJ / …" /></window.DsField>
      <window.DsField label="Landed cost"><input value={form.cost} onChange={set("cost")} placeholder="incl. shipping + fees" /></window.DsField>
      <window.DsField label="Sell price"><input value={form.price} onChange={set("price")} /></window.DsField>
      <window.DsField label="Source URL"><input value={form.sourceUrl} onChange={set("sourceUrl")} /></window.DsField>
      <window.DsField label="Angle" wide><input value={form.angle} onChange={set("angle")} placeholder="the marketing/creative angle" /></window.DsField>
      <window.DsField label="Notes" wide><textarea rows="3" value={form.notes} onChange={set("notes")} /></window.DsField>
    </div>
    <div className="dc-modal-actions"><button className="dc-quiet" onClick={onClose}>Cancel</button><button className="dc-primary" disabled={busy} onClick={save}>{busy ? "Saving…" : "Save idea"}</button></div>
  </window.DsModal>;
}

function DspMargin(item) {
  const cost = Number(item.cost) || 0; const price = Number(item.price) || 0;
  if (!cost || !price) return "—";
  const gross = price - cost;
  return "$" + gross.toFixed(2) + " (" + Math.round((gross / price) * 100) + "%)";
}

function DropshipProducts() {
  const watch = window.DsUseResource("/watchlist", "items", 30000);
  const products = window.DsUseResource("/products", null, 60000);
  const [editing, setEditing] = useStateDsp(null);
  const [open, setOpen] = useStateDsp(false);
  const items = Array.isArray(watch.data) ? watch.data : (watch.data && watch.data.items) || [];
  const live = (products.data && products.data.products) || [];
  const configured = products.data && products.data.configured;
  const del = async (id) => { if (!window.confirm("Remove this idea?")) return; try { await window.DsRequest("/watchlist/delete", { body: { id } }); watch.refresh(); } catch (e) { window.alert(e.message); } };
  return <div className="dc-page">
    <window.DsPageHead title="Products" copy="Your research pipeline (ideas → testing → winners) and the live Shopify catalog." actions={<button className="dc-primary" onClick={() => { setEditing(null); setOpen(true); }}><window.Icons.Plus size={14}/> Add idea</button>} />
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Research watchlist</div><div className="faint">Local — Hawk scores these; Shopify owns live products</div></div><b>{items.length}</b></div>
      {items.length ? <div className="dc-room-strip">{items.map((it) => <div key={it.id}><div className="dc-room-top"><span>{it.name}</span><b className="tabnum">{DspMargin(it)}</b></div><small>stage: {it.stage}{it.supplier ? " · " + it.supplier : ""}{it.verdict ? " · " + it.verdict : ""}</small>{it.angle && <small className="faint">{it.angle}</small>}<div className="dc-mini-actions"><button className="link" onClick={() => { setEditing(it); setOpen(true); }}>Edit</button><button className="link" onClick={() => del(it.id)}>Delete</button></div></div>)}</div> : <div className="dc-inline-empty">No product ideas yet — add one, then ask Hawk to score them from the Agents tab.</div>}
    </div>
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Live catalog (Shopify)</div><div className="faint">{configured ? "From your store" : "Add Shopify keys in dropship.env"}</div></div><b>{live.length}</b></div>
      <window.DsState loading={products.loading} error={products.error} empty={!live.length} icon="Products" title={configured ? "No products found" : "Shopify not connected"} copy={configured ? "Your store returned no products." : "Add SHOPIFY_STORE_DOMAIN + SHOPIFY_ADMIN_TOKEN to go live."}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Product</th><th>Status</th><th>Stock</th><th>Price</th></tr></thead><tbody>{live.map((p) => <tr key={p.id}><td>{p.title}</td><td>{p.status}</td><td className="tabnum">{p.stock}</td><td className="tabnum">{p.price != null ? "$" + p.price : "—"}</td></tr>)}</tbody></table></div>
      </window.DsState>
    </div>
    {open && <DspWatchModal item={editing} onClose={() => setOpen(false)} onSaved={watch.refresh} />}
  </div>;
}

function DropshipInventory() {
  const inv = window.DsUseResource("/inventory", null, 45000);
  const low = (inv.data && inv.data.low) || [];
  const configured = inv.data && inv.data.configured;
  return <div className="dc-page">
    <window.DsPageHead title="Inventory" copy="Low-stock variants — a stockout on a winner is an account-health risk." />
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">Low stock</div><div className="faint">{configured ? "variants at or below the threshold" : "Add Shopify keys in dropship.env"}</div></div><b>{low.length}</b></div>
      <window.DsState loading={inv.loading} error={inv.error} empty={!low.length} icon="Inventory" title={configured ? "Nothing low" : "Shopify not connected"} copy={configured ? "No variants are low on stock right now." : "Connect Shopify to monitor stock."}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Product</th><th>Variant</th><th>SKU</th><th>Stock</th></tr></thead><tbody>{low.map((r, i) => <tr key={i}><td>{r.product}</td><td>{r.variant}</td><td>{r.sku || "—"}</td><td className="tabnum" style={{ color: r.stock <= 0 ? "#F87171" : "#F4B860" }}>{r.stock}</td></tr>)}</tbody></table></div>
      </window.DsState>
    </div>
  </div>;
}

function DropshipSuppliers() {
  const sup = window.DsUseResource("/suppliers", null, 60000);
  const rows = (sup.data && sup.data.products) || [];
  const configured = sup.data && sup.data.configured;
  return <div className="dc-page">
    <window.DsPageHead title="Suppliers" copy="AutoDS sourcing — supplier cost, stock, and monitor state feed your margin math." />
    <div className="card card-pad dc-panel"><div className="dc-panel-head"><div><div className="card-title">AutoDS products</div><div className="faint">{configured ? "from your AutoDS store" : "Add AUTODS_API_KEY in dropship.env"}</div></div><b>{rows.length}</b></div>
      <window.DsState loading={sup.loading} error={sup.error} empty={!rows.length} icon="Suppliers" title={configured ? "No supplier products" : "AutoDS not connected"} copy={configured ? "AutoDS returned no products, or the endpoint needs confirming for your account tier." : "Add your AutoDS API key to pull sourcing data."}>
        <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Product</th><th>Cost</th><th>Stock</th><th>Status</th></tr></thead><tbody>{rows.map((r, i) => <tr key={i}><td>{r.title || r.name || r.item_id || "—"}</td><td className="tabnum">{r.price != null ? "$" + r.price : (r.buy_price != null ? "$" + r.buy_price : "—")}</td><td className="tabnum">{r.stock ?? r.quantity ?? "—"}</td><td>{r.status ?? "—"}</td></tr>)}</tbody></table></div>
      </window.DsState>
    </div>
  </div>;
}

Object.assign(window, { DropshipProducts, DropshipInventory, DropshipSuppliers });
