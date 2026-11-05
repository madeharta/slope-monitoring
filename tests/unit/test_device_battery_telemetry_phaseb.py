"""Focused, no-DB regression for the ITB battery header extraction and attribution."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest

from services.device_service.battery_telemetry import voltage_from_header, persist_four_g_battery
from ml.pipeline.preprocessing.lora_parser import parse_combined_gnss_csv


@pytest.mark.parametrize('raw', [None, '', 'NaN', 'inf', '-1', 'garbage'])
def test_battery_missing_value_is_not_a_measurement(raw):
    assert voltage_from_header(raw) is None


def test_valid_voltage_is_in_volts():
    assert voltage_from_header('12.45') == 12.45
    assert voltage_from_header('0') == 0.0  # Preserve ITB raw zero, no rewriting


def test_lora_csv_has_independent_device_values():
    rows = parse_combined_gnss_csv(
        'device_id,timestamp_utc,latitude,longitude,altitude_m,rtk_status,h_acc_m,batt\n'
        'BASE-01,2026-11-05 08:00:00,-6.20,106.80,500,2,0.02,12.50\n'
        'ROVER-B1-01,2026-11-05 08:00:00,-6.21,106.81,501,2,0.03,12.10\n',
        base_device_id='BASE-01',
    ).position_rows
    assert [(r.device_id, r.battery_voltage_v) for r in rows] == [
        ('BASE-01', 12.5), ('ROVER-B1-01', 12.1),
    ]


@pytest.mark.asyncio
async def test_4g_voltage_is_only_attributed_to_http_uploader():
    class Pool:
        def acquire(self): return self
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def fetchval(self, sql, *args):
            assert args == ('ROVER-B1-01',)
            return 'ITB-STAGING-01'
    pool = Pool()
    with patch('services.device_service.battery_telemetry.MeasurementsWriter') as writer:
        writer.return_value.write_battery_points = AsyncMock()
        ts = datetime(2026, 11, 5, 8, tzinfo=timezone.utc)
        await persist_four_g_battery(pool, device_id='ROVER-B1-01',
            voltage_header='12.43', uploaded_at=ts, file_name='gnss_R_20261105_0800.csv')
        writer.return_value.write_battery_points.assert_awaited_once_with(
            [('ROVER-B1-01', 'ITB-STAGING-01', ts, 12.43)],
            source_file='gnss_R_20261105_0800.csv',
        )
