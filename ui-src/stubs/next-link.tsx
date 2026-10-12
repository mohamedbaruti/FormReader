import type { AnchorHTMLAttributes, ReactNode } from "react";
import { navigate } from "./router";
export default function Link({ href, children, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string; children?: ReactNode }) {
  return <a href={href} {...rest} onClick={(e) => { e.preventDefault(); navigate(href); }}>{children}</a>;
}
