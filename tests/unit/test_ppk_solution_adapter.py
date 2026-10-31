from datetime import datetime, timedelta, timezone
import copy
import pytest

from ml.pipeline.adapters.ppk_solution_adapter import adapt_ppk_solution, audit_ppk_solutions

UTC = timezone.utc
NOW = datetime(2026, 10, 10, tzinfo=UTC)
ARGS = dict(site_id="SITE-01", rover_ids=("ROVER-B1-01",), base_device_id="BASE-01")


def row():
    d = dict(time=NOW, processed_at=NOW+timedelta(minutes=1), site_id="SITE-01",
        base_device_id="BASE-01", rover_device_id="ROVER-B1-01",
        schema_version="ppk.solution.v1", vertical_datum="ELLIPSOIDAL_WGS84",
        processing_engine="RTKLIB", quality_gate_status="accepted", validation_status="unvalidated",
        latitude=-7.2, longitude=112.5, ellipsoidal_height_m=65.,
        displacement_e_mm=1., displacement_n_mm=2., displacement_u_mm=3.,
        displacement_total_mm=3.742, h_acc_m=0.01, rtklib_quality=1, rtklib_ns=14,
        rtklib_age_s=0.3, rtklib_ratio=5., rtklib_sdn_m=0.01,
        rtklib_sde_m=0.02, rtklib_sdu_m=0.03)
    for field in ("navigation_sha256", "base_rawx_sha256", "rover_rawx_sha256",
        "base_obs_sha256", "rover_obs_sha256", "normalized_navigation_sha256",
        "convbin_sha256", "rnx2rtkp_sha256", "solution_pos_sha256"):
        d[field]="a"*64
    d["rtklib_config_sha256"]="b"*64
    return d


def test_candidate_default_not_ground_truth():
    result=adapt_ppk_solution(row(),**ARGS)
    assert result.structurally_valid and result.technical_quality_pass
    assert not result.supervised_target_eligible
    assert result.provenance_status=="complete"
    assert result.observed_at_utc.tzinfo is UTC


@pytest.mark.parametrize("changes", [
    {"quality_gate_status":"rejected"}, {"validation_status":"validated"},
    {"quality_gate_status":"rejected","validation_status":"validated"},
])
def test_status_never_grants_ground_truth(changes):
    r=row();r.update(changes)
    result=adapt_ppk_solution(r,**ARGS)
    assert not result.supervised_target_eligible
    assert result.technical_quality_pass == (r["quality_gate_status"]=="accepted")


@pytest.mark.parametrize("field,value", [
    ("site_id","OTHER"),("base_device_id","BASE-02"),("rover_device_id","OTHER"),
    ("schema_version","ppk.solution.v2"),("vertical_datum","MSL"),
    ("processing_engine","custom"),("quality_gate_status","yes"),
    ("validation_status","provisional"),("latitude",91.),("longitude",181.),
    ("h_acc_m",-1.),("displacement_e_mm",float('nan')),
    ("displacement_total_mm",float('inf')),("rtklib_quality",0),
    ("rtklib_quality",True),("rtklib_ns",-1),
    ("navigation_sha256","not-a-hash"),("rtklib_age_s",float('nan')),
])
def test_invalid_rejected(field,value):
    r=row();r[field]=value
    with pytest.raises(ValueError):adapt_ppk_solution(r,**ARGS)


def test_signed_rtklib_differential_age_is_preserved_as_valid():
    r = row()
    r["rtklib_age_s"] = -35.99
    candidate = adapt_ppk_solution(r, **ARGS)
    assert candidate.structurally_valid
    assert not candidate.supervised_target_eligible


def test_required_field_missing():
    r=row();del r['processed_at']
    with pytest.raises(ValueError,match="missing PPK columns"):
        adapt_ppk_solution(r,**ARGS)


def test_naive_time_rejected():
    r=row();r['time']=NOW.replace(tzinfo=None)
    with pytest.raises(ValueError):adapt_ppk_solution(r,**ARGS)


def test_partial_provenance_not_invented():
    r=row();r['base_obs_sha256']=None
    x=adapt_ppk_solution(r,**ARGS)
    assert x.provenance_status=='partial'
    assert ('base_obs_sha256',None) in x.hashes
    assert not x.supervised_target_eligible


def test_utc_normalization():
    r=row();r['time']=NOW.astimezone(timezone(timedelta(hours=7)))
    assert adapt_ppk_solution(r,**ARGS).observed_at_utc==NOW


def test_duplicate_timezone_identity_rejected():
    r=row();other=copy.deepcopy(r)
    other['time']=NOW.astimezone(timezone(timedelta(hours=7)))
    audit=audit_ppk_solutions([r,other],**ARGS)
    assert len(audit.candidates)==1 and audit.rejected[0][0]==1


def test_audit_partial_and_rejection():
    r=row();bad=row();bad['vertical_datum']='MSL'
    audit=audit_ppk_solutions([r,bad],**ARGS)
    assert audit.total==2 and len(audit.candidates)==1 and len(audit.rejected)==1


def test_original_row_unchanged():
    r=row();original=copy.deepcopy(r)
    adapt_ppk_solution(r,**ARGS)
    assert r==original
