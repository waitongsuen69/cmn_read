# ARM CMN Register Extraction Pipeline

A comprehensive pipeline for extracting and processing register definitions from ARM Coherent Mesh Network (CMN) PDF documentation.

## Overview

This pipeline processes ARM technical documentation PDFs through four sequential stages to produce production-ready C++ register definitions:

- **L1**: PDF Analysis - Extract tables from PDF using `pdftotext`
- **L2**: CSV Optimization - Clean and structure data
- **L3**: JSON Generation - Create register data model
- **L4**: C++ Generation - Generate field.cpp and register.cpp

## Quick Start

### Prerequisites

```bash
# macOS
brew install poppler

# Ubuntu/Debian
sudo apt-get install poppler-utils

# RHEL/CentOS
sudo yum install poppler-utils

# Python dependencies
pip install pandas
```

### Running the Pipeline

```bash
# Process PDF through all stages
./run_pipeline.sh path/to/pdf_file.pdf

# Example with provided PDF
./run_pipeline.sh cmn437-2072.pdf
```

### Individual Stages

```bash
# L1: Extract tables from PDF
python3 l1_pdf_analysis.py path/to/pdf_file.pdf

# L1: Process from existing text file
python3 l1_pdf_analysis.py --from-text L1_pdf_analysis/output.txt

# L2: Optimize CSV data
python3 l2_csv_optimize.py

# L3: Generate JSON model
python3 l3_cpp_generator.py

# L4: Generate C++ code
python3 l4_reg_generator.py
```

## Features

### Advanced PDF Parsing (L1)
- Uses `pdftotext -layout` for table structure preservation
- Multi-pass text processing to handle complex patterns
- Handles wrapped register names and field names
- Supports multi-segment array offsets
- Filters boilerplate and page artifacts
- **Current extraction**: ~1043 registers, 7704+ attributes

### Data Processing (L2-L4)
- Array register detection and validation
- Deduplication with collision handling
- C++ identifier sanitization
- Hierarchical register block structures
- Complete bit coverage validation

## Output Structure

```
L1_pdf_analysis/
├── output.txt                    # Raw extracted text
├── output_cleaned.txt            # Cleaned text after multi-pass processing
├── all_register_summaries.csv    # Register definitions
└── all_register_attributes.csv   # Bit field definitions

L2_csv_optimize/
├── register_summaries_optimized.csv
└── register_attributes_optimized.csv

L3_cpp_generator/
├── register_data.json            # Complete data model
├── field_rename_log.json
└── register_rename_log.json

L4_Reg_generator/
├── field.cpp                     # C++ field definitions
└── register.cpp                  # C++ register structures
```

## Testing

```bash
# Test name/type separation
python3 l1_pdf_analysis.py --test

# Verify register count (expected: ~1043)
wc -l L1_pdf_analysis/all_register_summaries.csv

# Check for concatenated entries
awk -F',' '{if(length($5) > 200) print NR ":" length($5)}' L1_pdf_analysis/all_register_summaries.csv
```

## Technical Details

For comprehensive documentation including:
- Pattern matching details
- Error handling procedures
- Key function references
- Quality metrics

See [CLAUDE.md](CLAUDE.md)

## License

Proprietary - See license file for details

## Contributing

This project uses automated code generation. Please ensure all changes maintain compatibility with the pipeline stages.