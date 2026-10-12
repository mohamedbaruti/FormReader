"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, formatDateTime, type FormLock, type TrainingField, type TrainingForm } from "@/lib/api";
import { sectionStyle } from "@/lib/sections";
import PhotoViewer from "@/components/PhotoViewer";
import StaffName from "@/components/StaffName";
import { IconAlert, IconArrowLeft, IconArrowRight, IconCheck, IconEye, IconInfo, IconLock, IconX } from "@/components/Icons";

const SECTION_NAMES: Record<string, string> = { A: "Personal details", B: "Parent details", C: "Citizenship details" };

/** Characters that must match the written boxes one to one (spaces and / are not boxes). */
const keyOf = (t: string) => t.toUpperCase().replace(/[\s/]/g, "");

function FieldCheck({ f, value, onChange, onEnter }: {
  f: TrainingField; value: string; onChange: (v: string) => void; onEnter: () => void;
}) {
  const n = f.boxes.length;
  const k = keyOf(value);
  const bad = k && /[^A-Z0-9]/.test(k);
  const state = !k ? "empty" : bad ? "bad" : k.length === n ? "ok" : "bad";
  const num = f.label.match(/^(\d+)\./)?.[1];
  return (
    <div className={`field tfield ${state}${f.unsure ? " flagged" : ""}`}>
      <div className="field-top">
        <label className="field-label" htmlFor={`t-${f.name}`} title={f.label}>
          {num && <span className="field-num">{num}</span>}{f.label_en}
        </label>
        <span className="chips">{f.unsure && <span className="chip warn">Please check</span>}</span>
      </div>
      <div className="crop-row"><div className="crop">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {f.image && <img src={f.image} alt={`${f.label_en} as written`} />}
      </div></div>
      <input id={`t-${f.name}`} className="text-input" value={value} autoComplete="off" spellCheck={false}
             onChange={(e) => onChange(e.target.value.toUpperCase())}
             onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); onEnter(); } }} />
      <p className={`box-count ${state}`}>
        {state === "ok" ? <><IconCheck size={14} /> {k.length} characters · {n} boxes with writing</>
          : state === "empty" ? <>Left empty: not used for training</>
          : bad ? <><IconAlert size={14} /> Only letters A–Z and digits 0–9 can be learned: not used</>
          : <><IconAlert size={14} /> {k.length} typed, {n} boxes with writing: not used for training</>}
      </p>
    </div>
  );
}

function CheckForm() {
  const id = useSearchParams().get("id") || "";
  const router = useRouter();
  const [form, setForm] = useState<TrainingForm | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [left, setLeft] = useState<number | null>(null);
  const [viewer, setViewer] = useState(false);
  // only one person checks a form at a time: "pending" while asking, "mine" when this tab has it,
  // "other" when someone else has it open, "lost" when someone took it over while this tab was idle
  const [hold, setHold] = useState<{ state: "pending" | "mine" | "other" | "lost"; lock?: FormLock }>({ state: "pending" });
  const holdRef = useRef(hold.state);
  holdRef.current = hold.state;
  const lastActive = useRef(Date.now());
  const top = useRef<HTMLDivElement>(null);

  const lockOf = (e: unknown) => (e instanceof ApiError ? (e.body as { lock?: FormLock } | null)?.lock : undefined);

  const load = useCallback((fid: string) => {
    api.trainingForm(fid).then((f) => {
      setForm(f);
      setValues(Object.fromEntries(f.fields.map((x) => [x.name, x.typed ?? x.read])));
      window.scrollTo({ top: 0 });
      setTimeout(() => document.getElementById(`t-${f.fields[0]?.name}`)?.focus(), 50);
    }).catch((e: Error) => setError(e.message));
  }, []);

  // open the form for this person (or find out who has it), and keep it open while the page is shown
  useEffect(() => {
    if (!id) return;
    let alive = true;
    setForm(null); setError(null); setHold({ state: "pending" });
    lastActive.current = Date.now();
    api.trainingLock(id).then(() => {
      if (!alive) return;
      setHold({ state: "mine" });
      load(id);
    }).catch((e: Error) => {
      if (!alive) return;
      const lk = lockOf(e);
      if (lk) setHold({ state: "other", lock: lk }); else setError(e.message);
    });
    api.trainingForms().then((r) => alive && setLeft(r.items.filter(
      (x) => x.status === "ready" && x.id !== id && !(x.lock && !x.lock.mine)).length)).catch(() => {});

    const beat = setInterval(() => {
      if (holdRef.current !== "mine") return;
      api.trainingLock(id, (Date.now() - lastActive.current) / 1000).catch((e: Error) => {
        const lk = lockOf(e);
        if (alive && lk) setHold({ state: "lost", lock: lk });
      });
    }, 30000);
    const active = () => { lastActive.current = Date.now(); };
    const leave = () => api.trainingUnlock(id);
    window.addEventListener("keydown", active);
    window.addEventListener("pointerdown", active);
    window.addEventListener("pagehide", leave);
    return () => {
      alive = false;
      clearInterval(beat);
      window.removeEventListener("keydown", active);
      window.removeEventListener("pointerdown", active);
      window.removeEventListener("pagehide", leave);
      api.trainingUnlock(id);                 // only frees it if this tab has it
    };
  }, [id, load]);

  async function takeOver() {
    if (!hold.lock || !window.confirm(`${hold.lock.name} opened this form but has not typed anything for `
      + `${hold.lock.idle_minutes} minutes. Take it over? Their unsaved typing will be lost.`)) return;
    setError(null);
    try {
      await api.trainingLock(id, 0, true);
      setHold({ state: "mine" });
      load(id);
    } catch (e) {
      const lk = lockOf(e);
      if (lk) setHold({ state: "other", lock: lk }); else setError((e as Error).message);
    }
  }

  const sections = useMemo(() => {
    const m = new Map<string, TrainingField[]>();
    for (const f of form?.fields ?? []) m.set(f.section, [...(m.get(f.section) ?? []), f]);
    return Array.from(m.entries());
  }, [form]);
  const order = form?.fields.map((f) => f.name) ?? [];
  const usable = form?.fields.filter((f) => { const k = keyOf(values[f.name] ?? ""); return k && !/[^A-Z0-9]/.test(k) && k.length === f.boxes.length; }) ?? [];
  const chars = usable.reduce((n, f) => n + f.boxes.length, 0);

  /** the next form waiting that nobody else has open (opened for this person by the reader) */
  async function goNext() {
    const r = await api.trainingNext(id);
    router.push(r.id ? `/training/check?id=${r.id}` : "/training");
  }

  function failed(e: unknown) {
    const lk = lockOf(e);
    if (lk) setHold({ state: "lost", lock: lk });
    setError((e as Error).message);
  }

  async function confirmForm() {
    if (!form) return;
    setBusy(true); setError(null);
    try { await api.trainingConfirm(form.id, values); await goNext(); }
    catch (e) { failed(e); } finally { setBusy(false); }
  }
  async function skipForm() {
    if (!form) return;
    setBusy(true);
    try { await api.trainingSkip(form.id); await goNext(); }
    catch (e) { failed(e); } finally { setBusy(false); }
  }

  if (!id) return <div className="page"><p>No form chosen. <Link href="/training">Back to training</Link></p></div>;

  return (
    <div className="page" ref={top}>
      <header className="page-head">
        <div>
          <p className="eyebrow">Reader training · check a form</p>
          <h1>{form ? `Form #${form.seq}` : hold.state === "other" ? "Form in use" : "Loading…"} {form?.test && <span className="chip edited test-chip">Test form</span>}</h1>
          <p className="lead">{form?.filename}{left != null ? ` · ${left} more waiting to be checked` : ""}</p>
        </div>
        <div className="head-actions">
          <StaffName compact />
          <Link href="/training" className="btn ghost"><IconArrowLeft size={16} /> Back to training</Link>
        </div>
      </header>

      {hold.state === "other" && hold.lock && (
        <div className="card in-use" role="status">
          <span className="in-use-icon"><IconLock size={22} /></span>
          <div>
            <h3>{hold.lock.name} is checking this form</h3>
            <p className="muted">Opened at {formatDateTime(hold.lock.since)}
              {hold.lock.idle_minutes > 0 ? ` · nothing typed for ${hold.lock.idle_minutes} min` : " · typing now"}.
              Two people cannot check the same form, so please take another one.</p>
            <div className="in-use-actions">
              <button className="btn primary" onClick={() => api.trainingNext().then((r) =>
                router.push(r.id ? `/training/check?id=${r.id}` : "/training")).catch((e: Error) => setError(e.message))}>
                Check another form <IconArrowRight size={16} /></button>
              {hold.lock.can_take_over &&
                <button className="btn ghost" onClick={takeOver}>Take over this form</button>}
            </div>
          </div>
        </div>
      )}
      {hold.state === "lost" && hold.lock && (
        <div className="notice error" role="alert"><IconLock size={18} />
          <span><strong>{hold.lock.name} took over this form</strong> after it was left without typing for a while.
            What you typed here is not saved. <button className="link-btn" onClick={() => api.trainingNext().then((r) =>
              router.push(r.id ? `/training/check?id=${r.id}` : "/training"))}>Check another form</button></span>
        </div>
      )}

      <div className="notice info rule-note">
        <IconInfo size={18} />
        <span><strong>Type exactly what is written, one character for each box</strong>, even spelling mistakes
          (MOHAMED stays MOHAMED) and place names as written (MBEYA MJINI). There are no rules or lists here:
          the reader is learning what each written character looks like.
          {form?.test && <> This is a <strong>test form</strong>: it is not trained on, it measures new models.</>}</span>
      </div>
      {error && <div className="notice error" role="alert"><IconAlert size={18} /><span>{error}</span></div>}
      {form && form.status !== "ready" && form.status !== "confirmed" && (
        <div className="notice warn"><IconAlert size={18} /><span>This form is not ready to check ({form.status}).</span></div>
      )}

      {form && (
        <div className="tcheck-layout">
          <aside className="card tcheck-side">
            <button className="photo-big" onClick={() => setViewer(true)} aria-label="Open the photo">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={api.trainingPhotoUrl(form.id)} alt="Photo of page 1" />
              <span><IconEye size={14} /> Open photo</span>
            </button>
            <div className="tcheck-sum">
              <div><strong>{usable.length}</strong><span>of {form.fields.length} fields usable</span></div>
              <div><strong>{chars}</strong><span>characters to learn</span></div>
            </div>
            <p className="muted small-note">Press Enter to go to the next field.</p>
          </aside>

          <div className="tcheck-main">
            {sections.map(([sec, fields]) => (
              <section key={sec} className="section card" style={sectionStyle(sec)}>
                <header className="section-head static">
                  <span className="section-toggle">
                    <span className="section-letter">{sec}</span>
                    <span className="section-names">
                      <span className="section-kicker">Section {sec} · {fields.length} fields with writing</span>
                      <span className="section-title">{SECTION_NAMES[sec] ?? `Section ${sec}`}</span>
                    </span>
                  </span>
                </header>
                <div className="section-body"><div className="fields">
                  {fields.map((f) => (
                    <FieldCheck key={f.name} f={f} value={values[f.name] ?? ""}
                                onChange={(v) => setValues((o) => ({ ...o, [f.name]: v }))}
                                onEnter={() => {
                                  const nxt = order[order.indexOf(f.name) + 1];
                                  if (nxt) document.getElementById(`t-${nxt}`)?.focus();
                                }} />
                  ))}
                </div></div>
              </section>
            ))}

            <div className="save-bar glass-light">
              <div className="save-progress">
                <span className="muted">{usable.length} of {form.fields.length} fields will be used · {chars} characters</span>
                <span className="progress"><span style={{ width: `${(usable.length / Math.max(1, form.fields.length)) * 100}%` }} /></span>
              </div>
              <div className="save-actions">
                <button className="btn ghost" onClick={skipForm} disabled={busy || hold.state !== "mine"}><IconX size={15} /> Skip form</button>
                <button className="btn primary big" onClick={confirmForm} disabled={busy || hold.state !== "mine"}>
                  {busy ? <><span className="spinner" /> Saving…</> : <>Confirm{left ? " & next" : ""} <IconArrowRight size={17} /></>}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {viewer && form && <PhotoViewer src={api.trainingPhotoUrl(form.id)} alt="Photo of page 1" onClose={() => setViewer(false)} />}
    </div>
  );
}

export default function CheckPage() {
  return <Suspense fallback={<div className="page"><p className="muted">Loading…</p></div>}><CheckForm /></Suspense>;
}
