from services.monitoring_service.sensor_read_repository import bounded_stride


def test_bounded_stride_no_downsampling_when_under_limit():
    assert bounded_stride(100, 2000) == 1


def test_bounded_stride_caps_transport_deterministically():
    assert bounded_stride(5001, 2000) == 3
    assert bounded_stride(10000, 2000) == 5


def test_bounded_stride_hard_caps_requested_limit():
    assert bounded_stride(10001, 999999) == 3


def test_bounded_stride_handles_empty():
    assert bounded_stride(0, 2000) == 1
