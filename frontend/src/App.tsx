import { BrowserRouter, Routes, Route, Link, Navigate } from "react-router-dom";
import { Start } from "./pages/Start";
import { Overview } from "./pages/Overview";
import { MonthlyTable } from "./pages/MonthlyTable";
import { Graph } from "./pages/Graph";

export function App() {
  return (
    <BrowserRouter>
      <nav
        style={{
          display: "flex",
          gap: 16,
          padding: 12,
          borderBottom: "1px solid #eee",
          position: "sticky",
          top: 0,
          zIndex: 20,
          background: "#f4f4f4",
        }}
      >
        <strong>trontrace</strong>
        <Link to="/overview">Overview</Link>
        <Link to="/monthly">Monthly Table</Link>
        <Link to="/graph">Graph</Link>
      </nav>
      <main style={{ padding: 16 }}>
        <Routes>
          <Route path="/" element={<Start />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/monthly" element={<MonthlyTable />} />
          <Route path="/graph" element={<Graph />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
