from datetime import datetime, timezone
from app.analysis.expansion_signals import (
    pay_cycle_fingerprint, aligns_with_cycle,
    RecipientFeatures, recipient_score, tier,
)


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
    f = RecipientFeatures(n_payers=2, months_paid=12, months_span=12,
                          aligned_fraction=1.0, amounts=[6000, 6000, 6000], distinct_senders=3)
    assert recipient_score(f) >= 0.8
    assert tier(recipient_score(f)) == "high"


def test_recipient_score_low_for_highfanin_oneoff():
    f = RecipientFeatures(n_payers=1, months_paid=1, months_span=12,
                          aligned_fraction=0.0, amounts=[2_000_000], distinct_senders=400)
    assert recipient_score(f) < 0.45
    assert tier(recipient_score(f)) == "low"
