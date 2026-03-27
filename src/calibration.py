import numpy as np
import pandas as pd
from scipy import stats
from typing import Tuple

def wilson_ci(count: int, total: int, confidence: float = 0.95) -> Tuple[float, float, float]:
    """Wilson score confidence interval. Returns (lower, point_estimate, upper)."""
    if total == 0:
        return (0.0, 0.0, 0.0)
    p = count / total
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    denom  = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    margin = z * np.sqrt(p * (1-p) / total + z**2 / (4 * total**2)) / denom
    return (max(0, centre - margin), p, min(1, centre + margin))


def calibrate_probability_table(df: pd.DataFrame, config: dict,
                                 context_col: str = None) -> pd.DataFrame:
    """
    Build the conditional probability table P(outcome | zone [, context]).
    Unchanged from original — shrinkage is applied at lookup time.
    """
    min_n    = config['min_sample_count']
    valid    = df.dropna(subset=['outcome', 'zone'])
    group_cols = ['zone'] + ([context_col] if context_col else [])
    rows = []

    for group_key, group in valid.groupby(group_cols):
        if isinstance(group_key, str):
            group_key = (group_key,)
        total = len(group)
        for outcome in ['MR', 'CONT', 'NEU']:
            count      = (group['outcome'] == outcome).sum()
            ci_lo, prob, ci_hi = wilson_ci(count, total)
            confidence = 'HIGH' if total >= min_n else 'LOW'
            row = dict(zip(group_cols, group_key))
            row.update({
                'outcome':    outcome,
                'count':      count,
                'total':      total,
                'prob':       round(prob, 4),
                'ci_lower':   round(ci_lo, 4),
                'ci_upper':   round(ci_hi, 4),
                'confidence': confidence,
            })
            rows.append(row)

    table = pd.DataFrame(rows)
    print(f"✅ Probability table calibrated ({len(table)} rows)")
    low_conf = table[table['confidence'] == 'LOW']['zone'].unique()
    if len(low_conf) > 0:
        print(f"⚠️  Low confidence zones (n < {min_n}): {list(low_conf)}")
    return table