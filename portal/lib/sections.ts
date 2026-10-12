import type { CSSProperties } from "react";
import type { Section } from "./api";

// One colour per form section, so a section is recognised at a glance in the
// navigator and on its own header. Dark enough for white letters (contrast >= 4.5:1).
const SECTION_COLORS: Record<string, string> = {
  K: "#7a5c12", A: "#1f6fd1", B: "#6d45c2", C: "#0b7f73", D: "#b9531f",
  E: "#3446a6", F: "#b2386e", G: "#4f6b12", H: "#4d5b70",
};

export function sectionColor(id: string) {
  return SECTION_COLORS[id] || "#1f6fd1";
}

export function sectionStyle(id: string): CSSProperties {
  return { ["--sec" as string]: sectionColor(id) } as CSSProperties;
}

/** English name of a section, without notes in brackets: "Personal records". */
export function sectionName(s: Section) {
  return (s.subtitle || s.title).replace(/\s*\(.*?\)\s*/g, "").trim();
}
