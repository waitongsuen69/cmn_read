#!/usr/bin/env python3
"""
L3 C++ Generator - JSON Generation Phase
Reads L2 optimized CSVs and generates comprehensive JSON for C++ code generation
"""

import json
import pandas as pd
import re
from pathlib import Path

def sanitize_name(name):
    """Sanitize names for C++ identifiers (same as L4)"""
    # Replace invalid C++ identifier characters
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    # Ensure it doesn't start with a number
    if name and name[0].isdigit():
        name = '_' + name
    # Remove consecutive underscores
    name = re.sub(r'_+', '_', name)
    # Remove trailing underscores
    name = name.strip('_')
    return name

def deduplicate_attributes(attributes_df, output_dir):
    """
    Deduplicate fields in attributes dataframe.
    - Remove exact duplicates (same register, field, bits)
    - Rename fields with same name but different bits
    """
    print("\nPerforming field deduplication...")
    
    deduplicated_rows = []
    stats = {'duplicates_removed': 0, 'fields_renamed': 0}
    rename_log = []  # Track all renames for logging
    
    for register_name in attributes_df['register_name'].unique():
        register_fields = attributes_df[attributes_df['register_name'] == register_name]
        
        seen_exact = set()  # (field_name, bits) tuples
        field_name_counts = {}  # Track field names for renaming
        sanitized_name_counts = {}  # Track sanitized names to detect collisions
        
        for _, row in register_fields.iterrows():
            key = (row['field_name'], row['bits'])
            
            # Skip exact duplicates
            if key in seen_exact:
                stats['duplicates_removed'] += 1
                continue
            
            seen_exact.add(key)
            new_row = row.copy()
            
            field_name = row['field_name']
            # Handle NaN or empty field names
            if pd.isna(field_name) or not str(field_name).strip():
                continue
            
            field_name = str(field_name).strip()
            sanitized = sanitize_name(field_name.upper())
            
            # Check for both raw name collisions and sanitized name collisions
            needs_rename = False
            
            # Case 1: Same raw field name with different bits
            if field_name in field_name_counts:
                needs_rename = True
            # Case 2: Different raw names but same sanitized name
            elif sanitized in sanitized_name_counts and sanitized_name_counts[sanitized] != field_name:
                needs_rename = True
                
            if needs_rename:
                # Determine suffix based on sanitized name count
                if sanitized in sanitized_name_counts:
                    suffix = len([k for k in sanitized_name_counts.keys() if k.startswith(sanitized)]) + 1
                else:
                    suffix = 1
                    
                original_name = new_row['field_name']
                new_row['field_name'] = f"{field_name}_{suffix}"
                stats['fields_renamed'] += 1
                rename_log.append({
                    'register': register_name,
                    'original': original_name,
                    'renamed': new_row['field_name'],
                    'bits': row['bits'],
                    'reason': 'sanitized_collision' if field_name not in field_name_counts else 'raw_collision'
                })
                
                # Update tracking
                field_name_counts[new_row['field_name']] = 1
                sanitized_name_counts[sanitize_name(new_row['field_name'].upper())] = new_row['field_name']
            else:
                field_name_counts[field_name] = 1
                sanitized_name_counts[sanitized] = field_name
            
            deduplicated_rows.append(new_row)
    
    # Create deduplicated dataframe
    dedup_df = pd.DataFrame(deduplicated_rows)
    
    # Save deduplicated CSV
    dedup_path = output_dir / "register_attributes_deduplicated.csv"
    dedup_df.to_csv(dedup_path, index=False)
    
    # Save rename log if there were any renames
    if rename_log:
        rename_log_path = output_dir / "field_rename_log.json"
        with open(rename_log_path, 'w') as f:
            json.dump(rename_log, f, indent=2)
        print(f"  Field rename log saved to: {rename_log_path}")
    
    print(f"  Original fields: {len(attributes_df)}")
    print(f"  Duplicates removed: {stats['duplicates_removed']}")
    print(f"  Fields renamed: {stats['fields_renamed']}")
    print(f"  Final fields: {len(dedup_df)}")
    print(f"  Saved to: {dedup_path}")
    
    return dedup_df

def deduplicate_registers(summaries_df, output_dir):
    """
    Deduplicate register names within same reg_block.
    Adds 'original_name' column to preserve original for field matching.
    """
    print("\nPerforming register deduplication...")
    
    deduplicated_rows = []
    stats = {'registers_renamed': 0}
    rename_log = []
    
    for block in summaries_df['reg_block'].unique():
        block_registers = summaries_df[summaries_df['reg_block'] == block]
        
        name_counts = {}  # Track register names for renaming
        
        for _, row in block_registers.iterrows():
            new_row = row.to_dict()  # Convert to dict for new column
            register_name = row['name']
            
            # Store original name for field matching
            new_row['original_name'] = register_name
            
            # Rename if duplicate name in same block
            if register_name in name_counts:
                suffix = name_counts[register_name]
                new_row['name'] = f"{register_name}_{suffix}"
                name_counts[register_name] += 1
                stats['registers_renamed'] += 1
                rename_log.append({
                    'block': block,
                    'original': register_name,
                    'renamed': new_row['name'],
                    'offset': row['offset']
                })
            else:
                name_counts[register_name] = 1
            
            deduplicated_rows.append(new_row)
    
    # Create deduplicated dataframe
    dedup_df = pd.DataFrame(deduplicated_rows)
    
    # Save deduplicated CSV
    dedup_path = output_dir / "register_summaries_deduplicated.csv"
    dedup_df.to_csv(dedup_path, index=False)
    
    # Save rename log
    if rename_log:
        log_path = output_dir / "register_rename_log.json"
        with open(log_path, 'w') as f:
            json.dump(rename_log, f, indent=2)
        print(f"  Register rename log saved to: {log_path}")
    
    print(f"  Original registers: {len(summaries_df)}")
    print(f"  Registers renamed: {stats['registers_renamed']}")
    print(f"  Final registers: {len(dedup_df)}")
    print(f"  Saved to: {dedup_path}")
    
    return dedup_df

def parse_offset(offset_str):
    """
    Parse offset string, taking start offset for ranges.
    Examples:
        "0x100" -> 256
        "0xF80 : 0xFA0" -> 3968 (takes 0xF80)
        "{0-15} 0x7580" -> 30080 (takes 0x7580, ignoring array indices)
        "{0-15} 0x7580 : 0x75F8" -> 30080 (takes start of range after indices)
        "0xC00 + 0x80" -> 3072 (takes 0xC00, ignoring size notation)
    """
    if not offset_str:
        return 0
    
    offset_str = str(offset_str).strip()
    
    # Handle offset+size format like "0xC00 + 0x80"
    if '+' in offset_str:
        # Take just the base offset before the +
        base = offset_str.split('+')[0].strip()
        return int(base, 16) if base.startswith('0x') else int(base)
    
    # Handle array index format like "{0-15} 0x7580" or "{0-15} 0x7580 : 0x75F8"
    if '{' in offset_str and '}' in offset_str:
        # Extract the offset part after the array indices
        parts = offset_str.split('}')
        if len(parts) > 1:
            offset_part = parts[1].strip()
            # Now handle this part which might be a simple offset or a range
            if ':' in offset_part:
                # It's a range, take the first part
                start = offset_part.split(':')[0].strip()
                return int(start, 16) if start.startswith('0x') else int(start)
            elif offset_part.startswith('0x'):
                return int(offset_part, 16)
    
    # Handle range format
    if ':' in offset_str:
        # Take the first part
        start = offset_str.split(':')[0].strip()
        if start:  # Make sure start is not empty
            return int(start, 16) if start.startswith('0x') else int(start)
        else:
            # If start is empty, try the second part
            parts = offset_str.split(':')
            if len(parts) > 1 and parts[1].strip():
                end = parts[1].strip()
                return int(end, 16) if end.startswith('0x') else int(end)
            return 0
    
    # Handle simple offset
    if offset_str.startswith('0x'):
        return int(offset_str, 16)
    
    return int(offset_str) if offset_str.isdigit() else 0

def parse_bits(bits_str):
    """
    Parse bit range string to get low and high bit positions.
    ARM notation can use either [high:low] or [low:high] format depending on context.
    We need to determine which is which based on the values.
    Examples:
        "[31:0]" -> (0, 31)   # bits 0 to 31 (high:low format)
        "31:0" -> (0, 31)     # bits 0 to 31 (high:low format)
        "0:15" -> (0, 15)     # bits 0 to 15 (low:high format)
        "32:47" -> (32, 47)   # bits 32 to 47 (low:high format)
        "[7]" -> (7, 7)       # single bit 7
        "7" -> (7, 7)         # single bit 7
    """
    # Remove brackets if present
    bits_str = bits_str.strip('[]')
    
    if ':' in bits_str:
        parts = bits_str.split(':')
        val1 = int(parts[0])
        val2 = int(parts[1])
        # Return (low, high) regardless of input order
        return (min(val1, val2), max(val1, val2))
    else:
        bit = int(bits_str)
        return bit, bit

def parse_reset_value(reset_str, bit_width=None):
    """
    Parse reset value from various formats.
    Returns: (parsed_value, is_fixed, original_string)
    """
    if not reset_str or pd.isna(reset_str):
        return 0, False, "undefined"
    
    reset_str = str(reset_str).strip()
    
    # Handle dash/empty
    if reset_str == '-' or reset_str == '':
        return 0, False, "undefined"
    
    # Handle hex format
    if reset_str.startswith('0x') or reset_str.startswith('0X'):
        try:
            return int(reset_str, 16), True, reset_str
        except ValueError:
            return 0, False, reset_str
    
    # Handle binary format (should be converted to hex already, but just in case)
    if reset_str.startswith('0b'):
        try:
            return int(reset_str[2:], 2), True, reset_str
        except ValueError:
            return 0, False, reset_str
    
    # Handle plain decimal
    if reset_str.replace('.', '').isdigit():
        try:
            # Handle float-like strings (e.g., "0.0" -> 0)
            return int(float(reset_str)), True, reset_str
        except ValueError:
            return 0, False, reset_str
    
    # Non-numeric values
    if any(keyword in reset_str.lower() for keyword in 
           ['configuration', 'implementation', 'dependent', 'variable']):
        return 0, False, reset_str
    
    # Unknown format
    return 0, False, reset_str

def calculate_register_reset(fields):
    """
    Calculate the complete register reset value from its fields.
    Returns: (calculated_reset_value, list_of_flags)
    """
    reset_value = 0
    reset_flags = []
    
    for field in fields:
        # Parse field reset
        field_reset, is_fixed, original = parse_reset_value(field['reset'])
        
        # Add flag if not fixed
        if not is_fixed:
            reset_flags.append({
                'field': field['name'],
                'bits': field['bits'],
                'reason': original
            })
        
        # Get bit positions
        bit_low = field['bit_low']
        bit_high = field['bit_high']
        
        # Ensure bit positions are valid
        if bit_high < bit_low:
            # Skip invalid field
            print(f"    Warning: Invalid bit range for field {field['name']}: [{bit_high}:{bit_low}]")
            continue
        
        # Calculate field width and mask
        field_width = bit_high - bit_low + 1
        
        # Ensure width is reasonable (max 64 bits for 64-bit register)
        if field_width > 64:
            print(f"    Warning: Field width too large for {field['name']}: {field_width} bits")
            field_width = 64
        
        field_mask = (1 << field_width) - 1
        
        # Apply mask to ensure field value fits
        field_reset &= field_mask
        
        # Shift to position and OR into register
        reset_value |= (field_reset << bit_low)
    
    return reset_value, reset_flags


def process_register_blocks():
    """
    Main processing function to generate register block data.
    """
    # Read L2 optimized CSVs
    summaries_path = Path("L2_csv_optimize/register_summaries_optimized.csv")
    attributes_path = Path("L2_csv_optimize/register_attributes_optimized.csv")
    
    if not summaries_path.exists() or not attributes_path.exists():
        print("Error: L2 optimized CSV files not found!")
        return None
    
    print(f"Loading {summaries_path}...")
    summaries_df = pd.read_csv(summaries_path)
    
    print(f"Loading {attributes_path}...")
    attributes_df = pd.read_csv(attributes_path)
    
    # Deduplicate data and save to L3 directory
    output_dir = Path("L3_cpp_generator")
    output_dir.mkdir(exist_ok=True)
    attributes_df = deduplicate_attributes(attributes_df, output_dir)
    summaries_df = deduplicate_registers(summaries_df, output_dir)
    
    # Build hierarchical structure
    register_blocks = {}
    
    # Process summaries to create register structure
    print("\nProcessing register summaries...")
    for _, row in summaries_df.iterrows():
        block_name = row['reg_block']
        
        # Initialize block if needed
        if block_name not in register_blocks:
            register_blocks[block_name] = {
                'name': block_name,
                'size': 0,  # Will calculate later
                'registers': []
            }
        
        # Parse offset
        offset = parse_offset(row['offset'])
        
        # Create register entry
        register = {
            'name': row['name'],
            'original_name': row.get('original_name', row['name']),  # For field matching
            'offset': offset,
            'offset_hex': row['offset'],
            'array_size': int(row['array_size']) if pd.notna(row['array_size']) else 1,
            'array_indices': str(row['array_indices']) if pd.notna(row['array_indices']) else "",
            'register_type': row['type'] if pd.notna(row['type']) else "RW",
            'bit_width': int(row['register_size']) if 'register_size' in row and pd.notna(row['register_size']) else 64,
            'fields': [],
            'calculated_reset': 0,
            'reset_flags': []
        }
        
        register_blocks[block_name]['registers'].append(register)
    
    # Add fields from attributes
    print("\nMatching fields to registers...")
    fields_matched = 0
    fields_unmatched = 0
    unmatched_fields = []  # Store unmatched fields for logging
    
    for _, field_row in attributes_df.iterrows():
        register_name = field_row['register_name']
        
        # Find ALL registers with matching original_name (for duplicates)
        found = False
        for block in register_blocks.values():
            for register in block['registers']:
                # Match using original_name (for renamed registers) or name (for non-renamed)
                match_name = register.get('original_name', register['name'])
                if match_name == register_name:
                    # Parse bit positions
                    bit_low, bit_high = parse_bits(field_row['bits'])
                    
                    # Parse reset value
                    reset_parsed, is_fixed, original = parse_reset_value(field_row['reset'])
                    
                    # Add field
                    field = {
                        'name': field_row['field_name'],
                        'bits': field_row['bits'],
                        'bit_low': bit_low,
                        'bit_high': bit_high,
                        'bits_size': int(field_row['bits_size']) if pd.notna(field_row['bits_size']) else (bit_high - bit_low + 1),
                        'type': field_row['type'] if pd.notna(field_row['type']) else "RW",
                        'reset': field_row['reset'] if pd.notna(field_row['reset']) else "-",
                        'reset_parsed': reset_parsed,
                        'reset_is_fixed': is_fixed
                    }
                    
                    register['fields'].append(field)
                    fields_matched += 1
                    found = True
                    # Don't break - add field to ALL matching registers
        
        if not found:
            fields_unmatched += 1
            print(f"  Warning: Could not match field to register: {register_name}.{field_row['field_name']}")
            
            # Store unmatched field details for logging
            unmatched_fields.append({
                'table_id': field_row.get('table_id', ''),
                'register_name': register_name,
                'field_name': field_row['field_name'],
                'bits': field_row['bits'],
                'bits_size': field_row.get('bits_size', ''),
                'type': field_row.get('type', ''),
                'reset': field_row.get('reset', ''),
                'reason': 'Register name not found in summaries'
            })
    
    print(f"  Matched {fields_matched} fields")
    if fields_unmatched > 0:
        print(f"  Unmatched {fields_unmatched} fields")
    
    # Calculate reset values for each register
    print("\nCalculating register reset values...")
    for block in register_blocks.values():
        max_offset = 0
        
        for register in block['registers']:
            # Calculate reset from fields
            if register['fields']:
                reset_value, reset_flags = calculate_register_reset(register['fields'])
                register['calculated_reset'] = reset_value
                register['reset_flags'] = reset_flags
                
                # Hex representation for readability
                register['calculated_reset_hex'] = f"0x{reset_value:016x}"
            
            # Update max offset for block size calculation
            # Assume 8 bytes per register
            register_end = register['offset'] + (8 * max(1, register['array_size']))
            max_offset = max(max_offset, register_end)
        
        # Set block size (round up to next power of 2 or page boundary)
        block['size'] = max_offset
    
    # Statistics
    print("\nStatistics:")
    total_registers = sum(len(block['registers']) for block in register_blocks.values())
    total_fields = sum(
        sum(len(reg['fields']) for reg in block['registers'])
        for block in register_blocks.values()
    )
    print(f"  Register blocks: {len(register_blocks)}")
    print(f"  Total registers: {total_registers}")
    print(f"  Total fields: {total_fields}")
    
    # Show blocks with sizes
    print("\nRegister blocks:")
    for block_name, block in register_blocks.items():
        print(f"  {block_name}: {len(block['registers'])} registers, size=0x{block['size']:x}")
    
    return {"register_blocks": register_blocks, "unmatched_fields": unmatched_fields}

def main():
    """Main entry point"""
    print("=" * 60)
    print("L3 C++ Generator - JSON Generation")
    print("=" * 60)
    
    # Process data
    data = process_register_blocks()
    
    if data is None:
        print("Error: Failed to process register blocks")
        return 1
    
    # Create output directory
    output_dir = Path("L3_cpp_generator")
    output_dir.mkdir(exist_ok=True)
    
    # Write JSON output
    output_file = output_dir / "register_data.json"
    print(f"\nWriting JSON to {output_file}...")
    
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=False)
    
    print(f"JSON output saved to: {output_file}")
    
    # Also create a pretty-printed summary
    summary_file = output_dir / "register_summary.txt"
    with open(summary_file, 'w') as f:
        f.write("Register Block Summary\n")
        f.write("=" * 60 + "\n\n")
        
        for block_name, block in data['register_blocks'].items():
            f.write(f"Block: {block_name}\n")
            f.write(f"  Size: 0x{block['size']:x} ({block['size']} bytes)\n")
            f.write(f"  Registers: {len(block['registers'])}\n")
            
            # Show first few registers
            for i, reg in enumerate(block['registers'][:5]):
                f.write(f"    - {reg['name']} @ 0x{reg['offset']:x}")
                if reg['array_size'] > 1:
                    f.write(f" [array size={reg['array_size']}]")
                f.write(f" (reset=0x{reg['calculated_reset']:016x})")
                if reg['reset_flags']:
                    f.write(" *has non-fixed fields")
                f.write("\n")
            
            if len(block['registers']) > 5:
                f.write(f"    ... and {len(block['registers']) - 5} more\n")
            f.write("\n")
    
    print(f"Summary saved to: {summary_file}")
    
    # Write unmatched fields log
    if data and 'unmatched_fields' in data and data['unmatched_fields']:
        unmatched_log_file = output_dir / "unmatched_fields.log"
        print(f"\nWriting unmatched fields log to {unmatched_log_file}...")
        
        with open(unmatched_log_file, 'w') as f:
            f.write("Unmatched Fields Log\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Generated: {pd.Timestamp.now()}\n")
            f.write(f"Total unmatched fields: {len(data['unmatched_fields'])}\n\n")
            
            # Group by register name for better analysis
            from collections import defaultdict
            by_register = defaultdict(list)
            for field in data['unmatched_fields']:
                by_register[field['register_name']].append(field)
            
            f.write("Fields grouped by register name:\n")
            f.write("-" * 40 + "\n\n")
            
            for register_name, fields in sorted(by_register.items()):
                f.write(f"Register: {register_name}\n")
                f.write(f"  Unmatched fields: {len(fields)}\n")
                for field in fields:
                    f.write(f"    - {field['field_name']} [{field['bits']}] {field['type']} (reset: {field['reset']})\n")
                f.write("\n")
            
            # Detailed CSV format for easy analysis
            f.write("\nDetailed CSV format:\n")
            f.write("-" * 20 + "\n")
            f.write("table_id,register_name,field_name,bits,bits_size,type,reset,reason\n")
            for field in data['unmatched_fields']:
                f.write(f"{field['table_id']},{field['register_name']},{field['field_name']},{field['bits']},{field['bits_size']},{field['type']},{field['reset']},{field['reason']}\n")
        
        print(f"Unmatched fields log saved to: {unmatched_log_file}")
    
    print("\n" + "=" * 60)
    print("JSON generation complete!")
    print("=" * 60)
    
    return 0

if __name__ == "__main__":
    exit(main())