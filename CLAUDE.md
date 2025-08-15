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
# L1: PDF Analysis - Extract tables from PDF
python3 l1_pdf_analysis.py path/to/pdf_file.pdf

# L2: CSV Optimization - Clean and structure data
python3 l2_csv_optimize.py

# L3: JSON Generation - Create register data model
python3 l3_cpp_generator.py

# L4: C++ Generation - Generate field.cpp and register.cpp
python3 l4_reg_generator.py

# Verify deduplication results
python3 verify_deduplication.py
```

### Dependencies
```bash
pip install pymupdf pandas
```

## Architecture Overview

### Pipeline Stages

**L1: PDF Analysis** (`l1_pdf_analysis.py`)
- Extracts register summary and attribute tables from ARM PDFs
- Handles PDF extraction artifacts and boilerplate filtering
- Outputs: `L1_pdf_analysis/all_register_summaries.csv`, `all_register_attributes.csv`

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

1. **PDF** → Raw text extraction with PyMuPDF
2. **Text** → Table detection using regex patterns
3. **Tables** → CSV with register/field definitions
4. **CSV** → Optimized CSV with array handling
5. **Optimized CSV** → JSON data model with deduplication
6. **JSON** → C++ code generation

## Critical Implementation Details

### L1 PDF Parsing Patterns
- Table headers: `Table X-Y: <name> register summary/attributes`
- Register columns: `table_name, Offset, Name, Type, Description`
- Bit field columns: `table_name, Bits, Name, Description, Type, Reset`
- Handles 21 type token variants (RO, RW, WO, R/W, R/W1C, etc.)
- **Sub-bit filtering**: Skips sub-bit definitions (e.g., `[4]`, `[3]`) within multi-bit field descriptions to prevent false field detection

### L2 Array Register Detection
- Pattern: `{start-end} 0xSTART : 0xEND` indicates array
- Contiguity validation ensures proper memory layout
- Single-element arrays simplified to scalar registers

### L3 Deduplication Strategy
- Exact duplicates removed (same register/field/bits)
- Conflicting fields renamed with numeric suffixes
- Maintains traceability via rename logs

### L4 C++ Generation Features
- Sanitizes names for valid C++ identifiers
- Maps field types to vlab access permissions
- Handles bit ranges and reset values
- Generates hierarchical register block structures

## Output Structure

```
L1_pdf_analysis/
├── all_register_summaries.csv    # Raw register definitions
├── all_register_attributes.csv   # Raw bit field definitions
└── cmn437-2072.pdf               # Extracted PDF pages

L2_csv_optimize/
├── register_summaries_optimized.csv    # Structured registers
└── register_attributes_optimized.csv   # Structured fields

L3_cpp_generator/
├── register_data.json            # Complete data model
├── register_summary.txt          # Human-readable summary
├── field_rename_log.json         # Field modification tracking
└── register_rename_log.json      # Register modification tracking

L4_Reg_generator/
├── field.cpp                     # C++ field definitions
└── register.cpp                  # C++ register structures
```

## Validation & Debugging

### Quality Metrics
- Target: ~1045 registers (based on manual verification)
- Current accuracy: ~96% coverage
- Zero boilerplate entries expected in output
- All names follow C++ identifier conventions

### Common Issues
- **Missing registers**: Check table header patterns in L1
- **Concatenated fields**: Verify L1 split_concatenated_registers()
- **Array detection**: Check L2 check_contiguous_segments()
- **Duplicate fields**: Review L3 deduplication logs

### Verification Commands
```bash
# Check register count
wc -l L1_pdf_analysis/all_register_summaries.csv

# Find concatenated entries (lines > 200 chars)
awk -F',' '{if(length($5) > 200) print NR ":" length($5)}' L1_pdf_analysis/all_register_summaries.csv

# Verify deduplication
python3 verify_deduplication.py
```

## Key Functions Reference

### L1: PDF Analysis
- `get_all_lines()`: Extract text from PDF
- `parse_register_tables()`: Find register summary tables
- `parse_attribute_tables()`: Find bit field tables (with sub-bit detection)
- `split_concatenated_registers()`: Recover merged entries
- `clean_rows()`: Remove boilerplate and artifacts
- `is_probable_name()`: Validate field names (rejects "1-" patterns)

### L2: CSV Optimization
- `extract_reg_block_name()`: Parse table headers
- `check_contiguous_segments()`: Validate array memory layout
- `simplify_single_element_offset()`: Convert single arrays to scalars
- `parse_offset_pattern()`: Extract array indices and addresses

### L3: JSON Generation
- `deduplicate_attributes()`: Remove duplicate fields
- `deduplicate_registers()`: Handle register conflicts
- `build_register_json()`: Create hierarchical data model

### L4: C++ Generation
- `sanitize_name()`: Create valid C++ identifiers
- `parse_bits_range()`: Extract bit positions
- `get_access_and_write_effect()`: Map types to vlab parameters
- `generate_field_constructor()`: Create field initialization code