from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from common.errors import InvalidCsvError
from ml.pipeline.preprocessing.lora_parser import parse_combined_gnss_csv
from services.monitoring_service.canonicalization_service import CanonicalizationService
@pytest.mark.asyncio
async def test_base_aggregated_position_is_attributed_to_each_rover():
    parsed = parse_combined_gnss_csv(
        "device_id,timestamp_utc,latitude,longitude,altitude_m,gnss_fix_type,h_acc_m,gnss_raw_payload_base64\n"
        "BASE-01,2026-09-15 09:24:00,0,0,0,0,0,tWIB\n"
        "ROVER-01,2026-09-15 09:24:00,-6.2,106.8,500,3,0.02,0\n"
        "ROVER-02,2026-09-15 09:25:00,-6.2,106.8,500,3,0.03,0\n",
        base_device_id="BASE-01",
    )
    rows = parsed.position_rows
    service = CanonicalizationService(None, lambda _: None)
    service._devices.get_site_id = AsyncMock(return_value="SITE-A")
    service._devices.get_base_device_id_for_site = AsyncMock(return_value="BASE-01")
    service._reference.get = AsyncMock(return_value=SimpleNamespace(latitude=-6.2, longitude=106.8, altitude_m=500))
    service._rover_baselines.get = AsyncMock(return_value=SimpleNamespace(latitude=-6.2, longitude=106.8, altitude_m=500, vertical_datum="MSL_CONFIRMED", max_h_acc_m=0.1))
    service._measurements.write_displacement = AsyncMock()
    await service.handle_position_rows("BASE-01", rows)
    assert [call.kwargs["device_id"] for call in service._measurements.write_displacement.await_args_list] == ["ROVER-01", "ROVER-02"]
@pytest.mark.asyncio
async def test_reject_rover_from_other_site_before_writing():
    parsed = parse_combined_gnss_csv(
        "device_id,timestamp_utc,latitude,longitude,altitude_m,gnss_fix_type,h_acc_m,gnss_raw_payload_base64\n"
        "BASE-01,2026-09-15 09:24:00,0,0,0,0,0,tWIB\n"
        "ROVER-01,2026-09-15 09:24:00,-6.2,106.8,500,3,0.02,0\n"
        "ROVER-OTHER,2026-09-15 09:25:00,-6.2,106.8,500,3,0.03,0\n",
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
