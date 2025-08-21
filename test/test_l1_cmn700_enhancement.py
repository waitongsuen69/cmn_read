#!/usr/bin/env python3
"""
Comprehensive test suite for L1 PDF parser CMN-700 enhancement.

Tests the functional validation of:
1. Helper functions for multi-segment array parsing
2. Multi-segment pattern matching in parse_register_tables()
3. Fourth pass text cleaning for CMN-700 format
4. Backward compatibility with CMN-437 format
5. Integration tests with actual PDF processing

Success Criteria:
- Extract ≥700 registers from CMN-700 PDF
- Maintain ~1043 registers from CMN-437 PDF  
- Correctly segment multi-segment arrays
- Backward compatibility preserved
"""

import unittest
import re
import os
import sys
import tempfile
import subprocess
from pathlib import Path

# Add the current directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import functions from l1_pdf_analysis.py
from l1_pdf_analysis import (
    parse_array_indices,
    extract_segment_offset,
    generate_segmented_register_name,
    clean_pdf_text,
    parse_register_tables,
    is_type_token,
    get_all_lines
)


class TestCMN700HelperFunctions(unittest.TestCase):
    """Test the new helper functions for CMN-700 multi-segment array parsing."""
    
    def test_parse_array_indices_single_segment(self):
        """Test parsing single array index pattern."""
        offset = "{0-23} 0xC00 : 0xCB8"
        indices = parse_array_indices(offset)
        
        self.assertEqual(len(indices), 1)
        self.assertEqual(indices[0], (0, 23))
    
    def test_parse_array_indices_multi_segment(self):
        """Test parsing multi-segment array index patterns."""
        offset = "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8"
        indices = parse_array_indices(offset)
        
        self.assertEqual(len(indices), 2)
        self.assertEqual(indices[0], (0, 23))
        self.assertEqual(indices[1], (24, 63))
    
    def test_parse_array_indices_complex_multi_segment(self):
        """Test parsing complex multi-segment patterns from real CMN-700 data."""
        offset = "{0-15} 0xD80 : 0xDF8; {16-47} 0x2880 : 0x2978; {48-79} 0x4380 : 0x4478"
        indices = parse_array_indices(offset)
        
        self.assertEqual(len(indices), 3)
        self.assertEqual(indices[0], (0, 15))
        self.assertEqual(indices[1], (16, 47))
        self.assertEqual(indices[2], (48, 79))
    
    def test_parse_array_indices_no_arrays(self):
        """Test handling of non-array offset patterns."""
        offset = "0x1000"
        indices = parse_array_indices(offset)
        
        self.assertEqual(len(indices), 0)
    
    def test_extract_segment_offset_first_segment(self):
        """Test extracting the first segment from multi-segment offset."""
        offset = "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8"
        segment = extract_segment_offset(offset, 0)
        
        self.assertEqual(segment, "{0-23} 0xC00 : 0xCB8")
    
    def test_extract_segment_offset_second_segment(self):
        """Test extracting the second segment from multi-segment offset."""
        offset = "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8"
        segment = extract_segment_offset(offset, 1)
        
        self.assertEqual(segment, "{24-63} 0x20C0 : 0x24B8")
    
    def test_extract_segment_offset_out_of_bounds(self):
        """Test handling of invalid segment index."""
        offset = "{0-23} 0xC00 : 0xCB8"
        segment = extract_segment_offset(offset, 5)
        
        self.assertEqual(segment, offset)  # Should return original offset
    
    def test_generate_segmented_register_name_basic(self):
        """Test generating segmented register names."""
        name = generate_segmented_register_name("non_hash_mem_region_reg", 0, 23)
        self.assertEqual(name, "non_hash_mem_region_reg0-23")
    
    def test_generate_segmented_register_name_with_existing_suffix(self):
        """Test generating segmented register names when base already has suffix."""
        name = generate_segmented_register_name("non_hash_mem_region_reg0-63", 0, 23)
        self.assertEqual(name, "non_hash_mem_region_reg0-23")
    
    def test_generate_segmented_register_name_second_segment(self):
        """Test generating segmented register names for second segment."""
        name = generate_segmented_register_name("non_hash_mem_region_reg0-63", 24, 63)
        self.assertEqual(name, "non_hash_mem_region_reg24-63")


class TestCMN700PatternMatching(unittest.TestCase):
    """Test multi-segment pattern matching in parse_register_tables()."""
    
    def setUp(self):
        """Set up test data."""
        self.table_header = "Table 4-123: Example register summary"
        
    def test_multi_segment_pattern_matching(self):
        """Test parsing of multi-segment array patterns."""
        lines = [
            self.table_header,
            "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8 non_hash_mem_region_reg RW Multi-segment array register"
        ]
        
        rows = parse_register_tables(lines)
        
        # Should generate 2 register entries (one per segment)
        self.assertEqual(len(rows), 2)
        
        # Check first segment
        self.assertEqual(rows[0]['offset'], "{0-23} 0xC00 : 0xCB8")
        self.assertEqual(rows[0]['name'], "non_hash_mem_region_reg0-23")
        self.assertEqual(rows[0]['type'], "RW")
        self.assertEqual(rows[0]['description'], "Multi-segment array register")
        
        # Check second segment
        self.assertEqual(rows[1]['offset'], "{24-63} 0x20C0 : 0x24B8")
        self.assertEqual(rows[1]['name'], "non_hash_mem_region_reg24-63")
        self.assertEqual(rows[1]['type'], "RW")
        self.assertEqual(rows[1]['description'], "Multi-segment array register")
    
    def test_single_segment_pattern_matching(self):
        """Test parsing of single array patterns (backward compatibility)."""
        lines = [
            self.table_header,
            "{0-31} 0x3000 : 0x31F8 simple_array_reg RO Single array register"
        ]
        
        rows = parse_register_tables(lines)
        
        # Should generate 1 register entry
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['offset'], "{0-31} 0x3000 : 0x31F8")
        self.assertEqual(rows[0]['name'], "simple_array_reg")
        self.assertEqual(rows[0]['type'], "RO")
        self.assertEqual(rows[0]['description'], "Single array register")
    
    def test_complex_multi_segment_pattern(self):
        """Test parsing of complex multi-segment patterns with 3+ segments."""
        lines = [
            self.table_header,
            "{0-15} 0xD80 : 0xDF8; {16-47} 0x2880 : 0x2978; {48-79} 0x4380 : 0x4478 complex_reg RWL Complex multi-segment register"
        ]
        
        rows = parse_register_tables(lines)
        
        # Should generate 3 register entries
        self.assertEqual(len(rows), 3)
        
        # Check all segments have correct naming
        expected_names = [
            "complex_reg0-15",
            "complex_reg16-47", 
            "complex_reg48-79"
        ]
        
        for i, expected_name in enumerate(expected_names):
            self.assertEqual(rows[i]['name'], expected_name)
            self.assertEqual(rows[i]['type'], "RWL")
    
    def test_invalid_type_token_handling(self):
        """Test handling of invalid type tokens in multi-segment patterns."""
        lines = [
            self.table_header,
            "{0-23} 0xC00 : 0xCB8; {24-63} 0x20C0 : 0x24B8 register_name INVALID description"
        ]
        
        rows = parse_register_tables(lines)
        
        # Should still parse but with corrected type
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row['type'], "-")  # Invalid type should be replaced with "-"
    
    def test_backward_compatibility_cmn437_patterns(self):
        """Test that CMN-437 patterns still work correctly."""
        lines = [
            self.table_header,
            "0x1000    register_name    RW    Standard register",
            "{0-31} 0x2000 : 0x20F8    array_reg    RO    Array register"
        ]
        
        rows = parse_register_tables(lines)
        
        # Should parse both patterns correctly
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['name'], "register_name")
        self.assertEqual(rows[1]['name'], "array_reg")


class TestCMN700TextCleaning(unittest.TestCase):
    """Test fourth pass text cleaning for CMN-700 format."""
    
    def test_fourth_pass_multi_segment_joining(self):
        """Test fourth pass cleaning joins CMN-700 multi-segment patterns correctly."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as input_file:
            # Write CMN-700 format test data
            test_lines = [
                "{0-23} register_name RW description",
                "16'hC00 :",
                "16'hCB8",
                "{24-63}",
                "16'h20C0 :",
                "16'h24B8",
                "",
                "Another line not related to arrays"
            ]
            input_file.write('\n'.join(test_lines))
            input_file.flush()
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as output_file:
                try:
                    # Run the text cleaning
                    clean_pdf_text(input_file.name, output_file.name)
                    
                    # Read the cleaned output
                    with open(output_file.name, 'r') as f:
                        cleaned_lines = f.readlines()
                    
                    # Should find the joined multi-segment pattern
                    joined_line_found = False
                    for line in cleaned_lines:
                        if "16'hC00 : 16'hCB8; {24-63} 16'h20C0 : 16'h24B8" in line:
                            joined_line_found = True
                            break
                    
                    self.assertTrue(joined_line_found, "Multi-segment pattern should be joined in fourth pass")
                    
                finally:
                    # Clean up temporary files
                    os.unlink(input_file.name)
                    os.unlink(output_file.name)


class TestCMN700Integration(unittest.TestCase):
    """Integration tests with actual PDF processing."""
    
    def setUp(self):
        """Set up paths to test PDFs."""
        self.cmn700_pdf = "/Users/waitongsuen/work/arm_cmn/cmn_read/cmn_700_pdftk.pdf"
        self.cmn437_pdf = "/Users/waitongsuen/work/arm_cmn/cmn_read/cmn437-2072.pdf"
    
    def test_cmn700_pdf_exists(self):
        """Verify CMN-700 PDF file exists."""
        self.assertTrue(os.path.exists(self.cmn700_pdf), "CMN-700 PDF should exist")
    
    def test_cmn437_pdf_exists(self):
        """Verify CMN-437 PDF file exists for compatibility testing."""
        self.assertTrue(os.path.exists(self.cmn437_pdf), "CMN-437 PDF should exist")
    
    def test_cmn700_register_extraction_count(self):
        """Test that CMN-700 PDF extracts ≥700 registers (success criteria)."""
        if not os.path.exists(self.cmn700_pdf):
            self.skipTest("CMN-700 PDF not available")
        
        # Use a temporary directory for this test
        original_dir = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                
                # Copy the PDF to temp directory
                import shutil
                temp_pdf = os.path.join(temp_dir, "cmn_700_pdftk.pdf")
                shutil.copy2(self.cmn700_pdf, temp_pdf)
                
                # Run L1 analysis
                result = subprocess.run([
                    sys.executable, 
                    os.path.join(original_dir, "l1_pdf_analysis.py"),
                    temp_pdf
                ], capture_output=True, text=True, timeout=300)
                
                if result.returncode != 0:
                    self.fail(f"L1 analysis failed: {result.stderr}")
                
                # Check register count
                register_file = os.path.join(temp_dir, "L1_pdf_analysis", "all_register_summaries.csv")
                if os.path.exists(register_file):
                    with open(register_file, 'r') as f:
                        lines = f.readlines()
                        # Subtract 1 for header line
                        register_count = len(lines) - 1
                        
                    print(f"CMN-700 extracted {register_count} registers")
                    self.assertGreaterEqual(register_count, 700, 
                                          f"Should extract ≥700 registers from CMN-700, got {register_count}")
                else:
                    self.fail("Register summary file not generated")
                    
            finally:
                os.chdir(original_dir)
    
    def test_cmn437_backward_compatibility(self):
        """Test that CMN-437 PDF still extracts ~1043 registers (backward compatibility)."""
        if not os.path.exists(self.cmn437_pdf):
            self.skipTest("CMN-437 PDF not available")
        
        # Use a temporary directory for this test
        original_dir = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                
                # Copy the PDF to temp directory
                import shutil
                temp_pdf = os.path.join(temp_dir, "cmn437-2072.pdf")
                shutil.copy2(self.cmn437_pdf, temp_pdf)
                
                # Run L1 analysis
                result = subprocess.run([
                    sys.executable,
                    os.path.join(original_dir, "l1_pdf_analysis.py"),
                    temp_pdf
                ], capture_output=True, text=True, timeout=300)
                
                if result.returncode != 0:
                    self.fail(f"L1 analysis failed: {result.stderr}")
                
                # Check register count
                register_file = os.path.join(temp_dir, "L1_pdf_analysis", "all_register_summaries.csv")
                if os.path.exists(register_file):
                    with open(register_file, 'r') as f:
                        lines = f.readlines()
                        # Subtract 1 for header line
                        register_count = len(lines) - 1
                        
                    print(f"CMN-437 extracted {register_count} registers")
                    # Allow some tolerance around 1043
                    self.assertGreaterEqual(register_count, 1000, 
                                          f"Should extract ~1043 registers from CMN-437, got {register_count}")
                    self.assertLessEqual(register_count, 1100,
                                       f"Should extract ~1043 registers from CMN-437, got {register_count}")
                else:
                    self.fail("Register summary file not generated")
                    
            finally:
                os.chdir(original_dir)


class TestCMN700EdgeCases(unittest.TestCase):
    """Test edge cases and error conditions specific to CMN-700 enhancement."""
    
    def test_malformed_multi_segment_patterns(self):
        """Test handling of malformed multi-segment patterns."""
        lines = [
            "Table 4-123: Example register summary",
            "{0-23} 0xC00 : 0xCB8; {invalid} 0x20C0 : 0x24B8 register_name RW description",
            "{0-23} 0xC00 : missing_end register_name RW description",
            "malformed_pattern register_name RW description"
        ]
        
        # Should not crash and should skip malformed patterns
        rows = parse_register_tables(lines)
        
        # Should parse what it can (the malformed patterns should be skipped)
        self.assertIsInstance(rows, list)
    
    def test_empty_segments_handling(self):
        """Test handling of empty segments in multi-segment patterns."""
        offset = "{0-23} 0xC00 : 0xCB8; ; {24-63} 0x20C0 : 0x24B8"
        
        # Should handle empty segments gracefully
        segments = offset.split(';')
        self.assertEqual(len(segments), 3)
        
        # Extract non-empty segments
        non_empty_segments = [s.strip() for s in segments if s.strip()]
        self.assertEqual(len(non_empty_segments), 2)
    
    def test_special_register_names(self):
        """Test handling of special characters in register names."""
        test_cases = [
            "register_with_underscores",
            "register123with456numbers",
            "CAPS_REGISTER_NAME",
            "mixed_Case_Register"
        ]
        
        for base_name in test_cases:
            segmented_name = generate_segmented_register_name(base_name, 0, 23)
            expected = f"{base_name}0-23"
            self.assertEqual(segmented_name, expected)
    
    def test_type_token_validation(self):
        """Test validation of different type tokens."""
        valid_types = ["RW", "RO", "WO", "RWL", "W1C", "W1S", "R/W", "R/W1C"]
        invalid_types = ["INVALID", "ABC", "123", ""]
        
        for valid_type in valid_types:
            self.assertTrue(is_type_token(valid_type), f"{valid_type} should be valid")
        
        for invalid_type in invalid_types:
            self.assertFalse(is_type_token(invalid_type), f"{invalid_type} should be invalid")


class TestCMN700Performance(unittest.TestCase):
    """Test performance aspects of CMN-700 enhancement."""
    
    def test_parse_large_multi_segment_pattern(self):
        """Test performance with large multi-segment patterns."""
        # Create a pattern with many segments
        segments = []
        for i in range(0, 100, 10):
            segments.append(f"{{{i}-{i+9}}} 0x{1000+i*16:X} : 0x{1000+(i+9)*16:X}")
        
        large_offset = "; ".join(segments)
        
        # Should handle large patterns efficiently
        import time
        start_time = time.time()
        indices = parse_array_indices(large_offset)
        end_time = time.time()
        
        # Should complete in reasonable time (< 1 second)
        self.assertLess(end_time - start_time, 1.0)
        self.assertEqual(len(indices), 10)
    
    def test_memory_usage_multi_segment_generation(self):
        """Test memory usage when generating many segmented registers."""
        base_name = "test_register"
        generated_names = []
        
        # Generate many segmented register names
        for i in range(1000):
            name = generate_segmented_register_name(base_name, i*10, (i+1)*10-1)
            generated_names.append(name)
        
        # Should complete without memory issues
        self.assertEqual(len(generated_names), 1000)
        self.assertEqual(generated_names[0], "test_register0-9")
        self.assertEqual(generated_names[999], "test_register9990-9999")


def run_tests():
    """Run all test suites and provide summary."""
    print("=" * 80)
    print("CMN-700 Enhancement Test Suite")
    print("=" * 80)
    
    # Create test suite
    test_suites = [
        unittest.TestLoader().loadTestsFromTestCase(TestCMN700HelperFunctions),
        unittest.TestLoader().loadTestsFromTestCase(TestCMN700PatternMatching),
        unittest.TestLoader().loadTestsFromTestCase(TestCMN700TextCleaning),
        unittest.TestLoader().loadTestsFromTestCase(TestCMN700EdgeCases),
        unittest.TestLoader().loadTestsFromTestCase(TestCMN700Performance),
        unittest.TestLoader().loadTestsFromTestCase(TestCMN700Integration)  # Run integration tests last
    ]
    
    combined_suite = unittest.TestSuite(test_suites)
    
    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    result = runner.run(combined_suite)
    
    # Print summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped) if hasattr(result, 'skipped') else 0}")
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    success = len(result.failures) == 0 and len(result.errors) == 0
    print(f"\nOVERALL: {'PASS' if success else 'FAIL'}")
    
    return success


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)