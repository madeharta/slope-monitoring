"""Isolated QA HTTP test fixtures; no real database connections."""
import pytest
from contextlib import asynccontextmanager
from unittest.mock import patch

from apps.api.routers.v1 import ppk


@pytest.fixture(autouse=True)
def _ppk_qa_account_guard_for_unit_tests(request):
    """Replace only account lookup in pre-existing QA unit contract tests.

    Dedicated tests for actual account verification must explicitly opt out.
    """
    if request.module.__name__.split(".")[-1] not in {
        "test_ppk_qa_api_contract",
        "test_ppk_qa_http_access",
        "test_ppk_qa_site_authorization",
        "test_ppk_qa_fallback",
    }:
        yield
        return

    async def active_test_account(_request, user):
        # The fixture represents an active account; keep JWT + site guard real.
        assert user is not None
        assert user.role in {"viewer", "operator", "admin"}

    with patch.object(ppk, "require_active_ppk_qa_user", active_test_account):
        yield
