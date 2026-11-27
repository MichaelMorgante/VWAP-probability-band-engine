import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

def get_research_data_root() -> Path:
    """
    Resolve the external historical research data directory.

    An environment variable allows each user to configure
    their own storage location without changing source code.
    """
    configured_path = os.environ.get("VWAP_RESEARCH_DATA_DIR")

    if configured_path:
        return Path(configured_path).expanduser().resolve()

    return PROJECT_ROOT.parent / "VWAP-research-data"


RESEARCH_CONFIG = {
    # Research scope
    "instrument": "US100.cash",
    "timeframe": "M1",
    "session_timezone": "America/New_York",

    # Historical datasets
    "data_dir": PROJECT_ROOT / "data" / "historical",
    "baseline_dataset": "2025_full_year.csv",

    # External research datasets
    "research_data_root": get_research_data_root(),
    "raw_data_dir": get_research_data_root() / "raw",
    "validated_data_dir": get_research_data_root() / "validated",

    # Chronological partitions (end-exclusive)
    "research_splits": (
        ("development", "2022-01-01", "2025-01-01"),
        ("known_development", "2025-01-01", "2026-01-01"),
        ("validation", "2026-01-01", "2026-07-01"),
        ("retrospective_holdout", "2026-07-01", "2026-11-28"),
    ),

    # Reproducibility
    "random_seed": 42,
}
