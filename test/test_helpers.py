#!/usr/bin/env python3
import re

def parse_array_indices(offset_str):
    """Extract array indices from patterns like {0-23} or {24-151}"""
    indices = []
    for match in re.finditer(r'\{(\d+)-(\d+)\}', offset_str):
        start, end = int(match.group(1)), int(match.group(2))
        indices.append((start, end))
    return indices

def extract_segment_offset(offset_str, segment_index):
    """Extract specific segment offset from multi-segment pattern"""
    segments = offset_str.split(';')
    if segment_index < len(segments):
        return segments[segment_index].strip()
    return offset_str

def generate_segmented_register_name(base_name, start_idx, end_idx):
    """Generate segmented register name like non_hash_mem_region_reg0-23"""
    # Remove existing range suffix if present
    base_clean = re.sub(r'\d+-\d+$', '', base_name)
    return f"{base_clean}{start_idx}-{end_idx}"

# Test data
offset = "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8"
name = "non_hash_mem_region_reg0-63"
type_token = "RW"
desc = "4.3.16.6 non_hash_mem_region_reg0-63 on page 1016"

print(f"Testing with offset: {offset}")
print(f"Name: {name}")

# Parse array indices for segment generation
indices = parse_array_indices(offset)
print(f"Parsed indices: {indices}")

if len(indices) > 1:
    print("Generating separate entries for each segment:")
    # Generate separate entries for each segment
    for idx, (start, end) in enumerate(indices):
        segment_offset = extract_segment_offset(offset, idx)
        segment_name = generate_segmented_register_name(name, start, end)
        
        print(f"  Segment {idx}: offset='{segment_offset}', name='{segment_name}'")
        print(f"    Full entry: table=current_table, offset='{segment_offset}', name='{segment_name}', type='{type_token}', description='{desc}'")
else:
    print("Single segment - use as-is")