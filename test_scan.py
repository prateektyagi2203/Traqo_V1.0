#!/usr/bin/env python3
"""Quick test scan to verify all fixes work"""
import sys
from datetime import date
from paper_trader import PaperTrader

pt = PaperTrader()
result = pt.scan_preview(date.today())

print("\n" + "="*80)
print("SCAN RESULTS", date.today())
print("="*80)
print(f"✓ Total signals found: {result['total_signals']}")
print(f"✓ Qualifying signals: {result['qualifying']}")
print(f"✗ Filtered out: {result['filtered_out']}")

if result.get('skip_reason_summary'):
    print("\nFILTER BREAKDOWN:")
    for reason, count in sorted(result['skip_reason_summary'].items(), key=lambda x: -x[1])[:5]:
        print(f"  - {reason}: {count}")

if result['qualifying'] > 0:
    print(f"\n✅ SUCCESS: {result['qualifying']} signals ready for trading!")
else:
    print("\n⚠️  No qualifying signals found")
