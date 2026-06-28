"""Iterative bipartite expansion engine (payers <-> recurring recipients).

Seeds from the base pipeline's entity wallets, then alternates:
  payee step  — score each payer's recipients, add cohort members
  payer step  — score each recipient's senders, discover new entity wallets
Loops until no High/Med node is added (loop-until-dry) or caps are hit.
"""
from __future__ import annotations

from . import store
from .analysis import expansion_signals as sig
from .analysis.classify import is_exchange_recipient
from .analysis.monthly import Transfer, aggregate_monthly, year_month_utc
from .config import settings
from .trongrid import TronGridClient


async def run_expansion(
    anchor: str, client: TronGridClient, seed_payers: set[str] | None = None
) -> None:
    store.set_progress(anchor=anchor, phase="expand", percent=0)
    payers: set[str] = set(seed_payers if seed_payers is not None
                           else store.get_wallets_by_role("primary_payer"))
    cohort: set[str] = {anchor}
    payer_frontier = set(payers)
    recipient_frontier: set[str] = set()
    rounds = 0
    fetches = 0  # hard budget: counts every TronGrid fetch across all steps

    while (payer_frontier or recipient_frontier) and rounds < settings.expand_max_rounds:
        if fetches >= settings.expand_max_total_fetches:
            break
        rounds += 1

        # --- payee step: payers -> candidate recipients ---
        new_recipients: set[str] = set()
        for w in list(payer_frontier):
            res = await client.fetch_transfers(w, direction="out",
                                               max_records=settings.candidate_tx_cap)
            fetches += 1
            store.insert_transactions(res.records)
        payer_frontier.clear()

        fingerprint = _fingerprint(payers, anchor)
        # Subtract `payers`: a known payer that receives from another payer (payer-to-payer
        # transit) must not be scored as a recipient — that would overwrite its payer node.
        candidates = _recipients_of(payers) - cohort - payers - {anchor}
        # Fetch each candidate's inbound to compute its fan-in (distinct_senders); this both
        # feeds the exchange gate and is reused as the recipient's inbound for the payer step.
        for cand in candidates:
            if fetches >= settings.expand_max_total_fetches:
                break
            res = await client.fetch_transfers(cand, direction="in",
                                               max_records=settings.recipient_inbound_cap)
            fetches += 1
            store.insert_transactions(res.records)
        for cand in candidates:
            feats, _ = _recipient_features(cand, payers, fingerprint, client_cache=None)
            # Hard exchange gate: a high-fan-in recipient is a custodial hub, not a genuine
            # counterparty. Skip entirely — never persisted, never enters the cohort.
            if is_exchange_recipient(cand, distinct_senders=feats.distinct_senders):
                continue
            conf = sig.recipient_score(feats)
            t = sig.tier(conf)
            # Persist every genuine (non-exchange) recipient at its actual tier; nothing is
            # hard-dropped from the ranked output. Only high/med expand the frontier.
            _persist_recipient(cand, conf, t, feats)
            # Budget: stop growing the cohort/frontier once the recipient cap is reached.
            if t in ("high", "med") and len(cohort) < settings.expand_max_recipients:
                cohort.add(cand)
                new_recipients.add(cand)
        recipient_frontier = new_recipients

        # --- payer step: recipients -> candidate payers ---
        # New recipients' inbound was already fetched above (idempotent INSERT OR IGNORE), so
        # no re-fetch is needed here before scoring senders as candidate payers.
        new_payers: set[str] = set()
        fingerprint = _fingerprint(payers, anchor)
        for cand in _senders_to(cohort) - payers - {anchor}:
            feats = _payer_features(cand, cohort, fingerprint)
            conf = sig.payer_score(feats)
            t = sig.tier(conf)
            if conf > 0:
                store.upsert_entity_node(cand, kind="payer", confidence=conf, tier=t,
                                         discovered_round=rounds)
            if t in ("high", "med") and len(payers) < settings.expand_max_payers:
                payers.add(cand)
                new_payers.add(cand)
        payer_frontier = new_payers

    _write_cohort_timelines(payers, cohort, anchor)
    store.set_progress(phase="done", percent=100)


def _recipients_of(payers: set[str]) -> set[str]:
    out: set[str] = set()
    for w in payers:
        out |= store.get_recipients(w)
    return out


def _senders_to(cohort: set[str]) -> set[str]:
    out: set[str] = set()
    for r in cohort:
        out |= store.get_funding_sources(r)
    return out


def _fingerprint(payers: set[str], anchor: str) -> set[int]:
    ts: list[int] = []
    for _to, _amt, t in store.outbound_transfers(payers):
        ts.append(t)
    return sig.pay_cycle_fingerprint(ts)


def _recipient_features(addr, payers, fingerprint, client_cache):
    rows = [(f, a, t) for (f, a, t) in _inbound_rows(addr)]
    senders = {f for f, _a, _t in rows}
    from_payers = [(a, t) for f, a, t in rows if f in payers]
    n_payers = len({f for f, _a, _t in rows if f in payers})
    months = {year_month_utc(t) for _a, t in from_payers}
    aligned = ([sig.aligns_with_cycle(t, fingerprint, settings.paycycle_tolerance_days)
                for _a, t in from_payers])
    aligned_fraction = (sum(aligned) / len(aligned)) if aligned else 0.0
    feats = sig.RecipientFeatures(
        n_payers=n_payers, months_paid=len(months),
        aligned_fraction=aligned_fraction, amounts=[a for a, _t in from_payers],
        distinct_senders=len(senders))
    return feats, rows


def _payer_features(addr, cohort, fingerprint):
    recips = store.get_recipients(addr)
    paid_known = recips & cohort
    overlap = (len(paid_known) / min(len(recips), len(cohort))) if recips and cohort else 0.0
    out_ts = [t for _to, _a, t in store.outbound_transfers({addr})]
    aligned = [sig.aligns_with_cycle(t, fingerprint, settings.paycycle_tolerance_days)
               for t in out_ts]
    aligned_fraction = (sum(aligned) / len(aligned)) if aligned else 0.0
    is_exch = is_exchange_recipient(addr, distinct_senders=len(store.get_funding_sources(addr)))
    return sig.PayerFeatures(overlap_with_cohort=overlap,
                             n_known_recipients_paid=len(paid_known),
                             aligned_fraction=aligned_fraction, is_exchange=is_exch)


def _inbound_rows(addr):
    return store.get_inbound_rows(addr)


def _persist_recipient(addr, conf, t, feats):
    store.upsert_entity_node(addr, kind="recipient", confidence=conf, tier=t,
                             months_active=feats.months_paid, n_payers=feats.n_payers,
                             total_raw=sum(feats.amounts))


def _write_cohort_timelines(payers, cohort, anchor):
    transfers = [Transfer(to, amt, ts)
                 for (to, amt, ts) in store.outbound_transfers(payers)
                 if to in cohort]
    store.write_monthly_stats(aggregate_monthly(transfers))
