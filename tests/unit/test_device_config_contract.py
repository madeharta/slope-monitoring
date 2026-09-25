from services.device_config_service.config_repository import compose_contract_config
def test_contract_shape_contains_latest_required_fields(monkeypatch):
    monkeypatch.setenv("DEVICE_DEFAULT_FIRMWARE_VERSION", "1.0.3")
    result = compose_contract_config(
        requested={"threshold_g": 0.75, "TriggerStart": 0},
        base={"TriggerStart": 1, "TimeOutTrigger": 2},
        battery_cal={"BASE-01": {"m": 0.0123, "c": 0.45}, "ROVER-B1-01": {"m": None, "c": None}},
        requested_is_base=False,
    )
    assert result == {
        "periodic_upload_s": 300,
        "firmware_version": "1.0.3",
        "threshold_g": 0.75,
        "time_record_ms": 2000,
        "TriggerStart": 1,
        "TimeOutTrigger": 2,
        "battery_cal": {
            "BASE-01": {"m": 0.0123, "c": 0.45},
            "ROVER-B1-01": {"m": None, "c": None},
        },
    }
def test_base_can_override_global_trigger(monkeypatch):
    monkeypatch.setenv("DEVICE_DEFAULT_TRIGGER_START", "0")
    result = compose_contract_config(
        requested={"TriggerStart": 1, "TimeOutTrigger": 5},
        base={"TriggerStart": 0, "TimeOutTrigger": 3},
        battery_cal={},
        requested_is_base=True,
    )
    assert result["TriggerStart"] == 1
    assert result["TimeOutTrigger"] == 5
def test_rover_cannot_override_global_trigger():
    result = compose_contract_config(
        requested={"TriggerStart": 0, "TimeOutTrigger": 99},
        base={"TriggerStart": 1, "TimeOutTrigger": 4},
        battery_cal={},
        requested_is_base=False,
    )
    assert result["TriggerStart"] == 1
    assert result["TimeOutTrigger"] == 4
