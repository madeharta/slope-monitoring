"""Device registration/management — sebelumnya TIDAK ADA endpoint sama
sekali untuk ini (device cuma bisa masuk lewat SQL manual di seed
script). Dibangun 2026-09-20 per permintaan eksplisit.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.errors import AppError, ErrorCode, NotFoundError


@dataclass(frozen=True)
class NewDevice:
    device_id: str
    device_type: str
    site_id: str
    label: str | None = None


class DeviceRepository:
    def __init__(self, pool) -> None:
        self._pool = pool

    async def create(self, device: NewDevice) -> None:
        """FK devices.site_id -> sites.site_id akan menolak otomatis kalau
        site_id belum terdaftar — sudah tertangani rapi lewat handler
        ForeignKeyViolationError di error_handler.py (pesan jelas, bukan
        500 mentah), tidak perlu dicek manual di sini."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO devices (device_id, device_type, site_id, label) VALUES ($1, $2, $3, $4)",
                device.device_id, device.device_type, device.site_id, device.label,
            )

    @staticmethod
    def _build_update_clause(
        device_type: str | None, site_id: str | None, label: str | None = None, label_given: bool = False,
    ) -> tuple[list[str], list]:
        """Logika murni (tidak sentuh DB) — dipisah dari update() supaya
        bisa diuji tanpa asyncpg terinstal. Mengembalikan (fields, args)
        TANPA device_id (dampak sampingnya ditambahkan pemanggil).

        `label_given` (2026-09-21, baru): label BEDA dari device_type/site_id
        — nilai kosong ("") atau None untuk label berarti "kosongkan
        label, fallback tampilan ke device_id apa adanya", BUKAN "field
        ini tidak diisi, jangan diubah". Jadi perlu penanda eksplisit
        terpisah dari None-check biasa (yang dipakai device_type/site_id
        untuk arti "tidak diminta berubah")."""
        fields, args = [], []
        if device_type is not None:
            args.append(device_type)
            fields.append(f"device_type = ${len(args)}")
        if site_id is not None:
            args.append(site_id)
            fields.append(f"site_id = ${len(args)}")
        if label_given:
            args.append(label if label else None)  # string kosong disamakan dengan NULL (kosongkan label)
            fields.append(f"label = ${len(args)}")
        return fields, args

    async def update(
        self, device_id: str, device_type: str | None, site_id: str | None,
        label: str | None = None, label_given: bool = False,
    ) -> None:
        """site_id (kalau diisi) melewati trigger prevent_device_site_id_change
        (migrasi 008/011) — BOLEH diubah kalau device belum pernah kirim
        data, DITOLAK kalau sudah. Trigger melempar RAISE EXCEPTION polos
        (bukan tipe asyncpg spesifik) — ditangkap di sini dan diubah jadi
        AppError yang rapi, pesannya sendiri sudah jelas (ditulis di
        migrasi 011), jadi cukup diteruskan apa adanya. `label` TIDAK
        melewati trigger itu sama sekali — murni kolom tampilan, boleh
        diubah kapan pun, termasuk device yang sudah punya riwayat data."""
        fields, args = self._build_update_clause(device_type, site_id, label, label_given)
        if not fields:
            return
        args.append(device_id)

        # Import DI LUAR try/except (bukan di dalamnya) — kalau di dalam
        # try dan importnya sendiri yang gagal, klausa `except
        # asyncpg.exceptions.RaiseError` ikut gagal dievaluasi
        # (UnboundLocalError, membingungkan) karena nama `asyncpg` belum
        # sempat terikat. Lazy tetap (bukan di top-level file), cuma
        # posisinya dipindah supaya gagalnya jelas (ModuleNotFoundError
        # apa adanya), bukan error sekunder yang menyesatkan.
        import asyncpg

        try:
            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ${len(args)}", *args,
                )
        except asyncpg.exceptions.RaiseError as exc:
            # Ini persis pesan dari trigger migrasi 011 — sudah manusiawi
            # ("device X SUDAH punya riwayat data..."), diteruskan apa adanya.
            raise AppError(ErrorCode.VALIDATION_ERROR, str(exc)) from exc

        if result == "UPDATE 0":
            raise NotFoundError("device", device_id)

    async def has_measurement_history(self, device_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchval("SELECT 1 FROM measurements WHERE device_id = $1 LIMIT 1", device_id)
        return row is not None

    async def delete(self, device_id: str) -> None:
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM devices WHERE device_id = $1", device_id)
        if result == "DELETE 0":
            raise NotFoundError("device", device_id)
