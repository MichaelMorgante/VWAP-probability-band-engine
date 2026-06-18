# VWAP-probability-band-engine

Intraday VWAP probability band engine for backtesting, replay analysis, and live MT5 monitoring.

## Intraday VWAP Probability Bands Under Discrete-Time Market Data

This project studies how intraday price behaves relative to a session-reset reference line, usually VWAP, and whether deviations from that reference historically tend to mean-revert, continue, or remain neutral. It combines intraday data loading, VWAP / sigma band construction, z-score normalisation, empirical probability calibration, filtered signal generation, replay stepping, and live MT5 monitoring in one structured Python repository.

The benchmark motivation comes from lecture material on TWAP and VWAP in stochastic control and algorithmic trading at King’s College London. The theoretical benchmark framing is continuous-time, but the engine implemented here is **discrete-time** and runs bar by bar on intraday candles. The lecture notes motivate the move from TWAP to VWAP as a more meaningful execution benchmark when market volume matters.

In continuous time,

$$
\mathrm{TWAP} = \frac{1}{T}\int_0^T S_t\,dt
$$

and

$$
\mathrm{VWAP} = \frac{\int_0^T V_t S_t\,dt}{\int_0^T V_t\,dt},
$$

where $S_t$ is price and $V_t$ is market volume or order-flow intensity.

Although the benchmark motivation is naturally introduced in continuous time, the engine in this repository is implemented in **discrete time** on intraday candles. In practice, the reference line is updated bar by bar within each session.

For a session-reset VWAP, the implemented form is

$$
\mathrm{VWAP}_t = \frac{\sum_{i=\mathrm{open}}^{t} P_i^{\mathrm{typical}} V_i}{\sum_{i=\mathrm{open}}^{t} V_i},
$$

where the typical price is

$$
P_i^{\mathrm{typical}} = \frac{H_i + L_i + C_i}{3},
$$

where $H_i$, $L_i$, and $C_i$ denote the high, low, and close of bar $i$.

This is the discrete-time analogue of the continuous-time VWAP benchmark, with the summation taken over observed bars from the session open up to time $t$.

When volume is unavailable or unreliable, the engine can instead use a TWAP-style fallback:

$$
\mathrm{TWAP}_t = \frac{1}{t}\sum_{i=\mathrm{open}}^{t} P_i^{\mathrm{typical}}.
$$

So while the lecture-theory framing begins with integrals, the code in this project works entirely with cumulative summations and recursive bar-by-bar updates. This discrete formulation is what drives the reference line, sigma bands, z-scores, and live state transitions throughout the repository.

This project does **not** solve the full optimal execution problem from stochastic control. Instead, it uses VWAP as an intraday reference line, builds volatility bands around it, and studies whether deviations from that reference historically tend to:

1. revert back toward the mean,
2. continue further in the same direction, or
3. do neither clearly.

## Project Overview

Starting from the session reference line, the engine estimates an intraday volatility scale and builds probability bands around that reference. These bands convert raw price distance into a standardised state representation that can be compared across bars, sessions, and instruments.

The sigma-band structure is

$$
\mathrm{Band}_{k,\pm}(t) = \mathrm{Reference}_t \pm k\sigma_t,
\qquad k \in \{1,2,3\}.
$$

The price deviation is then normalised into a dimensionless z-score:

$$
z_t = \frac{C_t - \mathrm{Reference}_t}{\sigma_t}.
$$

This turns raw price behaviour into an instrument-agnostic state representation. The z-score is discretised into zones such as `Z3-`, `Z2-`, `Z1-`, `Z0`, `Z1+`, `Z2+`, `Z3+`, and these zones are combined with contextual features such as trend, volume regime, time-of-day, and z-score velocity.

Historical data is then used to estimate empirical probabilities of the form

$$
P(\mathrm{Outcome}\mid \mathrm{Zone}, \mathrm{Context}),
$$

where the outcome is one of:
- mean reversion (`MR`)
- continuation (`CONT`)
- neutral (`NEU`)

The project then studies how these probabilities can be converted into filtered trading signals for replay and live monitoring.

## Key Questions

This repository investigates the following core questions:

1. **Does intraday price extension relative to session VWAP contain a stable empirical mean-reversion edge?**
2. **How much does that edge depend on contextual features such as trend, volume regime, and time-of-day?**
3. **Can historical zone probabilities be converted into a practical signal layer with risk-aware filters?**
4. **Does the same engine structure remain usable across backtest, replay, and live MT5 workflows?**

## What the Engine Does

The project is built around six main layers.

### 1. Reference-line construction
The engine computes an intraday mean reference line, usually VWAP, with session reset logic.

### 2. Volatility and sigma bands
It estimates a volatility scale around the reference line and constructs $\pm 1\sigma$, $\pm 2\sigma$, and $\pm 3\sigma$ bands.

For the EWMA-style update, the variance recursion takes the form

$$
\sigma_t^2 = (1-\lambda)r_t^2 + \lambda \sigma_{t-1}^2,
$$

where $r_t$ is deviation from the reference rather than raw close-to-close return.

### 3. Z-score and zone classification
It converts price deviation into z-scores and discrete extension zones.

### 4. Context modelling
It computes contextual regime features such as:
- trend direction,
- volume regime,
- time-of-day bucket,
- z-score velocity.

### 5. Historical probability calibration
It labels historical outcomes and estimates zone-level or zone-plus-context probabilities using Wilson confidence intervals and fallback logic.

### 6. Signal generation
It produces typed signals such as:
- `MR_LONG`
- `MR_SHORT`
- `CONT_LONG`
- `CONT_SHORT`
- `NO_SIGNAL`

and filters them using:
- edge-gap thresholds,
- session warmup,
- minimum $|z|$,
- accepted zones,
- regime compatibility,
- time-of-day filters.

### 7. Adaptive Trend Health

The live MT5 overlay also includes an Adaptive Trend Health layer. This is a discretionary context module rather than an automated entry trigger. Its purpose is to describe whether the current market is trending cleanly, whether the trend is expanding, and whether continuation conditions are strengthening or weakening.

The trend-health logic separates three ideas:

1. **Trend existence** — determined by price holding the correct side of VWAP while the relevant green/orange bands continue to shift in the trend direction.
2. **Trend strength** — determined by the red band shifting in the direction of the trend.
3. **Spread/expansion quality** — determined by the opposite red band moving away while total band width expands.

For bullish conditions, the engine monitors whether price is above VWAP, VWAP is rising, upper green/orange are not meaningfully shifting down, and the upper red band is shifting upward.  
For bearish conditions, it monitors whether price is below VWAP, VWAP is falling, lower green/orange are not meaningfully shifting up, and the lower red band is shifting downward.

Orange-band touches are treated as impulse or extension pressure, not as automatic trend-ending signals.

The current default thresholds are:

| Component | Value |
|---|---:|
| Building trend | 3 qualifying candles |
| Confirmed trend | 7 qualifying candles |
| Established trend | 11 qualifying candles |
| Extended trend | 16 qualifying candles |
| Trend break tolerance | 5 bad candles |
| Red shift baseline window | 7 candles |
| Current red shift window | 1 candle |
| Orange pressure window | 10 candles |
| Compression tolerance | 0.25 |
| Lane shift tolerance | 0.25 |

Directional red-band shift strength is classified as:

| Red-band shift | Label |
|---:|---|
| 40+ | `EXTREME_EVENT_SHIFT` |
| 20+ | `VERY_HIGH_VOL_SHIFT` |
| 12+ | `VERY_STRONG_SHIFT` |
| 8+ | `STRONG_SHIFT` |
| 5+ | `GOOD_SHIFT` |
| 3+ | `MINIMUM_SHIFT` |
| < 3 | `WEAK_SHIFT` |

Expansion is classified as:

| Spread count over current window | Label |
|---:|---|
| 3 | `STRONG_EXPANSION` |
| 2 | `EXPANDING` |
| 1 | `MIXED_EXPANSION` |
| 0 | `NOT_EXPANDING` |

The MT5 overlay displays this as a separate left-panel block below the current signal table:

```text
Adaptive Trend Health
---------------------
State: CONFIRMED_DOWN_TREND | Lane: 9
Avg red: 12.40 | Last red: 10.80 | Ratio: 87%
Avg class: VERY_STRONG_SHIFT
Spread: EXPANDING
Orange: STRONG_ORANGE_PRESSURE
Compression: NONE
Health: VERY_STRONG_DOWN_TREND
```
`Avg red` is the median directional red-band shift over recent qualifying trend-lane candles.  
`Last red` is the most recent closed candle’s directional red-band shift.  
`Ratio` is `Last red / Avg red`.

## Notebook Workflow

### `backtest_research.ipynb`
Main research notebook.

It:
- loads and checks historical data,
- builds the reference line and sigma bands,
- classifies z-score zones,
- computes context variables,
- labels outcomes,
- calibrates probability tables,
- evaluates signal quality,
- plots overlays and probability heatmaps,
- exports research artifacts.

### `replay_python.ipynb`
Replay notebook.

Python replay notebook.

It steps through historical data one bar at a time with no look-ahead, using the same engine state transition as live monitoring. This is for validating replay behaviour inside Python before building any TradingView/Pine overlay. Once loaded into TradingView, we can backtest by simulating the information state that would have been available at bar $t$.

### `live_trading.ipynb`
Live MT5 notebook.

It:
- connects to MT5,
- loads or exports live-use artifacts,
- runs the live engine,
- writes live JSON state,
- generates the MQL5 overlay source file.

## Repository Structure

```text
VWAP-probability-band-engine/
├── artifacts/
│   ├── logs/
│   ├── metadata/
│   ├── plots/
│   └── tables/
├── data/
│   ├── historical/
│   └── snapshots/
├── live_artifacts/
│   ├── exports/
│   ├── plots/
│   └── states/
├── notebooks/
│   ├── backtest_research.ipynb
│   ├── replay_python.ipynb
│   └── live_trading.ipynb
├── src/
│   ├── __init__.py
│   ├── adaptive_trend_health.py
│   ├── calibration.py
│   ├── config.py
│   ├── context_overlay.py
│   ├── context.py
│   ├── engine.py
│   ├── evaluation.py
│   ├── exports.py
│   ├── labelling.py
│   ├── live_runner.py
│   ├── loaders.py
│   ├── lookup.py
│   ├── mql5_overlay.py
│   ├── plotting.py
│   ├── reference.py
│   ├── replay.py
│   ├── session_times.py
│   ├── sigma.py
│   ├── signals.py
│   ├── splits.py
│   ├── startup.py
│   ├── walk_forward.py
│   └── zones.py
├── tests/
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt

## License

This repository is provided under an **All Rights Reserved** license. No use, copying, modification, distribution, or derivative works are permitted without prior written permission.
See the [LICENSE](LICENSE) file for details.