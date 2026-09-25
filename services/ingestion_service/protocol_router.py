from __future__ import annotations
from dataclasses import dataclass, field
from common.errors import InvalidCsvError
from ml.domain.canonical_schema import CanonicalAccelSample, CanonicalPositionSample
from ml.pipeline.preprocessing import g4_parser, lora_parser
from services.ingestion_service.csv_validator import UploadHeaders
@dataclass(frozen=True)
class ParsedUpload:
    rawx_rows: list[tuple] = field(default_factory=list)
    position_rows: list[CanonicalPositionSample] = field(default_factory=list)
    accel_rows: list[CanonicalAccelSample] = field(default_factory=list)
    blast_rawx_rows: list[tuple] = field(default_factory=list)
def route_and_parse(headers: UploadHeaders, raw_csv: str) -> ParsedUpload:
    key = (headers.communication_mode, headers.data_type, headers.device_role)
    if key in {("4g", "gnss", "base"), ("4g", "gnss", "rover")}:
        return ParsedUpload(rawx_rows=g4_parser.parse_gnss_csv(raw_csv))
    if key == ("4g", "accel", "rover"):
        parsed = g4_parser.parse_accel_csv_single_post_blast_rawx(raw_csv)
        return ParsedUpload(
            accel_rows=parsed.samples,
            blast_rawx_rows=[parsed.post_blast_rawx],
        )
    if key == ("lora", "gnss", "base"):
        parsed = lora_parser.parse_combined_gnss_csv(raw_csv, base_device_id=headers.device_id)
        return ParsedUpload(rawx_rows=parsed.rawx_rows, position_rows=parsed.position_rows)
    if key == ("lora", "accel", "rover"):
        return ParsedUpload(accel_rows=lora_parser.parse_accel_csv(raw_csv))
    raise InvalidCsvError(
        "unsupported upload combination: "
        f"mode={headers.communication_mode}, data_type={headers.data_type}, role={headers.device_role}"
    )
