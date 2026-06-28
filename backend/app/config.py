"""Central configuration.

All tunables live here and are overridable via environment variables / .env, so the
heuristics can be adjusted without touching code. Defaults match the design spec.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo-root .env (config.py is backend/app/config.py -> parents[2] is the repo root).
# In Docker the vars arrive via the environment, so a missing file here is harmless.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # --- TronGrid ---
    trongrid_api_key: str = ""
    trongrid_base_url: str = "https://api.trongrid.io"
    trongrid_max_rps: float = 12.0          # free keys cap at 15 rps; stay below
    trongrid_timeout_s: float = 30.0
    trongrid_max_retries: int = 3

    # --- Token under analysis (default: USDT TRC-20) ---
    token_symbol: str = "USDT"
    token_contract: str = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
    token_decimals: int = 6                 # USDT TRC-20 uses 6 decimals

    # --- Fetch caps (also act as exchange-detection signals) ---
    candidate_tx_cap: int = 5000            # stop + flag exchange past this many txs
    fanout_cap: int = 2000                  # distinct-recipient ceiling for non-exchange (sender-side)
    funding_fetch_cap: int = 1000           # max inbound txs fetched per candidate
    recipient_fanin_cap: int = 50           # distinct-sender ceiling for a real counterparty (recipient-side gate, v1.1)
    paycycle_tolerance_days: int = 2         # ±days around a pay-date peak

    # --- Clustering ---
    # recipient-side exchange gate (v1.1, opt-in): fetch each counterparty's inbound and flag
    # high-fan-in recipients as exchange/processor. Off by default (extra network cost).
    recipient_gate: bool = False
    recipient_gate_max_checks: int = 200     # bound live fan-in fetches per run
    recipient_inbound_cap: int = 3000        # max inbound txs fetched per counterparty

    score_threshold: float = 0.55           # average-linkage merge cutoff (tau)
    weight_overlap: float = 0.50            # base signal
    weight_rhythm: float = 0.30             # base signal
    weight_funding: float = 0.20            # positive-only bonus (absence never penalizes)
    employer_window_days: int = 180         # recent window for primary-payer selection

    # --- Recipient scoring (v1.1 expansion, pure) ---
    expand_tier_high: float = 0.70
    expand_tier_med: float = 0.45
    corecipient_min_k: int = 2              # min known recipients a payer must co-pay (K)
    recurrence_target_months: int = 6       # months_paid at/above this -> full recurrence credit
    recurrence_min_months: int = 2          # below this, recipient is not "recurring" (hard gate)
    # recipient score weights (sum 1.0)
    w_rec_corecipient: float = 0.35
    w_rec_recurrence: float = 0.25
    w_rec_paycycle: float = 0.20
    w_rec_stability: float = 0.10
    w_rec_fanin: float = 0.10

    # --- Payer scoring (v1.1 expansion, pure) ---
    # payer score weights (sum 1.0)
    w_pay_overlap: float = 0.50
    w_pay_paycycle: float = 0.25
    w_pay_corroboration: float = 0.25

    # --- Expansion BFS caps ---
    expand_max_rounds: int = 6
    expand_max_payers: int = 200
    expand_max_recipients: int = 5000
    expand_max_total_fetches: int = 4000

    # --- Server / storage ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    db_path: str = "data/trontrace.db"


settings = Settings()
