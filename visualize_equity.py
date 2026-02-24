"""
Equity Curve & Drawdown Visualization
=======================================
Generates equity curve charts from backtest results, with optional
meta-classifier gating overlay.

Usage:
    # Baseline equity curve (all 1,700 trades):
    python visualize_equity.py

    # Meta-gated equity curve (466 trades):
    python visualize_equity.py --meta-gate

    # Custom threshold:
    python visualize_equity.py --meta-gate --meta-threshold 0.60

    # Save to file instead of showing:
    python visualize_equity.py --save equity_curve.png

Change log:
    2026-02-25  Initial implementation (Task 1)
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import numpy as np

# matplotlib config — Agg backend for headless, TkAgg for interactive
import matplotlib
matplotlib.use("Agg")  # default to file output; overridden if --show
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

RESULTS_FILE = "backtest_walkforward_results.json"


def load_results(path: str = RESULTS_FILE) -> Tuple[dict, List[dict]]:
    """Load walkforward results and return (config, traded_results)."""
    if not os.path.exists(path):
        print(f"  ERROR: {path} not found. Run backtest_walkforward.py first.")
        sys.exit(1)

    with open(path, "r") as f:
        data = json.load(f)

    results = data.get("results", [])
    # Keep only traded (non-neutral) signals
    traded = [r for r in results if r["predicted_direction"] != "neutral"]
    # Sort by datetime
    traded.sort(key=lambda r: r["datetime"])
    return data, traded


def apply_meta_gate(
    traded: List[dict], threshold: float = None
) -> Tuple[List[dict], List[dict]]:
    """Apply meta-classifier gating. Returns (gated, rejected).

    Loads the trained meta-classifier model and scores each trade.
    Falls back to no gating if model unavailable.
    """
    try:
        from meta_classifier import MetaClassifier
    except ImportError:
        print("  WARNING: meta_classifier.py not found, skipping gate.")
        return traded, []

    clf = MetaClassifier()
    if not clf.load():
        print("  WARNING: No trained meta-classifier model found.")
        return traded, []

    if threshold is not None:
        clf.threshold = threshold

    actual_threshold = clf.threshold
    print(f"  Meta-classifier loaded (threshold={actual_threshold:.2f})")

    # Build a minimal stat_pred dict from each result
    gated, rejected = [], []
    for r in traded:
        stat_pred = {
            "predicted_direction": r["predicted_direction"],
            "confidence_score": r.get("predicted_confidence", 0),
            "confidence_level": r.get("predicted_conf_level", "LOW"),
            "n_matches": r.get("n_matches", 0),
            "match_tier": r.get("tier", "none"),
            "profit_factor": r.get("predicted_pf", 0),
            "bullish_edge": r.get("edge", 0),
        }
        should, prob = clf.should_trade(r, stat_pred, threshold=actual_threshold)
        if should:
            gated.append(r)
        else:
            rejected.append(r)

    print(f"  Meta gate: {len(gated)} accepted, {len(rejected)} rejected")
    return gated, rejected


# ---------------------------------------------------------------------------
# Equity computation
# ---------------------------------------------------------------------------


def compute_equity_series(
    trades: List[dict],
) -> Tuple[List[str], np.ndarray, np.ndarray, np.ndarray]:
    """Compute daily equity curve from trade-level returns.

    Returns:
        dates: sorted date strings
        cumulative_returns: cumulative sum of returns (%)
        peak: running peak of cumulative returns
        drawdown: peak - cumulative (always >= 0)
    """
    # Group returns by date
    daily_returns: Dict[str, float] = defaultdict(float)
    daily_count: Dict[str, int] = defaultdict(int)

    for r in trades:
        dt = r["datetime"][:10]  # YYYY-MM-DD
        ret = r.get("actual_return_sl_net", r.get("actual_return_sl", 0))
        daily_returns[dt] += ret
        daily_count[dt] += 1

    dates = sorted(daily_returns.keys())
    if not dates:
        return [], np.array([]), np.array([]), np.array([])

    returns = np.array([daily_returns[d] for d in dates])
    cumulative = np.cumsum(returns)

    # Running peak and drawdown
    peak = np.maximum.accumulate(cumulative)
    drawdown = peak - cumulative  # positive = below peak

    return dates, cumulative, peak, drawdown


def compute_equity_series_sized(
    trades: List[dict],
    initial_capital: float = 1_000_000,
) -> Tuple[List[str], np.ndarray, np.ndarray, np.ndarray]:
    """Compute position-sized equity curve using Kelly Criterion.

    Instead of summing flat % returns, each trade's return is weighted
    by its Kelly-derived position size. Equity grows/shrinks as capital.

    Returns same format as compute_equity_series but values are in
    capital-relative % terms.
    """
    from position_sizing import PositionSizer

    sizer = PositionSizer(capital=initial_capital)

    # Process trades in chronological order, updating capital
    daily_pnl: Dict[str, float] = defaultdict(float)

    for r in trades:
        dt = r["datetime"][:10]
        ret_pct = r.get("actual_return_sl_net", r.get("actual_return_sl", 0))
        pf = r.get("predicted_pf", 1.0)
        wr = r.get("predicted_wr", 50.0)
        sl = r.get("sl_pct", 1.5)
        conf = r.get("predicted_conf_level", "MEDIUM")

        size = sizer.calculate_size(
            win_rate=wr,
            profit_factor=pf,
            sl_pct=sl,
            confidence_level=conf,
        )
        pos_pct = size["position_pct"]  # % of capital to risk
        pos_value = sizer.capital * pos_pct / 100

        # P&L for this trade
        pnl = pos_value * ret_pct / 100
        daily_pnl[dt] += pnl

        # Update capital
        sizer.update_capital(pnl)

    dates = sorted(daily_pnl.keys())
    if not dates:
        return [], np.array([]), np.array([]), np.array([])

    pnl_series = np.array([daily_pnl[d] for d in dates])
    cumulative_pnl = np.cumsum(pnl_series)
    # Convert to % of initial capital
    cumulative_pct = cumulative_pnl / initial_capital * 100

    peak = np.maximum.accumulate(cumulative_pct)
    drawdown = peak - cumulative_pct

    final_capital = initial_capital + cumulative_pnl[-1]
    print(f"  [SIZED] Initial: {initial_capital:,.0f} -> Final: {final_capital:,.0f} "
          f"({cumulative_pct[-1]:+.1f}%) | Max DD: {drawdown.max():.1f}%")

    return dates, cumulative_pct, peak, drawdown


def compute_monthly_stats(
    trades: List[dict],
) -> Tuple[List[str], np.ndarray, np.ndarray, np.ndarray]:
    """Compute monthly aggregates.

    Returns:
        months: sorted YYYY-MM strings
        monthly_returns: total return per month
        monthly_trades: trade count per month
        monthly_pf: profit factor per month
    """
    month_wins: Dict[str, float] = defaultdict(float)
    month_losses: Dict[str, float] = defaultdict(float)
    month_count: Dict[str, int] = defaultdict(int)
    month_return: Dict[str, float] = defaultdict(float)

    for r in trades:
        month = r["datetime"][:7]  # YYYY-MM
        ret = r.get("actual_return_sl_net", r.get("actual_return_sl", 0))
        month_return[month] += ret
        month_count[month] += 1
        if ret > 0:
            month_wins[month] += ret
        else:
            month_losses[month] += abs(ret)

    months = sorted(month_return.keys())
    returns = np.array([month_return[m] for m in months])
    counts = np.array([month_count[m] for m in months])
    pfs = np.array(
        [
            month_wins[m] / month_losses[m] if month_losses[m] > 0 else 10.0
            for m in months
        ]
    )

    return months, returns, counts, pfs


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def plot_equity_curve(
    trades: List[dict],
    title: str = "Equity Curve",
    save_path: Optional[str] = None,
    show: bool = False,
    rejected_trades: Optional[List[dict]] = None,
    show_sized: bool = False,
):
    """Create a comprehensive equity curve visualization.

    4-panel chart:
      1. Cumulative equity curve + peak line + drawdown shading
      2. Drawdown (%) from peak
      3. Monthly returns bar chart
      4. Monthly trade counts
    """
    dates, cumulative, peak, drawdown = compute_equity_series(trades)
    months, monthly_ret, monthly_cnt, monthly_pf = compute_monthly_stats(trades)

    if len(dates) == 0:
        print("  No trades to plot.")
        return

    # Parse dates for x-axis
    from datetime import datetime as dt

    date_objs = [dt.strptime(d, "%Y-%m-%d") for d in dates]
    month_objs = [dt.strptime(m + "-15", "%Y-%m-%d") for m in months]

    # Figure setup
    fig = plt.figure(figsize=(16, 14))
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.98)
    gs = GridSpec(4, 1, height_ratios=[3, 1.2, 1.5, 1], hspace=0.25, figure=fig)

    # --- Panel 1: Equity Curve ---
    ax1 = fig.add_subplot(gs[0])

    # If we have rejected trades, show them as a dimmer line
    if rejected_trades and len(rejected_trades) > 0:
        rej_dates, rej_cum, _, _ = compute_equity_series(rejected_trades)
        if len(rej_dates) > 0:
            rej_date_objs = [dt.strptime(d, "%Y-%m-%d") for d in rej_dates]
            ax1.plot(
                rej_date_objs, rej_cum, color="#cccccc", linewidth=0.8,
                alpha=0.6, label=f"Rejected ({len(rejected_trades)} trades)",
                zorder=1,
            )

        # Also show full baseline
        all_trades = sorted(trades + rejected_trades, key=lambda r: r["datetime"])
        all_dates, all_cum, _, _ = compute_equity_series(all_trades)
        if len(all_dates) > 0:
            all_date_objs = [dt.strptime(d, "%Y-%m-%d") for d in all_dates]
            ax1.plot(
                all_date_objs, all_cum, color="#999999", linewidth=1.0,
                linestyle="--", alpha=0.5,
                label=f"Baseline ({len(all_trades)} trades)",
                zorder=2,
            )

    # Main equity line
    label = f"Equity ({len(trades)} trades)"
    ax1.plot(date_objs, cumulative, color="#1f77b4", linewidth=1.5, label=label, zorder=3)
    ax1.plot(date_objs, peak, color="#2ca02c", linewidth=0.8, alpha=0.5, label="Peak", zorder=2)

    # Position-sized overlay (secondary y-axis)
    ax1_twin = None
    if show_sized:
        sized_dates, sized_cum, sized_peak, sized_dd = compute_equity_series_sized(trades)
        if len(sized_dates) > 0:
            sized_date_objs = [dt.strptime(d, "%Y-%m-%d") for d in sized_dates]
            ax1_twin = ax1.twinx()
            ax1_twin.plot(
                sized_date_objs, sized_cum, color="#ff7f0e", linewidth=1.2,
                alpha=0.8, label="Kelly-Sized (%)", linestyle="-.",
                zorder=4,
            )
            ax1_twin.set_ylabel("Kelly-Sized Return (%)", color="#ff7f0e")
            ax1_twin.tick_params(axis="y", labelcolor="#ff7f0e")

    # Drawdown shading
    ax1.fill_between(
        date_objs, cumulative, peak,
        where=(drawdown > 0), alpha=0.15, color="red", label="Drawdown",
        zorder=1,
    )

    # Annotations
    max_cum = cumulative[-1]
    max_dd = drawdown.max()
    max_dd_idx = np.argmax(drawdown)
    n_wins = sum(1 for r in trades if r.get("actual_return_sl_net", 0) > 0)
    win_rate = n_wins / len(trades) * 100 if trades else 0

    # Compute PF
    gross_wins = sum(
        r.get("actual_return_sl_net", 0) for r in trades
        if r.get("actual_return_sl_net", 0) > 0
    )
    gross_losses = abs(
        sum(
            r.get("actual_return_sl_net", 0) for r in trades
            if r.get("actual_return_sl_net", 0) <= 0
        )
    )
    pf = gross_wins / gross_losses if gross_losses > 0 else float("inf")

    stats_text = (
        f"Total Return: {max_cum:+.1f}%\n"
        f"Profit Factor: {pf:.2f}\n"
        f"Win Rate: {win_rate:.1f}%\n"
        f"Trades: {len(trades)}\n"
        f"Max DD: {max_dd:.1f}%"
    )
    ax1.text(
        0.02, 0.97, stats_text,
        transform=ax1.transAxes,
        fontsize=10, verticalalignment="top",
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="lightyellow", alpha=0.9),
    )

    # Mark max drawdown point
    if max_dd > 0:
        ax1.annotate(
            f"Max DD: {max_dd:.1f}%",
            xy=(date_objs[max_dd_idx], cumulative[max_dd_idx]),
            xytext=(30, -30),
            textcoords="offset points",
            fontsize=8,
            arrowprops=dict(arrowstyle="->", color="red"),
            color="red",
        )

    ax1.set_ylabel("Cumulative Return (%)")
    # Combine legends from both axes
    lines1, labels1 = ax1.get_legend_handles_labels()
    if ax1_twin is not None:
        lines2, labels2 = ax1_twin.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="lower right", fontsize=9)
    else:
        ax1.legend(loc="lower right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.axhline(y=0, color="black", linewidth=0.5)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))

    # --- Panel 2: Drawdown ---
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax2.fill_between(date_objs, 0, -drawdown, color="red", alpha=0.4)
    ax2.set_ylabel("Drawdown (%)")
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(-max_dd * 1.3, max_dd * 0.1)
    ax2.axhline(y=0, color="black", linewidth=0.5)

    # --- Panel 3: Monthly Returns ---
    ax3 = fig.add_subplot(gs[2])
    colors = ["#2ca02c" if r > 0 else "#d62728" for r in monthly_ret]
    bars = ax3.bar(month_objs, monthly_ret, width=25, color=colors, alpha=0.7, edgecolor="none")

    # Label extreme months
    for i, (m_obj, ret, cnt) in enumerate(zip(month_objs, monthly_ret, monthly_cnt)):
        if abs(ret) > 30 or ret == monthly_ret.min() or ret == monthly_ret.max():
            ax3.annotate(
                f"{ret:+.0f}%\n({int(cnt)}t)",
                xy=(m_obj, ret),
                xytext=(0, 10 if ret > 0 else -15),
                textcoords="offset points",
                fontsize=7,
                ha="center",
                color="darkred" if ret < 0 else "darkgreen",
            )

    ax3.set_ylabel("Monthly Return (%)")
    ax3.axhline(y=0, color="black", linewidth=0.5)
    ax3.grid(True, alpha=0.3, axis="y")
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax3.xaxis.set_major_locator(mdates.MonthLocator(interval=2))

    # --- Panel 4: Monthly Trade Counts ---
    ax4 = fig.add_subplot(gs[3], sharex=ax3)
    ax4.bar(month_objs, monthly_cnt, width=25, color="#1f77b4", alpha=0.5, edgecolor="none")
    ax4.set_ylabel("Trades")
    ax4.set_xlabel("Date")
    ax4.grid(True, alpha=0.3, axis="y")

    # Final formatting
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")
    plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha="right")
    plt.setp(ax4.xaxis.get_majorticklabels(), rotation=45, ha="right")

    try:
        fig.tight_layout(rect=[0, 0, 1, 0.96])
    except UserWarning:
        pass

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Chart saved to {save_path}")
    if show:
        plt.show()
    if not show and not save_path:
        # Default: save to charts/ with descriptive name
        os.makedirs("charts", exist_ok=True)
        suffix = title.split(" ")[0].lower().replace("-", "_")
        default_path = f"charts/equity_curve_{suffix}.png"
        fig.savefig(default_path, dpi=150, bbox_inches="tight")
        print(f"  Chart saved to {default_path}")

    plt.close(fig)


def plot_instrument_breakdown(
    trades: List[dict],
    save_path: Optional[str] = None,
):
    """Generate instrument-level performance heatmap."""
    from collections import defaultdict

    inst_ret = defaultdict(float)
    inst_cnt = defaultdict(int)
    inst_wins = defaultdict(float)
    inst_losses = defaultdict(float)

    for r in trades:
        inst = r["instrument"]
        ret = r.get("actual_return_sl_net", 0)
        inst_ret[inst] += ret
        inst_cnt[inst] += 1
        if ret > 0:
            inst_wins[inst] += ret
        else:
            inst_losses[inst] += abs(ret)

    # Sort by total return
    instruments = sorted(inst_ret.keys(), key=lambda x: inst_ret[x], reverse=True)
    if not instruments:
        return

    returns = [inst_ret[i] for i in instruments]
    counts = [inst_cnt[i] for i in instruments]
    pfs = [
        inst_wins[i] / inst_losses[i] if inst_losses[i] > 0 else 10.0
        for i in instruments
    ]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, max(8, len(instruments) * 0.35)))
    fig.suptitle("Instrument-Level Performance", fontsize=14, fontweight="bold")

    # Bar chart: total return by instrument
    colors = ["#2ca02c" if r > 0 else "#d62728" for r in returns]
    y_pos = range(len(instruments))
    ax1.barh(y_pos, returns, color=colors, alpha=0.7)
    ax1.set_yticks(y_pos)
    ax1.set_yticklabels(instruments, fontsize=8)
    ax1.set_xlabel("Total Return (%)")
    ax1.set_title("Total Return by Instrument")
    ax1.axvline(x=0, color="black", linewidth=0.5)
    ax1.grid(True, alpha=0.3, axis="x")
    ax1.invert_yaxis()

    # Bar chart: PF by instrument
    pf_colors = ["#2ca02c" if p > 1 else "#d62728" for p in pfs]
    ax2.barh(y_pos, [min(p, 5) for p in pfs], color=pf_colors, alpha=0.7)
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels([f"{i} ({c}t)" for i, c in zip(instruments, counts)], fontsize=8)
    ax2.set_xlabel("Profit Factor (capped at 5)")
    ax2.set_title("Profit Factor by Instrument")
    ax2.axvline(x=1, color="black", linewidth=0.5, linestyle="--")
    ax2.grid(True, alpha=0.3, axis="x")
    ax2.invert_yaxis()

    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Instrument chart saved to {save_path}")
    else:
        os.makedirs("charts", exist_ok=True)
        default_path = "charts/instrument_breakdown.png"
        fig.savefig(default_path, dpi=150, bbox_inches="tight")
        print(f"  Instrument chart saved to {default_path}")

    plt.close(fig)


def print_summary_table(trades: List[dict], label: str = ""):
    """Print a text summary table to console."""
    if not trades:
        print("  No trades.")
        return

    months, monthly_ret, monthly_cnt, monthly_pf = compute_monthly_stats(trades)

    print(f"\n{'=' * 72}")
    print(f"  MONTHLY PERFORMANCE{f' — {label}' if label else ''}")
    print(f"{'=' * 72}")
    print(f"  {'Month':<10} {'Return':>10} {'Trades':>8} {'PF':>8} {'Cum.Ret':>10}")
    print(f"  {'-' * 50}")

    cum = 0
    for m, ret, cnt, pf in zip(months, monthly_ret, monthly_cnt, monthly_pf):
        cum += ret
        pf_str = f"{pf:.2f}" if pf < 10 else "∞"
        marker = " ◄◄" if ret < -30 else ("  ★" if ret > 30 else "")
        print(
            f"  {m:<10} {ret:>+10.2f}% {int(cnt):>8} {pf_str:>8} {cum:>+10.2f}%{marker}"
        )

    total_ret = monthly_ret.sum()
    total_trades = int(monthly_cnt.sum())
    n_positive = (monthly_ret > 0).sum()
    n_months = len(months)

    print(f"  {'-' * 50}")
    print(f"  {'TOTAL':<10} {total_ret:>+10.2f}% {total_trades:>8}")
    print(f"  Positive months: {n_positive}/{n_months} ({n_positive/n_months*100:.0f}%)")
    print(f"  Best month:  {monthly_ret.max():+.2f}%")
    print(f"  Worst month: {monthly_ret.min():+.2f}%")
    print(f"  Avg month:   {monthly_ret.mean():+.2f}%")
    print(f"  Std month:   {monthly_ret.std():.2f}%")
    if monthly_ret.std() > 0:
        sharpe_monthly = monthly_ret.mean() / monthly_ret.std()
        print(f"  Monthly Sharpe: {sharpe_monthly:.2f}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Equity Curve & Drawdown Visualization"
    )
    parser.add_argument(
        "--meta-gate", action="store_true",
        help="Apply meta-classifier gate to filter trades",
    )
    parser.add_argument(
        "--meta-threshold", type=float, default=None,
        help="Override meta-classifier threshold (default: model's auto-tuned)",
    )
    parser.add_argument(
        "--save", type=str, default=None,
        help="Save chart to specific path (e.g., equity_curve.png)",
    )
    parser.add_argument(
        "--show", action="store_true",
        help="Display chart interactively (requires GUI)",
    )
    parser.add_argument(
        "--instruments", action="store_true",
        help="Also generate instrument breakdown chart",
    )
    parser.add_argument(
        "--results-file", type=str, default=RESULTS_FILE,
        help="Path to walkforward results JSON",
    )
    parser.add_argument(
        "--position-sizing", action="store_true",
        help="Overlay Kelly-sized equity curve on the chart",
    )
    args = parser.parse_args()

    if args.show:
        matplotlib.use("TkAgg")

    print(f"\n{'=' * 65}")
    print(f"  EQUITY CURVE VISUALIZATION")
    print(f"{'=' * 65}")

    # Load data
    data, traded = load_results(args.results_file)
    config = data.get("config", {})
    print(f"  Loaded {len(traded)} traded signals from {args.results_file}")
    print(f"  Period: {traded[0]['datetime'][:10]} to {traded[-1]['datetime'][:10]}")
    print(f"  Slippage+Commission: {config.get('slippage_commission_pct', '?')}%")

    rejected_trades = None
    title_prefix = "Baseline"

    if args.meta_gate:
        traded, rejected_trades = apply_meta_gate(traded, args.meta_threshold)
        if rejected_trades:
            title_prefix = "Meta-Gated"
        else:
            title_prefix = "Baseline (meta-gate failed)"

    # Print summary
    print_summary_table(traded, label=title_prefix)

    if rejected_trades:
        print_summary_table(rejected_trades, label="Rejected")

    # Plot
    title = f"{title_prefix} Equity Curve — OOS Walk-Forward"
    if args.position_sizing:
        title += " (+ Kelly Sizing)"
    plot_equity_curve(
        traded,
        title=title,
        save_path=args.save,
        show=args.show,
        rejected_trades=rejected_trades,
        show_sized=args.position_sizing,
    )

    if args.instruments:
        save_inst = None
        if args.save:
            base, ext = os.path.splitext(args.save)
            save_inst = f"{base}_instruments{ext}"
        plot_instrument_breakdown(traded, save_path=save_inst)

    print("\n  Done.")


if __name__ == "__main__":
    main()
