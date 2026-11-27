"use client";

import { useEffect, useMemo, useRef, useState } from "react";

export type GNode = { id: string; type: string; label: string; summary: string; props: Record<string, any>; degree: number };
export type GEdge = { source: string; target: string; label: string };
export type GData = { nodes: GNode[]; edges: GEdge[]; types: { type: string; color: string; count: number }[]; title: string; alias: string };

type P = { x: number; y: number; vx: number; vy: number; fixed: boolean };

const FONT = "Helvetica Neue, Helvetica, Arial, sans-serif";

/** Force-directed knowledge graph of one brain, drawn on canvas. No dependencies: a small spring-electrical simulation. */
export default function BrainGraph({ data, height = 720 }: { data: GData; height?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const pos = useRef<Record<string, P>>({});
  const view = useRef({ x: 0, y: 0, k: 1 });
  const alpha = useRef(1);
  const fitted = useRef(false);
  const touched = useRef(false);
  const drag = useRef<{ mode: "pan" | "node" | null; id?: string; sx: number; sy: number; moved: boolean }>({ mode: null, sx: 0, sy: 0, moved: false });
  const [sel, setSel] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [edgeLabels, setEdgeLabels] = useState(false);
  const [query, setQuery] = useState("");
  const [width, setWidth] = useState(900);

  const color = useMemo(() => Object.fromEntries(data.types.map((t) => [t.type, t.color])), [data]);
  const byId = useMemo(() => Object.fromEntries(data.nodes.map((n) => [n.id, n])), [data]);
  const neighbours = useMemo(() => {
    const m: Record<string, Set<string>> = {};
    data.edges.forEach((e) => {
      (m[e.source] ??= new Set()).add(e.target);
      (m[e.target] ??= new Set()).add(e.source);
    });
    return m;
  }, [data]);

  // Seed positions: the person in the middle, everyone else on a ring by type so the layout settles quickly.
  useEffect(() => {
    const types = data.types.map((t) => t.type);
    const next: Record<string, P> = {};
    data.nodes.forEach((n, i) => {
      if (n.id === "person") { next[n.id] = { x: 0, y: 0, vx: 0, vy: 0, fixed: false }; return; }
      const ti = types.indexOf(n.type);
      const a = (ti / types.length) * Math.PI * 2 + (i % 7) * 0.09;
      const r = 120 + (i % 11) * 22;
      next[n.id] = { x: Math.cos(a) * r, y: Math.sin(a) * r, vx: 0, vy: 0, fixed: false };
    });
    pos.current = next;
    alpha.current = 1;
    view.current = { x: 0, y: 0, k: 1 };
    fitted.current = false;
    touched.current = false;
  }, [data]);

  useEffect(() => {
    const ro = new ResizeObserver(() => setWidth(wrapRef.current?.clientWidth ?? 900));
    if (wrapRef.current) ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  // Stop the page from scrolling while zooming the graph (React wheel listeners are passive).
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const stop = (e: WheelEvent) => e.preventDefault();
    c.addEventListener("wheel", stop, { passive: false });
    return () => c.removeEventListener("wheel", stop);
  }, []);

  // Simulation + render loop.
  useEffect(() => {
    let raf = 0;
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;

    const visible = (id: string) => !hidden.has(byId[id]?.type);
    const q = query.trim().toLowerCase();

    const tick = () => {
      const ps = pos.current;
      const ids = data.nodes.map((n) => n.id).filter(visible);
      const a = alpha.current;
      if (a > 0.004) {
        for (let i = 0; i < ids.length; i++) {
          const p = ps[ids[i]];
          for (let j = i + 1; j < ids.length; j++) {
            const o = ps[ids[j]];
            let dx = p.x - o.x, dy = p.y - o.y;
            let d2 = dx * dx + dy * dy;
            if (d2 < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 0.25; }
            if (d2 > 90000) continue;
            const f = (650 * a) / d2;
            p.vx += dx * f; p.vy += dy * f; o.vx -= dx * f; o.vy -= dy * f;
          }
        }
        for (const e of data.edges) {
          if (!visible(e.source) || !visible(e.target)) continue;
          const s = ps[e.source], t = ps[e.target];
          const hub = e.source === "person" || e.target === "person";
          const rest = hub ? 110 : 40;
          const dx = t.x - s.x, dy = t.y - s.y;
          const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const f = ((d - rest) / d) * 0.035 * a;
          s.vx += dx * f; s.vy += dy * f; t.vx -= dx * f; t.vy -= dy * f;
        }
        for (const id of ids) {
          const p = ps[id];
          if (p.fixed || id === "person") { p.vx = p.vy = 0; if (id === "person" && !p.fixed) { p.x *= 0.9; p.y *= 0.9; } continue; }
          p.vx -= p.x * 0.005 * a; p.vy -= p.y * 0.005 * a;
          p.vx *= 0.82; p.vy *= 0.82;
          p.x += Math.max(-20, Math.min(20, p.vx)); p.y += Math.max(-20, Math.min(20, p.vy));
        }
        alpha.current = a * 0.992;
        // Once the layout has mostly settled, zoom to fit everything (unless the user already moved the view).
        if (!fitted.current && alpha.current < 0.03 && !touched.current) {
          // Fit the middle 96% of nodes so a few stray leaves do not shrink everything.
          const xs = ids.map((id) => ps[id].x).sort((m, n) => m - n), ys = ids.map((id) => ps[id].y).sort((m, n) => m - n);
          const q = (arr: number[], f: number) => arr[Math.min(arr.length - 1, Math.max(0, Math.floor(arr.length * f)))];
          const x0 = q(xs, 0.02), x1 = q(xs, 0.98), y0 = q(ys, 0.02), y1 = q(ys, 0.98);
          const k = Math.min(1.3, 0.85 * Math.min(width / (x1 - x0 + 120), (height - 80) / (y1 - y0 + 80)));
          view.current = { k, x: -((x0 + x1) / 2) * k, y: -((y0 + y1) / 2) * k + 20 };
          fitted.current = true;
        }
      }

      // Render
      const { x: vx, y: vy, k } = view.current;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, width, height);
      ctx.translate(width / 2 + vx, height / 2 + vy);
      ctx.scale(k, k);
      const focus = hover ?? sel;
      const near = focus ? neighbours[focus] ?? new Set() : null;

      for (const e of data.edges) {
        if (!visible(e.source) || !visible(e.target)) continue;
        const s = ps[e.source], t = ps[e.target];
        const on = focus && (e.source === focus || e.target === focus);
        ctx.strokeStyle = on ? "#FF6623" : focus ? "rgba(200,200,200,0.35)" : "rgba(180,180,180,0.55)";
        ctx.lineWidth = (on ? 1.4 : 0.6) / Math.sqrt(k);
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);
        ctx.stroke();
        if (edgeLabels && (on || k > 1.6)) {
          ctx.fillStyle = on ? "#C2410C" : "#9CA3AF";
          ctx.font = `${9 / Math.sqrt(k)}px ${FONT}`;
          ctx.fillText(e.label, (s.x + t.x) / 2 + 2, (s.y + t.y) / 2 - 2);
        }
      }
      for (const n of data.nodes) {
        if (!visible(n.id)) continue;
        const p = ps[n.id];
        const r = (n.id === "person" ? 14 : 3.5 + Math.sqrt(n.degree) * 1.4) / Math.min(1, Math.sqrt(k));
        const dim = focus && n.id !== focus && !near!.has(n.id);
        const match = q && n.label.toLowerCase().includes(q);
        ctx.globalAlpha = dim ? 0.25 : 1;
        ctx.beginPath();
        ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
        ctx.fillStyle = color[n.type] ?? "#999";
        ctx.fill();
        ctx.lineWidth = (n.id === sel || match ? 2.5 : 1) / Math.sqrt(k);
        ctx.strokeStyle = n.id === sel ? "#1A1A1A" : match ? "#FF6623" : "#ffffff";
        ctx.stroke();
        const showLabel = n.id === focus || (near && near.has(n.id)) || match || n.degree >= 6 || k > 1.4 || n.type === "Person" || n.type === "Decision";
        if (showLabel) {
          ctx.fillStyle = "#1A1A1A";
          ctx.font = `${(n.id === "person" ? 13 : 10.5) / Math.sqrt(k)}px ${FONT}`;
          const label = n.label.length > 34 ? n.label.slice(0, 33) + "…" : n.label;
          ctx.fillText(label, p.x + r + 3, p.y + 3.5);
        }
        ctx.globalAlpha = 1;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [data, width, height, sel, hover, hidden, edgeLabels, query, color, byId, neighbours]);

  const toWorld = (cx: number, cy: number) => {
    const { x, y, k } = view.current;
    return { x: (cx - width / 2 - x) / k, y: (cy - height / 2 - y) / k };
  };
  const hit = (cx: number, cy: number): string | null => {
    const w = toWorld(cx, cy);
    let best: string | null = null, bd = Infinity;
    for (const n of data.nodes) {
      if (hidden.has(n.type)) continue;
      const p = pos.current[n.id];
      const r = (n.id === "person" ? 14 : 3.5 + Math.sqrt(n.degree) * 1.4) + 4 / view.current.k;
      const d = (p.x - w.x) ** 2 + (p.y - w.y) ** 2;
      if (d < r * r && d < bd) { best = n.id; bd = d; }
    }
    return best;
  };
  const local = (e: React.MouseEvent | React.WheelEvent) => {
    const r = canvasRef.current!.getBoundingClientRect();
    return { cx: e.clientX - r.left, cy: e.clientY - r.top };
  };

  const node = sel ? byId[sel] : null;
  const rels = sel ? data.edges.filter((e) => e.source === sel || e.target === sel) : [];

  return (
    <div ref={wrapRef} style={{ position: "relative", border: "1px solid #E5E7EB", background: "#fff" }}>
      <div style={{ position: "absolute", top: 12, left: 14, right: 14, display: "flex", gap: 10, alignItems: "center", zIndex: 2, pointerEvents: "none" }}>
        <b style={{ fontSize: 14, color: "#1A1A1A" }}>Brain graph: {data.alias}</b>
        <span className="muted" style={{ fontSize: 12 }}>{data.nodes.length} entities · {data.edges.length} relationships</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8, pointerEvents: "auto" }}>
          <input type="text" placeholder="Find an entity" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: 160 }} />
          <label className="row" style={{ gap: 4, fontSize: 13, background: "#fff" }}>
            <input type="checkbox" checked={edgeLabels} onChange={(e) => setEdgeLabels(e.target.checked)} /> Edge labels
          </label>
          <button className="btn ghost" style={{ padding: "4px 10px" }} onClick={() => { touched.current = false; fitted.current = false; alpha.current = Math.max(alpha.current, 0.031); }}>Fit view</button>
        </span>
      </div>

      <canvas
        ref={canvasRef}
        style={{ width, height, display: "block", cursor: hover ? "pointer" : drag.current.mode === "pan" ? "grabbing" : "grab" }}
        onMouseDown={(e) => {
          const { cx, cy } = local(e);
          const id = hit(cx, cy);
          drag.current = { mode: id ? "node" : "pan", id: id ?? undefined, sx: cx, sy: cy, moved: false };
          touched.current = true;
        }}
        onMouseMove={(e) => {
          const { cx, cy } = local(e);
          const d = drag.current;
          if (d.mode === "pan") {
            view.current.x += cx - d.sx; view.current.y += cy - d.sy;
            d.sx = cx; d.sy = cy; d.moved = true;
          } else if (d.mode === "node" && d.id) {
            const w = toWorld(cx, cy);
            const p = pos.current[d.id];
            p.x = w.x; p.y = w.y; p.fixed = true; d.moved = true;
            alpha.current = Math.max(alpha.current, 0.25);
          } else {
            setHover(hit(cx, cy));
          }
        }}
        onMouseUp={(e) => {
          const d = drag.current;
          if (!d.moved) {
            const { cx, cy } = local(e);
            setSel(hit(cx, cy));
          }
          drag.current = { mode: null, sx: 0, sy: 0, moved: false };
        }}
        onMouseLeave={() => { drag.current = { mode: null, sx: 0, sy: 0, moved: false }; setHover(null); }}
        onWheel={(e) => {
          const { cx, cy } = local(e);
          touched.current = true;
          const v = view.current;
          const k2 = Math.max(0.25, Math.min(5, v.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
          const wx = (cx - width / 2 - v.x) / v.k, wy = (cy - height / 2 - v.y) / v.k;
          v.x = cx - width / 2 - wx * k2; v.y = cy - height / 2 - wy * k2; v.k = k2;
        }}
      />

      <div style={{ position: "absolute", left: 14, bottom: 14, background: "rgba(255,255,255,0.94)", border: "1px solid #E5E7EB", padding: "8px 10px", maxWidth: 520 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: "#FF6623", letterSpacing: 0.5, marginBottom: 4 }}>ENTITY TYPES</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 12px" }}>
          {data.types.map((t) => (
            <button key={t.type} onClick={() => setHidden((h) => { const n = new Set(h); n.has(t.type) ? n.delete(t.type) : n.add(t.type); alpha.current = 0.4; return n; })}
              style={{ border: 0, background: "none", padding: 0, cursor: "pointer", fontSize: 12, color: hidden.has(t.type) ? "#C0C4CC" : "#333", display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ width: 9, height: 9, borderRadius: 9, background: hidden.has(t.type) ? "#E5E7EB" : t.color, display: "inline-block" }} />
              {t.type} <span style={{ color: "#9CA3AF" }}>{t.count}</span>
            </button>
          ))}
        </div>
      </div>

      {node && (
        <div style={{ position: "absolute", right: 14, top: 52, width: 300, maxHeight: height - 70, overflowY: "auto", background: "#fff",
          border: "1px solid #E5E7EB", boxShadow: "0 6px 20px rgba(0,0,0,0.08)", borderRadius: 8, padding: "12px 14px", fontSize: 13 }}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <b style={{ fontSize: 14, color: "#1A1A1A" }}>Node details</b>
            <span style={{ background: color[node.type], color: "#fff", fontSize: 11, padding: "2px 8px", borderRadius: 10 }}>{node.type}</span>
          </div>
          <table style={{ marginTop: 8, fontSize: 12.5 }}><tbody>
            <tr><td className="muted">Name</td><td className="ink">{node.label}</td></tr>
            <tr><td className="muted">ID</td><td className="mono">{node.id}</td></tr>
            <tr><td className="muted">Links</td><td>{node.degree}</td></tr>
            {Object.entries(node.props).slice(0, 10).map(([k, v]) => (
              <tr key={k}><td className="muted">{k.replace(/_/g, " ")}</td><td className="ink" style={{ wordBreak: "break-word" }}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td></tr>
            ))}
          </tbody></table>
          {node.summary && (<><div style={{ fontWeight: 700, marginTop: 8 }}>Summary</div><p style={{ margin: "4px 0 0" }}>{node.summary}</p></>)}
          <div style={{ fontWeight: 700, marginTop: 10 }}>Relationships ({rels.length})</div>
          <ul className="sq" style={{ marginTop: 4 }}>
            {rels.slice(0, 30).map((e, i) => {
              const other = e.source === node.id ? e.target : e.source;
              return (
                <li key={i} style={{ marginBottom: 3 }}>
                  <span className="mono">{e.source === node.id ? `${e.label} →` : `← ${e.label}`}</span>{" "}
                  <a style={{ cursor: "pointer", fontWeight: 600 }} onClick={() => setSel(other)}>{byId[other]?.label}</a>
                </li>
              );
            })}
            {rels.length > 30 && <li className="muted">and {rels.length - 30} more</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
