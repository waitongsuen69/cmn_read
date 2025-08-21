# L1 PDF Parser Enhancement for CMN-700 Register Extraction - Technical Specification

## Problem Statement
- **Business Issue**: L1 parser (l1_pdf_analysis.py) extracts only 11 registers from CMN-700 PDF instead of expected 700+ registers
- **Current State**: Regex patterns fail to match CMN-700 format where offset and register name have no space separator
- **Expected Outcome**: Extract ≥700 registers from CMN-700 PDF while maintaining ~1043 registers from CMN-437 PDF

## Solution Overview
- **Approach**: Modify existing regex patterns in parse_register_tables() to handle space-less offset-name format and generate segmented entries for multi-segment arrays
- **Core Changes**: Update multi_segment_match and array_match regex patterns, add segment generation logic
- **Success Criteria**: ≥700 registers extracted from CMN-700, no regression in CMN-437 extraction, no change to attribute extraction

## Technical Implementation

### Code Changes
- **Files to Modify**: `/Users/waitongsuen/work/arm_cmn/cmn_read/l1_pdf_analysis.py`
- **Function**: `parse_register_tables()` (lines 684-727)
- **Modification Type**: Update regex patterns and add segment generation logic

### Current vs Required Format
**Current CMN-700 Format** (after clean_pdf_text):
```
{0-23} 0xC00 : 0xCB8; {24-151} 0x20C0 : 0x24B8 non_hash_mem_region_reg0-127    RW    description
```

**Required Pattern Matches**:
- Multi-segment: `{0-23} 0xC00 : 0xCB8; {24-151} 0x20C0 : 0x24B8non_hash_mem_region_reg0-127`
- Single array: `{0-31} 0x3000 : 0x31F8register_name`

### Regex Pattern Updates

#### 1. Multi-segment Pattern (Line 684)
**Current**:
```python
multi_segment_match = re.match(r'^(\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+(?:\s*;\s*\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+)+)\s+(\S+)\s+(\S+)?\s*(.*)?', s)
```

**Required**:
```python
multi_segment_match = re.match(r'^(\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+(?:\s*;\s*\{[\d-]+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+)+)\s*(\S+)\s+(\S+)?\s*(.*)?', s)
```

#### 2. Single Array Pattern (Line 707)
**Current**:
```python
array_match = re.match(r'^(\{\d+-\d+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+)\s+(\S+)\s+(\S+)?\s*(.*)?', s)
```

**Required**:
```python
array_match = re.match(r'^(\{\d+-\d+\}\s+0x[0-9A-Fa-f]+\s*:\s*0x[0-9A-Fa-f]+)\s*(\S+)\s+(\S+)?\s*(.*)?', s)
```

### Segment Generation Logic

#### New Helper Functions
```python
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
```

#### Multi-segment Processing Enhancement
**Replace lines 685-704 with**:
```python
if multi_segment_match:
    offset = multi_segment_match.group(1).strip()
    name = multi_segment_match.group(2).strip()
    type_token = multi_segment_match.group(3).strip() if multi_segment_match.group(3) else "-"
    desc = multi_segment_match.group(4).strip() if multi_segment_match.group(4) else name
    
    # Validate type token
    if not is_type_token(type_token):
        desc = type_token + " " + desc if type_token != "-" else desc
        type_token = "-"
    
    # Parse array indices for segment generation
    indices = parse_array_indices(offset)
    
    if len(indices) > 1:
        # Generate separate entries for each segment
        for idx, (start, end) in enumerate(indices):
            segment_offset = extract_segment_offset(offset, idx)
            segment_name = generate_segmented_register_name(name, start, end)
            
            rows.append({
                "table": current_table,
                "offset": segment_offset,
                "name": segment_name,
                "type": type_token,
                "description": desc,
            })
    else:
        # Single segment - use as-is
        rows.append({
            "table": current_table,
            "offset": offset,
            "name": name,
            "type": type_token,
            "description": desc,
        })
    
    i += 1
    continue
```

### Configuration Changes
- **No new settings required**
- **No environment variables needed**
- **No feature flags required**

## Implementation Sequence

### Phase 1: Regex Pattern Updates
- Update multi_segment_match regex pattern (line 684) to remove mandatory space before register name
- Update array_match regex pattern (line 707) for consistency
- Test basic pattern matching with CMN-700 format

### Phase 2: Helper Function Implementation
- Add parse_array_indices() function before parse_register_tables()
- Add extract_segment_offset() function for multi-segment parsing
- Add generate_segmented_register_name() function for name generation

### Phase 3: Segment Generation Logic
- Replace multi-segment processing block (lines 685-704) with segment generation logic
- Test with CMN-700 PDF to verify segment creation
- Validate backward compatibility with CMN-437 PDF

## Validation Plan

### Unit Tests
- **Pattern Matching**: Verify regex patterns match CMN-700 format without spaces
- **Segment Generation**: Test parse_array_indices() with various patterns
- **Name Generation**: Validate generate_segmented_register_name() output format

### Integration Tests
- **CMN-700 Extraction**: Run full pipeline and verify ≥700 registers extracted
- **CMN-437 Compatibility**: Ensure ~1043 registers still extracted from CMN-437
- **Attribute Extraction**: Verify no regression in field extraction (~7704 fields)

### Business Logic Verification
- **Register Count**: `wc -l L1_pdf_analysis/all_register_summaries.csv` shows ≥700 increase
- **Segment Format**: Grep for segmented names like `non_hash_mem_region_reg0-23`
- **No Concatenation**: Verify no entries >200 characters in output
- **Type Token Validation**: Ensure all extracted registers have valid type tokens

### Validation Commands
```bash
# Test with CMN-700 PDF
python3 l1_pdf_analysis.py cmn_700_pdftk.pdf

# Verify register count increase
wc -l L1_pdf_analysis/all_register_summaries.csv

# Check for segmented register names
grep -E "reg\d+-\d+" L1_pdf_analysis/all_register_summaries.csv

# Verify backward compatibility with CMN-437
python3 l1_pdf_analysis.py cmn437-2072.pdf
wc -l L1_pdf_analysis/all_register_summaries.csv  # Should still show ~1043
```

## Key Constraints

### MUST Requirements
- **Exact Pattern Match**: Modified regex must handle both spaced and space-less formats
- **Segment Generation**: Multi-segment arrays must create separate register entries
- **Backward Compatibility**: CMN-437 extraction must remain unchanged
- **Type Token Validation**: All existing type validation logic must be preserved

### MUST NOT Requirements
- **No Breaking Changes**: Existing single-segment and range patterns must work unchanged
- **No Attribute Changes**: Field extraction logic must remain untouched
- **No Output Format Changes**: CSV column structure must remain identical
- **No Performance Degradation**: Processing time should not increase significantly