"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePhone } from "@/lib/device";
import {
  IconDashboard, IconNewEnrol, IconRecords, IconTraining, IconSettings, IconLogout, IconShield,
} from "./Icons";

const MAIN = [
  { href: "/", label: "Dashboard", icon: IconDashboard },
  { href: "/enrolment/new", label: "New Enrolment", icon: IconNewEnrol, cta: true },
  { href: "/enrolments", label: "Enrolments", icon: IconRecords },
  { href: "/training", label: "Reader Training", icon: IconTraining },
];

const BOTTOM = [
  { href: "/settings", label: "Settings", icon: IconSettings },
  { href: "/logout", label: "Logout", icon: IconLogout },
];

function isActive(path: string, href: string) {
  return href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
}

export default function Sidebar() {
  const path = usePathname() || "/";
  const [online, setOnline] = useState<boolean | null>(null);
  const phone = usePhone();          // the phone version has no Reader Training

  useEffect(() => {
    let alive = true;
    const ping = () => api.health().then(() => alive && setOnline(true)).catch(() => alive && setOnline(false));
    ping();
    const t = setInterval(ping, 30000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const item = (it: (typeof MAIN)[number] | (typeof BOTTOM)[number]) => {
    const active = isActive(path, it.href);
    const Icon = it.icon;
    return (
      <li key={it.href}>
        <Link href={it.href} className={`nav-item${active ? " active" : ""}${"cta" in it && it.cta ? " cta" : ""}`}
              aria-current={active ? "page" : undefined}>
          <span className="nav-icon"><Icon size={19} /></span>
          <span className="nav-label">{it.label}</span>
        </Link>
      </li>
    );
  };

  return (
    <aside className="sidebar glass" aria-label="Main menu">
      <div className="brand">
        <div className="brand-mark"><IconShield size={22} /></div>
        <div>
          <div className="brand-name">NIDA Enrolment</div>
          <div className="brand-sub">Form 1A reader</div>
        </div>
      </div>

      <nav className="nav">
        <div className="nav-heading">Menu</div>
        <ul>{MAIN.filter((it) => !(phone && it.href === "/training")).map(item)}</ul>
      </nav>

      <div className="sidebar-bottom">
        <div className={`api-status ${online === null ? "" : online ? "ok" : "down"}`} role="status">
          <span className="dot" />
          {online === null ? "Checking reader…" : online ? "Reader online" : "Reader offline"}
        </div>
        <ul>{BOTTOM.map(item)}</ul>
      </div>
    </aside>
  );
}
