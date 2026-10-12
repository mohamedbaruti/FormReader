"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import StaffName from "@/components/StaffName";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, formatDateTime, type CharStat, type TrainingFormRow, type TrainingStats } from "@/lib/api";
import {
  IconAlert, IconArrowRight, IconCheckCircle, IconDownload, IconInfo, IconRefresh, IconSparkle, IconTraining,
  IconLock, IconUpload, IconX,
} from "@/components/Icons";

const LEVEL = {
  needs_more: { label: "Needs more", cls: "lv-few" },
  moderate: { label: "Moderate", cls: "lv-mid" },
  enough: { label: "Enough", cls: "lv-ok" },
} as const;

const STATUS: Record<string, { label: string; cls: string }> = {
  queued: { label: "Waiting to be read", cls: "" },
  reading: { label: "Reading…", cls: "" },
  ready: { label: "To check", cls: "warn" },
  confirmed: { label: "Checked", cls: "ok" },
  skipped: { label: "Skipped", cls: "" },
  problem: { label: "Problem", cls: "bad" },
  failed: { label: "Failed", cls: "bad" },
};

const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);

function CharCell({ c, enough }: { c: CharStat; enough: number }) {
  const lv = LEVEL[c.level];
  const tip = [
    `${c.char}: ${c.samples} samples (${lv.label.toLowerCase()})`,
    c.seen ? `read right ${c.right} of ${c.seen} times (${pct(c.accuracy, 0)})` : "not seen on checked forms yet",
    c.confused_with.length ? `mixed up with ${c.confused_with.map((x) => `${x.char} ×${x.count}`).join(", ")}` : "",
    c.advice,
  ].filter(Boolean).join("\n");
  return (
    <div className={`tc-cell ${lv.cls}${c.reading === "often_misread" ? " misread" : ""}`} title={tip} tabIndex={0}
         aria-label={tip.replace(/\n/g, ". ")}>
      <span className="tc-char">{c.char}</span>
      <span className="tc-n">{c.samples}</span>
      <span className="tc-bar"><span style={{ width: `${Math.min(1, c.samples / enough) * 100}%` }} /></span>
      <span className="tc-acc">{c.seen ? pct(c.accuracy, 0) : "—"}</span>
    </div>
  );
}

export default function Training() {
  const router = useRouter();
  const [s, setS] = useState<TrainingStats | null>(null);
  const [forms, setForms] = useState<TrainingFormRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"all" | "ready" | "confirmed" | "problem">("all");
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    Promise.all([api.training(), api.trainingForms()])
      .then(([st, f]) => { setS(st); setForms(f.items); setError(null); })
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  // refresh while photos are being read or a training runs
  const active = !!s && (s.forms.queued + s.forms.reading > 0 || s.job.state === "running");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [active, load]);
  // while forms wait to be checked, refresh now and then so "Being checked by …" stays current
  const waiting = !!s && s.forms.ready > 0;
  useEffect(() => {
    if (!waiting || active) return;
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [waiting, active, load]);

  async function upload(list: FileList | null) {
    const files = Array.from(list || []).filter((f) => /\.(jpe?g|png)$/i.test(f.name) || /^image\/(jpeg|png)$/.test(f.type));
    if (!files.length) { setError("Choose JPG or PNG photos of page 1."); return; }
    setUploading(true); setError(null);
    try {
      // send in groups so 100 photos do not make one huge request
      let added = 0; const refused: string[] = [];
      for (let i = 0; i < files.length; i += 10) {
        const r = await api.trainingUpload(files.slice(i, i + 10));
        added += r.added; refused.push(...r.refused);
        setNotice(`Uploading… ${Math.min(i + 10, files.length)} of ${files.length}`);
      }
      setNotice(`${added} photo${added === 1 ? "" : "s"} added. They are being read now; you can start checking as soon as the first is ready.`
        + (refused.length ? ` Not added: ${refused.join("; ")}` : ""));
      load();
    } catch (e) { setError((e as Error).message); } finally { setUploading(false); }
  }

  async function act(fn: () => Promise<unknown>, done?: string) {
    setBusy(true); setError(null);
    try { await fn(); if (done) setNotice(done); load(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  // forms someone else has open are skipped (one person per form)
  const inUseByOthers = (f: TrainingFormRow) => !!f.lock && !f.lock.mine;
  const nextReady = forms.find((f) => f.status === "ready" && !inUseByOthers(f));
  const othersChecking = forms.filter((f) => f.status === "ready" && inUseByOthers(f)).length;
  async function checkNext() {
    setError(null);
    try {
      const r = await api.trainingNext();
      if (r.id) router.push(`/training/check?id=${r.id}`);
      else { setNotice("Every form waiting is being checked by someone else right now."); load(); }
    } catch (e) { setError((e as Error).message); }
  }
  const shown = forms.filter((f) => filter === "all" ? true : filter === "problem" ? ["problem", "failed"].includes(f.status) : f.status === filter)
    .slice().reverse();
  const enough = s?.settings.enough ?? 100;
  const few = s?.settings.few ?? 30;
  const toWork = (s?.per_character ?? []).filter((c) => c.level !== "enough" || c.reading === "often_misread" || c.reading === "sometimes_misread")
    .sort((a, b) => (a.reading === "often_misread" ? 0 : 1) - (b.reading === "often_misread" ? 0 : 1) || a.samples - b.samples)
    .slice(0, 8);
  const maxConf = Math.max(1, ...(s?.confusions ?? []).map((c) => c.count));
  const job = s?.job;
  const cand = s?.candidate;
  const progressNew = s ? Math.min(1, s.characters.new_since_training / (s.settings.retrain_after || 500)) : 0;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Handwriting</p>
          <h1>Reader training</h1>
          <p className="lead">Upload photos of page 1, check what is written, and train the reader on your own forms.</p>
        </div>
        <div className="head-actions">
          <button className="btn ghost icon-only" onClick={load} aria-label="Refresh" title="Refresh"><IconRefresh size={18} /></button>
          <button className="btn" onClick={() => input.current?.click()} disabled={uploading}><IconUpload size={17} /> Upload photos</button>
          <StaffName />
          {nextReady
            ? <button className="btn primary" onClick={checkNext}>Check next form <IconArrowRight size={17} /></button>
            : <button className="btn primary" disabled>{othersChecking ? "All forms are being checked" : "No form to check"}</button>}
        </div>
      </header>
      <input ref={input} type="file" multiple accept="image/jpeg,image/png,.jpg,.jpeg,.png" hidden
             onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />

      {error && <div className="notice error" role="alert"><IconAlert size={18} /><span>{error}</span></div>}
      {notice && <div className="notice info"><IconInfo size={18} /><span>{notice}</span>
        <button className="link-btn" onClick={() => setNotice(null)} aria-label="Close"><IconX size={15} /></button></div>}

      {/* ------------------------------------------------ figures */}
      <section className="kpis">
        <div className="kpi card">
          <div className="kpi-icon blue"><IconUpload size={20} /></div>
          <div className="kpi-label">Forms checked</div>
          <div className="kpi-value">{s ? s.forms.confirmed : "—"}<small> / {s?.forms.total ?? 0}</small></div>
          <div className="kpi-foot">{s ? `${s.forms.ready} to check · ${s.forms.queued + s.forms.reading} being read · ${s.forms.test} test` : " "}</div>
        </div>
        <div className="kpi card">
          <div className="kpi-icon teal"><IconTraining size={20} /></div>
          <div className="kpi-label">Characters collected</div>
          <div className="kpi-value">{s ? s.characters.samples.toLocaleString() : "—"}</div>
          <div className="kpi-foot">{s ? `from ${s.fields.used} of ${s.fields.checked} checked fields` : " "}</div>
        </div>
        <div className="kpi card">
          <div className="kpi-icon violet"><IconSparkle size={20} /></div>
          <div className="kpi-label">Read right first time</div>
          <div className="kpi-value">{pct(s?.characters.accuracy)}</div>
          <div className="kpi-foot">{s?.characters.checked ? `${s.characters.read_right.toLocaleString()} of ${s.characters.checked.toLocaleString()} characters checked` : "after the first checked forms"}</div>
        </div>
        <div className="kpi card">
          <div className="kpi-icon amber"><IconRefresh size={20} /></div>
          <div className="kpi-label">New since last training</div>
          <div className="kpi-value">{s ? s.characters.new_since_training.toLocaleString() : "—"}</div>
          <div className="kpi-foot">
            <span className="progress thin"><span style={{ width: `${progressNew * 100}%` }} /></span>
            {s ? `worth training from ${s.settings.retrain_after}` : " "}
          </div>
        </div>
      </section>

      <section className="grid-main">
        {/* ------------------------------------------------ advice */}
        <div className="card span-2">
          <div className="card-head"><div><h2>What to do next</h2><p className="muted">Based on the forms checked so far</p></div></div>
          {s && s.advice.length ? (
            <ul className="advice">
              {s.advice.map((a, i) => (
                <li key={i} className={a.level}>
                  {a.level === "action" ? <IconArrowRight size={17} /> : a.level === "warn" ? <IconAlert size={17} /> : <IconInfo size={17} />}
                  <span>{a.text}</span>
                </li>
              ))}
            </ul>
          ) : <p className="chart-empty">Upload photos of page 1 to begin.</p>}
        </div>

        {/* ------------------------------------------------ training */}
        <div className="card train-card">
          <div className="card-head"><div><h2>Train the reader</h2><p className="muted">
            {s?.models["char_cnn.npz"] ? `Model in use since ${formatDateTime(s.models["char_cnn.npz"])}` : " "}</p></div></div>
          {job?.state === "running" ? (
            <div className="train-run">
              <p><span className="spinner" /> <strong>Step {job.step} of {job.steps}:</strong> {job.step_name}</p>
              <span className="progress"><span style={{ width: `${((job.step || 0) / (job.steps || 3)) * 100}%` }} /></span>
              <p className="muted small-note">Started {formatDateTime(job.started_at)} with {job.samples?.toLocaleString()} characters. You can keep checking forms meanwhile.</p>
              {job.log && job.log.length > 0 && <pre className="train-log">{job.log.slice(-5).join("\n")}</pre>}
            </div>
          ) : cand && !cand.installed ? (
            <div className="train-result">
              <div className="compare">
                <div><span>Model in use</span><strong>{pct(cand.old_accuracy)}</strong></div>
                <div className={cand.better ? "win" : "lose"}><span>New model</span><strong>{pct(cand.new_accuracy)}</strong></div>
              </div>
              <p className="muted small-note">Characters read right on {cand.test_characters} characters of the test forms
                (never used for training).</p>
              {cand.better
                ? <p className="ok-line"><IconCheckCircle size={16} /> The new model reads better.</p>
                : <p className="bad-line"><IconAlert size={16} /> The new model is not better: keep the one in use.</p>}
              <div className="train-actions">
                <button className={`btn${cand.better ? " primary" : ""}`} disabled={busy}
                        onClick={() => { if (confirm("Use the new model now? The current one is kept as a backup.")) act(api.trainingInstall, "The new model is installed and used from the next reading."); }}>
                  <IconCheckCircle size={16} /> Install</button>
                {cand.files.map((f) => (
                  <a key={f} className="btn ghost small" href={api.trainingFileUrl(f)} download><IconDownload size={15} /> {f}</a>
                ))}
              </div>
            </div>
          ) : (
            <div className="train-idle">
              {job?.state === "failed" && <p className="bad-line"><IconAlert size={16} /> The last training failed: {job.error}</p>}
              {cand?.installed && <p className="ok-line"><IconCheckCircle size={16} /> The last trained model is installed
                ({pct(cand.new_accuracy)} on the test forms). Old model kept in {cand.backup}.</p>}
              <p className="muted">Trains on all checked forms (except the test forms) plus the reader's general
                handwriting, then compares the new model with the one in use. About 20 minutes.</p>
              {s && s.missing_packages?.length > 0 && <p className="bad-line"><IconAlert size={16} /> Install the training packages first:
                <code>pip install -r requirements-train.txt</code></p>}
              <button className="btn primary" disabled={busy || !s || s.missing_packages?.length > 0 || s.characters.samples < (s.settings.min_samples_to_train || 200)}
                      onClick={() => act(api.trainingStart, "Training started. This takes about 20 minutes.")}>
                <IconSparkle size={16} /> Start training</button>
              {s && s.characters.samples < (s.settings.min_samples_to_train || 200) &&
                <p className="muted small-note">Needs at least {s.settings.min_samples_to_train} characters ({s.characters.samples} so far).</p>}
            </div>
          )}
        </div>
      </section>

      {/* ------------------------------------------------ characters */}
      <section className="grid-main">
        <div className="card span-2">
          <div className="card-head">
            <div><h2>Samples per character</h2>
              <p className="muted">Number collected, and how often it was read right first time on checked forms</p></div>
          </div>
          <div className="tc-legend">
            <span><i className="lv-few" /> Needs more (under {few})</span>
            <span><i className="lv-mid" /> Moderate</span>
            <span><i className="lv-ok" /> Enough ({enough}+)</span>
            <span><i className="misread-key" /> Often misread</span>
          </div>
          <div className="tc-grid">
            {(s?.per_character ?? []).map((c) => <CharCell key={c.char} c={c} enough={enough} />)}
          </div>
          <table className="sr-only"><caption>Samples per character</caption><tbody>
            {(s?.per_character ?? []).map((c) => <tr key={c.char}><th>{c.char}</th><td>{c.samples}</td><td>{pct(c.accuracy, 0)}</td></tr>)}
          </tbody></table>
        </div>
        <div className="card">
          <div className="card-head"><div><h2>Characters to work on</h2><p className="muted">Fewest samples or most misread</p></div></div>
          {toWork.length ? (
            <ul className="work-list">
              {toWork.map((c) => (
                <li key={c.char}>
                  <span className={`work-char ${LEVEL[c.level].cls}`}>{c.char}</span>
                  <span className="work-text"><strong>{c.samples} samples{c.seen ? ` · ${pct(c.accuracy, 0)} right` : ""}</strong>
                    <span>{c.advice}</span></span>
                </li>
              ))}
            </ul>
          ) : <p className="chart-empty">{s?.characters.samples ? "All characters have enough samples." : "Nothing collected yet."}</p>}
        </div>
      </section>

      <section className="grid-main">
        {/* ------------------------------------------------ mix-ups */}
        <div className="card">
          <div className="card-head"><div><h2>Most common mix-ups</h2><p className="muted">Written → read as</p></div></div>
          {s && s.confusions.length ? (
            <div className="barlist">
              {s.confusions.map((c) => (
                <div key={c.char + c.read_as} className="bar-row">
                  <span className="bar-label mono">{c.char} → {c.read_as}</span>
                  <span className="bar-track"><span className="bar-fill" style={{ width: `${(c.count / maxConf) * 100}%` }} /></span>
                  <span className="bar-value">{c.count}</span>
                </div>
              ))}
            </div>
          ) : <p className="chart-empty">No mix-ups found yet.</p>}
          {s && Object.keys(s.fields.not_used_reasons).length > 0 && (
            <>
              <div className="card-head sub"><div><h2>Fields not used</h2><p className="muted">Typed text did not match the written boxes</p></div></div>
              <ul className="reasons">{Object.entries(s.fields.not_used_reasons).slice(0, 5).map(([r, n]) => <li key={r}><span>{r}</span><b>{n}</b></li>)}</ul>
            </>
          )}
        </div>

        {/* ------------------------------------------------ history */}
        <div className="card span-2">
          <div className="card-head"><div><h2>Training history</h2><p className="muted">Each training, compared on the test forms</p></div></div>
          {s && s.runs.length ? (
            <div className="table-wrap"><table className="table">
              <thead><tr><th>Trained</th><th>Characters</th><th>Model in use</th><th>New model</th><th>Result</th></tr></thead>
              <tbody>{s.runs.map((r) => (
                <tr key={r.trained_at}>
                  <td>{formatDateTime(r.trained_at)}</td><td>{r.samples.toLocaleString()}</td>
                  <td>{pct(r.old_accuracy)}</td><td><strong>{pct(r.new_accuracy)}</strong></td>
                  <td>{r.installed ? <span className="chip ok">Installed</span> : r.better ? <span className="chip edited">Better, not installed</span>
                    : <span className="chip">Not better</span>}</td>
                </tr>))}</tbody>
            </table></div>
          ) : <p className="chart-empty">No training yet.</p>}
        </div>
      </section>

      {/* ------------------------------------------------ forms */}
      <section className="card">
        <div className="card-head">
          <div><h2>Uploaded forms</h2><p className="muted">Page 1 photos. Every {s?.settings.test_every ?? 10}th is a test form, never trained on.</p></div>
          <div className="segmented" role="group" aria-label="Show">
            {(["all", "ready", "confirmed", "problem"] as const).map((k) => (
              <button key={k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>
                {k === "all" ? "All" : k === "ready" ? `To check (${s?.forms.ready ?? 0})` : k === "confirmed" ? "Checked" : `Problems (${(s?.forms.problem ?? 0) + (s?.forms.failed ?? 0)})`}
              </button>
            ))}
          </div>
        </div>
        <div className={`dropzone small-drop${over ? " over" : ""}`} role="button" tabIndex={0}
             onClick={() => input.current?.click()}
             onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") input.current?.click(); }}
             onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
             onDrop={(e) => { e.preventDefault(); setOver(false); upload(e.dataTransfer.files); }}>
          {uploading ? <><span className="spinner" /> {notice}</> : <><IconUpload size={20} /> <strong>Drop photos of page 1 here</strong>
            <span className="muted">many at once · JPG or PNG · different writers teach the most</span></>}
        </div>
        {shown.length ? (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>#</th><th>Photo</th><th>Status</th><th>Fields</th><th>Test</th><th /></tr></thead>
            <tbody>{shown.map((f) => (
              <tr key={f.id}>
                <td className="muted">{f.seq}</td>
                <td><span className="file-name" title={f.filename}>{f.filename}</span>
                  {f.problem && <div className="row-problem">{f.problem}</div>}</td>
                <td><span className={`chip ${STATUS[f.status]?.cls ?? ""}`}>{STATUS[f.status]?.label ?? f.status}</span>
                  {inUseByOthers(f) && <span className="chip in-use-chip" title={`Opened at ${formatDateTime(f.lock!.since)}`}>
                    <IconLock size={12} /> Being checked by {f.lock!.name}</span>}</td>
                <td>{f.status === "confirmed" ? `${f.fields_used} of ${f.fields} used` : f.fields ? `${f.fields}${f.unsure ? ` · ${f.unsure} unsure` : ""}` : "—"}</td>
                <td><label className="check-line small"><input type="checkbox" checked={f.test} disabled={busy}
                       onChange={(e) => act(() => api.trainingSetTest(f.id, e.target.checked))} /> Test</label></td>
                <td className="row-actions">
                  {(f.status === "ready" || f.status === "confirmed") && !inUseByOthers(f) &&
                    <Link className="btn small" href={`/training/check?id=${f.id}`}>{f.status === "ready" ? "Check" : "Open"}</Link>}
                  {(f.status === "problem" || f.status === "failed" || f.status === "skipped") &&
                    <button className="btn small" disabled={busy} onClick={() => act(() => api.trainingRetry(f.id))}>Read anyway</button>}
                  <button className="btn ghost small icon-only" disabled={busy || inUseByOthers(f)} aria-label="Remove" title="Remove"
                          onClick={() => { if (confirm(`Remove ${f.filename}? Its samples are removed too.`)) act(() => api.trainingDelete(f.id)); }}>
                    <IconX size={15} /></button>
                </td>
              </tr>))}</tbody>
          </table></div>
        ) : <p className="chart-empty">{forms.length ? "Nothing here." : "No photos uploaded yet."}</p>}
      </section>
    </div>
  );
}
