# MAGRIS — Benchmark Variant A (single MQTT pub/sub)

Tujuan: **membuktikan dengan data** apakah arsitektur 1 broker MQTT (Variant A)
*scalable & efisien* untuk pemantauan lereng, di tiga sisi:

1. **Jaringan & pesan** — throughput (msg/dtk), latency **p50/p95/p99**, message loss.
2. **Resource server** — CPU / memori / Net I/O broker (dan DB).
3. **Kualitas koneksi perangkat** — jumlah koneksi konkuren, keberhasilan connect.

> **Prinsip inti eksperimen:** naikkan beban **bertahap sampai sesuatu benar-benar
> jenuh** (latency melonjak non-linear, error muncul, atau CPU broker mentok).
> Titik itu = **kapasitas Variant A**. Skripsi lama tidak pernah menemukannya
> (berhenti di 1000 device saat semua masih santai, dan pakai 1 koneksi berbagi).

Dua alat, dua peran:

| Alat | Mengukur | Kapan dipakai |
|---|---|---|
| **JMeter** (+plugin MQTT) | sisi klien: throughput, latency, error, koneksi | uji beban utama, laporan rapi untuk sidang |
| **emqtt-bench** (Docker) | kapasitas koneksi skala besar (Erlang, tahan puluhan ribu) | uji **sisi server / kapasitas** tanpa install |
| **`capture-stats.sh`** | sisi server: CPU/mem/Net broker & DB | **jalan bareng** kedua alat di atas |

`docker stats`-lah yang mengukur *server*. JMeter/emqtt-bench hanya menghasilkan beban.
**Selalu jalankan `capture-stats.sh` berbarengan** — kalau tidak, kamu tak punya
data resource server sama sekali.

---

## 0. Prasyarat

```bash
# stack Variant A harus hidup
cd infra/variant-a && docker compose up -d
docker ps        # pastikan magris-variant-a-mosquitto-1 & timescaledb-1 "Up"
```

Broker MQTT ada di `localhost:1883`.

> **Matikan `loadgen/fleet.py` selama uji beban** — kamu ingin mengukur broker di
> bawah beban JMeter/emqtt-bench, bukan bercampur dengan fleet simulasi.

---

## 1. Jalur A — JMeter (uji beban utama)

### 1.1 Install JMeter + plugin MQTT

1. **JMeter**: unduh dari <https://jmeter.apache.org/download_jmeter.cgi> (butuh Java 8+),
   extract, jalankan `bin/jmeter.bat` (Windows).
2. **Plugin MQTT** — dua cara:
   - **Plugins Manager** (disarankan): unduh `jmeter-plugins-manager.jar` ke
     `lib/ext/`, restart JMeter → *Options ▸ Plugins Manager* → cari **"MQTT"
     (by XMeter)** → Install.
   - **Manual**: unduh `mqtt-xmeter-*-jar-with-dependencies.jar`
     (github.com/emqx/mqtt-jmeter, rilis) → taruh di `lib/ext/` → restart.

### 1.2 Buka test plan

`File ▸ Open` → `bench/jmeter/slope-mqtt-loadtest.jmx`.

Isinya sudah disiapkan:
- **Thread Group "Devices"** — `${__P(devices,100)}` thread; **1 thread = 1 device**.
- **MQTT Connect** — `client_id_prefix=slope-dev-` + **suffix acak** → **client id unik**
  (ini yang memperbaiki cacat #1 skripsi lama: koneksi berbagi).
- **MQTT Publish** — topik `slope/lereng-load/<n>/data`, QoS 1, payload JSON sesuai skema.
- **Constant Timer** — jeda `rate_ms` (default 2000ms = tiap device kirim tiap 2 dtk).

> ⚠️ **Verifikasi di GUI dulu.** Nama properti plugin bisa beda antar versi. Buka tiap
> sampler, pastikan Server=`localhost`, Port=`1883`, dan field terisi wajar. Klik
> **Run (▶)** sekali di GUI dengan `devices=10` untuk memastikan hijau (bukan merah),
> baru lanjut ke mode CLI.

### 1.3 Jalankan sweep (mode CLI — ini yang dipakai untuk data resmi)

**Jangan** ambil data dari mode GUI (GUI boros memori & memengaruhi hasil). Pakai CLI:

```bash
cd bench

# tiap skala: jalankan capture-stats DI TERMINAL LAIN dulu, lalu JMeter.
# Terminal 1 (server-side):
bash capture-stats.sh 100dev 180

# Terminal 2 (client-side), bersamaan:
jmeter -n -t jmeter/slope-mqtt-loadtest.jmx \
       -Jdevices=100 -Jrate_ms=2000 -Jduration=180 \
       -l results/jmeter-100.jtl
```

> ⚠️ **`jmeter -l` MENAMBAHKAN ke file yang sudah ada, tidak menimpanya.**
> Kalau kamu mengulang satu skala tanpa menghapus `.jtl` lamanya, kedua run
> tergabung dalam satu file — koneksi terhitung dua kali lipat dan rentang
> waktunya melar mencakup jeda antar-run. **Hapus dulu sebelum re-run:**
>
> ```bash
> rm -f results/jmeter-4000.jtl        # WAJIB sebelum mengulang skala ini
> ```
>
> `summarize.py` sekarang mendeteksi ini (jeda menganggur ≥60s di dalam satu
> `.jtl`), memberi peringatan, dan hanya meringkas run terakhir — tapi jangan
> mengandalkan itu, hapus saja filenya.

> **Durasi `capture-stats.sh` harus LEBIH PANJANG dari durasi JMeter**, beri
> kelebihan ~60 detik. Kalau lebih pendek, puncak CPU bisa terlewat dan angka
> peak-nya menjadi terlalu rendah.

Ulangi untuk tiap titik sweep, **naikkan `devices`**:

```
devices = 100 → 300 → 600 → 1000 → 1500 → 2000 → 3000 ...
```

Berhenti menaikkan saat salah satu terjadi:
- **error MQTT muncul** (connect gagal / publish gagal) di ringkasan JMeter,
- **p95/p99 melonjak** jauh (mis. dari puluhan ms → ratusan/ribuan ms),
- **CPU broker mentok** ~100% di `capture-stats`.

> **Baca caveat plafon load-gen:** JMeter di 1 mesin mentok ~beberapa ribu thread
> (JVM). Jika **JMeter/CPU host** yang mentok tapi **CPU broker masih rendah**, itu
> batas *generator*, bukan broker — catat sebagai keterbatasan, lalu lanjut uji
> kapasitas pakai **emqtt-bench** (Jalur B) yang jauh lebih hemat per-koneksi.

### 1.4 Ringkas hasil

```bash
python summarize.py --label 100dev \
    --jtl results/jmeter-100.jtl --stats results/stats-100dev.csv
```

Keluarannya termasuk **satu baris tabel markdown** siap tempel ke §4.

`--warmup` (default **60** detik) membuang fase ramp-up sebelum menghitung apa
pun — koneksi yang sedang dibuka mencemari ekor persentil. Pakai `--warmup 0`
hanya kalau kamu memang ingin melihat data mentah termasuk ramp-up.

Regenerasi seluruh tabel sekaligus:

```bash
cd bench
for n in 100 300 600 1000 1500 2000 3000 4000; do
  python summarize.py --label ${n}dev \
      --jtl results/jmeter-$n.jtl --stats results/stats-${n}dev.csv
done
```

Ambil baris `| ... |` terakhir dari tiap blok, tempel ke §4.

**Yang harus kamu periksa di outputnya:**

| Baris | Artinya |
|---|---|
| `conns : N established` | N wajib = jumlah device. Kalau kurang, ada koneksi gagal. |
| `... re-connect artefacts ignored` | Normal untuk `.jtl` lama (sebelum Once Only). Harus **0** di run baru. |
| `broker : n/a - capture-stats did not overlap` | Run tidak sah. Ulangi, `capture-stats.sh` dulu baru JMeter. |
| `! N genuine connection failures` | Sinyal jenuh — bandingkan CPU broker vs CPU host untuk tahu siapa yang menyerah. |

---

## 2. Jalur B — emqtt-bench (uji kapasitas / sisi server)

Untuk mendorong broker sampai jenuh **tanpa** batas JVM JMeter. Berbasis Docker,
tak perlu install apa pun selain Docker.

### 2.1 Uji throughput publisher

```bash
# 2000 koneksi publisher, tiap 1000ms, payload 256 byte, ke broker host
docker run --rm --network host emqx/emqtt-bench \
  pub -h 127.0.0.1 -p 1883 -c 2000 -i 10 -I 1000 -s 256 -q 1 -t 'slope/bench/%i/data'
```
- `-c` jumlah klien (koneksi unik `%i`) · `-i` interval spawn (ms) · `-I` interval publish (ms)
- `-s` ukuran payload (byte) · `-q` QoS · `-t` topik (`%i` = nomor klien)

> **Windows:** `--network host` tidak sepenuhnya didukung Docker Desktop. Jika broker
> tak terjangkau, ganti `-h 127.0.0.1` → `-h host.docker.internal` dan hapus
> `--network host`.

### 2.2 Uji jumlah koneksi (dimensi #3 — kualitas koneksi)

Berapa koneksi konkuren yang sanggup dipegang broker?

```bash
# buka 20.000 koneksi idle, tahan; lihat berapa yang sukses + biaya CPU/mem broker
docker run --rm emqx/emqtt-bench \
  conn -h host.docker.internal -p 1883 -c 20000 -i 5
```

### 2.3 Uji latency end-to-end (sub + pub)

emqtt-bench `sub` melaporkan latency e2e bila `pub` memakai timestamp:

```bash
# Terminal A: subscriber yang mengukur latency
docker run --rm emqx/emqtt-bench sub -h host.docker.internal -p 1883 -c 100 -t 'slope/bench/+/data'
# Terminal B: publisher
docker run --rm emqx/emqtt-bench pub -h host.docker.internal -p 1883 -c 100 -I 1000 -s 256 -t 'slope/bench/%i/data'
```

**Selalu** jalankan `bash capture-stats.sh <label> <detik>` berbarengan di terminal lain.

---

## 3. Yang WAJIB dicatat tiap run

| Kolom | Sumber |
|---|---|
| device / koneksi | parameter `-Jdevices` atau `-c` |
| throughput (msg/dtk) | `summarize.py` (dari .jtl) atau output emqtt-bench |
| p50 / p95 / p99 latency (ms) | `summarize.py` / emqtt-bench sub |
| error rate (%) | ringkasan JMeter / emqtt-bench |
| **CPU broker peak (%)** | `capture-stats` → `summarize.py` |
| **Mem broker peak** | idem |
| koneksi sukses / gagal | log broker / output tool |

---

## 4. Tabel hasil (isi sendiri saat menjalankan)

Kolomnya sama persis dengan urutan yang dicetak `summarize.py`, jadi barisnya
tinggal ditempel. `koneksi` **harus** sama dengan jumlah device — itu buktinya
1 device = 1 koneksi unik (perbaikan cacat #1 skripsi lama).

Semua baris di bawah memakai **test plan yang sama** (connect di Once Only),
`duration=300`, warm-up 60 detik dibuang, `err 0%` di seluruh titik, dan
`koneksi` selalu persis sama dengan jumlah device.

### 4a. Sweep jumlah device (`rate_ms=2000`)

| Skala | koneksi | msg/dtk | MB/dtk | p50 | p95 | p99 | max | err% | CPU peak | Mem peak |
|---|---|---|---|---|---|---|---|---|---|---|
| 100dev | 100 | 50 | 0.01 | 1 | 2 | 2 | 21 | 0.000% | 14% | 13 MiB |
| 300dev | 300 | 148 | 0.04 | 1 | 2 | 2 | 12 | 0.000% | 13% | 14 MiB |
| 600dev | 600 | 299 | 0.07 | 1 | 2 | 3 | 22 | 0.000% | 13% | 16 MiB |
| 1000dev | 1000 | 497 | 0.12 | 2 | 3 | 4 | 34 | 0.000% | 17% | 17 MiB |
| 1500dev | 1500 | 745 | 0.18 | 2 | 4 | 6 | 22 | 0.000% | 18% | 20 MiB |
| 2000dev | 2000 | 993 | 0.24 | 2 | 4 | 6 | 32 | 0.000% | 19% | 22 MiB |
| 3000dev | 3000 | 1472 | 0.36 | 2 | 3 | 5 | 70 | 0.000% | 20% | 26 MiB |
| 4000dev | 4000 | 1960 | 0.48 | 2 | 5 | 9 | 45 | 0.000% | 26% | 31 MiB |
| 5000dev | 5000 | 2392 | 0.59 | 3 | 6 | 10 | 53 | 0.000% | 28% | 35 MiB |
| 6000dev | 6000 | 2785 | 0.68 | 2 | 5 | 8 | 44 | 0.000% | 32% | 40 MiB |

**Jumlah device bukan batasnya.** Sampai 6000 koneksi konkuren, p95 tetap 2–6 ms,
p99 ≤ 10 ms, dan CPU broker naik mulus 13% → 32%. Memori naik linier tapi hanya
mencapai 40 MiB. Tidak ada tanda jenuh di sumbu ini sama sekali.

> **Catatan reproduktibilitas.** Titik `4000dev` awalnya terukur p95 11 ms /
> p99 27 ms / CPU 61% — melanggar monotonisitas, karena 5000dev dan 6000dev
> justru lebih ringan. Setelah di-run ulang dengan konfigurasi identik hasilnya
> jadi p95 5 / p99 9 / CPU 26%, yang konsisten dengan tetangganya. Ini outlier
> kedua yang hilang setelah pengulangan (`1500dev` yang pertama), jadi **satu run
> per titik tidak cukup** pada mesin ini — anggap sebagai batasan metodologis dan
> laporkan di Batasan.
>
> Klaim "lutut pertama di 4000 device" pada revisi dokumen sebelumnya **ditarik**:
> penyebabnya gangguan run, bukan jumlah device.

Throughput tercapai ~95% dari target teoretis (`devices/2`) sampai 5000, turun
ke 93% di 6000 — indikasi awal generator mulai tertinggal, bukan broker.

### 4b. Sweep laju pesan (4000 device) — **di sinilah titik jenuhnya**

Lima titik pada 4000 device. Baris `rate_ms=2000` adalah run `4000dev` dari §4a —
konfigurasinya memang identik, jadi dipakai sebagai jangkar bawah, bukan run
duplikat.

| rate_ms | target msg/dtk | tercapai | MB/dtk | p50 | p95 | p99 | max | err% | CPU peak | Mem peak |
|---|---|---|---|---|---|---|---|---|---|---|
| 2000 | 2 000 | 1 960 | 0.48 | 2 | 5 | 9 | 45 | 0.000% | 26% | 31 MiB |
| 1000 | 4 000 | 3 893 | 0.96 | 3 | 9 | 18 | 86 | 0.000% | 38% | 31 MiB |
| 500 | 8 000 | 7 677 | 1.89 | 5 | 20 | 47 | 257 | 0.000% | 74% | 31 MiB |
| 250 | 16 000 | **11 018** | 2.71 | **96** | **175** | **222** | 373 | 0.000% | **108%** | 38 MiB |
| 100 | 40 000 | **11 473** | 2.82 | **232** | **304** | **370** | 521 | 0.000% | **109%** | 45 MiB |

CPU broker naik monoton 26% → 38% → 74% → 108% → 109%, dan mendatar tepat ketika
throughput mendatar. Kurva ini yang menjadi bukti utama Bab 4.

**Titik jenuh Variant A pada hardware ini: ~11 000–11 500 msg/dtk, terbatas CPU
satu core broker.** Tiga bukti yang saling menguatkan:

1. **Throughput mendatar.** `rate_ms=250` meminta 16 000 msg/dtk dan dapat
   11 018; `rate_ms=100` meminta 40 000 — 2.5× lebih banyak — dan hanya dapat
   11 473. Menaikkan permintaan tidak lagi menaikkan hasil.
2. **CPU broker ~108%.** Mosquitto single-threaded, jadi ~100% berarti **satu
   core habis**. Broker tidak bisa lebih cepat apa pun yang dilakukan generator —
   ini yang membuat atribusi ke broker sah *tanpa* perlu data CPU host.
3. **Latensi melengkung non-linier tepat di situ.** p50 melompat 5 → 96 → 232 ms,
   p99 47 → 222 → 370 ms. Perilaku antrean klasik setelah saturasi.

**Tidak ada pesan hilang** (err 0.000% di semua titik). QoS 1 mengubah kelebihan
beban menjadi *backpressure dan latensi*, bukan kehilangan data — temuan
tersendiri, dan relevan untuk sistem peringatan dini.

**Batasnya laju pesan, bukan bandwidth.** Di titik jenuh trafiknya hanya
~2.8 MB/dtk. Broker menyerah pada *jumlah pesan per detik*, bukan volume byte.
Konsekuensinya: sweep ukuran payload akan menemukan plafon yang sama sekali
berbeda — dan itu belum diuji (lihat `context.md` §14).

**Cara membaca (untuk bab Analisis skripsi):**
- Selama p95/p99 **datar** dan error 0% sambil throughput naik → broker **masih efisien**.
- Titik di mana **p99 mulai melengkung naik / error > 0 / CPU broker ~100%** =
  **titik jenuh Variant A** pada hardware ini. Itu jawaban kuantitatif atas
  pertanyaanmu.
- Jika broker jenuh di angka **jauh di atas** kebutuhan nyata (puluhan lereng ×
  beberapa sensor) → Variant A **cukup & efisien** untuk kasus ini; Kafka (Variant
  B/C) baru relevan di skala jauh lebih besar. Itulah kontribusi tesis: **kapan 1
  MQTT cukup, kapan tidak.**

## 5. Kejujuran metodologis (tulis di Batasan)
- Semua angka **relatif terhadap hardware & konfigurasi ini** (1 mesin, Docker
  Desktop, mosquitto default) — laporkan spesifikasi mesin.
- Load-gen 1-mesin punya plafon sendiri; bila generator jenuh lebih dulu dari
  broker, itu batas pengukuran, bukan batas arsitektur — sebutkan eksplisit.
- Gunakan **persentil (p95/p99), bukan rata-rata** — rata-rata menyembunyikan ekor
  lonjakan yang justru penting untuk sistem peringatan dini.
