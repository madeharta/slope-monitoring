"""Batch 19.3 safe NAV parsing and failure diagnostics."""
import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

RUNNER = Path(__file__).resolve().parents[2] / 'deploy/biznet/magris-ppk-qa-runner-b19'
spec = importlib.util.spec_from_loader('magris_b193_runner', SourceFileLoader('magris_b193_runner', str(RUNNER)))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_nav_multiline_ready():
    assert runner.nav_status('NAV_TRANSFER: partial\nNAV_READY 66 0123456789abcdef\n') == 'NAV_READY 66 0123456789abcdef'


def test_nav_waiting_and_invalid():
    assert runner.nav_status('progress\nNAV_WAITING\n') == 'NAV_WAITING'
    for output in ('', 'NAV_READY 0 0123456789abcdef',
                   'NAV_READY 66 invalid', 'NAV_WAITING\nNAV_READY 66 0123456789abcdef'):
        with pytest.raises(RuntimeError):
            runner.nav_status(output)


def test_diagnostics_never_print_secrets():
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        runner.diagnostic('QA_WINDOW', runner.ContainerExecutionError(125),
                          {'rover':'ROVER-B1-02', 'since':'2026-10-08T11:00:00+00:00'})
    log = stream.getvalue()
    assert 'exit_code' in log and '125' in log
    assert 'QA_WINDOW' in log
    assert 'postgresql://' not in log


def test_docker_failure_safe_exit_code():
    class Result:
        returncode = 7
        stderr = 'postgresql://secret:password@hidden'
        stdout = 'private'
    stream = io.StringIO()
    with patch.object(runner.subprocess, 'run', return_value=Result()):
        with contextlib.redirect_stdout(stream):
            with pytest.raises(runner.ContainerExecutionError) as err:
                runner.docker(['run'], 3)
    assert err.value.exit_code == 7
    assert 'secret' not in stream.getvalue()
