from app.analysis.consistency import ConsistentRow, consistent_rows, wallet_change_hints

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


def test_wallet_change_hint_flags_adjacent_equal_amount():
    rows = [ConsistentRow("A", 3000 * M, 5, 0.95), ConsistentRow("B", 3000 * M, 4, 0.95)]
    timelines = {
        "A": _series(1, [3000 * M] * 5),   # 2025-01..2025-05
        "B": _series(6, [3000 * M] * 4),   # 2025-06..2025-09  (adjacent, no overlap)
    }
    hints = wallet_change_hints(rows, timelines)
    assert [(h[0], h[1]) for h in hints] == [("A", "B")]


def test_no_hint_for_overlap_or_different_amount():
    rows = [ConsistentRow("A", 3000 * M, 5, 0.95), ConsistentRow("C", 9000 * M, 5, 0.95),
            ConsistentRow("D", 3000 * M, 5, 0.95)]
    timelines = {
        "A": _series(1, [3000 * M] * 5),    # 2025-01..05
        "C": _series(6, [9000 * M] * 5),    # adjacent but different amount -> no hint
        "D": _series(3, [3000 * M] * 5),    # same amount but overlaps A -> no hint
    }
    assert wallet_change_hints(rows, timelines) == []
