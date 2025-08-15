#!/usr/bin/env python3
"""
L2 CSV Optimization Script
Transforms L1 CSV outputs into optimized L2 formats with better structure and array handling.
"""

import pandas as pd
import re
import csv
from pathlib import Path
import sys

def extract_reg_block_name(table_str):
    """
    Extract register block name from table header.
    Input: "Table 8-6: por_apb_cfg register summary"
    Output: "por_apb_cfg_regs"
    """
    match = re.match(r'^Table\s+\d+-\d+:\s+(.+?)\s+register\s+summary', table_str, re.IGNORECASE)
    if match:
        return match.group(1) + '_regs'
    
    # For attributes tables
    match = re.match(r'^Table\s+\d+-\d+:\s+(.+?)\s+attributes', table_str, re.IGNORECASE)
    if match:
        return match.group(1)
    
    return table_str  # Fallback

def check_contiguous_segments(offset_pattern):
    """
    Check if multi-segment offset pattern is actually contiguous.
    Example: {0-4} 0xF80 : 0xFA0 {5-31} 0x6028 : 0x60F8
    
    Returns: (is_contiguous, segments)
    """
    segments = re.findall(r'\{(\d+)-(\d+)\}\s*(0x[0-9A-Fa-f]+)\s*:\s*(0x[0-9A-Fa-f]+)', offset_pattern)
    
    if len(segments) <= 1:
        return True, segments
    
    for i in range(len(segments) - 1):
        curr_start_idx = int(segments[i][0])
        curr_end_idx = int(segments[i][1])
        curr_start_addr = int(segments[i][2], 16)
        curr_end_addr = int(segments[i][3], 16)
        
        next_start_idx = int(segments[i+1][0])
        next_start_addr = int(segments[i+1][2], 16)
        
        # Check if indices are contiguous
        if next_start_idx != curr_end_idx + 1:
            return False, segments
        
        # Calculate stride and check if addresses are contiguous
        count = curr_end_idx - curr_start_idx + 1
        if count > 0:
            stride = (curr_end_addr - curr_start_addr + 8) // count  # +8 for inclusive range
            expected_next = curr_end_addr + stride
            
            # Allow small tolerance for alignment
            if abs(next_start_addr - expected_next) > 0x8:
                return False, segments
    
    return True, segments

def simplify_single_element_offset(offset, array_size):
    """
    Convert single-element array offsets to simple form.
    0x23A8 : 0x23A8 -> 0x23a8
    {0-0} 0x23A8 : 0x23A8 -> 0x23a8
    """
    if array_size == 1:
        # Remove index prefix if present
        offset = re.sub(r'^\{[0-9]+-[0-9]+\}\s*', '', offset)
        
        # Check for X : X pattern
        match = re.match(r'^(0x[0-9A-Fa-f]+)\s*:\s*(0x[0-9A-Fa-f]+)$', offset)
        if match and match.group(1).lower() == match.group(2).lower():
            return match.group(1).lower()  # Return single offset in lowercase
        
        # Also handle simple ranges where start == end
        if ':' in offset:
            parts = offset.split(':')
            if len(parts) == 2 and parts[0].strip().lower() == parts[1].strip().lower():
                return parts[0].strip().lower()
    
    return offset

def determine_register_size(register_name, attributes_df):
    """
    Determine if register is 32-bit or 64-bit based on max bit position.
    Returns 32 if max bit <= 31, otherwise 64.
    """
    reg_fields = attributes_df[attributes_df['register_name'] == register_name]
    max_bit = 0
    
    for _, row in reg_fields.iterrows():
        bits = str(row['bits'])
        # Extract all numbers from the bits string
        numbers = re.findall(r'\d+', bits)
        if numbers:
            current_max = max(int(n) for n in numbers)
            max_bit = max(max_bit, current_max)
    
    # Return 32 if max bit is <= 31, otherwise 64
    return 32 if max_bit <= 31 else 64

def calculate_register_sizes_from_l1(input_csv):
    """
    Calculate register sizes from L1 attributes INCLUDING Reserved fields.
    Returns a dictionary mapping register_name -> size (32 or 64).
    """
    print(f"  Calculating register sizes from L1 (including Reserved fields)...")
    df = pd.read_csv(input_csv)
    
    register_sizes = {}
    register_has_reserved_21 = {}  # Track if register has Reserved bit 21
    
    for _, row in df.iterrows():
        # Parse table header to get register name
        table_id, register_name = parse_table_header(row['table'])
        
        # Get bit range and field name
        bits = str(row['bits'])
        field_name = str(row.get('name', '')).lower()
        
        # Check if this is Reserved bit 21 (single bit)
        if bits == '21' and 'reserved' in field_name:
            register_has_reserved_21[register_name] = True
        
        # Extract all numbers from the bits string
        numbers = re.findall(r'\d+', bits)
        if numbers:
            max_bit = max(int(n) for n in numbers)
            
            # Update the maximum bit for this register
            if register_name not in register_sizes:
                register_sizes[register_name] = 0
            register_sizes[register_name] = max(register_sizes[register_name], max_bit)
    
    # Convert max bits to register sizes (32 or 64)
    # WORKAROUND: If a register has Reserved bit 21 as its highest bit,
    # assume there are missing Reserved[63:22] or Reserved[31:22] fields
    for reg_name in register_sizes:
        max_bit = register_sizes[reg_name]
        
        # Check if this register likely has missing upper Reserved bits
        if max_bit == 21 and register_has_reserved_21.get(reg_name, False):
            # Assume 64-bit register with missing Reserved[63:22]
            print(f"    WARNING: {reg_name} has Reserved bit 21 as highest - assuming 64-bit (missing Reserved[63:22])")
            register_sizes[reg_name] = 64
        else:
            register_sizes[reg_name] = 32 if max_bit <= 31 else 64
    
    # Print some statistics
    size_32 = sum(1 for size in register_sizes.values() if size == 32)
    size_64 = sum(1 for size in register_sizes.values() if size == 64)
    print(f"    Found {len(register_sizes)} registers: {size_32} are 32-bit, {size_64} are 64-bit")
    
    return register_sizes

def parse_array_info(name, preserve_full_name=False):
    """
    Parse array information from register name.
    Returns: (base_name, name_array_size, array_indices)
    
    Args:
        name: The register name to parse
        preserve_full_name: If True, keeps the full name with array indices
    """
    # Pattern: grp0-4_add_mask, reg0-31, region0-127, reg_0-31
    match = re.search(r'(.+?)(\d+)-(\d+)(.*)$', name)
    if match:
        prefix = match.group(1).rstrip('_-')
        start_idx = int(match.group(2))
        end_idx = int(match.group(3))
        suffix = match.group(4)
        
        if preserve_full_name:
            # Keep the full name for display
            base_name = name
        else:
            # Strip indices for matching/grouping
            base_name = prefix + suffix
        
        array_size = end_idx - start_idx + 1
        array_indices = f"{start_idx}-{end_idx}"
        
        return base_name, array_size, array_indices
    
    return name, 1, ""

def process_register_entry(row):
    """
    Process a single register entry and potentially split it.
    Returns list of processed entries.
    """
    name = row['name']
    offset = row['offset']
    results = []
    
    # Parse array info from name twice - once for processing, once for display
    stripped_name, name_array_size, name_indices = parse_array_info(name, preserve_full_name=False)
    full_name, _, _ = parse_array_info(name, preserve_full_name=True)
    
    # Check for multi-segment offsets
    segments = re.findall(r'\{(\d+)-(\d+)\}\s*(0x[0-9A-Fa-f]+)\s*:\s*(0x[0-9A-Fa-f]+)', offset)
    
    if len(segments) > 1:
        # Check if segments are contiguous
        is_contiguous, _ = check_contiguous_segments(offset)
        
        if not is_contiguous:
            # Split into separate entries for non-contiguous segments
            # Match the segments with the name indices if available
            # For multi-segment non-contiguous arrays, split them
            # But first check if this is a case where the same offsets have different names
            # (like grp0-4 and grp5-31 with same offset pattern)
            if '-' in name and 'grp' in name:
                # Special handling for split register groups (e.g., grp0-4 and grp5-31)
                # The name tells us which segment this entry represents
                name_match = re.search(r'grp(\d+)-(\d+)', name)
                if name_match:
                    grp_start = int(name_match.group(1))
                    grp_end = int(name_match.group(2))
                    
                    # Find the matching segment
                    for seg_match in segments:
                        seg_start = int(seg_match[0])
                        seg_end = int(seg_match[1])
                        
                        # Check if this segment matches the group range
                        if seg_start == grp_start:
                            array_size = seg_end - seg_start + 1
                            new_entry = row.copy()
                            new_entry['offset'] = f"{seg_match[2]} : {seg_match[3]}"
                            new_entry['array_size'] = array_size
                            new_entry['array_indices'] = f"{seg_start}-{seg_end}"
                            new_entry['name'] = name  # Use original full name
                            
                            # Simplify if single element
                            if array_size == 1:
                                new_entry['offset'] = simplify_single_element_offset(new_entry['offset'], 1)
                                new_entry['array_indices'] = str(seg_start)
                            
                            results.append(new_entry)
                            break
                    
                    # If no exact match found, it might be a different naming pattern
                    if not results:
                        # Fall through to default splitting
                        pass
                else:
                    # Fall through to default splitting
                    pass
            
            # Default splitting for all non-contiguous multi-segment arrays
            if not results:
                # Default splitting for non-group arrays
                for seg_match in segments:
                    start_idx, end_idx, start_addr, end_addr = seg_match
                    seg_start = int(start_idx)
                    seg_end = int(end_idx)
                    array_size = seg_end - seg_start + 1
                    
                    # Create new entry for this segment
                    new_entry = row.copy()
                    new_entry['offset'] = f"{start_addr} : {end_addr}"
                    new_entry['array_size'] = array_size
                    new_entry['array_indices'] = f"{seg_start}-{seg_end}"
                    new_entry['name'] = name  # Use original full name
                    
                    # Simplify if single element
                    if array_size == 1:
                        new_entry['offset'] = simplify_single_element_offset(new_entry['offset'], 1)
                        new_entry['array_indices'] = str(seg_start)
                    
                    results.append(new_entry)
        else:
            # Keep as single entry with full range
            row['array_size'] = name_array_size
            row['array_indices'] = name_indices
            row['name'] = full_name
            results.append(row)
    elif segments:
        # Single segment with index prefix
        seg = segments[0]
        start_idx = int(seg[0])
        end_idx = int(seg[1])
        array_size = end_idx - start_idx + 1
        
        row['array_size'] = array_size
        row['array_indices'] = f"{start_idx}-{end_idx}" if array_size > 1 else str(start_idx)
        row['name'] = full_name
        row['offset'] = simplify_single_element_offset(offset, array_size)
        results.append(row)
    else:
        # Simple offset or range without index prefix
        row['array_size'] = name_array_size
        row['array_indices'] = name_indices
        row['name'] = full_name
        
        # Simplify single element offsets
        row['offset'] = simplify_single_element_offset(row['offset'], name_array_size)
        results.append(row)
    
    return results

def optimize_register_summaries(input_csv, output_csv):
    """
    Transform register summaries CSV with array handling.
    """
    print(f"Processing {input_csv}...")
    df = pd.read_csv(input_csv)
    
    # Process each row and collect results
    all_rows = []
    for _, row in df.iterrows():
        # Extract register block name
        row['reg_block'] = extract_reg_block_name(row['table'])
        
        # Process array information
        processed = process_register_entry(row)
        for entry in processed:
            # Reorder columns: reg_block, name, offset, array_size, array_indices, type, description
            new_row = {
                'reg_block': entry['reg_block'],
                'name': entry['name'],
                'offset': entry['offset'],
                'array_size': entry.get('array_size', 1),
                'array_indices': entry.get('array_indices', ''),
                'type': entry['type'],
                'description': entry['description']
            }
            all_rows.append(new_row)
    
    # Create DataFrame with new structure
    result_df = pd.DataFrame(all_rows)
    
    # Preserve L1 document order - do not sort
    # result_df = result_df.sort_values(['reg_block', 'offset'])  # Commented out to preserve L1 order
    
    # Save to CSV
    result_df.to_csv(output_csv, index=False)
    
    # Print statistics
    print(f"  Original rows: {len(df)}")
    print(f"  Optimized rows: {len(result_df)}")
    print(f"  Arrays detected: {len(result_df[result_df['array_size'] > 1])}")
    print(f"  Single registers: {len(result_df[result_df['array_size'] == 1])}")
    print(f"  Unique register blocks: {result_df['reg_block'].nunique()}")
    
    return result_df

def optimize_register_summaries_with_size(input_csv, output_csv, register_sizes):
    """
    Transform register summaries CSV with array handling and register size detection.
    """
    print(f"Processing {input_csv} with size detection...")
    df = pd.read_csv(input_csv)
    
    # Process each row and collect results
    all_rows = []
    for _, row in df.iterrows():
        # Extract register block name
        row['reg_block'] = extract_reg_block_name(row['table'])
        
        # Process array information
        processed = process_register_entry(row)
        for entry in processed:
            # Reorder columns: reg_block, name, offset, array_size, array_indices, type, register_size, description
            new_row = {
                'reg_block': entry['reg_block'],
                'name': entry['name'],
                'offset': entry['offset'],
                'array_size': entry.get('array_size', 1),
                'array_indices': entry.get('array_indices', ''),
                'type': entry['type'],
                'register_size': register_sizes.get(entry['name'], 64),  # Use pre-calculated size, default to 64-bit
                'description': entry['description']
            }
            
            all_rows.append(new_row)
    
    # Create DataFrame with new structure
    result_df = pd.DataFrame(all_rows)
    
    # Preserve L1 document order - do not sort
    
    # Save to CSV
    result_df.to_csv(output_csv, index=False)
    
    # Print statistics
    print(f"  Original rows: {len(df)}")
    print(f"  Optimized rows: {len(result_df)}")
    print(f"  Arrays detected: {len(result_df[result_df['array_size'] > 1])}")
    print(f"  Single registers: {len(result_df[result_df['array_size'] == 1])}")
    print(f"  32-bit registers: {len(result_df[result_df['register_size'] == 32])}")
    print(f"  64-bit registers: {len(result_df[result_df['register_size'] == 64])}")
    print(f"  Unique register blocks: {result_df['reg_block'].nunique()}")
    
    return result_df

def parse_table_header(table_str):
    """
    Parse table header to extract table ID and register name.
    Input: "Table 8-7: por_apb_node_info attributes"
    Output: ("Table 8-7", "por_apb_node_info")
    """
    match = re.match(r'^(Table\s+\d+-\d+):\s+(.+?)\s+attributes', table_str, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)
    return table_str, ""

def process_bit_range(bits_str):
    """
    Process bit range to reverse order and calculate size.
    Input: "63:32" or "0"
    Output: ("32:63", 32) or ("0", 1)
    """
    if ':' in bits_str:
        # Range format
        match = re.match(r'(\d+):(\d+)', bits_str)
        if match:
            high = int(match.group(1))
            low = int(match.group(2))
            # Reverse to low:high format
            reversed_bits = f"{low}:{high}"
            # Calculate size
            size = abs(high - low) + 1
            return reversed_bits, size
    else:
        # Single bit
        return bits_str, 1
    
    return bits_str, 1

def separate_field_name_from_description(name_str):
    """
    Separate field name from embedded description using space as delimiter.
    Also handles cases where binary values (0b0, 0b1) are concatenated to field names.
    
    Input: "drop_transactions_on_inbound_cxl_viral When set, write/read requests..."
    Output: ("drop_transactions_on_inbound_cxl_viral", "When set, write/read requests...")
    
    Input: "chi_pftgt_hint_disable0b1 CHI Prefetch target..."
    Output: ("chi_pftgt_hint_disable", "0b1 CHI Prefetch target...")
    """
    if not name_str or pd.isna(name_str):
        return '', ''
    
    name_str = str(name_str).strip()
    
    # First check if field name ends with binary value pattern (0b0, 0b1, etc.)
    binary_pattern = re.match(r'^(.+?)(0b[01]+)(.*)$', name_str)
    if binary_pattern:
        field_name = binary_pattern.group(1)
        binary_val = binary_pattern.group(2)
        rest = binary_pattern.group(3).strip()
        
        # Combine binary value with rest as description
        if rest:
            description = f"{binary_val} {rest}"
        else:
            description = binary_val
        
        return field_name, description
    
    # Otherwise, split on first space that's not inside brackets
    # This handles cases like htg#{index*4 + 3}_hn_cal_mode_en where spaces can be inside {}
    
    in_brackets = False
    bracket_depth = 0
    split_pos = -1
    
    for i, char in enumerate(name_str):
        if char == '{':
            bracket_depth += 1
            in_brackets = True
        elif char == '}':
            bracket_depth -= 1
            if bracket_depth == 0:
                in_brackets = False
        elif char == ' ' and not in_brackets:
            # Found first space outside brackets
            split_pos = i
            break
    
    if split_pos > 0:
        field_name = name_str[:split_pos]
        description = name_str[split_pos+1:]
        return field_name, description
    
    # No space found outside brackets - return whole string as field name
    return name_str, ''

def convert_reset_value(reset_str):
    """
    Convert reset values from binary (0bXXX) to hex (0xXXX) format.
    Also standardizes other formats.
    """
    if not reset_str or pd.isna(reset_str) or reset_str == '-':
        return '-'
    
    reset_str = str(reset_str).strip()
    
    # Handle binary format (0b...)
    if reset_str.startswith('0b'):
        try:
            # Convert binary string to integer, then to hex
            binary_str = reset_str[2:]  # Remove '0b' prefix
            value = int(binary_str, 2)
            return f'0x{value:x}'
        except ValueError:
            return reset_str  # Return as-is if conversion fails
    
    # Handle hex format - ensure lowercase
    if reset_str.startswith('0x') or reset_str.startswith('0X'):
        return '0x' + reset_str[2:].lower()
    
    # Return other formats as-is
    return reset_str

def optimize_register_attributes(input_csv, output_csv):
    """
    Transform register attributes CSV with proper structure.
    """
    print(f"\nProcessing {input_csv}...")
    df = pd.read_csv(input_csv)
    
    # Process each row
    all_rows = []
    for _, row in df.iterrows():
        # Get field name and clean it from embedded descriptions
        raw_field_name = str(row['name']) if pd.notna(row['name']) else ''
        field_name, extracted_desc = separate_field_name_from_description(raw_field_name)
        
        # Use existing description column if available, otherwise use extracted description
        description = str(row.get('description', ''))
        if not description and extracted_desc:
            description = extracted_desc
        
        # Enable Reserved filtering - skip Reserved fields
        if (field_name.lower() == 'reserved' or 
            field_name.lower().startswith('reserved') or
            'reserved for future' in description.lower()):
            continue
        
        # Parse table header
        table_id, register_name = parse_table_header(row['table'])
        
        # Process bit range
        bits_reversed, bits_size = process_bit_range(row['bits'])
        
        # Convert reset value from binary to hex
        reset_value = convert_reset_value(row['reset'])
        
        # Create new row
        new_row = {
            'table_id': table_id,
            'register_name': register_name,
            'field_name': field_name,
            'bits': bits_reversed,
            'bits_size': bits_size,
            'type': row['type'],
            'reset': reset_value
        }
        all_rows.append(new_row)
    
    # Create DataFrame with new structure
    result_df = pd.DataFrame(all_rows)
    
    # Do NOT sort - preserve original order from input file
    # This maintains the natural document order
    
    # Save to CSV
    result_df.to_csv(output_csv, index=False)
    
    # Print statistics
    print(f"  Original rows: {len(df)}")
    print(f"  Optimized rows: {len(result_df)}")
    print(f"  Unique registers: {result_df['register_name'].nunique()}")
    
    return result_df

def main():
    """Main function to run L2 optimization."""
    # Set up paths
    input_dir = Path("L1_pdf_analysis")
    output_dir = Path("L2_csv_optimize")
    
    # Create output directory
    output_dir.mkdir(exist_ok=True)
    
    print("=" * 60)
    print("L2 CSV Optimization")
    print("=" * 60)
    
    # First, calculate register sizes from L1 attributes (INCLUDING Reserved fields)
    attributes_input = input_dir / "all_register_attributes.csv"
    register_sizes = {}
    if attributes_input.exists():
        register_sizes = calculate_register_sizes_from_l1(attributes_input)
    else:
        print(f"Warning: {attributes_input} not found")
    
    # Process register attributes (this filters out Reserved fields)
    attributes_output = output_dir / "register_attributes_optimized.csv"
    
    attributes_df = None
    if attributes_input.exists():
        attributes_df = optimize_register_attributes(attributes_input, attributes_output)
    else:
        print(f"Warning: {attributes_input} not found")
    
    # Process register summaries with size information
    summaries_input = input_dir / "all_register_summaries.csv"
    summaries_output = output_dir / "register_summaries_optimized.csv"
    
    if summaries_input.exists():
        optimize_register_summaries_with_size(summaries_input, summaries_output, register_sizes)
    else:
        print(f"Warning: {summaries_input} not found")
    
    print("\n" + "=" * 60)
    print("L2 optimization complete!")
    print(f"Output files in: {output_dir}/")
    print("=" * 60)

if __name__ == "__main__":
    main()