import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import pandas as pd

from src.zones import ZONE_COLORS


def plot_band_overlay(results: pd.DataFrame, config: dict,
                      n_bars: int = None, title: str = None) -> None:
    """
    Plot VWAP sigma band overlay with zone probabilities.

    Parameters
    ----------
    results : output DataFrame from run_backtest()
    config  : CONFIG dictionary
    n_bars  : number of recent bars to display (None = all)
    title   : plot title override
    """
    n_bars = n_bars or config.get('plot_last_n_bars')
    plot_df = results.tail(n_bars).reset_index(drop=True)

    fig = plt.figure(figsize=(18, 12))
    gs = gridspec.GridSpec(3, 1, height_ratios=[4, 1.5, 1.5], hspace=0.08)

    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)

    x = range(len(plot_df))

    # ── Price panel ──
    ax1.plot(x, plot_df['close'], color='#212121', lw=1.0, label='Close', zorder=5)
    ax1.plot(x, plot_df['reference'], color='#1565C0', lw=1.5, label=config['reference_type'], zorder=4)

    # Sigma bands with shading
    band_styles = [
        ('band_1p', 'band_1n', '#4CAF50', 0.15, '±1σ'),
        ('band_2p', 'band_2n', '#FF9800', 0.10, '±2σ'),
        ('band_3p', 'band_3n', '#F44336', 0.07, '±3σ'),
    ]
    for upper, lower, color, alpha, label in band_styles:
        if upper in plot_df.columns and lower in plot_df.columns:
            ax1.fill_between(x, plot_df[upper], plot_df[lower],
                             color=color, alpha=alpha, zorder=1)
            ax1.plot(x, plot_df[upper], color=color, lw=0.7, alpha=0.6, label=label)
            ax1.plot(x, plot_df[lower], color=color, lw=0.7, alpha=0.6)

    # Zone background colouring
    for i, row in plot_df.iterrows():
        zone_color = ZONE_COLORS.get(row['zone'], '#FFFFFF')
        ax1.axvspan(i - 0.5, i + 0.5, color=zone_color, alpha=0.06, zorder=0)

    ax1.set_ylabel('Price', fontsize=11)
    ax1.legend(loc='upper left', fontsize=9, ncol=4)
    ax1.set_title(
        title or f"{config['instrument']} | {config['reference_type']} Sigma Bands | Last {n_bars} bars",
        fontsize=13, fontweight='bold'
    )
    ax1.grid(True, alpha=0.2)

    # ── Z-score panel ──
    ax2.plot(x, plot_df['z_score'], color='#5C6BC0', lw=1.0, label='Z-Score')
    ax2.axhline(0, color='#1565C0', lw=1.0, linestyle='--', alpha=0.7)
    for thresh in config['zone_thresholds']:
        ax2.axhline(thresh, color='#F44336', lw=0.6, linestyle=':', alpha=0.6)
        ax2.axhline(-thresh, color='#F44336', lw=0.6, linestyle=':', alpha=0.6)
    ax2.fill_between(x, plot_df['z_score'], 0,
                     where=plot_df['z_score'] >= 0, color='#4CAF50', alpha=0.15)
    ax2.fill_between(x, plot_df['z_score'], 0,
                     where=plot_df['z_score'] < 0, color='#F44336', alpha=0.15)
    ax2.set_ylabel('Z-Score', fontsize=10)
    ax2.legend(loc='upper left', fontsize=9)
    ax2.grid(True, alpha=0.2)

    # ── Probability panel ──
    if 'p_mr' in plot_df.columns:
        ax3.plot(x, plot_df['p_mr'], color='#4CAF50', lw=1.2, label='P(MR)')
        ax3.plot(x, plot_df['p_cont'], color='#F44336', lw=1.2, label='P(Cont)')
        ax3.plot(x, plot_df['p_neu'], color='#9E9E9E', lw=0.8, label='P(Neu)', alpha=0.6)
        ax3.axhline(0.5, color='#212121', lw=0.8, linestyle='--', alpha=0.5)
        ax3.set_ylim(0, 1)
        ax3.set_ylabel('Probability', fontsize=10)
        ax3.legend(loc='upper left', fontsize=9, ncol=3)
        ax3.grid(True, alpha=0.2)

    # X-axis labels — show datetimes spaced out
    tick_step = max(1, len(plot_df) // 10)
    tick_positions = list(range(0, len(plot_df), tick_step))
    tick_labels = [str(plot_df['datetime'].iloc[i])[:16] for i in tick_positions]
    ax3.set_xticks(tick_positions)
    ax3.set_xticklabels(tick_labels, rotation=30, ha='right', fontsize=8)

    # Legend for zone colours
    zone_patches = [mpatches.Patch(color=c, alpha=0.4, label=z)
                    for z, c in ZONE_COLORS.items()]
    ax1.legend(handles=ax1.get_legend_handles_labels()[0] +
               [mpatches.Patch(color='white')] + zone_patches,
               labels=ax1.get_legend_handles_labels()[1] +
               ['  Zones:'] + list(ZONE_COLORS.keys()),
               loc='upper left', fontsize=8, ncol=6)

    plt.tight_layout()
    plt.savefig('band_overlay.png', dpi=150, bbox_inches='tight')
    plt.show()
    print("✅ Chart saved to band_overlay.png")