"""Physical layer: generate rainfall first, then derive lagged sensor responses
(context.md §7). Moisture rises after rain begins, suction (pore pressure)
follows and *falls* as the soil wets, and tilt moves last and only under
sustained extreme wetness. A lagged model is sufficient — a full Richards
equation is not needed.

If tilt were pure random noise or moisture didn't respond to rainfall
plausibly, the charts would read as wrong to anyone who knows the domain
(context.md §10.8), so the model is intentionally causal and stateful.

Each site has a `hazard` (0..1) — its susceptibility / weather bias. It sets an
equilibrium wetness the soil relaxes toward, so a slope's baseline status is
stable while storms still push it around live.

Surface layer (added with the field-sensor set from the ITB contact, §14):
a GNSS rover reports 3D creep displacement, an ADXL355/MPU9025 node reports
two-axis tilt plus micro-vibration, and a piezometer reports pore-water
pressure. Displacement is the *ground truth* the indirect sensors are referenced
against: it accumulates only while the soil sits above a wetness knee, and it
self-accelerates (creep feeding on creep) so a wet, high-hazard slope enters the
tertiary-creep phase the inverse-velocity panel is built to read. Velocity and
acceleration are NOT modelled here — they are derived downstream from the
displacement series, so there is a single source of truth for the motion.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# Fixed downslope unit direction for the GNSS components, so the (east, north,
# vertical) triple traces a coherent line instead of wandering — east-dominant,
# with subsidence (negative up). |(0.82, 0.48, -0.31)| ≈ 1.0, so the resultant
# magnitude stays equal to the scalar creep state.
_DISP_E, _DISP_N, _DISP_U = 0.82, 0.48, -0.31


@dataclass
class SiteWeather:
    rng: random.Random
    hazard: float = 0.3
    wetness: float = 0.3
    rainfall: float = 0.0
    tilt: float = 0.08
    disp: float = 0.0  # cumulative 3D surface creep (mm), GNSS resultant
    _storm: float = field(default=0.0)

    def __post_init__(self) -> None:
        self.wetness = 0.25 + self.hazard * 0.55  # start near equilibrium
        # Seed accumulated creep from how far the equilibrium sits above the
        # creep knee, so a chronically-wet slope already shows displacement at
        # t0 instead of needing days of simulated time to build it up.
        self.disp = max(0.0, self.wetness - 0.72) * 180.0

    def step(self, minutes: float = 1.0) -> None:
        # storm arrival/decay — likelier and heavier on higher-hazard sites
        if self._storm > 0:
            self._storm -= minutes
        elif self.rng.random() < (0.003 + 0.02 * self.hazard) * minutes:
            self._storm = self.rng.uniform(10.0, 20.0 + 30.0 * self.hazard)
        target = self.rng.uniform(6.0, 10.0 + 30.0 * self.hazard) if self._storm > 0 else 0.0
        self.rainfall += (target - self.rainfall) * 0.3 * minutes
        self.rainfall = max(0.0, self.rainfall + self.rng.uniform(-0.4, 0.4))

        # wetness relaxes toward the hazard equilibrium, with storm bumps (the lag)
        eq = 0.25 + self.hazard * 0.55
        self.wetness += ((eq - self.wetness) * 0.03 + self.rainfall * 0.0009) * minutes
        self.wetness = min(max(self.wetness, 0.15), 0.98)

        # tilt accumulates slowly above a wetness knee; recovers very slowly; capped
        knee = 0.72
        if self.wetness > knee:
            self.tilt += (self.wetness - knee) * 0.02 * minutes
        else:
            self.tilt -= 0.0015 * minutes
        self.tilt = min(max(self.tilt, 0.05), 2.4)

        # GNSS creep: same knee, but self-accelerating (the disp term feeds back)
        # so a sustained-wet slope curves into tertiary creep rather than growing
        # linearly. This one evolves per real tick, NOT with the simulated
        # `minutes` — under the weather speedup a sim-time accumulator would
        # saturate within seconds of real time and the real-timestamped history
        # the DB records would be a flat line pinned at the cap, which would make
        # the velocity and inverse-velocity panels meaningless. On real time it
        # rises over minutes, then releases (apparent failure / re-survey) and
        # rebuilds, so the slope cycles through the accelerating regime the
        # Time-to-Failure panel exists to read.
        if self.wetness > knee:
            self.disp += (self.wetness - knee) * 0.02 + self.disp * 0.0006
        else:
            self.disp -= 0.004
        if self.disp > 55.0:
            self.disp = 12.0 + self.rng.uniform(-2.0, 2.0)
        self.disp = min(max(self.disp, 0.0), 60.0)

    def moisture(self) -> float:
        return round(25.0 + self.wetness * 35.0 + self.rng.uniform(-0.4, 0.4), 2)

    def suction(self) -> float:  # falls toward 0 as the soil wets
        return round(max(2.0, 52.0 - self.wetness * 50.0) + self.rng.uniform(-0.5, 0.5), 2)

    def pore_pressure(self) -> float:  # rises as the soil wets (mirror of suction)
        return round(6.0 + self.wetness * 30.0 + self.rng.uniform(-0.4, 0.4), 2)

    def tilt_deg(self) -> float:
        return round(self.tilt + self.rng.uniform(-0.008, 0.008), 3)

    def tilt_x(self) -> float:  # primary (downslope) axis
        return round(self.tilt + self.rng.uniform(-0.01, 0.01), 3)

    def tilt_y(self) -> float:  # cross-slope axis, smaller
        return round(self.tilt * 0.46 + self.rng.uniform(-0.01, 0.01), 3)

    def disp_resultant(self) -> float:
        return round(self.disp + self.rng.uniform(-0.05, 0.05), 3)

    def disp_e(self) -> float:
        return round(self.disp * _DISP_E + self.rng.uniform(-0.04, 0.04), 3)

    def disp_n(self) -> float:
        return round(self.disp * _DISP_N + self.rng.uniform(-0.04, 0.04), 3)

    def disp_u(self) -> float:
        return round(self.disp * _DISP_U + self.rng.uniform(-0.04, 0.04), 3)

    def vibration(self) -> float:
        """Dominant micro-vibration frequency (Hz): a quiet ambient baseline
        punctuated by occasional blast/rockfall spikes. Diagnostic only — no
        threshold, so it never drives status; the dashboard flags spikes as
        anomaly events instead."""
        base = 4.0 + self.rng.uniform(0.0, 1.5)
        if self.rng.random() < 0.03:
            base += self.rng.uniform(8.0, 30.0)
        return round(base, 2)

    def rain_mmh(self) -> float:
        return round(self.rainfall, 2)
