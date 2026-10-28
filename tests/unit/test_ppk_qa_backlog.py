import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('backlog', ROOT / 'scripts/ppk_qa_backlog.py')
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 10, 8, 15, tzinfo=UTC)


def item(rover, hour=0):
    return module.Window(rover, T0 + dt.timedelta(hours=hour), 24)


def test_two_rovers_and_limit():
    items = [item('ROVER-B1-02'), item('ROVER-B1-01'), item('ROVER-B1-02', 1), item('ROVER-B1-01', 1)]
    result = module.select_windows(items, [], set(), now=T0, limit=3)
    assert len(result) == 3
    assert [x.rover for x in result[:2]] == ['ROVER-B1-01', 'ROVER-B1-02']


def test_skip_completed_even_if_fingerprint_changes():
    x = item('ROVER-B1-01')
    assert module.select_windows([x], [((x.rover, x.start), 'COMPLETED', 1)], set(), now=T0) == []


def test_skip_existing_solution():
    x = item('ROVER-B1-02')
    assert module.select_windows([x], [], {(x.rover, x.start)}, now=T0) == []


def test_running_and_exhausted_failed_are_blocked():
    a, b = item('ROVER-B1-01'), item('ROVER-B1-02')
    assert module.select_windows([a, b], [((a.rover,a.start),'RUNNING',1),
                                          ((b.rover,b.start),'FAILED',3)], set(), now=T0) == []


def test_retryable_failed_allowed():
    a = item('ROVER-B1-01')
    assert module.select_windows([a], [((a.rover,a.start),'FAILED',2)], set(), now=T0) == [a]


def test_nav_cooldown():
    a = item('ROVER-B1-01')
    k = f'{a.rover}|{a.start.isoformat()}'
    assert module.select_windows([a], [], set(), {k:(T0+dt.timedelta(hours=2)).isoformat()}, now=T0) == []
    assert module.select_windows([a], [], set(), {k:(T0-dt.timedelta(hours=2)).isoformat()}, now=T0) == [a]


def test_invalid_cooldown_fail_closed():
    a = item('ROVER-B1-01')
    assert module.select_windows([a], [], set(), {f'{a.rover}|{a.start.isoformat()}':'invalid'}, now=T0) == []


def test_utc_validation_and_limit():
    assert module.parse_utc('2026-10-08T15:00:00Z') == T0
    import pytest
    with pytest.raises(ValueError):
        module.parse_utc('2026-10-08T15:30:00Z')
    with pytest.raises(ValueError):
        module.select_windows([item('ROVER-B1-01')], [], set(), limit=4)
