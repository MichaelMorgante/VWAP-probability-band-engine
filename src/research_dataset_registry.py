import csv
import json
import re
from pathlib import Path

from .research_data_diagnostics import sha256_file
from .research_data_fetcher import RAW_CANDLE_COLUMNS


def inspect_raw_csv(csv_path: Path) -> int:
    """
    Verify the native raw CSV schema and count observations.

    This is a structural integrity check, not a mathematical
    or historical data-quality validation.
    """
    with csv_path.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as file:
        reader = csv.reader(file, strict=True)

        header = next(reader, None)

        if header != list(RAW_CANDLE_COLUMNS):
            raise ValueError(
                f"Unexpected raw candle schema: {csv_path}"
            )

        rows = 0

        for row in reader:
            if len(row) != len(header):
                raise ValueError(
                    f"Malformed CSV row {rows + 2}: "
                    f"{csv_path}"
                )

            rows += 1

    return rows


def verify_raw_dataset(
    dataset_dir: str | Path,
) -> dict:
    """
    Verify a raw acquisition against its provenance manifest.

    Neither the CSV nor its metadata is modified.

    Successful verification does not establish historical
    timezone accuracy, trading-minute completeness or
    eligibility for statistical modelling.
    """
    directory = Path(dataset_dir).resolve()
    label = directory.name

    if not directory.is_dir():
        raise FileNotFoundError(directory)

    if not re.fullmatch(r"[a-zA-Z0-9_-]+", label):
        raise ValueError(
            f"Invalid dataset directory name: {label}"
        )

    csv_path = directory / f"{label}.csv"
    metadata_path = directory / f"{label}.json"

    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)

    if not metadata_path.is_file():
        raise FileNotFoundError(metadata_path)

    with metadata_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        metadata = json.load(file)

    if not isinstance(metadata, dict):
        raise ValueError(
            f"Invalid dataset metadata: {metadata_path}"
        )

    required_fields = {
        "metadata_schema_version",
        "dataset_id",
        "dataset_label",
        "filename",
        "sha256",
        "file_size_bytes",
        "source",
        "symbol",
        "timeframe",
        "requested_start",
        "requested_end_exclusive",
        "observed_first_timestamp",
        "observed_last_timestamp",
        "acquisition_started_utc",
        "acquisition_finished_utc",
        "rows",
        "code_version",
        "working_tree_dirty",
        "research_eligibility",
        "diagnostics",
        "acquisition_source_sha256",
    }

    missing = required_fields - metadata.keys()

    if missing:
        raise ValueError(
            f"Missing metadata fields: {sorted(missing)}"
        )

    if metadata["metadata_schema_version"] != 1:
        raise ValueError(
            "Unsupported metadata schema version."
        )

    if metadata["dataset_label"] != label:
        raise ValueError("Dataset label mismatch.")

    if metadata["filename"] != csv_path.name:
        raise ValueError("Dataset filename mismatch.")

    if metadata["timeframe"] != "M1":
        raise ValueError(
            "Only native M1 acquisitions are supported."
        )

    if metadata["research_eligibility"] != (
        "pending_validation"
    ):
        raise ValueError(
            "Raw acquisition must retain its original "
            "pending-validation status."
        )

    if not isinstance(metadata["source"], dict):
        raise ValueError("Invalid acquisition source.")

    if metadata["source"].get("symbol") != metadata["symbol"]:
        raise ValueError("Source symbol mismatch.")

    if not isinstance(
        metadata["code_version"], str
    ) or not metadata["code_version"].strip():
        raise ValueError("Missing acquisition code version.")

    if type(metadata["working_tree_dirty"]) is not bool:
        raise ValueError(
            "Invalid working-tree provenance."
        )

    if type(metadata["rows"]) is not int:
        raise ValueError("Invalid metadata row count.")

    if metadata["rows"] < 0:
        raise ValueError("Negative metadata row count.")

    if type(metadata["file_size_bytes"]) is not int:
        raise ValueError("Invalid metadata file size.")

    # Verify file size.
    actual_size = csv_path.stat().st_size

    if actual_size != metadata["file_size_bytes"]:
        raise ValueError(
            f"File size mismatch: {label}"
        )

    # Verify byte-level dataset integrity.
    actual_checksum = sha256_file(csv_path)

    if actual_checksum != metadata["sha256"]:
        raise ValueError(
            f"SHA-256 checksum mismatch: {label}"
        )

    expected_id = f"sha256:{actual_checksum}"

    if metadata["dataset_id"] != expected_id:
        raise ValueError(
            f"Dataset identity mismatch: {label}"
        )

    # Verify schema and actual number of observations.
    actual_rows = inspect_raw_csv(csv_path)

    if actual_rows != metadata["rows"]:
        raise ValueError(
            f"CSV row count mismatch: {label}"
        )

    diagnostics = metadata["diagnostics"]

    if not isinstance(diagnostics, dict):
        raise ValueError("Invalid acquisition diagnostics.")

    quality = diagnostics.get("quality", {})
    chunks = diagnostics.get("chunks", [])

    if quality.get("rows") != actual_rows:
        raise ValueError(
            "Diagnostic row count mismatch."
        )

    if not isinstance(chunks, list) or not chunks:
        raise ValueError(
            "Missing acquisition chunk diagnostics."
        )

    if sum(chunk["rows"] for chunk in chunks) != actual_rows:
        raise ValueError(
            "Acquisition chunk row count mismatch."
        )

    source = metadata["source"]

    return {
        "dataset_id": expected_id,
        "dataset_label": label,
        "dataset_type": "raw_acquisition",
        "csv_path": csv_path,
        "metadata_path": metadata_path,
        "symbol": metadata["symbol"],
        "timeframe": metadata["timeframe"],
        "rows": actual_rows,
        "file_size_bytes": actual_size,
        "sha256": actual_checksum,
        "provider": source.get("provider"),
        "broker_company": source.get("broker_company"),
        "broker_server": source.get("broker_server"),
        "requested_start": metadata["requested_start"],
        "requested_end_exclusive": (
            metadata["requested_end_exclusive"]
        ),
        "observed_first_timestamp": (
            metadata["observed_first_timestamp"]
        ),
        "observed_last_timestamp": (
            metadata["observed_last_timestamp"]
        ),
        "acquisition_started_utc": (
            metadata["acquisition_started_utc"]
        ),
        "code_version": metadata["code_version"],
        "working_tree_dirty": (
            metadata["working_tree_dirty"]
        ),
        "timestamp_alignment": diagnostics.get(
            "timestamp_alignment", "unverified"
        ),
        "integrity_verified": True,
        "research_eligibility": "pending_validation",
    }


def discover_raw_datasets(
    raw_data_dir: str | Path,
) -> list[dict]:
    """
    Discover and verify external raw acquisitions.

    Invalid datasets raise explicit errors rather than
    being silently skipped or repaired.
    """
    root = Path(raw_data_dir).expanduser().resolve()

    if not root.is_dir():
        raise FileNotFoundError(
            f"External raw data directory not found: {root}"
        )

    registry = []

    for directory in sorted(root.iterdir()):
        if directory.is_dir():
            registry.append(
                verify_raw_dataset(directory)
            )

        elif directory.suffix.lower() in {".csv", ".json"}:
            raise ValueError(
                f"Unexpected standalone dataset file: "
                f"{directory}"
            )

    return registry