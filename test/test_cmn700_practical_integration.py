#!/usr/bin/env python3
"""
Practical integration test for CMN-700 enhancement.
Tests register extraction against success criteria without full pipeline.
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

def test_cmn700_register_count():
    """Test CMN-700 PDF register extraction meets success criteria (≥700 registers)."""
    cmn700_pdf = "/Users/waitongsuen/work/arm_cmn/cmn_read/cmn_700_pdftk.pdf"
    
    if not os.path.exists(cmn700_pdf):
        print("❌ CMN-700 PDF not found, skipping integration test")
        return False
    
    print("🧪 Testing CMN-700 register extraction...")
    
    # Use temporary directory
    original_dir = os.getcwd()
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            os.chdir(temp_dir)
            
            # Copy PDF to temp directory
            temp_pdf = os.path.join(temp_dir, "cmn_700_pdftk.pdf")
            shutil.copy2(cmn700_pdf, temp_pdf)
            
            # Run L1 analysis
            print("  Running L1 PDF analysis...")
            result = subprocess.run([
                sys.executable,
                os.path.join(original_dir, "l1_pdf_analysis.py"),
                temp_pdf
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                print(f"❌ L1 analysis failed: {result.stderr}")
                return False
            
            # Check register count
            register_file = os.path.join(temp_dir, "L1_pdf_analysis", "all_register_summaries.csv")
            if not os.path.exists(register_file):
                print("❌ Register summary file not generated")
                return False
            
            with open(register_file, 'r') as f:
                lines = f.readlines()
                # Subtract 1 for header line
                register_count = len(lines) - 1
            
            print(f"  📊 Extracted {register_count} registers from CMN-700")
            
            # Check success criteria
            if register_count >= 700:
                print(f"✅ SUCCESS: CMN-700 extracted {register_count} registers (≥700 required)")
                return True
            else:
                print(f"❌ FAIL: CMN-700 extracted {register_count} registers (≥700 required)")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ L1 analysis timed out")
            return False
        except Exception as e:
            print(f"❌ Error during CMN-700 test: {e}")
            return False
        finally:
            os.chdir(original_dir)

def test_cmn437_backward_compatibility():
    """Test CMN-437 PDF maintains ~1043 registers (backward compatibility)."""
    cmn437_pdf = "/Users/waitongsuen/work/arm_cmn/cmn_read/cmn437-2072.pdf"
    
    if not os.path.exists(cmn437_pdf):
        print("❌ CMN-437 PDF not found, skipping backward compatibility test")
        return False
    
    print("🔄 Testing CMN-437 backward compatibility...")
    
    # Use temporary directory
    original_dir = os.getcwd()
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            os.chdir(temp_dir)
            
            # Copy PDF to temp directory
            temp_pdf = os.path.join(temp_dir, "cmn437-2072.pdf")
            shutil.copy2(cmn437_pdf, temp_pdf)
            
            # Run L1 analysis
            print("  Running L1 PDF analysis...")
            result = subprocess.run([
                sys.executable,
                os.path.join(original_dir, "l1_pdf_analysis.py"),
                temp_pdf
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                print(f"❌ L1 analysis failed: {result.stderr}")
                return False
            
            # Check register count
            register_file = os.path.join(temp_dir, "L1_pdf_analysis", "all_register_summaries.csv")
            if not os.path.exists(register_file):
                print("❌ Register summary file not generated")
                return False
            
            with open(register_file, 'r') as f:
                lines = f.readlines()
                # Subtract 1 for header line
                register_count = len(lines) - 1
            
            print(f"  📊 Extracted {register_count} registers from CMN-437")
            
            # Check backward compatibility (allow tolerance around 1043)
            if 1000 <= register_count <= 1100:
                print(f"✅ SUCCESS: CMN-437 extracted {register_count} registers (~1043 expected)")
                return True
            else:
                print(f"❌ FAIL: CMN-437 extracted {register_count} registers (~1043 expected)")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ L1 analysis timed out")
            return False
        except Exception as e:
            print(f"❌ Error during CMN-437 test: {e}")
            return False
        finally:
            os.chdir(original_dir)

def test_multi_segment_output_validation():
    """Test that multi-segment registers are properly segmented in output."""
    cmn700_pdf = "/Users/waitongsuen/work/arm_cmn/cmn_read/cmn_700_pdftk.pdf"
    
    if not os.path.exists(cmn700_pdf):
        print("❌ CMN-700 PDF not found, skipping segmentation test")
        return False
    
    print("🔍 Testing multi-segment register segmentation...")
    
    # Use temporary directory
    original_dir = os.getcwd()
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            os.chdir(temp_dir)
            
            # Copy PDF to temp directory
            temp_pdf = os.path.join(temp_dir, "cmn_700_pdftk.pdf")
            shutil.copy2(cmn700_pdf, temp_pdf)
            
            # Run L1 analysis
            result = subprocess.run([
                sys.executable,
                os.path.join(original_dir, "l1_pdf_analysis.py"),
                temp_pdf
            ], capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                print(f"❌ L1 analysis failed: {result.stderr}")
                return False
            
            # Check for segmented register names in output
            register_file = os.path.join(temp_dir, "L1_pdf_analysis", "all_register_summaries.csv")
            if not os.path.exists(register_file):
                print("❌ Register summary file not generated")
                return False
            
            segmented_registers = []
            with open(register_file, 'r') as f:
                for line in f:
                    # Look for registers with range suffixes (e.g., "reg0-23")
                    if '-' in line and any(char.isdigit() for char in line):
                        # Simple check for range pattern
                        import re
                        if re.search(r'\w+\d+-\d+', line):
                            segmented_registers.append(line.strip())
            
            print(f"  📊 Found {len(segmented_registers)} segmented registers")
            
            if len(segmented_registers) > 0:
                print("✅ SUCCESS: Multi-segment registers are properly segmented")
                print(f"  Example segmented registers: {segmented_registers[:3]}...")
                return True
            else:
                print("❌ FAIL: No segmented registers found")
                return False
                
        except Exception as e:
            print(f"❌ Error during segmentation test: {e}")
            return False
        finally:
            os.chdir(original_dir)

def main():
    """Run practical integration tests."""
    print("=" * 80)
    print("CMN-700 Enhancement - Practical Integration Tests")
    print("=" * 80)
    
    results = []
    
    # Test CMN-700 register extraction count
    results.append(test_cmn700_register_count())
    
    # Test CMN-437 backward compatibility
    results.append(test_cmn437_backward_compatibility())
    
    # Test multi-segment register segmentation
    results.append(test_multi_segment_output_validation())
    
    # Summary
    print("\n" + "=" * 80)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(results)
    total = len(results)
    
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 ALL INTEGRATION TESTS PASSED!")
        print("✅ CMN-700 enhancement meets all success criteria")
    else:
        print("❌ Some integration tests failed")
    
    print("=" * 80)
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)