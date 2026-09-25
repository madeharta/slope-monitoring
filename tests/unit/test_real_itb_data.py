import pytest
pytestmark = pytest.mark.skip(
    reason="legacy ITB sample CSVs are historical fixtures, not the 2026-09-24 production API contract"
)
def test_legacy_itb_fixtures_are_not_contract_tests():
    pass
