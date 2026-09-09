"""Tests pour alerts.py (config masquee, evaluation des regles)."""


def test_mask_config_hides_secrets(wg_env, fresh_modules):
    import alerts

    cfg = alerts.load_config()
    cfg["channels"]["slack_webhook_url"] = "https://hooks.slack.com/super-secret"
    alerts.save_config(cfg)

    masked = alerts.mask_config(alerts.load_config())
    assert masked["channels"]["slack_webhook_url"] == alerts.MASK


def test_save_config_preserves_secret_when_mask_sent_back(wg_env, fresh_modules):
    import alerts

    alerts.save_config({"channels": {"slack_webhook_url": "https://hooks.slack.com/real-secret"}})

    # Le frontend renvoie le MASK tel quel s'il n'a pas touche au champ
    result = alerts.save_config({"channels": {"slack_webhook_url": alerts.MASK}, "rules": {"inactive_days": 3}})
    assert result["channels"]["slack_webhook_url"] == "https://hooks.slack.com/real-secret"
    assert result["rules"]["inactive_days"] == 3


def test_evaluate_rules_disabled_by_default(wg_env, fresh_modules):
    import alerts

    result = alerts.evaluate_rules()
    assert result["checked"] is False


def test_evaluate_rules_inactive_client_triggers_and_dedups(wg_env, fresh_modules):
    from conftest import add_peer
    import alerts

    add_peer(wg_env["wg_conf"], "never-connected", "NEVERPUB000000000000000000000000000000000=", "10.66.66.9/32")

    cfg = alerts.load_config()
    cfg["enabled"] = True
    alerts.save_config(cfg)

    sent = []
    alerts.dispatch = lambda config, subject, message, level="warning": (sent.append(message) or ["slack"])

    result = alerts.evaluate_rules()
    assert result["checked"] is True
    assert any(t["rule"] == "inactive_days" for t in result["triggered"])

    # deuxieme passage immediat -> dedup, rien de nouveau
    result2 = alerts.evaluate_rules()
    assert result2["triggered"] == []
