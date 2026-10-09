import pytest
from fastapi import HTTPException

from apps.api.routers.v1.device_config import _assert_generic_write_allowed


@pytest.mark.parametrize("key", ["TriggerStart", "TimeOutTrigger"])
def test_generic_device_config_rejects_blast_global_keys(key):
    with pytest.raises(HTTPException) as exc:
        _assert_generic_write_allowed(key)

    assert exc.value.status_code == 400
    assert "/api/v1/blast/trigger" in str(exc.value.detail)
    assert "/api/v1/blast/reset" in str(exc.value.detail)


@pytest.mark.parametrize(
    "key",
    [
        "periodic_upload_s",
        "firmware_version",
        "threshold_g",
        "time_record_ms",
        "battery_cal_m",
        "battery_cal_c",
    ],
)
def test_generic_device_config_allows_non_blast_keys(key):
    _assert_generic_write_allowed(key)
