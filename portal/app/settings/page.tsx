"use client";

import { useEffect, useState } from "react";
import { API_BASE, api, formatDateTime, type Health } from "@/lib/api";
import { IconAlert, IconCheckCircle, IconRefresh, IconServer } from "@/components/Icons";
import { appBridge } from "@/lib/device";

export default function Settings() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  const check = () => {
    setChecking(true);
    api.health().then((h) => { setHealth(h); setError(null); })
      .catch((e: Error) => { setHealth(null); setError(e.message); })
      .finally(() => setChecking(false));
  };
  useEffect(check, []);
  const [inApp, setInApp] = useState(false);       // inside the Android app
  useEffect(() => { setInApp(!!appBridge()); }, []);

  return (
    <div className="page">
      <header className="page-head">
        <div><p className="eyebrow">System</p><h1>Settings</h1><p className="lead">Connection to the Form Reader and what it can read.</p></div>
        <button className="btn" onClick={check} disabled={checking}><IconRefresh size={16} /> {checking ? "Checking…" : "Check again"}</button>
      </header>

      <section className="grid-2">
        <div className="card">
          <div className="card-head"><div><h2>Form Reader API</h2></div></div>
          <div className={`conn ${health ? "ok" : error ? "down" : ""}`}>
            {health ? <IconCheckCircle size={22} /> : error ? <IconAlert size={22} /> : <IconServer size={22} />}
            <div>
              <strong>{health ? "Connected" : error ? "Not reachable" : "Checking…"}</strong>
              <p className="muted">Address used by this app: <code>{API_BASE}</code></p>
            </div>
          </div>
          {error && <p className="notice error"><IconAlert size={18} /><span>{error}</span></p>}
          {inApp && (
            <p><button className="btn" onClick={() => appBridge()?.changeServer()}>
              <IconServer size={16} /> Change computer address</button></p>
          )}
          <p className="muted small-note">
            The address of the Python app is set in <code>.env.local</code> (<code>FORMREADER_API</code>, default
            {" "}<code>http://127.0.0.1:8000</code>). Restart <code>npm run dev</code> after changing it.
          </p>
        </div>
        <div className="card">
          <div className="card-head"><div><h2>Reading models</h2></div></div>
          {health ? (
            <dl className="kv compact">
              {Object.entries(health.models).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>updated {formatDateTime(v)}</dd></div>)}
              <div><dt>API version</dt><dd>{health.version}</dd></div>
              {health.database && <div><dt>Saved enrolments</dt><dd>{health.database.records} in {health.database.path}</dd></div>}
            </dl>
          ) : <p className="muted">—</p>}
        </div>
      </section>

      <div className="card">
        <div className="card-head"><div><h2>Form editions the reader knows</h2><p className="muted">Recognised automatically from the photo</p></div></div>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Edition</th><th>Id</th><th>Pages</th><th>Fields</th></tr></thead>
            <tbody>
              {(health?.forms || []).map((f) => (
                <tr key={f.id}><td>{f.title}</td><td className="mono">{f.id}</td><td>{f.pages}</td><td>{f.fields}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
