#!/usr/bin/env python3
"""Fix all hex patterns in l1_pdf_analysis.py to support both 0x and 16'h notation"""

# Read the file
with open('l1_pdf_analysis.py', 'r') as f:
    lines = f.readlines()

# Process line by line
updated_lines = []
for line in lines:
    # Fix offset_re pattern
    if "offset_re  = re.compile(r'^0x[0-9A-Fa-f]+$')" in line:
        line = "offset_re  = re.compile(r'^(?:0x|16\\'h)[0-9A-Fa-f]+$')\n"
    
    # Fix array_offset_re pattern 
    elif "array_offset_re = re.compile(r'^\\{\\d+-\\d+\\}\\s+0x[0-9A-Fa-f]+\\s*:\\s*0x[0-9A-Fa-f]+')" in line:
        line = "array_offset_re = re.compile(r'^\\{\\d+-\\d+\\}\\s+(?:0x|16\\'h)[0-9A-Fa-f]+\\s*:\\s*(?:0x|16\\'h)[0-9A-Fa-f]+')\n"
    
    # Fix simple_offset_re pattern
    elif "simple_offset_re = re.compile(r'^0x[0-9A-Fa-f]+(?:\\s*:\\s*0x[0-9A-Fa-f]+)?')" in line:
        line = "simple_offset_re = re.compile(r'^(?:0x|16\\'h)[0-9A-Fa-f]+(?:\\s*:\\s*(?:0x|16\\'h)[0-9A-Fa-f]+)?')\n"
    
    # Fix addr_token_re
    elif "addr_token_re = r'(?:\\{\\s*\\d+(?:\\s*-\\s*\\d+)?\\s*\\}|0x[0-9A-Fa-f]+|:|,|–|-)'" in line:
        line = "addr_token_re = r'(?:\\{\\s*\\d+(?:\\s*-\\s*\\d+)?\\s*\\}|(?:0x|16\\'h)[0-9A-Fa-f]+|:|,|–|-)'\n"
    
    # Fix patterns in clean_pdf_text and other functions
    # Replace 0x[0-9A-Fa-f]+ with (?:0x|16'h)[0-9A-Fa-f]+
    elif "re.match(r'" in line and "0x[0-9A-Fa-f]+" in line:
        line = line.replace("0x[0-9A-Fa-f]+", "(?:0x|16\\'h)[0-9A-Fa-f]+")
    
    # Fix patterns in parse_register_tables
    elif "multi_segment_match = re.match(" in line:
        line = "        multi_segment_match = re.match(r'^(\\{[\\d-]+\\}\\s+(?:0x|16\\'h)[0-9A-Fa-f]+\\s*:\\s*(?:0x|16\\'h)[0-9A-Fa-f]+(?:\\s*;\\s*\\{[\\d-]+\\}\\s+(?:0x|16\\'h)[0-9A-Fa-f]+\\s*:\\s*(?:0x|16\\'h)[0-9A-Fa-f]+)+)\\s*(\\S+)\\s+(\\S+)?\\s*(.*)?', s)\n"
    
    elif "array_match = re.match(r'^(\\{\\d+-\\d+\\}\\s+0x[0-9A-Fa-f]+\\s*:\\s*0x[0-9A-Fa-f]+)" in line:
        line = "        array_match = re.match(r'^(\\{\\d+-\\d+\\}\\s+(?:0x|16\\'h)[0-9A-Fa-f]+\\s*:\\s*(?:0x|16\\'h)[0-9A-Fa-f]+)\\s*(\\S+)\\s+(\\S+)?\\s*(.*)?', s)\n"
    
    elif "range_match = re.match(r'^(0x[0-9A-Fa-f]+\\s*:\\s*0x[0-9A-Fa-f]+)" in line:
        line = "        range_match = re.match(r'^((?:0x|16\\'h)[0-9A-Fa-f]+\\s*:\\s*(?:0x|16\\'h)[0-9A-Fa-f]+)\\s+(\\S+)\\s+(\\S+)?\\s*(.*)?', s)\n"
    
    elif "offset_plus_match = re.match(r'^(0x[0-9A-Fa-f]+\\s*\\+\\s*0x[0-9A-Fa-f]+)" in line:
        line = "        offset_plus_match = re.match(r'^((?:0x|16\\'h)[0-9A-Fa-f]+\\s*\\+\\s*(?:0x|16\\'h)[0-9A-Fa-f]+)\\s+(\\S+)\\s+(\\S+)?\\s*(.*)?', s)\n"
    
    elif "simple_match = re.match(r'^(0x[0-9A-Fa-f]+)\\s+" in line:
        line = "        simple_match = re.match(r'^((?:0x|16\\'h)[0-9A-Fa-f]+)\\s+(\\S+)\\s+(\\S+)?\\s*(.*)?', s)\n"
    
    elif "offset_name_match = re.match(r'^(0x[0-9A-Fa-f]+)\\s+([A-Za-z_]" in line:
        line = "        offset_name_match = re.match(r'^((?:0x|16\\'h)[0-9A-Fa-f]+)\\s+([A-Za-z_][A-Za-z0-9_]*(?:[+-][A-Za-z0-9_]+)*)$', s)\n"
    
    updated_lines.append(line)

# Write the updated file
with open('l1_pdf_analysis.py', 'w') as f:
    f.writelines(updated_lines)

print("Fixed all hex patterns to support both 0x and 16'h notation")
print("Patterns updated successfully!")