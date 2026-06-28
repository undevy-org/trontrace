// Typed client for the trontrace backend.
const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export interface Status {
  phase: string;
  percent: number;
}

export interface Overview {
  anchor: string;
  primary_payer: { wallets: { address: string; confidence: number }[]; confidence: number };
  totals: { received: string; monthly_avg: string };
  counterparty_count: number;
  exchanges: string[];
  noise: string[];
}

export interface MonthlyRow {
  address: string;
  role: string;
  cells: Record<string, string>;
  total: string;
}
export interface Monthly {
  months: string[];
  rows: MonthlyRow[];
}

export interface GraphData {
  nodes: { id: string; role: string }[];
  edges: { source: string; target: string; weight: string }[];
}

export interface WalletDetail {
  address: string;
  role: string | null;
  confidence: number | null;
  first_seen: number | null;
  last_seen: number | null;
  top_recipients: { address: string; total: string }[];
  top_senders: { address: string; total: string }[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}/api${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  analyze: (address: string) =>
    fetch(`${BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ address }),
    }),
  status: () => get<Status>("/status"),
  overview: () => get<Overview>("/overview"),
  monthly: (from?: string, to?: string) =>
    get<Monthly>(`/monthly?from_=${from ?? ""}&to=${to ?? ""}`),
  graph: (month?: string) => get<GraphData>(`/graph?month=${month ?? ""}`),
  wallet: (address: string) => get<WalletDetail>(`/wallet/${address}`),
  csvUrl: () => `${BASE}/api/export/csv`,
};
