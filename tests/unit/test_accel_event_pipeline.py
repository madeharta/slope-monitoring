from datetime import datetime, timedelta, timezone
from pathlib import Path
import math

from ml.domain.canonical_schema import CanonicalAccelSample
from ml.pipeline.feature_engineering.vibration import analyze_accel_window, compute_vibration_metrics
from ml.pipeline.preprocessing import g4_parser, lora_parser

ROOT = Path(__file__).resolve().parents[2]

def _samples(n=100, dt=0.001):
    t0 = datetime(2026, 9, 18, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        t = i * dt
        ax = math.sin(2 * math.pi * 20 * t)
        out.append(CanonicalAccelSample(
            device_id="ROVER-01", sample_index=i, timestamp_utc=t0 + timedelta(seconds=t),
            adxl355_xyz_mps2=(ax, 0.0, 9.80665),
            mpu9250_xyz_mps2=(ax * 0.9, 0.0, 9.80665),
            colocated_position=None,
        ))
    return out

def test_accel_quality_accepts_nominal_1khz_window():
    q = analyze_accel_window(_samples())
    assert q.quality_gate_status == "accepted"
    assert abs(q.observed_sample_rate_hz - 1000.0) < 1.0
    assert q.max_gap_ms < 1.01

def test_accel_quality_degrades_large_sampling_gap_without_fabricating_continuity():
    rows = _samples()
    rows[50] = CanonicalAccelSample(
        **{**rows[50].__dict__, "timestamp_utc": rows[49].timestamp_utc + timedelta(milliseconds=20)}
    )
    # keep subsequent timestamps increasing after the injected gap
    shift = timedelta(milliseconds=19)
    rows = rows[:51] + [
        CanonicalAccelSample(**{**s.__dict__, "timestamp_utc": s.timestamp_utc + shift})
        for s in rows[51:]
    ]
    q = analyze_accel_window(rows)
    assert q.quality_gate_status == "degraded"
    assert "large_sampling_gap" in q.reasons

def test_accel_quality_rejects_duplicate_sample_index():
    rows = _samples()
    rows[10] = CanonicalAccelSample(**{**rows[10].__dict__, "sample_index": rows[9].sample_index})
    q = analyze_accel_window(rows)
    assert q.quality_gate_status == "rejected"
    assert "duplicate_sample_index" in q.reasons

def test_both_accelerometers_produce_finite_technical_metrics():
    rows = _samples(200)
    adxl = compute_vibration_metrics(rows, sensor="adxl355")
    mpu = compute_vibration_metrics(rows, sensor="mpu9250")
    assert adxl.ppa_g > 0 and adxl.ppv_mm_s > 0
    assert mpu.ppa_g > 0 and mpu.ppv_mm_s > 0

def test_real_4g_fixture_has_nominal_ordered_accel_window():
    raw = (ROOT / "tests/fixtures/itb_real_data/4g_accel_ppk.csv").read_text()
    parsed = g4_parser.parse_accel_csv_single_auxiliary_rawx(raw)
    q = analyze_accel_window(parsed.samples)
    assert q.quality_gate_status == "degraded"
    assert "sample_rate_outside_nominal_tolerance" in q.reasons
    assert 80 <= q.observed_sample_rate_hz <= 120

def test_real_lora_fixture_has_nominal_ordered_accel_window():
    raw = (ROOT / "tests/fixtures/itb_real_data/lora_accel_rtk.csv").read_text()
    samples = lora_parser.parse_accel_csv(raw)
    q = analyze_accel_window(samples)
    assert q.quality_gate_status == "degraded"
    assert "sample_rate_outside_nominal_tolerance" in q.reasons
    assert 80 <= q.observed_sample_rate_hz <= 120
    assert len(samples) == 505  # GNSS-only terminal row is not acceleration

def test_migration_023_locks_blast_event_contract_and_raw_provenance():
    sql = (ROOT / "data/db/migrations/023_blast_event_records.sql").read_text()
    assert "blast_event_records" in sql
    assert "blast.event.v1" in sql
    assert "quality_gate_status" in sql
    assert "validation_status" in sql
    assert "accel_raw_samples_file_name_fkey" in sql
    assert "VALUES (23)" in sql
