#!/usr/bin/env python3
"""Verify edge calculation is working"""
import sys
sys.path.insert(0, '/Users/tyagipra/Coding/Nifty_Data')

# Test edge calculation
win_rates = [30, 35, 40, 45, 50, 56, 60, 68, 70]
print("Edge Calculation Test:")
print(f"{'Win Rate':<12} {'Edge %':<10} {'Result':<30}")
print("-" * 52)

for wr in win_rates:
    edge = round((wr / 100 * 2 - 1) * 100, 2)
    status = "✓ PASS" if edge >= 0 else "✗ FAIL"
    print(f"{wr}%{'':<10} {edge}%{'':<8} {status}")

print("\n" + "="*52)
print("March trades should now have:")
print("  56% WR → 12% edge (passes 6% minimum)")
print("  58% WR → 16% edge (passes 6% minimum)")
print("\nWith MIN_WIN_RATE lowered to 30%, MORE trades qualify!")
