import { useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";
import { api } from "../api";
import { WalletDetail } from "../components/WalletDetail";

// Screen 4 — Connection Graph (Cytoscape.js).
const ROLE_COLORS: Record<string, string> = {
  anchor: "#1565c0",        // blue
  primary_payer: "#2e7d32", // green
  counterparty: "#f9a825",  // yellow
  noise: "#9e9e9e",         // gray
  exchange: "#c62828",      // red
};

export function Graph() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [month, setMonth] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let cy: cytoscape.Core | undefined;
    api.graph(month || undefined).then((g) => {
      if (!ref.current) return;
      const weights = g.edges.map((e) => parseFloat(e.weight) || 0);
      const maxW = Math.max(1, ...weights);
      cy = cytoscape({
        container: ref.current,
        elements: [
          ...g.nodes.map((n) => ({ data: { id: n.id, role: n.role } })),
          ...g.edges.map((e) => ({
            data: { id: `${e.source}->${e.target}`, source: e.source, target: e.target, w: parseFloat(e.weight) || 0 },
          })),
        ],
        style: [
          {
            selector: "node",
            style: {
              "background-color": (n: cytoscape.NodeSingular) => ROLE_COLORS[n.data("role")] ?? "#777",
              label: (n: cytoscape.NodeSingular) => (n.data("id") as string).slice(0, 6),
              "font-size": 8,
            },
          },
          {
            selector: "edge",
            style: {
              width: (e: cytoscape.EdgeSingular) => 1 + (5 * (e.data("w") as number)) / maxW,
              "line-color": "#cfd8dc",
              "curve-style": "bezier",
              "target-arrow-shape": "triangle",
              "target-arrow-color": "#cfd8dc",
            },
          },
        ],
        layout: { name: "cose", animate: false },
      });
      cy.on("tap", "node", (evt) => setSelected(evt.target.data("id")));
    });
    return () => cy?.destroy();
  }, [month]);

  return (
    <section>
      <h1>Connection Graph</h1>
      <input placeholder="Filter month YYYY-MM" value={month} onChange={(e) => setMonth(e.target.value)} />
      <div style={{ marginTop: 8, fontSize: 12 }}>
        {Object.entries(ROLE_COLORS).map(([role, color]) => (
          <span key={role} style={{ marginRight: 12 }}>
            <span style={{ display: "inline-block", width: 10, height: 10, background: color, borderRadius: 5, marginRight: 4 }} />
            {role}
          </span>
        ))}
      </div>
      <div ref={ref} style={{ height: 600, border: "1px solid #eee", marginTop: 8 }} />
      {selected && <WalletDetail address={selected} onClose={() => setSelected(null)} />}
    </section>
  );
}
