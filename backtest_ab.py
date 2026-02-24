"""
A/B Backtest: RAG (embedding) vs Statistical (metadata) Predictor
==================================================================
Tests both prediction engines on the SAME sample of documents and
produces a side-by-side comparison.

The statistical predictor excludes the test document's own instrument
to prevent look-ahead / self-match bias.

Usage:
    python backtest_ab.py                   # 2000 samples
    python backtest_ab.py --samples 5000    # larger
    python backtest_ab.py --stat-only       # skip slow RAG engine
"""

import json, time, random, argparse, sys
from collections import defaultdict
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
    is_tradeable_instrument, is_tradeable_timeframe, is_tradeable_pattern,
    is_tradeable_tier,
)


from fast_stat_predictor import FastStatPredictor


# ============================================================
# METRICS
# ============================================================

def compute_metrics(results, label=""):
    """Compute and print metrics for a set of results."""
    n = len(results)
    if n == 0:
        print(f"  {label}: No results")
        return {}

    correct = sum(1 for r in results if r["predicted_direction"] == r["actual_direction"])
    accuracy = correct / n * 100

    # Exclude neutrals for binary
    binary = [r for r in results if r["predicted_direction"] != "neutral"]
    b_correct = sum(1 for r in binary if r["predicted_direction"] == r["actual_direction"])
    b_accuracy = b_correct / len(binary) * 100 if binary else 0

    # Trade performance
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

    # Confusion (bullish signal)
    tp = sum(1 for r in results if r["predicted_direction"] == "bullish" and r["actual_direction"] == "bullish")
    fp = sum(1 for r in results if r["predicted_direction"] == "bullish" and r["actual_direction"] != "bullish")
    fn = sum(1 for r in results if r["predicted_direction"] != "bullish" and r["actual_direction"] == "bullish")
    precision = tp / (tp + fp) * 100 if (tp + fp) else 0
    recall = tp / (tp + fn) * 100 if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    metrics = {
        "n": n, "accuracy": accuracy, "binary_accuracy": b_accuracy,
        "n_trades": len(trades), "win_rate": win_rate,
        "profit_factor": pf, "total_return": total_ret,
        "avg_return": avg_ret, "sharpe": sharpe,
        "precision": precision, "recall": recall, "f1": f1,
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
    print(f"  Precision/Recall/F1:   {precision:.1f}% / {recall:.1f}% / {f1:.1f}%")

    # Stop-loss adjusted metrics (if SL data available)
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
            print(f"  Sharpe (SL):           {sl_sharpe:+.4f}  (was {sharpe:+.4f})")

            metrics["sl_win_rate"] = sl_wr
            metrics["sl_profit_factor"] = sl_pf
            metrics["sl_total_return"] = sl_total
            metrics["sl_avg_return"] = sl_avg
            metrics["sl_sharpe"] = sl_sharpe
            metrics["sl_triggers"] = n_triggered

    # Cost-adjusted metrics (SL + slippage + commissions)
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
            metrics["net_cost_drag"] = total_cost
            metrics["edge_survives_costs"] = edge_survives

    # Neutral count
    neutrals = sum(1 for r in results if r["predicted_direction"] == "neutral")
    print(f"  Neutral (no trade):    {neutrals} ({neutrals/n*100:.1f}%)")

    return metrics


def breakdown(results, field, label):
    """Print accuracy breakdown by a field."""
    buckets = defaultdict(list)
    for r in results:
        buckets[r.get(field, "?")].append(r)

    print(f"\n  {label}")
    print(f"  {'-' * 60}")
    print(f"  {'Value':<20} {'Count':>6} {'Accuracy':>10} {'Win Rate':>10} {'PF':>8} {'Avg Ret':>10}")

    for val in sorted(buckets.keys(), key=lambda x: -len(buckets[x])):
        b = buckets[val]
        if len(b) < 5:
            continue
        acc = sum(1 for r in b if r["predicted_direction"] == r["actual_direction"]) / len(b) * 100
        trades = []
        for r in b:
            if r["predicted_direction"] == "bullish":
                trades.append(r["actual_return"])
            elif r["predicted_direction"] == "bearish":
                trades.append(-r["actual_return"])
        wins = [t for t in trades if t > 0]
        wr = len(wins) / len(trades) * 100 if trades else 0
        gw = sum(wins) if wins else 0
        gl = abs(sum(t for t in trades if t <= 0)) or 0.001
        pf = gw / gl
        ar = float(np.mean(trades)) if trades else 0
        print(f"  {str(val):<20} {len(b):>6} {acc:>9.1f}% {wr:>9.1f}% {pf:>7.2f} {ar:>+9.4f}%")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stat-only", action="store_true",
                        help="Skip the slow RAG engine, only test statistical predictor")
    args = parser.parse_args()

    print("=" * 74)
    print("  A/B BACKTEST: Statistical Predictor")
    print("=" * 74)

    # Load docs
    print("\n  Loading documents...")
    with open(RAG_DOCS_PATH) as f:
        all_docs = json.load(f)

    # Filter eligible — apply production filters
    eligible = [d for d in all_docs
                if d.get(f"fwd_{PRIMARY_HORIZON}_return_pct") is not None
                and d.get(f"fwd_{PRIMARY_HORIZON}_direction") is not None
                and d.get("instrument") not in EXCLUDED_INSTRUMENTS
                and is_tradeable_instrument(d.get("instrument", ""))
                and is_tradeable_timeframe(d.get("timeframe", ""))]

    print(f"  Eligible (non-VIX, with outcomes): {len(eligible)}")

    # Sample
    random.seed(args.seed)
    if args.samples >= len(eligible):
        sample = eligible
    else:
        sample = random.sample(eligible, args.samples)
    print(f"  Sample size: {len(sample)}")

    # -------------------------------------------------------
    # STATISTICAL PREDICTOR
    # -------------------------------------------------------
    print("\n  Initializing statistical predictor...")
    sp = FastStatPredictor(all_docs)

    stat_results = []
    t0 = time.time()

    for idx, doc in enumerate(sample):
        # Check if all patterns are excluded (PF < 0.5)
        doc_patterns = set(p.strip() for p in doc.get("patterns", "").split(",") if p.strip())
        tradeable_patterns = doc_patterns - EXCLUDED_PATTERNS
        if not tradeable_patterns:
            # All patterns are excluded — treat as neutral (no trade)
            actual_dir = doc[f"fwd_{PRIMARY_HORIZON}_direction"]
            actual_ret = float(doc[f"fwd_{PRIMARY_HORIZON}_return_pct"])
            stat_results.append({
                "doc_id": doc["id"],
                "instrument": doc.get("instrument", "?"),
                "timeframe": doc.get("timeframe", "?"),
                "patterns": doc.get("patterns", "?"),
                "pattern_confidence": float(doc.get("pattern_confidence", 0)),
                "volume_confirmed": doc.get("volume_confirmed", False),
                "price_vs_vwap": str(doc.get("price_vs_vwap", "?")),
                "predicted_direction": "neutral",
                "predicted_confidence": 0,
                "predicted_conf_level": "LOW",
                "edge": 0,
                "tier": "none",
                "actual_direction": actual_dir,
                "actual_return": actual_ret,
                "actual_return_sl": actual_ret,
                "actual_return_sl_net": actual_ret,  # no cost for neutral
                "sl_triggered": False,
                "sl_pct": 0,
                "mae_5": float(doc.get("mae_5", 0) or 0),
                "mfe_5": float(doc.get("mfe_5", 0) or 0),
            })
            continue

        pred = sp.predict(doc, exclude_id=doc["id"])

        actual_dir = doc[f"fwd_{PRIMARY_HORIZON}_direction"]
        actual_ret = float(doc[f"fwd_{PRIMARY_HORIZON}_return_pct"])

        if pred is None:
            # No prediction = neutral
            stat_results.append({
                "doc_id": doc["id"],
                "instrument": doc.get("instrument", "?"),
                "timeframe": doc.get("timeframe", "?"),
                "patterns": doc.get("patterns", "?"),
                "pattern_confidence": float(doc.get("pattern_confidence", 0)),
                "volume_confirmed": doc.get("volume_confirmed", False),
                "price_vs_vwap": str(doc.get("price_vs_vwap", "?")),
                "predicted_direction": "neutral",
                "predicted_confidence": 0,
                "predicted_conf_level": "LOW",
                "edge": 0,
                "tier": "none",
                "actual_direction": actual_dir,
                "actual_return": actual_ret,
                "actual_return_sl": actual_ret,
                "actual_return_sl_net": actual_ret,  # no cost for neutral
                "sl_triggered": False,
                "sl_pct": 0,
                "mae_5": float(doc.get("mae_5", 0) or 0),
                "mfe_5": float(doc.get("mfe_5", 0) or 0),
            })
            continue

        # --- Stop-loss simulation (tiered) ---
        mae_5 = float(doc.get("mae_5", 0) or 0)
        mfe_5 = float(doc.get("mfe_5", 0) or 0)
        atr_14 = float(doc.get("atr_14", 0) or 0)
        close_price = float(doc.get("close", 1) or 1)

        # Determine SL multiplier: structural (2.0x) for Tier A patterns, standard (1.5x) otherwise
        doc_patterns = set(doc.get("patterns", "").split(","))
        is_structural = bool(doc_patterns & STRUCTURAL_SL_PATTERNS)
        sl_multiplier = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER

        # Compute ATR-based stop-loss %
        if atr_14 > 0 and close_price > 0:
            sl_pct = sl_multiplier * atr_14 / close_price * 100
        else:
            sl_pct = 1.0  # fallback
        sl_pct = max(SL_FLOOR_PCT, min(SL_CAP_PCT, sl_pct))

        # Check if SL would have been triggered
        pred_dir = pred["predicted_direction"]
        sl_triggered = False
        actual_ret_sl = actual_ret  # default: raw return

        if pred_dir == "bullish":
            # LONG trade: adverse = price drops, mae_5 is negative
            if mae_5 < -sl_pct:
                sl_triggered = True
                actual_ret_sl = -sl_pct  # loss capped at SL
            else:
                actual_ret_sl = actual_ret
        elif pred_dir == "bearish":
            # SHORT trade: adverse = price rises, mfe_5 is positive
            if mfe_5 > sl_pct:
                sl_triggered = True
                actual_ret_sl = -sl_pct  # loss capped at SL
            else:
                actual_ret_sl = -actual_ret  # SHORT profit

        # Net returns after slippage + commissions
        actual_ret_sl_net = actual_ret_sl - SLIPPAGE_COMMISSION_PCT  # cost deducted from trade PnL

        stat_results.append({
            "doc_id": doc["id"],
            "instrument": doc.get("instrument", "?"),
            "timeframe": doc.get("timeframe", "?"),
            "patterns": doc.get("patterns", "?"),
            "pattern_confidence": float(doc.get("pattern_confidence", 0)),
            "volume_confirmed": doc.get("volume_confirmed", False),
            "price_vs_vwap": str(doc.get("price_vs_vwap", "?")),
            "predicted_direction": pred_dir,
            "predicted_confidence": pred["confidence_score"],
            "predicted_conf_level": pred["confidence_level"],
            "edge": pred["edge"],
            "tier": pred["tier"],
            "n_matches": pred.get("n_matches", 0),
            "n_instruments": pred.get("n_instruments", 0),
            "predicted_pf": pred.get("profit_factor", 0),
            "actual_direction": actual_dir,
            "actual_return": actual_ret,
            "actual_return_sl": round(actual_ret_sl, 4),
            "actual_return_sl_net": round(actual_ret_sl_net, 4),
            "sl_triggered": sl_triggered,
            "sl_pct": round(sl_pct, 4),
            "mae_5": round(mae_5, 4),
            "mfe_5": round(mfe_5, 4),
        })

        if (idx + 1) % 500 == 0:
            elapsed = time.time() - t0
            print(f"    [{idx+1}/{len(sample)}] {(idx+1)/len(sample)*100:.0f}%  "
                  f"({(idx+1)/elapsed:.0f} queries/s)", flush=True)

    t_stat = time.time() - t0
    print(f"  Statistical predictor: {len(stat_results)} results in {t_stat:.1f}s "
          f"({len(stat_results)/t_stat:.0f} queries/s)")

    # -------------------------------------------------------
    # COMPUTE METRICS — STATISTICAL
    # -------------------------------------------------------
    sm = compute_metrics(stat_results, "STATISTICAL PREDICTOR (all)")

    # Breakdowns
    breakdown(stat_results, "predicted_conf_level", "BY CONFIDENCE LEVEL")
    breakdown(stat_results, "timeframe", "BY TIMEFRAME")
    breakdown(stat_results, "price_vs_vwap", "BY PRICE vs VWAP")
    breakdown(stat_results, "tier", "BY MATCH TIER")

    # Volume confirmed
    breakdown(stat_results, "volume_confirmed", "BY VOLUME CONFIRMED")

    # Pattern confidence buckets
    for r in stat_results:
        pc = r.get("pattern_confidence", 0)
        if pc < 0.3:
            r["_pc_bucket"] = "0.0-0.3"
        elif pc < 0.5:
            r["_pc_bucket"] = "0.3-0.5"
        elif pc < 0.7:
            r["_pc_bucket"] = "0.5-0.7"
        else:
            r["_pc_bucket"] = "0.7-1.0"
    breakdown(stat_results, "_pc_bucket", "BY PATTERN CONFIDENCE")

    # Edge strength buckets
    for r in stat_results:
        e = abs(r.get("edge", 0))
        if e < 3:
            r["_edge_bucket"] = "edge < 3%"
        elif e < 8:
            r["_edge_bucket"] = "edge 3-8%"
        elif e < 15:
            r["_edge_bucket"] = "edge 8-15%"
        else:
            r["_edge_bucket"] = "edge >15%"
    breakdown(stat_results, "_edge_bucket", "BY EDGE STRENGTH (base-rate corrected)")

    # Excluding extremes
    normal = [r for r in stat_results if abs(r["actual_return"]) <= 10]
    compute_metrics(normal, "STATISTICAL (excl. |ret| > 10%)")

    # HIGH confidence only
    high_conf = [r for r in stat_results if r["predicted_conf_level"] == "HIGH"]
    compute_metrics(high_conf, "STATISTICAL (HIGH confidence only)")

    # HIGH conf + strong edge (>8%)
    strong = [r for r in stat_results
              if r["predicted_conf_level"] == "HIGH" and abs(r.get("edge", 0)) >= 8]
    compute_metrics(strong, "STATISTICAL (HIGH conf + edge >= 8%)")

    # VWAP above + tier 1
    vwap_t1 = [r for r in stat_results
               if r.get("price_vs_vwap") == "above" and r.get("tier") == "tier_1"]
    compute_metrics(vwap_t1, "STATISTICAL (VWAP above + tier 1)")

    # top patterns
    print(f"\n  TOP PATTERN ACCURACY")
    pattern_data = defaultdict(list)
    for r in stat_results:
        for p in r["patterns"].split(","):
            p = p.strip()
            if p:
                pattern_data[p].append(r)
    sorted_p = sorted(pattern_data.items(), key=lambda x: -len(x[1]))
    print(f"  {'Pattern':<30} {'Count':>6} {'Accuracy':>10} {'Win Rate':>10} {'PF':>8}")
    for pat, rs in sorted_p[:20]:
        if len(rs) < 5:
            continue
        acc = sum(1 for r in rs if r["predicted_direction"] == r["actual_direction"]) / len(rs) * 100
        trades = []
        for r in rs:
            if r["predicted_direction"] == "bullish":
                trades.append(r["actual_return"])
            elif r["predicted_direction"] == "bearish":
                trades.append(-r["actual_return"])
        wins = [t for t in trades if t > 0]
        wr = len(wins) / len(trades) * 100 if trades else 0
        gw = sum(wins) if wins else 0
        gl = abs(sum(t for t in trades if t <= 0)) or 0.001
        pf = gw / gl
        print(f"  {pat:<30} {len(rs):>6} {acc:>9.1f}% {wr:>9.1f}% {pf:>7.2f}")

    # Save
    out_path = "backtest_stat_results.json"
    # Remove temp fields before saving
    for r in stat_results:
        r.pop("_pc_bucket", None)
        r.pop("_edge_bucket", None)
    with open(out_path, "w") as f:
        json.dump(stat_results, f, indent=2)
    print(f"\n  Results saved to {out_path}")

    # -------------------------------------------------------
    # COMPARISON WITH OLD RAG (if exists)
    # -------------------------------------------------------
    old_path = "backtest_results.json"
    try:
        with open(old_path) as f:
            old_results = json.load(f)
        print(f"\n\n{'#' * 74}")
        print(f"  COMPARISON: OLD RAG vs NEW STATISTICAL")
        print(f"{'#' * 74}")
        compute_metrics(old_results, "OLD RAG PREDICTOR (previous run)")
        print(f"\n  (New statistical results shown above)")
    except FileNotFoundError:
        pass

    print(f"\nDone.")


if __name__ == "__main__":
    main()
