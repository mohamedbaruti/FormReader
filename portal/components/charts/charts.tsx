"use client";

// Small SVG charts, no chart library. Colours come from CSS variables in
// globals.css (validated palette). Every chart has a hover tooltip and a
// screen-reader table.

import { useEffect, useRef, useState } from "react";

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((e) => setW(Math.floor(e[0].contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function niceMax(v: number) {
  if (v <= 4) return 4;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

function SrTable({ caption, rows }: { caption: string; rows: [string, number | string][] }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <tbody>{rows.map(([k, v]) => <tr key={k}><th scope="row">{k}</th><td>{v}</td></tr>)}</tbody>
    </table>
  );
}

// ---------------------------------------------------------------- area (time series)
export function AreaChart({ data, label }: { data: { date: string; count: number }[]; label: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const H = 220, padL = 34, padR = 12, padT = 14, padB = 26;
  const w = Math.max(width, 200);
  const max = niceMax(Math.max(1, ...data.map((d) => d.count)));
  const x = (i: number) => padL + (i * (w - padL - padR)) / Math.max(1, data.length - 1);
  const y = (v: number) => padT + (1 - v / max) * (H - padT - padB);
  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.count)}`).join(" ");
  const area = `${line} L${x(data.length - 1)},${y(0)} L${x(0)},${y(0)} Z`;
  const ticks = [0, max / 2, max];
  const fmt = (s: string) => new Date(s + "T00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const labelEvery = Math.ceil(data.length / 6);

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = (e.target as SVGRectElement).getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (data.length - 1));
    setHover(Math.max(0, Math.min(data.length - 1, i)));
  };

  return (
    <div ref={ref} className="chart">
      {width > 0 && (
        <svg width={w} height={H} role="img" aria-label={label}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={padL} x2={w - padR} y1={y(t)} y2={y(t)} className="grid" />
              <text x={padL - 8} y={y(t) + 4} className="axis" textAnchor="end">{t}</text>
            </g>
          ))}
          {data.map((d, i) => (i % labelEvery === 0 && data.length - 1 - i >= labelEvery / 2) || i === data.length - 1 ? (
            <text key={d.date} x={x(i)} y={H - 6} className="axis"
                  textAnchor={i === data.length - 1 ? "end" : i === 0 ? "start" : "middle"}>{fmt(d.date)}</text>
          ) : null)}
          <defs>
            <linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor="var(--series-1)" stopOpacity="0.28" />
              <stop offset="100%" stopColor="var(--series-1)" stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <path d={area} fill="url(#areaFill)" />
          <path d={line} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" />
          {hover !== null && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={padT} y2={y(0)} className="crosshair" />
              <circle cx={x(hover)} cy={y(data[hover].count)} r={5} fill="var(--series-1)" stroke="var(--card)" strokeWidth={2} />
            </g>
          )}
          <rect x={padL} y={padT} width={w - padL - padR} height={H - padT - padB} fill="transparent"
                onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
        </svg>
      )}
      {hover !== null && width > 0 && (
        <div className="tooltip" style={{ left: Math.min(Math.max(x(hover), 70), w - 70), top: y(data[hover].count) - 12 }}>
          <strong>{data[hover].count}</strong> enrolment{data[hover].count === 1 ? "" : "s"}
          <span>{fmt(data[hover].date)}</span>
        </div>
      )}
      <SrTable caption={label} rows={data.map((d) => [d.date, d.count])} />
    </div>
  );
}

// ---------------------------------------------------------------- donut (<= 3 categories)
const CAT = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-muted)"];

export function Donut({ data, label, centerLabel }:
  { data: { key: string; label: string; value: number }[]; label: string; centerLabel: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const total = data.reduce((s, d) => s + d.value, 0);
  const R = 70, r = 48, C = 90;
  let a0 = -Math.PI / 2;
  const gap = data.filter((d) => d.value > 0).length > 1 ? 0.025 : 0;
  const arcs = data.map((d, i) => {
    const frac = total ? d.value / total : 0;
    const a1 = a0 + frac * 2 * Math.PI;
    const s = a0 + gap / 2, e = a1 - gap / 2;
    a0 = a1;
    if (frac <= 0) return null;
    if (frac >= 0.9999) {
      return <g key={d.key}><circle cx={C} cy={C} r={(R + r) / 2} fill="none" stroke={CAT[i]} strokeWidth={R - r} /></g>;
    }
    const large = e - s > Math.PI ? 1 : 0;
    const p = (rad: number, a: number) => `${C + rad * Math.cos(a)},${C + rad * Math.sin(a)}`;
    const path = `M${p(R, s)} A${R},${R} 0 ${large} 1 ${p(R, e)} L${p(r, e)} A${r},${r} 0 ${large} 0 ${p(r, s)} Z`;
    return (
      <path key={d.key} d={path} fill={CAT[i]} opacity={hover === null || hover === i ? 1 : 0.45}
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
    );
  });
  const shown = hover !== null ? data[hover] : null;
  return (
    <div className="donut-wrap">
      <svg width={180} height={180} viewBox="0 0 180 180" role="img" aria-label={label}>
        {total === 0 && <circle cx={C} cy={C} r={(R + r) / 2} fill="none" stroke="var(--grid)" strokeWidth={R - r} />}
        {arcs}
        <text x={C} y={C - 2} textAnchor="middle" className="donut-value">{shown ? shown.value : total}</text>
        <text x={C} y={C + 18} textAnchor="middle" className="donut-caption">{shown ? shown.label : centerLabel}</text>
      </svg>
      <ul className="legend">
        {data.map((d, i) => (
          <li key={d.key} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <span className="swatch" style={{ background: CAT[i] }} />
            <span className="legend-label">{d.label}</span>
            <span className="legend-value">{d.value}<small>{total ? ` · ${Math.round((d.value / total) * 100)}%` : ""}</small></span>
          </li>
        ))}
      </ul>
      <SrTable caption={label} rows={data.map((d) => [d.label, d.value])} />
    </div>
  );
}

// ---------------------------------------------------------------- horizontal bars (one hue)
export function BarList({ data, label, empty = "No data yet" }:
  { data: { label: string; value: number }[]; label: string; empty?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...data.map((d) => d.value));
  if (!data.length) return <p className="chart-empty">{empty}</p>;
  return (
    <div className="barlist" role="img" aria-label={label}>
      {data.map((d, i) => (
        <div key={d.label} className={`bar-row${hover === i ? " hover" : ""}`}
             onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
          <span className="bar-label" title={d.label}>{d.label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${(d.value / max) * 100}%` }} />
          </span>
          <span className="bar-value">{d.value}</span>
        </div>
      ))}
      <SrTable caption={label} rows={data.map((d) => [d.label, d.value])} />
    </div>
  );
}

// ---------------------------------------------------------------- columns (one hue)
export function Columns({ data, label }: { data: { label: string; value: number }[]; label: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = niceMax(Math.max(1, ...data.map((d) => d.value)));
  return (
    <div className="columns" role="img" aria-label={label}>
      <div className="col-plot">
        {[1, 0.5, 0].map((t) => <span key={t} className="col-grid" style={{ bottom: `${t * 100}%` }}><em>{Math.round(t * max)}</em></span>)}
        {data.map((d, i) => (
          <div key={d.label} className="col" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            {hover === i && <span className="col-tip">{d.value}</span>}
            <span className="col-fill" style={{ height: `${(d.value / max) * 100}%`, opacity: hover === null || hover === i ? 1 : 0.55 }} />
          </div>
        ))}
      </div>
      <div className="col-labels">{data.map((d) => <span key={d.label}>{d.label}</span>)}</div>
      <SrTable caption={label} rows={data.map((d) => [d.label, d.value])} />
    </div>
  );
}

// ---------------------------------------------------------------- progress ring (single value)
export function Ring({ value, label }: { value: number | null; label: string }) {
  const R = 30, c = 2 * Math.PI * R;
  const v = value === null ? 0 : Math.max(0, Math.min(1, value));
  return (
    <svg width={76} height={76} viewBox="0 0 76 76" role="img" aria-label={`${label}: ${value === null ? "no data" : Math.round(v * 100) + "%"}`}>
      <circle cx={38} cy={38} r={R} fill="none" stroke="var(--grid)" strokeWidth={8} />
      {v > 0 && (
        <circle cx={38} cy={38} r={R} fill="none" stroke="var(--series-1)" strokeWidth={8} strokeLinecap="round"
                strokeDasharray={`${c * v} ${c}`} transform="rotate(-90 38 38)" />
      )}
    </svg>
  );
}
