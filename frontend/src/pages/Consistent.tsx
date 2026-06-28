import { useEffect, useMemo, useState } from "react";
import { api, Consistent as Data } from "../api";
import { WalletDetail } from "../components/WalletDetail";

export function Consistent() {
  const [data, setData] = useState<Data | null>(null);
  const [minMonths, setMinMonths] = useState("4");
  const [minCons, setMinCons] = useState("0.8");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    const q = `?min_months=${minMonths || 0}&min_consistency=${minCons || 0}`;
    api.consistent(q).then(setData).catch(() => setData(null));
  }, [minMonths, minCons]);

  const partners = useMemo(() => {
    const m = new Map<string, string>();
    data?.hints.forEach((h) => { m.set(h.a, h.b); m.set(h.b, h.a); });
    return m;
  }, [data]);

  function downloadCsv() {
    if (!data) return;
    const lines = [["address", "amount_per_month", "months", "consistency"].join(",")];
    data.rows.forEach((r) => lines.push([r.address, r.amount, r.months, r.consistency].join(",")));
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "consistent-recipients.csv"; a.click();
    URL.revokeObjectURL(url);
  }

  if (!data) return <p>No analysis yet. Run an expansion first.</p>;

  return (
    <section>
      <h1>Consistent-amount recipients</h1>
      <blockquote>Heuristic estimate from public on-chain data, not verified facts.</blockquote>
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <label>min months <input value={minMonths} onChange={(e) => setMinMonths(e.target.value)} style={{ width: 50 }} /></label>
        <label>min consistency <input value={minCons} onChange={(e) => setMinCons(e.target.value)} style={{ width: 50 }} /></label>
        <button onClick={downloadCsv}>Export CSV</button>
      </div>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead><tr>
          <th style={{ textAlign: "left", padding: 6 }}>Address</th>
          <th style={{ padding: 6 }}>Amount/mo</th>
          <th style={{ padding: 6 }}>Months</th>
          <th style={{ padding: 6 }}>Consistency</th>
        </tr></thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.address}>
              <td style={{ padding: 6 }}>
                <button onClick={() => setSelected(r.address)}
                        style={{ background: "none", border: 0, color: "#1565c0", cursor: "pointer" }}>
                  {r.address}
                </button>
                {partners.has(r.address) && (
                  <span title={`possible same entity as ${partners.get(r.address)}`}
                        style={{ marginLeft: 6, fontSize: 11, color: "#8e24aa" }}>↔</span>
                )}
              </td>
              <td style={{ padding: 6, textAlign: "right" }}>{r.amount}</td>
              <td style={{ padding: 6, textAlign: "center" }}>{r.months}</td>
              <td style={{ padding: 6, textAlign: "center" }}>{Math.round(r.consistency * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      {selected && <WalletDetail address={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}
