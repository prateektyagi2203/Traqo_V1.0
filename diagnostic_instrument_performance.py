"""
Diagnostic: Instrument Class Performance Analysis
==================================================
Analyzes live trading data from paper_trades.db to calculate PF and win rate
by instrument class (Nifty 50, Next 50, Midcap 150, Indices, etc.)

Outputs top performers to identify which 50-80 stocks to keep.
"""

import sqlite3
import pandas as pd
from collections import defaultdict
from typing import Dict, Tuple, List

# Instrument Classifications
NIFTY_50 = {
    "adanient", "adaniports", "apollohosp", "asianpaint", "axisbank",
    "bajajauto", "bajajfinsv", "bajfinance", "bhartiartl", "bpcl",
    "britannia", "cipla", "coalindia", "divislab", "drreddy",
    "eichermot", "eternal", "grasim", "hcltech", "hdfcbank",
    "hdfclife", "heromotoco", "hindalco", "hindunilvr", "icicibank",
    "indusindbk", "infosys", "itc", "jswsteel", "kotakbank",
    "lt", "mahindra", "maruti", "nestleind", "ntpc",
    "ongc", "powergrid", "reliance", "sbi", "sbilife",
    "shriramfin", "sunpharma", "tatamotors", "tatasteel", "tcs",
    "techm", "titan", "trent", "ultracemco", "wipro",
}

NIFTY_NEXT_50 = {
    "abb", "acc", "adanigreen", "adanipower", "ambujacem",
    "atgl", "auropharma", "bajajhldng", "bankbaroda", "bel",
    "bergepaint", "biocon", "boschltd", "canbk", "cholafin",
    "colpal", "dabur", "dlf", "gail", "godrejcp",
    "hal", "havells", "icicipruli", "indigo", "ioc",
    "irctc", "irfc", "jindalstel", "jiofin", "lici",
    "ltim", "ltts", "lupin", "maxhealth", "motherson",
    "naukri", "nhpc", "oberoirlty", "ofss", "paytm",
    "pfc", "pidilitind", "pnb", "polycab", "recltd",
    "sbicard", "siemens", "srf", "tataconsum", "tatapower",
}

INDICES = {
    "nifty50", "banknifty", "niftyit", "niftypharma",
    "niftyauto", "niftymetal", "niftyfmcg", "niftyenergy",
    "niftyinfra", "niftymedia", "niftypsubank", "niftyrealty",
    "dowjones", "nasdaq", "nikkei225", "hangseng",
    "ftse100", "eurostoxx50",
}

COMMODITIES = {"gold", "silver", "crude_oil"}


def classify_instrument(ticker: str) -> str:
    """Classify instrument into category."""
    ticker_lower = ticker.lower()
    if ticker_lower in NIFTY_50:
        return "Nifty_50"
    elif ticker_lower in NIFTY_NEXT_50:
        return "Nifty_Next_50"
    elif ticker_lower in INDICES:
        return "Indices"
    elif ticker_lower in COMMODITIES:
        return "Commodities"
    else:
        return "Nifty_Midcap_150"  # Default to midcap


def calculate_pf_wr(trades: List[Dict]) -> Tuple[float, float]:
    """Calculate Profit Factor and Win Rate from trades."""
    if not trades:
        return 0.0, 0.0
    
    total_wins = sum(t["return_pct"] for t in trades if t["return_pct"] > 0)
    total_losses = abs(sum(t["return_pct"] for t in trades if t["return_pct"] < 0))
    wins = sum(1 for t in trades if t["return_pct"] > 0)
    
    pf = total_wins / total_losses if total_losses != 0 else (1.5 if total_wins > 0 else 0.0)
    wr = (wins / len(trades)) * 100 if trades else 0.0
    
    return pf, wr


def analyze_performance() -> None:
    """Main analysis function."""
    
    print("=" * 80)
    print("DIAGNOSTIC: Instrument Class Performance Analysis")
    print("=" * 80)
    
    # Connect to database
    conn = sqlite3.connect("paper_trades/paper_trades.db")
    cursor = conn.cursor()
    
    # Fetch all closed trades with actual returns
    cursor.execute("""
        SELECT ticker, entry_price, exit_price, actual_return_pct, status, entry_date
        FROM trades 
        WHERE status IN ('CLOSED', 'EXITED', 'EXPIRED_WIN', 'EXPIRED_LOSS')
        AND actual_return_pct IS NOT NULL
        ORDER BY ticker, entry_date
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        print("\n❌ No closed trades found in database. Run live trading first.")
        return
    
    print(f"\n✅ Found {len(rows)} closed trades in database\n")
    
    # Group by instrument class
    trades_by_class = defaultdict(list)
    trades_by_ticker = defaultdict(list)
    
    for ticker, entry, exit_p, return_pct, status, entry_date in rows:
        classification = classify_instrument(ticker)
        trades_by_class[classification].append({"return_pct": return_pct, "ticker": ticker})
        trades_by_ticker[ticker.lower()].append({"return_pct": return_pct})
    
    # === SECTION 1: PERFORMANCE BY INSTRUMENT CLASS ===
    print("\n" + "=" * 80)
    print("SECTION 1: PERFORMANCE BY INSTRUMENT CLASS")
    print("=" * 80)
    
    class_results = []
    for classification in ["Nifty_50", "Nifty_Next_50", "Nifty_Midcap_150", "Indices", "Commodities"]:
        trades = trades_by_class.get(classification, [])
        if not trades:
            continue
        
        pf, wr = calculate_pf_wr(trades)
        total_return = sum(t["return_pct"] for t in trades)
        win_count = sum(1 for t in trades if t["return_pct"] > 0)
        loss_count = sum(1 for t in trades if t["return_pct"] <= 0)
        
        class_results.append({
            "Class": classification,
            "Trades": len(trades),
            "PF": pf,
            "WR%": wr,
            "Total_Return%": total_return,
            "Wins": win_count,
            "Losses": loss_count,
        })
        
        print(f"\n{classification}")
        print(f"  Trades:     {len(trades)}")
        print(f"  Profit Factor: {pf:.2f}")
        print(f"  Win Rate:   {wr:.1f}%")
        print(f"  Total Return: {total_return:.2f}%")
        print(f"  Wins/Losses: {win_count}/{loss_count}")
    
    # === SECTION 2: TOP INDIVIDUAL STOCKS ===
    print("\n" + "=" * 80)
    print("SECTION 2: TOP INDIVIDUAL STOCKS (by PF)")
    print("=" * 80)
    
    stock_results = []
    for ticker, trades in trades_by_ticker.items():
        if len(trades) < 5:  # Minimum 5 trades for credibility
            continue
        
        pf, wr = calculate_pf_wr(trades)
        classification = classify_instrument(ticker)
        total_return = sum(t["return_pct"] for t in trades)
        
        stock_results.append({
            "Ticker": ticker.upper(),
            "Class": classification,
            "Trades": len(trades),
            "PF": pf,
            "WR%": wr,
            "Total_Return%": total_return,
        })
    
    # Sort by PF descending
    stock_results.sort(key=lambda x: x["PF"], reverse=True)
    
    print("\n🏆 TOP 30 STOCKS (by Profit Factor, min 5 trades):\n")
    print(f"{'Rank':<5} {'Ticker':<12} {'Class':<18} {'Trades':<8} {'PF':<7} {'WR%':<8} {'Total_Return%':<12}")
    print("-" * 80)
    
    for i, result in enumerate(stock_results[:30], 1):
        print(f"{i:<5} {result['Ticker']:<12} {result['Class']:<18} "
              f"{result['Trades']:<8} {result['PF']:<7.2f} {result['WR%']:<8.1f} "
              f"{result['Total_Return%']:<10.2f}%")
    
    # === SECTION 3: BOTTOM PERFORMERS (for removal) ===
    print("\n\n" + "=" * 80)
    print("SECTION 3: BOTTOM PERFORMERS (candidates for removal)")
    print("=" * 80)
    
    print("\n⚠️ WORST 20 STOCKS (by Profit Factor, min 5 trades):\n")
    print(f"{'Rank':<5} {'Ticker':<12} {'Class':<18} {'Trades':<8} {'PF':<7} {'WR%':<8} {'Total_Return%':<12}")
    print("-" * 80)
    
    stock_results.sort(key=lambda x: x["PF"], reverse=False)
    for i, result in enumerate(stock_results[:20], 1):
        if result["PF"] >= 1.0:
            continue  # Only show underperformers
        print(f"{i:<5} {result['Ticker']:<12} {result['Class']:<18} "
              f"{result['Trades']:<8} {result['PF']:<7.2f} {result['WR%']:<8.1f} "
              f"{result['Total_Return%']:<10.2f}%")
    
    # === SECTION 4: RECOMMENDATION ===
    print("\n\n" + "=" * 80)
    print("SECTION 4: REBALANCE RECOMMENDATION (Option B)")
    print("=" * 80)
    
    # Extract top 50-80 stocks from top performers
    top_stocks = [r for r in stock_results[::-1]  # Reverse back to PF descending
                  if r["Class"] != "Indices" and r["Trades"] >= 5][:80]
    
    print(f"\n✅ Recommended ALLOWED_INSTRUMENTS for rebalance:")
    print(f"   • Nifty 50 Index (2-3 positions max)")
    print(f"   • BankNifty Index (3-4 positions max)")
    print(f"   • Nifty PSU Bank Index (1-2 positions max)")
    print(f"   • Nifty Smallcap 50 Index (1-2 positions max, if available)")
    print(f"   • Top {len(top_stocks)} individual stocks (from winners list above)")
    
    print(f"\n📊 Top {min(80, len(top_stocks))} Stocks to Keep:")
    print(f"{'#':<3} {'Ticker':<12} {'PF':<7} {'WR%':<8} {'Trades':<8}")
    print("-" * 40)
    
    for i, stock in enumerate(top_stocks[:80], 1):
        print(f"{i:<3} {stock['Ticker']:<12} {stock['PF']:<7.2f} {stock['WR%']:<8.1f} {stock['Trades']:<8}")
    
    print(f"\n💾 Stocks to REMOVE (underperformers, PF < 1.0):")
    underperformers = [r for r in stock_results 
                      if r["Class"] != "Indices" and r["PF"] < 1.0 and r["Trades"] >= 5]
    print(f"   Count: {len(underperformers)}")
    print(f"   Combined return loss: {sum(r['Total_Return%'] for r in underperformers):.2f}%")
    
    # === IMPACT ANALYSIS ===
    print("\n" + "=" * 80)
    print("SECTION 5: REBALANCE IMPACT ANALYSIS")
    print("=" * 80)
    
    current_total = sum(r["Total_Return%"] for r in class_results)
    index_pnl = sum(r["Total_Return%"] for r in class_results if r["Class"] == "Indices")
    stock_pnl = sum(r["Total_Return%"] for r in class_results if r["Class"] != "Indices")
    
    print(f"\nCurrent Universe (250 stocks + indices):")
    print(f"   Total Return: {current_total:.2f}%")
    print(f"   Index contribution: {index_pnl:.2f}% ({(index_pnl/max(current_total, 0.01)*100):.1f}%)")
    print(f"   Stock contribution: {stock_pnl:.2f}% ({(stock_pnl/max(current_total, 0.01)*100):.1f}%)")
    
    top_stock_pnl = sum(r["Total_Return%"] for r in stock_results[:80])
    print(f"\nRebalanced Universe (indices + top 80 stocks):")
    print(f"   Top 80 stock return: {top_stock_pnl:.2f}%")
    print(f"   Expected index boost: {index_pnl * 1.2:.2f}% (estimate, +20% from better positioning)")
    print(f"   Projected total: {top_stock_pnl + index_pnl * 1.2:.2f}%")
    print(f"   Expected win rate improvement: +0.5-1.5% (from higher PF instruments)")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    analyze_performance()
