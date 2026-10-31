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
        <h1>MAGRIS LEWS User Guide</h1>
        <p className="pgdoc-lead">
          A guide to the slope and blasting monitoring dashboard.
          Data and indicators must be interpreted according to their validation status.
        </p>

        <h2>Main navigation</h2>
        <p>
          Use the top navigation menu to access <strong>Overview</strong>,
          <strong> Analytics</strong>, and <strong>Alarms</strong>.
          Overview displays monitored sites, Analytics presents sensor
          measurements, and Alarms provides available alert information.
        </p>

        <h2>Understanding status colors</h2>
        <p>
          Status indicators reflect configured monitoring rules.
          They do not independently establish slope safety.
        </p>
        <ul>
          <li><strong className="pgdoc-normal">Normal</strong> — no configured threshold exceedance is indicated.</li>
          <li><strong className="pgdoc-siaga">Warning</strong> — a configured warning threshold is indicated.</li>
          <li><strong className="pgdoc-bahaya">Danger</strong> — a configured danger threshold is indicated.</li>
        </ul>
        <p>
          Unverified, stale, or unavailable measurements must not be treated
          as evidence of safe conditions.
        </p>

        <h2>Understanding slope details</h2>
        <p>
          Open a monitored site from the map to review available measurements,
          time ranges, sensor coverage, and validation notices.
        </p>
        <ul>
          <li><strong>3D resultant displacement</strong> — GNSS-derived displacement in millimeters, when a validated reference and operational data are available.</li>
          <li><strong>Tilt X (ADXL355)</strong> — accelerometer-derived tilt measurements.</li>
          <li><strong>Slope velocity</strong> — a derived rate of displacement change, when valid displacement data are available.</li>
          <li><strong>Rainfall, trailing 24h</strong> — external Open-Meteo rainfall estimates, not measurements from an on-site rain gauge.</li>
          <li><strong>Time to Failure</strong> — an experimental inverse-velocity estimate that requires appropriate data and validation; it is not a guaranteed failure prediction.</li>
          <li><strong>Sensor Coverage</strong> — information about installed monitoring hardware.</li>
        </ul>

        <h2>Live / Offline indicator</h2>
        <p>
          The <strong>Live</strong>/<strong>Offline</strong> indicator shows
          the dashboard connection state. It does not guarantee that every
          sensor is reporting fresh or validated measurements.
        </p>

        <h2>Change display theme</h2>
        <p>
          Use the <strong>Editorial</strong>/<strong>ISA-101</strong> theme control
          in the top-right corner to switch between display palettes.
          Editorial uses warm tones, while ISA-101 uses neutral gray tones.
        </p>

        <h2>Profile &amp; Sign Out</h2>
        <p>
          Select your avatar in the top-right corner to view account
          information or choose <strong>Sign Out</strong>.
          Session expiration depends on the active authentication configuration.
        </p>


        <h2>Sensor Monitoring &amp; Analytics</h2>
        <ol>
          <li>Select <strong>Analytics</strong> in the navigation menu.</li>
          <li>Choose a monitoring site and device.</li>
          <li>Select a time range: 1h, 6h, 24h, 7d, all available, or Custom.</li>
          <li>Filter by GNSS, acceleration, fix type, validation state, or quality state where applicable.</li>
          <li>Apply the query and inspect the available charts and measurements.</li>
        </ol>
        <p>
          This page includes GNSS observations, satellite signal quality,
          BASE–ROVER synchronization, coordinate charts, and acceleration
          waveforms where data are available. Experimental results are not
          equivalent to validated slope displacement.
        </p>

        <h2>Historical Slope Measurements</h2>
        <ol>
          <li>Open a site from Overview or Sites.</li>
          <li>Select a preset range: 6h, 24h, 3d, or 7d.</li>
          <li>Use a custom date range to inspect older measurements.</li>
          <li>Check the last recorded measurement and data freshness.</li>
        </ol>
        <p>
          Empty charts may indicate that no technical sensor measurements
          exist within the selected interval. External weather data may
          still be displayed. An empty interval does not prove sensor failure
          or slope safety.
        </p>

        <h2>Weather Station</h2>
        <ol>
          <li>Open <strong>Weather Station</strong> from the navigation menu.</li>
          <li>Select the start and end dates and times in WIB.</li>
          <li>Open a weather metric using its <strong>Explore</strong> control.</li>
          <li>Review the historical chart and observation table.</li>
          <li>Use timestamp sorting and pagination to inspect observations.</li>
        </ol>
        <p>
          Weather Station displays Weather Underground observations and
          refreshes automatically according to its configured collection
          interval. Weather metrics do not independently trigger operational
          slope alarms. This module is separate from the external Open-Meteo
          rainfall information shown elsewhere in the dashboard.
        </p>

        <h2>Experimental PPK Results</h2>
        <ol>
          <li>Open <strong>PPK Technical Results</strong>.</li>
          <li>Enter the site ID and select the rover.</li>
          <li>Choose All available, 24h, 7d, or 30d.</li>
          <li>Select a row limit and use Refresh to load available results.</li>
          <li>Inspect solution quality, epoch history, uncertainty,
          and reproducibility provenance.</li>
        </ol>
        <p>
          FIX, FLOAT, and SINGLE describe GNSS solution quality classes.
          The timeline uses elapsed GPST. Formal solution uncertainty
          is not independently verified positioning accuracy.
          Results marked PROVISIONAL_SPP or unvalidated are technical
          research outputs, not operational displacement measurements.
        </p>

        <h2>BASE Reference Management</h2>
        <ol>
          <li>Open BASE Reference Management from the PPK area.</li>
          <li>Select the monitoring site and BASE device.</li>
          <li>Choose Load history to inspect coordinate versions.</li>
          <li>Authorized Operator or Admin users may submit a new
          coordinate version with latitude, longitude, ellipsoidal
          height, source, effective time, and supporting notes.</li>
          <li>Review the recorded source and validation state.</li>
        </ol>
        <p>
          Submitting survey-derived or provisional coordinates does not
          automatically validate or activate an operational BASE reference.
          Existing versions remain preserved for traceability.
        </p>

        <h2>Upload History</h2>
        <ol>
          <li>Open <strong>Uploads</strong>.</li>
          <li>Search by filename or device ID.</li>
          <li>Filter by GNSS/acceleration data type, 4G/LoRa mode,
          and processing status.</li>
          <li>Review matching records and use pagination.</li>
          <li>Select Reset to clear filters.</li>
        </ol>
        <p>
          This view documents upload and processing history.
          A processed status does not establish field validation.
        </p>

        <h2>Blast Monitoring</h2>
        <p>
          Open <strong>Blast</strong> to access the available blast command
          controls. Select the relevant site and review the displayed
          form and feedback before taking an authorized action.
          This section should only be used according to the site's
          established operational procedures.
        </p>

        <h2>Devices &amp; Administration</h2>
        <p>
          Open <strong>Devices</strong> to search by device ID, filter
          by site or connection status, and inspect registered devices.
          Authorized administrators can access device management functions.
          Registration and deletion must follow the project's data
          governance procedures.
        </p>
        <p>
          Administrators can use <strong>Register New Site</strong> to enter
          site information and review nearby-site warnings. The
          <strong> Users</strong> page provides account management controls.
          <strong> Settings</strong> provides site and device configuration,
          including available battery calibration settings.
        </p>

        <h2>MFA &amp; Audit Log</h2>
        <p>
          The MFA enrollment page provides a manual authenticator setup
          key and a six-digit code verification step. Enrollment alone
          must not be interpreted as proof that MFA is enforced during login.
        </p>
        <p>
          Use <strong>Audit Log</strong> to review recorded actions, filter
          by action or actor email, and navigate result pages.
        </p>

        <h2>Troubleshooting</h2>
        <ul>
          <li><strong>No measurements:</strong> check the site, device,
          selected time range, and latest available timestamp.</li>
          <li><strong>Stale data:</strong> do not interpret the last
          recorded value as a live measurement.</li>
          <li><strong>PPK unavailable:</strong> check the displayed API
          availability and validation information.</li>
          <li><strong>Authentication error:</strong> verify access permissions
          and session status.</li>
          <li><strong>Failed upload processing:</strong> inspect the
          processing status and available diagnostic information.</li>
        </ul>

        <h2>Known limitations</h2>
        <p>
          The MFA enrollment feature is separate from MFA verification during
          login. Historical GNSS/PPK results marked provisional or unvalidated
          are research outputs, not approved operational displacement measurements.
          Do not use unvalidated results as the sole basis for safety decisions.
        </p>
      </div>
    </div>
  );
}
