<p align="center">
  <img src="traqo_icon_180.png" alt="Traqo" width="80">
</p>

<h1 align="center">Traqo</h1>
<p align="center">
  <strong>RAG-Powered Quantitative Candlestick Intelligence</strong><br>
  <em>by Prateek Tyagi</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/XGBoost-Meta--Classifier-green?logo=xgboost" alt="XGBoost">
  <img src="https://img.shields.io/badge/RAG-543K_Docs-orange" alt="RAG Docs">
  <img src="https://img.shields.io/badge/NSE-275_Instruments-red" alt="NSE">
  <img src="https://img.shields.io/badge/License-MIT-lightgrey" alt="License">
</p>

---

## What is Traqo?

Traqo is a **production-grade quantitative trading research system** that combines:

- **Retrieval-Augmented Generation (RAG)** over 15 authoritative candlestick & technical analysis books
- **Walk-forward backtesting** across 275 NSE instruments and 10 years of daily OHLCV data
- **XGBoost meta-classifier** with 38 engineered features for signal filtering
- **Automated paper trading** with position sizing, risk management, and self-improving feedback loops

It is **not** a black-box ML predictor. It is a systematic framework that extracts human-readable trading rules from books, validates them statistically against historical data, and deploys the proven ones in a disciplined paper-trading pipeline.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      DATA PIPELINE                              │
│  Yahoo Finance → 275 instruments × 10 years → daily_10yr/      │
│  Feature Engineering → 60+ indicators (RSI, MACD, ATR, OBV…)   │
│  Regime Detection → Trending / Mean-Reverting / Volatile        │
└──────────────┬──────────────────────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE ENGINE                             │
│  15 Books → 5,539 pages → 930 extracted rules → 53 patterns    │
│  RAG Corpus: 543,954 documents (JSONL + JSON)                   │
│  Semantic matching via Sentence-Transformers embeddings         │
└──────────────┬──────────────────────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PREDICTION LAYER                              │
│  Statistical Predictor → pattern detection + RAG context        │
│  XGBoost Meta-Classifier → 38 features, filters false signals   │
│  Position Sizing → Kelly Criterion + regime-adaptive            │
│  Risk Manager → drawdown limits, correlation checks             │
└──────────────┬──────────────────────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────────────────────┐
│                  PRODUCTION LAYER                               │
│  Paper Trader → automated daily execution via Task Scheduler    │
│  Trade Logger → SQLite database, entry/exit/PnL tracking        │
│  Feedback Loop → closed-trade outcomes refine RAG weights       │
│  Web Dashboards → server-rendered HTML, real-time portfolio     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Results

| Metric | Before Meta-Classifier | After Meta-Classifier |
|--------|----------------------|----------------------|
| Profit Factor | 1.14 | **1.44** |
| Max Drawdown | -49% | **-25%** |
| Win Rate | 48.2% | **51.7%** |
| Total Trades (OOS) | 3,103 | 1,847 |

> Walk-forward OOS period: 2024–2025. Training: 2016–2023.

---

## Knowledge Base

Built from **15 authoritative books** including:

- Nison — *Japanese Candlestick Charting Techniques*
- Bulkowski — *Encyclopedia of Candlestick Charts*
- Murphy — *Technical Analysis of the Financial Markets*
- Elder — *Trading for a Living*
- Morris — *Candlestick Charting Explained*
- Nison — *Beyond Candlesticks*

**930 trading rules** extracted, validated, and scored against 10 years of market data across 275 instruments.

The pre-extracted knowledge (`book_extracts/` and `parsed_knowledge/`) is included in the repo so you don't need the original PDFs.

---

## Project Structure

```
├── trading_config.py           # Centralized filters (instruments, timeframes, patterns)
├── fetch_expanded.py           # Download 10yr daily OHLCV from Yahoo Finance
├── fetch_nse250_expansion.py   # NSE 250 stock universe expansion
├── feature_engineering.py      # 60+ technical indicators & enrichment + RAG doc builder
├── pattern_detector.py         # Candlestick pattern recognition (53 patterns)
├── regime_detector.py          # Market regime classification
├── statistical_predictor.py    # RAG-based statistical signal generation
├── fast_stat_predictor.py      # Optimized lightweight predictor
├── candlestick_knowledge_base.py # 930-rule knowledge base
├── build_knowledge_base.py     # Book → knowledge base pipeline
├── extract_books.py            # PDF → structured JSON extraction
├── parse_books.py              # Raw text → trading rules parser
├── meta_classifier.py          # XGBoost meta-classifier training
├── backtest_walkforward.py     # Walk-forward backtesting engine
├── backtest_ab.py              # A/B testing framework
├── position_sizing.py          # Kelly Criterion + regime-adaptive sizing
├── risk_manager.py             # Drawdown/correlation risk controls
├── stress_test.py              # Monte Carlo stress testing
├── paper_trader.py             # Automated paper trading execution
├── trade_logger.py             # SQLite trade logging
├── rag_analyzer_dashboard.py   # RAG Analyzer dashboard (port 8522) — batch analysis + caching
├── paper_trading_dashboard.py  # Paper Trading dashboard (port 8521) — 6 pages
├── app_ollama.py               # Streamlit chatbot interface (legacy)
├── visualize_equity.py         # Equity curve visualization
├── setup_traqo.py              # One-click bootstrap script
├── requirements.txt            # Python dependencies
├── book_extracts/              # Extracted book content (JSON) — included in repo
├── parsed_knowledge/           # Parsed trading rules — included in repo
└── traqo_icon_180.png          # Logo
```

---

## Prerequisites

| Dependency | Purpose | Install |
|-----------|---------|---------|
| **Python 3.11+** | Runtime | [python.org](https://www.python.org/downloads/) |
| **Ollama** | Local LLM for RAG analysis | [ollama.com](https://ollama.com/download) |
| **qwen2.5:7b** | LLM model (~4.7 GB) | `ollama pull qwen2.5:7b` |
| **~8 GB RAM** | For LLM + data processing | — |

> **Ollama is required** for the RAG Analyzer dashboard and the Streamlit chatbot.
> The Paper Trading dashboard and backtesting work without Ollama.

---

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/prateektyagi2203/Traqo.git
cd Traqo
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Install Ollama (for LLM-powered analysis)

```bash
# Download & install from https://ollama.com/download
# Then pull the model:
ollama pull qwen2.5:7b
```

### 3. One-Click Setup

```bash
python setup_traqo.py
```

This will:
1. **Download** 10-year daily data for 275 NSE stocks from Yahoo Finance (~30 min)
2. **Engineer** 60+ technical features for every instrument
3. **Build** the candlestick knowledge base from included book extracts
4. **Generate** RAG document corpus (~2 GB, built from enriched data)
5. **Train** the XGBoost meta-classifier
6. **Run** walk-forward backtest to validate

Each step **skips automatically** if its output already exists. If setup fails midway, just re-run the same command — it will resume from where it stopped.

```bash
# Re-run everything from scratch (ignores existing outputs):
python setup_traqo.py --force
```

### 4. Launch Dashboards

```bash
# RAG Analyzer — single stock analysis with Ollama LLM (requires Ollama)
python rag_analyzer_dashboard.py
# → http://localhost:8522

# Paper Trading — portfolio view, trade history, analytics
python paper_trading_dashboard.py
# → http://localhost:8521
```

### 5. Run Paper Trader

```bash
python paper_trader.py run
```

For automated daily execution, set up a scheduled task (Windows Task Scheduler / cron).

---

## Run Individual Steps

```bash
python setup_traqo.py --step fetch      # Download market data only
python setup_traqo.py --step features   # Feature engineering only
python setup_traqo.py --step knowledge  # Build knowledge base only
python setup_traqo.py --step meta       # Train meta-classifier only
python setup_traqo.py --step backtest   # Run backtest only
```

---

## What Gets Generated (not in repo)

These directories are **not** included in the repo because they're large and regenerable:

| Directory | Size | Generated By | Purpose |
|-----------|------|-------------|---------|
| `daily_10yr/` | ~500 MB | `fetch_expanded.py` | Raw 10-year daily OHLCV CSVs |
| `enriched_v2/` | ~800 MB | `feature_engineering.py` | Feature-engineered CSVs (60+ indicators) |
| `rag_documents_v2/` | ~2 GB | `feature_engineering.py` | RAG corpus (543K pattern documents) |
| `models/` | ~5 MB | `meta_classifier.py` | Trained XGBoost model |

Run `python setup_traqo.py` to generate all of them automatically.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11 |
| ML | XGBoost, scikit-learn |
| LLM | Ollama (qwen2.5:7b) |
| Embeddings | Sentence-Transformers |
| Vector Store | ChromaDB |
| RAG Framework | LangChain |
| Data | Yahoo Finance (yfinance) |
| TA Indicators | ta library |
| Book Parsing | PyMuPDF |
| Web UI | Pure Python HTTP server + Tailwind CSS |
| Database | SQLite |
| Scheduling | Windows Task Scheduler |

---

## Dashboards

### RAG Analyzer (port 8522)
- Single-stock deep analysis with Ollama LLM reasoning
- Batch analysis for NIFTY 250 groups (5 groups of 50)
- 1-hour result caching for faster re-queries
- Pattern detection + statistical edge + trade levels

### Paper Trading (port 8521)
- **Overview** — open positions, total P&L, portfolio metrics
- **Open Trades** — live SL/target tracking
- **History** — closed trade journal with entry/exit details
- **Analytics** — win rate, profit factor, drawdown charts
- **Predictions** — latest signals from the statistical predictor
- **System** — config, model status, data freshness

---

## Troubleshooting

<details>
<summary><strong>pip install fails on sentence-transformers / torch</strong></summary>

These are large packages (~2 GB). Ensure you have:
- Stable internet and sufficient disk space (~5 GB for all dependencies)
- On Linux: `sudo apt install build-essential python3-dev`
- On Mac (Apple Silicon): use Python 3.11+ from python.org (not Homebrew)

```bash
# If it times out, try:
pip install --timeout 300 -r requirements.txt
```
</details>

<details>
<summary><strong>Yahoo Finance rate-limits during data download</strong></summary>

Fetching 275 stocks can trigger Yahoo's rate limiter. Symptoms: hangs, empty CSVs, HTTP 429 errors.

```bash
# Option 1: Run the fetch step again (it only downloads missing files)
python setup_traqo.py --step fetch

# Option 2: Wait 10 minutes, then retry
```
</details>

<details>
<summary><strong>Ollama: "ConnectionRefusedError" or "connection error"</strong></summary>

This means Ollama is not running. The RAG Analyzer dashboard requires Ollama as a background service.

```bash
# 1. Install Ollama from https://ollama.com/download
# 2. Start the Ollama service:
ollama serve              # Linux/Mac
# On Windows: Ollama runs automatically after installation

# 3. Pull the model (one-time, ~4.7 GB download):
ollama pull qwen2.5:7b

# 4. Verify it works:
ollama run qwen2.5:7b "Hello"
```

> **Note:** The Paper Trading dashboard and backtesting work fine without Ollama. Only the RAG Analyzer and Streamlit chatbot need it.
</details>

<details>
<summary><strong>setup_traqo.py fails at Step 2 (feature engineering)</strong></summary>

Step 2 is the longest step (~60 min). If it fails:

```bash
# Re-run just this step (it will regenerate missing outputs):
python setup_traqo.py --step features

# Or force a complete re-run:
python setup_traqo.py --step features --force
```
</details>

<details>
<summary><strong>"rag_documents_v2/all_pattern_documents.json not found"</strong></summary>

RAG documents are generated by `feature_engineering.py`. If enriched data exists but RAG docs don't:

```bash
python setup_traqo.py --step rag
# This will detect the missing file and re-run feature_engineering.py
```
</details>

<details>
<summary><strong>Port 8521/8522 already in use</strong></summary>

Another process is using the port. Kill it:

```bash
# Windows:
netstat -ano | findstr "8521"
taskkill /PID <pid> /F

# Linux/Mac:
lsof -i :8521
kill -9 <pid>
```
</details>

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Author

**Prateek Tyagi**

Built as a research project to explore the intersection of RAG, quantitative finance, and candlestick pattern analysis. Traqo demonstrates that systematic, book-grounded trading rules — when filtered by ML and validated via walk-forward testing — can produce edge in Indian equity markets.

---

<p align="center">
  <em>Traqo — RAG-Powered Quantitative Candlestick Intelligence</em>
</p>
