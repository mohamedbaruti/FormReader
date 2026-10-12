"use client";

import { useEffect, useState } from "react";

/** True on the phone: inside the Android app (its WebView adds "NIDAPortalApp" to the user agent),
 *  in a phone browser, or when opened from the home-screen icon. The phone version has no
 *  Reader Training. false until known (first render on the server). */
export function isPhone(): boolean {
  if (typeof window === "undefined") return false;
  const ua = navigator.userAgent || "";
  return /NIDAPortalApp|Android|iPhone|iPad|Mobile/i.test(ua)
    || window.matchMedia?.("(display-mode: standalone)").matches === true;
}

export function usePhone(): boolean {
  const [phone, setPhone] = useState(false);
  useEffect(() => { setPhone(isPhone()); }, []);
  return phone;
}

type AppBridge = { saveFile: (name: string, text: string) => void; changeServer: () => void };

/** The Android app's bridge (window.NIDAApp), or null in a normal browser. */
export function appBridge(): AppBridge | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as { NIDAApp?: AppBridge }).NIDAApp ?? null;
}

/** Save a text file: into the phone's Downloads inside the Android app, a normal download elsewhere. */
export function saveTextFile(name: string, text: string, type = "application/json") {
  const app = appBridge();
  if (app) { app.saveFile(name, text); return; }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
