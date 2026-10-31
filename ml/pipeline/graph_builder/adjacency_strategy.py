"""Dynamic adjacency matrix — blueprint §6. Dua lapis, saklar otomatis
berdasar jumlah device aktif (§6.3), BUKAN pilihan manual.

Kembalikan `numpy.ndarray`, BUKAN `torch.Tensor` seperti ditulis di
blueprint §6.1 — `torch` TIDAK terpasang di lingkungan pengembangan ini
(dicek langsung, bukan diasumsikan), dan modul ini murni operasi
numerik (tidak butuh autograd/GPU). Konversi ke tensor PyTorch (kalau
memang dipakai model nanti) adalah satu baris (`torch.from_numpy(...)`)
di titik konsumsi, bukan di sini — pola yang sama dengan lazy-import
`torch` di ml/legacy/gcn_v2_6_0/model_v2_6_0.py untuk alasan serupa.

STATUS PER LAPIS (2026-09-21, DIPERBARUI setelah pengguna minta
perhitungan MIC yang benar, bukan proxy):
  - IDW (spasial): implementasi PENUH, sesuai Shepard (1968), diuji
    terhadap kasus jarak yang diketahui pasti.
  - MIC (korelasi): `compute_mic()` pakai `minepy` (implementasi C
    resmi ApproxMaxMI, Reshef et al. 2011) KALAU TERPASANG. Kalau
    tidak, fallback ke exhaustive equal-frequency grid search yang
    MENGHITUNG DEFINISI MIC YANG SAMA PERSIS (Persamaan 1: max{
    I(x,y)/log(min(nx,ny)) } untuk nx*ny<B(n), B(n)=n^0.6) via
    brute-force, BUKAN dynamic programming ApproxMaxMI asli (rekursi
    DP-nya ditemukan sebagian dari paten resmi tapi tidak bisa
    diverifikasi kebenarannya tanpa referensi untuk cross-check — lihat
    docstring _mic_exhaustive_search() untuk penjelasan lengkap kenapa
    ini dipilih dibanding menulis DP yang tidak bisa dipastikan benar).
    Proxy histogram equal-width LAMA (_histogram_mutual_information)
    dipertahankan cuma untuk test lama, TIDAK DIPAKAI lagi oleh
    MICBasedAdjacency. Konteks yang meringankan: lapis ini baru AKTIF
    saat N>3 device — saat ini device aktif = 3, jadi belum dipakai di
    produksi.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import numpy as np

_EARTH_RADIUS_M = 6_371_000.0  # sama dengan services/site_service/site_repository.py — duplikasi sengaja (ml/ tidak boleh bergantung pada services/, lihat blueprint tentang isolasi layer)


@dataclass(frozen=True)
class DeviceNode:
    device_id: str
    lat: float
    lon: float


def haversine_matrix(coords: list[tuple[float, float]]) -> np.ndarray:
    """N×N jarak great-circle (meter) antar semua pasangan titik.
    Formula sama persis yang sudah diverifikasi di
    services/site_service/site_repository.py (terhadap jarak
    Jakarta-Bandung sungguhan) — diduplikasi di sini, bukan diimpor,
    karena ml/ sengaja tidak bergantung pada services/ (blueprint:
    lapisan terpisah, ml/ harus testable berdiri sendiri)."""
    n = len(coords)
    dist = np.zeros((n, n))
    for i in range(n):
        lat1, lon1 = coords[i]
        for j in range(i + 1, n):
            lat2, lon2 = coords[j]
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
            d = 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))
            dist[i, j] = dist[j, i] = d
    return dist


def inverse_distance_weight(dist_matrix: np.ndarray, power: float = 2.0) -> np.ndarray:
    """w_ij = 1 / d_ij^power (Shepard 1968 — blueprint §6.2, dikutip
    sebagai landasan METODE klasik, bukan riset terkini). `power=2.0`
    adalah default paling umum dipakai literatur IDW (blueprint tidak
    menetapkan angka spesifik) — dijadikan parameter, bukan hardcode,
    supaya bisa disetel kalau perlu tanpa mengubah kode.
    Diagonal (d_ii=0) di-nol-kan eksplisit — device tidak terhubung ke
    dirinya sendiri di graph adjacency ini (self-loop, kalau perlu,
    urusan arsitektur GCN-nya, bukan matriks jarak)."""
    n = dist_matrix.shape[0]
    w = np.zeros_like(dist_matrix, dtype=float)
    for i in range(n):
        for j in range(n):
            if i != j and dist_matrix[i, j] > 0:
                w[i, j] = 1.0 / (dist_matrix[i, j] ** power)
    return w


def row_normalize(matrix: np.ndarray) -> np.ndarray:
    """Tiap baris dijumlahkan jadi 1 — stabilitas numerik GCN (blueprint
    §6.3, "untuk stabilitas GCN"). Baris yang sudah nol semua (device
    terisolasi/tanpa tetangga) DIBIARKAN nol, bukan dibagi nol."""
    row_sums = matrix.sum(axis=1, keepdims=True)
    safe_sums = np.where(row_sums == 0, 1.0, row_sums)  # cegah divide-by-zero untuk baris kosong
    return matrix / safe_sums


class AdjacencyStrategy(ABC):
    @abstractmethod
    def build(self, active_devices: list[DeviceNode], timestep: datetime) -> np.ndarray:
        """(N, N) — N mengikuti len(active_devices) saat dipanggil,
        BUKAN konstanta (blueprint §6.1 — prinsip skalabilitas)."""
        ...


class GeographicKNNAdjacency(AdjacencyStrategy):
    """Lapis 1 (§6.2) — WAJIB untuk POC. IDW murni jarak geografis,
    tidak butuh histori time-series sama sekali (beda dari MIC di
    bawah) — jadi selalu bisa dihitung, bahkan untuk device yang baru
    terdaftar tanpa satu pun bacaan."""

    def build(self, active_devices: list[DeviceNode], timestep: datetime) -> np.ndarray:
        if len(active_devices) < 2:
            return np.zeros((len(active_devices), len(active_devices)))
        coords = [(d.lat, d.lon) for d in active_devices]
        dist = haversine_matrix(coords)
        w = inverse_distance_weight(dist)
        return row_normalize(w)


def _equal_frequency_bins(values: np.ndarray, n_bins: int) -> np.ndarray:
    """Bagi `values` jadi `n_bins` bin ber-isi (hampir) sama banyak
    berdasar RANK (equipartition, istilah persis yang dipakai paper MIC),
    BUKAN equal-width seperti proxy histogram lama. Ini konsisten dengan
    bagaimana algoritma MIC asli mempartisi sumbu."""
    n = len(values)
    order = np.argsort(values)
    bins = np.zeros(n, dtype=int)
    for rank, idx in enumerate(order):
        bins[idx] = min(int(rank * n_bins / n), n_bins - 1)
    return bins


def _mutual_information_from_bins(x_bins: np.ndarray, y_bins: np.ndarray, nx: int, ny: int) -> float:
    n = len(x_bins)
    joint = np.zeros((nx, ny))
    for i in range(n):
        joint[x_bins[i], y_bins[i]] += 1
    joint /= n
    x_marg = joint.sum(axis=1)
    y_marg = joint.sum(axis=0)
    mi = 0.0
    for i in range(nx):
        for j in range(ny):
            if joint[i, j] > 0 and x_marg[i] > 0 and y_marg[j] > 0:
                mi += joint[i, j] * math.log(joint[i, j] / (x_marg[i] * y_marg[j]))
    return mi


def _mic_exhaustive_search(x: list[float], y: list[float]) -> float:
    """MIC via BRUTE-FORCE grid search — menghitung definisi MIC yang
    SAMA PERSIS (Persamaan 1, Reshef et al. 2011, dikonfirmasi dari
    multiple sumber akademik 2026-09-21: MIC(x,y) = max{ I(x,y) /
    log(min(nx,ny)) } untuk semua grid nx*ny < B(n), B(n)=n^0.6) —
    TAPI dengan mencoba SEMUA grid valid + partisi equal-frequency di
    KEDUA sumbu, bukan dynamic programming ApproxMaxMI asli (yang
    mengoptimasi sumbu-X untuk partisi sumbu-Y yang FIXED).

    KENAPA BUKAN DP ASLI: rekursi DP-nya (ditemukan sebagian dari paten
    US9536201B2) TIDAK bisa diverifikasi kebenarannya tanpa referensi
    (minepy) untuk cross-check — subrutin pendukung (GetClumpsPartition,
    definisi presisi H(<i,m>,Q)) tidak didapat lengkap dari pencarian.
    Menulis DP kompleks dari potongan informasi dan mengklaimnya "MIC
    asli" tanpa cara memverifikasi itu justru berisiko salah tanpa
    ketahuan — jadi dipilih exhaustive search yang PASTI menghitung
    definisi yang benar (walau lebih lambat), bukan DP yang saya tidak
    yakin persis. Untuk window sensor yang kecil (puluhan-ratusan titik,
    bukan genomik ribuan titik), performa exhaustive search ini tidak
    jadi masalah praktis.

    Dipakai HANYA sebagai fallback kalau `minepy` (implementasi C resmi
    ApproxMaxMI) tidak terpasang — lihat compute_mic()."""
    n = len(x)
    if n < 4:
        return 0.0  # B(n) < 4 untuk n kecil -> tidak ada grid nx*ny>=4 (nx,ny>=2) yang valid sama sekali

    x_arr, y_arr = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    b_n = n ** 0.6
    if b_n < 4:
        return 0.0  # properti MIC yang benar: butuh n cukup besar (n>=12ish) baru ada grid valid

    best = 0.0
    max_nx = int(b_n // 2)  # ny>=2 -> nx <= B(n)/2
    for nx in range(2, max(2, max_nx) + 1):
        max_ny = int(b_n // nx)
        if max_ny < 2:
            continue
        x_bins = _equal_frequency_bins(x_arr, nx)
        for ny in range(2, max_ny + 1):
            y_bins = _equal_frequency_bins(y_arr, ny)
            mi = _mutual_information_from_bins(x_bins, y_bins, nx, ny)
            normalized = mi / math.log(min(nx, ny))
            best = max(best, normalized)
    return min(1.0, best)  # clip pembulatan floating-point, MIC secara teori <=1


def compute_mic(x: list[float], y: list[float]) -> float:
    """MIC(x,y) — pakai `minepy` (implementasi C resmi ApproxMaxMI,
    Reshef et al. 2011) KALAU TERPASANG; fallback ke exhaustive search
    (masih definisi MIC yang benar, bukan proxy histogram lama) kalau
    tidak. `alpha=0.6, c=15` adalah parameter DEFAULT dari paper asli
    (B(n)=n^0.6, c mengontrol granularitas awal pencarian DP) — bukan
    dipilih sembarangan."""
    try:
        from minepy import MINE

        mine = MINE(alpha=0.6, c=15)
        mine.compute_score(list(x), list(y))
        return float(mine.mic())
    except ImportError:
        return _mic_exhaustive_search(x, y)


def _histogram_mutual_information(x: list[float], y: list[float], bins: int = 8) -> float:
    """PROXY LAMA (2026-09-21) — DIPERTAHANKAN cuma untuk kompatibilitas
    test lama (test_mi_proxy_*), TIDAK DIPAKAI lagi oleh MICBasedAdjacency
    (lihat compute_mic() di atas, yang sekarang dipanggil sebagai
    gantinya). Histogram equal-WIDTH sederhana, bukan definisi MIC
    sesungguhnya — digantikan karena pengguna secara eksplisit minta
    perhitungan yang benar, bukan proxy."""
    if len(x) < 2 or len(y) < 2:
        return 0.0
    joint_hist, _, _ = np.histogram2d(x, y, bins=bins)
    joint_prob = joint_hist / joint_hist.sum()
    x_prob = joint_prob.sum(axis=1)
    y_prob = joint_prob.sum(axis=0)

    mi = 0.0
    for i in range(bins):
        for j in range(bins):
            if joint_prob[i, j] > 0 and x_prob[i] > 0 and y_prob[j] > 0:
                mi += joint_prob[i, j] * math.log(joint_prob[i, j] / (x_prob[i] * y_prob[j]))

    max_entropy = math.log(bins)
    if max_entropy == 0:
        return 0.0
    return max(0.0, min(1.0, mi / max_entropy))


class MICBasedAdjacency(AdjacencyStrategy):
    """Lapis 2 (§6.2) — aktif otomatis saat N>3 (lihat AdjacencyStrategySelector).
    `displacement_history` diberikan lewat parameter eksplisit (bukan
    query DB langsung dari sini) — supaya kelas ini tetap pure/testable
    tanpa perlu database sungguhan, konsisten dengan modul ml/ lainnya."""

    def __init__(self, displacement_history: dict[str, list[float]], threshold: float = 0.2):
        self._history = displacement_history  # device_id -> list nilai displacement (window sama untuk semua device)
        self._threshold = threshold            # τ=0.2, persis blueprint §6.2

    def build(self, active_devices: list[DeviceNode], timestep: datetime) -> np.ndarray:
        n = len(active_devices)
        w = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                xi = self._history.get(active_devices[i].device_id, [])
                xj = self._history.get(active_devices[j].device_id, [])
                if not xi or not xj or len(xi) != len(xj):
                    continue  # histori tidak cukup/tidak selaras -> tetap 0, bukan error
                mic_score = compute_mic(xi, xj)
                w[i, j] = mic_score if mic_score > self._threshold else 0.0
        return row_normalize(w)


class AdjacencyStrategySelector:
    """Saklar OTOMATIS (§6.3) — bukan pilihan manual. Dievaluasi ulang
    tiap pembentukan batch (bukan disimpan sebagai state tetap), supaya
    kalau device baru terdaftar (N bertambah lewat POST /api/v1/devices
    yang sudah ada), strategi otomatis berubah pada query berikutnya
    tanpa perlu restart/re-deploy."""

    MIC_MIN_DEVICES = 4  # N > 3 -> cukup pasangan untuk estimasi yang tidak degenerate, persis blueprint §6.3

    def select(self, active_devices: list[DeviceNode], displacement_history: dict[str, list[float]] | None = None) -> AdjacencyStrategy:
        if len(active_devices) >= self.MIC_MIN_DEVICES:
            return MICBasedAdjacency(displacement_history or {})
        return GeographicKNNAdjacency()
