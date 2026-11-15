import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'gnss_provisional_reference.py'
spec = importlib.util.spec_from_file_location('gnss_provisional_reference', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_solution(tmp_path, *, lat=2.31667944, lon=117.38691939, quality=5, count=20, outlier=False):
    lines = ['% RTKLIB LLH']
    for n in range(count):
        point_lat = lat + (0.1 if outlier and n == count - 1 else n * 0.00000001)
        lines.append(f'2026/11/15 03:40:{n:02d} {point_lat} {lon} 28.5 {quality} 9 0.1')
    file = tmp_path / 'test.pos'
    file.write_text('\n'.join(lines))
    return file


def test_initialization_and_rover_marker(tmp_path):
    base = module.candidate(make_solution(tmp_path), 'BASE-01')
    state, result = module.evaluate({}, base)
    assert result['status'] == 'REFERENCE_INITIALIZED_PROVISIONAL'
    assert state['reference_epoch'] == 1
    rover = module.candidate(make_solution(tmp_path, lat=2.31864491), 'ROVER-B1-01')
    state2, result = module.evaluate(state, rover)
    assert result['status'] == 'MARKER_READY'
    assert state2['provisional_base_reference'] == state['provisional_base_reference']


def test_outlier_is_rejected(tmp_path):
    result = module.candidate(make_solution(tmp_path, outlier=True), 'BASE-01')
    assert result['status'] == 'HOLD_UNSTABLE_SPP'


def test_bad_quality_is_rejected(tmp_path):
    result = module.candidate(make_solution(tmp_path, quality=1), 'BASE-01')
    assert result['status'] == 'HOLD_INSUFFICIENT_SPP'


def test_relocation_does_not_overwrite_reference(tmp_path):
    first = module.candidate(make_solution(tmp_path), 'BASE-01')
    state, _ = module.evaluate({}, first)
    second = module.candidate(make_solution(tmp_path, lat=2.3500), 'BASE-01')
    state2, result = module.evaluate(state, second)
    assert result['status'] == 'HOLD_RELOCATION_REVIEW'
    assert state2['provisional_base_reference'] == state['provisional_base_reference']
    assert 'pending_base_relocation' in state2


def test_insufficient_samples(tmp_path):
    result = module.candidate(make_solution(tmp_path, count=2), 'ROVER-B1-02')
    assert result['status'] == 'HOLD_INSUFFICIENT_SPP'
