"""
Walk-Forward Out-of-Sample Backtest
====================================
Splits data into IN-SAMPLE (2016-2023) and OUT-OF-SAMPLE (2024-2025).
The statistical predictor is trained ONLY on in-sample data, then tested
on out-of-sample data it has never seen.

This is the gold standard for validating that the edge is real and not
just curve-fitting to historical noise.

Usage:
    python backtest_walkforward.py                  # default: all OOS docs
    python backtest_walkforward.py --oos-samples 2000
    python backtest_walkforward.py --split-year 2024  # change IS/OOS boundary
"""

import json, time, random, argparse, sys, os
from collections import defaultdict
from datetime import datetime
import numpy as np

RAG_DOCS_PATH = "rag_documents_v2/all_pattern_documents.json"

# Import centralized production config
from trading_config import (
    PRIMARY_HORIZON, EXCLUDED_INSTRUMENTS, EXCLUDED_PATTERNS,
    WHITELISTED_PATTERNS, STRUCTURAL_SL_PATTERNS,
    STANDARD_SL_MULTIPLIER, STRUCTURAL_SL_MULTIPLIER,
    SL_FLOOR_PCT, SL_CAP_PCT, SLIPPAGE_COMMISSION_PCT,
    MIN_MATCHES, TOP_K, MAX_PER_INSTRUMENT,
    ALLOWED_TIMEFRAMES, ALLOWED_INSTRUMENTS, ALLOWED_TIERS,
    INSTRUMENT_SECTORS,
    HORIZON_SL_CONFIG, PRODUCTION_FILTERS, HORIZON_EDGE_THRESHOLDS,
    DISABLED_HORIZONS,
    is_tradeable_instrument, is_tradeable_timeframe, is_tradeable_pattern,
    is_tradeable_tier, filter_doc_for_trading,
)
from position_sizing import PositionSizer, HORIZON_SIZE_MULTIPLIER, SECTOR_VOL_MULTIPLIER

from fast_stat_predictor import FastStatPredictor


# ============================================================
# METRICS
# ============================================================

def compute_metrics(results, label=""):
    n = len(results)
    if n == 0:
        print(f"  {label}: No results")
        return {}

    correct = sum(1 for r in results if r["predicted_direction"] == r["actual_direction"])
    accuracy = correct / n * 100

    binary = [r for r in results if r["predicted_direction"] != "neutral"]
    b_correct = sum(1 for r in binary if r["predicted_direction"] == r["actual_direction"])
    b_accuracy = b_correct / len(binary) * 100 if binary else 0

    # Raw trade returns
    trades = []
    for r in results:
        if r["predicted_direction"] == "bullish":
            trades.append(r["actual_return"])
        elif r["predicted_direction"] == "bearish":
            trades.append(-r["actual_return"])

    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    gross_wins = sum(wins) if wins else 0
    gross_losses = abs(sum(losses)) if losses else 0.001
    pf = gross_wins / gross_losses
    total_ret = sum(trades)
    avg_ret = float(np.mean(trades)) if trades else 0
    std_ret = float(np.std(trades)) if trades else 1
    sharpe = avg_ret / std_ret if std_ret > 0 else 0

    metrics = {
        "n": n, "accuracy": accuracy, "binary_accuracy": b_accuracy,
        "n_trades": len(trades), "win_rate": win_rate,
        "profit_factor": pf, "total_return": total_ret,
        "avg_return": avg_ret, "sharpe": sharpe,
    }

    print(f"\n  {'=' * 70}")
    print(f"  {label}  ({n} predictions)")
    print(f"  {'=' * 70}")
    print(f"  Directional accuracy:  {accuracy:.1f}%  ({correct}/{n})")
    print(f"  Binary accuracy:       {b_accuracy:.1f}%  ({b_correct}/{len(binary)})")
    print(f"  Win rate:              {win_rate:.1f}%  ({len(wins)}/{len(trades)} trades)")
    print(f"  Profit factor:         {pf:.2f}")
    print(f"  Total return:          {total_ret:+.2f}%")
    print(f"  Avg return/trade:      {avg_ret:+.4f}%")
    print(f"  Sharpe (per trade):    {sharpe:+.4f}")

    # SL-adjusted
    has_sl = any("actual_return_sl" in r for r in results)
    if has_sl:
        sl_trades = []
        for r in results:
            if r["predicted_direction"] == "bullish":
                sl_trades.append(r.get("actual_return_sl", r["actual_return"]))
            elif r["predicted_direction"] == "bearish":
                sl_trades.append(r.get("actual_return_sl", -r["actual_return"]))
        if sl_trades:
            sl_wins = [t for t in sl_trades if t > 0]
            sl_losses = [t for t in sl_trades if t <= 0]
            sl_wr = len(sl_wins) / len(sl_trades) * 100
            sl_gw = sum(sl_wins) if sl_wins else 0
            sl_gl = abs(sum(sl_losses)) if sl_losses else 0.001
            sl_pf = sl_gw / sl_gl
            sl_total = sum(sl_trades)
            sl_avg = float(np.mean(sl_trades))
            sl_std = float(np.std(sl_trades)) if len(sl_trades) > 1 else 1
            sl_sharpe = sl_avg / sl_std if sl_std > 0 else 0
            n_triggered = sum(1 for r in results if r.get("sl_triggered", False))

            print(f"\n  --- WITH STOP-LOSS (tiered: {STANDARD_SL_MULTIPLIER}x / {STRUCTURAL_SL_MULTIPLIER}x ATR) ---")
            print(f"  SL triggers:           {n_triggered}/{len(sl_trades)} ({n_triggered / len(sl_trades) * 100:.1f}%)")
            print(f"  Win rate (SL):         {sl_wr:.1f}%")
            print(f"  Profit factor (SL):    {sl_pf:.2f}  (was {pf:.2f})")
            print(f"  Total return (SL):     {sl_total:+.2f}%  (was {total_ret:+.2f}%)")
            print(f"  Avg return/trade (SL): {sl_avg:+.4f}%  (was {avg_ret:+.4f}%)")
            print(f"  Sharpe (SL):           {sl_sharpe:+.4f}")

            metrics["sl_win_rate"] = sl_wr
            metrics["sl_profit_factor"] = sl_pf
            metrics["sl_total_return"] = sl_total
            metrics["sl_avg_return"] = sl_avg
            metrics["sl_sharpe"] = sl_sharpe
            metrics["sl_triggers"] = n_triggered

    # Cost-adjusted (SL + slippage + commissions)
    has_net = any("actual_return_sl_net" in r for r in results)
    if has_net:
        net_trades = []
        for r in results:
            if r["predicted_direction"] == "bullish":
                net_trades.append(r.get("actual_return_sl_net", r["actual_return"] - SLIPPAGE_COMMISSION_PCT))
            elif r["predicted_direction"] == "bearish":
                net_trades.append(r.get("actual_return_sl_net", -r["actual_return"] - SLIPPAGE_COMMISSION_PCT))
        if net_trades:
            net_wins = [t for t in net_trades if t > 0]
            net_losses = [t for t in net_trades if t <= 0]
            net_wr = len(net_wins) / len(net_trades) * 100
            net_gw = sum(net_wins) if net_wins else 0
            net_gl = abs(sum(net_losses)) if net_losses else 0.001
            net_pf = net_gw / net_gl
            net_total = sum(net_trades)
            net_avg = float(np.mean(net_trades))
            net_std = float(np.std(net_trades)) if len(net_trades) > 1 else 1
            net_sharpe = net_avg / net_std if net_std > 0 else 0
            total_cost = SLIPPAGE_COMMISSION_PCT * len(net_trades)

            print(f"\n  --- WITH SL + TRADING COSTS ({SLIPPAGE_COMMISSION_PCT:.2f}% per trade) ---")
            print(f"  Total cost drag:       {total_cost:+.2f}% across {len(net_trades)} trades")
            print(f"  Win rate (net):        {net_wr:.1f}%")
            ref_pf = metrics.get("sl_profit_factor", pf)
            print(f"  Profit factor (net):   {net_pf:.2f}  (was {ref_pf:.2f} with SL only)")
            ref_total = metrics.get("sl_total_return", total_ret)
            print(f"  Total return (net):    {net_total:+.2f}%  (was {ref_total:+.2f}% with SL only)")
            ref_avg = metrics.get("sl_avg_return", avg_ret)
            print(f"  Avg return/trade (net):{net_avg:+.4f}%  (was {ref_avg:+.4f}% with SL only)")
            print(f"  Sharpe (net):          {net_sharpe:+.4f}")
            edge_survives = net_pf > 1.0
            print(f"  EDGE SURVIVES COSTS:   {'YES ✓' if edge_survives else 'NO ✗'}  (PF {'>' if edge_survives else '<='} 1.0)")

            metrics["net_win_rate"] = net_wr
            metrics["net_profit_factor"] = net_pf
            metrics["net_total_return"] = net_total
            metrics["net_avg_return"] = net_avg
            metrics["net_sharpe"] = net_sharpe
            metrics["edge_survives_costs"] = edge_survives

    neutrals = sum(1 for r in results if r["predicted_direction"] == "neutral")
    print(f"  Neutral (no trade):    {neutrals} ({neutrals/n*100:.1f}%)")

    return metrics


def compute_drawdown(results):
    """Compute max drawdown from the equity curve (SL+cost adjusted)."""
    equity = [0.0]
    for r in results:
        if r["predicted_direction"] == "neutral":
            continue
        ret = r.get("actual_return_sl_net", r.get("actual_return_sl", r["actual_return"]))
        equity.append(equity[-1] + ret)

    peak = equity[0]
    max_dd = 0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd
    return max_dd, equity


# Horizon int → label mapping (for PositionSizer)
HORIZON_LABEL_MAP = {1: "BTST_1d", 3: "Swing_3d", 5: "Swing_5d", 10: "Swing_10d"}


def compute_weighted_metrics(results, horizon, instrument_sectors=None, label="POSITION-WEIGHTED"):
    """R7: Compute position-weighted equity and metrics.

    For each trade, calculates Kelly position size, then weights the PnL by
    that size/capital.  Returns a dict with weighted PF, WR, max DD, etc.

    Args:
        results: list of result dicts (must have predicted_wr, predicted_pf,
                 sl_pct, predicted_conf_level, instrument, actual_return_sl_net)
        horizon: int horizon (1,3,5,10,25)
        instrument_sectors: dict mapping instrument → sector (optional)
        label: display label for printing
    """
    from position_sizing import PositionSizer, HORIZON_SIZE_MULTIPLIER, SECTOR_VOL_MULTIPLIER

    sizer = PositionSizer()
    horizon_label = HORIZON_LABEL_MAP.get(horizon, "Swing_5d")

    weighted_returns = []
    total_position = 0.0
    weighted_wins = 0.0
    weighted_losses = 0.0
    n_sized = 0

    for r in results:
        if r["predicted_direction"] == "neutral":
            continue

        wr = r.get("predicted_wr", 50)
        pf = r.get("predicted_pf", 1.0)
        sl = r.get("sl_pct", 1.5)
        conf = r.get("predicted_conf_level", "MEDIUM")
        inst = r.get("instrument", "")
        sector = (instrument_sectors or {}).get(inst) if instrument_sectors else None

        sizing = sizer.calculate_size(
            win_rate=wr, profit_factor=pf, sl_pct=sl,
            confidence_level=conf, horizon_label=horizon_label, sector=sector,
        )
        pos_pct = sizing["position_pct"]  # % of capital allocated
        if pos_pct <= 0:
            continue  # below minimum — skip

        ret = r.get("actual_return_sl_net", r.get("actual_return_sl", r["actual_return"]))
        # Weighted return: pos_pct/100 * ret (% of capital * return%)
        w_ret = (pos_pct / 100) * ret
        weighted_returns.append(w_ret)
        total_position += pos_pct
        n_sized += 1
        if w_ret > 0:
            weighted_wins += w_ret
        else:
            weighted_losses += abs(w_ret)

    if not weighted_returns:
        print(f"\n  {label}: No trades sized above minimum.")
        return {}

    # Equity curve
    equity = [0.0]
    for wr in weighted_returns:
        equity.append(equity[-1] + wr)

    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd

    w_pf = weighted_wins / weighted_losses if weighted_losses > 0.001 else 99.0
    w_wr = sum(1 for w in weighted_returns if w > 0) / len(weighted_returns) * 100
    avg_w_ret = sum(weighted_returns) / len(weighted_returns)
    total_ret = sum(weighted_returns)
    avg_pos = total_position / n_sized if n_sized else 0

    print(f"\n  {label} (n={n_sized}, avg position={avg_pos:.2f}% of capital)")
    print(f"  Weighted PF:           {w_pf:.3f}")
    print(f"  Weighted WR:           {w_wr:.1f}%")
    print(f"  Total equity (bps):    {total_ret:.2f}")
    print(f"  Avg return/trade:      {avg_w_ret:.4f}%")
    print(f"  Max drawdown:          {max_dd:.2f}%")

    return {
        "weighted_pf": round(w_pf, 3),
        "weighted_wr": round(w_wr, 1),
        "total_equity_bps": round(total_ret, 2),
        "avg_weighted_return": round(avg_w_ret, 4),
        "max_drawdown": round(max_dd, 2),
        "n_trades": n_sized,
        "avg_position_pct": round(avg_pos, 2),
    }


def breakdown(results, field, label):
    buckets = defaultdict(list)
    for r in results:
        buckets[r.get(field, "?")].append(r)

    print(f"\n  {label}")
    print(f"  {'-' * 60}")
    print(f"  {'Value':<20} {'Count':>6} {'Accuracy':>10} {'WR':>8} {'PF':>8} {'NetPF':>8}")

    for val in sorted(buckets.keys(), key=lambda x: -len(buckets[x])):
        b = buckets[val]
        if len(b) < 5:
            continue
        acc = sum(1 for r in b if r["predicted_direction"] == r["actual_direction"]) / len(b) * 100
        trades = []
        net_trades = []
        for r in b:
            if r["predicted_direction"] == "bullish":
                trades.append(r["actual_return"])
                net_trades.append(r.get("actual_return_sl_net",
                                        r["actual_return"] - SLIPPAGE_COMMISSION_PCT))
            elif r["predicted_direction"] == "bearish":
                trades.append(-r["actual_return"])
                net_trades.append(r.get("actual_return_sl_net",
                                        -r["actual_return"] - SLIPPAGE_COMMISSION_PCT))
        wr = len([t for t in trades if t > 0]) / len(trades) * 100 if trades else 0
        gw = sum(t for t in trades if t > 0)
        gl = abs(sum(t for t in trades if t <= 0)) or 0.001
        pf = gw / gl
        net_gw = sum(t for t in net_trades if t > 0)
        net_gl = abs(sum(t for t in net_trades if t <= 0)) or 0.001
        net_pf = net_gw / net_gl
        print(f"  {str(val):<20} {len(b):>6} {acc:>9.1f}% {wr:>7.1f}% {pf:>7.2f} {net_pf:>7.2f}")


# ============================================================
# ROLLING WALK-FORWARD
# ============================================================

def run_rolling_walkforward(all_docs, start_oos_year=2021, end_year=2026, seed=42, horizon=None):
    """Run expanding-window walk-forward across multiple years.
    
    For each OOS year Y:
      - Train on all docs with datetime < Y-01-01
      - Test on docs with datetime in year Y
    
    This validates stability of the edge across different market regimes.
    """
    hz = horizon or PRIMARY_HORIZON
    print(f"\n{'#' * 74}")
    print(f"  ROLLING WALK-FORWARD (expanding window)")
    print(f"  OOS years: {start_oos_year} → {end_year - 1}")
    print(f"{'#' * 74}")

    # Pre-filter docs for production universe
    eligible = []
    for d in all_docs:
        dt_str = d.get("datetime", "")
        if not dt_str:
            continue
        if d.get("instrument") in EXCLUDED_INSTRUMENTS:
            continue
        if not is_tradeable_instrument(d.get("instrument", "")):
            continue
        if not is_tradeable_timeframe(d.get("timeframe", "")):
            continue
        if d.get(f"fwd_{hz}_return_pct") is None:
            continue
        if d.get(f"fwd_{hz}_direction") is None:
            continue
        eligible.append(d)

    print(f"  Eligible docs after filters: {len(eligible)}")

    fold_results = []

    for oos_year in range(start_oos_year, end_year):
        split_date = f"{oos_year}-01-01"
        end_date = f"{oos_year + 1}-01-01"

        train = [d for d in eligible if d.get("datetime", "") < split_date]
        test = [d for d in eligible
                if split_date <= d.get("datetime", "") < end_date]

        if len(train) < 1000 or len(test) < 50:
            print(f"\n  Year {oos_year}: Skipped (train={len(train)}, test={len(test)})")
            continue

        print(f"\n  {'='*60}")
        print(f"  FOLD: Train ≤{oos_year-1} ({len(train)} docs)  |  Test {oos_year} ({len(test)} docs)")
        print(f"  {'='*60}")

        h_edge_cfg_roll = HORIZON_EDGE_THRESHOLDS.get(hz, HORIZON_EDGE_THRESHOLDS.get(5, {"neutral_zone": 3.0}))
        nz_roll = h_edge_cfg_roll.get("neutral_zone", 3.0)
        sp = FastStatPredictor(train, horizon=hz, neutral_zone=nz_roll)

        fold_oos = []
        for doc in test:
            doc_patterns = set(p.strip() for p in doc.get("patterns", "").split(",") if p.strip())
            actual_dir = doc[f"fwd_{hz}_direction"]
            actual_ret = float(doc[f"fwd_{hz}_return_pct"])

            pred = sp.predict(doc)
            if pred is None:
                fold_oos.append({
                    "predicted_direction": "neutral",
                    "actual_direction": actual_dir, "actual_return": actual_ret,
                    "actual_return_sl": actual_ret, "actual_return_sl_net": actual_ret,
                    "sl_triggered": False, "predicted_conf_level": "LOW", "edge": 0,
                    "instrument": doc.get("instrument", "?"),
                    "datetime": doc.get("datetime", "?"),
                })
                continue

            # SL simulation (R1+R2+R5 — matches sweep loop logic)
            mae_h_val = float(doc.get(f"mae_{hz}", 0) or 0)
            mfe_h_val = float(doc.get(f"mfe_{hz}", 0) or 0)
            atr_14 = float(doc.get("atr_14", 0) or 0)
            close_price = float(doc.get("close", 1) or 1)

            h_sl_cfg = HORIZON_SL_CONFIG.get(hz, HORIZON_SL_CONFIG[5])
            is_structural = bool(doc_patterns & STRUCTURAL_SL_PATTERNS)
            base_sl = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER
            sl_scaled = h_sl_cfg["sl_mult_scale"] * base_sl
            sl_pct = sl_scaled * atr_14 / close_price * 100 if atr_14 > 0 and close_price > 0 else 1.0
            sl_pct = max(SL_FLOOR_PCT, min(h_sl_cfg["sl_cap"], sl_pct))
            target_pct = sl_pct * h_sl_cfg["rr_min"]

            pred_dir = pred["predicted_direction"]
            sl_triggered = False
            actual_ret_sl = actual_ret
            if pred_dir == "bullish":
                if mfe_h_val >= target_pct:
                    actual_ret_sl = target_pct
                elif mfe_h_val >= target_pct * 0.5 and mae_h_val >= -sl_pct:
                    actual_ret_sl = max(0.0, actual_ret)
                elif mae_h_val < -sl_pct:
                    sl_triggered = True; actual_ret_sl = -sl_pct
            elif pred_dir == "bearish":
                bear_actual = -actual_ret
                if (-mae_h_val) >= target_pct:
                    actual_ret_sl = target_pct
                elif (-mae_h_val) >= target_pct * 0.5 and mfe_h_val <= sl_pct:
                    actual_ret_sl = max(0.0, bear_actual)
                elif mfe_h_val > sl_pct:
                    sl_triggered = True; actual_ret_sl = -sl_pct
                else:
                    actual_ret_sl = bear_actual

            actual_ret_sl_net = actual_ret_sl - SLIPPAGE_COMMISSION_PCT

            fold_oos.append({
                "predicted_direction": pred_dir,
                "predicted_conf_level": pred["confidence_level"],
                "edge": pred["edge"],
                "actual_direction": actual_dir,
                "actual_return": actual_ret,
                "actual_return_sl": round(actual_ret_sl, 4),
                "actual_return_sl_net": round(actual_ret_sl_net, 4),
                "sl_triggered": sl_triggered,
                "instrument": doc.get("instrument", "?"),
                "datetime": doc.get("datetime", "?"),
            })

        fold_m = compute_metrics(fold_oos, f"OOS {oos_year}")
        fold_results.append({
            "year": oos_year,
            "train_size": len(train),
            "test_size": len(test),
            "metrics": fold_m,
        })

    # Summary table
    print(f"\n{'#' * 74}")
    print(f"  ROLLING WALK-FORWARD SUMMARY")
    print(f"{'#' * 74}")
    print(f"\n  {'Year':<6} {'Train':>7} {'Test':>6} {'Trades':>7} {'WR':>7} {'PF':>7} {'NetPF':>7} {'TotRet':>10}")
    print(f"  {'-' * 62}")

    all_net_pfs = []
    for fr in fold_results:
        m = fr["metrics"]
        net_pf = m.get("net_profit_factor", m.get("profit_factor", 0))
        all_net_pfs.append(net_pf)
        print(f"  {fr['year']:<6} {fr['train_size']:>7} {fr['test_size']:>6} "
              f"{m.get('n_trades', 0):>7} "
              f"{m.get('net_win_rate', m.get('win_rate', 0)):>6.1f}% "
              f"{m.get('profit_factor', 0):>6.2f} "
              f"{net_pf:>6.2f} "
              f"{m.get('net_total_return', m.get('total_return', 0)):>+9.1f}%")

    if all_net_pfs:
        avg_pf = np.mean(all_net_pfs)
        std_pf = np.std(all_net_pfs)
        min_pf = min(all_net_pfs)
        max_pf = max(all_net_pfs)
        profitable_folds = sum(1 for p in all_net_pfs if p > 1.0)
        print(f"\n  Avg Net PF:    {avg_pf:.2f} ± {std_pf:.2f}")
        print(f"  Min / Max PF:  {min_pf:.2f} / {max_pf:.2f}")
        print(f"  Profitable:    {profitable_folds}/{len(all_net_pfs)} folds")

        if avg_pf > 1.0 and profitable_folds >= len(all_net_pfs) * 0.6:
            print(f"\n  ★ ROLLING EDGE CONFIRMED — {profitable_folds}/{len(all_net_pfs)} "
                  f"folds profitable, avg PF {avg_pf:.2f} ★")
        else:
            print(f"\n  ✗ ROLLING EDGE WEAK — only {profitable_folds}/{len(all_net_pfs)} "
                  f"folds profitable, avg PF {avg_pf:.2f}")

    return fold_results


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Walk-forward OOS backtest")
    parser.add_argument("--oos-samples", type=int, default=0,
                        help="Max OOS samples (0 = all)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--split-year", type=int, default=2024,
                        help="First year of OOS period (default: 2024)")
    parser.add_argument("--rolling", action="store_true",
                        help="Run rolling (expanding-window) walk-forward across multiple years")
    parser.add_argument("--rolling-start", type=int, default=2021,
                        help="First OOS year for rolling walk-forward (default: 2021)")
    parser.add_argument("--meta-gate", action="store_true",
                        help="Enable meta-classifier quality gate on trades")
    parser.add_argument("--meta-threshold", type=float, default=None,
                        help="Override meta-classifier threshold (default: use saved model threshold)")
    parser.add_argument("--horizon", type=int, default=None,
                        help="Override prediction horizon (1/3/5/10). Default: PRIMARY_HORIZON")
    parser.add_argument("--sweep-horizons", action="store_true",
                        help="Run backtest for every horizon (1,3,5,10) and compare")
    args = parser.parse_args()

    # Determine horizon(s) to test
    horizons_to_test = [args.horizon or PRIMARY_HORIZON]
    if args.sweep_horizons:
        horizons_to_test = [1, 3, 5, 10]  # 25d removed from scope

    print("=" * 74)
    print("  WALK-FORWARD OUT-OF-SAMPLE BACKTEST")
    print("=" * 74)

    # Load all docs (use JSONL to avoid Windows >1GB read limit)
    jsonl_path = RAG_DOCS_PATH.replace(".json", ".jsonl")
    if os.path.exists(jsonl_path):
        print(f"\n  Loading documents from {jsonl_path} (JSONL)...")
        all_docs = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    all_docs.append(json.loads(line))
    else:
        print(f"\n  Loading documents from {RAG_DOCS_PATH}...")
        with open(RAG_DOCS_PATH, encoding="utf-8") as f:
            raw = f.read()
        all_docs = json.loads(raw)
    print(f"  Total documents: {len(all_docs):,}")

    # Rolling walk-forward mode
    if args.rolling:
        fold_results = run_rolling_walkforward(
            all_docs, start_oos_year=args.rolling_start, seed=args.seed,
            horizon=args.horizon or PRIMARY_HORIZON,
        )
        # Save
        out_path = "backtest_rolling_results.json"
        with open(out_path, "w") as f:
            json.dump({"folds": fold_results}, f, indent=2, default=str)
        print(f"\n  Rolling results saved to {out_path}")
        return

    # Parse dates and split
    split_date = f"{args.split_year}-01-01"

    for h in horizons_to_test:
      # R6: Skip disabled horizons
      if h in DISABLED_HORIZONS:
          print(f"\n  HORIZON {h} — DISABLED (in DISABLED_HORIZONS), skipping.")
          continue

      print(f"\n{'#' * 74}")
      print(f"  HORIZON = {h} day(s)")
      print(f"{'#' * 74}")

      in_sample = []
      out_of_sample = []

      for d in all_docs:
        dt_str = d.get("datetime", "")
        if not dt_str:
            continue
        if d.get("instrument") in EXCLUDED_INSTRUMENTS:
            continue
        if not is_tradeable_instrument(d.get("instrument", "")):
            continue
        if not is_tradeable_timeframe(d.get("timeframe", "")):
            continue
        if d.get(f"fwd_{h}_return_pct") is None:
            continue
        if d.get(f"fwd_{h}_direction") is None:
            continue

        if dt_str < split_date:
            in_sample.append(d)
        else:
            out_of_sample.append(d)

      # --- everything below stays inside the for-h loop ---
      print(f"\n  Split boundary:        {split_date}")
      print(f"  In-sample (train):     {len(in_sample)} docs  "
            f"({in_sample[0]['datetime'][:10] if in_sample else '?'} -> "
            f"{in_sample[-1]['datetime'][:10] if in_sample else '?'})")
      print(f"  Out-of-sample (test):  {len(out_of_sample)} docs  "
            f"({out_of_sample[0]['datetime'][:10] if out_of_sample else '?'} -> "
            f"{out_of_sample[-1]['datetime'][:10] if out_of_sample else '?'})")

      # Optionally sub-sample OOS
      if args.oos_samples > 0 and args.oos_samples < len(out_of_sample):
          random.seed(args.seed)
          out_of_sample = random.sample(out_of_sample, args.oos_samples)
          print(f"  OOS sub-sampled to:    {len(out_of_sample)}")

      # Load meta-classifier if requested
      meta_clf = None
      if args.meta_gate:
          try:
              from meta_classifier import MetaClassifier
              meta_clf = MetaClassifier()
              if meta_clf.load():
                  if args.meta_threshold is not None:
                      meta_clf.threshold = args.meta_threshold
                  print(f"  Meta-classifier loaded (threshold={meta_clf.threshold:.2f})")
              else:
                  print(f"  WARNING: Meta-classifier model not found. Running without gate.")
                  meta_clf = None
          except ImportError as e:
              print(f"  WARNING: Could not import meta_classifier: {e}")
              meta_clf = None

      # Train predictor on IN-SAMPLE only (R4: per-horizon neutral zone)
      h_edge_cfg = HORIZON_EDGE_THRESHOLDS.get(h, HORIZON_EDGE_THRESHOLDS.get(5, {"neutral_zone": 3.0}))
      nz = h_edge_cfg.get("neutral_zone", 3.0)
      print(f"\n  Training statistical predictor on {len(in_sample)} in-sample docs...")
      print(f"  Horizon={h}, neutral_zone={nz}%")
      sp = FastStatPredictor(in_sample, horizon=h, neutral_zone=nz)
      print(f"  Predictor ready. Base rates: {sp.base_rates}")
      print(f"  Patterns indexed: {len(sp.pattern_idx)}")

      # Test on OUT-OF-SAMPLE
      print(f"\n  Testing on {len(out_of_sample)} out-of-sample docs...\n")

      oos_results = []
      t0 = time.time()

      for idx, doc in enumerate(out_of_sample):
          doc_patterns = set(p.strip() for p in doc.get("patterns", "").split(",") if p.strip())
          tradeable_patterns = doc_patterns - EXCLUDED_PATTERNS
          actual_dir = doc[f"fwd_{h}_direction"]
          actual_ret = float(doc[f"fwd_{h}_return_pct"])

          if not tradeable_patterns:
              oos_results.append({
                  "doc_id": doc["id"],
                  "instrument": doc.get("instrument", "?"),
                  "timeframe": doc.get("timeframe", "?"),
                  "patterns": doc.get("patterns", "?"),
                  "datetime": doc.get("datetime", "?"),
                  "predicted_direction": "neutral",
                  "predicted_confidence": 0,
                  "predicted_conf_level": "LOW",
                  "edge": 0, "tier": "none",
                  "actual_direction": actual_dir,
                  "actual_return": actual_ret,
                  "actual_return_sl": actual_ret,
                  "actual_return_sl_net": actual_ret,
                  "sl_triggered": False, "sl_pct": 0,
              })
              continue

          pred = sp.predict(doc)

          if pred is None:
              oos_results.append({
                  "doc_id": doc["id"],
                  "instrument": doc.get("instrument", "?"),
                  "timeframe": doc.get("timeframe", "?"),
                  "patterns": doc.get("patterns", "?"),
                  "datetime": doc.get("datetime", "?"),
                  "predicted_direction": "neutral",
                  "predicted_confidence": 0,
                  "predicted_conf_level": "LOW",
                  "edge": 0, "tier": "none",
                  "actual_direction": actual_dir,
                  "actual_return": actual_ret,
                  "actual_return_sl": actual_ret,
                  "actual_return_sl_net": actual_ret,
                  "sl_triggered": False, "sl_pct": 0,
              })
              continue

          # --- Stop-loss simulation (R1: MFE-before-MAE, R2: horizon-scaled, R5: trailing) ---
          mae_h = float(doc.get(f"mae_{h}", 0) or 0)   # horizon-specific MAE (no fallback)
          mfe_h = float(doc.get(f"mfe_{h}", 0) or 0)   # horizon-specific MFE
          atr_14 = float(doc.get("atr_14", 0) or 0)
          close_price = float(doc.get("close", 1) or 1)

          # R2: Horizon-scaled SL (mirrors paper_trader)
          h_sl_cfg = HORIZON_SL_CONFIG.get(h, HORIZON_SL_CONFIG[5])
          is_structural = bool(doc_patterns & STRUCTURAL_SL_PATTERNS)
          base_sl_mult = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER
          sl_mult_scaled = h_sl_cfg["sl_mult_scale"] * base_sl_mult

          if atr_14 > 0 and close_price > 0:
              sl_pct = sl_mult_scaled * atr_14 / close_price * 100
          else:
              sl_pct = 1.0
          sl_pct = max(SL_FLOOR_PCT, min(h_sl_cfg["sl_cap"], sl_pct))

          # Target from R:R ratio + predicted avg return
          pred_avg_ret = abs(pred.get("avg_return", 0) or 0)
          target_pct = max(sl_pct * h_sl_cfg["rr_min"], pred_avg_ret)

          pred_dir = pred["predicted_direction"]
          sl_triggered = False
          target_hit = False
          actual_ret_sl = actual_ret

          # R1: Check target BEFORE SL — if MFE reached target, exit at +target
          # R5: Trailing stop — if MFE > 50% of target, SL moves to breakeven
          if pred_dir == "bullish":
              if mfe_h >= target_pct:
                  # Target hit first (conservative: award target, not full MFE)
                  target_hit = True
                  actual_ret_sl = target_pct
              elif mfe_h >= target_pct * 0.5 and mae_h >= -sl_pct:
                  # R5: Trailing — MFE > 50% target but didn't hit full target
                  # SL trailed to breakeven, trade exits at actual return (floored at 0)
                  actual_ret_sl = max(0.0, actual_ret)
              elif mae_h < -sl_pct:
                  sl_triggered = True
                  actual_ret_sl = -sl_pct
              else:
                  actual_ret_sl = actual_ret
          elif pred_dir == "bearish":
              # For bearish: MFE = how far price dropped (good), MAE = how far price rose (bad)
              # Note: mfe_h is always positive (max favourable), mae_h can be positive (adverse for bear)
              neg_mfe = -mfe_h   # mfe_h is stored as positive even for bearish
              neg_mae = -mae_h   # mae_h stored as the most adverse move
              bear_actual = -actual_ret
              if (-mae_h) >= target_pct:  # price dropped by target_pct
                  target_hit = True
                  actual_ret_sl = target_pct
              elif (-mae_h) >= target_pct * 0.5 and mfe_h <= sl_pct:
                  actual_ret_sl = max(0.0, bear_actual)
              elif mfe_h > sl_pct:
                  sl_triggered = True
                  actual_ret_sl = -sl_pct
              else:
                  actual_ret_sl = bear_actual

          # Net of costs
          actual_ret_sl_net = actual_ret_sl - SLIPPAGE_COMMISSION_PCT

          # Meta-classifier probability (computed always if model loaded)
          meta_prob = None
          meta_pass = True  # default: no gate
          if meta_clf is not None:
              meta_prob = meta_clf.predict_probability(doc, pred)
              if meta_prob is not None:
                  meta_pass = meta_prob >= meta_clf.threshold
              else:
                  meta_pass = False  # if can't compute, reject

          result_entry = {
              "doc_id": doc["id"],
              "instrument": doc.get("instrument", "?"),
              "timeframe": doc.get("timeframe", "?"),
              "patterns": doc.get("patterns", "?"),
              "datetime": doc.get("datetime", "?"),
              "predicted_direction": pred_dir,
              "predicted_confidence": pred["confidence_score"],
              "predicted_conf_level": pred["confidence_level"],
              "edge": pred["edge"],
              "tier": pred["tier"],
              "n_matches": pred.get("n_matches", 0),
              "predicted_pf": pred.get("profit_factor", 0),
              "predicted_wr": pred.get("win_rate", 50),
              "actual_direction": actual_dir,
              "actual_return": actual_ret,
              "actual_return_sl": round(actual_ret_sl, 4),
              "actual_return_sl_net": round(actual_ret_sl_net, 4),
              "sl_triggered": sl_triggered,
              "sl_pct": round(sl_pct, 4),
          }
          if meta_prob is not None:
              result_entry["meta_probability"] = round(meta_prob, 4)
              result_entry["meta_pass"] = meta_pass

          oos_results.append(result_entry)

          if (idx + 1) % 2000 == 0 or idx == len(out_of_sample) - 1:
              elapsed = time.time() - t0
              rate = (idx + 1) / elapsed if elapsed > 0 else 0
              pct = (idx + 1) / len(out_of_sample) * 100
              print(f"    [{idx+1}/{len(out_of_sample)}] {pct:.0f}%  "
                    f"({rate:.0f} docs/s)", flush=True)

      t_total = time.time() - t0
      print(f"\n  Completed in {t_total:.1f}s ({len(oos_results)/t_total:.0f} docs/s)")

      # -------------------------------------------------------
      # RESULTS
      # -------------------------------------------------------
      print(f"\n{'#' * 74}")
      print(f"  WALK-FORWARD OUT-OF-SAMPLE RESULTS")
      print(f"  Train: ≤{args.split_year - 1}  |  Test: {args.split_year}+")
      print(f"{'#' * 74}")

      # All OOS
      oos_m = compute_metrics(oos_results, "ALL OOS")

      # Max drawdown
      max_dd, equity = compute_drawdown(oos_results)
      print(f"  Max drawdown (net):    {max_dd:.2f}%")

      # R3: Production filter aligned with paper_trader (WR, confidence, R:R, edge)
      pf_min_wr = PRODUCTION_FILTERS["min_win_rate"]
      pf_min_conf = PRODUCTION_FILTERS["min_confidence"]
      pf_min_edge = PRODUCTION_FILTERS["min_edge_pct"]
      conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
      min_conf_rank = conf_rank.get(pf_min_conf, 2)
      prod_filter = [
          r for r in oos_results
          if conf_rank.get(r.get("predicted_conf_level", "LOW"), 0) >= min_conf_rank
          and abs(r.get("edge", 0)) >= pf_min_edge
          and r.get("predicted_wr", 0) >= pf_min_wr
      ]
      prod_m = compute_metrics(prod_filter,
          f"PRODUCTION FILTER (conf>={pf_min_conf}, WR>={pf_min_wr}, edge>={pf_min_edge}%)")
      if prod_filter:
          max_dd_p, _ = compute_drawdown(prod_filter)
          print(f"  Max drawdown (net):    {max_dd_p:.2f}%")

      # Meta-gated results (if meta-classifier was loaded)
      meta_gated_m = None
      meta_rejected_m = None
      max_dd_meta = 0
      if meta_clf is not None:
          meta_gated = [r for r in oos_results if r.get("meta_pass", False)]
          meta_rejected = [r for r in oos_results
                           if "meta_pass" in r and not r["meta_pass"]]
          meta_gated_m = compute_metrics(meta_gated,
              f"META-GATED (threshold={meta_clf.threshold:.2f})")
          if meta_gated:
              max_dd_meta, _ = compute_drawdown(meta_gated)
              print(f"  Max drawdown (net):    {max_dd_meta:.2f}%")
          meta_rejected_m = compute_metrics(meta_rejected, "META-REJECTED (should be bad)")
          if meta_rejected:
              max_dd_reject, _ = compute_drawdown(meta_rejected)
              print(f"  Max drawdown (net):    {max_dd_reject:.2f}%")

          # Sanity check
          gated_pf = meta_gated_m.get("net_profit_factor", 0) if meta_gated_m else 0
          reject_pf = meta_rejected_m.get("net_profit_factor", 0) if meta_rejected_m else 0
          if reject_pf >= gated_pf and gated_pf > 0:
              print(f"\n  ⚠ META SANITY FAIL: Rejected PF ({reject_pf:.2f}) >= "
                    f"Gated PF ({gated_pf:.2f})")
          elif gated_pf > 0:
              print(f"\n  ✓ META SANITY PASS: Rejected PF ({reject_pf:.2f}) < "
                    f"Gated PF ({gated_pf:.2f})")

      # R7: Position-weighted metrics (Kelly sizing × sector × horizon)
      instrument_sectors = {inst.lower(): sec for inst, sec in INSTRUMENT_SECTORS.items()}
      weighted_all_m = compute_weighted_metrics(
          oos_results, h, instrument_sectors, "R7: ALL OOS POSITION-WEIGHTED")
      weighted_prod_m = {}
      if prod_filter:
          weighted_prod_m = compute_weighted_metrics(
              prod_filter, h, instrument_sectors, "R7: PROD FILTER POSITION-WEIGHTED")

      # Breakdowns
      breakdown(oos_results, "predicted_conf_level", "BY CONFIDENCE LEVEL")
      breakdown(oos_results, "timeframe", "BY TIMEFRAME")
      breakdown(oos_results, "tier", "BY MATCH TIER")

      # By sector
      for r in oos_results:
          inst = r.get("instrument", "").lower()
          r["_sector"] = INSTRUMENT_SECTORS.get(inst, "other")
      breakdown(oos_results, "_sector", "BY SECTOR")

      # By year
      for r in oos_results:
          r["_year"] = r.get("datetime", "?")[:4]
      breakdown(oos_results, "_year", "BY YEAR")

      # By instrument (top 15)
      inst_data = defaultdict(list)
      for r in oos_results:
          inst_data[r["instrument"]].append(r)
      sorted_inst = sorted(inst_data.items(), key=lambda x: -len(x[1]))
      print(f"\n  BY INSTRUMENT (top 15)")
      print(f"  {'-' * 60}")
      print(f"  {'Instrument':<20} {'Count':>6} {'Accuracy':>10} {'WR':>8} {'NetPF':>8}")
      for inst, rs in sorted_inst[:15]:
          if len(rs) < 10:
              continue
          acc = sum(1 for r in rs if r["predicted_direction"] == r["actual_direction"]) / len(rs) * 100
          net_trades = []
          for r in rs:
              if r["predicted_direction"] != "neutral":
                  net_trades.append(r.get("actual_return_sl_net", 0))
          net_gw = sum(t for t in net_trades if t > 0)
          net_gl = abs(sum(t for t in net_trades if t <= 0)) or 0.001
          net_pf = net_gw / net_gl
          wr = len([t for t in net_trades if t > 0]) / len(net_trades) * 100 if net_trades else 0
          print(f"  {inst:<20} {len(rs):>6} {acc:>9.1f}% {wr:>7.1f}% {net_pf:>7.2f}")

      # Edge strength buckets
      for r in oos_results:
          e = abs(r.get("edge", 0))
          if e < 3: r["_edge"] = "edge < 3%"
          elif e < 8.5: r["_edge"] = "edge 3-8.5%"
          elif e < 15: r["_edge"] = "edge 8.5-15%"
          else: r["_edge"] = "edge >=15%"
      breakdown(oos_results, "_edge", "BY EDGE STRENGTH")

      # -------------------------------------------------------
      # IN-SAMPLE vs OOS comparison
      # -------------------------------------------------------
      print(f"\n{'#' * 74}")
      print(f"  IN-SAMPLE vs OUT-OF-SAMPLE COMPARISON")
      print(f"{'#' * 74}")

      # Quick in-sample metrics (sample 2000 from IS)
      random.seed(args.seed)
      is_sample = random.sample(in_sample, min(2000, len(in_sample)))
      sp_is = FastStatPredictor(in_sample, horizon=h, neutral_zone=nz)  # same predictor, same horizon

      is_results = []
      for doc in is_sample:
          doc_patterns = set(p.strip() for p in doc.get("patterns", "").split(",") if p.strip())
          tradeable_patterns = doc_patterns - EXCLUDED_PATTERNS
          actual_dir = doc[f"fwd_{h}_direction"]
          actual_ret = float(doc[f"fwd_{h}_return_pct"])

          if not tradeable_patterns:
              is_results.append({
                  "predicted_direction": "neutral",
                  "actual_direction": actual_dir, "actual_return": actual_ret,
                  "actual_return_sl": actual_ret, "actual_return_sl_net": actual_ret,
                  "sl_triggered": False, "predicted_conf_level": "LOW", "edge": 0,
              })
              continue

          pred = sp_is.predict(doc)
          if pred is None:
              is_results.append({
                  "predicted_direction": "neutral",
                  "actual_direction": actual_dir, "actual_return": actual_ret,
                  "actual_return_sl": actual_ret, "actual_return_sl_net": actual_ret,
                  "sl_triggered": False, "predicted_conf_level": "LOW", "edge": 0,
              })
              continue

          # --- SL sim (R1: MFE-before-MAE, R2: horizon-scaled, R5: trailing) ---
          mae_h = float(doc.get(f"mae_{h}", 0) or 0)
          mfe_h = float(doc.get(f"mfe_{h}", 0) or 0)
          atr_14 = float(doc.get("atr_14", 0) or 0)
          close_price = float(doc.get("close", 1) or 1)

          h_sl_cfg = HORIZON_SL_CONFIG.get(h, HORIZON_SL_CONFIG[5])
          is_structural = bool(doc_patterns & STRUCTURAL_SL_PATTERNS)
          base_sl_mult = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER
          sl_mult_scaled = h_sl_cfg["sl_mult_scale"] * base_sl_mult

          if atr_14 > 0 and close_price > 0:
              sl_pct = sl_mult_scaled * atr_14 / close_price * 100
          else:
              sl_pct = 1.0
          sl_pct = max(SL_FLOOR_PCT, min(h_sl_cfg["sl_cap"], sl_pct))

          pred_avg_ret = abs(pred.get("avg_return", 0) or 0)
          target_pct = max(sl_pct * h_sl_cfg["rr_min"], pred_avg_ret)

          pred_dir = pred["predicted_direction"]
          sl_triggered = False
          actual_ret_sl = actual_ret

          if pred_dir == "bullish":
              if mfe_h >= target_pct:
                  actual_ret_sl = target_pct
              elif mfe_h >= target_pct * 0.5 and mae_h >= -sl_pct:
                  actual_ret_sl = max(0.0, actual_ret)
              elif mae_h < -sl_pct:
                  sl_triggered = True
                  actual_ret_sl = -sl_pct
          elif pred_dir == "bearish":
              if (-mae_h) >= target_pct:
                  actual_ret_sl = target_pct
              elif (-mae_h) >= target_pct * 0.5 and mfe_h <= sl_pct:
                  actual_ret_sl = max(0.0, -actual_ret)
              elif mfe_h > sl_pct:
                  sl_triggered = True
                  actual_ret_sl = -sl_pct
              else:
                  actual_ret_sl = -actual_ret

          actual_ret_sl_net = actual_ret_sl - SLIPPAGE_COMMISSION_PCT

          is_results.append({
              "predicted_direction": pred_dir,
              "predicted_conf_level": pred["confidence_level"],
              "predicted_wr": pred.get("win_rate", 50),
              "edge": pred["edge"],
              "actual_direction": actual_dir,
              "actual_return": actual_ret,
              "actual_return_sl": round(actual_ret_sl, 4),
              "actual_return_sl_net": round(actual_ret_sl_net, 4),
              "sl_triggered": sl_triggered,
              "sl_pct": round(sl_pct, 4),
          })

      is_m = compute_metrics(is_results, f"IN-SAMPLE (2016-{args.split_year - 1}, 2000 sampled)")

      # Production filter on IS (aligned with paper_trader)
      is_prod = [
          r for r in is_results
          if conf_rank.get(r.get("predicted_conf_level", "LOW"), 0) >= min_conf_rank
          and abs(r.get("edge", 0)) >= pf_min_edge
          and r.get("predicted_wr", 0) >= pf_min_wr
      ]
      compute_metrics(is_prod,
          f"IN-SAMPLE PROD FILTER (conf>={pf_min_conf}, WR>={pf_min_wr}, edge>={pf_min_edge}%)")

      # -------------------------------------------------------
      # SUMMARY TABLE
      # -------------------------------------------------------
      print(f"\n{'#' * 74}")
      print(f"  VERDICT SUMMARY")
      print(f"{'#' * 74}")

      oos_net_pf = oos_m.get("net_profit_factor", oos_m.get("profit_factor", 0))
      prod_net_pf = prod_m.get("net_profit_factor", prod_m.get("profit_factor", 0)) if prod_m else 0
      is_net_pf = is_m.get("net_profit_factor", is_m.get("profit_factor", 0))
      meta_net_pf = (meta_gated_m.get("net_profit_factor", meta_gated_m.get("profit_factor", 0))
                     if meta_gated_m else 0)

      if meta_clf is not None:
          print(f"\n  {'Metric':<25} {'In-Sample':>12} {'OOS (all)':>12} {'OOS (prod)':>12} {'OOS (meta)':>12}")
          print(f"  {'-' * 78}")
          print(f"  {'Net PF':<25} {is_net_pf:>12.2f} {oos_net_pf:>12.2f} {prod_net_pf:>12.2f} {meta_net_pf:>12.2f}")
          print(f"  {'Win Rate (net)':<25} "
                f"{is_m.get('net_win_rate', is_m.get('win_rate', 0)):>11.1f}% "
                f"{oos_m.get('net_win_rate', oos_m.get('win_rate', 0)):>11.1f}% "
                f"{prod_m.get('net_win_rate', prod_m.get('win_rate', 0)):>11.1f}% "
                f"{meta_gated_m.get('net_win_rate', meta_gated_m.get('win_rate', 0)):>11.1f}%")
          print(f"  {'Avg Ret/Trade (net)':<25} "
                f"{is_m.get('net_avg_return', is_m.get('avg_return', 0)):>+11.4f}% "
                f"{oos_m.get('net_avg_return', oos_m.get('avg_return', 0)):>+11.4f}% "
                f"{prod_m.get('net_avg_return', prod_m.get('avg_return', 0)):>+11.4f}% "
                f"{meta_gated_m.get('net_avg_return', meta_gated_m.get('avg_return', 0)):>+11.4f}%")
          print(f"  {'Max DD':<25} {'—':>12} {max_dd:>11.2f}% "
                f"{max_dd_p:>11.2f}%" if prod_filter else "",
                f" {max_dd_meta:>11.2f}%" if meta_clf else "")
          print(f"  {'N trades':<25} "
                f"{is_m.get('n_trades', 0):>12} "
                f"{oos_m.get('n_trades', 0):>12} "
                f"{prod_m.get('n_trades', 0):>12} "
                f"{meta_gated_m.get('n_trades', 0):>12}")
      else:
          print(f"\n  {'Metric':<30} {'In-Sample':>12} {'OOS (all)':>12} {'OOS (prod)':>12}")
          print(f"  {'-' * 66}")
          print(f"  {'Net PF':<30} {is_net_pf:>12.2f} {oos_net_pf:>12.2f} {prod_net_pf:>12.2f}")
          print(f"  {'Win Rate (net)':<30} "
                f"{is_m.get('net_win_rate', is_m.get('win_rate', 0)):>11.1f}% "
                f"{oos_m.get('net_win_rate', oos_m.get('win_rate', 0)):>11.1f}% "
                f"{prod_m.get('net_win_rate', prod_m.get('win_rate', 0)):>11.1f}%")
          print(f"  {'Avg Ret/Trade (net)':<30} "
                f"{is_m.get('net_avg_return', is_m.get('avg_return', 0)):>+11.4f}% "
                f"{oos_m.get('net_avg_return', oos_m.get('avg_return', 0)):>+11.4f}% "
                f"{prod_m.get('net_avg_return', prod_m.get('avg_return', 0)):>+11.4f}%")
          print(f"  {'Max DD':<30} {'—':>12} {max_dd:>11.2f}% "
                f"{max_dd_p:>11.2f}%" if prod_filter else "")
          print(f"  {'N trades':<30} "
                f"{is_m.get('n_trades', 0):>12} "
                f"{oos_m.get('n_trades', 0):>12} "
                f"{prod_m.get('n_trades', 0):>12}")

      pf_drift = abs(is_net_pf - oos_net_pf)
      print(f"\n  PF drift (IS vs OOS):  {pf_drift:.2f}")
      if pf_drift < 0.15:
          print(f"  Assessment: STABLE — minimal overfitting ✓")
      elif pf_drift < 0.30:
          print(f"  Assessment: MODERATE DRIFT — some overfitting likely")
      else:
          print(f"  Assessment: HIGH DRIFT — significant overfitting detected ✗")

      if oos_net_pf > 1.0:
          print(f"\n  ★ OOS EDGE CONFIRMED — PF {oos_net_pf:.2f} after costs ★")
      else:
          print(f"\n  ✗ OOS EDGE NOT CONFIRMED — PF {oos_net_pf:.2f} after costs")

      # Save OOS results
      if len(horizons_to_test) > 1:
          out_path = f"backtest_walkforward_h{h}_results.json"
      else:
          out_path = "backtest_walkforward_results.json"
      # Clean temp fields
      for r in oos_results:
          r.pop("_year", None)
          r.pop("_edge", None)
          r.pop("_sector", None)
      save_data = {
              "config": {
                  "horizon_days": h,
                  "split_year": args.split_year,
                  "is_docs": len(in_sample),
                  "oos_docs": len(out_of_sample),
                  "slippage_commission_pct": SLIPPAGE_COMMISSION_PCT,
                  "excluded_patterns": list(EXCLUDED_PATTERNS),
                  "whitelisted_patterns": list(WHITELISTED_PATTERNS),
                  "allowed_timeframes": list(ALLOWED_TIMEFRAMES),
                  "allowed_instruments_count": len(ALLOWED_INSTRUMENTS),
                  "allowed_tiers": list(ALLOWED_TIERS),
                  "min_matches": MIN_MATCHES,
                  "meta_gate": args.meta_gate,
              },
              "metrics_all_oos": oos_m,
              "metrics_prod_filter": prod_m,
              "metrics_in_sample": is_m,
              "pf_drift": pf_drift,
              "max_drawdown_all": max_dd,
              "results": oos_results,
          }
      if meta_gated_m is not None:
          save_data["metrics_meta_gated"] = meta_gated_m
          save_data["metrics_meta_rejected"] = meta_rejected_m
          save_data["meta_threshold"] = meta_clf.threshold if meta_clf else None
          save_data["max_drawdown_meta"] = max_dd_meta
      if weighted_all_m:
          save_data["metrics_weighted_all"] = weighted_all_m
      if weighted_prod_m:
          save_data["metrics_weighted_prod"] = weighted_prod_m

      with open(out_path, "w") as f:
          json.dump(save_data, f, indent=2)
      print(f"\n  Results saved to {out_path}")
      print(f"\nDone.")


if __name__ == "__main__":
    main()
