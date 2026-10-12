"use client";

import Link from "next/link";
import { usePhone } from "@/lib/device";
import { IconInfo } from "@/components/Icons";

/** Reader Training is only on the computer: on the phone (the Android app) it is not shown. */
export default function TrainingLayout({ children }: { children: React.ReactNode }) {
  const phone = usePhone();
  if (!phone) return <>{children}</>;
  return (
    <div className="page">
      <div className="notice info"><IconInfo size={18} />
        <span>Reader Training is done on the computer, not on the phone.{" "}
          <Link href="/enrolment/new" className="strong-link">Start a new enrolment</Link></span>
      </div>
    </div>
  );
}
