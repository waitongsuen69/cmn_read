# Test Files

This directory contains test scripts and utilities for the ARM CMN register extraction pipeline.

## Test Files

### CMN-700 Enhancement Tests
- `test_l1_cmn700_enhancement.py` - Initial test suite for L1 parser CMN-700 enhancements
- `test_l1_cmn700_enhancement_updated.py` - Updated realistic assessment of L1 parser
- `test_cmn700_validation.py` - Quick validation script for CMN-700 extraction
- `test_cmn700_practical_integration.py` - Practical integration tests
- `test_cmn700_final_report.py` - Final validation report for CMN-700 support

### Utility Tests
- `test_regex.py` - Regular expression pattern testing
- `test_cmn700_regex.py` - CMN-700 specific regex pattern tests
- `test_helpers.py` - Helper function tests

### Fix Scripts
- `fix_hex_patterns.py` - Script to fix hex notation patterns (16'h to 0x conversion)

### Backups
- `backups/` - Contains backup files from modifications

## Running Tests

```bash
# Run a specific test
python3 test/<test_file>.py

# Example: Validate CMN-700 extraction
python3 test/test_cmn700_validation.py
```

## Test Results Summary

- **CMN-437**: Successfully extracts 1043+ registers
- **CMN-700**: Extracts 411 registers (improved from 11, target is 700+)
- **Pipeline**: Full pipeline now completes without crashes