import pandas as pd

# Zone labels from most negative to most positive
ZONE_LABELS = ['Z3-', 'Z2-', 'Z1-', 'Z0', 'Z1+', 'Z2+', 'Z3+']

# Zone colours for visualisation
ZONE_COLORS = {
    'Z3-': '#d32f2f',  # deep red  — extreme short extension
    'Z2-': '#f57c00',  # orange    — extended short
    'Z1-': '#fbc02d',  # yellow    — mild short
    'Z0':  '#388e3c',  # green     — at mean
    'Z1+': '#fbc02d',  # yellow    — mild long
    'Z2+': '#f57c00',  # orange    — extended long
    'Z3+': '#d32f2f',  # deep red  — extreme long extension
}


def compute_zscore(df: pd.DataFrame) -> pd.Series:
    """
    Compute z-score of close price relative to the reference line.
    z = (close - reference) / sigma
    """
    return (df['close'] - df['reference']) / df['sigma']


def classify_zone(z: float, thresholds: list) -> str:
    """
    Assign a zone label to a single z-score value.
    thresholds: list of positive boundaries, e.g. [0.5, 1.0, 2.0]
    Returns one of: Z3-, Z2-, Z1-, Z0, Z1+, Z2+, Z3+
    """
    t = sorted(thresholds)  # ensure ascending
    az = abs(z)
    sign = '+' if z >= 0 else '-'

    if az < t[0]:
        return 'Z0'
    elif az < t[1]:
        return f'Z1{sign}'
    elif az < t[2]:
        return f'Z2{sign}'
    else:
        return f'Z3{sign}'


def classify_zones_series(zscore_series: pd.Series, thresholds: list) -> pd.Series:
    """Vectorised zone classification for a full series."""
    return zscore_series.apply(lambda z: classify_zone(z, thresholds))