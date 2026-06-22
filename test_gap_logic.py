#!/usr/bin/env python3
gap = -2.5

# Test the logic
if gap >= 10:
    gap_msg = "working_msg"
    gap_subtitle = "Real outperforms"
elif gap >= 5:
    gap_msg = "monitor_msg"
    gap_subtitle = "Real outperforms"
elif gap > 0:
    gap_msg = "horizon_msg_1"
    gap_subtitle = "Real slightly ahead"
else:
    gap_msg = "horizon_msg_2"
    gap_subtitle = "Shadow outperforms"

print(f"gap={gap}")
print(f"gap_msg={gap_msg}")
print(f"gap_subtitle={gap_subtitle}")
print(f"Interpretation conditional: {'Filtered signals underperform' if gap >= 0 else 'Real trades underperform'}")
