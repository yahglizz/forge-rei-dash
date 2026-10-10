// Daycare · Family Forms — every Family Contact Form submission as a stored PDF
// (child, parent, emergency contact, authorized pickup). Files live in a private
// Blob store on the form project; this page lists them and streams them through
// the connector, behind the daycare session. View opens the PDF, Download saves it.
const { useState: useStateDff } = React;

const DFF_BRANDS = [["", "All"], ["atob", "A Touch of Blessings"], ["amt", "A Mother's Touch"]];

function dffWhen(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso || "";
  return d.toLocaleString("en-US", { timeZone: "America/New_York", dateStyle: "medium", timeStyle: "short" });
}
function dffUrl(path, download) {
  return "/api/daycare/family-forms/pdf?path=" + encodeURIComponent(path) + (download ? "&download=1" : "");
}

function DaycareFamilyForms() {
  const res = window.DcxUseResource("/family-forms", "forms", 60000);
  const [brand, setBrand] = useStateDff("");
  const [search, setSearch] = useStateDff("");
  const payload = (res.data && typeof res.data === "object") ? res.data : {};
  const forms = Array.isArray(res.data) ? res.data : (Array.isArray(payload.forms) ? payload.forms : []);
  const q = search.trim().toLowerCase();
  const visible = forms.filter((f) => (!brand || f.brand === brand)
    && (!q || [f.child, f.parent].some((s) => (s || "").toLowerCase().includes(q))));
  const count = (b) => forms.filter((f) => !b || f.brand === b).length;

  const actions = <div className="dc-search"><window.Icons.Search size={14} />
    <input placeholder="Search child or parent…" value={search} onChange={(e) => setSearch(e.target.value)} /></div>;

  return <div className="dc-page">
    <window.DcxPageHead title="Family Forms" eyebrow="CONTACT FORM PDFs"
      copy="Every Family Contact Form a family submits is saved here as a PDF — emergency contact, authorized pickup, uniform sizes. View or download any time."
      actions={actions} />
    {payload.configured === false && <div className="card card-pad"><div className="dc-form-hint">Family Forms isn't connected yet. {payload.hint || ""}</div></div>}
    {payload.error && <div className="card card-pad"><div className="dc-form-hint" style={{ color: "#f28b82" }}>Couldn't reach the forms store ({payload.error}). Try again in a minute.</div></div>}
    {payload.stale && <div className="card card-pad"><div className="dc-form-hint">Showing the last list loaded — the forms store didn't answer just now.</div></div>}
    <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", margin: "4px 0 12px" }}>
      {DFF_BRANDS.map(([key, label]) => <button key={key || "all"} className={"dc-quiet" + (brand === key ? " active" : "")}
        style={brand === key ? { fontWeight: 700, textDecoration: "underline" } : undefined}
        onClick={() => setBrand(key)}>{label} · {count(key)}</button>)}
    </div>
    <window.DcxState loading={res.loading} error={res.error} onRetry={res.refresh}
      empty={payload.configured !== false && !forms.length && !payload.error} icon="Children" title="No forms yet"
      copy="New Family Contact Form submissions will show up here within a minute of being sent." />
    {forms.length > 0 && <div className="card dc-table-wrap"><table className="lead-table dc-table">
      <thead><tr><th>Child</th><th>Parent</th><th>Center</th><th>Submitted (ET)</th><th></th></tr></thead>
      <tbody>{visible.map((f) => <tr key={f.path}>
        <td><b>{f.child}</b></td>
        <td>{f.parent}</td>
        <td>{f.brand_label || f.brand}</td>
        <td>{dffWhen(f.submittedAt)}</td>
        <td><div className="dc-row-actions">
          <a className="dc-quiet" href={dffUrl(f.path, false)} target="_blank" rel="noopener noreferrer">View</a>
          <a className="dc-quiet" href={dffUrl(f.path, true)}>Download</a>
        </div></td>
      </tr>)}</tbody></table>
      {!visible.length && <div className="dc-inline-empty">No form matches that search.</div>}</div>}
  </div>;
}

Object.assign(window, { DaycareFamilyForms });
