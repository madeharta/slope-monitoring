import datetime as dt
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import pytest

FILE = Path(__file__).resolve().parents[2] / 'deploy/biznet/magris-ppk-qa-runner-b19'
loader = importlib.machinery.SourceFileLoader('runner_b19', str(FILE))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
UTC = dt.timezone.utc

def test_candidate_validation_three_max():
    base = dt.datetime(2026,10,8,tzinfo=UTC)
    jobs = [{'rover':'ROVER-B1-01','since':(base+dt.timedelta(hours=i)).isoformat(),
             'until':(base+dt.timedelta(hours=i+1)).isoformat()} for i in range(3)]
    assert len(m.load_jobs(json.dumps({'selected':jobs}))) == 3
    with pytest.raises(ValueError): m.load_jobs(json.dumps({'selected':jobs+jobs[:1]}))
    with pytest.raises(ValueError): m.load_jobs(json.dumps({'selected':jobs[:1]*2}))


def test_reject_rover_and_bad_duration():
    a={'rover':'BASE-01','since':'2026-10-08T00:00:00+00:00','until':'2026-10-08T01:00:00+00:00'}
    with pytest.raises(ValueError): m.load_jobs(json.dumps({'selected':[a]}))
    a['rover']='ROVER-B1-01';a['until']='2026-10-08T02:00:00+00:00'
    with pytest.raises(ValueError): m.load_jobs(json.dumps({'selected':[a]}))


def test_rotating_historical_slice():
    now=dt.datetime(2026,10,28,12,tzinfo=UTC)
    begin,end=m.discovery_bounds({'cursor':m.START.isoformat()},now)
    assert begin == m.START
    assert end-begin == dt.timedelta(days=7)
    begin2,end2=m.discovery_bounds({'cursor':end.isoformat()},now)
    assert begin2 == end
    assert end2-begin2 == dt.timedelta(days=7)


def test_persistent_cooldown_and_atomic_state(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'CACHE',tmp_path)
    monkeypatch.setattr(m,'STATE',tmp_path/'state.json')
    state=m.read_state()
    job={'rover':'ROVER-B1-02','since':'2026-10-08T00:00:00+00:00'}
    now=dt.datetime(2026,10,28,tzinfo=UTC)
    m.record_cooldown(state,job,'WAITING_NAV',now)
    m.write_state(state)
    assert m.read_state()['cooldowns'][job['rover']+'|'+job['since']]
    m.record_cooldown(state,job,'PROCESSED_OR_IDEMPOTENT',now)
    m.write_state(state)
    assert not m.read_state()['cooldowns']


def test_fail_closed_corrupt_state(tmp_path,monkeypatch):
    monkeypatch.setattr(m,'STATE',tmp_path/'state.json')
    (tmp_path/'state.json').write_text('{')
    with pytest.raises(ValueError): m.read_state()
