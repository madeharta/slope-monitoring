import { useNavigate } from "react-router-dom";
export default function PanduanPenggunaan() {
  const navigate = useNavigate();
  return (
    <div className="l2 pgdoc2-page">
      <div className="l2head">
        <button className="pgdoc-back" onClick={() => navigate(-1)}>← Kembali</button>
        <h1 style={{ fontSize: 18, fontWeight: 650 }}>Panduan Penggunaan</h1>
      </div>
      <div className="pgdoc2-card">
        <h1>Panduan Penggunaan MAGRIS LEWS</h1>
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
          <li><strong className="pgdoc-siaga">Siaga</strong> — mendekati ambang batas, pantau lebih sering.</li>
          <li><strong className="pgdoc-bahaya">Bahaya</strong> — melewati ambang batas, perlu tindakan lapangan segera.</li>
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
          <li><strong>Sensor Coverage</strong> — daftar sensor yang benar-benar terpasang di lokasi ini.</li>
        </ul>
        <h2>Indikator Live / Offline</h2>
        <p>
          Titik di sebelah tulisan <strong>Live</strong>/<strong>Offline</strong> (dekat
          jam, kanan atas) menunjukkan apakah dashboard sedang menerima
          data terbaru secara real-time.
        </p>
        <h2>Ganti tema tampilan</h2>
        <p>
          Tombol <strong>Editorial</strong>/<strong>ISA-101</strong> di kanan atas
          mengganti palet warna dashboard — Editorial (hangat, sepia) untuk
          presentasi, ISA-101 (abu-abu netral) untuk pemantauan jangka
          panjang di ruang kontrol.
        </p>
        <h2>Profil &amp; keluar</h2>
        <p>
          Klik avatar (inisial) di kanan atas untuk melihat email/role
          akun Anda, atau untuk <strong>Keluar</strong>. Sesi otomatis berakhir
          setelah 15 menit.
        </p>
        <h2>Batasan yang perlu diketahui</h2>
        <p>
          Verifikasi MFA belum terhubung ke alur login (baru tersedia lewat
          API), dan sesi login belum diperpanjang otomatis.
        </p>
      </div>
    </div>
  );
}
