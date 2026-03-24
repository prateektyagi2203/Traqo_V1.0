#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Safe Dashboard Startup — Ensures all dependencies installed before running
"""
import subprocess
import sys
import os

def ensure_dependencies():
    """Ensure all dependencies from requirements.txt are installed."""
    print("🔍 Checking dependencies...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode == 0:
            print("✅ All dependencies verified/installed")
            return True
        else:
            print(f"⚠️ Warning during dependency install:\n{result.stderr}")
            return True  # Continue anyway
    except Exception as e:
        print(f"⚠️ Could not auto-install dependencies: {e}")
        print("   Please run manually: pip install -r requirements.txt")
        return True  # Continue anyway

def start_dashboard():
    """Start the paper trading dashboard."""
    print("\n🚀 Starting Paper Trading Dashboard...")
    print("📍 Dashboard will be available at: http://localhost:8521\n")
    
    try:
        # Import and run dashboard in same process
        from paper_trading_dashboard import run_server
        run_server()
    except Exception as e:
        print(f"❌ Dashboard error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    ensure_dependencies()
    start_dashboard()
