"""Tests pour wgstate.py (lecture wg0.conf / wg show, sans Flask)."""
from conftest import add_peer


def test_load_peer_config_parses_enabled_and_disabled_blocks(wg_env, fresh_modules):
    import wgstate

    add_peer(wg_env["wg_conf"], "alice", "ALICEPUB0000000000000000000000000000000000=", "10.66.66.5/32", enabled=True)
    add_peer(wg_env["wg_conf"], "bob", "BOBPUB00000000000000000000000000000000000=", "10.66.66.6/32", enabled=False)

    config = wgstate.load_peer_config()
    assert len(config) == 2
    alice = next(v for v in config.values() if v["name"] == "alice")
    bob = next(v for v in config.values() if v["name"] == "bob")
    assert alice["enabled"] is True
    assert bob["enabled"] is False
    assert alice["allowed_ips"] == "10.66.66.5/32"


def test_load_live_peers_merges_config_with_wg_show(wg_env, fresh_modules):
    import wgstate

    add_peer(wg_env["wg_conf"], "alice", "ALICEPUB0000000000000000000000000000000000=", "10.66.66.5/32")

    # remplace le faux `wg` pour renvoyer un handshake recent pour alice
    fake_wg = wg_env["bin_dir"] / "wg"
    fake_wg.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = \"show\" ]; then\n"
        "  echo wg0\n"
        "  echo -e \"ALICEPUB0000000000000000000000000000000000=\\tpsk\\t1.2.3.4:51820\\t10.66.66.5/32\\t$(date +%s)\\t1000\\t2000\\t25\"\n"
        "fi\n"
    )
    fake_wg.chmod(0o755)

    peers = wgstate.load_live_peers(online_threshold_sec=180)
    assert len(peers) == 1
    assert peers[0]["name"] == "alice"
    assert peers[0]["status"] == "online"
    assert peers[0]["rx_bytes"] == 1000
    assert peers[0]["endpoint"] == "1.2.3.4:51820"


def test_disabled_peer_has_no_live_data_and_status_disabled(wg_env, fresh_modules):
    import wgstate

    add_peer(wg_env["wg_conf"], "bob", "BOBPUB00000000000000000000000000000000000=", "10.66.66.6/32", enabled=False)

    peers = wgstate.load_live_peers()
    assert len(peers) == 1
    assert peers[0]["status"] == "disabled"
    assert peers[0]["enabled"] is False


def test_build_reconnect_stats_counts_endpoint_changes(wg_env, fresh_modules):
    import wgstate

    rows = [
        {"ts": 1000, "endpoint": "1.1.1.1:51820"},
        {"ts": 1300, "endpoint": "1.1.1.1:51820"},  # meme endpoint, pas de nouvelle session
        {"ts": 1600, "endpoint": "2.2.2.2:51820"},  # endpoint different -> nouvelle session
        {"ts": 5000, "endpoint": "2.2.2.2:51820"},  # ecart > 600s -> nouvelle session
    ]
    stats = wgstate.build_reconnect_stats(rows)
    assert stats["reconnect_count"] == 2
    assert stats["last_endpoint"] == "2.2.2.2:51820"


def test_build_reconnect_stats_empty_input():
    import wgstate

    stats = wgstate.build_reconnect_stats([])
    assert stats == {"reconnect_count": 0, "last_endpoint": None}
