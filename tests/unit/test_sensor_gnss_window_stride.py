from services.monitoring_service.sensor_read_repository import (
    HARD_MAX_POINTS,
    bounded_window_stride,
)


def selected_count(total: int, stride: int) -> int:
    if total <= 0:
        return 0
    selected = {1, total}
    selected.update(range(1, total + 1, stride))
    return len(selected)


def test_small_window_undownsampled():
    assert bounded_window_stride(100, 5000) == 1


def test_24h_like_window_respects_hard_limit():
    stride = bounded_window_stride(5760, HARD_MAX_POINTS)
    assert stride >= 2
    assert selected_count(5760, stride) <= HARD_MAX_POINTS


def test_long_window_respects_requested_limit():
    stride = bounded_window_stride(50000, 5000)
    assert stride > 1
    assert selected_count(50000, stride) <= 5000


def test_empty_window():
    assert bounded_window_stride(0, 5000) == 1
