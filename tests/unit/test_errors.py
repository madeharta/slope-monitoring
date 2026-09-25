from common.errors import ErrorCode, InvalidCsvError, InvalidDeviceIdError, STATUS_FOR
def test_every_error_code_has_a_status():
    for code in ErrorCode:
        assert code in STATUS_FOR, f"{code} missing from STATUS_FOR"
def test_invalid_device_id_maps_to_403():
    err = InvalidDeviceIdError("ROVER-99")
    assert err.status_code == 403
    assert err.code == ErrorCode.INVALID_DEVICE_ID
    assert err.to_envelope() == {
        "ok": False, "error": "INVALID_DEVICE_ID", "detail": "device_id 'ROVER-99' is not registered",
    }
def test_invalid_csv_maps_to_400():
    err = InvalidCsvError("missing column")
    assert err.status_code == 400
