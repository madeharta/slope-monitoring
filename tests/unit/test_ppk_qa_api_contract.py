"""PPK QA API v1 contract: deterministic 240-row HTTP regression."""

import base64
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.routers.v1.ppk import router
from common.security import TokenPayload, create_access_token


def fixture_rows():
    return [
        {
            "id": i + 1,
            "site_id": "ITB-STAGING-01",
            "base_device_id": "BASE-01",
            "rover_device_id": "ROVER-B1-02",
            "source_pos_sha256": "a" * 64,
            "gps_week": 2440,
            "gps_tow_s": 489621.0 + i * 15,
            "latitude_deg": -6.8671,
            "longitude_deg": 107.5787,
            "ellipsoidal_height_m": 880.0,
            "rtklib_quality": 2,
            "satellite_count": 9,
            "sdn_m": 0.02,
            "sde_m": 0.03,
            "sdu_m": 0.04,
            "sdne_m": None,
            "sdeu_m": None,
            "sdun_m": None,
            "age_s": 0.0,
            "ratio": 0.0,
            "reference_type": "PROVISIONAL_SPP",
            "validation_status": "unvalidated",
            "schema_version": "ppk.qa.solution.v1",
            "created_at": datetime(
                2026, 10, 16, tzinfo=timezone.utc
            ),
        }
        for i in range(240)
    ]


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, query, *args):
        if "SELECT DISTINCT rover_device_id" in query:
            return [{"rover_device_id": "ROVER-B1-02"}]

        assert "ppk_qa_experimental_solutions" in query

        site, rover, cutoff, week, tow, row_id, limit = args

        selected = [
            row for row in self.rows
            if row["site_id"] == site
            and (rover is None or row["rover_device_id"] == rover)
            and (
                cutoff is None
                or row["gps_week"] * 604800 + row["gps_tow_s"]
                >= cutoff
            )
            and (
                week is None
                or (
                    row["gps_week"],
                    row["gps_tow_s"],
                    row["id"],
                ) > (week, tow, row_id)
            )
        ]

        selected.sort(
            key=lambda r: (
                r["gps_week"],
                r["gps_tow_s"],
                r["id"],
            )
        )

        return selected[:limit]


class FakePool:
    def __init__(self, rows):
        self.connection = FakeConnection(rows)

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def test_qa_api_contract_240_epochs():
    app = FastAPI()
    app.include_router(router)
    app.state.ppk_qa_db_pool = FakePool(fixture_rows())

    token = create_access_token(
        TokenPayload(
            sub="1001",
            role="viewer",
            mfa_verified=False,
        )
    )
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = "/api/v1/ppk/qa/solutions"

    with TestClient(app) as client:
        assert client.get(endpoint).status_code == 401

        rovers = client.get(
            "/api/v1/ppk/qa/rovers",
            headers=headers,
        )
        assert rovers.status_code == 200
        assert rovers.json()["rovers"] == ["ROVER-B1-02"]

        cursor = None
        collected = []
        pages = 0

        while True:
            params = {
                "site_id": "ITB-STAGING-01",
                "rover_device_id": "ROVER-B1-02",
                "time_range": "all",
                "limit": 50,
            }

            if cursor:
                params["cursor"] = cursor

            response = client.get(
                endpoint,
                params=params,
                headers=headers,
            )
            assert response.status_code == 200, response.text

            body = response.json()

            assert body["availability_status"] == "available"
            assert body["schema_version"] == "ppk.qa.solution.v1"
            assert body["api_contract_version"] == "ppk.qa.api.v1"
            assert body["operational_displacement_approved"] is False
            assert body["validation_status"] == "unvalidated"
            assert body["pagination"]["returned"] == len(body["rows"])

            for row in body["rows"]:
                assert row["vertical_datum"] == "ELLIPSOIDAL_WGS84"
                assert row["reference_type"] == "PROVISIONAL_SPP"
                assert row["validation_status"] == "unvalidated"
                assert row["rtklib_quality"] == 2
                assert row["gps_week"] == 2440
                assert row["gps_utc_offset_s"] == 18
                assert row["time_conversion_status"] == (
                    "GPS_UTC_OFFSET_18S_EPOCH_LIMITED"
                )
                assert row["observation_time_utc"] is not None

            collected.extend(body["rows"])
            pages += 1

            if not body["pagination"]["has_more"]:
                assert body["pagination"]["next_cursor"] is None
                break

            cursor = body["pagination"]["next_cursor"]
            assert cursor
            assert pages < 10

        keys = [
            (r["gps_week"], r["gps_tow_s"])
            for r in collected
        ]

        assert pages == 5
        assert len(collected) == 240
        assert len(set(keys)) == 240
        assert keys == sorted(keys)

        invalid = client.get(
            endpoint,
            params={"cursor": "invalid!"},
            headers=headers,
        )
        assert invalid.status_code == 422

        other_site = client.get(
            endpoint,
            params={"site_id": "OTHER-SITE"},
            headers=headers,
        )
        assert other_site.status_code == 200
        assert other_site.json()["rows"] == []
