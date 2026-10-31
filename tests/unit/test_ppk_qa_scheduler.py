import gzip
import io

import pytest
import datetime as dt
import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2]/'scripts'/'ppk_qa_scheduler.py'
spec = importlib.util.spec_from_file_location('ppk_qa_scheduler', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_closed_windows_with_grace():
    now = dt.datetime(2026, 10, 19, 11, 28, tzinfo=dt.timezone.utc)
    result = module.windows(now, 20, 3)
    assert result == [
        (dt.datetime(2026,10,19,8,tzinfo=dt.timezone.utc),dt.datetime(2026,10,19,9,tzinfo=dt.timezone.utc)),
        (dt.datetime(2026,10,19,9,tzinfo=dt.timezone.utc),dt.datetime(2026,10,19,10,tzinfo=dt.timezone.utc)),
        (dt.datetime(2026,10,19,10,tzinfo=dt.timezone.utc),dt.datetime(2026,10,19,11,tzinfo=dt.timezone.utc)),
    ]


def test_invalid_grace_fails_closed():
    try:
        module.windows(dt.datetime.now(dt.timezone.utc), 0, 3)
        assert False
    except ValueError:
        pass


def test_bounded_nav_decompress_valid():
    assert module.bounded_nav_decompress(gzip.compress(b'valid-data')) == b'valid-data'


def test_bounded_nav_decompress_rejects_compressed_size(monkeypatch):
    monkeypatch.setattr(module, 'MAX_NAV_GZIP_BYTES', 5)
    with pytest.raises(ValueError, match='compressed size'):
        module.bounded_nav_decompress(gzip.compress(b'valid'))


def test_bounded_nav_decompress_rejects_expansion_bomb(monkeypatch):
    monkeypatch.setattr(module, 'MAX_NAV_EXPANDED_BYTES', 128)
    with pytest.raises(ValueError, match='expanded size'):
        module.bounded_nav_decompress(gzip.compress(b'A' * 4096))


def test_bounded_nav_decompress_rejects_truncated_gzip():
    with pytest.raises(ValueError, match='corrupt or truncated'):
        module.bounded_nav_decompress(gzip.compress(b'nav-data')[:-5])


def test_b19_rover_selection_and_rejection():
    assert module.selected_rovers(None) == ['ROVER-B1-01', 'ROVER-B1-02']
    assert module.selected_rovers(['ROVER-B1-02', 'ROVER-B1-02']) == ['ROVER-B1-02']
    with pytest.raises(ValueError):
        module.selected_rovers(['OTHER'])


def test_b19_backlog_bounded_and_closed():
    now = dt.datetime(2026, 10, 28, 12, 30, tzinfo=dt.timezone.utc)
    selected = module.planned_windows(now, 20, 3, '2026-10-26T12:00:00+00:00', '2026-10-27T12:00:00+00:00')
    assert len(selected) == 24
    assert selected[0][0].isoformat() == '2026-10-26T12:00:00+00:00'
    assert selected[-1][1].isoformat() == '2026-10-27T12:00:00+00:00'
    with pytest.raises(ValueError, match='bounded'):
        module.planned_windows(now, 20, 3, '2026-10-25T00:00:00+00:00', '2026-10-27T00:00:00+00:00')
    with pytest.raises(ValueError, match='unclosed'):
        module.planned_windows(now, 20, 3, '2026-10-28T12:00:00+00:00', '2026-10-28T13:00:00+00:00')
    with pytest.raises(ValueError, match='timezone'):
        module.planned_windows(now, 20, 3, '2026-10-26T12:00:00', '2026-10-27T12:00:00')


def test_b19_nav_404_becomes_waiting(monkeypatch, tmp_path):
    import urllib.error
    def missing(*a, **kw):
        raise urllib.error.HTTPError('https://example.invalid', 404, 'missing', {}, None)
    monkeypatch.setattr(module.urllib.request, 'urlopen', missing)
    start = dt.datetime(2026, 10, 28, 7, tzinfo=dt.timezone.utc)
    with pytest.raises(RuntimeError, match='WAITING_NAV HTTP_404'):
        module.nav_for(start, start + dt.timedelta(hours=1), tmp_path, True)
    assert not list(tmp_path.glob('*.part'))
    assert not list(tmp_path.glob('*.part.json'))


def test_b19_runs_both_rovers_without_apply(monkeypatch, tmp_path, capsys):
    import argparse
    config = tmp_path / 'config.conf'
    config.write_text('QA fixture')
    monkeypatch.setenv('PPK_QA_FORWARD_CONFIG', str(config))
    for key in ('PPK_QA_SOURCE_DATABASE_URL','PPK_QA_WRITER_DATABASE_URL',
                'PPK_QA_SOURCE_DB_NAME','PPK_QA_WRITER_DB_NAME',
                'PPK_QA_SOURCE_DB_ROLE','PPK_QA_WRITER_DB_ROLE'):
        monkeypatch.setenv(key, 'fixture')
    monkeypatch.setattr(module, 'planned_windows', lambda *a, **kw: [
        (dt.datetime(2026,10,26,12,tzinfo=dt.timezone.utc),
         dt.datetime(2026,10,26,13,tzinfo=dt.timezone.utc))])
    monkeypatch.setattr(module, 'nav_for', lambda *a: (tmp_path/'nav', 4, 'd'*64))
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        return argparse.Namespace(returncode=0, stdout='{"status":"WAITING_PAIR"}', stderr='')
    monkeypatch.setattr(module.subprocess, 'run', fake_run)
    args = argparse.Namespace(apply=False, grace_minutes=20, backfill_hours=3, since=None,
        until=None, rover=None, site='ITB-STAGING-01', base='BASE-01', min_matched=4,
        no_download=False, timeout_seconds=600)
    assert module.run(args) == 0
    assert len(calls) == 2
    assert [call[call.index('--rover')+1] for call in calls] == list(module.DEFAULT_ROVERS)
    assert capsys.readouterr().out.count('"result": "WAITING_INPUT"') == 2


def test_nav_download_streaming_success(monkeypatch):
    import types
    class Stream:
        headers = {'Content-Type': 'application/gzip'}
        def __init__(self): self.blocks = [b'abc', b'def', b'']
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size): return self.blocks.pop(0)
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **kw: Stream())
    assert module.download_nav('https://igs.bkg.bund.de/example.gz') == b'abcdef'


def test_nav_download_rejects_html(monkeypatch):
    class Stream:
        headers = {'Content-Type': 'text/html; charset=utf-8'}
        def __enter__(self): return self
        def __exit__(self, *args): return False
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **kw: Stream())
    with pytest.raises(ValueError, match='HTML'):
        module.download_nav('https://igs.bkg.bund.de/example.gz')


def test_nav_download_rejects_oversized_stream(monkeypatch):
    monkeypatch.setattr(module, 'MAX_NAV_GZIP_BYTES', 5)
    class Stream:
        headers = {'Content-Type': 'application/gzip'}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size): return b'0123456789'
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **kw: Stream())
    with pytest.raises(ValueError, match='maximum size'):
        module.download_nav('https://igs.bkg.bund.de/example.gz')


def test_nav_deadline_becomes_waiting_and_cache_stays_empty(monkeypatch, tmp_path):
    def timeout(_url):
        raise module.NavDeadlineExceeded('test deadline')
    monkeypatch.setattr(module, 'download_nav_resumable', lambda *_: timeout(None))
    start = dt.datetime(2026, 10, 8, 15, tzinfo=dt.timezone.utc)
    with pytest.raises(RuntimeError, match='WAITING_NAV download_deadline_exceeded'):
        module.nav_for(start, start + dt.timedelta(hours=1), tmp_path, True)
    assert not list(tmp_path.glob('*.part'))
    assert not list(tmp_path.glob('*.part.json'))


def test_nav_resume_range_after_partial_timeout(monkeypatch, tmp_path):
    import urllib.error
    data = gzip.compress(b'hello NAV data' * 300)
    url, name = 'https://example.test/BRDC.gz', 'BRDC.gz'
    seen = []

    class Response:
        def __init__(self, status, headers, payload, fail=False):
            self.status, self.headers, self.payload, self.fail = status, headers, payload, fail
            self.pos = 0
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def read(self, n):
            if self.fail and self.pos >= 18:
                raise urllib.error.URLError('connection interrupted')
            out = self.payload[self.pos:self.pos + min(n, 18)]
            self.pos += len(out)
            return out

    def urlopen(request, timeout=None):
        seen.append(dict(request.header_items()))
        if len(seen) == 1:
            return Response(200, {'Content-Type': 'application/gzip',
                                  'Content-Length': str(len(data)),
                                  'ETag': '"v1"'}, data, fail=True)
        offset = int(request.get_header('Range').split('=')[1].split('-')[0])
        return Response(206, {'Content-Type': 'application/gzip',
                              'Content-Range': f'bytes {offset}-{len(data)-1}/{len(data)}',
                              'ETag': '"v1"'}, data[offset:])

    monkeypatch.setattr(module.urllib.request, 'urlopen', urlopen)
    with pytest.raises(urllib.error.URLError):
        module.download_nav_resumable(url, tmp_path, name)
    partial = tmp_path / (name + '.part')
    assert partial.stat().st_size == 18
    assert module.download_nav_resumable(url, tmp_path, name) == data
    assert seen[1]['Range'] == 'bytes=18-'
    assert seen[1]['If-range'] == '"v1"'


def test_nav_resume_restarts_on_http_200(monkeypatch, tmp_path):
    data = gzip.compress(b'different NAV file')
    url, name = 'https://example.test/BRDC.gz', 'BRDC.gz'
    (tmp_path / (name + '.part')).write_bytes(b'old')
    (tmp_path / (name + '.part.json')).write_text(
        __import__('json').dumps({'url': url, 'validator': '"old"', 'total': 100}))

    class Response:
        status = 200
        headers = {'Content-Type': 'application/gzip', 'Content-Length': str(len(data)), 'ETag': '"new"'}
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def __init__(self): self.payload = data
        def read(self, size):
            value, self.payload = self.payload[:size], self.payload[size:]
            return value

    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **kw: Response())
    assert module.download_nav_resumable(url, tmp_path, name) == data
    assert (tmp_path / (name + '.part')).read_bytes() == data
