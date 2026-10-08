"""Legacy hardware CSV fixtures are intentionally not contract tests.

Decision 2026-09-24: production parsing is governed by API Spec LoRa v1.5 /
4G v1.8 plus the active contract overrides. The Sep-18 CSV examples differ
from that contract and therefore must not gate production parser behavior.
They remain in tests/fixtures only as historical/raw evidence for manual
forensics and future migration tooling.
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="legacy ITB sample CSVs are historical fixtures, not the 2026-09-24 production API contract"
)


def test_legacy_itb_fixtures_are_not_contract_tests():
    pass
