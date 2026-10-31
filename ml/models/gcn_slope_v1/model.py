"""Arsitektur GCN — skema fitur SENSOR SUNGGUHAN (10 fitur,
node_feature_builder.py), bukan 15 fitur v2.6.0 lama yang tidak
kompatibel.

REVISI 2026-09-22 (permintaan eksplisit pengguna): ditulis ulang pakai
`torch` LANGSUNG — versi sebelumnya NumPy murni karena `torch` tidak
tersedia di sandbox pengembangan saat itu.

⚠️ CATATAN JUJUR PENTING: `torch` MASIH TIDAK TERSEDIA di sandbox saya
saat menulis file ini — kode di bawah TIDAK BISA saya jalankan/uji
sendiri, beda dari versi NumPy sebelumnya yang saya buktikan nyata
lewat 9 test yang benar-benar dijalankan. Untuk meminimalkan risiko
salah: setiap operasi di sini adalah TRANSLASI LANGSUNG dari logika
NumPy yang SUDAH terverifikasi (formula sama persis, cuma
`np.eye`->`torch.eye`, `@`->tetap `@` di torch, dst) — bukan logika
baru yang ditulis dari nol. TAPI ini tetap bukan pengganti pengujian
sungguhan. WAJIB dijalankan pengguna:
    pip install -r requirements.txt
    pytest tests/unit/test_gcn_slope_v1.py -v
dan laporkan hasilnya — jangan anggap "selesai" sampai itu dikonfirmasi.

Formula propagasi GCN standar (Kipf & Welling, 2017, "Semi-Supervised
Classification with Graph Convolutional Networks", ICLR): Ã=A+I,
row-normalize (konsisten dengan konvensi row_normalize() yang sudah
dipakai ml/pipeline/graph_builder/adjacency_strategy.py di seluruh
proyek ini, bukan symmetric D^-1/2..D^-1/2 versi asli paper).
"""

from __future__ import annotations

import os

import torch
import torch.nn as nn
import torch.nn.functional as F

from ml.domain.interfaces import GraphBatch, ModelInterface, PredictionResult

N_FEATURES = 10  # HARUS sama dengan len(node_feature_builder.FEATURE_NAMES) — dijaga eksplisit lewat test
HIDDEN_DIM = 16  # arbitrer, belum ada bukti empiris untuk angka "benar" karena belum ada data training


def add_self_loops_and_normalize(adjacency: torch.Tensor) -> torch.Tensor:
    """Ã = A + I, lalu row-normalize. Self-loop SENGAJA tidak ditambahkan
    di adjacency_strategy.py (didokumentasikan eksplisit di sana:
    "self-loop urusan arsitektur GCN") — ditambahkan di sini."""
    n = adjacency.shape[0]
    a_hat = adjacency + torch.eye(n, dtype=adjacency.dtype, device=adjacency.device)
    row_sums = a_hat.sum(dim=1, keepdim=True)
    safe_sums = torch.where(row_sums == 0, torch.ones_like(row_sums), row_sums)
    return a_hat / safe_sums


class GraphConvLayer(nn.Module):
    """Satu layer graph convolution: H' = Â @ Linear(X). `nn.Linear`
    dipakai (bukan matriks weight/bias manual) — cara idiomatik PyTorch,
    otomatis dapat inisialisasi bobot standar (Kaiming uniform) dan
    kompatibel `state_dict()` untuk save/load checkpoint."""

    def __init__(self, in_features: int, out_features: int) -> None:
        super().__init__()
        self.linear = nn.Linear(in_features, out_features)

    def forward(self, x: torch.Tensor, adjacency: torch.Tensor) -> torch.Tensor:
        a_norm = add_self_loops_and_normalize(adjacency)
        return self.linear(a_norm @ x)


class GCNSlopeV1(nn.Module, ModelInterface):
    """2-layer GCN — arsitektur sama seperti v2.6.0 lama ("2-layer GCN"
    per ways-of-working), skema fitur beda total (10 fitur sensor asli).
    Registrasi TERPISAH dari model_type="gcn" (stub produksi lama, TIDAK
    disentuh — lihat ml/models/gcn_baseline/model.py)."""

    def __init__(self) -> None:
        nn.Module.__init__(self)
        self.conv1 = GraphConvLayer(N_FEATURES, HIDDEN_DIM)
        self.conv2 = GraphConvLayer(HIDDEN_DIM, 2)  # 2-class output
        self._loaded_version: str | None = None

    @property
    def model_type(self) -> str:
        return "gcn_slope_v1"

    def input_contract(self) -> dict:
        return {"n_features": N_FEATURES, "n_classes": 2, "supports_variable_n": True}

    def load_weights(self, version_id: str, artifact_path: str) -> None:
        """Checkpoint via torch.save(model.state_dict(), path) — HARUS
        raise kalau file tidak ada (ModelRegistry.activate() bergantung
        ini). TIDAK ADA checkpoint terlatih sama sekali saat ini (belum
        ada data training)."""
        if not os.path.exists(artifact_path):
            raise FileNotFoundError(f"checkpoint tidak ditemukan: {artifact_path}")
        state_dict = torch.load(artifact_path, map_location="cpu")
        self.load_state_dict(state_dict)
        self._loaded_version = version_id

    def initialize_random_weights(self, seed: int = 42) -> None:
        """HANYA untuk verifikasi mekanisme forward pass (test/demo) —
        BUKAN jalur produksi. Prediksi dari sini TIDAK BERARTI APA-APA
        secara klinis — bobot acak, bukan hasil training. Re-inisialisasi
        layer eksplisit (bukan cuma torch.manual_seed sebelum __init__
        yang sudah lewat) supaya determinisme terjamin dipanggil ulang."""
        torch.manual_seed(seed)
        self.conv1 = GraphConvLayer(N_FEATURES, HIDDEN_DIM)
        self.conv2 = GraphConvLayer(HIDDEN_DIM, 2)
        self._loaded_version = f"random-init-seed-{seed}-NOT-FOR-PRODUCTION"

    def predict(self, batch: GraphBatch) -> PredictionResult:
        if self._loaded_version is None:
            raise RuntimeError("predict() called before load_weights() — registry bug, not caller error")

        x = torch.tensor(batch.node_features, dtype=torch.float32)
        adjacency = torch.tensor(batch.adjacency, dtype=torch.float32)
        if x.shape[1] != N_FEATURES:
            raise ValueError(f"node_features punya {x.shape[1]} fitur, model ini butuh {N_FEATURES}")

        self.eval()
        with torch.no_grad():
            h1 = F.relu(self.conv1(x, adjacency))
            h2 = torch.sigmoid(self.conv2(h1, adjacency))
        # h2 shape (N, 2) — kolom 1 = probabilitas kelas "risiko" (2-class,
        # 3-tier normal/siaga/bahaya adalah post-processing di luar model).
        risk_scores = h2[:, 1].tolist()

        return PredictionResult(
            device_ids=batch.device_ids,
            risk_scores=risk_scores,
            model_type=self.model_type,
            version_id=self._loaded_version,
        )
