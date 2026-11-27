"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import BrainGraph, { GData } from "@/components/BrainGraph";
import { api } from "@/lib/api";

export default function BrainPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [data, setData] = useState<GData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api(`/customers/${id}/graph`).then(setData).catch((e) => setError(e.message)); }, [id]);

  return (
    <main className="wrap" style={{ maxWidth: 1560 }}>
      <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
        <Link href="/">Dashboard</Link> / <Link href={`/customers/${id}`}>{data?.title ?? id}</Link> / brain graph
      </div>
      <section className="hero" style={{ marginBottom: 14 }}>
        <h1>The <em>brain</em> of {data?.title ?? id}</h1>
        <p>Every dot is something this brain holds: the customer, every loan, payment, promise, subscription and message, what they said,
          the facts computed from it, the beliefs those facts support, and the decision on top. Scroll to zoom, drag to move, click a dot for its details.</p>
      </section>
      {error && <div className="notice">{error}</div>}
      {!data && !error && <p className="muted">Growing the brain…</p>}
      {data && <BrainGraph data={data} height={760} />}
      <div className="row" style={{ marginTop: 12 }}>
        <Link className="btn ghost" href={`/customers/${id}`}>Back to the customer</Link>
      </div>
    </main>
  );
}
