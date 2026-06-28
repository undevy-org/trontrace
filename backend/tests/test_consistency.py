from app.analysis.consistency import ConsistentRow, consistent_rows

M = 1_000_000  # 1 USDT in base units


def _series(start_month, amounts):
    return [(f"2025-{start_month + i:02d}", a) for i, a in enumerate(amounts)]


def test_consistent_rows_filters_and_sorts():
    timelines = {
        "STEADY": _series(1, [3000 * M] * 6),                 # consistent, in band -> keep
        "BIG":    _series(1, [50000 * M] * 6),                # above band -> drop
        "ONEOFF": _series(1, [3000 * M]),                     # < min_months -> drop
        "NOISY":  _series(1, [1000 * M, 11000 * M] * 3),      # low consistency -> drop
        "SMALL":  _series(1, [2000 * M] * 6),                 # consistent, in band -> keep
    }
    rows = consistent_rows(timelines, band_low=500 * M, band_high=12000 * M,
                           min_consistency=0.80, min_months=4)
    assert [r.address for r in rows] == ["STEADY", "SMALL"]   # sorted by amount desc
    assert rows[0].median_monthly == 3000 * M
    assert rows[0].months_paid == 6
    assert rows[0].consistency >= 0.99
