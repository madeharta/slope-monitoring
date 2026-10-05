from ml.pipeline.feature_engineering.displacement import (
    compute_displacement_mm,
    meters_per_degree_lat,
    meters_per_degree_lon,
)


def test_meters_per_degree_lon_at_equator_matches_classic_constant():
    # Classic spherical-earth approximation is ~111,320 m/deg; the WGS-84
    # ellipsoid value at the equator should be very close to it.
    assert 111_300 < meters_per_degree_lon(0.0) < 111_320


def test_meters_per_degree_lon_shrinks_away_from_equator():
    assert meters_per_degree_lon(-6.2) < meters_per_degree_lon(0.0)


def test_zero_displacement_when_rover_equals_base():
    d = compute_displacement_mm(-6.2, 106.8, 500.0, -6.2, 106.8, 500.0)
    assert d.de_mm == d.dn_mm == d.du_mm == d.total_mm == 0.0


def test_altitude_only_offset_matches_exactly():
    # A pure vertical offset must pass straight through as dU / total_mm —
    # this is the one axis with no degree-to-meter conversion, so it is the
    # simplest possible correctness check on the total_mm assembly.
    d = compute_displacement_mm(-6.2, 106.8, 500.006, -6.2, 106.8, 500.0)
    assert abs(d.total_mm - 6.0) < 1e-6
    assert abs(d.de_mm) < 1e-6 and abs(d.dn_mm) < 1e-6


def test_latitude_offset_produces_expected_order_of_magnitude():
    # 1e-6 degree of latitude ~ 0.111 m at most latitudes -> ~111 mm.
    d = compute_displacement_mm(-6.2 + 1e-6, 106.8, 500.0, -6.2, 106.8, 500.0)
    assert 100 < d.dn_mm < 125


def test_ecef_enu_cross_axis_coupling_is_negligible():
    # A pure-North offset must not leak into dE/dU beyond floating-point
    # noise — this is the property the ECEF->ENU rotation guarantees that
    # the old degree-approximation formula could not (2026-09-18 correction,
    # ITB-reported formula error). Regression guard: if this starts
    # failing, the ECEF/ENU math has been broken.
    d = compute_displacement_mm(-6.2 + 1e-6, 106.8, 500.0, -6.2, 106.8, 500.0)
    assert abs(d.de_mm) < 1e-3
    assert abs(d.du_mm) < 1e-3

    d2 = compute_displacement_mm(-6.2, 106.8 + 1e-6, 500.0, -6.2, 106.8, 500.0)
    assert abs(d2.dn_mm) < 1e-3
    assert abs(d2.du_mm) < 1e-3


def test_geodetic_to_ecef_known_reference_point():
    # Equator, prime meridian, zero height -> ECEF should land on the
    # WGS-84 semi-major axis exactly (a well-known sanity checkpoint).
    from ml.pipeline.feature_engineering.displacement import geodetic_to_ecef
    x, y, z = geodetic_to_ecef(0.0, 0.0, 0.0)
    assert abs(x - 6_378_137.0) < 1e-3
    assert abs(y) < 1e-6
    assert abs(z) < 1e-6
