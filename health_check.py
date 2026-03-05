#!/usr/bin/env python3
"""
🏥 TRAQO HEALTH CHECK
Comprehensive diagnostic script to verify live prices are working
Run this BEFORE starting the dashboard to catch issues early
"""

def main():
    print("🏥 TRAQO HEALTH CHECK")
    print("=" * 60)
    
    # Test 1: yfinance import
    print("\n1️⃣ Testing yfinance import...")
    try:
        import yfinance as yf
        print(f"   ✅ SUCCESS: yfinance v{yf.__version__} imported")
    except ImportError as e:
        print(f"   ❌ FAILED: {e}")
        print("   🔧 FIX: pip install yfinance")
        return False
    
    # Test 2: Sample price fetch
    print("\n2️⃣ Testing live price fetch...")
    try:
        data = yf.download("SBIN.NS", period="1d", progress=False)
        if not data.empty:
            price = float(data['Close'].iloc[-1])
            print(f"   ✅ SUCCESS: SBIN.NS = ₹{price:.2f}")
        else:
            print("   ❌ FAILED: Empty data returned")
            return False
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    # Test 3: Database connectivity
    print("\n3️⃣ Testing database connectivity...")
    try:
        import sqlite3
        conn = sqlite3.connect('paper_trades/paper_trades.db')
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status = 'OPEN'")
        open_count = cursor.fetchone()[0]
        conn.close()
        print(f"   ✅ SUCCESS: {open_count} open trades found")
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    # Test 4: Dashboard function test
    print("\n4️⃣ Testing dashboard live price function...")
    try:
        from paper_trading_dashboard import fetch_live_prices
        test_tickers = ['SBIN.NS', 'HDFCBANK.NS']
        prices = fetch_live_prices(test_tickers)
        if prices:
            print(f"   ✅ SUCCESS: Got {len(prices)} prices")
            for ticker, price in list(prices.items())[:2]:
                print(f"      {ticker}: ₹{price:.2f}")
        else:
            print("   ❌ FAILED: No prices returned")
            return False
    except Exception as e:
        print(f"   ❌ FAILED: {e}")
        return False
    
    print("\n" + "=" * 60)
    print("🎉 ALL TESTS PASSED!")
    print("✅ Live prices should work perfectly in the dashboard")
    print("🚀 You can now safely start the dashboard with start_dashboard.bat")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        print("\n💡 RECOMMENDATIONS:")
        print("1. Ensure you're in the Traqo directory")
        print("2. Activate virtual environment: .venv\\Scripts\\activate.bat")
        print("3. Install yfinance: pip install yfinance")
        print("4. Run this test again until all checks pass")
    
    input("\nPress Enter to continue...")