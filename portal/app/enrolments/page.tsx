"use client";

import Link from "next/link";
import { saveTextFile } from "@/lib/device";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, fieldLabel, formatDateTime, titleCase, type EnrolmentSummary, type Value } from "@/lib/api";
import { IconAlert, IconDownload, IconNewEnrol, IconSearch, IconX } from "@/components/Icons";

type Record_ = Awaited<ReturnType<typeof api.enrolment>>;

function showValue(v: Value) {
  if (v === true) return "Yes";
  if (v === false) return "No";
  if (v === null || v === "") return "—";
  return /^[a-z_]+$/.test(v) ? titleCase(v) : v;
}

function Detail({ id, onClose }: { id: string; onClose: () => void }) {
  const [rec, setRec] = useState<Record_ | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setRec(null); api.enrolment(id).then(setRec).catch((e: Error) => setError(e.message)); }, [id]);

  const download = () => {
    if (!rec) return;
    saveTextFile(`enrolment_${rec.id}.json`, JSON.stringify(rec, null, 2));
  };

  return (
    <aside className="drawer glass-light" role="dialog" aria-label="Enrolment record">
      <div className="drawer-head">
        <div>
          <p className="eyebrow">Record {id}</p>
          <h2>{rec ? [rec.data.first_name, rec.data.middle_name, rec.data.last_name].filter(Boolean).join(" ") || "(no name)" : "Loading…"}</h2>
          {rec && <p className="muted">{rec.form_title || rec.form} · saved {formatDateTime(rec.saved_at)}</p>}
        </div>
        <button className="btn ghost icon-only" onClick={onClose} aria-label="Close"><IconX size={18} /></button>
      </div>
      {error && <div className="notice error"><IconAlert size={18} /><span>{error}</span></div>}
      {rec && (
        <>
          <div className="drawer-actions">
            <button className="btn small" onClick={download}><IconDownload size={15} /> Download JSON</button>
            {rec.sections_confirmed?.length ? <span className="chip ok">Sections confirmed: {rec.sections_confirmed.join(", ")}</span> : null}
          </div>
          <dl className="kv">
            {Object.entries(rec.data).map(([k, v]) => (
              <div key={k} className={v === null || v === "" ? "empty" : ""}>
                <dt>{fieldLabel(k)}</dt><dd>{showValue(v)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </aside>
  );
}

function EnrolmentsInner() {
  const params = useSearchParams();
  const router = useRouter();
  const openId = params.get("id");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<EnrolmentSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      api.enrolments(q, 200).then((r) => { setItems(r.items); setTotal(r.total); setError(null); })
        .catch((e: Error) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Records</p>
          <h1>Enrolments</h1>
          <p className="lead">{items ? `${total} saved record${total === 1 ? "" : "s"}` : "Loading…"}</p>
        </div>
        <div className="head-actions">
          <label className="search">
            <IconSearch size={17} />
            <input placeholder="Search name, phone, region…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search enrolments" />
          </label>
          <Link href="/enrolment/new" className="btn primary"><IconNewEnrol size={18} /> New enrolment</Link>
        </div>
      </header>

      {error && <div className="notice error"><IconAlert size={18} /><span>{error}</span></div>}

      <div className="card">
        {items && items.length === 0 ? (
          <p className="chart-empty">{q ? "No records match your search." : "No enrolments saved yet."}</p>
        ) : (
          <div className="table-wrap">
            <table className="table hover">
              <thead><tr><th>Name</th><th>Sex</th><th>Date of birth</th><th>Phone</th><th>Region</th><th>Corrected</th><th>Saved</th></tr></thead>
              <tbody>
                {(items || []).map((r) => (
                  <tr key={r.id} onClick={() => router.push(`/enrolments?id=${r.id}`)} className={openId === r.id ? "selected" : ""}>
                    <td><button className="link-btn" onClick={(e) => { e.stopPropagation(); router.push(`/enrolments?id=${r.id}`); }}>{r.name}</button></td>
                    <td>{titleCase(r.sex)}</td>
                    <td>{r.date_of_birth || "—"}</td>
                    <td className="mono">{r.phone_number || "—"}</td>
                    <td>{titleCase(r.region)}</td>
                    <td>{r.fields_corrected ?? "—"}</td>
                    <td className="muted">{formatDateTime(r.saved_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openId && <Detail id={openId} onClose={() => router.push("/enrolments")} />}
    </div>
  );
}

export default function Enrolments() {
  return <Suspense fallback={<div className="page"><p className="muted">Loading…</p></div>}><EnrolmentsInner /></Suspense>;
}
