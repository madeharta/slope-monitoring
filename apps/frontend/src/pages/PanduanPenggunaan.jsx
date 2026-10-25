// User Guide — REVISI 2026-09-20 (kedua kalinya, per klarifikasi):
// sebelumnya seluruh halaman putih, keluar total dari tema dashboard.
// Sekarang: latar TETAP ikut style dashboard eksis (dark, `.l2`, TopBar
// global) — cuma BAGIAN TEKS yang dibungkus kartu putih, supaya tetap
// terasa satu aplikasi tapi teks panjang tetap enak dibaca (kontras
// tinggi di atas putih, bukan di atas gelap).

import { useNavigate } from "react-router-dom";

export default function PanduanPenggunaan() {
  const navigate = useNavigate();

  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate(-1)}>← Back</button>
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>User Guide</h1>
      </div>

      <div className="pgdoc2-card">
        <h1>User Guide MAGRIS LEWS</h1>
        <p className="pgdoc-lead">
          Ringkasan cara pakai dashboard pemantauan lereng dan peledakan.
        </p>

        <h2>Navigasi utama</h2>
        <p>
          Menu di kiri atas topbar berisi <strong>Overview</strong> (peta seluruh
          lereng dengan status live) dan <strong>Analytics</strong> (grafik
          historis per sensor untuk satu lereng), serta <strong>Alarms</strong>{" "}
          (daftar peringatan aktif). Klik salah satu untuk berpindah halaman.
        </p>

        <h2>Arti warna status</h2>
        <p>Setiap lereng diberi satu dari tiga status, ditentukan oleh pembacaan sensor terhadap ambang batas yang sudah dikonfigurasi:</p>
        <ul>
          <li><strong className="pgdoc-normal">Normal</strong> — dalam batas aman, tidak perlu tindakan.</li>
          <li><strong className="pgdoc-siaga">Warning</strong> — mendekati ambang batas, pantau lebih sering.</li>
          <li><strong className="pgdoc-bahaya">Danger</strong> — melewati ambang batas, perlu tindakan lapangan segera.</li>
        </ul>

        <h2>Membaca halaman detail lereng</h2>
        <p>
          Klik salah satu titik di peta atau kartu peringatan untuk membuka
          detail satu lereng. Halaman ini menampilkan:
        </p>
        <ul>
          <li><strong>3D resultant displacement</strong> — pergeseran GNSS rover terhadap titik referensi base, dalam milimeter. Ini indikator utama.</li>
          <li><strong>Tilt X (ADXL355)</strong> — kemiringan dari sensor accelerometer di rover.</li>
          <li><strong>Slope velocity</strong> — laju perubahan displacement (mm/hari), dihitung dari data GNSS, bukan sensor terpisah.</li>
          <li><strong>Rainfall, trailing 24h</strong> — curah hujan 24 jam terakhir dari Open-Meteo (data cuaca eksternal — sistem ini <em>tidak</em> punya rain gauge fisik).</li>
          <li><strong>Time to Failure</strong> — estimasi waktu keruntuhan berbasis proyeksi inverse-velocity, hanya muncul kalau lereng benar-benar sedang mempercepat pergerakannya.</li>
          <li><strong>Sensor Coverage</strong> — list of sensors actually installed at this site.</li>
        </ul>

        <h2>Indikator Live / Offline</h2>
        <p>
          Titik di sebelah tulisan <strong>Live</strong>/<strong>Offline</strong> (dekat
          jam, kanan atas) menunjukkan apakah dashboard sedang menerima
          data terbaru secara real-time.
        </p>

        <h2>Change display theme</h2>
        <p>
          Use the <strong>Editorial</strong>/<strong>ISA-101</strong> toggle in the
          top-right corner to change the dashboard color palette. Editorial
          uses warm, sepia tones suitable for presentations, while ISA-101
          uses neutral gray tones for long-term control room monitoring.
        </p>

        <h2>Profile &amp; Sign Out</h2>
        <p>
          Click your avatar (initials) in the top-right corner to view your
          account email and role, or select <strong>Sign Out</strong>.
          The session automatically expires after 15 minutes.
        </p>

        <h2>Known limitations</h2>
        <p>
          MFA verification is not yet integrated into the login flow
          (currently available through the API), and login sessions
          are not automatically renewed.
        </p>
      </div>
    </div>
  );
}
