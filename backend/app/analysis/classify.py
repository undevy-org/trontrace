"""Exchange / custodial hot-wallet gate.

This runs *before* clustering and is the single most important correctness mechanism: a CEX
hot wallet that slips through would fuse strangers into the primary-payer cluster.

A candidate is flagged `exchange` if ANY of:
  1. static blocklist hit (app/data/known_exchanges.json),
  2. cap-hit: outbound pagination exceeded CANDIDATE_TX_CAP before exhaustion,
  3. fan-out: distinct recipient count exceeded FANOUT_CAP.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..config import settings

_BLOCKLIST_PATH = Path(__file__).resolve().parent.parent / "data" / "known_exchanges.json"


@lru_cache(maxsize=1)
def known_exchanges() -> set[str]:
    try:
        data = json.loads(_BLOCKLIST_PATH.read_text())
        return {entry["address"] for entry in data.get("exchanges", [])}
    except FileNotFoundError:
        return set()


def is_exchange(
    address: str,
    *,
    distinct_recipients: int,
    tx_cap_hit: bool,
) -> bool:
    """Return True if the wallet should be excluded as exchange/custodial."""
    if address in known_exchanges():
        return True
    if tx_cap_hit:  # exceeded CANDIDATE_TX_CAP before pagination exhausted
        return True
    if distinct_recipients > settings.fanout_cap:
        return True
    return False
