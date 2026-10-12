// Who is using this browser tab, so that two people never check the same training form.
// There is no sign-in yet: each tab gets a random id (kept while the tab is open, also after a
// reload), and the person types their name once on the Training page (kept in this browser).
// Both are sent to the reader with every call (lib/api.ts) as X-Staff-Client / X-Staff-Name.

const ID_KEY = "nida.staffClient";
const NAME_KEY = "nida.staffName";
let memoryId: string | null = null;
let memoryName = "";

function randomId() {
  try {
    return crypto.randomUUID().replace(/-/g, "");
  } catch {
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
}

/** Random id of this browser tab. */
export function staffClient(): string {
  if (typeof window === "undefined") return "";
  try {
    let id = sessionStorage.getItem(ID_KEY);
    if (!id) { id = randomId(); sessionStorage.setItem(ID_KEY, id); }
    return id;
  } catch {
    return (memoryId ||= randomId());
  }
}

/** Name shown to others ("Being checked by Asha"). Empty until the person types it. */
export function staffName(): string {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(NAME_KEY) || "";
  } catch {
    return memoryName;
  }
}

export function setStaffName(name: string) {
  memoryName = name.trim().slice(0, 40);
  try { localStorage.setItem(NAME_KEY, memoryName); } catch { /* kept in memory for this tab */ }
}

/** Headers sent with every call to the reader. */
export function staffHeaders(): Record<string, string> {
  const id = staffClient();
  return id ? { "X-Staff-Client": id, "X-Staff-Name": encodeURIComponent(staffName()) } : {};
}
