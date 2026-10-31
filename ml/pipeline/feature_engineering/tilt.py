"""Tilt (kemiringan statis) dari accelerometer — GAP NYATA (2026-09-21):
dashboard sudah lama menampilkan kartu "Tilt X (ADXL355)" tapi TIDAK ADA
satu pun fungsi perhitungan tilt di backend manapun (dicek: `grep -rn
"def.*tilt"` di seluruh `ml/` dan `services/` — nol hasil). Kartu itu
selalu kosong bukan karena belum ada data, tapi karena tidak ada kode
yang menghitungnya sama sekali.

KOREKSI (2026-09-21, sesudah dicek ulang ke API Spec §1/§13.3 —
dokstring awal modul ini SALAH): draft pertama menulis "tilt dari
window tenang terpisah dari event blast" — TERNYATA sistem ini TIDAK
PUNYA mode upload accel periodik/tenang sama sekali. `accel.csv`
HANYA PERNAH dikirim manual setelah event ledakan (API Spec: "File
tersimpan di SD rover... User unduh via SoftAP, lalu POST accel.csv
secara manual"). Jadi tilt di sistem ini SELALU dihitung dari window
ledakan yang sama dengan PPA/PPV — bukan window terpisah yang memang
tidak ada sumber datanya. Konsekuensinya harus jujur ditampilkan ke
pengguna dashboard: nilai tilt = orientasi SAAT ledakan terakhir
terjadi, BUKAN pembacaan kontinu/real-time.

Beda dengan vibration.py (PPA/PPV — metrik EVENT TRANSIEN, sinyal
di-detrend/dibuang komponen statisnya): tilt justru SEBALIKNYA — yang
dicari adalah komponen statis (rata-rata, BUKAN di-detrend), karena
itulah yang merepresentasikan orientasi sensor relatif gravitasi.
Rata-rata atas window ~2 detik ini adalah ESTIMASI (asumsi getaran
dinamis rata-rata mendekati nol dalam window pendek), bukan pembacaan
statis murni seperti andai ada mode tenang sungguhan — makanya modul
tetap terpisah dari vibration.py (tujuan pembacaan beda), tapi
KONSUMENNYA (canonicalization_service.py) memanggil keduanya dari
window data yang SAMA, bukan dari upload terpisah.

Formula: sudut roll/pitch standar dari vektor gravitasi rata-rata
(dasar fisika IMU, dipakai luas di aplikasi embedded — bukan klaim
dari satu paper tertentu, ini aljabar vektor gravitasi baku), diuji
terhadap kasus geometri yang jawabannya sudah pasti (0/45/90 derajat) —
lihat tests/unit/test_tilt.py:
    roll  (tilt_x) = atan2(x, sqrt(y^2 + z^2))
    pitch (tilt_y) = atan2(y, sqrt(x^2 + z^2))
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ml.domain.canonical_schema import CanonicalAccelSample


@dataclass(frozen=True)
class TiltDeg:
    tilt_x_deg: float
    tilt_y_deg: float
    sample_count: int


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def compute_tilt(samples: list[CanonicalAccelSample], sensor: str = "adxl355") -> TiltDeg:
    """Rata-rata (BUKAN detrend) x/y/z atas window, lalu roll/pitch dari
    vektor gravitasi rata-rata itu. `sensor` sama seperti
    compute_vibration_metrics — pilih ADXL355 atau MPU9250."""
    if not samples:
        raise ValueError("compute_tilt requires at least one sample")

    if sensor == "adxl355":
        xs = [s.adxl355_xyz_mps2[0] for s in samples]
        ys = [s.adxl355_xyz_mps2[1] for s in samples]
        zs = [s.adxl355_xyz_mps2[2] for s in samples]
    elif sensor == "mpu9250":
        xs = [s.mpu9250_xyz_mps2[0] for s in samples]
        ys = [s.mpu9250_xyz_mps2[1] for s in samples]
        zs = [s.mpu9250_xyz_mps2[2] for s in samples]
    else:
        raise ValueError(f"unknown sensor '{sensor}' (expected adxl355|mpu9250)")

    x, y, z = _mean(xs), _mean(ys), _mean(zs)

    tilt_x = math.degrees(math.atan2(x, math.sqrt(y**2 + z**2)))
    tilt_y = math.degrees(math.atan2(y, math.sqrt(x**2 + z**2)))
    return TiltDeg(tilt_x_deg=tilt_x, tilt_y_deg=tilt_y, sample_count=len(samples))
