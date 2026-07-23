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

// --- AutoDS section (the "Suppliers" tab) -----------------------------------
// Everything AutoDS in one place: what's wired, the supplier catalog, the supplier-side
// orders, and the marketplace/product-finder. Read-only — placing or approving a supplier
// order stays the operator's action (rule 2).
const DSP_AUTODS_TABS = [
  ["products", "Products", "Supplier cost + stock behind your listings"],
  ["orders", "Orders", "Supplier-side order + fulfillment state"],
  ["marketplace", "Marketplace", "AutoDS product finder — winning/trending items"],
];

function DspAutodsProducts() {
  const sup = window.DsUseResource("/suppliers", null, 60000);
  const rows = (sup.data && sup.data.products) || [];
  const configured = sup.data && sup.data.configured;
  return <window.DsState loading={sup.loading} error={sup.error} empty={!rows.length} icon="Suppliers"
    title={configured ? "No supplier products" : "AutoDS not connected"}
    copy={configured ? "AutoDS returned no products, or AUTODS_PRODUCTS_PATH needs confirming for your account tier." : "Add your AutoDS API key to pull sourcing data."}>
    <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Product</th><th>Cost</th><th>Stock</th><th>Status</th></tr></thead><tbody>{rows.map((r, i) => <tr key={i}><td>{r.title || r.name || r.item_id || "—"}</td><td className="tabnum">{r.price != null ? "$" + r.price : (r.buy_price != null ? "$" + r.buy_price : "—")}</td><td className="tabnum">{r.stock ?? r.quantity ?? "—"}</td><td>{r.status ?? "—"}</td></tr>)}</tbody></table></div>
  </window.DsState>;
}

function DspAutodsOrders() {
  const ord = window.DsUseResource("/autods/orders", null, 60000);
  const rows = (ord.data && ord.data.orders) || [];
  const configured = ord.data && ord.data.configured;
  return <window.DsState loading={ord.loading} error={ord.error} empty={!rows.length} icon="Orders"
    title={configured ? "No supplier orders" : "AutoDS not connected"}
    copy={configured ? "AutoDS returned no orders, or AUTODS_ORDERS_PATH needs confirming for your account tier." : "Add your AutoDS API key to pull supplier orders."}>
    <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Order</th><th>Status</th><th>Total</th><th>Tracking</th><th>Placed</th></tr></thead><tbody>{rows.map((r, i) => <tr key={i}>
      <td>{r.order_id || r.id || r.reference || "—"}</td>
      <td>{r.status || r.order_status || "—"}</td>
      <td className="tabnum">{r.total != null ? "$" + r.total : (r.price != null ? "$" + r.price : "—")}</td>
      <td>{r.tracking_number || r.tracking || "—"}</td>
      <td className="faint">{r.created_at || r.date || "—"}</td>
    </tr>)}</tbody></table></div>
  </window.DsState>;
}

function DspAutodsMarketplace() {
  const [q, setQ] = useStateDsp("");
  const [term, setTerm] = useStateDsp("");
  const mk = window.DsUseResource("/autods/marketplace" + (term ? "?q=" + encodeURIComponent(term) : ""), null, 0);
  const rows = (mk.data && mk.data.products) || [];
  const configured = mk.data && mk.data.configured;
  return <>
    <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the AutoDS product finder…" onKeyDown={(e) => { if (e.key === "Enter") setTerm(q.trim()); }} />
      <button className="dc-outline" onClick={() => setTerm(q.trim())}>Search</button>
    </div>
    <window.DsState loading={mk.loading} error={mk.error} empty={!rows.length} icon="Products"
      title={configured ? "Nothing returned" : "AutoDS not connected"}
      copy={configured ? "The marketplace/product-finder is a paid AutoDS add-on — if this stays empty, confirm AUTODS_MARKETPLACE_PATH for your plan." : "Add your AutoDS API key to use the product finder."}>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Product</th><th>Cost</th><th>Sell</th><th>Sold</th><th>Category</th></tr></thead><tbody>{rows.map((r, i) => {
        const sig = r.signal || {};
        return <tr key={i}>
          <td>{r.sourceUrl ? <a href={r.sourceUrl} target="_blank" rel="noreferrer">{r.name}</a> : r.name}</td>
          <td className="tabnum">{r.cost != null ? "$" + r.cost : "—"}</td>
          <td className="tabnum">{sig.sellPrice != null ? "$" + sig.sellPrice : "—"}</td>
          <td className="tabnum">{sig.sold ?? "—"}</td>
          <td className="faint">{sig.category || sig.supplierName || "—"}</td>
        </tr>;
      })}</tbody></table></div>
    </window.DsState>
  </>;
}

function DropshipSuppliers() {
  const [tab, setTab] = useStateDsp("products");
  const health = window.DsUseResource("/autods/health", null, 120000);
  const wiring = window.DsUseResource("/autods/wiring", null, 120000);
  const h = health.data || {}; const w = wiring.data || {};
  const keys = w.keys || {}; const paths = w.paths || {};
  const meta = DSP_AUTODS_TABS.find((t) => t[0] === tab) || DSP_AUTODS_TABS[0];
  return <div className="dc-page">
    <window.DsPageHead title="AutoDS · Suppliers"
      copy="Sourcing, supplier orders, and the product finder — the cost side of every margin the crew quotes. Read-only: placing or approving a supplier order stays your action." />

    <div className="dc-kpi-grid">
      <window.DsKpi label="Connection" value={h.connected ? "Live" : (h.configured ? "Error" : "Add key")} sub={h.error || h.detail || "AutoDS API"} icon="Suppliers" color={h.connected ? "#22C55E" : (h.configured ? "#F87171" : "#F4B860")} />
      <window.DsKpi label="API key" value={keys.AUTODS_API_KEY ? "Set" : "Missing"} sub="AUTODS_API_KEY" icon="Sliders" color={keys.AUTODS_API_KEY ? "#22C55E" : "#F4B860"} />
      <window.DsKpi label="Store id" value={keys.AUTODS_STORE_ID ? "Set" : "—"} sub="AUTODS_STORE_ID (optional)" icon="Sliders" color={keys.AUTODS_STORE_ID ? "#22C55E" : "#64748B"} />
      <window.DsKpi label="AutoDS MCP" value={keys.AUTODS_MCP_URL ? "Set" : "Not yet"} sub="add it in Connections & MCP" icon="Bot" color={keys.AUTODS_MCP_URL ? "#22C55E" : "#64748B"} />
    </div>

    <div className="tabs" style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
      {DSP_AUTODS_TABS.map((t) => <button key={t[0]} className={"tab" + (tab === t[0] ? " active" : "")} onClick={() => setTab(t[0])}>{t[1]}</button>)}
    </div>

    <div className="card card-pad dc-panel">
      <div className="dc-panel-head"><div><div className="card-title">{meta[1]}</div><div className="faint">{meta[2]}</div></div></div>
      {tab === "products" && <DspAutodsProducts />}
      {tab === "orders" && <DspAutodsOrders />}
      {tab === "marketplace" && <DspAutodsMarketplace />}
    </div>

    <div className="card card-pad dc-panel" style={{ marginTop: 12 }}>
      <div className="dc-panel-head"><div><div className="card-title">AutoDS wiring</div><div className="faint">Which keys are present (never their values) and which endpoints are in use</div></div><button className="link" onClick={() => window.GoTo("Connections")}>Connections & MCP</button></div>
      <div className="tbl-wrap"><table className="tbl"><thead><tr><th>Endpoint</th><th>Path in use</th></tr></thead><tbody>
        <tr><td>API base</td><td><code>{paths.base || "—"}</code></td></tr>
        <tr><td>Products</td><td><code>{paths.products || "—"}</code></td></tr>
        <tr><td>Orders</td><td><code>{paths.orders || "—"}</code></td></tr>
        <tr><td>Marketplace</td><td><code>{paths.marketplace || "—"}</code></td></tr>
      </tbody></table></div>
      <div className="faint" style={{ marginTop: 8 }}>{w.detail || "Paths are env-overridable (AUTODS_*_PATH) — confirm them against your AutoDS plan's API docs if a read comes back empty."}</div>
    </div>
  </div>;
}

Object.assign(window, {
  DropshipProducts, DropshipInventory, DropshipSuppliers,
  DspAutodsProducts, DspAutodsOrders, DspAutodsMarketplace, DSP_AUTODS_TABS,
});
