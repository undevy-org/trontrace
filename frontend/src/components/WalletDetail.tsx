import { useEffect, useState } from "react";
import { api, WalletDetail as Detail } from "../api";

// Screen 5 — Wallet Detail (side panel).
export function WalletDetail({ address, onClose }: { address: string; onClose: () => void }) {
  const [d, setD] = useState<Detail | null>(null);

  useEffect(() => {
    setD(null);
    api.wallet(address).then(setD).catch(() => setD(null));
  }, [address]);

  const ts = (s: number | null) => (s ? new Date(s * 1000).toISOString().slice(0, 10) : "—");

  return (
    <aside
      style={{
        position: "fixed",
        right: 0,
        top: 56,
        height: "calc(100vh - 56px)",
        width: 360,
        background: "#fff",
        boxShadow: "-2px 0 8px rgba(0,0,0,.1)",
        padding: 16,
        overflowY: "auto",
        zIndex: 10,
      }}
    >
      <button onClick={onClose} style={{ float: "right" }}>✕</button>
      <h3 style={{ wordBreak: "break-all" }}>{address}</h3>
      <button onClick={() => navigator.clipboard?.writeText(address)}>Copy address</button>
      {!d ? (
        <p>Loading…</p>
      ) : (
        <>
          <p>
            Role: <strong>{d.role ?? "unknown"}</strong>
            {d.confidence != null && <> · {Math.round(d.confidence * 100)}% confidence</>}
          </p>
          <p>
            Active: {ts(d.first_seen)} → {ts(d.last_seen)}
          </p>
          <h4>Top recipients</h4>
          <ul>{d.top_recipients.map((r) => <li key={r.address}><code>{r.address.slice(0, 10)}…</code> {r.total}</li>)}</ul>
          <h4>Top senders</h4>
          <ul>{d.top_senders.map((r) => <li key={r.address}><code>{r.address.slice(0, 10)}…</code> {r.total}</li>)}</ul>
          <a href={`https://tronscan.org/#/address/${address}`} target="_blank" rel="noreferrer">
            View on Tronscan ↗
          </a>
        </>
      )}
    </aside>
  );
}
