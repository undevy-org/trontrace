from datetime import datetime, timezone
from app.analysis.expansion_signals import (
    pay_cycle_fingerprint, aligns_with_cycle,
    RecipientFeatures, recipient_score, tier,
    PayerFeatures, payer_score,
)
from app.config import settings


def _ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def test_fingerprint_finds_fixed_pay_days():
    ts = [_ts(2025, m, 1) for m in range(1, 7)] + [_ts(2025, m, 15) for m in range(1, 7)]
    ts += [_ts(2025, 3, 7)]  # one-off noise, should not be a peak
    fp = pay_cycle_fingerprint(ts)
    assert fp == {1, 15}


def test_aligns_within_tolerance():
    fp = {1, 15}
    assert aligns_with_cycle(_ts(2025, 4, 2), fp, tolerance_days=2) is True   # day 2 ~ peak 1
    assert aligns_with_cycle(_ts(2025, 4, 9), fp, tolerance_days=2) is False  # day 9, no peak


def test_recipient_score_high_for_recurring_lowfanin():
    # months_paid=12 -> recurrence=min(1.0,12/6)=1.0; still high
    f = RecipientFeatures(n_payers=2, months_paid=12,
                          aligned_fraction=1.0, amounts=[6000, 6000, 6000], distinct_senders=3)
    assert recipient_score(f) >= 0.8
    assert tier(recipient_score(f)) == "high"


def test_recipient_score_low_for_highfanin_oneoff():
    # months_paid=1 -> hard-gated below Med; also high fan-in
    f = RecipientFeatures(n_payers=1, months_paid=1,
                          aligned_fraction=0.0, amounts=[2_000_000], distinct_senders=400)
    assert recipient_score(f) < 0.45
    assert tier(recipient_score(f)) == "low"


def test_payer_score_high_when_overlaps_cohort_on_cycle():
    f = PayerFeatures(overlap_with_cohort=0.9, n_known_recipients_paid=3,
                      aligned_fraction=1.0, is_exchange=False)
    assert payer_score(f) >= 0.7


def test_payer_score_zero_below_corroboration_or_exchange():
    below_k = PayerFeatures(overlap_with_cohort=1.0, n_known_recipients_paid=1,
                            aligned_fraction=1.0, is_exchange=False)
    exch = PayerFeatures(overlap_with_cohort=1.0, n_known_recipients_paid=5,
                         aligned_fraction=1.0, is_exchange=True)
    assert payer_score(below_k) == 0.0   # K defaults to 2
    assert payer_score(exch) == 0.0


# --- Regression guard: single-month recipient must be hard-gated below Med ---
def test_single_month_recipient_clamped_below_med_despite_strong_signals():
    """Bug regression: a one-off payment must NOT reach Med/High tier.

    Even with strong corroboration signals (3 payers, on pay-cycle, stable amount,
    low fan-in), months_paid=1 must force the score below expand_tier_med.
    """
    f = RecipientFeatures(
        n_payers=3,          # max co-recipient signal
        months_paid=1,       # the bug: single month → was scoring 1.0 recurrence
        aligned_fraction=1.0,  # perfectly on pay-cycle
        amounts=[6000, 6000, 6000],  # perfectly stable
        distinct_senders=3,  # low fan-in → fanin=1.0
    )
    score = recipient_score(f)
    assert score < settings.expand_tier_med, (
        f"Single-month recipient scored {score:.4f} >= med threshold "
        f"{settings.expand_tier_med} — recurrence hard-gate is broken"
    )
    assert tier(score) == "low"


# --- Genuine multi-month recipient must NOT be clamped ---
def test_multi_month_recipient_not_clamped():
    """A recipient paid across recurrence_min_months distinct months must be eligible
    for Med/High — the hard-gate must only apply to single-month (non-recurring) cases.
    """
    f = RecipientFeatures(
        n_payers=2,
        months_paid=settings.recurrence_min_months,  # exactly at the gate
        aligned_fraction=1.0,
        amounts=[6000, 6000, 6000],
        distinct_senders=3,
    )
    score = recipient_score(f)
    # Must be allowed to reach Med (gate not applied); score won't be clamped
    assert score >= settings.expand_tier_med, (
        f"Multi-month recipient (months_paid={settings.recurrence_min_months}) scored "
        f"{score:.4f} < med threshold {settings.expand_tier_med} — gate is over-restrictive"
    )


def test_amount_consistency_identical_and_variable():
    from app.analysis.expansion_signals import amount_consistency
    assert amount_consistency([6000, 6000, 6000]) >= 0.99   # identical -> ~1
    assert amount_consistency([1000, 11000, 1000, 11000]) < 0.5   # high variance -> low
    assert amount_consistency([6000]) == 0.0                # <2 points -> 0


def test_consistent_amount_outranks_variable():
    from app.analysis.expansion_signals import amount_consistency
    base = dict(n_payers=2, months_paid=12, aligned_fraction=1.0, distinct_senders=3)
    steady = RecipientFeatures(amounts=[6000] * 12, **base)
    variable = RecipientFeatures(amounts=[1000, 11000] * 6, **base)   # same mean, high variance
    assert recipient_score(steady) > recipient_score(variable)
    assert tier(recipient_score(steady)) == "high"
