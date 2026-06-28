import { useEffect, useState } from "react";
import { api, Cohort as CohortData } from "../api";
import { WalletDetail } from "../components/WalletDetail";

const TIER_COLOR: Record<string, string> = { high: "#2e7d32", med: "#f9a825", low: "#9e9e9e" };

export function Cohort() {
  const [data, setData] = useState<CohortData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.cohort().then(setData).catch(() => setData(null));
  }, []);

  if (!data) return <p>No expansion yet. Run one from the home screen.</p>;

  return (
    <section>
      <h1>Recurring-recipient cohort</h1>
      <blockquote>Heuristic estimates from public on-chain data, not verified facts.</blockquote>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", padding: 6 }}>Address</th>
            <th style={{ padding: 6 }}>Tier</th>
            <th style={{ padding: 6 }}>Months</th>
            <th style={{ padding: 6 }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {data.recipients.map((r) => (
            <tr key={r.address}>
              <td style={{ padding: 6 }}>
                <button onClick={() => setSelected(r.address)}
                        style={{ background: "none", border: 0, color: "#1565c0", cursor: "pointer" }}>
                  {r.address}
                </button>
              </td>
              <td style={{ padding: 6, textAlign: "center" }}>
                <span style={{ color: TIER_COLOR[r.tier] ?? "#777" }}>{r.tier}</span>
              </td>
              <td style={{ padding: 6, textAlign: "center" }}>{r.months_active}</td>
              <td style={{ padding: 6, textAlign: "right" }}>{r.total}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <WalletDetail address={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}
