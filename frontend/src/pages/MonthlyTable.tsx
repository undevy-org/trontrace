import { useEffect, useMemo, useState } from "react";
import { api, Monthly } from "../api";
import { WalletDetail } from "../components/WalletDetail";

// Screen 3 — Monthly Table (primary screen).
export function MonthlyTable() {
  const [data, setData] = useState<Monthly | null>(null);
  const [search, setSearch] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    api.monthly(from || undefined, to || undefined).then(setData).catch(() => setData(null));
  }, [from, to]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = search.toLowerCase();
    return data.rows.filter((r) => !q || r.address.toLowerCase().includes(q));
  }, [data, search]);

  if (!data) return <p>No analysis yet. Start one from the home screen.</p>;

  return (
    <section>
      <h1>Monthly Table</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input placeholder="Search address" value={search} onChange={(e) => setSearch(e.target.value)} />
        <input placeholder="From YYYY-MM" value={from} onChange={(e) => setFrom(e.target.value)} />
        <input placeholder="To YYYY-MM" value={to} onChange={(e) => setTo(e.target.value)} />
        <a href={api.csvUrl()}>
          <button>Export CSV</button>
        </a>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr>
              <th style={th}>Counterparty</th>
              {data.months.map((m) => <th key={m} style={th}>{m}</th>)}
              <th style={th}>Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.address} style={{ fontWeight: r.role === "anchor" ? 700 : 400 }}>
                <td style={td}>
                  <button className="link" onClick={() => setSelected(r.address)}
                          style={{ background: "none", border: 0, cursor: "pointer", color: "#1565c0" }}>
                    {r.address}
                  </button>
                </td>
                {data.months.map((m) => <td key={m} style={tdNum}>{r.cells[m] ?? "0"}</td>)}
                <td style={tdNum}><strong>{r.total}</strong></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {selected && selected !== "You" && (
        <WalletDetail address={selected} onClose={() => setSelected(null)} />
      )}
    </section>
  );
}

const th: React.CSSProperties = { borderBottom: "2px solid #ddd", padding: "6px 10px", textAlign: "left" };
const td: React.CSSProperties = { borderBottom: "1px solid #eee", padding: "6px 10px" };
const tdNum: React.CSSProperties = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };
