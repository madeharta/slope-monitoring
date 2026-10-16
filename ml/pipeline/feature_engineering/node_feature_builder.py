"""Node feature vector builder — blueprint §6 (graph construction input),
dengan skema fitur SENSOR SUNGGUHAN sistem ini (GNSS + accelerometer),
BUKAN skema v2.6.0 lama (IMU orientasi + cuaca, tidak kompatibel — lihat
docs/architecture/BLUEPRINT_ARSITEKTUR_BACKEND_ML.md §0).

Murni transformasi deterministik dari hasil modul lain yang SUDAH
diverifikasi (displacement.py, vibration.py, tilt.py) — modul ini
sendiri tidak menghitung fisika apa pun, cuma menggabungkan jadi satu
vektor dengan urutan tetap. Tidak ada I/O, bisa diuji penuh dengan input
sintetis (tidak perlu DB/hardware).

Kenapa 10 fitur ini (bukan skema lain): dE/dN/dU + total (4) adalah
sinyal utama (pergerakan lereng); velocity (1) menangkap TREN, bukan
cuma posisi sesaat; PPA/PPV (2) menangkap event getaran (ledakan/gempa
mikro); tilt X/Y (2) menangkap orientasi statis (indikasi rotasi
lereng, bukan cuma translasi); h_acc_m (1) adalah indikator KUALITAS
bacaan GNSS itu sendiri — model perlu tahu seberapa dipercaya input-nya,
bukan cuma nilainya.
"""

from __future__ import annotations

from dataclasses import dataclass

from ml.pipeline.feature_engineering.displacement import DisplacementMM
from ml.pipeline.feature_engineering.tilt import TiltDeg
from ml.pipeline.feature_engineering.vibration import VibrationMetrics

# Urutan ini SENGAJA eksplisit dan diekspor terpisah dari dataclass-nya —
# supaya kode yang mengonsumsi to_tensor_row() bisa selalu tahu index ke-N
# itu fitur apa, tanpa harus mengintip constructor NodeFeatureVector.
FEATURE_NAMES: tuple[str, ...] = (
    "de_mm", "dn_mm", "du_mm", "total_mm",
    "velocity_mm_day",
    "ppa_g", "ppv_mm_s",
    "tilt_x_deg", "tilt_y_deg",
    "h_acc_m",
)


@dataclass(frozen=True)
class NodeFeatureVector:
    device_id: str
    de_mm: float
    dn_mm: float
    du_mm: float
    total_mm: float
    velocity_mm_day: float          # 0.0 kalau tidak ada displacement sebelumnya untuk dibandingkan (bukan "diam", tapi "belum bisa dihitung")
    ppa_g: float                    # 0.0 kalau tidak ada event getaran di window ini (nilai sah — bukan data hilang)
    ppv_mm_s: float
    tilt_x_deg: float
    tilt_y_deg: float
    h_acc_m: float

    def to_tensor_row(self) -> tuple[float, ...]:
        """Urutan HARUS persis sama dengan FEATURE_NAMES — dijaga lewat
        test_node_feature_builder.py yang membandingkan keduanya eksplisit,
        supaya perubahan salah satu (constructor vs urutan tensor) tanpa
        mengubah yang lain langsung ketahuan gagal, bukan silent bug."""
        return (
            self.de_mm, self.dn_mm, self.du_mm, self.total_mm,
            self.velocity_mm_day,
            self.ppa_g, self.ppv_mm_s,
            self.tilt_x_deg, self.tilt_y_deg,
            self.h_acc_m,
        )


def compute_velocity_mm_day(
    current_total_mm: float, previous_total_mm: float | None,
    current_epoch_s: float, previous_epoch_s: float | None,
) -> float:
    """Laju perubahan displacement total, mm/hari. 0.0 (bukan None/NaN —
    fitur tensor harus selalu berupa angka) kalau tidak ada titik
    sebelumnya untuk dibandingkan, ATAU kalau selisih waktu <= 0 (data
    tidak berurutan/duplikat — dibagi nol dihindari secara eksplisit,
    bukan kebetulan tidak error)."""
    if previous_total_mm is None or previous_epoch_s is None:
        return 0.0
    dt_days = (current_epoch_s - previous_epoch_s) / 86400.0
    if dt_days <= 0:
        return 0.0
    return (current_total_mm - previous_total_mm) / dt_days


def build_node_features(
    device_id: str,
    displacement: DisplacementMM,
    current_epoch_s: float,
    h_acc_m: float,
    previous_displacement: DisplacementMM | None = None,
    previous_epoch_s: float | None = None,
    vibration: VibrationMetrics | None = None,
    tilt: TiltDeg | None = None,
) -> NodeFeatureVector:
    """Titik gabung tunggal — setiap komponen datang dari modul yang
    SUDAH diverifikasi terpisah (displacement.py, vibration.py, tilt.py).
    `vibration`/`tilt` opsional (None) karena secara alami tidak selalu
    ada di window yang sama sebagai displacement — vibration cuma ada
    saat event getaran/blast, tilt dari window "tenang" (periodic
    upload) yang mungkin belum tersedia untuk epoch ini. None -> 0.0
    di vektor akhir (lihat docstring NodeFeatureVector.velocity_mm_day
    untuk alasan yang sama)."""
    velocity = compute_velocity_mm_day(
        displacement.total_mm,
        previous_displacement.total_mm if previous_displacement else None,
        current_epoch_s, previous_epoch_s,
    )
    return NodeFeatureVector(
        device_id=device_id,
        de_mm=displacement.de_mm, dn_mm=displacement.dn_mm,
        du_mm=displacement.du_mm, total_mm=displacement.total_mm,
        velocity_mm_day=velocity,
        ppa_g=vibration.ppa_g if vibration else 0.0,
        ppv_mm_s=vibration.ppv_mm_s if vibration else 0.0,
        tilt_x_deg=tilt.tilt_x_deg if tilt else 0.0,
        tilt_y_deg=tilt.tilt_y_deg if tilt else 0.0,
        h_acc_m=h_acc_m,
    )
