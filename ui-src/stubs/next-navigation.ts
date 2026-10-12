import { navigate, useLocation } from "./router";
export function usePathname() { return useLocation().split("?")[0]; }
export function useRouter() { return { push: navigate, replace: navigate, back: () => history.back(), refresh: () => {} }; }
export function useSearchParams() { const l = useLocation(); return new URLSearchParams(l.includes("?") ? l.split("?")[1] : ""); }
