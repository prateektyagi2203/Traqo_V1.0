"""
NSE 250 Expansion — Download 10yr Daily Data for ~230 NEW Stocks
================================================================
Downloads daily OHLCV data for Nifty 250 stocks NOT already in the RAG
knowledge base. Skips any file that already exists in daily_10yr/.

Existing 20 Indian equities already in RAG (EXCLUDED):
  adanient, axisbank, bajfinance, bhartiartl, hcltech, hdfcbank,
  hindunilvr, icicibank, infosys, itc, kotakbank, lt, maruti,
  reliance, sbi, sunpharma, tcs, titan, wipro
  (tatamotors was in config but download failed → included here as retry)

After running this script:
  1. Run feature_engineering.py   → regenerates enriched CSVs + RAG docs
  2. Run rag_predictor.py         → re-indexes ChromaDB (if applicable)
  3. Restart StatisticalPredictor  → auto-loads new docs
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os
import time
import sys

# ============================================================
# STOCKS ALREADY IN RAG (will be SKIPPED even if listed)
# ============================================================
ALREADY_IN_RAG = {
    "adanient", "axisbank", "bajfinance", "bhartiartl", "hcltech",
    "hdfcbank", "hindunilvr", "icicibank", "infosys", "itc",
    "kotakbank", "lt", "maruti", "reliance", "sbi",
    "sunpharma", "tcs", "titan", "wipro",
}

# ============================================================
# ~230 NEW NSE STOCKS (Top 250 minus existing 20)
# Organized by: Nifty 50 remainder → Nifty Next 50 → Nifty Midcap 150
# ============================================================
NEW_INSTRUMENTS = {

    # ══════════════════════════════════════════════════════════
    # TIER A: Nifty 50 Completion (31 stocks)
    # ══════════════════════════════════════════════════════════
    "ADANIPORTS.NS":  "adaniports",
    "APOLLOHOSP.NS":  "apollohosp",
    "ASIANPAINT.NS":  "asianpaint",
    "BAJAJ-AUTO.NS":  "bajajauto",
    "BAJAJFINSV.NS":  "bajajfinsv",
    "BPCL.NS":        "bpcl",
    "BRITANNIA.NS":   "britannia",
    "CIPLA.NS":       "cipla",
    "COALINDIA.NS":   "coalindia",
    "DIVISLAB.NS":    "divislab",
    "DRREDDY.NS":     "drreddy",
    "EICHERMOT.NS":   "eichermot",
    "ETERNAL.NS":     "eternal",          # formerly ZOMATO (renamed Jan 2025)
    "GRASIM.NS":      "grasim",
    "HDFCLIFE.NS":    "hdfclife",
    "HEROMOTOCO.NS":  "heromotoco",
    "HINDALCO.NS":    "hindalco",
    "INDUSINDBK.NS":  "indusindbk",
    "JSWSTEEL.NS":    "jswsteel",
    "M&M.NS":         "mahindra",
    "NESTLEIND.NS":   "nestleind",
    "NTPC.NS":        "ntpc",
    "ONGC.NS":        "ongc",
    "POWERGRID.NS":   "powergrid",
    "SBILIFE.NS":     "sbilife",
    "SHRIRAMFIN.NS":  "shriramfin",
    "TATAMOTORS.NS":  "tatamotors",       # retry: was in original batch but download failed
    "TATASTEEL.NS":   "tatasteel",
    "TECHM.NS":       "techm",
    "TRENT.NS":       "trent",
    "ULTRACEMCO.NS":  "ultracemco",

    # ══════════════════════════════════════════════════════════
    # TIER B: Nifty Next 50 (50 stocks)
    # ══════════════════════════════════════════════════════════
    "ABB.NS":         "abb",
    "ACC.NS":         "acc",
    "ADANIGREEN.NS":  "adanigreen",
    "ADANIPOWER.NS":  "adanipower",
    "AMBUJACEM.NS":   "ambujacem",
    "ATGL.NS":        "atgl",
    "AUROPHARMA.NS":  "auropharma",
    "BAJAJHLDNG.NS":  "bajajhldng",
    "BANKBARODA.NS":  "bankbaroda",
    "BEL.NS":         "bel",
    "BERGEPAINT.NS":  "bergepaint",
    "BIOCON.NS":      "biocon",
    "BOSCHLTD.NS":    "boschltd",
    "CANBK.NS":       "canbk",
    "CHOLAFIN.NS":    "cholafin",
    "COLPAL.NS":      "colpal",
    "DABUR.NS":       "dabur",
    "DLF.NS":         "dlf",
    "GAIL.NS":        "gail",
    "GODREJCP.NS":    "godrejcp",
    "HAL.NS":         "hal",
    "HAVELLS.NS":     "havells",
    "ICICIPRULI.NS":  "icicipruli",
    "INDIGO.NS":      "indigo",
    "IOC.NS":         "ioc",
    "IRCTC.NS":       "irctc",
    "IRFC.NS":        "irfc",
    "JINDALSTEL.NS":  "jindalstel",
    "JIOFIN.NS":      "jiofin",
    "LICI.NS":        "lici",
    "LTIM.NS":        "ltim",
    "LTTS.NS":        "ltts",
    "LUPIN.NS":       "lupin",
    "MAXHEALTH.NS":   "maxhealth",
    "MOTHERSON.NS":   "motherson",
    "NAUKRI.NS":      "naukri",
    "NHPC.NS":        "nhpc",
    "OBEROIRLTY.NS":  "oberoirlty",
    "OFSS.NS":        "ofss",
    "PAYTM.NS":      "paytm",           # was ONE97.NS, renamed
    "PFC.NS":         "pfc",
    "PIDILITIND.NS":  "pidilitind",
    "PNB.NS":         "pnb",
    "POLYCAB.NS":     "polycab",
    "RECLTD.NS":      "recltd",
    "SBICARD.NS":     "sbicard",
    "SIEMENS.NS":     "siemens",
    "SRF.NS":         "srf",
    "TATACONSUM.NS":  "tataconsum",
    "TATAPOWER.NS":   "tatapower",

    # ══════════════════════════════════════════════════════════
    # TIER C: Nifty Midcap 150 (149 stocks)
    # ══════════════════════════════════════════════════════════
    "AARTIIND.NS":     "aartiind",
    "ABCAPITAL.NS":    "abcapital",
    "ABFRL.NS":        "abfrl",
    "ALKEM.NS":        "alkem",
    "ANGELONE.NS":     "angelone",
    "APLAPOLLO.NS":    "aplapollo",
    "APLLTD.NS":       "aplltd",
    "ASHOKLEY.NS":     "ashokley",
    "ASTRAL.NS":       "astral",
    "ATUL.NS":         "atul",
    "AUBANK.NS":       "aubank",
    "BALKRISIND.NS":   "balkrisind",
    "BANKINDIA.NS":    "bankindia",
    "BATAINDIA.NS":    "bataindia",
    "BHARATFORG.NS":   "bharatforg",
    "BHEL.NS":         "bhel",
    "BSE.NS":          "bse",
    "CANFINHOME.NS":   "canfinhome",
    "CARBORUNIV.NS":   "carboruniv",
    "CASTROLIND.NS":   "castrolind",
    "CDSL.NS":         "cdsl",
    "CESC.NS":         "cesc",
    "CGPOWER.NS":      "cgpower",
    "CHAMBLFERT.NS":   "chamblfert",
    "CLEAN.NS":        "clean",
    "COCHINSHIP.NS":   "cochinship",
    "COFORGE.NS":      "coforge",
    "COROMANDEL.NS":   "coromandel",
    "CROMPTON.NS":     "crompton",
    "CUB.NS":          "cub",
    "CUMMINSIND.NS":   "cumminsind",
    "CYIENT.NS":       "cyient",
    "DALBHARAT.NS":    "dalbharat",
    "DEEPAKNTR.NS":    "deepakntr",
    "DELHIVERY.NS":    "delhivery",
    "DEVYANI.NS":      "devyani",
    "DIXON.NS":        "dixon",
    "EMAMILTD.NS":     "emamiltd",
    "ENDURANCE.NS":    "endurance",
    "ESCORTS.NS":      "escorts",
    "EXIDEIND.NS":     "exideind",
    "FACT.NS":         "fact",
    "FEDERALBNK.NS":   "federalbnk",
    "FINEORG.NS":      "fineorg",
    "FLUOROCHEM.NS":   "fluorochem",
    "FORTIS.NS":       "fortis",
    "GILLETTE.NS":     "gillette",
    "GLENMARK.NS":     "glenmark",
    "GLAXO.NS":        "glaxo",
    "GMRAIRPORT.NS":   "gmrairport",
    "GNFC.NS":         "gnfc",
    "GODREJIND.NS":    "godrejind",
    "GODREJPROP.NS":   "godrejprop",
    "GRANULES.NS":     "granules",
    "GRAPHITE.NS":     "graphite",
    "GRINDWELL.NS":    "grindwell",
    "GUJGASLTD.NS":    "gujgasltd",
    "HATSUN.NS":       "hatsun",
    "HINDPETRO.NS":    "hindpetro",
    "HONAUT.NS":       "honaut",
    "IDFCFIRSTB.NS":   "idfcfirstb",
    "IEX.NS":          "iex",
    "IIFL.NS":         "iifl",
    "INDIANB.NS":      "indianb",
    "INDHOTEL.NS":    "indianhotels",    # was INDIANHOTELS.NS, corrected ticker
    "INDIAMART.NS":    "indiamart",
    "INDUSTOWER.NS":   "industower",
    "INTELLECT.NS":    "intellect",
    "IPCALAB.NS":      "ipcalab",
    "JKCEMENT.NS":     "jkcement",
    "JSWENERGY.NS":    "jswenergy",
    "JUBLFOOD.NS":     "jublfood",
    "KALYANKJIL.NS":   "kalyankjil",
    "KEI.NS":          "kei",
    "KIMS.NS":         "kims",
    "KPITTECH.NS":     "kpittech",
    "LALPATHLAB.NS":   "lalpathlab",
    "LAURUSLABS.NS":   "lauruslabs",
    "LICHSGFIN.NS":    "lichsgfin",
    "MANAPPURAM.NS":   "manappuram",
    "MANKIND.NS":      "mankind",
    "MARICO.NS":       "marico",
    "MAZDOCK.NS":      "mazdock",
    "METROBRAND.NS":   "metrobrand",
    "MFSL.NS":         "mfsl",
    "MGL.NS":          "mgl",
    "MPHASIS.NS":      "mphasis",
    "MRF.NS":          "mrf",
    "MUTHOOTFIN.NS":   "muthootfin",
    "NATCOPHARM.NS":   "natcopharm",
    "NAVINFLUOR.NS":   "navinfluor",
    "NMDC.NS":         "nmdc",
    "OIL.NS":          "oil",
    "PAGEIND.NS":      "pageind",
    "PATANJALI.NS":    "patanjali",
    "PERSISTENT.NS":   "persistent",
    "PETRONET.NS":     "petronet",
    "PHOENIXLTD.NS":   "phoenixltd",
    "PIIND.NS":        "piind",
    "POLYMED.NS":      "polymed",
    "PRESTIGE.NS":     "prestige",
    "PVRINOX.NS":      "pvrinox",
    "RADICO.NS":       "radico",
    "RAIN.NS":         "rain",
    "RAJESHEXPO.NS":   "rajeshexpo",
    "RAMCOCEM.NS":     "ramcocem",
    "RATNAMANI.NS":    "ratnamani",
    "RBLBANK.NS":      "rblbank",
    "SAIL.NS":         "sail",
    "SCHAEFFLER.NS":   "schaeffler",
    "SHREECEM.NS":     "shreecem",
    "SONACOMS.NS":     "sonacoms",
    "STARHEALTH.NS":   "starhealth",
    "SUMICHEM.NS":     "sumichem",
    "SUNDARMFIN.NS":   "sundarmfin",
    "SUNDRMFAST.NS":   "sundrmfast",
    "SUNTV.NS":        "suntv",
    "SUPREMEIND.NS":   "supremeind",
    "SYNGENE.NS":      "syngene",
    "TATACHEM.NS":     "tatachem",
    "TATACOMM.NS":     "tatacomm",
    "TATAELXSI.NS":    "tataelxsi",
    "TATATECH.NS":     "tatatech",
    "TIINDIA.NS":      "tiindia",
    "TIMKEN.NS":       "timken",
    "TORNTPHARM.NS":   "torntpharm",
    "TORNTPOWER.NS":   "torntpower",
    "TRIDENT.NS":      "trident",
    "TVSMOTOR.NS":     "tvsmotor",
    "UBL.NS":          "ubl",
    "UNIONBANK.NS":    "unionbank",
    "UNITDSPR.NS":     "unitdspr",
    "UPL.NS":          "upl",
    "VBL.NS":          "vbl",
    "VEDL.NS":         "vedl",
    "VOLTAS.NS":       "voltas",
    "WHIRLPOOL.NS":    "whirlpool",
    "YESBANK.NS":      "yesbank",
    "ZEEL.NS":         "zeel",
    "ZYDUSLIFE.NS":    "zyduslife",
    "PGHH.NS":         "pghh",
    "3MINDIA.NS":      "3mindia",
    "AIAENG.NS":       "aiaeng",
    "AJANTPHARM.NS":   "ajantpharm",
    "NAM-INDIA.NS":    "namindia",
    "JSWINFRA.NS":     "jswinfra",
    "POONAWALLA.NS":   "poonawalla",
    "SUNTECK.NS":      "sunteck",
}

# ============================================================
# Sector mapping for all new stocks (used in trading_config.py)
# ============================================================
SECTOR_MAP = {
    # --- Nifty 50 Completion ---
    "adaniports": "infrastructure", "apollohosp": "healthcare",
    "asianpaint": "fmcg", "bajajauto": "auto",
    "bajajfinsv": "bfsi", "bpcl": "energy",
    "britannia": "fmcg", "cipla": "pharma",
    "coalindia": "metals_mining", "divislab": "pharma",
    "drreddy": "pharma", "eichermot": "auto",
    "eternal": "consumer_tech", "grasim": "diversified",
    "hdfclife": "bfsi", "heromotoco": "auto",
    "hindalco": "metals_mining", "indusindbk": "bfsi",
    "jswsteel": "metals_mining", "mahindra": "auto",
    "nestleind": "fmcg", "ntpc": "energy",
    "ongc": "energy", "powergrid": "energy",
    "sbilife": "bfsi", "shriramfin": "bfsi",
    "tatamotors": "auto", "tatasteel": "metals_mining",
    "techm": "it", "trent": "retail",
    "ultracemco": "cement",
    # --- Nifty Next 50 ---
    "abb": "capital_goods", "acc": "cement",
    "adanigreen": "energy", "adanipower": "energy",
    "ambujacem": "cement", "atgl": "energy",
    "auropharma": "pharma", "bajajhldng": "bfsi",
    "bankbaroda": "bfsi", "bel": "defence",
    "bergepaint": "chemicals", "biocon": "pharma",
    "boschltd": "auto", "canbk": "bfsi",
    "cholafin": "bfsi", "colpal": "fmcg",
    "dabur": "fmcg", "dlf": "realty",
    "gail": "energy", "godrejcp": "fmcg",
    "hal": "defence", "havells": "consumer_durables",
    "icicipruli": "bfsi", "indigo": "aviation",
    "ioc": "energy", "irctc": "travel",
    "irfc": "bfsi", "jindalstel": "metals_mining",
    "jiofin": "bfsi", "lici": "bfsi",
    "ltim": "it", "ltts": "it",
    "lupin": "pharma", "maxhealth": "healthcare",
    "motherson": "auto", "naukri": "it",
    "nhpc": "energy", "oberoirlty": "realty",
    "ofss": "it", "paytm": "fintech",
    "pfc": "bfsi", "pidilitind": "chemicals",
    "pnb": "bfsi", "polycab": "capital_goods",
    "recltd": "bfsi", "sbicard": "bfsi",
    "siemens": "capital_goods", "srf": "chemicals",
    "tataconsum": "fmcg", "tatapower": "energy",
    # --- Nifty Midcap 150 ---
    "aartiind": "chemicals", "abcapital": "bfsi",
    "abfrl": "retail", "alkem": "pharma",
    "angelone": "bfsi", "aplapollo": "capital_goods",
    "aplltd": "pharma", "ashokley": "auto",
    "astral": "capital_goods", "atul": "chemicals",
    "aubank": "bfsi", "balkrisind": "auto",
    "bankindia": "bfsi", "bataindia": "retail",
    "bharatforg": "capital_goods", "bhel": "capital_goods",
    "bse": "bfsi", "canfinhome": "bfsi",
    "carboruniv": "capital_goods", "castrolind": "energy",
    "cdsl": "bfsi", "cesc": "energy",
    "cgpower": "capital_goods", "chamblfert": "chemicals",
    "clean": "chemicals", "cochinship": "defence",
    "coforge": "it", "coromandel": "chemicals",
    "crompton": "consumer_durables", "cub": "bfsi",
    "cumminsind": "capital_goods", "cyient": "it",
    "dalbharat": "cement", "deepakntr": "chemicals",
    "delhivery": "logistics", "devyani": "consumer_services",
    "dixon": "consumer_durables", "emamiltd": "fmcg",
    "endurance": "auto", "escorts": "auto",
    "exideind": "auto", "fact": "chemicals",
    "federalbnk": "bfsi", "fineorg": "chemicals",
    "fluorochem": "chemicals", "fortis": "healthcare",
    "gillette": "fmcg", "glenmark": "pharma",
    "glaxo": "pharma", "gmrairport": "infrastructure",
    "gnfc": "chemicals", "godrejind": "diversified",
    "godrejprop": "realty", "granules": "pharma",
    "graphite": "capital_goods", "grindwell": "capital_goods",
    "gujgasltd": "energy", "hatsun": "fmcg",
    "hindpetro": "energy", "honaut": "capital_goods",
    "idfcfirstb": "bfsi", "iex": "capital_goods",
    "iifl": "bfsi", "indianb": "bfsi",
    "indianhotels": "hospitality", "indiamart": "it",
    "industower": "telecom", "intellect": "it",
    "ipcalab": "pharma", "jkcement": "cement",
    "jswenergy": "energy", "jublfood": "consumer_services",
    "kalyankjil": "retail", "kei": "capital_goods",
    "kims": "healthcare", "kpittech": "it",
    "lalpathlab": "healthcare", "lauruslabs": "pharma",
    "lichsgfin": "bfsi", "manappuram": "bfsi",
    "mankind": "pharma", "marico": "fmcg",
    "mazdock": "defence", "metrobrand": "retail",
    "mfsl": "bfsi", "mgl": "energy",
    "mphasis": "it", "mrf": "auto",
    "muthootfin": "bfsi", "natcopharm": "pharma",
    "navinfluor": "chemicals", "nmdc": "metals_mining",
    "oil": "energy", "pageind": "retail",
    "patanjali": "fmcg", "persistent": "it",
    "petronet": "energy", "phoenixltd": "realty",
    "piind": "chemicals", "polymed": "healthcare",
    "prestige": "realty", "pvrinox": "entertainment",
    "radico": "consumer_services", "rain": "chemicals",
    "rajeshexpo": "fmcg", "ramcocem": "cement",
    "ratnamani": "capital_goods", "rblbank": "bfsi",
    "sail": "metals_mining", "schaeffler": "auto",
    "shreecem": "cement", "sonacoms": "auto",
    "starhealth": "bfsi", "sumichem": "chemicals",
    "sundarmfin": "bfsi", "sundrmfast": "auto",
    "suntv": "media", "supremeind": "capital_goods",
    "syngene": "pharma", "tatachem": "chemicals",
    "tatacomm": "telecom", "tataelxsi": "it",
    "tatatech": "it", "tiindia": "capital_goods",
    "timken": "capital_goods", "torntpharm": "pharma",
    "torntpower": "energy", "trident": "textiles",
    "tvsmotor": "auto", "ubl": "consumer_services",
    "unionbank": "bfsi", "unitdspr": "consumer_services",
    "upl": "chemicals", "vbl": "fmcg",
    "vedl": "metals_mining", "voltas": "consumer_durables",
    "whirlpool": "consumer_durables", "yesbank": "bfsi",
    "zeel": "media", "zyduslife": "pharma",
    "pghh": "fmcg", "3mindia": "diversified",
    "aiaeng": "capital_goods", "ajantpharm": "pharma",
    "namindia": "bfsi", "jswinfra": "infrastructure",
    "poonawalla": "bfsi", "sunteck": "realty",
}

# ============================================================
# Configuration
# ============================================================
OUTPUT_DIR = "daily_10yr"
end_date = datetime.today()
daily_start = end_date - timedelta(days=10 * 365)  # 10 YEARS


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Filter out instruments whose CSV already exists
    to_download = {}
    skipped_existing = []
    for ticker, name in NEW_INSTRUMENTS.items():
        csv_path = f"{OUTPUT_DIR}/{name}_daily_10yr.csv"
        if os.path.exists(csv_path):
            skipped_existing.append(name)
        else:
            to_download[ticker] = name

    total = len(to_download)
    print(f"{'=' * 70}")
    print(f"  NSE 250 EXPANSION: {total} new stocks to download")
    print(f"  Already downloaded (skipped): {len(skipped_existing)}")
    print(f"  Date range: {daily_start.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')}")
    print(f"  Output: {OUTPUT_DIR}/")
    print(f"{'=' * 70}")

    if skipped_existing:
        print(f"  Skipped: {', '.join(sorted(skipped_existing)[:10])}{'...' if len(skipped_existing) > 10 else ''}")

    if total == 0:
        print("\n  All stocks already downloaded! Run feature_engineering.py next.")
        return

    summary = []
    failed = []

    for i, (ticker, name) in enumerate(to_download.items(), 1):
        print(f"\n[{i}/{total}] {name.upper()} ({ticker})")
        rows = 0

        try:
            df = yf.download(
                ticker,
                start=daily_start.strftime('%Y-%m-%d'),
                end=end_date.strftime('%Y-%m-%d'),
                interval="1d",
                progress=False,
                timeout=30,
            )
            if not df.empty:
                csv_path = f"{OUTPUT_DIR}/{name}_daily_10yr.csv"
                df.to_csv(csv_path)
                rows = df.shape[0]
                print(f"  ✓ {rows:,} rows saved")
            else:
                print(f"  EMPTY — no data returned")
        except Exception as e:
            print(f"  FAILED: {e}")

        if rows == 0:
            failed.append(f"{name} ({ticker})")

        summary.append({"name": name, "ticker": ticker, "rows": rows})

        # Rate limit: 0.5s between requests (Yahoo throttles at ~2000/hr)
        time.sleep(0.5)

    # ── Summary ──
    print(f"\n\n{'=' * 80}")
    print("NSE 250 EXPANSION — DOWNLOAD SUMMARY")
    print(f"{'=' * 80}")
    print(f"{'Name':<20} {'Ticker':<20} {'Rows':>8}  Status")
    print("-" * 60)

    ok_count = 0
    total_rows = 0
    for s in summary:
        status = "✓" if s["rows"] > 0 else "✗ FAILED"
        if s["rows"] > 0:
            ok_count += 1
        print(f"{s['name']:<20} {s['ticker']:<20} {s['rows']:>8,}  {status}")
        total_rows += s["rows"]

    print("-" * 60)
    print(f"{'TOTAL':<20} {'':<20} {total_rows:>8,}")
    print(f"\nStocks: {ok_count}/{total} successful ({len(skipped_existing)} pre-existing skipped)")
    print(f"Total daily candles: {total_rows:,}")

    if failed:
        print(f"\nFailed ({len(failed)}):")
        for f_name in failed:
            print(f"  - {f_name}")

    # ── Retry suggestions for failed tickers ──
    if failed:
        print(f"\nRetry failed tickers:")
        print(f"  python fetch_nse250_expansion.py")
        print(f"  (script auto-skips already-downloaded files)")

    print(f"\n{'=' * 80}")
    print(f"NEXT STEPS:")
    print(f"  1. python feature_engineering.py          # Process all CSVs → RAG docs")
    print(f"  2. Update trading_config.py               # Add new stocks to ALLOWED_INSTRUMENTS")
    print(f"  3. Restart trading apps                   # Auto-loads new docs")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
