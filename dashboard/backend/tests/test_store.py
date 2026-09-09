"""Tests pour store.py (metriques long terme + journal + dedup d'alertes)."""
import time


def test_query_series_computes_deltas_not_raw_counters(wg_env, fresh_modules):
    """Regression : les compteurs `wg show` sont cumulatifs, query_series
    doit renvoyer un DEBIT par intervalle, pas la somme des compteurs bruts."""
    import store

    pubkey = "ALICEPUB0000000000000000000000000000000000="
    now = int(time.time())
    base_rx, base_tx = 1000, 500
    for i in range(10):
        ts = now - (10 - i) * 3600
        base_rx += 5_000_000
        base_tx += 2_000_000
        store.ingest_wg_dump(ts, f"{pubkey}\tpsk\t1.2.3.4:51820\t10.0.0.0/32\t{ts}\t{base_rx}\t{base_tx}\t25")

    series = store.query_series(pubkey, "24h")
    assert len(series) > 0
    # chaque bucket doit etre proche du delta reel (5 Mo), jamais la somme cumulative brute
    for bucket in series:
        assert bucket["rx"] < 10_000_000


def test_query_series_unknown_range_raises(wg_env, fresh_modules):
    import store
    import pytest

    with pytest.raises(ValueError):
        store.query_series(None, "3 ans")


def test_query_series_on_empty_db_returns_empty_list(wg_env, fresh_modules):
    """Regression : une base fraichement creee ne doit jamais faire planter
    une lecture (init_db() doit etre appele depuis les chemins de lecture)."""
    import store

    assert store.query_series(None, "1h") == []


def test_detect_traffic_spike(wg_env, fresh_modules):
    import store

    pubkey = "ALICEPUB0000000000000000000000000000000000="
    now = int(time.time())
    base_rx, base_tx = 0, 0
    for i in range(24):
        ts = now - (24 - i) * 3600
        base_rx += 200_000
        base_tx += 50_000
        store.ingest_wg_dump(ts, f"{pubkey}\tpsk\t1.2.3.4:51820\t10.0.0.0/32\t{ts}\t{base_rx}\t{base_tx}\t25")

    # injecte un pic massif sur le dernier point
    base_rx += 50_000_000
    store.ingest_wg_dump(now, f"{pubkey}\tpsk\t1.2.3.4:51820\t10.0.0.0/32\t{now}\t{base_rx}\t{base_tx}\t25")

    spike = store.detect_traffic_spike(pubkey, "24h", min_floor_bytes=100_000)
    assert spike is not None
    assert spike["last"] > spike["mean"]


def test_logs_pagination_and_filtering(wg_env, fresh_modules):
    import store

    pk1, pk2 = "ALICEPUB0000000000000000000000000000000000=", "BRUNOPUB0000000000000000000000000000000000="
    now = int(time.time())
    for i in range(15):
        ts = now - (15 - i) * 300
        store.ingest_log_snapshot(
            ts,
            f"{pk1}\tpsk\t1.2.3.4:51820\t10.0.0.5/32\t{ts}\t1000\t500\t25\n"
            f"{pk2}\tpsk\t9.9.9.9:51820\t10.0.0.6/32\t{ts}\t2000\t900\t25",
        )

    page = store.query_logs(limit=5, offset=0)
    assert page["total"] == 30
    assert len(page["rows"]) == 5

    by_pubkey = store.query_logs(limit=1000, pubkey=pk1)
    assert by_pubkey["total"] == 15
    assert all(r["pubkey"] == pk1 for r in by_pubkey["rows"])

    by_search = store.query_logs(limit=1000, search="9.9.9.9")
    assert by_search["total"] == 15

    chrono = store.query_logs_for_pubkey(pk1)
    assert chrono[0]["ts"] <= chrono[-1]["ts"]


def test_alert_dedup_cooldown(wg_env, fresh_modules):
    import store

    assert store.should_send("rule-a", cooldown_sec=3600) is True
    assert store.should_send("rule-a", cooldown_sec=3600) is False  # dans le cooldown

    now = int(time.time())
    assert store.should_send("rule-b", cooldown_sec=10, now=now) is True
    assert store.should_send("rule-b", cooldown_sec=10, now=now + 20) is True  # cooldown ecoule


def test_clear_alert_state_one_and_all(wg_env, fresh_modules):
    import store

    store.should_send("rule-a", 3600)
    store.should_send("rule-b", 3600)
    assert len(store.list_alert_state()) == 2

    deleted = store.clear_alert_state("rule-a")
    assert deleted == 1
    remaining = store.list_alert_state()
    assert len(remaining) == 1
    assert remaining[0]["rule_key"] == "rule-b"

    deleted_all = store.clear_alert_state(None)
    assert deleted_all == 1
    assert store.list_alert_state() == []
