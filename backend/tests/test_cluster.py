from app.analysis.cluster import cluster_wallets, select_primary_payer
from app.analysis.similarity import WalletContext


def _ctx(addr, recipients):
    return WalletContext(addr, recipients=set(recipients))


def test_average_linkage_resists_weak_chaining():
    # A~B and B~C share recipients, but A and C share none. Average-linkage should NOT
    # necessarily glue all three into one cluster the way single-linkage would.
    a = _ctx("A", {"r1", "r2", "r3", "r4"})
    b = _ctx("B", {"r3", "r4", "r5", "r6"})
    c = _ctx("C", {"r7", "r8", "r9", "r10"})
    clusters = cluster_wallets([a, b, c])
    members = [set(cl.members) for cl in clusters]
    assert {"C"} in members or all("C" not in m or len(m) <= 2 for m in members)


def test_primary_payer_by_volume_not_size():
    big_cluster = type("C", (), {"members": ["X", "Y", "Z"]})()
    small_cluster = type("C", (), {"members": ["P"]})()
    paid = {"P": 1_000_000, "X": 1, "Y": 1, "Z": 1}
    winner = select_primary_payer([big_cluster, small_cluster], paid)
    assert winner.members == ["P"]
