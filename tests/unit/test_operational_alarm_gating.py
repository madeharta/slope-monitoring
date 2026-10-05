from apps.api import config


def test_operational_gate_defaults_fail_closed(monkeypatch):
    monkeypatch.delenv("OPERATIONAL_ALARMS_ENABLED", raising=False)

    assert config.operational_alarms_enabled() is False
    assert config.operational_alarm_for("bahaya") is False
    assert config.operational_alarm_for("siaga") is False
    assert "Evacuate" not in config.action_for("bahaya")


def test_legacy_action_symbol_is_safe_by_default():
    assert config.ACTION is config.TECHNICAL_ACTION
    assert "Evacuate" not in config.ACTION["bahaya"]


def test_explicit_enable_allows_operational_alarm(monkeypatch):
    monkeypatch.setenv("OPERATIONAL_ALARMS_ENABLED", "true")

    assert config.operational_alarms_enabled() is True
    assert config.operational_alarm_for("bahaya") is True
    assert config.operational_alarm_for("siaga") is True
    assert config.operational_alarm_for("normal") is False
    assert config.action_for("bahaya") == config.OPERATIONAL_ACTION["bahaya"]


def test_unknown_switch_value_fails_closed(monkeypatch):
    monkeypatch.setenv("OPERATIONAL_ALARMS_ENABLED", "maybe")

    assert config.operational_alarms_enabled() is False
    assert config.operational_alarm_for("bahaya") is False
    assert "Evacuate" not in config.action_for("bahaya")
