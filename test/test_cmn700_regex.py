#!/usr/bin/env python3
import re

# CMN-700 line
cmn700_line = "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8 non_hash_mem_region_reg0-63 RW 4.3.16.6 non_hash_mem_region_reg0-63 on page 1016"

# Multi-segment pattern
pattern = r'^(\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+(?:\s*;\s*\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+)+)\s*(\S+)\s+(\S+)?\s*(.*)?'

print(f"Testing CMN-700 line:")
print(f"Line: {cmn700_line}")
print(f"Pattern: {pattern}")

match = re.match(pattern, cmn700_line)
if match:
    print("✓ MATCH FOUND!")
    print(f"  Group 1 (offset): '{match.group(1)}'")
    print(f"  Group 2 (name): '{match.group(2)}'")
    print(f"  Group 3 (type): '{match.group(3)}'")
    print(f"  Group 4 (desc): '{match.group(4)}'")
else:
    print("✗ NO MATCH")
    
    # Try to debug by testing parts
    print("\nDebugging:")
    
    # Test the offset part
    offset_pattern = r'^(\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+(?:\s*;\s*\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+)+)'
    offset_match = re.match(offset_pattern, cmn700_line)
    if offset_match:
        print(f"  ✓ Offset part matches: '{offset_match.group(1)}'")
        remaining = cmn700_line[len(offset_match.group(1)):]
        print(f"  Remaining: '{remaining}'")
        
        # Test name extraction from remaining
        name_pattern = r'^\s*(\S+)\s+(\S+)?\s*(.*)?'
        name_match = re.match(name_pattern, remaining)
        if name_match:
            print(f"  ✓ Name part matches:")
            print(f"    Group 1 (name): '{name_match.group(1)}'")
            print(f"    Group 2 (type): '{name_match.group(2)}'")
            print(f"    Group 3 (desc): '{name_match.group(3)}'")
        else:
            print(f"  ✗ Name part doesn't match: '{remaining}'")
    else:
        print("  ✗ Offset part doesn't match")