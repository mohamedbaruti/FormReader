import { useSyncExternalStore } from "react";
const subs = new Set<() => void>();
export function navigate(href: string) { history.pushState({}, "", href); subs.forEach((f) => f()); window.scrollTo(0, 0); }
window.addEventListener("popstate", () => subs.forEach((f) => f()));
export function useLocation() {
  return useSyncExternalStore((cb) => { subs.add(cb); return () => subs.delete(cb); }, () => location.pathname + location.search);
}
