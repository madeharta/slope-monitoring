from datetime import datetime, timezone

from services.monitoring_service.ppk_solution_repository import is_complete_provenance
from ml.pipeline.preprocessing.ppk_engine import PPK_OUTPUT_SCHEMA_VERSION, PPKSolutionEpoch


def test_ppk_solution_v1_contract_keys_and_vertical_datum_are_locked():
    solution = PPKSolutionEpoch(
        timestamp_utc=datetime(2026, 10, 9, tzinfo=timezone.utc),
        latitude=-6.2,
        longitude=106.8,
        ellipsoidal_height_m=500.0,
        rtklib_quality=1,
        satellites=12,
        sdn_m=0.002,
        sde_m=0.003,
        sdu_m=0.004,
        age_s=0.5,
        ratio=10.0,
    )
    contract = solution.to_contract()
    assert contract["schema_version"] == PPK_OUTPUT_SCHEMA_VERSION == "ppk.solution.v1"
    assert contract["vertical_datum"] == "ELLIPSOIDAL_WGS84"
    assert set(contract) == {
        "schema_version",
        "timestamp_utc",
        "latitude",
        "longitude",
        "ellipsoidal_height_m",
        "vertical_datum",
        "rtklib_quality",
        "rtklib_ns",
        "rtklib_sdn_m",
        "rtklib_sde_m",
        "rtklib_sdu_m",
        "h_acc_m",
        "rtklib_age_s",
        "rtklib_ratio",
    }
    assert not any(key.startswith("displacement") for key in contract)


def test_provenance_completeness_requires_full_reproducibility_chain():
    complete = {
        "base_rawx_sha256": "a" * 64,
        "rover_rawx_sha256": "b" * 64,
        "base_obs_sha256": "c" * 64,
        "rover_obs_sha256": "d" * 64,
        "navigation_sha256": "e" * 64,
        "normalized_navigation_sha256": "f" * 64,
        "convbin_sha256": "1" * 64,
        "rnx2rtkp_sha256": "2" * 64,
        "solution_pos_sha256": "3" * 64,
    }
    assert is_complete_provenance(complete) is True
    complete["solution_pos_sha256"] = None
    assert is_complete_provenance(complete) is False
