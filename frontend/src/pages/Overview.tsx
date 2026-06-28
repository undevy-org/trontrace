import { useEffect, useState } from "react";
import { api, Overview as OverviewData } from "../api";

// Screen 2 — Overview.
export function Overview() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.overview().then(setData).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p>No analysis yet. Start one from the home screen.</p>;
  if (!data) return <p>Loading…</p>;

  const lowConfidence = data.primary_payer.confidence < 0.7;

  return (
    <section>
      <h1>Overview</h1>
      {lowConfidence && (
        <blockquote style={{ background: "#fff8e1", padding: 12, borderLeft: "4px solid #ffb300" }}>
          Results are heuristic estimates from public on-chain data, not verified facts.
          Cross-check on a block explorer.
        </blockquote>
      )}

      <h3>Primary payer cluster ({Math.round(data.primary_payer.confidence * 100)}% confidence)</h3>
      <ul>
        {data.primary_payer.wallets.map((w) => (
          <li key={w.address}>
            <code>{w.address}</code> — {Math.round(w.confidence * 100)}%
          </li>
        ))}
      </ul>

      <p>
        Anchor received <strong>{data.totals.received}</strong> total (avg{" "}
        {data.totals.monthly_avg}/month). Counterparties: <strong>{data.counterparty_count}</strong>.
      </p>

      <details>
        <summary>Excluded — likely exchange ({data.exchanges.length})</summary>
        <ul>{data.exchanges.map((a) => <li key={a}><code>{a}</code></li>)}</ul>
      </details>
      <details>
        <summary>Noise — non-cluster senders ({data.noise.length})</summary>
        <ul>{data.noise.map((a) => <li key={a}><code>{a}</code></li>)}</ul>
      </details>
    </section>
  );
}
