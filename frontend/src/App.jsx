import { useEffect, useMemo, useState } from "react";
import { api, rootRequest } from "./api.js";

const statuses = ["OPEN", "INVESTIGATING", "RESOLVED", "CLOSED"];
const priorities = ["P0", "P1", "P2", "P3"];

const statusAction = {
  OPEN: { label: "Start", next: "INVESTIGATING" },
  INVESTIGATING: { label: "Resolve", next: "RESOLVED" },
  RESOLVED: { label: "Close", next: "CLOSED" }
};

const priorityLabel = {
  P0: "Database / Host",
  P1: "Latency / Queue",
  P2: "Cache / NoSQL",
  P3: "API / Other"
};

function Icon({ name }) {
  const paths = {
    pulse: "M3 12h4l2-7 4 14 2-7h6",
    list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    signal: "M2 20h20M6 16l4-4 3 3 5-7 4 4",
    refresh: "M21 12a9 9 0 0 1-15.5 6.2M3 12A9 9 0 0 1 18.5 5.8M18 3v5h-5M6 21v-5h5",
    file: "M6 2h9l5 5v15H6zM14 2v6h6M9 13h8M9 17h8"
  };
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="icon">
      <path d={paths[name]} />
    </svg>
  );
}

function cx(...items) {
  return items.filter(Boolean).join(" ");
}

function formatTime(value) {
  if (!value) return "Not set";
  return new Intl.DateTimeFormat("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "short"
  }).format(new Date(value));
}

function secondsLabel(value) {
  if (value == null) return "Not resolved";
  if (value < 60) return `${Math.round(value)}s`;
  return `${Math.round(value / 60)}m`;
}

function App() {
  const [activeView, setActiveView] = useState("incidents");
  const [incidents, setIncidents] = useState([]);
  const [signals, setSignals] = useState([]);
  const [signalStats, setSignalStats] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [selectedSignals, setSelectedSignals] = useState([]);
  const [selectedRca, setSelectedRca] = useState(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [countdown, setCountdown] = useState(60);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [rcaDraft, setRcaDraft] = useState({
    root_cause_category: "",
    fix_applied: "",
    prevention_steps: ""
  });

  async function loadData() {
    const params = { limit: "100" };
    if (statusFilter) params.status = statusFilter;
    const selectedId = selectedIncident?.id;

    const [incidentData, signalData, statsData, metricsData] = await Promise.all([
      api.incidents(params),
      api.signals({ limit: "80" }),
      api.signalStats(),
      rootRequest("/metrics")
    ]);

    const nextIncidents = incidentData.incidents || [];
    setIncidents(nextIncidents);
    setSignals(signalData || []);
    setSignalStats(statsData);
    setMetrics(metricsData);
    setLastUpdated(new Date());

    if (selectedId) {
      const refreshedIncident = nextIncidents.find((incident) => incident.id === selectedId);
      if (refreshedIncident) {
        setSelectedIncident(refreshedIncident);
      }
      const linkedSignals = await api.signals({ incident_id: selectedId, limit: "20" });
      setSelectedSignals(linkedSignals || []);
    }
  }

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      loadData()
        .then(() => {
          if (!cancelled) setCountdown(60);
        })
        .catch((error) => {
          if (!cancelled) setToast(error.message);
        });
    };

    refresh();
    const timer = setInterval(() => {
      setCountdown((current) => {
        if (current <= 1) {
          refresh();
          return 60;
        }
        return current - 1;
      });
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [statusFilter, selectedIncident?.id]);

  async function selectIncident(incident) {
    setSelectedIncident(incident);
    setSelectedRca(null);
    setRcaDraft({
      root_cause_category: "",
      fix_applied: "",
      prevention_steps: ""
    });

    const [linkedSignals, rca] = await Promise.all([
      api.signals({ incident_id: incident.id, limit: "20" }),
      api.getRca(incident.id).catch(() => null)
    ]);
    setSelectedSignals(linkedSignals || []);
    setSelectedRca(rca);
    if (rca) {
      setRcaDraft({
        root_cause_category: rca.root_cause_category,
        fix_applied: rca.fix_applied,
        prevention_steps: rca.prevention_steps
      });
    }
  }

  async function transition(incident, nextStatus) {
    setBusy(true);
    setToast("");
    try {
      const updated = await api.updateIncidentStatus(incident.id, nextStatus);
      setSelectedIncident(updated);
      setToast(`Incident moved to ${updated.status}`);
      await loadData();
      setCountdown(60);
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitRca() {
    if (!selectedIncident) return;
    setBusy(true);
    setToast("");
    try {
      const rca = await api.submitRca(selectedIncident.id, rcaDraft);
      setSelectedRca(rca);
      setToast("RCA saved");
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(false);
    }
  }

  const summary = useMemo(() => {
    const byStatus = Object.fromEntries(statuses.map((status) => [status, 0]));
    const byPriority = Object.fromEntries(priorities.map((priority) => [priority, 0]));
    for (const incident of incidents) {
      byStatus[incident.status] = (byStatus[incident.status] || 0) + 1;
      byPriority[incident.priority] = (byPriority[incident.priority] || 0) + 1;
    }
    return { byStatus, byPriority };
  }, [incidents]);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">IMS</span>
          <div>
            <strong>IMS</strong>
            <span>Incident Management System</span>
          </div>
        </div>

        <nav className="nav">
          <button className={cx(activeView === "incidents" && "active")} onClick={() => setActiveView("incidents")}>
            <Icon name="list" /> Incidents
          </button>
          <button className={cx(activeView === "signals" && "active")} onClick={() => setActiveView("signals")}>
            <Icon name="signal" /> Signals
          </button>
        </nav>

        <div className="sidebar-stat">
          <span>Live</span>
          <strong>{metrics ? "ONLINE" : "SYNC"}</strong>
        </div>
        <div className="sidebar-stat">
          <span>P0</span>
          <strong>{summary.byPriority.P0 || 0}</strong>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>Incident Management</h1>
            <p>Signals, work items, RCA, closure.</p>
          </div>
          <button
            className="icon-button"
            onClick={() => {
              loadData()
                .then(() => setCountdown(60))
                .catch((error) => setToast(error.message));
            }}
            title="Refresh"
          >
            <Icon name="refresh" />
          </button>
        </header>

        {toast && <div className="toast">{toast}</div>}

        <section className="metric-grid">
          <div className="metric">
            <span>Total</span>
            <strong>{incidents.length}</strong>
          </div>
          <div className="metric accent-blue">
            <span>Active</span>
            <strong>{(summary.byStatus.OPEN || 0) + (summary.byStatus.INVESTIGATING || 0)}</strong>
          </div>
          <div className="metric accent-red">
            <span>P0 Critical</span>
            <strong>{summary.byPriority.P0 || 0}</strong>
          </div>
          <div className="metric accent-amber">
            <span>P1 Warning</span>
            <strong>{summary.byPriority.P1 || 0}</strong>
          </div>
          <div className="metric accent-green">
            <span>Resolved</span>
            <strong>{summary.byStatus.RESOLVED || 0}</strong>
          </div>
          <div className="metric refresh-card">
            <span>Auto-refresh</span>
            <strong>{countdown}s</strong>
            <div className="timer-track">
              <div className="timer-fill" style={{ width: `${(countdown / 60) * 100}%` }} />
            </div>
          </div>
        </section>

        {activeView === "incidents" ? (
          <section className="workspace">
            <div className="content-area">
              <div className="toolbar">
                <h2>Incident Feed</h2>
                <div className="segmented">
                  <button className={!statusFilter ? "selected" : ""} onClick={() => setStatusFilter("")}>All</button>
                  {statuses.map((status) => (
                    <button key={status} className={statusFilter === status ? "selected" : ""} onClick={() => setStatusFilter(status)}>
                      {status}
                    </button>
                  ))}
                </div>
              </div>

              <div className="incident-list">
                {incidents.map((incident) => (
                  <article
                    className={cx("incident-row", selectedIncident?.id === incident.id && "selected")}
                    key={incident.id}
                    onClick={() => selectIncident(incident).catch((error) => setToast(error.message))}
                  >
                    <div className="row-main">
                      <div className="row-title">
                        <span className={cx("priority", incident.priority)}>{incident.priority}</span>
                        <strong>{incident.component_id}</strong>
                      </div>
                      <p>{incident.summary}</p>
                      <div className="row-meta">
                        <span>{incident.component_type}</span>
                        <span>{incident.severity}</span>
                        <span>{incident.signal_count} signals</span>
                        <span>{formatTime(incident.created_at)}</span>
                      </div>
                    </div>
                    <div className="row-actions">
                      <span className={cx("status-pill", incident.status)}>{incident.status}</span>
                      {statusAction[incident.status] && (
                        <button
                          className="primary-action"
                          disabled={busy}
                          onClick={(event) => {
                            event.stopPropagation();
                            transition(incident, statusAction[incident.status].next);
                          }}
                        >
                          {statusAction[incident.status].label}
                        </button>
                      )}
                    </div>
                  </article>
                ))}
              </div>
              <div className="last-updated">
                Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString("en-IN") : "syncing"}
              </div>
            </div>

            <aside className="detail-pane">
              {selectedIncident ? (
                <IncidentDetail
                  incident={selectedIncident}
                  signals={selectedSignals}
                  rca={selectedRca}
                  rcaDraft={rcaDraft}
                  setRcaDraft={setRcaDraft}
                  onSubmitRca={submitRca}
                  onTransition={(next) => transition(selectedIncident, next)}
                  busy={busy}
                />
              ) : (
                <div className="empty-state">
                  <Icon name="pulse" />
                  <strong>Select an incident</strong>
                  <span>Details, signals, and RCA appear here.</span>
                </div>
              )}
            </aside>
          </section>
        ) : (
          <SignalsView signals={signals} signalStats={signalStats} />
        )}
      </main>
    </div>
  );
}

function IncidentDetail({ incident, signals, rca, rcaDraft, setRcaDraft, onSubmitRca, onTransition, busy }) {
  const action = statusAction[incident.status];

  return (
    <div className="detail-content">
      <div className="detail-header">
        <span className={cx("priority", incident.priority)}>{incident.priority}</span>
        <h2>{incident.component_id}</h2>
        <span className={cx("status-pill", incident.status)}>{incident.status}</span>
      </div>

      <p className="summary-text">{incident.summary}</p>

      <div className="detail-grid">
        <div><span>Alert</span><strong>{incident.alert_type}</strong></div>
        <div><span>MTTR</span><strong>{secondsLabel(incident.mttr_seconds)}</strong></div>
        <div><span>Started</span><strong>{formatTime(incident.start_time)}</strong></div>
        <div><span>Ended</span><strong>{formatTime(incident.end_time)}</strong></div>
      </div>

      {action && (
        <button className="wide-action" disabled={busy} onClick={() => onTransition(action.next)}>
          {action.label} Incident
        </button>
      )}

      <section className="pane-section">
        <div className="section-title">
          <Icon name="file" />
          <strong>RCA</strong>
          {rca?.valid && <span className="valid">Valid</span>}
        </div>
        <label>
          Root cause
          <input
            value={rcaDraft.root_cause_category}
            onChange={(event) => setRcaDraft({ ...rcaDraft, root_cause_category: event.target.value })}
          />
        </label>
        <label>
          Fix applied
          <textarea
            rows="3"
            value={rcaDraft.fix_applied}
            onChange={(event) => setRcaDraft({ ...rcaDraft, fix_applied: event.target.value })}
          />
        </label>
        <label>
          Prevention steps
          <textarea
            rows="3"
            value={rcaDraft.prevention_steps}
            onChange={(event) => setRcaDraft({ ...rcaDraft, prevention_steps: event.target.value })}
          />
        </label>
        <button className="wide-action secondary" disabled={busy} onClick={onSubmitRca}>
          Save RCA
        </button>
      </section>

      <section className="pane-section">
        <div className="section-title">
          <Icon name="signal" />
          <strong>Linked Signals</strong>
        </div>
        <div className="mini-list">
          {signals.map((signal) => (
            <div key={signal.id} className="mini-signal">
              <strong>{signal.message}</strong>
              <span>{signal.severity} - {formatTime(signal.received_at)}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function SignalsView({ signals, signalStats }) {
  return (
    <section className="signals-layout">
      <div className="signal-stats">
        {Object.entries(signalStats?.by_severity || {}).map(([severity, count]) => (
          <div className="metric" key={severity}>
            <span>{severity}</span>
            <strong>{count}</strong>
          </div>
        ))}
        {priorities.map((priority) => (
          <div className="priority-note" key={priority}>
            <strong>{priority}</strong>
            <span>{priorityLabel[priority]}</span>
          </div>
        ))}
      </div>

      <div className="signal-table">
        {signals.map((signal) => (
          <article className="signal-row" key={signal.id}>
            <div>
              <strong>{signal.component_id}</strong>
              <p>{signal.message}</p>
            </div>
            <div className="row-meta">
              <span>{signal.component_type}</span>
              <span>{signal.severity}</span>
              <span>{formatTime(signal.received_at)}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export default App;
