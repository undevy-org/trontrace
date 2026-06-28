from datetime import datetime, timezone
from app.analysis.expansion_signals import pay_cycle_fingerprint, aligns_with_cycle


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
