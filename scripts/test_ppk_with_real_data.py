def main() -> None:
    raise SystemExit(
        "DEPRECATED: base=rover self-pair is not a valid PPK test. "
        "Use python -m scripts.convert_rawx_ppk --input "
        "tests/fixtures/itb_real_data/4g_ppk_only.csv --output /path/to/empty-dir. "
        "See docs/ops/RAWX_PPK_RUNBOOK.md."
    )
if __name__ == "__main__":
    main()
