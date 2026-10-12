"use client";

import type { Field, Issue, Section, Value } from "@/lib/api";
import { sectionName, sectionStyle } from "@/lib/sections";
import FieldRow from "./FieldRow";
import { IconAlert, IconArrowRight, IconCheck } from "../Icons";

export default function SectionCard({
  section, values, original, onChange, confirmed, onConfirm, supplied, open, onToggle, nextLabel, problems, errorCount,
  choicesFor,
}: {
  section: Section;
  values: Record<string, Value>;
  original: Record<string, Value>;
  onChange: (name: string, v: Value) => void;
  confirmed: boolean;
  /** fromFooter: confirmed with the button at the end of the section (then go on to the next one) */
  onConfirm: (v: boolean, fromFooter: boolean) => void;
  supplied: boolean;
  open: boolean;
  onToggle: () => void;
  nextLabel: string | null;      // e.g. "section E" (where the footer button goes next)
  problems: Record<string, Issue[]>;   // field -> logic checks that failed
  errorCount: number;                  // problems in this section that block confirming
  choicesFor?: (f: Field) => { options: string[]; within: string | null } | undefined;  // dropdown fields
}) {
  const toCheck = section.fields.filter((f) => f.flagged).length;
  const edited = section.fields.filter((f) => JSON.stringify(values[f.name] ?? null) !== JSON.stringify(original[f.name] ?? null)).length;
  const bodyId = `sec-${section.id}-body`;
  const name = sectionName(section);

  return (
    <section id={`sec-${section.id}`} data-section={section.id} style={sectionStyle(section.id)}
             className={`section card${confirmed ? " confirmed" : ""}${open ? "" : " collapsed"}`}
             aria-labelledby={`sec-${section.id}-title`}>
      {/* the whole bar opens/closes the section, except the confirm tick */}
      <header className="section-head"
              onClick={(e) => { if (!(e.target as HTMLElement).closest(".confirm-toggle")) onToggle(); }}>
        <button className="section-toggle" aria-expanded={open} aria-controls={bodyId}>
          <span className="section-letter">
            {section.id}
            {confirmed && <span className="letter-check"><IconCheck size={11} /></span>}
          </span>
          <span className="section-names">
            <span className="section-kicker">Section {section.id} · Page {section.page + 1} · {section.fields.length} fields</span>
            <span id={`sec-${section.id}-title`} className="section-title">{name}</span>
          </span>
          <span className={`chev${open ? " open" : ""}`} aria-hidden="true">▾</span>
        </button>
        <div className="section-meta">
          {errorCount > 0 && <span className="chip bad"><IconAlert size={13} /> {errorCount} to correct</span>}
          {toCheck > 0 && <span className="chip warn">{toCheck} to check</span>}
          {edited > 0 && <span className="chip edited">{edited} edited</span>}
          <label className={`confirm-toggle${confirmed ? " on" : ""}${errorCount ? " blocked" : ""}`}
                 title={errorCount ? "Correct the problems in this section first" : undefined}>
            <input type="checkbox" checked={confirmed} disabled={errorCount > 0 && !confirmed}
                   onChange={(e) => onConfirm(e.target.checked, false)} />
            <span className="box" aria-hidden="true">{confirmed && <IconCheck size={14} />}</span>
            {confirmed ? "Confirmed" : "Confirm section"}
          </label>
        </div>
      </header>

      {open && (
        <div id={bodyId} className="section-body">
          {!supplied && (
            <p className="notice info">This page could not be read from the photo, so its fields are empty. Type them in from the paper form.</p>
          )}
          <div className="fields">
            {section.fields.map((f) => (
              <FieldRow
                key={f.name}
                field={f}
                value={values[f.name] ?? null}
                original={original[f.name] ?? null}
                onChange={(v) => onChange(f.name, v)}
                attachedValue={f.attached ? values[f.attached.name] ?? null : undefined}
                onAttached={f.attached ? (v) => onChange(f.attached!.name, v) : undefined}
                problems={problems[f.name] ?? []}
                choices={f.lookup ? choicesFor?.(f) : undefined}
              />
            ))}
          </div>
          <div className="section-foot">
            {errorCount > 0 ? (
              <span className="foot-blocked"><IconAlert size={16} />
                Correct the {errorCount === 1 ? "problem" : `${errorCount} problems`} marked in red before confirming section {section.id}.
              </span>
            ) : confirmed ? (
              <>
                <span className="foot-done"><IconCheck size={16} /> Section {section.id} confirmed</span>
                {nextLabel && (
                  <button className="btn" onClick={() => onConfirm(true, true)}>
                    Go to {nextLabel} <IconArrowRight size={16} />
                  </button>
                )}
              </>
            ) : (
              <button className="btn primary confirm-next" onClick={() => onConfirm(true, true)}>
                <IconCheck size={17} /> All fields in section {section.id} are correct
                {nextLabel ? <> · go to {nextLabel} <IconArrowRight size={16} /></> : null}
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
