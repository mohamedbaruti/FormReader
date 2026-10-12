"use client";

import { useEffect, useRef } from "react";
import type { FormPage } from "@/lib/api";
import { sectionName, sectionStyle } from "@/lib/sections";
import { IconCheck, IconList } from "../Icons";

/** The form's navigation: Page 1 and Page 2, each with its sections.
 *  Clicking a page shows it; clicking a section jumps straight to it (switching
 *  page if needed). Shows the section you are in, problems to correct, fields to
 *  check and confirmed sections. */
export default function SectionNav({ pages, confirmed, active, onGo, page, onPage, errors }: {
  pages: FormPage[];
  confirmed: Record<string, boolean>;
  active: string | null;
  onGo: (sectionId: string) => void;
  page: number;                         // page shown
  onPage: (p: number) => void;
  errors: Record<string, number>;       // section -> rule problems to correct
}) {
  const all = pages.flatMap((p) => p.sections);
  const done = all.filter((s) => confirmed[s.id]).length;
  const ref = useRef<HTMLElement>(null);

  // On narrow screens the navigator is a bar that scrolls sideways: keep the current section visible.
  useEffect(() => {
    const nav = ref.current;
    const el = nav?.querySelector<HTMLElement>(".snav-item.active");
    if (!nav || !el || nav.scrollWidth <= nav.clientWidth) return;
    const left = el.offsetLeft - nav.clientWidth / 2 + el.offsetWidth / 2;
    nav.scrollTo({ left: Math.max(0, left), behavior: "smooth" });
  }, [active]);

  return (
    <nav ref={ref} className="section-nav card" aria-label="Form pages and sections">
      <div className="snav-head">
        <span className="snav-heading"><IconList size={17} /> Form</span>
        <span className="snav-progress-text">{done} of {all.length} confirmed</span>
      </div>
      <span className="progress snav-progress"><span style={{ width: `${(done / Math.max(1, all.length)) * 100}%` }} /></span>

      <div className="snav-groups">
        {pages.map((p) => {
          const pDone = p.sections.filter((s) => confirmed[s.id]).length;
          const pErr = p.sections.reduce((n, s) => n + (errors[s.id] || 0), 0);
          const shown = page === p.index;
          return (
            <div key={p.index} className={`snav-group${shown ? " shown" : ""}`}>
              <button className="snav-page" onClick={() => onPage(p.index)} aria-current={shown ? "page" : undefined}>
                <span className="snav-page-name">Page {p.index + 1}</span>
                <span className="snav-page-meta">
                  {pErr > 0 ? <span className="snav-err">{pErr}</span> : null}
                  <span className={`snav-page-count${pDone === p.sections.length ? " done" : ""}`}>{pDone}/{p.sections.length}</span>
                </span>
              </button>
              <ul>
                {p.sections.map((s) => {
                  const toCheck = s.fields.filter((f) => f.flagged).length;
                  const isDone = !!confirmed[s.id];
                  const isActive = active === s.id && shown;
                  const err = errors[s.id] || 0;
                  return (
                    <li key={s.id}>
                      <button
                        className={`snav-item${isActive ? " active" : ""}${isDone ? " done" : ""}${err ? " has-err" : ""}`}
                        style={sectionStyle(s.id)}
                        aria-current={isActive ? "location" : undefined}
                        onClick={() => onGo(s.id)}
                        title={`Section ${s.id}: ${sectionName(s)}`}
                      >
                        <span className="snav-letter">{s.id}</span>
                        <span className="snav-title">{sectionName(s)}</span>
                        <span className="snav-status">
                          {err > 0 ? <span className="snav-err" aria-label={`${err} problems to correct`}>!</span>
                            : isDone ? <span className="snav-done" aria-label="confirmed"><IconCheck size={13} /></span>
                            : toCheck > 0 ? <span className="snav-count" aria-label={`${toCheck} fields to check`}>{toCheck}</span>
                            : null}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
      <p className="snav-legend">
        <span><span className="snav-err">!</span> to correct</span>
        <span><span className="snav-count">3</span> to check</span>
        <span><span className="snav-done"><IconCheck size={11} /></span> confirmed</span>
      </p>
    </nav>
  );
}
