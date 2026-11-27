import json
import os
import unittest

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.research_config import (
    PROJECT_ROOT,
    get_research_data_root,
)

from src.research_data_fetcher import (
    fetch_raw_mt5_candles,
)

from src.research_data_exports import (
    export_raw_acquisition,
)

from src.research_dataset_registry import (
    inspect_raw_csv,
    verify_raw_dataset,
    discover_raw_datasets,
)


class TestResearchDatasetRegistry(unittest.TestCase):

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)

        start = datetime(
            2025, 1, 6, 14, 30,
            tzinfo=timezone.utc,
        )

        mt5 = Mock()
        mt5.TIMEFRAME_M1 = 1

        mt5.copy_rates_range.return_value = [
            {
                "time": int(start.timestamp()),
                "open": 20000.0,
                "high": 20005.0,
                "low": 19995.0,
                "close": 20001.0,
                "tick_volume": 100,
                "spread": 190,
                "real_volume": 0,
            }
        ]

        result = fetch_raw_mt5_candles(
            mt5,
            "US100.cash",
            start,
            start + timedelta(minutes=1),
        )

        source = {
            "provider": "MetaTrader5",
            "symbol": "US100.cash",
            "broker_company": "Mock Broker",
            "broker_server": "Mock Server",
        }

        exported = export_raw_acquisition(
            result,
            source,
            self.root,
            code_version="mock-commit",
            working_tree_dirty=False,
            label="sample",
        )

        self.directory = exported["dataset_dir"]
        self.csv_path = exported["csv_path"]
        self.metadata_path = exported["metadata_path"]

    def change_metadata(self, key, value):
        metadata = json.loads(
            self.metadata_path.read_text(
                encoding="utf-8"
            )
        )

        metadata[key] = value

        self.metadata_path.write_text(
            json.dumps(metadata),
            encoding="utf-8",
        )

    def test_default_external_data_root(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                get_research_data_root(),
                PROJECT_ROOT.parent / "VWAP-research-data",
            )

    def test_configurable_external_data_root(self):
        with patch.dict(
            os.environ,
            {
                "VWAP_RESEARCH_DATA_DIR": str(self.root),
            },
        ):
            self.assertEqual(
                get_research_data_root(),
                self.root.resolve(),
            )

    def test_valid_dataset(self):
        record = verify_raw_dataset(self.directory)

        self.assertTrue(record["integrity_verified"])
        self.assertEqual(record["rows"], 1)

        self.assertEqual(
            record["research_eligibility"],
            "pending_validation",
        )

        self.assertEqual(
            record["timestamp_alignment"],
            "unverified",
        )

    def test_dataset_discovery(self):
        registry = discover_raw_datasets(self.root)

        self.assertEqual(len(registry), 1)

        self.assertEqual(
            registry[0]["dataset_label"],
            "sample",
        )

    def test_missing_metadata_rejected(self):
        self.metadata_path.unlink()

        with self.assertRaises(FileNotFoundError):
            verify_raw_dataset(self.directory)

    def test_missing_csv_rejected(self):
        self.csv_path.unlink()

        with self.assertRaises(FileNotFoundError):
            verify_raw_dataset(self.directory)

    def test_modified_file_size_rejected(self):
        with self.csv_path.open("ab") as file:
            file.write(b"modified")

        with self.assertRaisesRegex(
            ValueError,
            "File size mismatch",
        ):
            verify_raw_dataset(self.directory)

    def test_same_size_modified_csv_rejected(self):
        original = self.csv_path.read_bytes()

        modified = original.replace(
            b"20000.0",
            b"20002.0",
            1,
        )

        self.assertNotEqual(original, modified)
        self.assertEqual(len(original), len(modified))

        self.csv_path.write_bytes(modified)

        with self.assertRaisesRegex(
            ValueError,
            "SHA-256 checksum mismatch",
        ):
            verify_raw_dataset(self.directory)

    def test_incorrect_row_count_rejected(self):
        self.change_metadata("rows", 10)

        with self.assertRaisesRegex(
            ValueError,
            "CSV row count mismatch",
        ):
            verify_raw_dataset(self.directory)

    def test_incorrect_dataset_id_rejected(self):
        self.change_metadata(
            "dataset_id",
            "sha256:incorrect",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Dataset identity mismatch",
        ):
            verify_raw_dataset(self.directory)

    def test_invalid_schema_rejected(self):
        self.csv_path.write_text(
            "incorrect,columns\n1,2\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unexpected raw candle schema",
        ):
            inspect_raw_csv(self.csv_path)

    def test_raw_dataset_cannot_claim_validation(self):
        self.change_metadata(
            "research_eligibility",
            "validated",
        )

        with self.assertRaises(ValueError):
            verify_raw_dataset(self.directory)

    def test_verification_does_not_modify_files(self):
        original_csv = self.csv_path.read_bytes()
        original_metadata = self.metadata_path.read_bytes()

        verify_raw_dataset(self.directory)

        self.assertEqual(
            self.csv_path.read_bytes(),
            original_csv,
        )

        self.assertEqual(
            self.metadata_path.read_bytes(),
            original_metadata,
        )

    def test_missing_external_directory(self):
        with self.assertRaises(FileNotFoundError):
            discover_raw_datasets(
                self.root / "missing"
            )

    def test_invalid_dataset_not_silently_skipped(self):
        (self.root / "incomplete").mkdir()

        with self.assertRaises(FileNotFoundError):
            discover_raw_datasets(self.root)

    def test_standalone_csv_rejected(self):
        (self.root / "standalone.csv").touch()

        with self.assertRaises(ValueError):
            discover_raw_datasets(self.root)


if __name__ == "__main__":
    unittest.main()