from app.analysis.monthly import (
    Transfer,
    aggregate_monthly,
    raw_to_decimal_str,
    year_month_utc,
)


def test_year_month_utc_boundary():
    # 2026-01-31 23:59:59 UTC stays in January.
    assert year_month_utc(1769903999) == "2026-01"


def test_aggregate_sums_are_exact_integers():
    transfers = [
        Transfer("cp1", 1_500_000, 1769900000),
        Transfer("cp1", 2_500_000, 1769900100),  # same month
        Transfer("cp2", 1_000_000, 1769900200),
    ]
    cells = {(c.counterparty_address, c.year_month): c for c in aggregate_monthly(transfers)}
    assert cells[("cp1", "2026-01")].total_raw == 4_000_000
    assert cells[("cp1", "2026-01")].tx_count == 2


def test_raw_to_decimal_no_float_error():
    assert raw_to_decimal_str(4_000_000, 6) == "4"
    assert raw_to_decimal_str(1_500_000, 6) == "1.5"
    assert raw_to_decimal_str(1, 6) == "0.000001"
