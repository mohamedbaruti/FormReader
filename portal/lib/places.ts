// Linked dropdowns for place names (region -> district -> ward -> village).
// The lists come from the Python reader (which loads them from your lookup
// service); each entry knows its parent: a district's parent_id is its region's
// id (regionId), a ward's parent_id its district's id (districtId).
// Each field knows its parent field in the same section (birth_district ->
// birth_region), so every section works on its own.

import type { Field, LookupEntry, Value } from "./api";

export type Lists = Record<string, LookupEntry[]>;
type Vals = Record<string, Value>;

const str = (v: Value | undefined) => (typeof v === "string" && v ? v : null);

/** Ids allowed by what is chosen in `name`: the chosen entry (narrowed by its own parent); when
 *  `name` is empty, every entry under the parent chosen above it (district empty, region TANGA:
 *  all of TANGA's districts). null = no restriction. */
export function chosenIds(name: string, vals: Vals, meta: Record<string, Field>, lists: Lists): Set<number | null> | null {
  const f = meta[name];
  const v = str(vals[name]);
  if (!f?.lookup || !lists[f.lookup]) return null;
  const pIds = f.parent_field ? chosenIds(f.parent_field, vals, meta, lists) : null;
  if (!v) return pIds ? new Set(lists[f.lookup].filter((e) => pIds.has(e.parent_id)).map((e) => e.id)) : null;
  let es = lists[f.lookup].filter((e) => e.name === v);
  if (pIds) {
    const within = es.filter((e) => pIds.has(e.parent_id));
    if (within.length) es = within;
  }
  return es.length ? new Set(es.map((e) => e.id)) : null;
}

/** Names offered in a field's dropdown: only those under the parent chosen in the same section. */
export function choicesFor(f: Field, vals: Vals, meta: Record<string, Field>, lists: Lists):
  { options: string[]; within: string | null } | undefined {
  const list = f.lookup ? lists[f.lookup] : undefined;
  if (!list || !list.length) return undefined;
  const pIds = f.parent_field ? chosenIds(f.parent_field, vals, meta, lists) : null;
  const es = pIds ? list.filter((e) => pIds.has(e.parent_id)) : list;
  return {
    options: Array.from(new Set(es.map((e) => e.name))).sort(),
    within: pIds ? nearestChosen(f, vals, meta) : null,
  };
}

/** The closest field above `f` in its section that has a value (its name, e.g. "TANGA"). */
function nearestChosen(f: Field, vals: Vals, meta: Record<string, Field>): string | null {
  let p = f.parent_field;
  while (p) {
    if (str(vals[p])) return str(vals[p]);
    p = meta[p]?.parent_field ?? null;
  }
  return null;
}

/** Set a place field and keep its section consistent:
 *  - a parent left empty is filled from the chosen name (choosing district TEMEKE fills region DAR ES SALAAM),
 *  - a child that is no longer under the new choice is emptied (changing the region empties district and ward). */
export function setPlace(name: string, v: Value, vals: Vals, meta: Record<string, Field>, lists: Lists): Vals {
  const next: Vals = { ...vals, [name]: v };

  // fill empty parents upwards
  let cur = name;
  while (str(next[cur]) && meta[cur]?.parent_field) {
    const f = meta[cur], pf = f.parent_field!;
    if (str(next[pf])) break;
    const ids = chosenIds(cur, next, meta, lists);
    const pList = lists[meta[pf]?.lookup ?? ""];
    const parentIds = new Set((lists[f.lookup!] || []).filter((e) => ids?.has(e.id)).map((e) => e.parent_id));
    const parents = Array.from(new Set((pList || []).filter((e) => parentIds.has(e.id)).map((e) => e.name)));
    if (parents.length !== 1) break;
    next[pf] = parents[0];
    cur = pf;
  }

  // empty children that no longer fit, downwards
  const clear = (parent: string) => {
    for (const child of Object.values(meta).filter((m) => m.parent_field === parent)) {
      const cv = str(next[child.name]);
      if (cv) {
        const c = choicesFor(child, next, meta, lists);
        if (c && !c.options.includes(cv)) next[child.name] = null;
      }
      clear(child.name);
    }
  };
  clear(name);
  return next;
}

/** Postcode fields (34, 42): region postcode + district postcode + ward postcode of the same
 *  section, e.g. 17 + 1 + 06 = 17106. Empty until all three are chosen. */
export function fillPostcodes(vals: Vals, meta: Record<string, Field>, lists: Lists): Vals {
  let next = vals;
  for (const f of Object.values(meta)) {
    if (!f.postcode_parts?.length) continue;
    const parts = f.postcode_parts.map((p) => {
      const m = meta[p];
      if (!m?.lookup || !str(next[p])) return null;
      const ids = chosenIds(p, next, meta, lists);
      const e = (lists[m.lookup] || []).find((x) => ids?.has(x.id));
      return e?.postcode != null && String(e.postcode).trim() !== "" ? String(e.postcode).trim() : null;
    });
    const code = parts.every((x) => x !== null) ? parts.join("") : null;
    if ((next[f.name] ?? null) !== code) next = { ...next, [f.name]: code };
  }
  return next;
}
