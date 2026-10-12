// Client for the Python Form Reader API.
// By default requests go to /pyapi/..., which next.config.mjs forwards to the
// Python app. Set NEXT_PUBLIC_API_URL to call the API directly instead.

import { staffHeaders } from "./staff";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "/pyapi").replace(/\/$/, "");

export type FieldType =
  | "alpha" | "digit" | "alnum" | "date_d" | "date_m" | "date_y" | "check" | "flag" | "image";

export type Value = string | boolean | null;

export interface Field {
  name: string;
  label: string;          // Swahili label as printed on the form, with item number
  label_en: string;       // English meaning
  type: FieldType;
  value: Value;
  flagged: boolean;       // the reader is unsure: please check
  page: number;
  image: string;          // data URL: the handwriting exactly as on the form
  options?: string[];     // for tick-box choices (e.g. sex: male / female)
  attached?: { name: string; value: Value; image: string };   // section F "attached" tick
  lookup?: string;        // value must come from this official list (e.g. "district"): dropdown
  parent_field?: string | null;   // field in the same section holding the parent (district -> region)
  postcode_parts?: string[];      // postcode filled in from these fields (region, district, ward): not typed
  read_as?: string | null;    // what the handwriting was read as, before matching to the list
  match?: "sure" | "guess" | "none" | "empty";   // how the list name was chosen
}

export interface Section {
  id: string;
  title: string;
  subtitle: string;
  page: number;
  fields: Field[];
}

export interface FormPage {
  index: number;
  supplied: boolean;
  sections: Section[];
}

export interface ExtractResult {
  job_id: string;
  form: string;
  form_title: string;
  page_count: number;
  pages: FormPage[];
  data: Record<string, Value>;
  needs_review: string[];
  warnings: string[];
  issues: Issue[];            // logic checks (validation_rules.json in the reader)
  lookups?: Record<string, LookupEntry[]>;   // official lists: { region: [...], district: [...], ward: [...] }
  endorsements?: Endorsements | null;        // page 2: signatures and stamps found
  processing_seconds: number;
  filename: string;
}

/** Quick look at one photo before reading (POST /api/inspect). */
export interface InspectResult {
  recognised: boolean;        // looks like a page of a known Form 1A edition
  form: string;
  form_title: string;
  compatible_forms: string[]; // editions this printed page belongs to (page 2 is shared)
  page_count: number;         // pages in that edition
  page: number;               // which page this photo is (1-based)
  match: number;              // strength of the match (feature points that agree)
  file_pages: number;
  blank: boolean | null;      // nothing written on it (null if it could not be checked)
  boxes_written: number | null;
  boxes_total: number | null;
  ticks: number | null;
  processing_seconds: number;
  endorsements?: Endorsements | null;   // page 2: signatures and stamps (items 59, 60, 68, 70, 71)
}

/** One signature / stamp box on page 2 and what the reader found in it. */
export interface EndorsementItem {
  id: string;                 // applicant, ward_officer, immigration, weo_employer, nida_officer
  numbers: string;            // item number printed on this edition, e.g. "68" (or "69")
  label: string; label_en: string;
  needs: ("mark" | "writing" | "name_signature" | "stamp")[];
  stamp: boolean;
  writing: boolean | null;    // null = cannot tell (writing on top of a stamp of the same colour)
  writing_pieces: number;
  missing: string[];          // e.g. ["stamp"], ["name and signature"]
  notes: string[];
  ok: boolean;
  image?: string;             // picture of the box and a little around it
}
export interface Endorsements { ok: boolean; missing: number; unsure: number; items: EndorsementItem[] }

/** One name in an official list; parent_id links it to its region / district. */
export interface LookupEntry { id: number | null; name: string; parent_id: number | null; postcode?: string | null }

/** A logic check that failed (e.g. phone number not 10 digits). */
export interface Issue {
  rule: string;
  fields: string[];           // every field the problem concerns
  severity: "error" | "warning";   // error = must be corrected before saving
  message: string;
}

export interface SaveResult {
  id: string;
  data: Record<string, Value>;
  saved_to: string;
  training_samples_added: number;
  characters_corrected: number;
  fields_corrected: number;
}

export interface EnrolmentSummary {
  id: string;
  name: string;
  sex: string | null;
  date_of_birth: string | null;
  region: string | null;
  phone_number: string | null;
  form: string | null;
  saved_at: string | null;
  fields_corrected: number | null;
}

export interface Stats {
  total: number;
  today: number;
  this_week: number;
  previous_week: number;
  per_day: { date: string; count: number }[];
  sex: Record<string, number>;
  marital_status: Record<string, number>;
  employment_status: Record<string, number>;
  regions: Record<string, number>;
  age_bands: Record<string, number>;
  editions: Record<string, number>;
  accuracy: {
    reviewed_records: number;
    characters_total: number;
    characters_corrected: number;
    auto_read_rate: number | null;
    fields_corrected_per_form: number | null;
    fields_flagged_per_form: number | null;
  };
  training_samples: number;
  recent: EnrolmentSummary[];
}

export interface Health {
  status: string;
  version: string;
  forms: { id: string; title: string; pages: number; fields: number }[];
  models: Record<string, string>;
  database?: { path: string; records: number };   // SQLite database of saved enrolments (on the computer)
}

// ---------------------------------------------------------------- Training page
export type TrainingStatus = "queued" | "reading" | "ready" | "confirmed" | "skipped" | "problem" | "failed";

/** Who has a training form open for checking (only one person at a time). */
export interface FormLock {
  name: string; since: string; idle_minutes: number;
  mine: boolean;                       // this browser tab has it
  can_take_over: boolean;              // idle long enough that someone else may take it
}

export interface TrainingFormRow {
  id: string; seq: number; filename: string; status: TrainingStatus; test: boolean;
  problem: string | null; uploaded_at: string; read_at?: string; confirmed_at?: string;
  fields: number; unsure: number; fields_used?: number; form_title?: string;
  lock?: FormLock | null;
}

export interface TrainingField {
  name: string; label: string; label_en: string; section: string;
  type: "alpha" | "digit" | "alnum" | "date";
  read: string;                       // what the reader read
  boxes: [string, string, number, string][];   // [file, char read, confidence, kind] per written box
  unsure: boolean;
  image?: string;                     // picture of the handwriting
  typed?: string; used?: boolean; reason?: string | null;
}

export interface TrainingForm extends Omit<TrainingFormRow, "fields"> { fields: TrainingField[] }

export interface CharStat {
  char: string; samples: number; seen: number; right: number; accuracy: number | null;
  level: "needs_more" | "moderate" | "enough";
  reading: "often_misread" | "sometimes_misread" | "good" | null;
  advice: string; confused_with: { char: string; count: number }[];
}

export interface TrainingRun {
  trained_at: string; samples: number; test_characters: number;
  old_accuracy: number | null; new_accuracy: number | null; better: boolean | null;
  installed: boolean; seconds: number;
}

export interface TrainingStats {
  forms: Record<TrainingStatus | "total" | "test", number>;
  characters: { samples: number; checked: number; read_right: number; accuracy: number | null;
                test_characters: number; new_since_training: number };
  fields: { checked: number; used: number; not_used_reasons: Record<string, number> };
  per_character: CharStat[];
  confusions: { char: string; read_as: string; count: number }[];
  advice: { level: "action" | "warn" | "info"; text: string }[];
  runs: TrainingRun[];
  candidate: (TrainingRun & { files: string[]; installed_at?: string; backup?: string;
              per_character?: Record<string, { seen: number; old: number; new: number }> }) | null;
  job: { state: "idle" | "running" | "done" | "failed"; step?: number; steps?: number; step_name?: string;
         started_at?: string; finished_at?: string; error?: string; log?: string[]; samples?: number };
  models: Record<string, string>;
  settings: Record<string, number>;
  missing_packages: string[];        // training needs: pip install -r requirements-train.txt
}

/** An error answer from the API; body holds the JSON it sent (e.g. issues). */
export class ApiError extends Error {
  body: unknown;
  constructor(message: string, body: unknown) { super(message); this.body = body; }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      cache: "no-store", ...init, headers: { ...staffHeaders(), ...(init?.headers as Record<string, string> | undefined) },
    });
  } catch {
    throw new Error("Cannot reach the Form Reader API. Is the Python app running (python run.py)?");
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  if (!res.ok) {
    const msg = (body as { error?: string } | null)?.error;
    throw new ApiError(msg || `The API answered ${res.status} ${res.statusText}`, body);
  }
  return body as T;
}

export const api = {
  health: () => call<Health>("/health"),
  stats: (days = 30) => call<Stats>(`/stats?days=${days}`),
  training: () => call<TrainingStats>("/training"),
  trainingForms: () => call<{ items: TrainingFormRow[] }>("/training/forms"),
  trainingForm: (id: string) => call<TrainingForm>(`/training/forms/${id}`),
  trainingPhotoUrl: (id: string) => `${API_BASE}/training/forms/${id}/photo`,
  trainingUpload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("file", f));
    return call<{ added: number; ids: string[]; refused: string[] }>("/training/forms", { method: "POST", body: fd });
  },
  trainingConfirm: (id: string, values: Record<string, string>) =>
    call<TrainingForm>(`/training/forms/${id}/confirm`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ values }),
    }),
  /** Open a form for checking / keep it open (every 30 s). Fails with 423 (ApiError body.lock) when someone else has it. */
  trainingLock: (id: string, idleSeconds = 0, takeOver = false) =>
    call<FormLock>(`/training/forms/${id}/lock`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idle_seconds: Math.round(idleSeconds), take_over: takeOver }),
    }),
  /** Free a form (also works while the page is closing). */
  trainingUnlock: (id: string) => {
    fetch(`${API_BASE}/training/forms/${id}/unlock`, { method: "POST", keepalive: true, headers: staffHeaders() }).catch(() => {});
  },
  /** Open the next form waiting to be checked that nobody else has open ({id: null} when none). */
  trainingNext: (after?: string) =>
    call<{ id: string | null }>("/training/next", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ after: after ?? null }),
    }),
  trainingSkip: (id: string) => call<TrainingForm>(`/training/forms/${id}/skip`, { method: "POST" }),
  trainingRetry: (id: string) => call<TrainingForm>(`/training/forms/${id}/retry`, { method: "POST" }),
  trainingSetTest: (id: string, test: boolean) =>
    call<TrainingForm>(`/training/forms/${id}/test`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ test }),
    }),
  trainingDelete: (id: string) => call<{ deleted: string }>(`/training/forms/${id}`, { method: "DELETE" }),
  trainingStart: () => call<TrainingStats["job"]>("/training/train", { method: "POST" }),
  trainingInstall: () => call<TrainingStats["candidate"]>("/training/install", { method: "POST" }),
  trainingFileUrl: (name: string) => `${API_BASE}/training/candidate/${name}`,
  enrolments: (q = "", limit = 100) =>
    call<{ total: number; items: EnrolmentSummary[] }>(`/enrolments?q=${encodeURIComponent(q)}&limit=${limit}`),
  enrolment: (id: string) =>
    call<{ id: string; form: string; form_title?: string; saved_at: string; data: Record<string, Value>;
           sections_confirmed?: string[]; review?: Record<string, number> }>(`/enrolments/${id}`),

  /** Check one photo: which page of which edition, and is anything written on it. */
  inspect: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<InspectResult>("/inspect", { method: "POST", body: fd });
  },

  /** Run the logic checks on the current values. */
  validate: (data: Record<string, Value>) =>
    call<{ issues: Issue[]; errors: number; warnings: number }>("/validate", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data }),
    }),

  /** Send the photos (page 1 first) and get every field back, grouped by page and section. */
  extract: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("file", f));
    return call<ExtractResult>("/extract?review=1", { method: "POST", body: fd });
  },

  /** Save the checked record; the API also keeps the handwriting for retraining. */
  save: (jobId: string, data: Record<string, Value>, sectionsConfirmed: string[]) =>
    call<SaveResult>(`/jobs/${jobId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data, sections_confirmed: sectionsConfirmed }),
    }),
};

// ---------------------------------------------------------------- display helpers
export function titleCase(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function fieldLabel(name: string): string {
  return titleCase(name);
}
