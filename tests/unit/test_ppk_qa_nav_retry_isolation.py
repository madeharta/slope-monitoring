"""Safety regression for Batch 19.2 NAV-only and hourly QA boundaries."""
import datetime as dt
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

RUNNER = (Path(__file__).resolve().parents[2] / 'deploy/biznet/magris-ppk-qa-runner-b19')
loader = importlib.machinery.SourceFileLoader('b192_nav_isolation', str(RUNNER))
spec = importlib.util.spec_from_loader(loader.name, loader)
runner = importlib.util.module_from_spec(spec)
loader.exec_module(runner)
NOW = dt.datetime(2026, 10, 29, 0, tzinfo=dt.timezone.utc)
JOB = {'rover': 'ROVER-B1-02', 'since': '2026-10-20T00:00:00+00:00',
       'until': '2026-10-20T01:00:00+00:00'}
KEY = JOB['rover'] + '|' + JOB['since']


def state():
    return {'cursor': runner.START.isoformat(), 'cooldowns': {},
            'nav_pending': {KEY: {'rover': JOB['rover'], 'since': JOB['since'],
                                 'retry_at': NOW.isoformat()}}}


def test_nav_only_ready_never_calls_worker(tmp_path):
    s = state()
    with patch.object(runner, 'STATE', tmp_path / 'state.json'), \
         patch.object(runner, 'CACHE', tmp_path), \
         patch.object(runner, 'prepare_nav', return_value='NAV_READY 42 abc'), \
         patch.object(runner, 'run_scheduler', side_effect=AssertionError('--apply called')):
        assert runner.retry_nav_only(JOB, s, NOW) == 'NAV_READY'
        stored = json.loads((tmp_path / 'state.json').read_text())
        assert stored['nav_pending'][KEY]['ready'] is True
        assert runner.due_nav_jobs(stored, NOW) == []
        assert runner.ready_nav_jobs(stored) == [JOB]


def test_nav_only_waiting_persists_and_can_retry(tmp_path):
    s = state()
    with patch.object(runner, 'STATE', tmp_path / 'state.json'), \
         patch.object(runner, 'CACHE', tmp_path), \
         patch.object(runner, 'prepare_nav', return_value='NAV_WAITING'), \
         patch.object(runner, 'run_scheduler', side_effect=AssertionError('--apply called')):
        assert runner.retry_nav_only(JOB, s, NOW) == 'WAITING_NAV'
        stored = json.loads((tmp_path / 'state.json').read_text())
        assert stored['nav_pending'][KEY]['retry_at'] == (NOW + dt.timedelta(minutes=15)).isoformat()
        assert runner.due_nav_jobs(stored, NOW) == []
        assert runner.due_nav_jobs(stored, NOW + dt.timedelta(minutes=15)) == [JOB]


def test_hourly_consumes_ready_before_discovery(tmp_path, monkeypatch):
    s = state()
    s['nav_pending'][KEY]['ready'] = True
    monkeypatch.setenv('MAGRIS_PPK_QA_RELEASE', '/unused-release')
    monkeypatch.setenv('MAGRIS_PPK_QA_IMAGE', 'unused-image')
    with patch.object(runner, 'ROOT', tmp_path), \
         patch.object(runner, 'CACHE', tmp_path), \
         patch.object(runner, 'STATE', tmp_path / 'state.json'), \
         patch.object(runner, 'read_state', return_value=s), \
         patch.object(runner, 'run_scheduler', return_value='PROCESSED_OR_IDEMPOTENT') as worker, \
         patch.object(runner, 'discovery_bounds', side_effect=AssertionError('discovery called')):
        runner.main(nav_retry_only=False)
        worker.assert_called_once_with(JOB)
    assert KEY not in s['nav_pending']


def test_nav_only_main_never_launches_worker_or_discovery(tmp_path, monkeypatch):
    s = state()
    monkeypatch.setenv('MAGRIS_PPK_QA_RELEASE', '/unused-release')
    monkeypatch.setenv('MAGRIS_PPK_QA_IMAGE', 'unused-image')
    with patch.object(runner, 'ROOT', tmp_path), \
         patch.object(runner, 'CACHE', tmp_path), \
         patch.object(runner, 'STATE', tmp_path / 'state.json'), \
         patch.object(runner, 'read_state', return_value=s), \
         patch.object(runner, 'due_nav_jobs', return_value=[JOB]), \
         patch.object(runner, 'prepare_nav', return_value='NAV_READY 42 abc'), \
         patch.object(runner, 'run_scheduler', side_effect=AssertionError('worker called')), \
         patch.object(runner, 'discovery_bounds', side_effect=AssertionError('discovery called')):
        runner.main(nav_retry_only=True)
    assert json.loads((tmp_path / 'state.json').read_text())['nav_pending'][KEY]['ready'] is True
