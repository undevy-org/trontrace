"""TronGrid API client: paginated, rate-limited, retrying.

TRC-20 transfers endpoint (account-based):

    GET {base}/v1/accounts/{address}/transactions/trc20
        ?contract_address={token_contract}
        &only_to=true | &only_from=true
        &limit=200
        &fingerprint={cursor}      # from previous response's meta.fingerprint

Auth header: TRON-PRO-API-KEY: {api_key}
Free keys cap at 15 requests/second — the RateLimiter keeps us below trongrid_max_rps.

Normalization gotchas (handled in normalize_transfer):
  - `block_timestamp` is MILLISECONDS -> store unix seconds.
  - `value` is a base-unit string -> store int `amount_raw`, never float.
  - pagination cursor lives in `meta.fingerprint`.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

from .config import settings

# SQLite INTEGER is signed 64-bit. Base-unit amounts above this cannot be stored and are
# provably fake for real tokens (e.g. spam USDT transfers carrying value = 2**256-1), so they
# are dropped at ingestion. Token-agnostic: tied to the storage type, not to USDT specifics.
INT64_MAX = 2**63 - 1


@dataclass
class TransferRecord:
    tx_hash: str
    from_address: str
    to_address: str
    amount_raw: int          # base units (token decimals)
    timestamp: int           # unix seconds, UTC
    token: str


@dataclass
class FetchResult:
    records: list[TransferRecord] = field(default_factory=list)
    cap_hit: bool = False               # True if max_records hit while more pages remained
    last_fingerprint: str | None = None  # cursor to resume from (None when exhausted)
    skipped_oversized: int = 0          # spam/spoof transfers dropped (value > INT64_MAX)


def normalize_transfer(rec: dict) -> TransferRecord:
    """Map one raw TronGrid TRC-20 record to a TransferRecord (ms->s, str->int)."""
    return TransferRecord(
        tx_hash=rec["transaction_id"],
        from_address=rec["from"],
        to_address=rec["to"],
        amount_raw=int(rec["value"]),
        timestamp=int(rec["block_timestamp"]) // 1000,
        token=(rec.get("token_info") or {}).get("symbol") or settings.token_symbol,
    )


class RateLimiter:
    """Async token bucket. `now`/`sleep` are injectable for deterministic testing."""

    def __init__(
        self,
        rps: float,
        *,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._now = now or (lambda: asyncio.get_event_loop().time())
        self._sleep = sleep or asyncio.sleep
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def wait(self) -> None:
        async with self._lock:
            t = self._now()
            if self._last is None:
                self._last = t
                return
            elapsed = t - self._last
            if elapsed < self._min_interval:
                await self._sleep(self._min_interval - elapsed)
                self._last = self._last + self._min_interval
            else:
                self._last = t


class TronGridClient:
    def __init__(
        self,
        *,
        rps: float | None = None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int | None = None,
        backoff_base: float = 0.5,
    ) -> None:
        self._limiter = RateLimiter(rps if rps is not None else settings.trongrid_max_rps)
        self._transport = transport
        self._max_retries = max_retries if max_retries is not None else settings.trongrid_max_retries
        self._backoff_base = backoff_base
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "TronGridClient":
        self._client = httpx.AsyncClient(
            base_url=settings.trongrid_base_url,
            headers={"TRON-PRO-API-KEY": settings.trongrid_api_key},
            timeout=settings.trongrid_timeout_s,
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def fetch_transfers(
        self,
        address: str,
        *,
        direction: str,                       # 'in' | 'out'
        max_records: int | None = None,
        start_fingerprint: str | None = None,
    ) -> FetchResult:
        """Paginate TRC-20 transfers for `address`, honoring caps and rate limits."""
        if direction not in ("in", "out"):
            raise ValueError("direction must be 'in' or 'out'")

        params: dict[str, object] = {
            "limit": 200,
            "contract_address": settings.token_contract,
            ("only_to" if direction == "in" else "only_from"): "true",
        }

        result = FetchResult()
        fingerprint = start_fingerprint
        while True:
            if fingerprint:
                params["fingerprint"] = fingerprint
            else:
                params.pop("fingerprint", None)

            payload = await self._get_page(address, params)
            for raw in payload.get("data", []):
                rec = normalize_transfer(raw)
                if rec.amount_raw > INT64_MAX or rec.amount_raw < 0:
                    result.skipped_oversized += 1
                    continue
                result.records.append(rec)
            fingerprint = (payload.get("meta") or {}).get("fingerprint")

            if max_records is not None and len(result.records) >= max_records:
                result.cap_hit = fingerprint is not None
                result.records = result.records[:max_records]
                result.last_fingerprint = fingerprint
                return result

            if not fingerprint:
                result.last_fingerprint = None
                return result

    async def _get_page(self, address: str, params: dict) -> dict:
        assert self._client is not None, "use 'async with TronGridClient() as c'"
        path = f"/v1/accounts/{address}/transactions/trc20"
        for attempt in range(self._max_retries + 1):
            await self._limiter.wait()
            resp = await self._client.get(path, params=params)
            if resp.status_code == 200:
                return resp.json()
            retriable = resp.status_code == 429 or 500 <= resp.status_code < 600
            if retriable and attempt < self._max_retries:
                await asyncio.sleep(self._backoff_base * (2 ** attempt))
                continue
            resp.raise_for_status()
        raise RuntimeError("unreachable")  # pragma: no cover
