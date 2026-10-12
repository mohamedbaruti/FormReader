"use client";

import { useState } from "react";
import type { Field, Issue, Value } from "@/lib/api";
import { titleCase } from "@/lib/api";

const DATE_RE = /^\d{2}\/\d{2}\/\d{4}$/;

function isDate(f: Field) {
  return f.type.startsWith("date");
}

/** One field: the handwriting exactly as on the form, and below it the editable value. */
export default function FieldRow({ field, value, original, onChange, attachedValue, onAttached, problems = [], choices }: {
  field: Field;
  value: Value;
  original: Value;
  onChange: (v: Value) => void;
  attachedValue?: Value;
  onAttached?: (v: boolean) => void;
  problems?: Issue[];                 // logic checks that failed on this field
  choices?: { options: string[]; within: string | null };   // official list: shown as a dropdown
}) {
  const id = `f-${field.name}`;
  // item number as printed on the form ("32. Namba ya nyumba" -> "32"), to find it on the paper
  const num = field.label.match(/^(\d+)\./)?.[1] ?? null;
  // Fields with a long row of handwriting (national IDs, long names) take the full width
  const [wide, setWide] = useState(false);
  const edited = JSON.stringify(value ?? null) !== JSON.stringify(original ?? null);
  const badDate = isDate(field) && typeof value === "string" && value !== "" && !DATE_RE.test(value);
  const errors = problems.filter((p) => p.severity === "error");
  const warnings = problems.filter((p) => p.severity === "warning");

  let editor: React.ReactNode = null;
  if (field.type === "check") {
    const opts = field.options || [];
    editor = (
      <div className="choice-group" role="radiogroup" aria-labelledby={`${id}-label`}>
        {opts.map((o) => (
          <button key={o} type="button" role="radio" aria-checked={value === o}
                  className={`choice${value === o ? " on" : ""}`} onClick={() => onChange(o)}>
            {titleCase(o)}
          </button>
        ))}
        <button type="button" role="radio" aria-checked={value === null || value === ""}
                className={`choice none${value === null || value === "" ? " on" : ""}`} onClick={() => onChange(null)}>
          None ticked
        </button>
      </div>
    );
  } else if (field.type === "flag") {
    editor = (
      <label className="check-line">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> Ticked
      </label>
    );
  } else if (field.postcode_parts?.length) {
    // Postcode: filled in from the region, district and ward of this section; not typed
    editor = (
      <div className="lookup-wrap">
        <input id={id} className="text-input readonly" value={typeof value === "string" ? value : ""} readOnly
               placeholder="Choose region, district and ward" aria-describedby={`${id}-readas`} />
        <span id={`${id}-readas`} className="read-as">
          Filled in from region + district + ward{field.read_as ? <> · written on the form: <b>{field.read_as}</b></> : null}
        </span>
      </div>
    );
  } else if (choices && !choices.options.length && choices.within) {
    // e.g. regions when the country is not Tanzania: there is no list to choose from
    editor = (
      <div className="lookup-wrap">
        <select id={id} className="text-input select" disabled value=""><option value="">No {field.lookup} list for {choices.within}</option></select>
        {field.read_as && <span className="read-as">Read as <b>{field.read_as}</b></span>}
      </div>
    );
  } else if (choices && choices.options.length) {
    // Name from the official list (e.g. districts): the reader pre-selects the closest one
    const v = typeof value === "string" ? value : "";
    editor = (
      <div className="lookup-wrap">
        <select id={id} className={`text-input select${errors.length ? " error" : ""}`} value={v}
                aria-invalid={errors.length > 0 || undefined}
                aria-describedby={`${id}-readas${problems.length ? ` ${id}-problems` : ""}`}
                onChange={(e) => onChange(e.target.value || null)}>
          <option value="">— Choose {field.lookup}{choices.within ? ` in ${choices.within}` : ""} —</option>
          {v && !choices.options.includes(v) && <option value={v}>{v} (not in the list)</option>}
          {choices.options.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <span id={`${id}-readas`} className={`read-as ${field.match ?? ""}`}>
          {!field.read_as ? "Nothing written on the form"
            : field.match === "sure" && v === original ? <>Read as <b>{field.read_as}</b> · matched to the list</>
            : field.match === "guess" && v === original ? <>Read as <b>{field.read_as}</b> · closest name chosen, please check</>
            : field.match === "none" && !v ? <>Read as <b>{field.read_as}</b> · no close name in the list, please choose</>
            : <>Read as <b>{field.read_as}</b></>}
        </span>
      </div>
    );
  } else if (field.type !== "image") {
    editor = (
      <input
        id={id}
        className={`text-input${isDate(field) ? " date" : ""}${badDate || warnings.length ? " invalid" : ""}${errors.length ? " error" : ""}`}
        aria-invalid={errors.length > 0 || undefined}
        aria-describedby={problems.length ? `${id}-problems` : undefined}
        value={typeof value === "string" ? value : ""}
        placeholder={isDate(field) ? "DD/MM/YYYY (empty)" : "(empty)"}
        inputMode={field.type === "digit" || isDate(field) ? "numeric" : "text"}
        autoComplete="off" spellCheck={false}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(isDate(field) ? raw : raw.toUpperCase());
        }}
        onBlur={(e) => {
          const v = e.target.value.replace(/\s+/g, " ").trim();
          onChange(v === "" ? null : isDate(field) ? v : v.toUpperCase());
        }}
      />
    );
  }

  return (
    <div className={`field${errors.length ? " has-error" : ""}${field.flagged ? " flagged" : ""}${field.type === "image" ? " picture" : ""}${wide ? " wide" : ""}`}>
      <div className="field-top">
        <label id={`${id}-label`} htmlFor={field.type === "check" || field.type === "image" ? undefined : id}
               className="field-label" title={field.label}>
          {num && <span className="field-num">{num}</span>}{field.label_en}
        </label>
        <span className="chips">
          {errors.length > 0 && <span className="chip bad">Correct this</span>}
          {field.flagged && <span className="chip warn">Please check</span>}
          {edited && <span className="chip edited">Edited</span>}
          {badDate && <span className="chip warn">Use DD/MM/YYYY</span>}
        </span>
      </div>

      <div className="crop-row">
        <div className="crop" title="As written on the form">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={field.image} alt={`${field.label_en} as written on the form`}
               onLoad={(e) => setWide(e.currentTarget.naturalWidth > 560)} />
        </div>
        {field.attached && (
          <div className="crop small" title="Attached tick box">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={field.attached.image} alt={`${field.label_en}: attached tick box`} />
          </div>
        )}
      </div>

      {field.type === "image" ? (
        <p className="muted small-note">Picture only, for reference. Not read as text.</p>
      ) : (
        <div className="editor-row">
          {editor}
          {field.attached && onAttached && (
            <label className="check-line attached">
              <input type="checkbox" checked={!!attachedValue} onChange={(e) => onAttached(e.target.checked)} />
              Attached
            </label>
          )}
        </div>
      )}
      {problems.length > 0 && (
        <ul className="field-problems" id={`${id}-problems`}>
          {problems.map((p) => (
            <li key={p.rule} className={p.severity}>{p.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
