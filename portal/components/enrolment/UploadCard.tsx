"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import type { InspectResult } from "@/lib/api";
import { usePhone } from "@/lib/device";
import { IconCamera, IconUpload, IconX, IconCheckCircle, IconAlert, IconInfo } from "../Icons";

const OK_TYPES = ["image/jpeg", "image/png"];

/** What the quick check of a photo found (null = no photo yet). */
export type CheckState =
  | { state: "checking" }
  | { state: "done"; r: InspectResult }
  | { state: "error"; message: string }
  | null;

/** Something about a photo the user should look at. Nothing is ever rejected:
 *  the user fixes it with one of the actions, or keeps the photo as it is. */
export interface Issue {
  code: string;
  tone: "warn" | "error" | "info";
  title: string;
  text: string;
  actions: { label: string; onClick?: () => void; replace?: boolean; primary?: boolean; icon?: ReactNode }[];
  details?: ReactNode;          // more to show under the text (e.g. the signature boxes)
  acknowledged?: boolean;       // the user chose "keep it"
  onUndo?: () => void;
}

/** "Form 1A, edition 1.4 (green, with voter registration)" -> "edition 1.4 (green)" */
export function shortTitle(t: string) {
  const m = t.match(/edition\s*([\d.]+)\s*(?:\(([^,)]*))?/i);
  return m ? `edition ${m[1]}${m[2] && !/pages?/.test(m[2]) ? ` (${m[2]})` : ""}` : t;
}

export default function UploadCard({ page, title, sections, file, check, issues, onFile, notNeeded }: {
  page: number;
  title: string;
  sections: string[];
  file: File | null;
  check: CheckState;
  issues: Issue[];
  onFile: (f: File | null) => void;
  notNeeded?: string;          // shown instead of the drop area when this page is not used
}) {
  const input = useRef<HTMLInputElement>(null);
  const camera = useRef<HTMLInputElement>(null);     // opens the camera directly (phone)
  const phone = usePhone();
  const [over, setOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    if (!file) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const take = (f: File | undefined | null) => {
    if (!f) return;
    if (!OK_TYPES.includes(f.type) && !/\.(jpe?g|png)$/i.test(f.name)) {
      setError("Please choose a JPG or PNG photo."); return;
    }
    if (f.size > 25 * 1024 * 1024) { setError("That photo is larger than 25 MB."); return; }
    setError(null);
    onFile(f);
  };

  const open = issues.filter((i) => !i.acknowledged && i.tone !== "info");
  const r = check?.state === "done" ? check.r : null;
  const status: "empty" | "checking" | "attention" | "ok" =
    !file ? "empty" : check?.state === "checking" ? "checking" : open.length ? "attention" : "ok";
  const detectedOther = r?.recognised && r.page !== page;

  return (
    <div className={`upload-card card status-${status}`}>
      <div className="upload-head">
        <span className="page-pill">Page {page}</span>
        <div>
          <h3>{title}<span className="req" aria-hidden="true"> *</span></h3>
          <p className="muted">{sections.join(" · ")}</p>
        </div>
        {status === "ok" && <IconCheckCircle size={22} className="ok-mark" />}
        {status === "attention" && <IconAlert size={22} className="warn-mark" />}
      </div>

      {notNeeded && !file ? (
        <div className="not-needed"><IconInfo size={20} /><p>{notNeeded}</p></div>
      ) : (
        <div
          className={`dropzone${over ? " over" : ""}${preview ? " filled" : ""}`}
          role="button" tabIndex={0}
          aria-label={`Choose photo of page ${page}`}
          onClick={() => input.current?.click()}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); take(e.dataTransfer.files?.[0]); }}
        >
          {preview ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={preview} alt={`Photo chosen for page ${page}`} className="preview" />
              {check?.state === "checking" && <span className="scan-line" aria-hidden="true" />}
              {r?.recognised && (
                <span className={`detected-badge${detectedOther ? " other" : ""}`}>
                  {detectedOther ? `Looks like page ${r.page}` : `Page ${r.page} ✓`}
                </span>
              )}
            </>
          ) : (
            <div className="drop-empty">
              <span className="drop-icon"><IconCamera size={30} /></span>
              <strong>{phone ? `Add the photo of page ${page}` : `Drop the photo of page ${page} here`}</strong>
              <span className="muted">{phone ? "Take a photo, or choose one saved on the phone" : "or click to choose · JPG or PNG"}</span>
            </div>
          )}
        </div>
      )}
      <input ref={input} type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" hidden
             onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }} />
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden
             onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }} />
      {phone && !(notNeeded && !file) && (
        <div className="source-buttons">
          <button type="button" className="btn primary" onClick={() => camera.current?.click()}>
            <IconCamera size={18} /> {file ? "Take again" : "Take photo"}
          </button>
          <button type="button" className="btn" onClick={() => input.current?.click()}>
            <IconUpload size={18} /> {file ? "Choose another" : "Choose from phone"}
          </button>
        </div>
      )}

      {error && <p className="field-error" role="alert">{error}</p>}

      {file && (
        <div className="check-area" aria-live="polite">
          {check?.state === "checking" && (
            <p className="check-line-status"><span className="spinner" /> Checking the photo…</p>
          )}
          {status === "ok" && r?.recognised && (
            <p className="check-line-status ok">
              <IconCheckCircle size={17} />
              <span>Page {r.page} of Form 1A, {r.compatible_forms.length > 1
                ? shortTitle(r.form_title).replace(/\s*\(.*\)$/, "") : shortTitle(r.form_title)}
                {r.boxes_written ? ` · writing found in ${r.boxes_written} boxes` : ""}</span>
            </p>
          )}
          {issues.map((i) => i.acknowledged ? (
            <p key={i.code} className="check-line-status kept">
              <IconInfo size={16} /><span>Kept as it is: {i.title.replace(/[:?.].*$/, "").toLowerCase()}.</span>
              {i.onUndo && <button className="link-btn" onClick={i.onUndo}>Undo</button>}
            </p>
          ) : (
            <div key={i.code} className={`issue ${i.tone}`} role={i.tone === "info" ? undefined : "alert"}>
              <div className="issue-text">
                <strong>{i.title}</strong>
                <span>{i.text}</span>
              </div>
              {i.details}
              <div className="issue-actions">
                {i.actions.map((a) => (
                  <button key={a.label} className={`btn small${a.primary ? " primary" : ""}`} onClick={a.replace ? () => input.current?.click() : a.onClick}>
                    {a.icon}{a.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
          <div className="file-row">
            <span className="file-name" title={file.name}>{file.name}</span>
            <span className="muted">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
            <button className="btn ghost small" onClick={() => input.current?.click()}><IconUpload size={15} /> Replace</button>
            <button className="btn ghost small icon-only" onClick={() => onFile(null)} aria-label={`Remove photo of page ${page}`}>
              <IconX size={15} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
