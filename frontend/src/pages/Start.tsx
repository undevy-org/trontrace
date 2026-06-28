import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, Status } from "../api";

// Screen 1 — Start / Analysis: anchor input + live progress.
export function Start() {
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [running, setRunning] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const navigate = useNavigate();

  const valid = /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(address);

  useEffect(() => () => window.clearInterval(timer.current), []);

  async function start() {
    const res = await api.analyze(address);
    if (!res.ok) return;
    setRunning(true);
    timer.current = window.setInterval(async () => {
      const s = await api.status();
      setStatus(s);
      if (s.phase === "done") {
        window.clearInterval(timer.current);
        setRunning(false);
        navigate("/overview");
      }
    }, 1500);
  }

  return (
    <section>
      <h1>Trace a wallet</h1>
      <p>Enter an anchor TRON address to start the analysis.</p>
      <input
        placeholder="T..."
        value={address}
        onChange={(e) => setAddress(e.target.value.trim())}
        disabled={running}
        style={{ width: 380, padding: 8 }}
      />
      <button disabled={!valid || running} onClick={start} style={{ marginLeft: 8 }}>
        {running ? "Analyzing…" : "Start analysis"}
      </button>
      {address && !valid && <p style={{ color: "crimson" }}>Not a valid TRON address.</p>}
      {status && (
        <div style={{ marginTop: 16, maxWidth: 420 }}>
          <div>
            Phase: <strong>{status.phase}</strong> — {status.percent}%
          </div>
          <div style={{ background: "#eee", height: 8, borderRadius: 4, marginTop: 4 }}>
            <div
              style={{
                width: `${status.percent}%`,
                height: 8,
                borderRadius: 4,
                background: "#4caf50",
                transition: "width .3s",
              }}
            />
          </div>
        </div>
      )}
    </section>
  );
}
