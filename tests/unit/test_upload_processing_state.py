import pytest
from services.ingestion_service.csv_validator import check_idempotent
class FakeRepo:
    def __init__(self, row):
        self.row = row
    async def get_by_file_name(self, _file_name):
        return self.row
@pytest.mark.asyncio
async def test_idempotent_only_when_processed():
    assert await check_idempotent("x.csv", FakeRepo({"processing_status": "processed"})) is True
    assert await check_idempotent("x.csv", FakeRepo({"processing_status": "failed"})) is False
    assert await check_idempotent("x.csv", FakeRepo({"processing_status": "processing"})) is False
    assert await check_idempotent("x.csv", FakeRepo(None)) is False
@pytest.mark.asyncio
async def test_legacy_row_without_status_is_processed_for_compatibility():
    assert await check_idempotent("legacy.csv", FakeRepo({"file_name": "legacy.csv"})) is True
