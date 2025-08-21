#!/usr/bin/env python3
"""
Quick validation script for CMN-700 enhancement functionality.
Tests core functions without requiring full PDF processing.
"""

import sys
import os

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from l1_pdf_analysis import (
    parse_array_indices,
    extract_segment_offset,
    generate_segmented_register_name,
    parse_register_tables,
    is_type_token
)

def test_helper_functions():
    """Test the new helper functions."""
    print("Testing CMN-700 helper functions...")
    
    # Test parse_array_indices
    offset = "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8"
    indices = parse_array_indices(offset)
    assert len(indices) == 2
    assert indices[0] == (0, 23)
    assert indices[1] == (24, 63)
    print("✓ parse_array_indices works correctly")
    
    # Test extract_segment_offset
    segment_0 = extract_segment_offset(offset, 0)
    segment_1 = extract_segment_offset(offset, 1)
    assert segment_0 == "{0-23} 0xC00 : 0xCB8"
    assert segment_1 == "{24-63} 0x20C0 : 0x24B8"
    print("✓ extract_segment_offset works correctly")
    
    # Test generate_segmented_register_name
    name_0 = generate_segmented_register_name("non_hash_mem_region_reg0-63", 0, 23)
    name_1 = generate_segmented_register_name("non_hash_mem_region_reg0-63", 24, 63)
    assert name_0 == "non_hash_mem_region_reg0-23"
    assert name_1 == "non_hash_mem_region_reg24-63"
    print("✓ generate_segmented_register_name works correctly")

def test_multi_segment_parsing():
    """Test multi-segment pattern parsing in parse_register_tables."""
    print("\nTesting multi-segment pattern parsing...")
    
    lines = [
        "Table 4-123: Example register summary",
        "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8 non_hash_mem_region_reg RW Multi-segment array register"
    ]
    
    rows = parse_register_tables(lines)
    
    # Should generate 2 register entries
    assert len(rows) == 2
    
    # Check first segment
    assert rows[0]['offset'] == "{0-23} 0xC00 : 0xCB8"
    assert rows[0]['name'] == "non_hash_mem_region_reg0-23"
    assert rows[0]['type'] == "RW"
    
    # Check second segment
    assert rows[1]['offset'] == "{24-63} 0x20C0 : 0x24B8"
    assert rows[1]['name'] == "non_hash_mem_region_reg24-63"
    assert rows[1]['type'] == "RW"
    
    print("✓ Multi-segment pattern parsing works correctly")

def test_backward_compatibility():
    """Test backward compatibility with CMN-437 patterns."""
    print("\nTesting backward compatibility...")
    
    lines = [
        "Table 4-123: Example register summary",
        "0x1000    register_name    RW    Standard register",
        "{0-31} 0x2000 : 0x20F8    array_reg    RO    Array register"
    ]
    
    rows = parse_register_tables(lines)
    
    # Should parse both patterns correctly
    assert len(rows) == 2
    assert rows[0]['name'] == "register_name"
    assert rows[1]['name'] == "array_reg"
    
    print("✓ Backward compatibility maintained")

def test_type_token_validation():
    """Test type token validation."""
    print("\nTesting type token validation...")
    
    valid_types = ["RW", "RO", "WO", "RWL", "W1C", "W1S", "R/W", "R/W1C"]
    invalid_types = ["INVALID", "ABC", "123", ""]
    
    for valid_type in valid_types:
        assert is_type_token(valid_type), f"{valid_type} should be valid"
    
    for invalid_type in invalid_types:
        assert not is_type_token(invalid_type), f"{invalid_type} should be invalid"
    
    print("✓ Type token validation works correctly")

def test_edge_cases():
    """Test edge cases."""
    print("\nTesting edge cases...")
    
    # Test with no array indices
    offset_no_array = "0x1000"
    indices = parse_array_indices(offset_no_array)
    assert len(indices) == 0
    print("✓ No array pattern handled correctly")
    
    # Test with out of bounds segment index
    offset = "{0-23} 0xC00 : 0xCB8"
    segment = extract_segment_offset(offset, 5)
    assert segment == offset  # Should return original
    print("✓ Out of bounds segment index handled correctly")
    
    # Test with complex multi-segment
    complex_offset = "{0-15} 0xD80 : 0xDF8; {16-47} 0x2880 : 0x2978; {48-79} 0x4380 : 0x4478"
    indices = parse_array_indices(complex_offset)
    assert len(indices) == 3
    assert indices[0] == (0, 15)
    assert indices[1] == (16, 47)
    assert indices[2] == (48, 79)
    print("✓ Complex multi-segment patterns handled correctly")

def test_real_cmn700_pattern():
    """Test with real CMN-700 pattern from the PDF."""
    print("\nTesting real CMN-700 pattern...")
    
    lines = [
        "Table 4-123: Example register summary",
        "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8 non_hash_mem_region_reg0-63 RW 4.3.16.6 non_hash_mem_region_reg0-63 on page 1016"
    ]
    
    rows = parse_register_tables(lines)
    
    # Should generate 2 register entries
    assert len(rows) == 2
    
    # Check naming
    assert rows[0]['name'] == "non_hash_mem_region_reg0-23"
    assert rows[1]['name'] == "non_hash_mem_region_reg24-63"
    
    # Check description preserved
    expected_desc = "4.3.16.6 non_hash_mem_region_reg0-63 on page 1016"
    assert rows[0]['description'] == expected_desc
    assert rows[1]['description'] == expected_desc
    
    print("✓ Real CMN-700 pattern parsed correctly")

def main():
    """Run all validation tests."""
    print("=" * 60)
    print("CMN-700 Enhancement Validation")
    print("=" * 60)
    
    try:
        test_helper_functions()
        test_multi_segment_parsing()
        test_backward_compatibility()
        test_type_token_validation()
        test_edge_cases()
        test_real_cmn700_pattern()
        
        print("\n" + "=" * 60)
        print("✓ ALL VALIDATION TESTS PASSED")
        print("CMN-700 enhancement is working correctly!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n✗ VALIDATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)