"use client";

/** The customer's world as a radial graph: the person at the centre, each object type on its own spoke. */
export default function Graph({ world }: { world: { nodes: any[]; edges: any[]; counts: Record<string, number> } }) {
  const W = 900, H = 460, cx = W / 2, cy = H / 2;
  const types = Object.keys(world.counts);
  const center = world.nodes.find((n) => n.type === "Customer");
  const pos: Record<string, { x: number; y: number }> = {};
  if (center) pos[center.id] = { x: cx, y: cy };

  const hubs = types.map((t, i) => {
    const a = (i / types.length) * Math.PI * 2 - Math.PI / 2;
    return { type: t, a, x: cx + Math.cos(a) * 150, y: cy + Math.sin(a) * 120 };
  });

  // Place each type's nodes on an arc beyond its hub; types linking to another object sit beyond that object.
  hubs.forEach((h) => {
    const nodes = world.nodes.filter((n) => n.type === h.type).slice(0, 14);
    nodes.forEach((n, j) => {
      const spread = Math.min(0.9, 0.12 * nodes.length);
      const a = h.a + (nodes.length > 1 ? (j / (nodes.length - 1) - 0.5) * spread : 0);
      const r = 235 + (j % 2) * 26;
      pos[n.id] = { x: cx + Math.cos(a) * r * 1.35, y: cy + Math.sin(a) * r * 0.78 };
    });
  });

  const shownEdges = world.edges.filter((e) => pos[e.from] && pos[e.to]);

  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ minWidth: 640, background: "#fff" }}>
        {hubs.map((h) => <line key={h.type} x1={cx} y1={cy} x2={h.x} y2={h.y} stroke="#FFB089" strokeWidth={2} />)}
        {shownEdges.map((e, i) => {
          const a = pos[e.from], b = pos[e.to];
          const hub = hubs.find((h) => e.from.startsWith(h.type + ":"));
          const via = e.to.startsWith("Customer:") && hub ? hub : b;
          return <line key={i} x1={a.x} y1={a.y} x2={via.x} y2={via.y} stroke="#E5E7EB" strokeWidth={1} />;
        })}
        {world.nodes.filter((n) => pos[n.id] && n.type !== "Customer").map((n) => (
          <circle key={n.id} cx={pos[n.id].x} cy={pos[n.id].y} r={5} fill="#FFE0D0" stroke="#FF6623" strokeWidth={1}>
            <title>{n.type} {n.label}</title>
          </circle>
        ))}
        {hubs.map((h) => {
          const label = `${h.type} ×${world.counts[h.type]}`;
          const w = label.length * 7.4 + 22;
          return (
            <g key={h.type}>
              <rect x={h.x - w / 2} y={h.y - 15} width={w} height={30} rx={6} fill="#fff" stroke="#FF6623" />
              <text x={h.x} y={h.y + 5} textAnchor="middle" fontSize={13} fill="#1A1A1A" fontFamily="Helvetica Neue, Helvetica, Arial">{label}</text>
            </g>
          );
        })}
        {center && (
          <g>
            <rect x={cx - 70} y={cy - 22} width={140} height={44} rx={8} fill="#FF6623" />
            <text x={cx} y={cy - 3} textAnchor="middle" fontSize={13} fontWeight={700} fill="#fff" fontFamily="Helvetica Neue, Helvetica, Arial">Customer</text>
            <text x={cx} y={cy + 13} textAnchor="middle" fontSize={12} fill="#fff" fontFamily="Helvetica Neue, Helvetica, Arial">{center.label}</text>
          </g>
        )}
      </svg>
      <div className="muted" style={{ fontSize: 12 }}>Up to 14 records per type are drawn; hover a dot for its id.</div>
    </div>
  );
}
