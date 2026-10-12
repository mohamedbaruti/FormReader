"use client";

import { useState } from "react";
import type { EndorsementItem } from "@/lib/api";
import PhotoViewer from "../PhotoViewer";
import { IconAlert, IconCheck, IconEye } from "../Icons";

/** The signature and stamp boxes of page 2 (items 59, 60, 68, 70, 71): a picture of each box
 *  and what the reader found. The check itself is in the Python reader (app/endorsements.py). */
export default function EndorsementList({ items }: { items: EndorsementItem[] }) {
  const [open, setOpen] = useState<EndorsementItem | null>(null);
  const missing = items.flatMap((it) => it.missing.map((m) => ({ it, m })));
  return (
    <>
      {missing.length > 0 && (
        <ul className="endorse-missing">
          {missing.map(({ it, m }) => (
            <li key={it.id + m}><IconAlert size={14} /> <b>{it.numbers}</b> {it.label_en.split(":")[0]}: <b>{m}</b> missing</li>
          ))}
        </ul>
      )}
      <ul className="endorse-list">
        {items.map((it) => {
          const wantsWriting = it.needs.some((n) => n === "writing" || n === "name_signature" || n === "mark");
          const writingLabel = it.needs.includes("mark") ? "Signature / fingerprint"
            : it.needs.includes("name_signature") ? "Name & signature" : "Signature";
          return (
            <li key={it.id} className={`endorse-item ${it.ok ? (it.notes.length ? "unsure" : "ok") : "missing"}`}>
              {it.image && (
                <button className="endorse-pic" onClick={() => setOpen(it)} aria-label={`Open the picture of item ${it.numbers}`}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={it.image} alt={`Item ${it.numbers} as on the photo`} />
                  <span><IconEye size={12} /></span>
                </button>
              )}
              <div className="endorse-text">
                <strong><span className="endorse-num">{it.numbers}</span> {it.label_en}</strong>
                <span className="endorse-sw">{it.label}</span>
                <span className="endorse-chips">
                  {wantsWriting && <Chip ok={it.writing} label={writingLabel} />}
                  {it.needs.includes("stamp") && <Chip ok={it.stamp} label="Stamp" />}
                </span>
                {it.notes.map((n) => <span key={n} className="endorse-note">{n}</span>)}
              </div>
            </li>
          );
        })}
      </ul>
      {open?.image && <PhotoViewer src={open.image} alt={`Item ${open.numbers}: ${open.label_en}`} onClose={() => setOpen(null)} />}
    </>
  );
}

function Chip({ ok, label }: { ok: boolean | null; label: string }) {
  return (
    <span className={`chip ${ok === true ? "ok" : ok === false ? "bad" : "unsure"}`}>
      {ok === true ? <IconCheck size={12} /> : <IconAlert size={12} />}
      {label}{ok === false ? " missing" : ok === null ? ": look at the picture" : ""}
    </span>
  );
}
