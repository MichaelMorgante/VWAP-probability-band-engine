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

    # Original historical datasets
    "data_dir": PROJECT_ROOT / "data" / "historical",
    "baseline_dataset": "2025_full_year.csv",

    # External research datasets
    "research_data_root": get_research_data_root(),
    "raw_data_dir": get_research_data_root() / "raw",
    "validated_data_dir": get_research_data_root() / "validated",

    # Existing Gaussian baseline session configuration
    # All times are New York local time.
    "pre_anchor_minutes": 90,
    "vwap_anchor_time": "09:00",
    "vwap_seed_minutes": 30,
    "research_start_time": "09:30",
    "research_end_time": "12:30",

    # Existing solid RMS band parameters
    "ewma_halflife": 15,
    "solid_band_multipliers": (1.0, 2.0, 3.0),

    # Existing Gaussian ghost band parameters
    "ghost_lookback_bars": 20,
    "ghost_upper_percentiles": (0.85, 0.95, 0.995),

    # Reproducibility
    "random_seed": 42,
}
