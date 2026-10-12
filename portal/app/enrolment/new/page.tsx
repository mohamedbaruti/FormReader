"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api, ApiError, type ExtractResult, type Field, type InspectResult, type Issue as RuleIssue, type SaveResult, type Section, type Value,
} from "@/lib/api";
import UploadCard, { shortTitle, type CheckState, type Issue } from "@/components/enrolment/UploadCard";
import SectionCard from "@/components/enrolment/SectionCard";
import SectionNav from "@/components/enrolment/SectionNav";
import PhotoViewer from "@/components/PhotoViewer";
import EndorsementList from "@/components/enrolment/EndorsementList";
import { saveTextFile } from "@/lib/device";
import { choicesFor, fillPostcodes, setPlace } from "@/lib/places";
import {
  IconAlert, IconArrowLeft, IconArrowRight, IconCheckCircle, IconDownload, IconEye, IconSparkle, IconSwap,
} from "@/components/Icons";

type Stage = "upload" | "reading" | "review" | "saving" | "saved";

// The Swahili section names stay here on purpose: they match the headings printed
// on the paper, so the user can see which photo goes in which box.
const PAGE_INFO = [
  { title: "Photo of page 1", sections: ["A · Taarifa binafsi", "B · Taarifa za wazazi", "C · Taarifa za uraia"] },
  { title: "Photo of page 2", sections: ["D · Mahali anapoishi", "E · Anuani ya makazi", "F · Kumbukumbu binafsi",
                                          "G · Tamko", "H · Matumizi ya ofisi"] },
];

const READING_STEPS = ["Recognising the form edition", "Straightening the photos", "Finding the boxes", "Reading the handwriting"];

interface Photo { id: number; file: File; check: CheckState }

function Steps({ stage }: { stage: Stage }) {
  const idx = stage === "upload" || stage === "reading" ? 0 : stage === "saved" ? 2 : 1;
  const names = ["Upload photos", "Check & confirm", "Saved"];
  return (
    <ol className="steps" aria-label="Progress">
      {names.map((n, i) => (
        <li key={n} className={i < idx ? "done" : i === idx ? "current" : ""} aria-current={i === idx ? "step" : undefined}>
          <span className="step-dot">{i < idx ? "✓" : i + 1}</span>{n}
        </li>
      ))}
    </ol>
  );
}

const sameFile = (a: File, b: File) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

export default function NewEnrolment() {
  const [stage, setStage] = useState<Stage>("upload");
  // photos: each keeps the result of its own check, so moving or swapping keeps it
  const [photos, setPhotos] = useState<Record<number, Photo>>({});
  const [slots, setSlots] = useState<(number | null)[]>([null, null]);
  const [kept, setKept] = useState<Record<string, boolean>>({});      // "photoId:slot:issue" the user chose to keep
  const nextId = useRef(1);

  const [result, setResult] = useState<ExtractResult | null>(null);
  const [values, setValues] = useState<Record<string, Value>>({});
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [openId, setOpenId] = useState<string | null>(null);   // the one section open (accordion)
  const [tab, setTab] = useState(0);
  const [active, setActive] = useState<string | null>(null);
  const [pendingScroll, setPendingScroll] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readStep, setReadStep] = useState(0);
  const [saved, setSaved] = useState<SaveResult | null>(null);
  const [viewer, setViewer] = useState<string | null>(null);
  const [photoUrls, setPhotoUrls] = useState<(string | null)[]>([null, null]);
  const [ruleIssues, setRuleIssues] = useState<RuleIssue[]>([]);   // logic checks on the values

  const slotPhoto = (i: number) => (slots[i] != null ? photos[slots[i]!] ?? null : null);
  const files = [slotPhoto(0)?.file ?? null, slotPhoto(1)?.file ?? null];

  // ---------------------------------------------------------------- photo checks
  const runCheck = useCallback((id: number, file: File) => {
    setPhotos((old) => ({ ...old, [id]: { id, file, check: { state: "checking" } } }));
    api.inspect(file)
      .then((r) => setPhotos((old) => old[id] ? { ...old, [id]: { ...old[id], check: { state: "done", r } } } : old))
      .catch((e: Error) => setPhotos((old) => old[id] ? { ...old, [id]: { ...old[id], check: { state: "error", message: e.message } } } : old));
  }, []);

  function setSlotFile(slot: number, file: File | null) {
    if (!file) { setSlots((s) => s.map((x, j) => (j === slot ? null : x))); return; }
    const id = nextId.current++;
    runCheck(id, file);
    setSlots((s) => s.map((x, j) => (j === slot ? id : x)));
  }
  const swap = () => setSlots(([a, b]) => [b, a]);
  const move = (from: number, to: number) => setSlots((s) => { const n = [...s]; n[to] = s[from]; n[from] = null; return n; });
  const keepKey = (slot: number, code: string) => `${slots[slot]}:${slot}:${code}`;

  const r0 = slotPhoto(0)?.check?.state === "done" ? (slotPhoto(0)!.check as { r: InspectResult }).r : null;

  function issuesFor(slot: number): Issue[] {
    const ph = slotPhoto(slot);
    if (!ph || !ph.check || ph.check.state === "checking") return [];
    const out: Issue[] = [];
    const keep = (code: string) => () => setKept((k) => ({ ...k, [keepKey(slot, code)]: true }));
    const undo = (code: string) => () => setKept((k) => { const n = { ...k }; delete n[keepKey(slot, code)]; return n; });
    const add = (i: Issue) => out.push({ ...i, acknowledged: !!kept[keepKey(slot, i.code)], onUndo: undo(i.code) });

    if (ph.check.state === "error") {
      add({ code: "check-failed", tone: "error", title: "Could not check this photo", text: ph.check.message,
            actions: [{ label: "Try again", primary: true, onClick: () => runCheck(ph.id, ph.file) },
                      { label: "Use it anyway", onClick: keep("check-failed") }] });
      return out;
    }
    const r = ph.check.r;
    if (!r.recognised) {
      add({ code: "unknown", tone: "warn", title: "This does not look like a page of Form 1A",
            text: "The reader could not match it to any known edition of the form. Check that it is the right photo and that the whole page is visible and in focus.",
            actions: [{ label: "Choose another photo", replace: true, primary: true },
                      { label: "Use it anyway", onClick: keep("unknown") }] });
      return out;
    }
    if (r.page !== slot + 1) {
      const target = r.page - 1;
      const otherFilled = slots[target] != null;
      add({ code: "wrong-page", tone: "warn", title: `This looks like page ${r.page}, not page ${slot + 1}`,
            text: otherFilled
              ? `The two photos seem to be in the wrong boxes. Swap them so page ${slot + 1} is in the "Page ${slot + 1}" box.`
              : `This photo appears to be page ${r.page} of the form. Move it to the "Page ${r.page}" box.`,
            actions: [otherFilled
              ? { label: "Swap the photos", primary: true, icon: <IconSwap size={15} />, onClick: swap }
              : { label: `Move to page ${r.page}`, primary: true, icon: <IconSwap size={15} />, onClick: () => move(slot, target) },
              { label: `It is page ${slot + 1}, keep it`, onClick: keep("wrong-page") }] });
    }
    // the two pages must be of the same paper form: some edition must have both
    // (1.4 has two printings of page 2, so page 1 and page 2 can each fit several editions)
    if (slot === 1 && r0?.recognised && r0.page === 1 && r.page === 2
        && !r.compatible_forms.some((f) => r0.compatible_forms.includes(f))) {
      add({ code: "edition", tone: "warn", title: "Page 2 does not match page 1",
            text: `Page 1 is ${shortTitle(r0.form_title)}, but this page 2 belongs to a different edition of the form. Both photos should be of the same paper form.`,
            actions: [{ label: "Choose another photo", replace: true, primary: true }, { label: "Keep it", onClick: keep("edition") }] });
    }
    const other = slotPhoto(1 - slot);
    if (slot === 1 && other && sameFile(other.file, ph.file)) {
      add({ code: "same-photo", tone: "warn", title: "The same photo is in both boxes",
            text: "Page 1 and page 2 need different photos.",
            actions: [{ label: "Choose another photo", replace: true, primary: true }, { label: "Keep it", onClick: keep("same-photo") }] });
    }
    // page 2: signatures and stamps (items 59, 60, 68, 70, 71), checked by the reader (app/endorsements.py)
    const en = r.page === 2 && !r.blank ? r.endorsements : null;
    if (en && en.missing > 0) {
      add({ code: "endorsements", tone: "warn",
            title: `${en.missing} signature${en.missing === 1 ? "" : "s"} or stamp${en.missing === 1 ? "" : "s"} missing on page 2`,
            text: "Each missing part is listed below with a picture of its box. If the form really is missing them, it must be "
              + "completed before enrolment. If they are there and the reader missed them, continue.",
            details: <EndorsementList items={en.items} />,
            actions: [{ label: "Choose another photo", replace: true, primary: true },
                      { label: "They are there, continue", onClick: keep("endorsements") }] });
    } else if (en && en.unsure > 0) {
      add({ code: "endorsements-look", tone: "info", title: "Please look at the signatures on page 2",
            text: "All signature and stamp boxes have something in them, but the reader could not see everything clearly.",
            details: <EndorsementList items={en.items} />, actions: [] });
    }
    if (r.blank) {
      add({ code: "blank", tone: "warn", title: "No handwriting found: is the form empty?",
            text: `Nothing seems to be written in any box on this page${r.page === 2 ? " and no box is ticked" : ""}. Check that this is the filled-in form and not a blank copy.`,
            actions: [{ label: "Choose another photo", replace: true, primary: true },
                      { label: "The form is correct, use it", onClick: keep("blank") }] });
    }
    return out;
  }

  const issues = [issuesFor(0), issuesFor(1)];
  const openIssues = issues.flat().filter((i) => !i.acknowledged && i.tone !== "info").length;
  const checking = [0, 1].some((i) => slotPhoto(i)?.check?.state === "checking");
  // A complete form has both pages: both photos are required.
  const missing = [!files[0], !files[1]];
  const canRead = !missing[0] && !missing[1] && !checking && openIssues === 0;
  const blockers = [
    missing[0] && "add the photo of page 1",
    missing[1] && "add the photo of page 2",
    checking && "wait for the photo check",
    openIssues > 0 && `look at ${openIssues === 1 ? "the note" : `the ${openIssues} notes`} on the photos`,
  ].filter(Boolean) as string[];

  // ---------------------------------------------------------------- review helpers
  useEffect(() => {
    const urls = files.map((f) => (f ? URL.createObjectURL(f) : null));
    setPhotoUrls(urls);
    return () => urls.forEach((u) => u && URL.revokeObjectURL(u));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files[0], files[1]]);

  useEffect(() => {
    if (stage !== "reading") return;
    setReadStep(0);
    const t = setInterval(() => setReadStep((s) => Math.min(s + 1, READING_STEPS.length - 1)), 900);
    return () => clearInterval(t);
  }, [stage]);

  useEffect(() => {
    if (stage !== "review") return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [stage]);

  const allSections = useMemo(() => result?.pages.flatMap((p) => p.sections) ?? [], [result]);
  const confirmedCount = allSections.filter((s) => confirmed[s.id]).length;
  const allConfirmed = allSections.length > 0 && confirmedCount === allSections.length;
  // every field by name (for the linked region / district / ward dropdowns)
  const fieldMeta = useMemo(() => {
    const m: Record<string, Field> = {};
    for (const s of allSections) for (const f of s.fields) m[f.name] = f;
    return m;
  }, [allSections]);
  const lists = useMemo(() => result?.lookups ?? {}, [result]);
  const onFieldChange = (name: string, v: Value) =>
    setValues((old) => fillPostcodes(
      fieldMeta[name]?.lookup ? setPlace(name, v, old, fieldMeta, lists) : { ...old, [name]: v }, fieldMeta, lists));

  const pageOf = useCallback((id: string) => allSections.find((s) => s.id === id)?.page ?? 0, [allSections]);

  // ---------------------------------------------------------------- logic checks (rules set in the reader's
  // validation_rules.json): run again shortly after every change
  useEffect(() => {
    if (stage !== "review" || !result) return;
    const t = setTimeout(() => {
      api.validate(values).then((r) => setRuleIssues(r.issues)).catch(() => { /* keep the last result */ });
    }, 350);
    return () => clearTimeout(t);
  }, [values, stage, result]);

  const problemsByField = useMemo(() => {
    const m: Record<string, RuleIssue[]> = {};
    for (const i of ruleIssues) for (const f of i.fields) (m[f] ||= []).push(i);
    return m;
  }, [ruleIssues]);
  const sectionFieldNames = (s: Section) => s.fields.flatMap((f) => (f.attached ? [f.name, f.attached.name] : [f.name]));
  const errorsBySection = useMemo(() => {
    const m: Record<string, number> = {};
    for (const s of allSections) {
      const names = new Set(sectionFieldNames(s));
      m[s.id] = ruleIssues.filter((i) => i.severity === "error" && i.fields.some((f) => names.has(f))).length;
    }
    return m;
  }, [ruleIssues, allSections]);
  const errorCount = ruleIssues.filter((i) => i.severity === "error").length;

  // a confirmed section that now has a problem is no longer confirmed
  useEffect(() => {
    setConfirmed((c) => {
      const bad = Object.keys(c).filter((id) => c[id] && errorsBySection[id] > 0);
      if (!bad.length) return c;
      const n = { ...c };
      bad.forEach((id) => { n[id] = false; });
      return n;
    });
  }, [errorsBySection]);

  // which section is on screen (for the navigator)
  useEffect(() => {
    if (stage !== "review" && stage !== "saving") return;
    let frame = 0;
    const onScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const els = Array.from(document.querySelectorAll<HTMLElement>("[data-section]"));
        if (!els.length) return;
        const line = Math.min(220, window.innerHeight * 0.3);
        let current = els[0].dataset.section!;
        for (const el of els) if (el.getBoundingClientRect().top <= line) current = el.dataset.section!;
        if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
          const last = els.filter((el) => el.getBoundingClientRect().top < window.innerHeight * 0.6).pop();
          if (last) current = last.dataset.section!;
        }
        setActive(current);
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); };
  }, [stage, tab, result]);

  // scroll to a section once its page tab is showing
  useEffect(() => {
    if (!pendingScroll) return;
    const id = pendingScroll;
    const t = requestAnimationFrame(() => {
      document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
      setActive(id);
      setPendingScroll(null);
    });
    return () => cancelAnimationFrame(t);
  }, [pendingScroll, tab]);

  function switchPage(p: number) {
    const first = pages0()[p]?.sections[0]?.id;
    if (first) goTo(first); else setTab(p);
  }
  const pages0 = () => result?.pages ?? [];

  /** open one section (closing the others), showing its page, and scroll to it */
  function goTo(id: string) {
    setOpenId(id);
    const p = pageOf(id);
    if (p !== tab) setTab(p);
    setPendingScroll(id);
  }

  /** the next section after `id` (in form order) that is not yet confirmed, else simply the next one */
  function nextAfter(id: string, conf = confirmed): Section | null {
    const i = allSections.findIndex((s) => s.id === id);
    const rest = [...allSections.slice(i + 1), ...allSections.slice(0, i)];
    return rest.find((s) => !conf[s.id]) ?? null;
  }

  function onConfirm(s: Section, v: boolean, fromFooter: boolean) {
    if (v && errorsBySection[s.id] > 0) return;      // fix the problems first
    const conf = { ...confirmed, [s.id]: v };
    setConfirmed(conf);
    if (!v) return;
    setOpenId((o) => (o === s.id ? null : o));
    if (fromFooter) {
      const n = nextAfter(s.id, conf);
      if (n) goTo(n.id);
      else document.getElementById("save-bar")?.scrollIntoView({ behavior: "smooth", block: "end" });
    } else {
      // collapsing moves the page; keep the confirmed section's header in view
      setPendingScroll(s.id);
    }
  }

  // ---------------------------------------------------------------- actions
  async function read() {
    if (!canRead) return;
    setError(null);
    setStage("reading");
    try {
      const send = files.filter(Boolean) as File[];
      const r = await api.extract(send);
      setResult(r);
      setValues({ ...r.data });
      setRuleIssues(r.issues ?? []);
      setConfirmed({});
      setOpenId(r.pages[0]?.sections[0]?.id ?? null);     // only section A open to start
      setTab(0);
      setActive(r.pages[0]?.sections[0]?.id ?? null);
      setStage("review");
      window.scrollTo({ top: 0 });
    } catch (e) {
      setError((e as Error).message);
      setStage("upload");
    }
  }

  async function save() {
    if (!result || !allConfirmed || errorCount > 0) return;
    setStage("saving");
    setError(null);
    try {
      const r = await api.save(result.job_id, values, allSections.map((s) => s.id));
      setSaved(r);
      setStage("saved");
      window.scrollTo({ top: 0 });
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as { issues?: RuleIssue[] } | null) : null;
      if (body?.issues) setRuleIssues(body.issues);
      setError((e as Error).message);
      setStage("review");
    }
  }

  function downloadJson() {
    const data = saved?.data ?? values;
    const name = [data.first_name, data.last_name].filter(Boolean).join("_") || "enrolment";
    saveTextFile(`${name}.json`, JSON.stringify({ form: result?.form, ...data }, null, 2));
  }


  function reset() {
    setStage("upload"); setPhotos({}); setSlots([null, null]); setKept({}); setResult(null); setValues({});
    setConfirmed({}); setOpenId(null); setSaved(null); setError(null);
  }

  // ---------------------------------------------------------------- upload
  if (stage === "upload" || stage === "reading") {
    return (
      <div className="page">
        <header className="page-head">
          <div>
            <p className="eyebrow">New enrolment</p>
            <h1>Upload the form photos</h1>
            <p className="lead">Add a clear photo of each page of the filled NIDA Form 1A. Each photo is checked as soon as you add it.</p>
          </div>
          <Steps stage={stage} />
        </header>

        {error && <div className="notice error" role="alert"><IconAlert size={18} /><span>{error}</span></div>}

        <div className="upload-grid">
          {[0, 1].map((i) => (
            <UploadCard key={i} page={i + 1} title={PAGE_INFO[i].title} sections={PAGE_INFO[i].sections}
                        file={files[i]} check={slotPhoto(i)?.check ?? null} issues={issues[i]}
                        onFile={(f) => setSlotFile(i, f)} />
          ))}
        </div>

        <div className="card tips">
          <IconSparkle size={18} />
          <p><strong>For best results:</strong> whole page in the photo, in focus, even light without shadows across the boxes.
            The page can be a little tilted: the reader straightens it.</p>
        </div>

        <div className="action-bar">
          <span className={`ready-line${canRead ? " ready" : ""}`}>
            {canRead
              ? <><IconCheckCircle size={18} /> Both photos are checked and ready to read</>
              : <>To continue, {blockers.join(", ")}.</>}
          </span>
          <button className="btn primary big" onClick={read} disabled={!canRead || stage === "reading"}>
            {stage === "reading" ? <><span className="spinner" /> Reading…</> : <>Read the form <IconArrowRight size={18} /></>}
          </button>
        </div>

        {stage === "reading" && (
          <div className="reading-overlay" role="status" aria-live="polite">
            <div className="reading-card glass-light">
              <span className="spinner big" />
              <h3>Reading the form</h3>
              <ul>
                {READING_STEPS.map((s, i) => (
                  <li key={s} className={i < readStep ? "done" : i === readStep ? "now" : ""}>{i < readStep ? "✓ " : ""}{s}</li>
                ))}
              </ul>
              <p className="muted">This usually takes 10 to 20 seconds.</p>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------- saved
  if (stage === "saved" && saved) {
    const d = saved.data;
    const name = [d.first_name, d.middle_name, d.last_name].filter(Boolean).join(" ");
    return (
      <div className="page">
        <header className="page-head"><div><p className="eyebrow">New enrolment</p><h1>Enrolment saved</h1></div><Steps stage="saved" /></header>
        <div className="card saved-card">
          <IconCheckCircle size={48} className="ok-mark" />
          <h2>{name || "Record saved"}</h2>
          <p className="muted">Record {saved.id} · {saved.fields_corrected} field{saved.fields_corrected === 1 ? "" : "s"} corrected during review</p>
          <div className="saved-actions">
            <button className="btn primary" onClick={reset}>New enrolment</button>
            <Link className="btn" href={`/enrolments?id=${saved.id}`}>View record</Link>
            <button className="btn ghost" onClick={downloadJson}><IconDownload size={16} /> Download JSON</button>
          </div>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------- review
  if (!result) return null;
  const pages = result.pages;
  const page = pages[Math.min(tab, pages.length - 1)];
  const pageConfirmed = (p: number) => pages[p].sections.filter((s) => confirmed[s.id]).length;

  return (
    <div className="page review-page">
      <header className="page-head">
        <div>
          <p className="eyebrow">New enrolment · {result.form_title}</p>
          <h1>Check and confirm</h1>
          <p className="lead">Compare each value with the handwriting above it, correct anything wrong, then confirm each section.</p>
        </div>
        <Steps stage={stage} />
      </header>

      <div className="review-bar card">
        <div className="photos">
          {photoUrls.map((u, i) => u && (
            <button key={i} className="photo-thumb" onClick={() => setViewer(u)} aria-label={`View photo of page ${i + 1}`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={u} alt="" /><span><IconEye size={14} /> Page {i + 1}</span>
            </button>
          ))}
        </div>
        <div className="review-facts">
          <div><strong>{result.needs_review.length}</strong><span>fields to check</span></div>
          <div><strong>{result.processing_seconds}s</strong><span>reading time</span></div>
          <div><strong>{confirmedCount}/{allSections.length}</strong><span>sections confirmed</span></div>
        </div>
        <button className="btn ghost small" onClick={() => { if (confirm("Discard this form and start again?")) reset(); }}>
          <IconArrowLeft size={16} /> Start again
        </button>
      </div>

      {result.warnings.map((w) => <div key={w} className="notice warn"><IconAlert size={18} /><span>{w}</span></div>)}
      {error && <div className="notice error" role="alert"><IconAlert size={18} /><span>{error}</span></div>}

      <div className="review-layout">
        <SectionNav pages={pages} confirmed={confirmed} active={active} onGo={goTo}
                    page={tab} onPage={switchPage} errors={errorsBySection} />

        <div className="review-main">
          <div className="page-banner" id="page-banner">
            <span className="page-banner-num">Page {tab + 1}<small> of {pages.length}</small></span>
            <span className="page-banner-text">
              Sections {page.sections.map((s) => s.id).join(", ")}
              <span className="muted"> · {pageConfirmed(tab)} of {page.sections.length} confirmed</span>
            </span>
            {pages.length > 1 && (
              <button className="btn small" onClick={() => switchPage(tab === 0 ? 1 : 0)}>
                {tab === 0 ? <>Go to page 2 <IconArrowRight size={15} /></> : <><IconArrowLeft size={15} /> Back to page 1</>}
              </button>
            )}
          </div>

          {tab === 1 && result.endorsements && (result.endorsements.missing > 0 || result.endorsements.unsure > 0) && (
            <div className={`notice ${result.endorsements.missing ? "warn" : "info"} endorse-notice`} role="status">
              <IconAlert size={18} />
              <div>
                <strong>{result.endorsements.missing
                  ? `Signatures and stamps: ${result.endorsements.missing} missing on page 2`
                  : "Signatures and stamps: please look at the pictures"}</strong>
                <EndorsementList items={result.endorsements.items} />
              </div>
            </div>
          )}

          <div className="sections" aria-label={`Page ${tab + 1} sections`}>
            {page.sections.map((s) => {
              const n = nextAfter(s.id, { ...confirmed, [s.id]: true });
              return (
                <SectionCard key={s.id} section={s} values={values} original={result.data}
                             problems={problemsByField} errorCount={errorsBySection[s.id] ?? 0}
                             choicesFor={(f) => choicesFor(f, values, fieldMeta, lists)}
                             supplied={page.supplied}
                             open={openId === s.id}
                             onToggle={() => (openId === s.id ? setOpenId(null) : goTo(s.id))}
                             nextLabel={n ? `section ${n.id}` : null}
                             onChange={onFieldChange}
                             confirmed={!!confirmed[s.id]}
                             onConfirm={(v, fromFooter) => onConfirm(s, v, fromFooter)} />
              );
            })}
          </div>

          {tab < pages.length - 1 && (
            <button className="btn next-page" onClick={() => switchPage(tab + 1)}>
              Continue to page {tab + 2} <IconArrowRight size={18} />
            </button>
          )}

          <div id="save-bar" className="save-bar glass-light">
            <div className="save-progress">
              <span className={errorCount ? "save-errors" : "muted"}>
                {errorCount > 0
                  ? `${errorCount} problem${errorCount === 1 ? "" : "s"} to correct before saving`
                  : allConfirmed ? "All sections confirmed" : `${allSections.length - confirmedCount} section${allSections.length - confirmedCount === 1 ? "" : "s"} still to confirm`}
              </span>
              <span className="progress"><span style={{ width: `${(confirmedCount / Math.max(1, allSections.length)) * 100}%` }} /></span>
            </div>
            <div className="save-actions">
              {errorCount > 0 ? (
                <button className="btn danger-soft" onClick={() => { const n = allSections.find((s) => errorsBySection[s.id] > 0); if (n) goTo(n.id); }}>
                  Go to the problem <IconArrowRight size={16} />
                </button>
              ) : !allConfirmed && (
                <button className="btn" onClick={() => { const n = allSections.find((s) => !confirmed[s.id]); if (n) goTo(n.id); }}>
                  Next to confirm <IconArrowRight size={16} />
                </button>
              )}
              <button className="btn ghost" onClick={downloadJson}><IconDownload size={16} /> JSON</button>
              <button className="btn primary big" onClick={save} disabled={!allConfirmed || errorCount > 0 || stage === "saving"}
                      title={errorCount > 0 ? "Correct the problems first" : allConfirmed ? "Save this enrolment" : "Confirm every section first"}>
                {stage === "saving" ? <><span className="spinner" /> Saving…</> : "Save enrolment"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {viewer && <PhotoViewer src={viewer} alt="Original photo of the form" onClose={() => setViewer(null)} />}
    </div>
  );
}
