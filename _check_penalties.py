import json

# Load learned rules to check penalties
with open('feedback/learned_rules.json') as f:
    lr = json.load(f)

print("Learned Rules Summary:")
print("="*70)

# Check horizon penalties
if 'horizon_filter_penalties' in lr:
    print("\nHORIZON PENALTIES (reasons they're filtered):")
    hz_pen = lr['horizon_filter_penalties']
    for key, val in sorted(hz_pen.items()):
        print(f"  {key:>15}: {val}")
else:
    print("\nNo horizon penalties found")

# Check horizon adjustments
if 'horizon_adj' in lr:
    print("\nHORIZON ADJUSTMENTS (win rate adjustments):")
    hz_adj = lr['horizon_adj']
    for key, val in sorted(hz_adj.items()):
        print(f"  {key:>15}: {val}")
else:
    print("\nNo horizon adjustments found")

# Check horizon boosts
if 'horizon_filter_boosts' in lr:
    print("\nHORIZON BOOSTS (reasons they passed):")
    hz_boost = lr['horizon_filter_boosts']
    for key, val in sorted(hz_boost.items()):
        print(f"  {key:>15}: {val}")
else:
    print("\nNo horizon boosts found")
