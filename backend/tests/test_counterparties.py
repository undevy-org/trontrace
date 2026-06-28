from app.analysis.classify import is_exchange_recipient
from app.analysis.counterparties import derive_counterparties


def test_recipient_fanin_gate_flags_high_fanin():
    # Empirically: private wallets <20 senders, exchange recipients 150-700+. Cap defaults to 50.
    assert is_exchange_recipient("Tprivate", distinct_senders=12) is False
    assert is_exchange_recipient("Thub", distinct_senders=360) is True
    # explicit cap override
    assert is_exchange_recipient("Tx", distinct_senders=30, cap=20) is True


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
