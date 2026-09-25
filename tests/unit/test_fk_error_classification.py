from __future__ import annotations
def _classify_fk_detail(detail_text: str) -> str:
    if "is still referenced from table" in detail_text:
        return "DELETE_BLOCKED_BY_CHILD"
    return "INSERT_REFERENCES_MISSING_ROW"
def test_delete_blocked_by_child_row_detail_pattern():
    detail = 'Key (device_id)=(BASE-01) is still referenced from table "device_reference_position".'
    assert _classify_fk_detail(detail) == "DELETE_BLOCKED_BY_CHILD"
def test_insert_references_missing_row_detail_pattern():
    detail = 'Key (base_id)=(BASE-99) is not present in table "devices".'
    assert _classify_fk_detail(detail) == "INSERT_REFERENCES_MISSING_ROW"
