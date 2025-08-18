#!/usr/bin/env python3
"""
L4 C++ Generator - Complete Field and Register Generation
Generates both field.cpp and register.cpp in a single unified process
"""

import json
import pandas as pd
import re
from pathlib import Path

# ============================================================================
# SHARED UTILITIES
# ============================================================================

def sanitize_name(name):
    """Sanitize names for C++ identifiers"""
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

# ============================================================================
# FIELD GENERATION (from l4_reg_generator.py)
# ============================================================================

def parse_bits_range(bits_str):
    """
    Parse bit range string to get start bit and size.
    Examples:
        "31" -> (31, 1)
        "31:16" -> (16, 16)  # start=16, size=16
        "0:15" -> (0, 16)    # start=0, size=16
    """
    if ':' in bits_str:
        parts = bits_str.split(':')
        bit1 = int(parts[0])
        bit2 = int(parts[1])
        # Always use the smaller value as start, larger-smaller+1 as size
        start_bit = min(bit1, bit2)
        bit_size = abs(bit1 - bit2) + 1
        return start_bit, bit_size
    else:
        # Single bit
        bit = int(bits_str)
        return bit, 1

def get_access_and_write_effect(field_type):
    """
    Convert field type to vlab access and write effect parameters.
    
    Returns:
        tuple: (access_param, write_effect_param)
        - access_param: None for default RW, or "vlab::Access::read_only" for RO
        - write_effect_param: None for default, or "vlab::WriteEffect::one_to_clear" for W1C
    """
    if not field_type or field_type == "-":
        return None, None
    
    field_type_upper = field_type.upper()
    
    # Read-only types
    if field_type_upper in ['RO', 'R']:
        return "vlab::Access::read_only", None
    
    # Write-one-to-clear types
    if field_type_upper in ['W1C', 'R/W1C']:
        return "vlab::Access::read_write", "vlab::WriteEffect::one_to_clear"
    
    # Write-one-to-set types (if supported by vlab)
    if field_type_upper in ['W1S', 'R/W1S']:
        return "vlab::Access::read_write", "vlab::WriteEffect::one_to_set"
    
    # Write-one-to-pulse types (if supported by vlab)
    if field_type_upper in ['W1P', 'R/W1P']:
        return "vlab::Access::read_write", "vlab::WriteEffect::one_to_pulse"
    
    # RWL (Read-Write Lock) - treat as normal read-write
    # RWL fields can be locked but are initially read-write
    if field_type_upper in ['RWL']:
        return None, None  # Default RW access
    
    # Default read-write (no extra parameters needed)
    # This covers: RW, R/W, WO, etc.
    return None, None

def generate_field_cpp(l2_df, output_dir):
    """Generate field.cpp with vlab::Field32/Field64 definitions for all fields"""
    output_file = output_dir / "field.cpp"
    field_variables = {}  # Track generated field variables for register generator
    
    print(f"Generating {output_file}...")
    
    # Load L3 JSON to get all register names and sizes for conflict detection
    try:
        l3_data = load_l3_json()
        all_register_names = set()
        register_sizes = {}  # Map register name to bit width
        for block_data in l3_data['register_blocks'].values():
            for register in block_data['registers']:
                # Store sanitized uppercase register names for comparison
                reg_name_sanitized = sanitize_name(register['name'].upper())
                all_register_names.add(reg_name_sanitized)
                # Store register size
                register_sizes[register['name']] = register.get('bit_width', 64)
        print(f"Loaded {len(all_register_names)} register names for conflict detection")
    except Exception as e:
        print(f"Warning: Could not load register names for conflict detection: {e}")
        all_register_names = set()
        register_sizes = {}
    
    with open(output_file, 'w') as f:
        # Process each field in original L2 CSV order (no grouping)
        field_count = 0
        current_register = ""
        conflict_count = 0
        
        for _, row in l2_df.iterrows():
            register_name = str(row['register_name'])
            field_name = str(row['field_name'])
            bits = str(row['bits'])
            field_type = str(row['type'])
            
            # Skip invalid entries
            if pd.isna(register_name) or pd.isna(field_name) or not register_name or not field_name:
                continue
            
            # Parse bit range
            try:
                start_bit, bit_size = parse_bits_range(bits)
            except (ValueError, IndexError):
                print(f"Warning: Could not parse bits '{bits}' for {register_name}.{field_name}")
                continue
            
            # Sanitize names for C++
            register_cpp_name = sanitize_name(register_name.upper())
            field_cpp_name = sanitize_name(field_name)
            
            # Generate field variable name
            field_var_name = f"{register_cpp_name}_{field_cpp_name.upper()}"
            
            # Check for naming conflict with register names
            # Check both the full field variable name and just the field name part
            field_name_sanitized = sanitize_name(field_name.upper())
            if field_var_name in all_register_names or field_name_sanitized in all_register_names:
                field_var_name = field_var_name + "_"
                conflict_count += 1
                print(f"  Resolved naming conflict: {register_name}.{field_name} -> {field_var_name}")
            
            # Store for register generator with register-specific key
            field_variables[(register_name, field_name)] = field_var_name
            
            # Get access and write effect parameters
            access_param, write_effect_param = get_access_and_write_effect(field_type)
            
            # Build parameter list
            params = [f'"{field_name}"', str(start_bit), str(bit_size)]
            if access_param:
                params.append(access_param)
            if write_effect_param:
                params.append(write_effect_param)
            
            # Add register comment when register changes (preserve L2 order)
            if register_name != current_register:
                f.write(f"\n// Fields for register: {register_name}\n")
                current_register = register_name
            
            # Determine field type based on register size
            register_bit_width = register_sizes.get(register_name, 64)
            field_type_name = f"Field{register_bit_width}"
            
            # Write field definition immediately (preserve L2 order)
            param_str = ", ".join(params)
            f.write(f"vlab::{field_type_name} {field_var_name} {{{param_str}}};\n")
            
            field_count += 1
        
        f.write(f"\n// Total fields generated: {field_count}\n")
    
    print(f"Generated {field_count} field definitions in {output_file}")
    if conflict_count > 0:
        print(f"  Resolved {conflict_count} naming conflicts by appending underscore")
    return field_variables

# ============================================================================
# REGISTER GENERATION (from l4_register_generator.py)
# ============================================================================

def load_l3_json():
    """Load L3 register_data.json as the primary structure source"""
    json_path = Path("L3_cpp_generator/register_data.json")
    if not json_path.exists():
        raise FileNotFoundError(f"L3 JSON not found: {json_path}")
    
    with open(json_path, 'r') as f:
        return json.load(f)

def simplify_reset_value(reset_value):
    """
    Simplify reset values by removing leading zeros.
    Examples: 
        0 -> 0x0
        0x0000000000001000 -> 0x1000
        0x0000000000000000 -> 0x0
    """
    if reset_value == 0:
        return "0x0"
    
    # Convert to hex string and remove leading zeros
    hex_str = f"0x{reset_value:x}"
    return hex_str

def get_fields_for_register(register_name, l2_df, field_variables):
    """
    Get all field variable names for a register using L2 CSV mapping.
    Returns fields in L2 CSV order (same as field.cpp order).
    """
    # Find all fields for this register
    register_fields = l2_df[l2_df['register_name'] == register_name]
    
    field_vars = []
    for _, field_row in register_fields.iterrows():
        field_name = field_row['field_name']
        
        # Skip invalid field names (NaN, empty, etc.)
        if pd.isna(field_name) or not field_name or not str(field_name).strip():
            continue
        
        field_name = str(field_name).strip()
        
        if (register_name, field_name) in field_variables:
            field_vars.append(field_variables[(register_name, field_name)])
        else:
            # Generate expected variable name if not found
            register_cpp_name = sanitize_name(register_name.upper())
            field_cpp_name = sanitize_name(field_name.upper())
            expected_var = f"{register_cpp_name}_{field_cpp_name}"
            field_vars.append(expected_var)
            print(f"Warning: Field variable not found, using generated name: {expected_var}")
    
    return field_vars

def generate_register_cpp(l3_data, l2_df, field_variables, output_dir):
    """Generate register.cpp with vlab register definitions"""
    output_file = output_dir / "register.cpp"
    
    print(f"Generating {output_file}...")
    
    with open(output_file, 'w') as f:
        # Generate register blocks first (in L3 JSON order)
        f.write("// Register Blocks\n")
        for block_name, block_data in l3_data['register_blocks'].items():
            size_hex = f"0x{block_data['size']:x}"
            f.write(f"vlab::RegBlock {block_name} {{*this, \"{block_name}\", {size_hex}, 0x0, vlab::Endianness::little, 64}};\n")
        f.write("\n")
        
        # Generate registers (following L3 JSON order)
        f.write("// Registers\n")
        total_registers = 0
        
        for block_name, block_data in l3_data['register_blocks'].items():
            f.write(f"\n// Registers for block: {block_name}\n")
            
            # Process registers in L3 JSON array order
            for register in block_data['registers']:
                register_name = register['name']
                # Use original_name for field matching (renamed registers still use original for fields)
                original_name = register.get('original_name', register_name)
                offset_hex = f"0x{register['offset']:x}"
                reset_simplified = simplify_reset_value(register['calculated_reset'])
                array_size = register.get('array_size', 1)
                
                # Get fields for this register using original name
                field_list = get_fields_for_register(original_name, l2_df, field_variables)
                
                # Sanitize register name for C++ variable
                register_cpp_name = sanitize_name(register_name.upper())
                
                # Get register bit width
                register_bit_width = register.get('bit_width', 64)
                reg_type = f"Reg{register_bit_width}"
                byte_size = register_bit_width // 8  # 4 for 32-bit, 8 for 64-bit
                
                if array_size > 1:
                    # Register array with correct byte size
                    field_str = ", ".join(field_list) if field_list else ""
                    f.write(f"vlab::{reg_type}Array {register_cpp_name} {{{block_name}, \"{register_name}\", {offset_hex}, {array_size}, {reset_simplified}, {{{field_str}}}, {byte_size}}};\n")
                else:
                    # Single register
                    field_str = ", ".join(field_list) if field_list else ""
                    f.write(f"vlab::{reg_type} {register_cpp_name} {{{block_name}, \"{register_name}\", {offset_hex}, {reset_simplified}, {{{field_str}}}}};\n")
                
                total_registers += 1
        
        f.write(f"\n// Total registers generated: {total_registers}\n")
    
    print(f"Generated {total_registers} register definitions in {output_file}")
    return total_registers

# ============================================================================
# MAIN UNIFIED GENERATOR
# ============================================================================

def generate_cpp_files():
    """
    Generate both field.cpp and register.cpp in unified process.
    Returns: (field_count, register_count)
    """
    print("Loading data sources...")
    
    # Load L2 CSV for field generation
    attributes_path = Path("L3_cpp_generator/register_attributes_deduplicated.csv")
    if not attributes_path.exists():
        raise FileNotFoundError(f"Deduplicated attributes CSV not found: {attributes_path}")
    
    l2_df = pd.read_csv(attributes_path)
    
    # Load L3 JSON for register generation
    l3_data = load_l3_json()
    
    print(f"Loaded {len(l2_df)} field mappings from L2")
    print(f"Processing {len(l3_data['register_blocks'])} register blocks from L3")
    
    # Create output directory
    output_dir = Path("L4_Reg_generator")
    output_dir.mkdir(exist_ok=True)
    
    # Step 1: Generate field.cpp and get field variable mapping
    print("\n--- Step 1: Generating Field Definitions ---")
    field_variables = generate_field_cpp(l2_df, output_dir)
    
    # Step 2: Generate register.cpp using field variables
    print("\n--- Step 2: Generating Register Definitions ---")
    register_count = generate_register_cpp(l3_data, l2_df, field_variables, output_dir)
    
    return len(field_variables), register_count

def main():
    """Main entry point"""
    print("=" * 60)
    print("L4 C++ Generator - Field & Register Definitions")
    print("=" * 60)
    
    try:
        field_count, register_count = generate_cpp_files()
        
        print("\n" + "=" * 60)
        print("C++ generation complete!")
        print(f"Generated {field_count} field definitions")
        print(f"Generated {register_count} register definitions")
        print("=" * 60)
        print("Output files:")
        print("  L4_Reg_generator/field.cpp")
        print("  L4_Reg_generator/register.cpp")
        print("=" * 60)
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())