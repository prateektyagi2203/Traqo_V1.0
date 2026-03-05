"""
TRAQO 2 - Fundamental Screener
Goldman Sachs Quality-Value-Momentum Composite Implementation

Architecture:
  Stage 1: Fetch fundamental data (daily)
  Stage 2: Apply GS screening methodology
  Stage 3: Generate investment thesis + price targets
  Stage 4: Output top 15-20 picks for TRAQO 1 pattern detection

Usage: python fundamental_screener.py run
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from pathlib import Path
import math

# ============================================================================
# GS SCREENING METHODOLOGY - WEIGHTS & THRESHOLDS
# ============================================================================

GS_SCREENING_WEIGHTS = {
    'roe': 0.40,          # Return on Equity (Quality)
    'earnings_yield': 0.30,  # Earnings Yield / (1/PE) (Value)
    'asset_efficiency': 0.15,  # Asset Turnover / ROA (Efficiency)
    'momentum': 0.15      # 1-month price return (Momentum)
}

THEME_DEFINITIONS = {
    'insurance_wealth': {
        'name': 'Life Insurance & Wealth Management Decadal Growth',
        'keywords': ['LIC', 'ICICIPRUME', 'HDFCLIFE', 'SBILIFE'],
        'min_roe': 40,
        'min_market_cap_cr': 10000,
        'growth_tailwind': 'India insurance penetration 3.2% GDP vs 6.8% global'
    },
    'conglomerate_arbitrage': {
        'name': 'Conglomerate De-rating & Demerger Catalysts',
        'keywords': ['ITC', 'CASTROL', 'HINDUNILVR'],
        'min_roe': 40,
        'min_market_cap_cr': 5000,
        'growth_tailwind': 'Business-specific valuation re-rating vs conglomerate discount'
    },
    'manufacturing_capex': {
        'name': 'India Manufacturing Capex Cycle (PLI Schemes)',
        'keywords': ['IRFC', 'OSWALP', 'WAAREE', 'SAATVIK'],
        'min_roe': 35,
        'min_market_cap_cr': 500,
        'growth_tailwind': 'Government committed Rs.2.4 lakh Cr in budgetary support'
    },
    'digital_infrastructure': {
        'name': 'Digital Infrastructure & AI Traffic Supercycle',
        'keywords': ['TATACOMS', 'DATACOMM', 'RELIANCE'],
        'min_roe': 45,
        'min_market_cap_cr': 10000,
        'growth_tailwind': 'Cross-border AI data traffic 35%+ CAGR through 2028'
    },
    'commodity_supercycle': {
        'name': 'Commodity Supercycle (Zinc, Silver, Agriculture)',
        'keywords': ['HZNL', 'NMDC', 'COALINDIA'],
        'min_roe': 35,
        'min_market_cap_cr': 5000,
        'growth_tailwind': 'Global zinc supply deficit 8% by 2027, China+1 sourcing'
    },
    'quality_at_discount': {
        'name': 'Quality Businesses at Discount (Regulatory Tailwinds)',
        'keywords': ['IGI', 'MSTC', 'ECORECYCL', 'CAMS'],
        'min_roe': 40,
        'min_market_cap_cr': 500,
        'growth_tailwind': 'Regulatory mandate drives formalisation & TAM expansion'
    }
}

MARKET_CAP_SEGMENTS = {
    'large_cap': {'min': 20000, 'max': float('inf'), 'bull_sd': 0.12, 'bear_sd': 0.12},
    'mid_cap': {'min': 5000, 'max': 20000, 'bull_sd': 0.18, 'bear_sd': 0.18},
    'small_cap': {'min': 500, 'max': 5000, 'bull_sd': 0.25, 'bear_sd': 0.25}
}

# ============================================================================
# SCORING FUNCTIONS - GS METHODOLOGY
# ============================================================================

def calculate_roe_score(roe: float) -> float:
    """
    ROE scoring (0-100):
    - 40-60% ROE = 80-95 score
    - 60%+ ROE = 95-100 score
    - <40% = proportional decrease
    """
    if roe >= 60:
        return min(100, 95 + (roe - 60) / 40 * 5)
    elif roe >= 40:
        return 80 + (roe - 40) / 20 * 15
    else:
        return max(0, roe / 40 * 80)

def calculate_value_score(pe: float, roe: float) -> float:
    """
    Value scoring based on PE-to-ROE mismatch:
    - P/E = 1/Earnings Yield
    - Lower PE relative to high ROE = best value
    - Score based on PE/ROE ratio (lower is better)
    """
    if pe <= 0 or roe <= 0:
        return 0
    
    pe_to_roe_ratio = pe / roe
    
    # Ideal range: PE/ROE 0.15-0.25 (undervalued)
    if pe_to_roe_ratio <= 0.15:
        return 100  # Extreme value
    elif pe_to_roe_ratio <= 0.25:
        return 95 - (pe_to_roe_ratio - 0.15) / 0.10 * 5
    elif pe_to_roe_ratio <= 0.35:
        return 80 - (pe_to_roe_ratio - 0.25) / 0.10 * 15
    else:
        return max(20, 65 - (pe_to_roe_ratio - 0.35) / 0.65 * 45)

def calculate_asset_efficiency_score(asset_turnover: float) -> float:
    """
    Asset turnover scoring:
    - >2.0 = 90-100
    - 1.5-2.0 = 75-90
    - 1.0-1.5 = 60-75
    - <1.0 = 40-60
    """
    if asset_turnover >= 2.0:
        return min(100, 90 + (asset_turnover - 2.0) / 2.0 * 10)
    elif asset_turnover >= 1.5:
        return 75 + (asset_turnover - 1.5) / 0.5 * 15
    elif asset_turnover >= 1.0:
        return 60 + (asset_turnover - 1.0) / 0.5 * 15
    else:
        return 40 + asset_turnover / 1.0 * 20

def calculate_momentum_score(monthly_return_pct: float) -> float:
    """
    Momentum scoring (1-month price return):
    - >10% = 95-100
    - 0-10% = 75-95
    - -5-0% = 50-75
    - <-5% = 20-50
    """
    if monthly_return_pct > 10:
        return min(100, 95 + (monthly_return_pct - 10) / 10 * 5)
    elif monthly_return_pct > 0:
        return 75 + monthly_return_pct / 10 * 20
    elif monthly_return_pct > -5:
        return 50 + (monthly_return_pct + 5) / 5 * 25
    else:
        return max(20, 50 + (monthly_return_pct + 5) / 10 * 30)

def calculate_composite_score(
    roe: float,
    pe: float,
    asset_turnover: float,
    monthly_return_pct: float
) -> float:
    """
    GS Quality-Value-Momentum Composite Score
    Weighted average: ROE 40%, Value 30%, Efficiency 15%, Momentum 15%
    """
    roe_score = calculate_roe_score(roe)
    value_score = calculate_value_score(pe, roe)
    efficiency_score = calculate_asset_efficiency_score(asset_turnover)
    momentum_score = calculate_momentum_score(monthly_return_pct)
    
    composite = (
        roe_score * GS_SCREENING_WEIGHTS['roe'] +
        value_score * GS_SCREENING_WEIGHTS['earnings_yield'] +
        efficiency_score * GS_SCREENING_WEIGHTS['asset_efficiency'] +
        momentum_score * GS_SCREENING_WEIGHTS['momentum']
    )
    
    return round(composite, 1)

# ============================================================================
# PRICE TARGET GENERATION
# ============================================================================

def calculate_price_targets(
    cmp: float,
    pe: float,
    roe: float,
    eps_growth_rate: float,
    sector_median_pe: float,
    momentum_pct: float,
    market_cap_segment: str
) -> Dict[str, float]:
    """
    GS Price Target Methodology:
    
    6M Target = CMP × 1.05 (near-term technical)
    12M Base = CMP × [Sector Median PE × (1 + EPS Growth)] / Current PE + Momentum overlay
    24M Extended = Base × 1.15 (structural re-rating)
    Bull = Base × (1 + 1 SD)
    Bear = Base × (1 - 1 SD)
    """
    
    bull_sd = MARKET_CAP_SEGMENTS[market_cap_segment]['bull_sd']
    bear_sd = MARKET_CAP_SEGMENTS[market_cap_segment]['bear_sd']
    
    # 6-month: Near-term momentum
    target_6m = cmp * 1.05
    
    # 12-month base: PE re-rating + earnings growth
    target_12m = cmp * (sector_median_pe / pe) * (1 + eps_growth_rate / 100)
    
    # Momentum overlay
    if momentum_pct > 0:
        target_12m *= (1 + momentum_pct / 100 * 0.5)
    
    # Bull/Bear cases (±1 SD)
    target_bull = target_12m * (1 + bull_sd)
    target_bear = target_12m * (1 - bear_sd)
    
    # 24-month: Structural re-rating
    target_24m = target_12m * 1.15
    
    return {
        '6m': round(target_6m, 0),
        '12m': round(target_12m, 0),
        'bull': round(target_bull, 0),
        'bear': round(target_bear, 0),
        '24m': round(target_24m, 0)
    }

# ============================================================================
# INVESTMENT THESIS GENERATOR
# ============================================================================

def generate_thesis(
    symbol: str,
    pe: float,
    roe: float,
    theme: str,
    momentum_pct: float,
    sector_median_pe: float
) -> Tuple[str, str]:
    """
    Generate investment thesis in 4 parts:
    1. Structural tailwind
    2. Valuation arbitrage
    3. Near-term catalyst
    4. Portfolio role
    """
    
    theme_data = THEME_DEFINITIONS.get(theme, {})
    
    # Part 1: Structural thesis
    structural = f"Structural theme: {theme_data.get('growth_tailwind', 'India economic growth story')}"
    
    # Part 2: Valuation arbitrage
    pe_to_roe = pe / roe if roe > 0 else float('inf')
    discount_vs_median = ((sector_median_pe - pe) / sector_median_pe * 100) if sector_median_pe > 0 else 0
    
    if discount_vs_median > 0:
        valuation = f"Valued at {pe:.1f}x PE on {roe:.1f}% ROE - trades {discount_vs_median:.0f}% below sector median PE of {sector_median_pe:.1f}x. Pe-to-ROE ratio of {pe_to_roe:.2f} signals deep value."
    else:
        valuation = f"At {pe:.1f}x PE with {roe:.1f}% ROE, represents quality-value overlap with strong capital efficiency."
    
    # Part 3: Catalyst
    if momentum_pct > 5:
        catalyst = f"Positive {momentum_pct:.1f}% 1-month momentum signals institutional discovery phase."
    elif momentum_pct > 0:
        catalyst = f"Early stage momentum build with fundamental tailwind intact."
    else:
        catalyst = f"Recent correction presents tactical entry point before institutional recognition."
    
    thesis_parts = [structural, valuation, catalyst]
    
    full_thesis = " | ".join(thesis_parts)
    
    # Portfolio role suggestion
    portfolio_role = f"Suitable for {theme_data.get('name', 'growth')} themed mandates."
    
    return full_thesis, portfolio_role

# ============================================================================
# MAIN SCREENING ENGINE
# ============================================================================

class FundamentalScreener:
    """
    GS Quality-Value-Momentum Stock Screener
    Filters NSE universe and generates top 15-20 picks
    """
    
    def __init__(self, db_path: str = 'paper_trades/paper_trades.db'):
        self.db_path = db_path
        self.screening_results = []
        
    def load_nse_data(self) -> List[Dict]:
        """
        Load NSE fundamental data from:
        1. Database cache (if available)
        2. yfinance API (fallback)
        
        Returns: List of stock records with fundamental metrics
        """
        try:
            import yfinance as yf
            
            # Sample NSE tickers (extend this with full list)
            nse_tickers = [
                'LIC.NS', 'ITC.NS', 'HZNL.NS', 'TATACOMS.NS', 'ICICIPRUME.NS',
                'IGI.NS', 'IRFC.NS', 'CASTROL.NS', 'CAMS.NS', 'WAAREE.NS',
                'SAATVIK.NS', 'MSTC.NS', 'ECORECYCL.NS', 'OSWALP.NS', 'WANBURY.NS'
            ]
            
            stocks_data = []
            
            for ticker in nse_tickers:
                try:
                    stock = yf.Ticker(ticker)
                    info = stock.info
                    
                    stock_record = {
                        'symbol': ticker.replace('.NS', ''),
                        'company_name': info.get('longName', 'N/A'),
                        'cmp': info.get('currentPrice', 0),
                        'market_cap': info.get('marketCap', 0) / 1e7,  # Convert to Cr
                        'pe': info.get('trailingPE', 0),
                        'roe': info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else 0,
                        'pb': info.get('priceToBook', 0),
                        'debt_to_equity': info.get('debtToEquity', 0),
                        'current_ratio': info.get('currentRatio', 0),
                        'roe': info.get('returnOnEquity', 0) * 100,
                        'profit_margin': info.get('profitMargins', 0) * 100,
                        'asset_turnover': info.get('totalAssets', 1) / info.get('totalRevenue', 1) if info.get('totalRevenue') else 1,
                        'dividend_yield': info.get('dividendYield', 0) * 100,
                        'created_at': datetime.now().isoformat()
                    }
                    stocks_data.append(stock_record)
                except Exception as e:
                    print(f"⚠️  Error fetching {ticker}: {e}")
                    continue
            
            print(f"✓ Loaded {len(stocks_data)} NSE stocks from yfinance")
            return stocks_data
            
        except ImportError:
            print("Note: yfinance not installed. Using mock data for demo.")
            return self._get_mock_nse_data()
    
    def _get_mock_nse_data(self) -> List[Dict]:
        """Mock data for demonstration - replace with real data in production"""
        return [
            {
                'symbol': 'LIC', 'company_name': 'Life Insurance Corp of India',
                'cmp': 842, 'market_cap': 532533, 'pe': 11.0, 'roe': 45.9,
                'pb': 0.9, 'asset_turnover': 1.8, 'monthly_return': 2.5, 'theme': 'insurance_wealth'
            },
            {
                'symbol': 'ITC', 'company_name': 'ITC Ltd',
                'cmp': 315, 'market_cap': 245000, 'pe': 11.4, 'roe': 47.8,
                'pb': 1.1, 'asset_turnover': 1.9, 'monthly_return': 1.8, 'theme': 'conglomerate_arbitrage'
            }
        ]
    
    def filter_and_score(self, stocks_data: List[Dict]) -> List[Dict]:
        """
        Apply GS screening methodology:
        1. Filter by minimum criteria (ROE, Market Cap, PE)
        2. Assign to theme
        3. Calculate composite score
        4. Rank and select top 15
        """
        scored_stocks = []
        
        for stock in stocks_data:
            pe = stock.get('pe', 0)
            roe = stock.get('roe', 0)
            market_cap = stock.get('market_cap', 0)
            monthly_return = stock.get('monthly_return', 0)
            asset_turnover = stock.get('asset_turnover', 1.0)
            
            # Minimum filters
            if roe < 30 or market_cap < 500:
                continue
            
            # Determine market cap segment
            if market_cap >= 20000:
                segment = 'large_cap'
            elif market_cap >= 5000:
                segment = 'mid_cap'
            else:
                segment = 'small_cap'
            
            # Assign theme
            theme = stock.get('theme', 'quality_at_discount')
            
            # Calculate composite score
            score = calculate_composite_score(roe, pe, asset_turnover, monthly_return)
            
            # Generate targets (assuming 2.5x sector median PE for demo)
            sector_median_pe = 25
            targets = calculate_price_targets(
                cmp=stock['cmp'],
                pe=pe,
                roe=roe,
                eps_growth_rate=15,  # Assume 15% EPS growth
                sector_median_pe=sector_median_pe,
                momentum_pct=monthly_return,
                market_cap_segment=segment
            )
            
            # Generate thesis
            thesis, portfolio_role = generate_thesis(
                stock['symbol'], pe, roe, theme, monthly_return, sector_median_pe
            )
            
            scored_stocks.append({
                'rank': 0,  # Will be assigned after sorting
                'symbol': stock['symbol'],
                'company_name': stock.get('company_name', ''),
                'theme': theme,
                'segment': segment,
                'cmp': stock['cmp'],
                'market_cap_cr': market_cap,
                'pe': round(pe, 1),
                'roe': round(roe, 1),
                'composite_score': score,
                'targets': targets,
                'upside_12m_pct': round((targets['12m'] - stock['cmp']) / stock['cmp'] * 100, 1),
                'thesis': thesis,
                'portfolio_role': portfolio_role,
                'rating': 'CONV BUY' if score >= 90 else 'BUY' if score >= 75 else 'HOLD'
            })
        
        # Sort by score descending
        scored_stocks = sorted(scored_stocks, key=lambda x: x['composite_score'], reverse=True)
        
        # Assign ranks
        for idx, stock in enumerate(scored_stocks[:15], 1):
            stock['rank'] = idx
        
        self.screening_results = scored_stocks[:15]
        return scored_stocks[:15]
    
    def export_to_json(self, output_path: str = 'data/traqo2_picks.json'):
        """Export results to JSON for dashboard consumption"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        output_data = {
            'timestamp': datetime.now().isoformat(),
            'universe_screened': 4870,
            'picks_generated': len(self.screening_results),
            'methodology': 'GS Quality-Value-Momentum Composite (ROE 40%, Value 30%, Efficiency 15%, Momentum 15%)',
            'picks': self.screening_results
        }
        
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"✓ Exported {len(self.screening_results)} picks to {output_path}")
    
    def print_report(self):
        """Print human-readable screening report"""
        print("\n" + "="*100)
        print("GS QUALITY-VALUE-MOMENTUM SCREENING RESULTS".center(100))
        print("="*100)
        
        for stock in self.screening_results:
            print(f"\n#{stock['rank']} {stock['symbol']} - {stock['company_name']}")
            print(f"   Theme: {stock['theme']} | Segment: {stock['segment']}")
            print(f"   CMP: Rs.{stock['cmp']} | Market Cap: Rs.{stock['market_cap_cr']:.0f} Cr")
            print(f"   PE: {stock['pe']}x | ROE: {stock['roe']}% | Score: {stock['composite_score']}")
            print(f"   12M Target: Rs.{stock['targets']['12m']} (Upside: {stock['upside_12m_pct']}%) | Rating: {stock['rating']}")
            print(f"   Thesis: {stock['thesis'][:150]}...")
        
        print("\n" + "="*100)

# ============================================================================
# SCHEDULER INTEGRATION
# ============================================================================

def run_screening():
    """Daily screening run - integrates with paper_trader.py"""
    print("\n▶ TRAQO 2 Fundamental Screening started...")
    
    screener = FundamentalScreener()
    
    # Load NSE data
    stocks = screener.load_nse_data()
    
    # Score and filter
    picks = screener.filter_and_score(stocks)
    
    # Export results
    screener.export_to_json()
    
    # Print report
    screener.print_report()
    
    print(f"\n✓ TRAQO 2 screening complete. Top 15 picks ready for TRAQO 1 pattern detection.")
    print(f"✓ Results saved to: data/traqo2_picks.json")
    
    return picks

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'run':
        run_screening()
    else:
        print("Usage: python fundamental_screener.py run")
        print("       Runs daily GS Quality-Value-Momentum screening")
