// crm.jsx — native CRM overview, composed from existing read-only GHL routes.
const { useMemo: useMemoCRM } = React;

function CrmKpi({ label, value, detail, icon, color = "#4F7CFF" }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Activity;
  return (
    <div className="card" style={{ padding: 16, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span className="faint" style={{ fontSize: 12 }}>{label}</span>
        <span style={{ color }}><Ico size={16} /></span>
      </div>
      <div className="tabnum" style={{ fontSize: 25, fontWeight: 750, marginTop: 10 }}>{value}</div>
      <div className="faint" style={{ fontSize: 11, marginTop: 3 }}>{detail}</div>
    </div>
  );
}

function CrmSection({ title, icon, action, children }) {
  const Icons = window.Icons;
  const Ico = Icons[icon] || Icons.Activity;
  return (
    <section className="card" style={{ padding: 16, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="faint"><Ico size={16} /></span>
          <div style={{ fontWeight: 700, fontSize: 14 }}>{title}</div>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function CrmActivityRow({ item }) {
  const kind = String(item.kind || item.action || item.type || "activity").replaceAll("_", " ");
  const detail = item.detail || item.message || item.description || "Recorded in FORGE";
  return (
    <div className="row-item" style={{ alignItems: "flex-start" }}>
      <span className="dot online" style={{ marginTop: 5, flexShrink: 0 }} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 12.5, fontWeight: 600, textTransform: "capitalize" }}>{kind}</div>
        <div className="faint" style={{ fontSize: 11.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{detail}</div>
      </div>
      <span className="faint" style={{ fontSize: 10.5, whiteSpace: "nowrap" }}>{window.timeAgo(item.at || item.createdAt || item.timestamp)}</span>
    </div>
  );
}

function CRMPage() {
  const Icons = window.Icons;
  const dashboard = window.useApi("/api/dashboard", { interval: 30000 });
  const activity = window.useApi("/api/actions/log?n=6", { interval: 15000 });
  const stats = dashboard.data || {};
  const convos = stats.recentConversations || [];
  const taskRows = stats.openTaskRows || [];
  const actionRows = (activity.data && activity.data.actions) || [];
  const stageSummary = useMemoCRM(() => (stats.pipelineStages || []).slice(0, 6), [stats.pipelineStages]);
  const refresh = () => [dashboard, activity].forEach((resource) => resource.refresh());
  const error = dashboard.error || activity.error;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 14, flexWrap: "wrap" }}>
        <div>
          <div className="faint" style={{ fontSize: 11, letterSpacing: 1, textTransform: "uppercase" }}>CRM · GHL reference layer</div>
          <h1 style={{ fontSize: 24, fontWeight: 750, letterSpacing: "-0.5px", marginTop: 4 }}>Lead operations</h1>
          <p className="faint" style={{ fontSize: 13.5, marginTop: 4 }}>One operator view of contacts, conversations, pipeline, follow-ups, and recorded activity.</p>
        </div>
        <button className="tab" onClick={refresh} style={{ display: "inline-flex", alignItems: "center", gap: 7, border: "1px solid var(--border)" }}><Icons.Activity size={14} /> Refresh</button>
      </div>

      <div style={{ padding: "10px 13px", borderRadius: 11, background: "rgba(79,124,255,0.08)", border: "1px solid rgba(79,124,255,0.25)", color: "var(--text-2)", fontSize: 12.5 }}>
        Read-only first slice. GoHighLevel remains the source of truth; no CRM writes or production workflow changes happen here.
      </div>
      {error && <window.ErrorRow error={error} onRetry={refresh} />}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
        <CrmKpi label="Contacts" value={stats.totalLeads ?? "—"} detail="GHL contacts" icon="Leads" />
        <CrmKpi label="Unread threads" value={stats.activeConversations ?? "—"} detail="Needs attention" icon="Conversations" color="#F59E0B" />
        <CrmKpi label="Open opportunities" value={stats.openOpportunities ?? "—"} detail={stats.pipelineValue != null ? window.fmtMoney(stats.pipelineValue) + " pipeline" : "GHL pipeline"} icon="Pipeline" color="#22C55E" />
        <CrmKpi label="Due today" value={stats.tasksDueToday ?? "—"} detail={stats.openTasks != null ? stats.openTasks + " open tasks" : "Follow-up tasks"} icon="Tasks" color="#EC4899" />
        <CrmKpi label="Appointments" value={stats.appointments ?? "—"} detail="Pipeline signal only" icon="Calendar" color="#8B5CF6" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.15fr) minmax(300px, .85fr)", gap: 16, alignItems: "start" }}>
        <CrmSection title="Recent conversations" icon="Conversations" action={<button className="link" onClick={() => window.GoTo && window.GoTo("Conversations")}>Open inbox</button>}>
          {dashboard.loading && !dashboard.data && <window.LoadingRow label="Loading conversations…" />}
          {!dashboard.loading && !convos.length && <div className="empty" style={{ padding: 24 }}><div className="empty-ico"><Icons.Message size={20} /></div><div>No recent conversations</div></div>}
          {convos.map((conversation) => <button key={conversation.id} onClick={() => { window.__forgeOpenConvo = conversation; window.GoTo && window.GoTo("Conversations"); }} className="row-item" style={{ width: "100%", textAlign: "left", color: "var(--text)" }}><div style={{ width: 32, height: 32, borderRadius: 10, background: "var(--card-2)", display: "grid", placeItems: "center", flexShrink: 0 }}><Icons.Message size={14} /></div><div style={{ minWidth: 0, flex: 1 }}><div style={{ fontSize: 12.5, fontWeight: 650, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{conversation.name}</div><div className="faint" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{conversation.lastMessage || "No message preview"}</div></div><span className="faint" style={{ fontSize: 10.5, whiteSpace: "nowrap" }}>{window.timeAgo(conversation.lastMessageDate)}</span></button>)}
        </CrmSection>

        <CrmSection title="Pipeline activity" icon="Pipeline" action={<button className="link" onClick={() => window.GoTo && window.GoTo("Pipeline")}>Open pipeline</button>}>
          {dashboard.loading && !dashboard.data && <window.LoadingRow label="Loading pipeline…" />}
          {!dashboard.loading && !stageSummary.length && <div className="faint" style={{ fontSize: 12.5, padding: "10px 0" }}>No active stage data yet.</div>}
          {stageSummary.map((stage) => <div key={stage.id} className="row-item"><div style={{ minWidth: 0, flex: 1 }}><div style={{ fontSize: 12.5, fontWeight: 600 }}>{stage.name}</div><div className="faint" style={{ fontSize: 11 }}>{stage.count} {stage.count === 1 ? "opportunity" : "opportunities"}</div></div><span className="tabnum" style={{ color: "var(--green)", fontSize: 12 }}>{stage.value ? window.fmtMoney(stage.value) : "—"}</span></div>)}
        </CrmSection>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 16, alignItems: "start" }}>
        <CrmSection title="Follow-up queue" icon="Tasks" action={<button className="link" onClick={() => window.GoTo && window.GoTo("Tasks")}>Open tasks</button>}>
          {dashboard.loading && !dashboard.data && <window.LoadingRow label="Loading follow-ups…" />}
          {!dashboard.loading && !taskRows.length && <div className="faint" style={{ fontSize: 12.5, padding: "10px 0" }}>No open follow-ups in the scanned GHL contacts.</div>}
          {taskRows.map((task) => <div key={task.id} className="row-item"><div style={{ minWidth: 0, flex: 1 }}><div style={{ fontSize: 12.5, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{task.title}</div><div className="faint" style={{ fontSize: 11 }}>{task.contactName || "Unknown contact"} · {task.dueDate ? new Date(task.dueDate).toLocaleDateString() : "No due date"}</div></div><span className="pill" style={{ fontSize: 10, color: "#F59E0B", background: "rgba(245,158,11,.12)" }}>open</span></div>)}
        </CrmSection>
        <CrmSection title="Automation & agent activity" icon="Activity" action={<button className="link" onClick={() => window.GoTo && window.GoTo("SystemHealth")}>System health</button>}>
          {activity.loading && !activity.data && <window.LoadingRow label="Loading activity…" />}
          {!activity.loading && !actionRows.length && <div className="faint" style={{ fontSize: 12.5, padding: "10px 0" }}>No recorded activity yet.</div>}
          {actionRows.slice(0, 5).map((item, index) => <CrmActivityRow key={item.id || index} item={item} />)}
        </CrmSection>
      </div>
    </div>
  );
}

Object.assign(window, { CRMPage });
