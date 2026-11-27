export async function api<T = any>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export type NumberSystem = "indian" | "international";

/** ₹ amounts. Indian: ₹1,23,456 and L / Cr. International: ₹123,456 and K / Mn. */
export function inr(v: unknown, sys: NumberSystem, compact = false): string {
  const n = Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return "–";
  if (compact) {
    if (sys === "indian") {
      if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
      if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
    } else {
      if (Math.abs(n) >= 1e6) return `₹${(n / 1e6).toFixed(2)} Mn`;
      if (Math.abs(n) >= 1e3) return `₹${(n / 1e3).toFixed(1)}K`;
    }
  }
  return "₹" + Math.round(n).toLocaleString(sys === "indian" ? "en-IN" : "en-US");
}

export function num(v: unknown, sys: NumberSystem): string {
  const n = Number(v);
  if (v === null || v === undefined || Number.isNaN(n)) return "–";
  return n.toLocaleString(sys === "indian" ? "en-IN" : "en-US");
}

/** DD/MM/YYYY, with time when the value has one. */
export function ddmmyyyy(v: string | null | undefined): string {
  if (!v) return "–";
  const [d, t] = v.split("T");
  const [y, m, day] = d.split("-");
  return `${day}/${m}/${y}${t ? " " + t.slice(0, 5) : ""}`;
}

export const ACTION_LABEL: Record<string, string> = {
  contact: "Contact",
  hold: "Hold",
  human_review: "Human review",
  no_action: "No message needed",
};

export function pretty(s: string | null | undefined): string {
  return (s ?? "").replace(/_/g, " ");
}
