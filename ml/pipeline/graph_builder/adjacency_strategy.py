from __future__ import annotations
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import numpy as np
_EARTH_RADIUS_M = 6_371_000.0
@dataclass(frozen=True)
class DeviceNode:
    device_id: str
    lat: float
    lon: float
def haversine_matrix(coords: list[tuple[float, float]]) -> np.ndarray:
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
    n = dist_matrix.shape[0]
    w = np.zeros_like(dist_matrix, dtype=float)
    for i in range(n):
        for j in range(n):
            if i != j and dist_matrix[i, j] > 0:
                w[i, j] = 1.0 / (dist_matrix[i, j] ** power)
    return w
def row_normalize(matrix: np.ndarray) -> np.ndarray:
    row_sums = matrix.sum(axis=1, keepdims=True)
    safe_sums = np.where(row_sums == 0, 1.0, row_sums)
    return matrix / safe_sums
class AdjacencyStrategy(ABC):
    @abstractmethod
    def build(self, active_devices: list[DeviceNode], timestep: datetime) -> np.ndarray:
        ...
class GeographicKNNAdjacency(AdjacencyStrategy):
    def build(self, active_devices: list[DeviceNode], timestep: datetime) -> np.ndarray:
        if len(active_devices) < 2:
            return np.zeros((len(active_devices), len(active_devices)))
        coords = [(d.lat, d.lon) for d in active_devices]
        dist = haversine_matrix(coords)
        w = inverse_distance_weight(dist)
        return row_normalize(w)
def _equal_frequency_bins(values: np.ndarray, n_bins: int) -> np.ndarray:
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
    n = len(x)
    if n < 4:
        return 0.0
    x_arr, y_arr = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    b_n = n ** 0.6
    if b_n < 4:
        return 0.0
    best = 0.0
    max_nx = int(b_n // 2)
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
    return min(1.0, best)
def compute_mic(x: list[float], y: list[float]) -> float:
    try:
        from minepy import MINE
        mine = MINE(alpha=0.6, c=15)
        mine.compute_score(list(x), list(y))
        return float(mine.mic())
    except ImportError:
        return _mic_exhaustive_search(x, y)
def _histogram_mutual_information(x: list[float], y: list[float], bins: int = 8) -> float:
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
    def __init__(self, displacement_history: dict[str, list[float]], threshold: float = 0.2):
        self._history = displacement_history
        self._threshold = threshold
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
                    continue
                mic_score = compute_mic(xi, xj)
                w[i, j] = mic_score if mic_score > self._threshold else 0.0
        return row_normalize(w)
class AdjacencyStrategySelector:
    MIC_MIN_DEVICES = 4
    def select(self, active_devices: list[DeviceNode], displacement_history: dict[str, list[float]] | None = None) -> AdjacencyStrategy:
        if len(active_devices) >= self.MIC_MIN_DEVICES:
            return MICBasedAdjacency(displacement_history or {})
        return GeographicKNNAdjacency()
