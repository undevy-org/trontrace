from app.analysis.similarity import (
    WalletContext,
    overlap_coefficient,
    pair_score,
    recipient_overlap,
)


def test_funding_absence_does_not_penalize():
    # Identical recipients + identical rhythm, but no shared funding. Funding is a positive-only
    # bonus, so the score must stay near 1.0 (not be dragged down by absent funding).
    a = WalletContext("A", recipients={"x", "y", "z"},
                      outbound_timestamps=[0, 100], outbound_amounts=[10, 10])
    b = WalletContext("B", recipients={"x", "y", "z"},
                      outbound_timestamps=[0, 100], outbound_amounts=[10, 10])
    assert pair_score(a, b) >= 0.95


def test_overlap_coefficient_handles_asymmetry():
    # Rotation case: a fresh wallet (5 recipients, subset) vs an old one (100 recipients).
    small = {f"r{i}" for i in range(5)}
    big = {f"r{i}" for i in range(100)}
    # Jaccard would be 5/100 = 0.05; overlap coefficient correctly reports full containment.
    assert overlap_coefficient(small, big) == 1.0


def test_overlap_empty_is_zero():
    assert overlap_coefficient(set(), {"a"}) == 0.0


def test_recipient_overlap_partial():
    a = WalletContext("A", recipients={"x", "y", "z"})
    b = WalletContext("B", recipients={"y", "z", "w"})
    # |{y,z}| / min(3,3) = 2/3
    assert abs(recipient_overlap(a, b) - 2 / 3) < 1e-9
