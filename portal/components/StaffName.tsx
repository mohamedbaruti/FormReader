"use client";

import { useEffect, useState } from "react";
import { setStaffName, staffName } from "@/lib/staff";

/** "Your name" box: shown to the others when you have a training form open ("Being checked by Asha"). */
export default function StaffName({ compact = false }: { compact?: boolean }) {
  const [name, setName] = useState("");
  useEffect(() => { setName(staffName()); }, []);
  return (
    <label className={`staff-name${compact ? " compact" : ""}`}>
      <span>{compact ? "Checking as" : "Your name"}</span>
      <input className="text-input" value={name} maxLength={40} placeholder="Type your name" autoComplete="name"
             onChange={(e) => { setName(e.target.value); setStaffName(e.target.value); }} />
    </label>
  );
}
