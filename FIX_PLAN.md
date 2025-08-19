# Pipeline Fix Plan - Critical Issues Found

## Critical L1 Issues

### 1. Multi-line Reset Values (Affects 312+ fields)
**Problem**: Reset values like "Configuration dependent" are split across lines. Parser only captures first part "Configuration".

**Example**:
```
[35:26] snoop_request_sinkbuffer_depth ... RO Configuration
                                                dependent
```
Currently parsed as: `reset="Configuration"` 
Should be: `reset="Configuration dependent"`

### 2. Wrong Reset Values from Line Wrapping (Affects 13+ fields)  
**Problem**: Parser incorrectly extracts text fragments as reset values when lines wrap.

**Examples**:
- `Poison_On_Decode_Err` has reset="and" (grabbed from wrapped description)
- `Lock_On_Commit_#{index}` has reset="fields" 
- `CONFIG_LOCK` has reset="attribute"

### 3. Incomplete Description Parsing
**Problem**: Multi-line descriptions are not fully captured, only first line is parsed.

## L2 Issue

### Column Mapping Error
**Problem**: L2 expects field names in column 'name' but L1 provides them in column 'field_name'
- Line 536 in l2_csv_optimize.py: `row['name']` should be `row['field_name']`
- L1 outputs an empty 'name' column at the end (column 8)

## Fix Implementation Plan

### Phase 1: Fix L1 Attribute Parser
1. **Enhance multi-line handling in parse_attribute_tables()**:
   - After matching a field line, check next lines for continuations
   - If next line starts with whitespace and no bits pattern, it's a continuation
   - Concatenate reset values that span multiple lines
   - Concatenate descriptions that span multiple lines

2. **Fix reset value extraction**:
   - Look for complete "Configuration dependent" or "Implementation defined" patterns
   - Don't treat partial words as reset values
   - Validate reset values match expected patterns (hex, binary, dash, or known text values)

3. **Remove empty 'name' column from output**:
   - Update CSV header to not include redundant 'name' column
   - Only output: table, register_name, bits, field_name, description, type, reset

### Phase 2: Fix L2 Compatibility
1. **Update l2_csv_optimize.py line 536**:
   - Change from: `raw_field_name = str(row['name'])`
   - To: `raw_field_name = str(row['field_name'])`

### Phase 3: Validation
1. Run full pipeline: `./run_pipeline.sh cmn437-2072.pdf`
2. Verify outputs:
   - L1: ~1043 registers, ~7704 attributes
   - No "Configuration" without "dependent"
   - No single word reset values like "and", "fields", "attribute"
   - L2: Successful optimization
   - L3: JSON generation works
   - L4: C++ files generated

## Expected Results After Fix
- All 312 "Configuration dependent" reset values properly captured
- All 13 incorrect text reset values fixed
- Complete multi-line descriptions captured
- L2-L4 pipeline works without errors
- Clean C++ output generation