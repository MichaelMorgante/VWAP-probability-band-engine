import pandas as pd

def lookup_probabilities(zone: str, prob_table: pd.DataFrame,
                          marginal_table: pd.DataFrame,
                          context: dict = None,
                          config: dict = None) -> dict:
    """
    Look up outcome probabilities with a three-tier fallback hierarchy.

    Tier 1: zone + all context bins (if N >= min_conditioned_n)
            blended toward marginal via shrinkage when N < shrinkage_k
    Tier 2: zone-only marginal (if conditioned cell is too sparse)
    Tier 3: uniform 1/3 prior (if zone not in table at all)

    Also computes edge_gap = best_prob - second_best_prob.
    Signal is only actionable if edge_gap >= config['edge_gap_threshold'].

    Returns
    -------
    dict with keys MR, CONT, NEU (each a dict) plus:
        'edge_gap'       : float
        'dominant'       : str ('MR', 'CONT', 'NEU')
        'actionable'     : bool
        'lookup_tier'    : int (1, 2, or 3)
    """
    k_shrink = (config or {}).get('shrinkage_k', 30)
    min_cond  = (config or {}).get('min_conditioned_n', 10)
    edge_thr  = (config or {}).get('edge_gap_threshold', 0.10)

    def _extract(table, mask):
        sub = table[mask]
        if len(sub) == 0:
            return None, 0
        # total is the same for all outcome rows in the same cell
        total = sub['total'].iloc[0]
        result = {}
        for _, row in sub.iterrows():
            result[row['outcome']] = {
                'prob':       row['prob'],
                'ci_lower':   row['ci_lower'],
                'ci_upper':   row['ci_upper'],
                'confidence': row['confidence'],
            }
        return result, total

    # ── Tier 2: zone-only marginal (always computed as the fallback base) ──
    marginal_probs, _ = _extract(marginal_table, marginal_table['zone'] == zone)

    if marginal_probs is None:
        # Tier 3: zone not in table at all
        uniform = {o: {'prob': 1/3, 'ci_lower': 0.0, 'ci_upper': 1.0, 'confidence': 'NONE'}
                   for o in ['MR', 'CONT', 'NEU']}
        probs      = uniform
        lookup_tier = 3
    else:
        lookup_tier = 2
        probs       = marginal_probs

        # ── Tier 1: attempt conditioned lookup ──
        if context:
            mask = prob_table['zone'] == zone
            for col, val in context.items():
                if col in prob_table.columns:
                    mask = mask & (prob_table[col] == val)

            cond_probs, n_cond = _extract(prob_table, mask)

            if cond_probs is not None and n_cond >= min_cond:
                # Shrinkage blend: alpha = N / (N + k)
                alpha = n_cond / (n_cond + k_shrink)
                blended = {}
                for outcome in ['MR', 'CONT', 'NEU']:
                    p_cond = cond_probs.get(outcome, {}).get('prob', 1/3)
                    p_marg = marginal_probs.get(outcome, {}).get('prob', 1/3)
                    blended_p = alpha * p_cond + (1 - alpha) * p_marg
                    blended[outcome] = {
                        'prob':       round(blended_p, 4),
                        'ci_lower':   cond_probs.get(outcome, {}).get('ci_lower', 0),
                        'ci_upper':   cond_probs.get(outcome, {}).get('ci_upper', 1),
                        'confidence': 'HIGH' if n_cond >= 100 else 'LOW',
                    }
                probs       = blended
                lookup_tier = 1

    # ── Edge gap and actionability ──
    sorted_probs = sorted(
        [(o, probs[o]['prob']) for o in ['MR', 'CONT', 'NEU'] if o in probs],
        key=lambda x: x[1], reverse=True
    )
    dominant  = sorted_probs[0][0] if sorted_probs else 'NEU'
    edge_gap  = (sorted_probs[0][1] - sorted_probs[1][1]) if len(sorted_probs) >= 2 else 0.0
    actionable = edge_gap >= edge_thr

    probs['edge_gap']    = edge_gap
    probs['dominant']    = dominant
    probs['actionable']  = actionable
    probs['lookup_tier'] = lookup_tier
    return probs