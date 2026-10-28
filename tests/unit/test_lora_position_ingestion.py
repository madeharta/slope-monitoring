from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from common.errors import InvalidCsvError
from ml.pipeline.preprocessing.lora_parser import parse_combined_gnss_csv
from services.monitoring_service.canonicalization_service import CanonicalizationService
@pytest.mark.asyncio
async def test_base_aggregated_position_is_attributed_to_each_rover():
    parsed = parse_combined_gnss_csv(
        "device_id,timestamp_utc,latitude,longitude,altitude_m,rtk_status,h_acc_m,batt\n"
        "BASE-01,2026-09-15 09:24:00,-6.20000000,106.80000000,500.0000,2,0.0200,12.50\n"
        "ROVER-01,2026-09-15 09:24:00,-6.20000000,106.80000000,500.0000,2,0.0200,12.40\n"
        "ROVER-02,2026-09-15 09:25:00,-6.20000000,106.80000000,500.0000,2,0.0300,12.40\n",
        base_device_id="BASE-01",
    )
    rows = parsed.position_rows
    service = CanonicalizationService(None, lambda _: None)
    service._devices.get_site_id = AsyncMock(return_value="SITE-A")
    service._devices.get_base_device_id_for_site = AsyncMock(return_value="BASE-01")
    service._reference.get = AsyncMock(return_value=SimpleNamespace(latitude=-6.2, longitude=106.8, altitude_m=500))
    service._rover_baselines.get = AsyncMock(return_value=SimpleNamespace(latitude=-6.2, longitude=106.8, altitude_m=500, vertical_datum="ELLIPSOIDAL_WGS84", max_h_acc_m=0.1))
    service._measurements.write_displacement = AsyncMock()
    await service.handle_position_rows("BASE-01", rows)
    assert [call.kwargs["device_id"] for call in service._measurements.write_displacement.await_args_list] == ["ROVER-01", "ROVER-02"]
@pytest.mark.asyncio
async def test_reject_rover_from_other_site_before_writing():
    parsed = parse_combined_gnss_csv(
        "device_id,timestamp_utc,latitude,longitude,altitude_m,rtk_status,h_acc_m,batt\n"
        "BASE-01,2026-09-15 09:24:00,-6.20000000,106.80000000,500.0000,2,0.0200,12.50\n"
        "ROVER-01,2026-09-15 09:24:00,-6.20000000,106.80000000,500.0000,2,0.0200,12.40\n"
        "ROVER-OTHER,2026-09-15 09:25:00,-6.20000000,106.80000000,500.0000,2,0.0300,12.40\n",
        base_device_id="BASE-01",
    )
    rows = parsed.position_rows
    service = CanonicalizationService(None, lambda _: None)
    service._devices.get_site_id = AsyncMock(side_effect=lambda device: "SITE-B" if device == "ROVER-OTHER" else "SITE-A")
    service._devices.get_base_device_id_for_site = AsyncMock(return_value="BASE-01")
    service._reference.get = AsyncMock(return_value=SimpleNamespace(latitude=-6.2, longitude=106.8, altitude_m=500))
    service._measurements.write_displacement = AsyncMock()
    with pytest.raises(InvalidCsvError, match="different site"):
        await service.handle_position_rows("BASE-01", rows)
    service._measurements.write_displacement.assert_not_awaited()


@pytest.mark.asyncio
async def test_lora_base_position_never_produces_displacement():
    from ml.domain.canonical_schema import DeviceRole

    csv_text = (
        "device_id,timestamp_utc,latitude,longitude,altitude_m,rtk_status,h_acc_m,batt\n"
        "BASE-01,2026-10-27 00:00:00,-6.20000000,106.80000000,500.0000,2,0.0200,12.50\n"
        "ROVER-01,2026-10-27 00:00:00,-6.20010000,106.80010000,500.1000,2,0.0300,12.40\n"
    )

    parsed = parse_combined_gnss_csv(
        csv_text, base_device_id="BASE-01"
    )

    assert [sample.role for sample in parsed.position_rows] == [
        DeviceRole.BASE, DeviceRole.ROVER
    ]

    service = CanonicalizationService(None, lambda _: None)
    service._devices.get_site_id = AsyncMock(return_value="SITE-A")
    service._rover_baselines.get = AsyncMock(
        return_value=SimpleNamespace(
            latitude=-6.2,
            longitude=106.8,
            altitude_m=500,
            vertical_datum="ELLIPSOIDAL_WGS84",
            max_h_acc_m=0.1,
        )
    )
    service._measurements.write_displacement = AsyncMock()

    await service.handle_position_rows("BASE-01", parsed.position_rows)

    written_ids = [
        call.kwargs["device_id"]
        for call in service._measurements.write_displacement.await_args_list
    ]

    assert written_ids == ["ROVER-01"]

    baseline_ids = [
        call.args[0]
        for call in service._rover_baselines.get.await_args_list
    ]
    assert baseline_ids == ["ROVER-01"]
