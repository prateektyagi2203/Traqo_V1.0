"""
Book Knowledge Extractor
========================
Extracts text from all 15 selected trading/candlestick books,
filters for candlestick-relevant chapters, and saves structured
extracted knowledge for knowledge base enrichment.
"""

import os
import json
import re
import fitz  # PyMuPDF

BOOKS_DIR = r"C:\Users\tyagipra\Downloads\some-investment-books-master"
OUTPUT_DIR = "book_extracts"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── ALL 15 BOOKS: CRITICAL + HIGH VALUE + NICE TO HAVE ──
BOOKS = {
    # ── TIER 1: CRITICAL — Core Candlestick Knowledge ──
    "nison_jcct": {
        "file": "Japanese Candlestick Charting Techniques 2nd edition 2001.pdf",
        "tier": "critical",
        "focus": "candlestick_patterns",
        "description": "Nison's canonical candlestick reference — pattern rules, confirmation, context",
    },
    "nison_beyond": {
        "file": "Beyond Candlesticks - New Japanese Charting Techniques Revealed 1994.pdf",
        "tier": "critical",
        "focus": "advanced_patterns",
        "description": "Advanced patterns, Renko, Kagi, pattern combinations",
    },
    "nison_course": {
        "file": "The Candlestick Course 2003.pdf",
        "tier": "critical",
        "focus": "candlestick_patterns",
        "description": "Structured pattern-by-pattern rules with entry/exit/stoploss",
    },
    "morris_explained": {
        "file": "Candlestick Charting Explained 3rd edition 2006.pdf",
        "tier": "critical",
        "focus": "pattern_statistics",
        "description": "Morris — pattern statistics, reliability data, systematic classification",
    },
    "bulkowski_encyclopedia": {
        "file": "Encyclopedia of Chart Patterns 2nd edition 2005.pdf",
        "tier": "critical",
        "focus": "chart_pattern_stats",
        "description": "Bulkowski — statistical methodology, failure rates, measure rules",
    },
    "candlestick_pivots": {
        "file": "Candlestick and Pivot Point Trading Triggers - Setups for Stock, Forex, and Futures Markets CDR edition 2006.pdf",
        "tier": "critical",
        "focus": "entry_exit_stoploss",
        "description": "Candlesticks + pivot levels for entry/exit/stoploss",
    },

    # ── TIER 2: HIGH VALUE — Context & Strategy ──
    "volume_price": {
        "file": "A Complete Guide To Volume Price Analysis 2013.pdf",
        "tier": "high_value",
        "focus": "volume_analysis",
        "description": "Volume confirmation — our weakest context modifier",
    },
    "price_action_5min": {
        "file": "Understanding Price Action - Practical Analysis of the 5-Minute Time Frame 2014.pdf",
        "tier": "high_value",
        "focus": "intraday_price_action",
        "description": "Directly relevant to 15-min intraday analysis",
    },
    "high_prob_strategies": {
        "file": "High Probability Trading Strategies - Entry to Exit Tactics for the Forex, Futures, and Stock Markets 2008.pdf",
        "tier": "high_value",
        "focus": "entry_exit_tactics",
        "description": "Entry/exit tactics, risk-reward frameworks",
    },
    "trade_what_you_see": {
        "file": "Trade What You See - How To Profit from Pattern Recognition 2007.pdf",
        "tier": "high_value",
        "focus": "pattern_recognition",
        "description": "Pattern recognition methodology",
    },
    "murphy_ta": {
        "file": "Technical Analysis of the Financial Markets - A Comprehensive Guide to Trading Methods and Applications 1999.pdf",
        "tier": "high_value",
        "focus": "technical_analysis_core",
        "description": "Murphy TA bible — trend, S/R, volume chapters",
    },
    "candlestick_getting_started": {
        "file": "Getting Started in Candlestick Charting 2008.pdf",
        "tier": "high_value",
        "focus": "candlestick_patterns",
        "description": "Pattern basics with practical examples",
    },
    "candlestick_dummies": {
        "file": "Candlestick Charting For Dummies 2008.pdf",
        "tier": "high_value",
        "focus": "candlestick_patterns",
        "description": "Accessible pattern guide with trading rules",
    },

    # ── TIER 3: NICE TO HAVE — Trading Psychology & Risk ──
    "trading_zone": {
        "file": "Trading in the Zone - Master the Market with Confidence, Discipline and a Winning Attitude 2000.pdf",
        "tier": "nice_to_have",
        "focus": "trading_psychology",
        "description": "Trading principles, psychology",
    },
    "elder_trading": {
        "file": "The New Trading for a Living - Psychology, Discipline, Trading Tools and Systems, Risk Control, Trade Management 2014.pdf",
        "tier": "nice_to_have",
        "focus": "risk_management",
        "description": "Elder — risk management formulas, 2% rule, position sizing",
    },
}

# Keywords to identify candlestick/pattern-relevant content
CANDLESTICK_KEYWORDS = [
    r"candlestick", r"candle\s*pattern", r"doji", r"hammer", r"engulfing",
    r"morning\s*star", r"evening\s*star", r"harami", r"marubozu", r"spinning\s*top",
    r"shooting\s*star", r"hanging\s*man", r"piercing\s*line", r"dark\s*cloud",
    r"three\s*white\s*soldiers", r"three\s*black\s*crows", r"tweezer",
    r"abandoned\s*baby", r"kicker", r"belt\s*hold", r"three\s*inside",
    r"three\s*outside", r"rising\s*three", r"falling\s*three", r"tri[\-\s]*star",
    r"counterattack", r"on[\-\s]*neck", r"in[\-\s]*neck", r"tasuki",
    r"advance\s*block", r"deliberation", r"stalled", r"high\s*wave",
    r"inverted\s*hammer", r"gravestone", r"dragonfly", r"long[\-\s]*legged",
    r"bullish\s*reversal", r"bearish\s*reversal", r"continuation\s*pattern",
    r"reversal\s*pattern", r"confirmation", r"stop[\-\s]*loss", r"entry\s*price",
    r"target\s*price", r"risk[\-\s]*reward", r"win\s*rate", r"success\s*rate",
    r"failure\s*rate", r"reliability", r"probability", r"volume\s*confirm",
]

# Broader keywords for context/strategy books
STRATEGY_KEYWORDS = [
    r"support\s*(?:and|&)\s*resistance", r"trend\s*(?:line|direction|following)",
    r"fibonacci", r"pivot\s*point", r"volume\s*analysis", r"price\s*action",
    r"risk\s*management", r"position\s*sizing", r"stop\s*loss",
    r"entry\s*(?:point|signal|trigger|rule)", r"exit\s*(?:point|signal|trigger|rule)",
    r"money\s*management", r"risk[\-\s]*reward\s*ratio", r"atr",
    r"rsi", r"macd", r"bollinger", r"stochastic", r"ema\b", r"moving\s*average",
    r"overbought", r"oversold", r"divergence", r"breakout", r"pullback",
    r"market\s*regime", r"bull\s*market", r"bear\s*market", r"ranging",
    r"trading\s*psychology", r"discipline", r"2\s*percent\s*rule",
    r"expectancy", r"edge", r"backtest",
]

COMBINED_PATTERN = re.compile(
    "|".join(CANDLESTICK_KEYWORDS + STRATEGY_KEYWORDS), re.IGNORECASE
)

CANDLESTICK_PATTERN = re.compile(
    "|".join(CANDLESTICK_KEYWORDS), re.IGNORECASE
)


def extract_pdf(filepath, book_key, book_info):
    """Extract text from a PDF, filtering for relevant pages."""
    print(f"\n  [{book_info['tier'].upper()}] Extracting: {book_info['file']}")

    if not os.path.exists(filepath):
        print(f"    FILE NOT FOUND: {filepath}")
        return None

    try:
        doc = fitz.open(filepath)
    except Exception as e:
        print(f"    ERROR opening PDF: {e}")
        return None

    total_pages = len(doc)
    all_text = []
    relevant_pages = []
    full_text_pages = []

    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text()
        full_text_pages.append(text)

        # Check relevance
        if COMBINED_PATTERN.search(text):
            relevant_pages.append(page_num)
            # Count candlestick-specific hits for scoring
            cs_hits = len(CANDLESTICK_PATTERN.findall(text))
            all_text.append({
                "page": page_num + 1,
                "text": text,
                "candlestick_hits": cs_hits,
                "is_highly_relevant": cs_hits >= 3,
            })

    doc.close()

    # For candlestick-focused books, also grab table of contents / intro / conclusion pages
    # (first 15 and last 10 pages regardless of keyword matches)
    context_pages = set(range(min(15, total_pages))) | set(range(max(0, total_pages - 10), total_pages))
    for pg in context_pages:
        if pg not in [p["page"] - 1 for p in all_text]:
            all_text.append({
                "page": pg + 1,
                "text": full_text_pages[pg],
                "candlestick_hits": 0,
                "is_highly_relevant": False,
            })

    # Sort by page number
    all_text.sort(key=lambda x: x["page"])

    result = {
        "book_key": book_key,
        "title": book_info["file"],
        "tier": book_info["tier"],
        "focus": book_info["focus"],
        "description": book_info["description"],
        "total_pages": total_pages,
        "relevant_pages": len(relevant_pages),
        "highly_relevant_pages": sum(1 for p in all_text if p["is_highly_relevant"]),
        "extracted_pages": all_text,
    }

    print(f"    Total pages: {total_pages} | Relevant: {len(relevant_pages)} | "
          f"Highly relevant: {result['highly_relevant_pages']}")

    return result


def save_extract(result, output_dir):
    """Save extracted text to JSON."""
    if result is None:
        return
    outpath = os.path.join(output_dir, f"{result['book_key']}.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"    Saved: {outpath}")


def main():
    print("=" * 80)
    print("BOOK KNOWLEDGE EXTRACTOR — Processing ALL 15 Books")
    print("=" * 80)

    summary = {"critical": [], "high_value": [], "nice_to_have": []}

    for book_key, book_info in BOOKS.items():
        filepath = os.path.join(BOOKS_DIR, book_info["file"])
        result = extract_pdf(filepath, book_key, book_info)
        if result:
            save_extract(result, OUTPUT_DIR)
            summary[book_info["tier"]].append({
                "key": book_key,
                "title": book_info["file"],
                "total_pages": result["total_pages"],
                "relevant_pages": result["relevant_pages"],
                "highly_relevant": result["highly_relevant_pages"],
            })

    # Save summary
    summary_path = os.path.join(OUTPUT_DIR, "_extraction_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 80)
    print("EXTRACTION SUMMARY")
    print("=" * 80)
    for tier, books in summary.items():
        print(f"\n  {tier.upper()} ({len(books)} books):")
        for b in books:
            print(f"    {b['key']}: {b['total_pages']} pages → "
                  f"{b['relevant_pages']} relevant ({b['highly_relevant']} highly)")

    total_pages = sum(b["relevant_pages"] for books in summary.values() for b in books)
    print(f"\n  TOTAL relevant pages extracted: {total_pages}")
    print(f"  Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
