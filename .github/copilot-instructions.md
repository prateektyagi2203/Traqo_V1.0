# Traqo Project Context for GitHub Copilot

## Project Overview
Traqo is a **RAG-powered quantitative candlestick intelligence** system for Indian equity markets (NSE). Built in **pure Python** with zero external frameworks for maximum reliability.

## Architecture
- **Trading Engine**: `paper_trader.py` — main orchestrator, runs scans, executes trades
- **Web Dashboard**: `paper_trading_dashboard.py` — HTTP server on port 8521, TailwindCSS CDN
- **RAG Predictor**: `statistical_predictor.py` — loads 147K+ pattern docs from `rag_documents_v2/all_pattern_documents.json`
- **Database**: SQLite at `paper_trades/paper_trades.db` — all trade/position data
- **Knowledge Base**: Lightweight `candlestick_knowledge_base.py` + `data/candlestick_knowledge_base.json` (53 patterns from 12 trading books)

## Production Files (15 core + 1 setup)
- Core engines: `paper_trader.py`, `statistical_predictor.py`, `paper_trading_dashboard.py`
- Configuration: `trading_config.py` (horizons, tiers, thresholds)
- Detection & Features: `pattern_detector.py`, `feature_engineering.py`, `candlestick_knowledge_base.py`
- Risk & Sizing: `regime_detector.py`, `risk_manager.py`, `position_sizing.py`, `position_risk_monitor.py`, `trajectory_health.py`
- Utilities: `trade_logger.py`, `meta_classifier.py`, `fast_stat_predictor.py`
- Setup: `setup_traqo.py` (onboarding wizard)

## Data Structure
- `rag_documents_v2/` — 472K+ JSON pattern documents (used by StatisticalPredictor)
- `feedback/` — RAG learning feedback loop (164 entries, learned rules)
- `paper_trades/` — SQLite DB + position monitoring data
- `models/` — XGBoost & meta classifier pickles
- `data/` — Knowledge base JSON (token-optimized storage)

## Key Patterns
- **Config-driven**: All parameters in `trading_config.py` (horizons, sectors, thresholds)
- **Multi-horizon**: BTST 1d, Swing 3d/5d/10d (h25 disabled)
- **4-layer protection**: Entry filters → Regime detector → Tier-1 risk monitor → RAG feedback
- **RAG feedback loop**: Tracks actual vs predicted outcomes, adjusts pattern penalties/boosts

## Deprecated/Archive
- `archive/` — Old code, ChromaDB experiments, superseded files (NEVER modify)
- `archive/stale/` — Recently archived analysis scripts and markdown docs

## Development Guidelines
- **No external frameworks** (Flask, FastAPI, React) — pure Python + HTTP server
- **SQLite only** — no PostgreSQL, MongoDB, Redis
- **Minimal dependencies** — prefer stdlib, avoid heavy ML libraries except XGBoost/scikit
- **Config-driven** — hardcoded values go in `trading_config.py`
- **Token-conscious** — large data in JSON files, not Python dict literals

## When suggesting changes:
- Check `trading_config.py` first for existing parameters
- Consider RAG feedback loop impact (will this break learning?)
- Prefer modifications over rewrites (preserve trading history)
- Test with existing `paper_trades.db` data
- Maintain backward compatibility with dashboard/API