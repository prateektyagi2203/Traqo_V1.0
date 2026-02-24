"""
Traqo — One-Click Setup & Data Bootstrap
=========================================
Run this script after cloning the repo to download market data,
engineer features, build the RAG knowledge base, train the
meta-classifier, and launch the dashboard.

Usage:
    python setup_traqo.py                  # full pipeline
    python setup_traqo.py --step fetch     # run a single step
    python setup_traqo.py --force          # re-run all steps even if outputs exist

Steps (in order):
  1. fetch          — Download 10-year daily OHLCV for 275 NSE stocks
  2. features       — Engineer 60+ technical features & enrich CSVs
  3. knowledge      — Build candlestick knowledge base from book extracts
  4. rag            — Build RAG document corpus (JSONL + JSON)
  5. meta           — Train XGBoost meta-classifier
  6. backtest       — Run walk-forward backtest
  7. dashboard      — Launch the Traqo web dashboard

Each step checks whether its output already exists and skips if so.
Use --force to override this and re-run everything.

Author : Prateek Tyagi
Version: 1.0 (Feb 2026)
"""

import subprocess
import sys
import os
import argparse
import time
import glob

ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable

# Set by --force flag
FORCE = False


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────
def banner(msg: str):
    width = 60
    print("\n" + "=" * width)
    print(f"  {msg}")
    print("=" * width)


def _count_files(directory: str, extension: str = "") -> int:
    """Count files in a directory, optionally filtering by extension."""
    d = os.path.join(ROOT, directory)
    if not os.path.isdir(d):
        return 0
    if extension:
        return len([f for f in os.listdir(d) if f.endswith(extension)])
    return len(os.listdir(d))


def _dir_size_mb(directory: str) -> float:
    """Get total size of a directory in MB."""
    d = os.path.join(ROOT, directory)
    if not os.path.isdir(d):
        return 0.0
    total = sum(os.path.getsize(os.path.join(d, f))
                for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
    return total / (1024 * 1024)


def _step_skip(step_name: str, reason: str) -> bool:
    """Check if a step can be skipped. Returns True if skipped."""
    if FORCE:
        return False
    print(f"  ⏭  Skipping {step_name} — {reason}")
    print(f"     (use --force to re-run)")
    return True


def run_script(script: str, args: list[str] | None = None, check: bool = True):
    """Run a Python script in a subprocess."""
    cmd = [PYTHON, os.path.join(ROOT, script)]
    if args:
        cmd.extend(args)
    print(f"  → Running: {' '.join(cmd)}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=ROOT)
    elapsed = time.time() - t0
    if check and result.returncode != 0:
        print(f"  ✗ {script} failed (exit {result.returncode}) after {elapsed:.0f}s")
        print(f"  💡 Fix the error above, then re-run: python setup_traqo.py --step {_current_step}")
        sys.exit(1)
    print(f"  ✓ {script} completed in {elapsed:.0f}s")
    return result


# Track current step for error messages
_current_step = ""


# ────────────────────────────────────────────────────────────
# Pipeline Steps (with skip-if-exists logic)
# ────────────────────────────────────────────────────────────
def step_fetch():
    """Download 10-year daily OHLCV data for all 275 instruments."""
    global _current_step; _current_step = "fetch"
    banner("Step 1/7 — Fetching Market Data (275 instruments × 10 years)")

    csv_count = _count_files("daily_10yr", ".csv")
    if csv_count >= 200 and _step_skip("fetch", f"daily_10yr/ already has {csv_count} CSVs"):
        return

    print("  ⏳ This downloads ~275 stocks from Yahoo Finance (~30 min)")
    print("     If it stalls, Yahoo may be rate-limiting. Wait a few minutes and retry.")
    run_script("fetch_expanded.py")
    run_script("fetch_nse250_expansion.py")
    csv_count = _count_files("daily_10yr", ".csv")
    print(f"  📂 daily_10yr/ now has {csv_count} CSV files")


def step_features():
    """Engineer 60+ technical features for every instrument."""
    global _current_step; _current_step = "features"
    banner("Step 2/7 — Feature Engineering + RAG Document Generation")

    enriched_count = _count_files("enriched_v2", ".csv")
    rag_exists = os.path.isfile(os.path.join(ROOT, "rag_documents_v2", "all_pattern_documents.json"))
    if enriched_count >= 200 and rag_exists and _step_skip(
            "features", f"enriched_v2/ has {enriched_count} CSVs and RAG docs exist"):
        return

    run_script("feature_engineering.py")
    enriched_count = _count_files("enriched_v2", ".csv")
    print(f"  📂 enriched_v2/ now has {enriched_count} enriched CSVs")
    rag_mb = _dir_size_mb("rag_documents_v2")
    if rag_mb > 0:
        print(f"  📂 rag_documents_v2/ generated ({rag_mb:.0f} MB)")


def step_knowledge():
    """Build the candlestick knowledge base from book extracts."""
    global _current_step; _current_step = "knowledge"
    banner("Step 3/7 — Building Candlestick Knowledge Base")

    # Check if parsed_knowledge exists (shipped with repo)
    pk_path = os.path.join(ROOT, "parsed_knowledge", "all_book_knowledge.json")
    if os.path.isfile(pk_path):
        size_mb = os.path.getsize(pk_path) / (1024 * 1024)
        print(f"  ℹ  parsed_knowledge/all_book_knowledge.json exists ({size_mb:.1f} MB)")

    run_script("build_knowledge_base.py")


def step_rag():
    """Verify RAG document corpus exists — rebuild if missing."""
    global _current_step; _current_step = "rag"
    banner("Step 4/7 — Verifying RAG Document Corpus")

    rag_path = os.path.join(ROOT, "rag_documents_v2", "all_pattern_documents.json")
    if os.path.isfile(rag_path):
        size_mb = os.path.getsize(rag_path) / (1024 * 1024)
        print(f"  ✓ RAG corpus exists: all_pattern_documents.json ({size_mb:.0f} MB)")
        jsonl_path = os.path.join(ROOT, "rag_documents_v2", "all_pattern_documents.jsonl")
        if os.path.isfile(jsonl_path):
            jsonl_mb = os.path.getsize(jsonl_path) / (1024 * 1024)
            print(f"  ✓ JSONL variant: all_pattern_documents.jsonl ({jsonl_mb:.0f} MB)")
        return

    # RAG docs don't exist — need to generate them
    print("  ⚠  RAG documents not found — they are generated by feature_engineering.py")
    enriched_count = _count_files("enriched_v2", ".csv")
    if enriched_count < 10:
        print("  ✗ enriched_v2/ is empty. Run Step 2 (features) first:")
        print(f"    {PYTHON} setup_traqo.py --step features")
        sys.exit(1)

    print("  → Re-running feature_engineering.py to generate RAG documents...")
    run_script("feature_engineering.py")

    if os.path.isfile(rag_path):
        size_mb = os.path.getsize(rag_path) / (1024 * 1024)
        print(f"  ✓ RAG corpus generated: {size_mb:.0f} MB")
    else:
        print("  ✗ RAG documents were not generated. Check feature_engineering.py output above.")
        sys.exit(1)


def step_meta():
    """Train XGBoost meta-classifier on walk-forward results."""
    global _current_step; _current_step = "meta"
    banner("Step 5/7 — Training Meta-Classifier")

    model_path = os.path.join(ROOT, "models", "meta_classifier.json")
    if os.path.isfile(model_path) and _step_skip("meta", "models/meta_classifier.json exists"):
        return

    run_script("meta_classifier.py")


def step_backtest():
    """Run walk-forward backtest."""
    global _current_step; _current_step = "backtest"
    banner("Step 6/7 — Walk-Forward Backtest")

    results_path = os.path.join(ROOT, "backtest_walkforward_results.json")
    if os.path.isfile(results_path) and _step_skip("backtest", "backtest_walkforward_results.json exists"):
        return

    run_script("backtest_walkforward.py")


def step_dashboard():
    """Launch the Traqo web dashboard."""
    global _current_step; _current_step = "dashboard"
    banner("Step 7/7 — Launching Dashboard")
    print("  → Starting Traqo dashboard on http://localhost:8521")
    run_script("paper_trading_dashboard.py", check=False)


# ────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────
STEPS = {
    "fetch":     step_fetch,
    "features":  step_features,
    "knowledge": step_knowledge,
    "rag":       step_rag,
    "meta":      step_meta,
    "backtest":  step_backtest,
    "dashboard": step_dashboard,
}

def main():
    global FORCE
    parser = argparse.ArgumentParser(
        description="Traqo — One-Click Setup & Data Bootstrap"
    )
    parser.add_argument(
        "--step",
        choices=list(STEPS.keys()),
        help="Run a single step instead of the full pipeline",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run steps even if their outputs already exist",
    )
    args = parser.parse_args()
    FORCE = args.force

    banner("Traqo — RAG-Powered Quantitative Candlestick Intelligence")
    print(f"  Python : {sys.version.split()[0]}")
    print(f"  Root   : {ROOT}")
    if FORCE:
        print(f"  Mode   : --force (re-running all steps)")

    if args.step:
        STEPS[args.step]()
    else:
        # Full pipeline
        for name, func in STEPS.items():
            if name == "dashboard":
                continue  # don't auto-launch dashboard in full pipeline
            func()

        banner("Setup Complete!")
        print("  All data downloaded, features engineered, models trained.")
        print()
        print("  To launch the dashboards:")
        print(f"    {PYTHON} paper_trading_dashboard.py    →  http://localhost:8521")
        print(f"    {PYTHON} rag_analyzer_dashboard.py     →  http://localhost:8522  (requires Ollama)")
        print()
        print("  To re-run any step:")
        print(f"    {PYTHON} setup_traqo.py --step <step_name>")
        print(f"    {PYTHON} setup_traqo.py --force          # re-run everything")


if __name__ == "__main__":
    main()
