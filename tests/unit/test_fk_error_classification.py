"""Regression guard untuk bug nyata 2026-09-21: satu pesan generik
dipakai untuk DUA situasi FK violation yang beda makna (lihat
apps/api/middlewares/error_handler.py) — pengguna coba hapus BASE-01
(masih dirujuk device_reference_position) dan dapat pesan "device tidak
ada di database, cek sudah di-seed" yang SALAH KONTEKS (device itu ADA,
cuma tidak bisa dihapus karena masih dirujuk).

Tidak bisa test middleware penuh di sini (butuh FastAPI Request +
asyncpg exception instance sungguhan, tidak tersedia di sandbox) — test
ini mengunci POLA STRING yang membedakan keduanya, dikonfirmasi dari
dokumentasi resmi asyncpg + contoh error Postgres nyata (GitHub issues
MagicStack/asyncpg, fastapi/sqlmodel #457).
"""

from __future__ import annotations


def _classify_fk_detail(detail_text: str) -> str:
    """Replika PERSIS logika di error_handler.py — kalau logika di sana
    berubah, test ini juga harus diperbarui (bukan otomatis sinkron)."""
    if "is still referenced from table" in detail_text:
        return "DELETE_BLOCKED_BY_CHILD"
    return "INSERT_REFERENCES_MISSING_ROW"


def test_delete_blocked_by_child_row_detail_pattern():
    # Pola nyata Postgres saat DELETE ditolak karena masih ada anak yang
    # merujuk baris ini (dikonfirmasi dari fastapi/sqlmodel issue #457).
    detail = 'Key (device_id)=(BASE-01) is still referenced from table "device_reference_position".'
    assert _classify_fk_detail(detail) == "DELETE_BLOCKED_BY_CHILD"


def test_insert_references_missing_row_detail_pattern():
    # Pola nyata Postgres saat INSERT/UPDATE merujuk baris yang belum ada
    # (dikonfirmasi dari Chainlit/chainlit issue #1788).
    detail = 'Key (base_id)=(BASE-99) is not present in table "devices".'
    assert _classify_fk_detail(detail) == "INSERT_REFERENCES_MISSING_ROW"
