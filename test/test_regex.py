#!/usr/bin/env python3
import re

# Test line from the cleaned output
test_line = "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8 non_hash_mem_region_reg0-63 RW 4.3.16.6 non_hash_mem_region_reg0-63 on page 1016"

# Current regex pattern
multi_segment_pattern = r'^(\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+(?:\s*;\s*\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+)+)\s*(\S+)\s+(\S+)?\s*(.*)?'

print(f"Test line: {test_line}")
print(f"Pattern: {multi_segment_pattern}")

match = re.match(multi_segment_pattern, test_line)
if match:
    print("✓ MATCH FOUND!")
    print(f"  Group 1 (offset): '{match.group(1)}'")
    print(f"  Group 2 (name): '{match.group(2)}'")
    print(f"  Group 3 (type): '{match.group(3)}'")
    print(f"  Group 4 (desc): '{match.group(4)}'")
else:
    print("✗ NO MATCH")

# Test modified pattern if needed
print("\nTesting with space requirement...")
pattern_with_space = r'^(\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+(?:\s*;\s*\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+)+)\s+(\S+)\s+(\S+)?\s*(.*)?'
match2 = re.match(pattern_with_space, test_line)
if match2:
    print("✓ SPACE-REQUIRED PATTERN MATCHES!")
    print(f"  Group 1 (offset): '{match2.group(1)}'")
    print(f"  Group 2 (name): '{match2.group(2)}'")
    print(f"  Group 3 (type): '{match2.group(3)}'")
    print(f"  Group 4 (desc): '{match2.group(4)}'")
else:
    print("✗ SPACE-REQUIRED PATTERN DOESN'T MATCH")