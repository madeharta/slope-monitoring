# Menjalankan MAGRIS di laptop baru (Variant A)

Inti workflow untuk membuat stack **loadgen → MQTT → TimescaleDB → API → dashboard**
berjalan dari nol di mesin lain. Semua perintah dijalankan **dari root repo**
(`MAGRIS/`) kecuali disebut lain.

---

## 0. Prasyarat (install dulu)

| Software | Versi | Untuk |
|---|---|---|
| **Docker Desktop** | terbaru, **harus running** | broker MQTT + TimescaleDB |
| **Python** | 3.11+ | loadgen, db-writer, API |
| **Node.js + npm** | 18+ | build dashboard React (`frontend/dist` tidak di-commit) |
| **Git** | apa saja | ambil kode |

Cek: `docker --version`, `python --version`, `node --version`.

---

## 1. Ambil kode

```bash
git clone <url-repo> MAGRIS
cd MAGRIS
```

---

## 2. Nyalakan infra (DB + broker)

```bash
cd infra/variant-a
docker compose up -d
cd ../..
```

- Skema DB **otomatis dibuat** saat pertama kali (folder `init/` di-mount ke
  `docker-entrypoint-initdb.d` — hanya jalan kalau volume masih kosong).
- Verifikasi:
  ```bash
  docker ps    # harus ada magris-variant-a-mosquitto-1 & -timescaledb-1 (Up)
  ```
- Port yang dipakai: **1883** (MQTT), **5432** (Postgres/Timescale).

> **Kredensial:** default kode = default compose (`magris` / `magris_dev`), jadi
> **tanpa `.env` pun jalan**. Proyek ini **tidak** meng-auto-load `.env` di sisi
> Python — kalau mau ganti password, set sebagai **environment variable asli**
> (mis. PowerShell `$env:DB_PASSWORD="..."`) **sebelum** menjalankan compose *dan*
> proses Python, supaya keduanya sinkron.

---

## 3. Environment Python

```bash
python -m venv .venv
# aktifkan:
#   PowerShell : .\.venv\Scripts\Activate.ps1
#   Git Bash   : source .venv/Scripts/activate
pip install -r requirements.txt
pip install -r consumers/api/requirements.txt
```

`requirements.txt` (aiomqtt, asyncpg, pydantic) dipakai loadgen + db-writer;
`consumers/api/requirements.txt` (fastapi, uvicorn, asyncpg, **paho-mqtt**) untuk API.

---

## 4. Build dashboard (sekali, atau tiap UI berubah)

```bash
cd frontend
npm install
npm run build      # menghasilkan frontend/dist — disajikan oleh API
cd ..
```

---

## 5. Jalankan pipeline — **urutan penting**, tiap proses di terminal sendiri

Semua dengan **venv aktif** dan **dari root repo**.

```bash
# Terminal 1 — consumer: baca MQTT, tulis batch ke TimescaleDB
python consumers/db-writer/writer.py

# Terminal 2 — load generator: 24 device tersimulasi (1 koneksi/​device)
python loadgen/fleet.py

# Terminal 3 — API + dashboard (uvicorn di 127.0.0.1:8000)
python consumers/api/main.py
```

Urutan yang benar: **infra (§2) → db-writer → fleet → API**. db-writer dulu supaya
tidak ada pesan awal yang terlewat; API boleh kapan saja.

Buka **<http://127.0.0.1:8000>**.

---

## 6. Verifikasi sehat

```bash
docker ps                                   # 2 kontainer Up
curl http://127.0.0.1:8000/api/overview     # balas JSON (status lereng)
```
Dashboard menampilkan peta + status; klik marker / kartu warning → halaman detail
per-indikator.

---

## 7. Reset data (balik ke nol)

```bash
# cepat — kosongkan tabel measurement saja:
docker exec -it magris-variant-a-timescaledb-1 psql -U magris -d magris -c "TRUNCATE measurements;"

# full reset — buang volume, skema dibuat ulang dari init/:
cd infra/variant-a && docker compose down -v && docker compose up -d && cd ../..
```

---

## 8. Benchmark

Untuk uji skalabilitas/efisiensi Variant A (JMeter + emqtt-bench + docker stats):
lihat **`bench/BENCHMARK.md`**.

---

## 9. Troubleshooting

| Gejala | Sebab & solusi |
|---|---|
| `NotImplementedError: add_reader` (loadgen/writer) | Windows asyncio Proactor — sudah ditangani via `WindowsSelectorEventLoopPolicy`; jalankan lewat perintah di §5 (blok `__main__`), jangan impor `main()` manual. |
| API error `ModuleNotFoundError: paho` | `pip install -r consumers/api/requirements.txt` (paho-mqtt ada di sana). |
| Dashboard 404 / halaman kosong | `frontend/dist` belum ada — jalankan `npm run build` (§4) **sebelum** start API. |
| Port bentrok 1883/5432/8000 | hentikan proses lain, atau ubah mapping port di `docker-compose.yml` / env. |
| Python tak konek DB (password auth) | pastikan **tidak** set `DB_PASSWORD` berbeda hanya di file `.env` (tak dibaca Python) — samakan lewat env var asli, atau pakai default. |
| `docker compose` tak menemukan skema baru | skema hanya auto-init saat volume kosong; pakai `down -v` (§7) untuk memaksa ulang. |
| Tak ada Node.js di mesin target | build `frontend/dist` di mesin lain lalu salin foldernya, atau install Node. |
| emqtt-bench (Docker) tak jangkau broker host | pakai `-h host.docker.internal` (lihat `bench/BENCHMARK.md`). |

---

## Ringkasan satu layar

```bash
# 0) infra
cd infra/variant-a && docker compose up -d && cd ../..
# 1) python
python -m venv .venv && source .venv/Scripts/activate   # atau Activate.ps1
pip install -r requirements.txt -r consumers/api/requirements.txt
# 2) dashboard
cd frontend && npm install && npm run build && cd ..
# 3) jalan (3 terminal)
python consumers/db-writer/writer.py
python loadgen/fleet.py
python consumers/api/main.py     # -> http://127.0.0.1:8000
```
