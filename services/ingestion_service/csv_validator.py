from __future__ import annotations
import csv
import re
from dataclasses import dataclass
from io import StringIO
from typing import Mapping
from common.errors import InvalidCsvError, MissingHeaderError
REQUIRED_HEADERS = (
    "X-Communication-Mode",
    "X-Device-Id",
    "X-Device-Role",
    "X-Data-Type",
    "X-File-Name",
    "X-Record-Count",
)
_ALLOWED_MODES = {"4g", "lora"}
_ALLOWED_ROLES = {"base", "rover"}
_ALLOWED_DATA_TYPES = {"gnss", "accel"}
_TS_PATTERNS = {
    "gnss": r"\d{8}_\d{4}",
    "accel": r"\d{8}_\d{6}",
}
@dataclass(frozen=True)
class UploadHeaders:
    communication_mode: str
    device_id: str
    device_role: str
    data_type: str
    file_name: str
    record_count: int
    upload_origin: str
def validate_headers(raw_headers: Mapping[str, str]) -> UploadHeaders:
    for name in REQUIRED_HEADERS:
        if not raw_headers.get(name):
            raise MissingHeaderError(name)
    mode = raw_headers["X-Communication-Mode"].strip().lower()
    role = raw_headers["X-Device-Role"].strip().lower()
    data_type = raw_headers["X-Data-Type"].strip().lower()
    if mode not in _ALLOWED_MODES:
        raise InvalidCsvError("X-Communication-Mode must be one of: 4g, lora")
    if role not in _ALLOWED_ROLES:
        raise InvalidCsvError("X-Device-Role must be one of: base, rover")
    if data_type not in _ALLOWED_DATA_TYPES:
        raise InvalidCsvError("X-Data-Type must be one of: gnss, accel")
    try:
        record_count = int(raw_headers["X-Record-Count"])
    except ValueError as exc:
        raise MissingHeaderError("X-Record-Count (not an integer)") from exc
    if record_count < 0:
        raise InvalidCsvError("X-Record-Count must be >= 0")
    headers = UploadHeaders(
        communication_mode=mode,
        device_id=raw_headers["X-Device-Id"].strip(),
        device_role=role,
        data_type=data_type,
        file_name=raw_headers["X-File-Name"].strip(),
        record_count=record_count,
        upload_origin=raw_headers.get("X-Upload-Origin", "device_auto").strip().lower(),
    )
    validate_upload_combination(headers)
    validate_file_name(headers)
    return headers
def validate_upload_combination(headers: UploadHeaders) -> None:
    valid = {
        ("4g", "gnss", "base"),
        ("4g", "gnss", "rover"),
        ("4g", "accel", "rover"),
        ("lora", "gnss", "base"),
        ("lora", "accel", "rover"),
    }
    key = (headers.communication_mode, headers.data_type, headers.device_role)
    if key not in valid:
        raise InvalidCsvError(
            "invalid upload combination: "
            f"mode={headers.communication_mode}, data_type={headers.data_type}, role={headers.device_role}"
        )
def validate_file_name(headers: UploadHeaders) -> None:
    prefix = "gnss" if headers.data_type == "gnss" else "accel"
    timestamp_pattern = _TS_PATTERNS[headers.data_type]
    expected = re.compile(
        rf"^{prefix}_{re.escape(headers.device_id)}_{timestamp_pattern}\.csv$"
    )
    if not expected.fullmatch(headers.file_name):
        raise InvalidCsvError(
            f"X-File-Name '{headers.file_name}' does not match the {headers.data_type} naming rule for "
            f"device '{headers.device_id}'"
        )
def validate_path_file_name(path_file_name: str, headers: UploadHeaders) -> None:
    if path_file_name != headers.file_name:
        raise InvalidCsvError(
            f"upload path file name '{path_file_name}' must equal X-File-Name '{headers.file_name}'"
        )
def validate_record_count(raw_csv: str, expected_count: int) -> int:
    reader = csv.reader(StringIO(raw_csv))
    rows = list(reader)
    if not rows:
        raise InvalidCsvError("CSV body is empty")
    actual = max(len(rows) - 1, 0)
    if actual != expected_count:
        raise InvalidCsvError(
            f"X-Record-Count={expected_count} but CSV contains {actual} data row(s)"
        )
    return actual
async def check_idempotent(file_name: str, file_upload_repo) -> bool:
    existing = await file_upload_repo.get_by_file_name(file_name)
    return bool(existing and existing.get("processing_status", "processed") == "processed")
async def record_upload(headers: UploadHeaders, file_upload_repo) -> None:
    await file_upload_repo.claim_for_processing(
        file_name=headers.file_name,
        device_id=headers.device_id,
        data_type=headers.data_type,
        communication_mode=headers.communication_mode,
        upload_origin=headers.upload_origin,
        record_count=headers.record_count,
    )
