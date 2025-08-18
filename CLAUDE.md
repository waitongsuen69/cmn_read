# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ARM CMN (Coherent Mesh Network) register extraction pipeline that parses PDF documentation to extract register information, optimize it, and generate C++ code. The pipeline processes ARM technical documentation through four sequential stages (L1→L2→L3→L4) to produce production-ready C++ register definitions.

## Key Commands

### Run Complete Pipeline
```bash
# Process PDF through all stages (L1→L2→L3→L4)
./run_pipeline.sh path/to/pdf_file.pdf

# Example with provided PDF
./run_pipeline.sh cmn437-2072.pdf
```

### Run Individual Stages
```bash
# L1: PDF Analysis - Extract tables from PDF using pdftotext
python3 l1_pdf_analysis.py path/to/pdf_file.pdf

# L1: Alternative - Process from existing text file
python3 l1_pdf_analysis.py --from-text L1_pdf_analysis/output.txt

# L2: CSV Optimization - Clean and structure data  
python3 l2_csv_optimize.py

# L3: JSON Generation - Create register data model
python3 l3_cpp_generator.py

# L4: C++ Generation - Generate field.cpp and register.cpp
python3 l4_reg_generator.py
```

### Testing & Validation
```bash
# Test name/type separation fix in L1
python3 l1_pdf_analysis.py --test

# Check register count (current: 1043 registers from cmn437-2072.pdf)
wc -l L1_pdf_analysis/all_register_summaries.csv

# Find concatenated entries (lines > 200 chars)
awk -F',' '{if(length($5) > 200) print NR ":" length($5)}' L1_pdf_analysis/all_register_summaries.csv

# Verify no boilerplate in output
grep -i "non-confidential\|arm limited\|technical reference" L1_pdf_analysis/all_register_summaries.csv

# Check for multi-segment array registers (should find entries with semicolons)
grep "; {" L1_pdf_analysis/all_register_summaries.csv
```

### Dependencies
```bash
# System dependencies
# macOS:
brew install poppler

# Ubuntu/Debian:
sudo apt-get install poppler-utils

# RHEL/CentOS:
sudo yum install poppler-utils

# Python dependencies
pip install pandas
```

## Architecture Overview

### Pipeline Stages

**L1: PDF Analysis** (`l1_pdf_analysis.py`)
- Uses `pdftotext -layout` to extract structured text from PDFs
- Extracts register summary and attribute tables from the text
- Handles PDF extraction artifacts and boilerplate filtering
- Outputs: `L1_pdf_analysis/output.txt` (extracted text), `all_register_summaries.csv`, `all_register_attributes.csv`

**L2: CSV Optimization** (`l2_csv_optimize.py`)
- Transforms raw CSV data into structured format
- Handles array registers and multi-segment offsets
- Simplifies single-element arrays and validates contiguous segments
- Outputs: `L2_csv_optimize/register_summaries_optimized.csv`, `register_attributes_optimized.csv`

**L3: JSON Generation** (`l3_cpp_generator.py`)
- Deduplicates registers and fields
- Creates comprehensive JSON data model
- Generates rename logs for tracking modifications
- Outputs: `L3_cpp_generator/register_data.json`, field/register rename logs

**L4: C++ Generation** (`l4_reg_generator.py`)
- Generates production C++ code from JSON model
- Creates both field definitions and register structures
- Handles access permissions and write effects
- Outputs: `L4_Reg_generator/field.cpp`, `register.cpp`

### Data Flow

1. **PDF** → Text extraction with `pdftotext -layout` (preserves table structure)
2. **Text file** → Table detection using regex patterns
3. **Tables** → CSV with register/field definitions
4. **CSV** → Optimized CSV with array handling
5. **Optimized CSV** → JSON data model with deduplication
6. **JSON** → C++ code generation

## Critical Implementation Details

### L1 PDF Parsing Patterns
- Table headers: `Table X-Y: <name> register summary/attributes`
- Register columns: `table_name, Offset, Name, Type, Description`
- Bit field columns: `table_name, Bits, Name, Description, Type, Reset`
- Handles 21 type token variants (RO, RW, WO, R/W, R/W1C, RWL, etc.)
- **Complex offset formats**: Supports ranges (`0x100 : 0x200`), arrays (`{0-31} 0x3000 : 0x30F8`), offset+size (`0xC00 + 0x80`), and multi-segment arrays
- **Multi-pass text processing**: Three-phase approach for handling split patterns across lines
- **Sub-bit filtering**: Skips sub-bit definitions (e.g., `[4]`, `[3]`) within multi-bit field descriptions to prevent false field detection
- **Reserved concatenation artifacts**: Filters PDF extraction artifacts where "Reserved" concatenates with following content without spaces
- **Boilerplate filtering**: Removes document metadata and header/footer noise using multiple pattern sets
- **Multi-segment array parsing**: Handles complex patterns like `{0-23} 0xCC0 : 0xD78; {24-151} 0x24C0 : 0x28B8`
- **Wrapped register pattern handling**: Fixes cases where array indices and partial register names appear first, with offset information on subsequent lines (e.g., `{0-1} partial_name...` followed by `0x37E0 cfg_reg0-1`, `:`, `0x37E8`)

### L2 Array Register Detection
- Pattern: `{start-end} 0xSTART : 0xEND` indicates array
- Contiguity validation ensures proper memory layout
- Single-element arrays simplified to scalar registers
- Multi-segment offset handling with stride calculation

### L3 Deduplication Strategy
- Exact duplicates removed (same register/field/bits)
- Conflicting fields renamed with numeric suffixes
- Sanitized name collision detection (handles C++ identifier rules)
- Maintains traceability via rename logs

### L4 C++ Generation Features
- Sanitizes names for valid C++ identifiers
- Maps field types to vlab access permissions
- Handles bit ranges and reset values
- Generates hierarchical register block structures
- Special handling for RWL (Read-Write Lock) fields

## Output Structure

```
L1_pdf_analysis/
├── output.txt                    # Extracted text from pdftotext
├── all_register_summaries.csv    # Raw register definitions
├── all_register_attributes.csv   # Raw bit field definitions
└── cmn437-2072.pdf               # Original PDF (if copied)

L2_csv_optimize/
├── register_summaries_optimized.csv    # Structured registers
└── register_attributes_optimized.csv   # Structured fields

L3_cpp_generator/
├── register_data.json            # Complete data model
├── register_summary.txt          # Human-readable summary
├── field_rename_log.json         # Field modification tracking
├── register_rename_log.json      # Register modification tracking
├── register_summaries_deduplicated.csv
├── register_attributes_deduplicated.csv
└── unmatched_fields.log          # Fields without matching registers

L4_Reg_generator/
├── field.cpp                     # C++ field definitions
└── register.cpp                  # C++ register structures
```

## Error Handling & Recovery

### Clean Build Process
The pipeline performs a clean build by default, removing:
- Previous CSV outputs from L1
- All L2, L3, and L4 output directories
- Preserves the source PDF in L1_pdf_analysis/

### Common Issues & Solutions

**Missing registers**
- Check table header patterns in L1
- Verify PDF page extraction in `get_all_lines()`
- Look for boilerplate filtering false positives

**Concatenated fields**
- Verify L1 `split_concatenated_registers()`
- Check for Reserved concatenation artifacts
- Review address-name separation logic

**Array detection failures**
- Check L2 `check_contiguous_segments()`
- Verify stride calculation logic
- Review multi-segment offset patterns
- Ensure L1 `clean_pdf_text()` properly joins split array patterns

**Duplicate field conflicts**
- Review L3 deduplication logs
- Check sanitized name collision handling
- Verify field rename logic

**Invalid C++ identifiers**
- Check `sanitize_name()` function
- Review leading digit handling
- Verify underscore cleanup

## Key Functions Reference

### L1: PDF Analysis
- `get_all_lines()`: Extract text from PDF using pdftotext command
- `clean_pdf_text()`: Three-pass text cleaning for complex patterns (split offsets, multi-segment arrays, wrapped lines)
- `parse_register_tables()`: Find register summary tables with enhanced pattern detection
- `parse_attribute_tables()`: Find bit field tables with sub-bit detection
- `split_concatenated_registers()`: Recover merged entries
- `clean_rows()`: Remove boilerplate and artifacts
- `is_probable_name()`: Validate field names (rejects "1-" patterns)
- `is_reserved_concatenation_artifact()`: Filter Reserved concatenation artifacts
- `remove_spurious_reserved_entries()`: Post-process to remove false Reserved entries

### L2: CSV Optimization
- `extract_reg_block_name()`: Parse table headers
- `check_contiguous_segments()`: Validate array memory layout
- `simplify_single_element_offset()`: Convert single arrays to scalars
- `parse_offset_pattern()`: Extract array indices and addresses
- `determine_register_size()`: Calculate 32-bit vs 64-bit registers

### L3: JSON Generation
- `deduplicate_attributes()`: Remove duplicate fields with collision handling
- `deduplicate_registers()`: Handle register conflicts
- `build_register_json()`: Create hierarchical data model
- `sanitize_name()`: Ensure C++ identifier validity

### L4: C++ Generation
- `sanitize_name()`: Create valid C++ identifiers
- `parse_bits_range()`: Extract bit positions
- `get_access_and_write_effect()`: Map types to vlab parameters
- `generate_field_constructor()`: Create field initialization code
- `generate_field_cpp()`: Generate all field definitions
- `generate_register_cpp()`: Generate register structures

## Quality Metrics & Validation

### Expected Outputs
- 1043 registers from cmn437-2072.pdf (includes complex multi-segment arrays)
- Zero boilerplate entries in final output
- All names follow C++ identifier conventions
- No concatenated entries over 200 characters
- Support for all offset formats (ranges, arrays, offset+size, multi-segment)
- Clean text extraction in `L1_pdf_analysis/output.txt` and `output_cleaned.txt`

### Validation Points
1. **L1 Output**: Check for boilerplate, concatenations, and count
2. **L2 Output**: Verify array detection and contiguity
3. **L3 Output**: Review deduplication logs and unmatched fields
4. **L4 Output**: Compile generated C++ code for syntax validation