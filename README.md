# VWAP-probability-band-engine

Intraday VWAP probability band engine for backtesting, replay analysis, and live MT5 monitoring.

## Intraday VWAP Probability Bands Under Discrete-Time Market Data

This project studies how intraday price behaves relative to a session-reset reference line, usually VWAP, and whether deviations from that reference historically tend to mean-revert, continue, or remain neutral. It combines intraday data loading, VWAP / sigma band construction, z-score normalisation, empirical probability calibration, filtered signal generation, replay stepping, and live MT5 state updates in one structured Python repository.

The repository is not just a plotting tool. It is a reusable intraday engine that converts price deviation from VWAP into a probabilistic state space, then uses that state to support research, replay inspection, and live monitoring.

The benchmark motivation comes from algorithmic trading / stochastic control lecture material on TWAP and VWAP, where VWAP is treated as a more meaningful benchmark than TWAP when market volume matters. In continuous-time notation,

`TWAP = (1 / T) ∫_0^T S_t dt`

and

`VWAP = (∫_0^T V_t S_t dt) / (∫_0^T V_t dt)`

where `S_t` is price and `V_t` is market volume or order-flow intensity. Lecture 10 explicitly motivates the move from TWAP to VWAP as a more informative execution benchmark. :contentReference[oaicite:0]{index=0}

This project, however, is implemented in **discrete time**, not continuous time. The engine operates bar by bar on intraday candles, so all references, volatility bands, z-scores, and context features are computed using summation and recursive updates rather than continuous-time integrals.

## Project Overview

For each intraday bar, the engine computes a session-aware reference line, usually VWAP, in the discrete-time form

`VWAP_t = [Σ_{i=open}^t P_i^typical V_i] / [Σ_{i=open}^t V_i]`

with

`P_i^typical = (H_i + L_i + C_i) / 3`

If volume is unavailable or unreliable, a TWAP-style fallback is used:

`TWAP_t = (1 / t) Σ_{i=open}^t P_i^typical`

Around this reference, the engine estimates volatility and constructs sigma bands:

`Band_{k,±}(t) = Reference_t ± kσ_t,   k ∈ {1,2,3}`

The price deviation is then normalised into a dimensionless z-score:

`z_t = (C_t - Reference_t) / σ_t`

This turns raw price behaviour into an instrument-agnostic state representation. The z-score is discretised into zones such as `Z3-`, `Z2-`, `Z1-`, `Z0`, `Z1+`, `Z2+`, `Z3+`, and these zones are combined with contextual features such as trend, volume regime, time-of-day, and z-score velocity.

Historical data is then used to estimate empirical probabilities of the form

`P(Outcome | Zone, Context)`

where the outcome is one of:
- mean reversion (`MR`)
- continuation (`CONT`)
- neutral (`NEU`)

The project then studies how these probabilities can be used to generate and filter live intraday trading signals.

## Key Questions

This repository investigates the following core questions:

1. **Does intraday price extension relative to session VWAP contain a stable empirical mean-reversion edge?**
2. **How much does that edge depend on contextual features such as trend, volume regime, and time-of-day?**
3. **Can historical zone probabilities be converted into a practical signal layer with risk-aware filters?**
4. **Does the same engine structure remain usable across backtest, replay, and live MT5 workflows?**

## What the Engine Does

The project is built around six main layers:

### 1. Reference-line construction
The engine computes an intraday mean reference line, usually VWAP, with session reset logic.

### 2. Volatility and sigma bands
It estimates a volatility scale around that reference and constructs ±1σ, ±2σ, and ±3σ bands.

### 3. Z-score and zone classification
It converts price deviation into z-scores and discrete extension zones.

### 4. Context modelling
It computes regime-like context features such as:
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
- minimum |z|,
- allowed zones,
- regime compatibility,
- time-of-day filters.

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

### `replay_tradingview.ipynb`
Replay notebook.

It steps through historical data one bar at a time with no look-ahead, simulating the information state that would have been available at bar `t`.

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
│   ├── replay_tradingview.ipynb
│   └── live_trading.ipynb
├── src/
│   ├── calibration.py
│   ├── config.py
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
│   ├── sigma.py
│   ├── signals.py
│   ├── splits.py
│   └── zones.py
├── tests/
├── README.md
└── requirements.txt