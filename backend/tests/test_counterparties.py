from app.analysis.counterparties import derive_counterparties


def test_excludes_anchor_and_exchanges():
    cps, needs = derive_counterparties(
        {"C1", "C2", "EX", "ANCHOR"}, anchor="ANCHOR", exchange_addresses={"EX"}
    )
    assert cps == {"C1", "C2"}
    assert needs == {"EX"}


def test_excludes_primary_payer_members_themselves():
    # A primary-payer wallet that self-transfers must not appear as its own counterparty.
    cps, _ = derive_counterparties(
        {"C1", "C2", "PAYER"}, anchor="ANCHOR", exchange_addresses=set(), payers={"PAYER"}
    )
    assert cps == {"C1", "C2"}
