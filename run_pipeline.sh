#!/bin/bash

# ARM CMN Register Extraction Pipeline
# Runs the complete L1 -> L2 -> L3 -> L4 processing pipeline
# Usage: ./run_pipeline.sh <path_to_pdf>

# Check dependencies
if ! command -v pdftotext &> /dev/null; then
    echo "Error: pdftotext is not installed. Please install poppler-utils:"
    echo "  macOS: brew install poppler"
    echo "  Ubuntu/Debian: sudo apt-get install poppler-utils"
    echo "  RHEL/CentOS: sudo yum install poppler-utils"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed."
    exit 1
fi

# Check if PDF path is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <path_to_pdf>"
    echo "Example: $0 cmn_s3ae.pdf"
    echo "Example: $0 /path/to/your/pdf_file.pdf"
    return 0 2>/dev/null || exit 0
fi

PDF_PATH="$1"

# Check if PDF file exists
if [ ! -f "$PDF_PATH" ]; then
    echo "Error: PDF file '$PDF_PATH' not found"
    return 0 2>/dev/null || exit 0
fi

set -e  # Exit on any error (after parameter validation)

echo "============================================================"
echo "ARM CMN Register Extraction Pipeline"
echo "============================================================"
echo "Input PDF: $PDF_PATH"
echo "Using pdftotext for text extraction"

# Clean build: Remove generated files (keep L1 PDF source)
echo "Cleaning previous outputs..."
rm -f L1_pdf_analysis/all_register_summaries.csv
rm -f L1_pdf_analysis/all_register_attributes.csv
rm -f L1_pdf_analysis/output.txt
rm -rf L2_csv_optimize/
rm -rf L3_cpp_generator/
rm -rf L4_Reg_generator/
echo "✓ Clean build prepared"
echo

# Step 1: L1 PDF Analysis
echo "Step 1: Running L1 PDF Analysis..."
echo "Processing PDF: $PDF_PATH"
python3 l1_pdf_analysis.py "$PDF_PATH"

if [ $? -eq 0 ]; then
    echo "✓ L1 PDF Analysis completed successfully"
else
    echo "✗ L1 PDF Analysis failed"
    exit 1
fi

echo

# Step 2: L2 CSV Optimization
echo "Step 2: Running L2 CSV Optimization..."
python3 l2_csv_optimize.py

if [ $? -eq 0 ]; then
    echo "✓ L2 CSV Optimization completed successfully"
else
    echo "✗ L2 CSV Optimization failed"
    exit 1
fi

echo

# Step 3: L3 C++ Generator (JSON)
echo "Step 3: Running L3 C++ Generator (JSON)..."
python3 l3_cpp_generator.py

if [ $? -eq 0 ]; then
    echo "✓ L3 C++ Generator completed successfully"
else
    echo "✗ L3 C++ Generator failed"
    exit 1
fi

echo

# Step 4: L4 Register Generator (Fields & Registers)
echo "Step 4: Running L4 Register Generator (Fields & Registers)..."
python3 l4_reg_generator.py

if [ $? -eq 0 ]; then
    echo "✓ L4 C++ Generator completed successfully"
else
    echo "✗ L4 C++ Generator failed"
    exit 1
fi

echo
echo "============================================================"
echo "Pipeline completed successfully!"
echo "============================================================"
echo "Output files:"
echo "  L1: L1_pdf_analysis/output.txt (extracted text)"
echo "      L1_pdf_analysis/all_register_summaries.csv"
echo "      L1_pdf_analysis/all_register_attributes.csv"
echo "  L2: L2_csv_optimize/register_summaries_optimized.csv"
echo "      L2_csv_optimize/register_attributes_optimized.csv"
echo "  L3: L3_cpp_generator/register_data.json"
echo "      L3_cpp_generator/register_summary.txt"
echo "  L4: L4_Reg_generator/field.cpp"
echo "      L4_Reg_generator/register.cpp"
echo "============================================================"