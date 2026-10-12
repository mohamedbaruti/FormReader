"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, formatDateTime, titleCase, type Stats } from "@/lib/api";
import { AreaChart, BarList, Columns, Donut, Ring } from "@/components/charts/charts";
import {
  IconNewEnrol, IconRecords, IconTrendDown, IconTrendUp, IconClock, IconSparkle, IconTraining,
  IconRefresh, IconAlert, IconArrowRight,
} from "@/components/Icons";

const RANGE = [7, 30, 90];

/** "Form 1A, edition 1.4 (green, with voter registration)" -> "1.4 green" */
function shortEdition(t: string) {
  const m = t.match(/edition\s*([\d.]+)\s*(?:\(([^,)]*))?/i);
  return m ? `${m[1]}${m[2] ? " " + m[2] : ""}` : t;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api.stats(days).then((s) => { setStats(s); setError(null); })
      .catch((e: Error) => setError(e.message)).finally(() => setLoading(false));
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const s = stats;
  const delta = s ? s.this_week - s.previous_week : 0;
  const sexData = s ? [
    { key: "male", label: "Male", value: s.sex.male || 0 },
    { key: "female", label: "Female", value: s.sex.female || 0 },
    ...(s.sex.unknown ? [{ key: "unknown", label: "Not ticked", value: s.sex.unknown }] : []),
  ] : [];
  const toBars = (o: Record<string, number>, raw = false) =>
    Object.entries(o).filter(([k]) => raw || k !== "unknown").sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ label: raw ? shortEdition(k) : titleCase(k), value: v }));

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</p>
          <h1>{greeting()} 👋</h1>
          <p className="lead">Here is how enrolment is going.</p>
        </div>
        <div className="head-actions">
          <div className="segmented" role="group" aria-label="Time range">
            {RANGE.map((d) => (
              <button key={d} className={d === days ? "on" : ""} onClick={() => setDays(d)}>{d} days</button>
            ))}
          </div>
          <button className="btn ghost icon-only" onClick={load} aria-label="Refresh" title="Refresh">
            <IconRefresh size={18} />
          </button>
          <Link href="/enrolment/new" className="btn primary"><IconNewEnrol size={18} /> New enrolment</Link>
        </div>
      </header>

      {error && (
        <div className="notice error"><IconAlert size={18} /> <span>{error}</span>
          <button className="btn small" onClick={load}>Try again</button></div>
      )}

      <section className="kpis" aria-busy={loading}>
        <div className="kpi card">
          <div className="kpi-icon blue"><IconRecords size={20} /></div>
          <div className="kpi-label">Total enrolments</div>
          <div className="kpi-value">{s ? s.total.toLocaleString() : "—"}</div>
          <div className="kpi-foot">{s ? `${s.today} today` : " "}</div>
        </div>
        <div className="kpi card">
          <div className="kpi-icon teal"><IconClock size={20} /></div>
          <div className="kpi-label">This week</div>
          <div className="kpi-value">{s ? s.this_week : "—"}</div>
          <div className={`kpi-foot ${delta > 0 ? "up" : delta < 0 ? "down" : ""}`}>
            {s ? (<>{delta > 0 ? <IconTrendUp size={15} /> : delta < 0 ? <IconTrendDown size={15} /> : null}
              {delta === 0 ? "same as last week" : `${delta > 0 ? "+" : ""}${delta} vs last week`}</>) : " "}
          </div>
        </div>
        <div className="kpi card kpi-ring">
          <div>
            <div className="kpi-icon violet"><IconSparkle size={20} /></div>
            <div className="kpi-label">Read correctly first time</div>
            <div className="kpi-value">
              {s?.accuracy.auto_read_rate != null ? `${(s.accuracy.auto_read_rate * 100).toFixed(1)}%` : "—"}
            </div>
            <div className="kpi-foot">of characters, before review</div>
          </div>
          <Ring value={s?.accuracy.auto_read_rate ?? null} label="Read correctly first time" />
        </div>
        <div className="kpi card">
          <div className="kpi-icon amber"><IconTraining size={20} /></div>
          <div className="kpi-label">Fields corrected per form</div>
          <div className="kpi-value">{s?.accuracy.fields_corrected_per_form ?? "—"}</div>
          <div className="kpi-foot">{s?.accuracy.fields_flagged_per_form != null ? `${s.accuracy.fields_flagged_per_form} marked "Please check" per form` : " "}</div>
        </div>
      </section>

      {s && s.total === 0 && !loading && (
        <div className="card empty-hero">
          <div>
            <h2>No enrolments yet</h2>
            <p>Start by reading the photos of a filled Form 1A. The charts fill in as records are saved.</p>
          </div>
          <Link href="/enrolment/new" className="btn primary">Start first enrolment <IconArrowRight size={18} /></Link>
        </div>
      )}

      <section className="grid-main">
        <div className="card span-2">
          <div className="card-head">
            <div><h2>Enrolments per day</h2><p className="muted">Last {days} days</p></div>
          </div>
          {s ? <AreaChart data={s.per_day} label={`Enrolments per day, last ${days} days`} /> : <div className="skeleton h220" />}
        </div>
        <div className="card">
          <div className="card-head"><div><h2>Sex</h2><p className="muted">All enrolments</p></div></div>
          {s ? <Donut data={sexData} label="Enrolments by sex" centerLabel="people" /> : <div className="skeleton h180" />}
        </div>
      </section>

      <section className="grid-3">
        <div className="card">
          <div className="card-head"><div><h2>Age groups</h2><p className="muted">From date of birth</p></div></div>
          {s ? <Columns data={Object.entries(s.age_bands).map(([k, v]) => ({ label: k, value: v }))} label="Enrolments by age group" />
             : <div className="skeleton h180" />}
        </div>
        <div className="card">
          <div className="card-head"><div><h2>Top regions</h2><p className="muted">Region of residence</p></div></div>
          {s ? <BarList data={toBars(s.regions)} label="Enrolments by region" /> : <div className="skeleton h180" />}
        </div>
        <div className="card">
          <div className="card-head"><div><h2>Marital status</h2><p className="muted">All enrolments</p></div></div>
          {s ? <BarList data={toBars(s.marital_status)} label="Enrolments by marital status" /> : <div className="skeleton h180" />}
        </div>
      </section>

      <section className="grid-main">
        <div className="card span-2">
          <div className="card-head">
            <div><h2>Recent enrolments</h2><p className="muted">Latest saved records</p></div>
            <Link href="/enrolments" className="btn ghost small">View all <IconArrowRight size={16} /></Link>
          </div>
          {s && s.recent.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Name</th><th>Sex</th><th>Date of birth</th><th>Region</th><th>Saved</th></tr></thead>
                <tbody>
                  {s.recent.map((r) => (
                    <tr key={r.id}>
                      <td><Link href={`/enrolments?id=${r.id}`} className="strong-link">{r.name}</Link></td>
                      <td>{titleCase(r.sex)}</td><td>{r.date_of_birth || "—"}</td>
                      <td>{titleCase(r.region)}</td><td className="muted">{formatDateTime(r.saved_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="chart-empty">Saved enrolments will appear here.</p>}
        </div>
        <div className="card">
          <div className="card-head"><div><h2>Employment</h2><p className="muted">All enrolments</p></div></div>
          {s ? <BarList data={toBars(s.employment_status)} label="Enrolments by employment" /> : <div className="skeleton h180" />}
          {s && Object.keys(s.editions).length > 0 && (
            <>
              <div className="card-head sub"><div><h2>Form editions</h2></div></div>
              <BarList data={toBars(s.editions, true)} label="Enrolments by form edition" />
            </>
          )}
        </div>
      </section>
    </div>
  );
}
