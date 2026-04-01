# VWAP Probability Band Engine

A Python project for intraday VWAP-based probability bands, combining historical backtesting, replay analysis, and live MT5 monitoring in one unified workflow.

The project studies how price behaves relative to an intraday mean reference line, converts that deviation into z-score zones, calibrates empirical probabilities for mean reversion vs continuation, and then uses those probabilities to generate filtered trading signals.

---

## Motivation

In execution and algorithmic trading, a benchmark is needed to judge whether trades are being executed efficiently. A simple benchmark is **TWAP** (time-weighted average price), while a more market-aware benchmark is **VWAP** (volume-weighted average price). Your lecture notes frame this distinction directly, moving from TWAP to VWAP as a more meaningful benchmark when volume matters. :contentReference[oaicite:0]{index=0}

In continuous-time notation, TWAP can be written as

\[
\mathrm{TWAP} = \frac{1}{T}\int_0^T S_t\,dt
\]

where \(S_t\) is price.

VWAP instead weights price by traded volume:

\[
\mathrm{VWAP} = \frac{\int_0^T V_t S_t\,dt}{\int_0^T V_t\,dt}
\]

where \(V_t\) is market volume or order flow intensity. This benchmark is often more informative because it reflects where trading activity actually occurred, rather than treating all moments equally. That idea is the core starting point for this project. :contentReference[oaicite:1]{index=1}

This repository does **not** try to solve the full optimal execution problem from stochastic control. Instead, it uses VWAP as an intraday reference line, builds volatility bands around it, and studies whether deviations from that reference historically tend to:

1. revert back toward the mean,
2. continue further in the same direction, or
3. do neither clearly.

---

## Core idea

For each bar, the engine computes an intraday reference line, usually VWAP:

\[
\mathrm{VWAP}_t
=
\frac{\sum_{i=\text{session open}}^{t} P_i^{\text{typical}} V_i}
     {\sum_{i=\text{session open}}^{t} V_i}
\]

with typical price defined as

\[
P_i^{\text{typical}} = \frac{H_i + L_i + C_i}{3}
\]

When volume is unavailable or unreliable, a TWAP-style fallback can be used:

\[
\mathrm{TWAP}_t
=
\frac{1}{t}\sum_{i=\text{session open}}^{t} P_i^{\text{typical}}
\]

Around this reference, the engine estimates volatility and constructs sigma bands:

\[
\text{Band}_{k,\pm}(t) = \mathrm{Reference}_t \pm k \sigma_t,
\qquad k \in \{1,2,3\}
\]

Price deviation is then normalised into a dimensionless z-score:

\[
z_t = \frac{C_t - \mathrm{Reference}_t}{\sigma_t}
\]

This allows the same zone logic to be applied across instruments and sessions.

---

## Methodology

### 1. Intraday reference line
The reference is session-aware and resets each new session. In practice this is usually VWAP, though TWAP and EMA variants are supported.

### 2. Sigma bands
A rolling volatility estimate is built around the reference line rather than around close-to-close returns. This produces intraday probability bands that move with the reference.

For the EWMA version, the variance update follows the form

\[
\sigma_t^2 = (1-\lambda)\,r_t^2 + \lambda\,\sigma_{t-1}^2
\]

where \(r_t\) is deviation from the reference rather than raw return.

### 3. Zone classification
The z-score is discretised into zones such as:

- `Z3-`, `Z2-`, `Z1-`
- `Z0`
- `Z1+`, `Z2+`, `Z3+`

These zones describe how extended price is relative to the reference.

### 4. Context variables
Raw zone probabilities are not assumed to be stationary across all regimes. The engine therefore adds contextual bins such as:

- trend regime
- volume regime
- time of day
- z-score velocity

### 5. Outcome labelling
In backtest mode only, each bar is labelled by looking \(N\) bars forward and classifying whether the move became:

- **MR**: mean reversion
- **CONT**: continuation
- **NEU**: neutral

Labels are cost-adjusted so that mean-reversion only counts when the move survives a stop-style adverse excursion and still clears a minimum net edge after spread assumptions.

### 6. Probability calibration
The engine estimates empirical conditional probabilities of the form

\[
P(\text{Outcome} \mid \text{Zone}, \text{Context})
\]

using historical counts and Wilson confidence intervals. A zone-only marginal table is also kept as a fallback.

### 7. Probability lookup and shrinkage
At runtime, lookup follows a hierarchy:

\[
\text{Zone + Context} \;\rightarrow\; \text{Zone only} \;\rightarrow\; \text{Uniform prior}
\]

Sparse conditioned cells are blended toward the marginal table using shrinkage.

### 8. Signal layer
Signals are generated from the dominant probability outcome and then filtered by:

- edge-gap threshold
- session warmup
- minimum \(|z|\)
- accepted zones
- regime compatibility
- time-of-day filters

---

## Repository structure

```text
VWAP-probability-band-engine/
│
├── artifacts/
│   ├── logs/
│   ├── metadata/
│   ├── plots/
│   └── tables/
│
├── data/
│   ├── historical/
│   └── snapshots/
│
├── live_artifacts/
│   ├── exports/
│   ├── plots/
│   └── states/
│
├── notebooks/
│   ├── backtest_research.ipynb
│   ├── replay_tradingview.ipynb
│   └── live_trading.ipynb
│
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
│
├── tests/
├── README.md
└── requirements.txt