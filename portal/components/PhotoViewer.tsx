"use client";

import { useEffect, useRef, useState } from "react";
import { IconX } from "./Icons";

/** Full-screen photo viewer. The photo opens at the width of the screen and scrolls up and down;
 *  zoom in to read small writing (buttons, + / - keys, or Ctrl + mouse wheel) and drag to move around.
 *  Esc, the X or a click on the dark area closes it. */
export default function PhotoViewer({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  const [zoom, setZoom] = useState(1);              // 1 = photo as wide as the viewer
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; left: number; top: number; moved: boolean } | null>(null);

  const change = (z: number) => setZoom(Math.min(4, Math.max(0.5, Math.round(z * 100) / 100)));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "+" || e.key === "=") setZoom((z) => Math.min(4, z + 0.25));
      else if (e.key === "-") setZoom((z) => Math.max(0.5, z - 0.25));
      else if (e.key === "0") setZoom(1);
    };
    window.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";       // the page behind does not scroll
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = overflow; };
  }, [onClose]);

  useEffect(() => { box.current?.focus(); }, []);

  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label={alt}>
      <div className="viewer-bar">
        <span className="viewer-title">{alt}</span>
        <div className="viewer-tools">
          <button className="btn small" onClick={() => change(zoom - 0.25)} aria-label="Zoom out" disabled={zoom <= 0.5}>−</button>
          <span className="viewer-zoom" aria-live="polite">{Math.round(zoom * 100)}%</span>
          <button className="btn small" onClick={() => change(zoom + 0.25)} aria-label="Zoom in" disabled={zoom >= 4}>+</button>
          <button className="btn small" onClick={() => setZoom(1)}>Fit width</button>
          <button className="btn icon-only" aria-label="Close" onClick={onClose}><IconX size={20} /></button>
        </div>
      </div>
      <div ref={box} className="viewer-scroll" tabIndex={0}
           onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
           onWheel={(e) => { if (e.ctrlKey) { e.preventDefault(); change(zoom * (e.deltaY < 0 ? 1.1 : 0.9)); } }}
           onMouseDown={(e) => {
             if (e.button !== 0 || !box.current || e.target === e.currentTarget) return;
             e.preventDefault();
             drag.current = { x: e.clientX, y: e.clientY, left: box.current.scrollLeft, top: box.current.scrollTop, moved: false };
           }}
           onMouseMove={(e) => {
             const d = drag.current;
             if (!d || !box.current) return;
             d.moved = true;
             box.current.scrollLeft = d.left - (e.clientX - d.x);
             box.current.scrollTop = d.top - (e.clientY - d.y);
           }}
           onMouseUp={() => { drag.current = null; }}
           onMouseLeave={() => { drag.current = null; }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={alt} draggable={false} style={{ width: `${zoom * 100}%` }} />
      </div>
      <p className="viewer-help">Scroll to move up and down · drag to move around · + / − to zoom · Esc to close</p>
    </div>
  );
}
