import argparse
import subprocess

from src.research_config import (
    PROJECT_ROOT,
    RESEARCH_CONFIG,
)

from src.research_data_diagnostics import (
    capture_mt5_source,
)

from src.research_data_exports import (
    calendar_year_bounds,
    fetch_calendar_year,
    export_raw_acquisition,
)

from src.research_dataset_registry import (
    discover_raw_datasets,
)


def main():

    parser = argparse.ArgumentParser(
        description="Acquire immutable historical MT5 research data."
    )

    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Calendar year to acquire.",
    )

    args = parser.parse_args()

    year = args.year
    symbol = RESEARCH_CONFIG["instrument"]
    raw_dir = RESEARCH_CONFIG["raw_data_dir"]

    calendar_year_bounds(year)

    label = (
        symbol.lower().replace(".", "_")
        + f"_m1_raw_{year}"
    )

    if raw_dir.exists():

        existing = discover_raw_datasets(raw_dir)

        for record in existing:

            if (
                record["symbol"] == symbol
                and record["requested_start"][:4] == str(year)
            ):
                parser.error(
                    f"A dataset for {symbol} in {year} "
                    "already exists. Existing acquisitions "
                    "must be reviewed before replacement."
                )

    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(
            f"MT5 connection failed: {mt5.last_error()}"
        )

    try:

        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(
                f"Unable to select {symbol}."
            )

        source = capture_mt5_source(mt5, symbol)

        if source["broker_server"] != "FTMO-Server":
            raise RuntimeError(
                "Unexpected MT5 server. Check the connected terminal."
            )

        code_version = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
        ).strip()

        working_tree_dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=PROJECT_ROOT,
                text=True,
            ).strip()
        )

        print(f"Acquiring {symbol} M1 data for {year}...")

        result = fetch_calendar_year(
            mt5,
            symbol,
            year,
        )

        if result.candles.empty:
            raise RuntimeError(
                "No historical observations returned."
            )

        exported = export_raw_acquisition(
            result,
            source,
            raw_dir,
            code_version=code_version,
            working_tree_dirty=working_tree_dirty,
            label=label,
        )

        print(f"Observations: {len(result.candles):,}")
        print(f"Saved CSV: {exported['csv_path']}")
        print(f"Metadata: {exported['metadata_path']}")
        print("Research eligibility: pending validation")

    finally:

        mt5.shutdown()


if __name__ == "__main__":
    main()