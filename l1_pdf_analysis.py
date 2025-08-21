# file_spider_fixed.py
# Python 3.8+ (tested on Windows). Requires: poppler-utils (pdftotext) and pandas

"""
Known PDF Extraction Issues:
- Reserved Concatenation Artifacts: PDF extraction sometimes concatenates "Reserved" 
  with following content without spaces, creating invalid entries like 
  "Reserved6332node_id3116node_type150". These are filtered using pattern matching.
"""

import re, json
import subprocess
import pandas as pd
from pathlib import Path
import sys
import os

# ------------------ Regexes / token classes ------------------
heading_re = re.compile(r'^Table\s+\d+-\d+:\s+.*$', re.IGNORECASE)
section_re = re.compile(r'^\d+(\.\d+)+')  # e.g., 8.3.1
offset_re  = re.compile(r'^(?:0x|16\'h)[0-9A-Fa-f]+$')
bits_re    = re.compile(r'^\[\d+(?::\d+)?\]$')
range_re   = re.compile(r'^\{\s*\d+(?:\s*-\s*\d+)?\s*\}$')

# New patterns for pdftotext format with ligatures
array_offset_re = re.compile(r'^\{\d+-\d+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+')  # {0-31} 0x3000 : 0x31F8 or 16\'h3000
simple_offset_re = re.compile(r'^(?:0x|16\'h)[0-9A-Fa-f]+(?:\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+)?')  # 0x100 or 16\'h100 : 16\'h200

footer_noise = re.compile(r'^(Page\b|Copyright|Arm\s+Limited|ARM\s+Limited)', re.IGNORECASE)

# Pattern to detect document boilerplate that gets mixed into descriptions and names
document_boilerplate_re = re.compile(
    r'\b(Non-Confidential|Arm\s*®\s*Neoverse|Technical\s+Reference\s+Manual|Document\s+ID|Issue\s+\d+|Programmers?\s+model|®\s*Neoverse|CMN\s*S3|Coherent\s+Mesh\s+Network)\b',
    re.IGNORECASE
)

# Pattern to detect boilerplate sentences that should never be register names
boilerplate_sentence_re = re.compile(
    r'^(This\s+register\s+is\s+owned|This\s+register\s+is\s+accessible|Usage\s+constraint|Non-secure\s+space|Secure\s+space|The\s+following\s+image\s+shows|Figure\s+\d)',
    re.IGNORECASE
)

# Explicit boilerplate strings that must be filtered out (failsafe)
EXPLICIT_BOILERPLATE_STRINGS = {
    "This register is owned in the Non-secure space and is accessible using Non-secure, Secure,",
    "This register is owned in the Non-secure space and is accessible using Non-secure, Secure",
    "This register is owned in the Non-secure space",
    "This register is accessible using Non-secure, Secure,",
    "This register is accessible using Non-secure, Secure",
    "Root, and Realm transactions.",
    "Root, and Realm transactions",
    "Bit descriptions"
}

TYPE_TOKENS = {
    "RO","RW","WO","R/W","R/W1C","R/W1S","R/W1P","R/WC","R/W0C","R/W0S","R/W0P",
    "R/W0","R/W1","R/WS","R/WP","R/C","R/S","R0","W1C","W1S","W1P","RWL"
}

# Performance optimization: Pre-sort TYPE_TOKENS for efficient longest-first matching
SORTED_TYPE_TOKENS = sorted(TYPE_TOKENS, key=len, reverse=True)

# Constants for maintainability
MIN_NAME_LENGTH = 3  # Minimum valid register name length
LONG_NAME_THRESHOLD = 10  # Threshold for relaxed validation
HEADER_LABELS = {'offset','name','type','description','reset','bits'}

# Reserved concatenation artifact detection constants
RESERVED_PREFIX = "Reserved"
RESERVED_PREFIX_LENGTH = len(RESERVED_PREFIX)
# Pre-compiled for ~10% performance improvement over inline regex
RESERVED_CONCATENATION_PATTERN = re.compile(r'^\d+.*[a-zA-Z]')

ADDR_SEPARATORS = {":", "-", "–", ",", ";"}
# One or more address tokens only (no names/types)
addr_token_re = r'(?:\{\s*\d+(?:\s*-\s*\d+)?\s*\}|(?:0x|16\'h)[0-9A-Fa-f]+|:|,|–|-)'
addr_line_re  = re.compile(r'^(?:\s*' + addr_token_re + r'\s*)+$')

# Things that must never be treated as a register name
BAD_NAME_PREFIXES = {
    "reset value", "reset values",
    "see individual bit resets",
    "attributes", "attribute",
    "bits", "name", "description", "type", "offset",
    "usage constraints", "usage constraint",
    "non-confidential"
}
# Reset-noise anywhere in a line (more robust than prefix-only)
RESET_NOISE_RE = re.compile(
    r'\b(reset\s+value|reset\s+values|see\s+individual\s+bit\s+resets?)\b',
    re.IGNORECASE
)

# ------------------ Helpers ------------------
def is_reserved_concatenation_artifact(name: str) -> bool:
    """
    Check if name is a Reserved concatenation artifact.
    
    These are PDF extraction artifacts where "Reserved" gets concatenated 
    with numbers and other text without proper spacing.
    
    Examples:
        Reserved6332node_id3116node_type150 -> True (artifact)
        Reserved -> False (legitimate)
        Reserved_field -> False (legitimate underscore)
        Reserved123abc -> True (artifact)
    
    Args:
        name: The name string to check
    
    Returns:
        bool: True if this appears to be a Reserved concatenation artifact
    """
    if not name.startswith(RESERVED_PREFIX):
        return False
    
    if len(name) <= RESERVED_PREFIX_LENGTH or name == RESERVED_PREFIX:
        return False
    
    # Extract the suffix after "Reserved"
    reserved_suffix = name[RESERVED_PREFIX_LENGTH:]
    
    # Check if it matches the concatenation pattern (starts with numbers, contains letters)
    return bool(RESERVED_CONCATENATION_PATTERN.match(reserved_suffix))

def clean_line(s: str) -> str:
    # Normalize common ligatures and whitespace
    s = s.replace('\uFB00', 'ff').replace('\uFB01', 'fi').replace('\uFB02', 'fl')
    s = s.replace('\uFB03', 'ffi').replace('\uFB04', 'ffl')
    # Preserve leading spaces (important for continuation lines) but normalize internal spaces
    # Strip only trailing whitespace
    leading_spaces = len(s) - len(s.lstrip())
    s_cleaned = re.sub(r'\s+', ' ', s.strip())
    # Re-add leading spaces if there were any
    if leading_spaces > 0 and s_cleaned:
        return ' ' * leading_spaces + s_cleaned
    return s_cleaned

def is_heading(s: str) -> bool: return bool(heading_re.match(s))
def is_section_heading(s: str) -> bool: return bool(section_re.match(s))
def is_noise(s: str) -> bool: return bool(footer_noise.match(s))
def is_type_token(s: str) -> bool: return s in TYPE_TOKENS
def is_bits_token(s: str) -> bool: return bool(bits_re.match(s))
def is_offset_token(s: str) -> bool: return bool(offset_re.match(s))
def is_range_token(s: str) -> bool: return bool(range_re.match(s))
def is_addr_sep(s: str) -> bool: return s in ADDR_SEPARATORS
def is_addr_line(s: str) -> bool: return bool(addr_line_re.match(s))
def is_addr_token(s: str) -> bool:
    return is_offset_token(s) or is_range_token(s) or is_addr_sep(s)

def clean_pdf_text(input_path: str, output_path: str):
    """Remove page footers/headers that break tables across pages and join wrapped lines."""
    print(f"[INFO] Cleaning PDF text to remove page breaks...")
    
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    cleaned_lines = []
    i = 0
    seen_table_headers = set()  # Track which table headers we've seen
    current_table = None
    
    while i < len(lines):
        line = lines[i]
        
        # Check for footer pattern (Copyright line)
        if 'Copyright ©' in line and 'Arm Limited' in line:
            # Skip footer (3 lines) and header (3 lines) and empty lines
            # Footer: Copyright, Non-Confidential, Page X of Y
            # Header: Product name, Technical Reference Manual, Section
            skip_count = 0
            while i < len(lines) and skip_count < 9:  # Max lines to skip
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if 'Non-Confidential' in next_line or 'Non-Conﬁdential' in next_line:
                        i += 1  # Skip Non-Confidential
                        skip_count += 1
                    elif 'Page ' in next_line and ' of ' in next_line:
                        i += 1  # Skip Page line
                        skip_count += 1
                    elif 'Arm®' in next_line or 'Neoverse™' in next_line:
                        i += 1  # Skip product name
                        skip_count += 1
                    elif 'Technical Reference Manual' in next_line:
                        i += 1  # Skip manual line
                        skip_count += 1
                    elif 'Programmers model' in next_line or 'Issue' in next_line:
                        i += 1  # Skip section line
                        skip_count += 1
                    elif next_line.strip() == '':
                        i += 1  # Skip empty lines
                        skip_count += 1
                    else:
                        break
                else:
                    break
            i += 1
            continue
        
        # Check for Table header to track current table
        if line.startswith('Table ') and ':' in line:
            table_match = re.match(r'^(Table \d+-\d+:.*)', line)
            if table_match:
                current_table = table_match.group(1)
        
        # Check for repeated column headers and skip if duplicate
        if re.match(r'^Oﬀset\s+Name\s+', line) or re.match(r'^Bits\s+Name\s+', line):
            # Create a key for this table's header
            header_key = f"{current_table}:{line.strip()}"
            if header_key in seen_table_headers:
                # Skip this duplicate header
                i += 1
                continue
            else:
                seen_table_headers.add(header_key)
        
        cleaned_lines.append(line)
        i += 1
    
    # Second pass: Join split offset ranges (must be done BEFORE array index handling)
    pass2_lines = []
    i = 0
    
    while i < len(cleaned_lines):
        line = cleaned_lines[i]
        
        # Handle offset range splits (two patterns)
        # Pattern 1: "0x2240 :" followed by "0x2248" (colon on first line)
        if re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+\s*:$', line.strip()):
            if i + 1 < len(cleaned_lines) and re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+$', cleaned_lines[i + 1].strip()):
                # Join the two lines into an offset range
                combined = f"{line.strip()} {cleaned_lines[i + 1].strip()}\n"
                pass2_lines.append(combined)
                i += 2
                continue
        
        # Pattern 2: "0x2240" followed by ":" followed by "0x2248" (colon on separate line)
        if re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+$', line.strip()):
            if i + 1 < len(cleaned_lines) and cleaned_lines[i + 1].strip() == ':':
                if i + 2 < len(cleaned_lines) and re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+$', cleaned_lines[i + 2].strip()):
                    # Join the three lines into an offset range
                    combined = f"{line.strip()} : {cleaned_lines[i + 2].strip()}\n"
                    pass2_lines.append(combined)
                    i += 3
                    continue
        
        pass2_lines.append(line)
        i += 1
    
    # Third pass: Join wrapped lines and handle other patterns
    final_lines = []
    i = 0
    
    while i < len(pass2_lines):
        line = pass2_lines[i]
        
        # Handle wrapped attribute field names
        # Pattern: "[31:29] htg#{index*4 +                         configuration to map..."
        # Next line: "        1}_hnf_cal_override_map_11"
        if re.match(r'^\[[\d:]+\]\s+.*\+\s+', line) and i + 1 < len(pass2_lines):
            next_line = pass2_lines[i + 1]
            # Check if next line is the field name continuation
            if re.match(r'^\s+.*\}_', next_line):
                # Extract components from first line
                # Pattern: [bits] incomplete_field_name+ description type reset
                bits_match = re.match(r'^(\[[\d:]+\])\s+(\S+\s*\+)\s+(.*)', line)
                if bits_match:
                    bits = bits_match.group(1)
                    incomplete_name = bits_match.group(2).rstrip()  # Remove trailing spaces after +
                    remaining = bits_match.group(3)
                    
                    # Extract field name continuation from next line
                    continuation_match = re.match(r'^\s+(\S+)', next_line)
                    if continuation_match:
                        name_continuation = continuation_match.group(1)
                        
                        # Combine field name - add space after + if needed
                        if incomplete_name.endswith('+'):
                            complete_name = incomplete_name + ' ' + name_continuation
                        else:
                            complete_name = incomplete_name + name_continuation
                        
                        # Reconstruct the line
                        combined_line = f"{bits} {complete_name} {remaining}\n"
                        final_lines.append(combined_line)
                        i += 2  # Skip both lines
                        continue
        
        # Handle special case where array indices and partial register name appear first,
        # followed by offset information on subsequent lines
        # Pattern: "{0-1}  hashed_target_grp_hnf_target_type_override_          RW hashed_target_grp_hnf_target_type_override_cfg_reg0-1"
        # Next line: "0x37E0 cfg_reg0-1"
        # Next line: ":"
        # Next line: "0x37E8"
        if (re.match(r'^\{[\d-]+\}\s+\w+.*?\s+(RW|RO|WO|RWL|W1C|W1S|R/W)', line) and 
            i + 3 < len(pass2_lines)):
            
            # Check if this matches the pattern where offset comes after
            line1 = pass2_lines[i + 1].strip()
            line2 = pass2_lines[i + 2].strip() 
            line3 = pass2_lines[i + 3].strip()
            
            # Look for: "0x37E0 cfg_reg0-1", ":", "0x37E8"
            if (re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+\s+\w+', line1) and 
                line2 == ':' and 
                re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+$', line3)):
                
                # Extract components
                array_match = re.match(r'^(\{[\d-]+\})\s+(.*?)\s+(RW|RO|WO|RWL|W1C|W1S|R/W)\s+(.*)', line)
                offset_match = re.match(r'^((?:0x|16\'h)[0-9A-Fa-f]+)\s+(.*)', line1)
                
                if array_match and offset_match:
                    array_indices = array_match.group(1)
                    partial_name = array_match.group(2)
                    reg_type = array_match.group(3)
                    description = array_match.group(4)
                    
                    offset_start = offset_match.group(1)
                    name_completion = offset_match.group(2)
                    offset_end = line3
                    
                    # Construct the proper line format
                    full_offset = f"{offset_start} : {offset_end}"
                    full_name = f"{partial_name}{name_completion}"
                    
                    combined_line = f"{array_indices} {full_offset} {full_name} {reg_type} {description}\n"
                    final_lines.append(combined_line)
                    i += 4  # Skip all 4 lines we just processed
                    continue
        
        # Handle wrapped register names (name ends with _ and has continuation)
        # Pattern: "0x2080 por_c2capb_c2c_port_ingressid_route_table_                RW     por_c2capb_c2c_port_ingressid_route_table_control_and_status"
        # Next line: "       control_and_status"
        if re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+.*_\s+(RW|RO|WO|RWL|W1C|W1S|R/W)', line):
            # This register name ends with underscore before the type
            if i + 1 < len(cleaned_lines):
                next_line = cleaned_lines[i + 1]
                # Check if next line is the continuation (indented lowercase text)
                if re.match(r'^\s+[a-z_]+\s*$', next_line.rstrip('\n')):
                    # Skip the continuation line - we already have the full name in description
                    i += 2  # Skip both current and continuation
                    final_lines.append(line)
                    continue
        
        # Handle array offset splits where ending offset is on next line
        # Pattern: "{0-31} 0x3000 :    ra_rnsam_hashed_tgt_grp_cfg1_region0-31 ..."
        # Next line: "0x30F8"
        if re.match(r'^\{[\d-]+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:', line):
            if i + 1 < len(cleaned_lines):
                next_line = cleaned_lines[i + 1].strip()
                # Check if next line is just a hex offset
                if re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+$', next_line):
                    # Join the lines properly
                    # Extract parts from the first line
                    match = re.match(r'^(\{[\d-]+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:)\s*(.*)', line)
                    if match:
                        offset_part = match.group(1)
                        rest_of_line = match.group(2)
                        # Create the joined line with proper format
                        line = f"{offset_part} {next_line} {rest_of_line}\n"
                        i += 2
                        final_lines.append(line)
                        continue
        
        # Handle registers where array index and offset are split
        # Pattern: "{0-3}  cml_port_aggr_mode_ctrl_reg1-12  RW ..."
        # Next line: "0x11A0 : 0x11B8"
        # Possibly more: "{4-19}"
        # And: "0x2A20 : 0x2A98"
        if re.match(r'^\{[\d-]+\}\s+\w+', line) and not re.match(r'^\{[\d-]+\}\s+0x', line):
            # This line starts with array index but no offset - check if offset is on next line
            if i + 1 < len(pass2_lines):
                next_line = pass2_lines[i + 1].strip()
                if re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+\s*$', next_line):
                    # Found offset on next line - merge them
                    # Extract the array index from current line
                    match = re.match(r'^(\{[\d-]+\})\s+(.*)', line)
                    if match:
                        array_idx = match.group(1)
                        rest_of_line = match.group(2).rstrip('\n')
                        # Build offset part separately from rest of line
                        offset_part = f"{array_idx} {next_line}"
                        
                        # Look for additional continuation patterns (enhanced for multi-segment arrays)
                        j = i + 2
                        continuation_found = True
                        while j < len(pass2_lines) and j <= i + 15 and continuation_found:  # Expanded range
                            lookahead = pass2_lines[j].strip()
                            if not lookahead:  # Skip blank lines
                                j += 1
                                continue
                            
                            # Check for another array+offset pair
                            if re.match(r'^\{[\d-]+\}$', lookahead):
                                # Found another array index - look for its offset in wider range
                                continuation_array_idx = lookahead
                                offset_found = False
                                k = j + 1
                                while k < len(pass2_lines) and k <= j + 8:  # Expanded nested range
                                    offset_candidate = pass2_lines[k].strip()
                                    if not offset_candidate:  # Skip blank lines
                                        k += 1
                                        continue
                                    if re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+\s*$', offset_candidate):
                                        # Add to offset part, not end of line
                                        offset_part += f"; {continuation_array_idx} {offset_candidate}"
                                        j = k + 1
                                        offset_found = True
                                        break
                                    elif re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+$', offset_candidate):
                                        # Handle split offset (start only, look for end)
                                        if k + 2 < len(pass2_lines):
                                            if pass2_lines[k + 1].strip() == ':' and re.match(r'^(?:0x|16\'h)[0-9A-Fa-f]+$', pass2_lines[k + 2].strip()):
                                                full_offset = f"{offset_candidate} : {pass2_lines[k + 2].strip()}"
                                                # Add to offset part, not end of line
                                                offset_part += f"; {continuation_array_idx} {full_offset}"
                                                j = k + 3
                                                offset_found = True
                                                break
                                        k += 1
                                    else:
                                        # Hit a non-offset line, stop searching for this array's offset
                                        break
                                
                                if not offset_found:
                                    # No offset found for this array index, stop looking for more continuations
                                    continuation_found = False
                                    break
                            else:
                                # Hit a non-array line, stop looking for continuations
                                continuation_found = False
                                break
                        
                        # Construct final combined line with proper CSV column placement
                        combined_line = f"{offset_part} {rest_of_line}\n"
                        
                        final_lines.append(combined_line)
                        i = j
                        continue
        
        # Handle registers with double offset ranges that already have register names
        # Pattern: "{0-4} 0xF80 : 0xFA0       cmn_hns_cml_port_aggr_grp0-4_add_mask ..."
        # Next line(s): blank
        # Next line: "{5-31} 0x6028 : 0x60F8"
        if re.match(r'^\{[\d-]+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+\s+\w+', line):
            # Extract components from current line  
            match = re.match(r'^(\{[\d-]+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+)\s+(.*)', line)
            if match:
                offset_part = match.group(1)
                rest_of_line = match.group(2).rstrip('\n')
                
                # Look ahead for continuation offset pattern
                found_continuation = False
                j = i + 1
                while j < len(pass2_lines) and j <= i + 3:
                    lookahead = pass2_lines[j].strip()
                    # Check if this is a continuation offset (just the offset, no register name)
                    if re.match(r'^\{[\d-]+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+$', lookahead):
                        # Add to offset part, not end of line
                        offset_part += f"; {lookahead}"
                        i = j + 1
                        found_continuation = True
                        break
                    elif lookahead and not lookahead.startswith('{'):
                        # Hit a non-blank, non-offset line - stop looking
                        break
                    j += 1
                
                if not found_continuation:
                    i += 1
                
                # Construct final line with proper CSV column placement
                line = f"{offset_part} {rest_of_line}\n"
            
            final_lines.append(line)
            continue
        
        # Note: Offset range splits are now handled in the second pass
        
        final_lines.append(line)
        i += 1
    
    # Fourth pass: Join multi-segment arrays in CMN-700 format
    # Pattern: {0-23} register_name RW description
    #          16\'hC00 :
    #          16\'hCB8
    #          {24-63}
    #          16\'h20C0 :
    #          16\'h24B8
    # Should become: {0-23} 16\'hC00 : 16\'hCB8; {24-63} 16\'h20C0 : 16\'h24B8 register_name RW description
    pass4_lines = []
    i = 0
    
    while i < len(final_lines):
        line = final_lines[i]
        
        # Look for pattern: {X-Y} register_name TYPE description
        first_segment_match = re.match(r'^(\{[\d-]+\})\s+(\w+.*?)\s+(RW|RO|WO|RWL|W1C|W1S|R/W)\s+(.*)', line)
        if first_segment_match:
            array_indices = [first_segment_match.group(1)]
            register_name = first_segment_match.group(2)
            reg_type = first_segment_match.group(3)
            description = first_segment_match.group(4)
            
            # Look ahead for offset patterns
            j = i + 1
            offsets = []
            
            # Collect offset ranges for first segment
            if j < len(final_lines):
                # Look for: 16\'hXXX :
                start_offset_match = re.match(r'^16\'h([0-9A-Fa-f]+)\s*:$', final_lines[j].strip())
                if start_offset_match:
                    j += 1
                    if j < len(final_lines):
                        # Look for: 16\'hXXX
                        end_offset_match = re.match(r'^16\'h([0-9A-Fa-f]+)$', final_lines[j].strip())
                        if end_offset_match:
                            offsets.append(f"0x{start_offset_match.group(1)} : 0x{end_offset_match.group(1)}")
                            j += 1
            
            # Look for additional segments
            while j < len(final_lines):
                # Look for: {X-Y}
                next_segment_match = re.match(r'^(\{[\d-]+\})$', final_lines[j].strip())
                if next_segment_match:
                    array_indices.append(next_segment_match.group(1))
                    j += 1
                    
                    # Look for its offset range
                    if j < len(final_lines):
                        start_offset_match = re.match(r'^16\'h([0-9A-Fa-f]+)\s*:$', final_lines[j].strip())
                        if start_offset_match:
                            j += 1
                            if j < len(final_lines):
                                end_offset_match = re.match(r'^16\'h([0-9A-Fa-f]+)$', final_lines[j].strip())
                                if end_offset_match:
                                    offsets.append(f"0x{start_offset_match.group(1)} : 0x{end_offset_match.group(1)}")
                                    j += 1
                                else:
                                    break
                            else:
                                break
                        else:
                            break
                else:
                    break
            
            # If we found multiple segments, create the combined line
            if len(array_indices) > 1 and len(offsets) == len(array_indices):
                # Build the multi-segment offset string
                offset_parts = []
                for idx, offset in enumerate(offsets):
                    offset_parts.append(f"{array_indices[idx]} {offset}")
                
                combined_offset = "; ".join(offset_parts)
                combined_line = f"{combined_offset} {register_name} {reg_type} {description}\n"
                pass4_lines.append(combined_line)
                i = j
                continue
        
        pass4_lines.append(line)
        i += 1
    
    # Write cleaned and joined text
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(pass4_lines)
    
    print(f"[INFO] Cleaned text saved to {output_path}")
    print(f"[INFO] Reduced from {len(lines)} to {len(pass4_lines)} lines")

def get_all_lines(pdf_path: str):
    """Extract text from PDF using pdftotext and return as list of lines."""
    # Create output directory if it doesn't exist
    output_dir = Path("L1_pdf_analysis")
    output_dir.mkdir(exist_ok=True)
    
    output_txt = output_dir / "output.txt"
    cleaned_txt = output_dir / "output_cleaned.txt"
    
    # Run pdftotext with -layout option to preserve table structure
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, str(output_txt)],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"[INFO] Successfully extracted text from PDF to {output_txt}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to run pdftotext: {e}")
        print(f"[ERROR] Make sure poppler-utils is installed (brew install poppler on macOS)")
        sys.exit(1)
    except FileNotFoundError:
        print("[ERROR] pdftotext command not found. Please install poppler-utils:")
        print("  macOS: brew install poppler")
        print("  Ubuntu/Debian: sudo apt-get install poppler-utils")
        print("  RHEL/CentOS: sudo yum install poppler-utils")
        sys.exit(1)
    
    # Clean the extracted text to remove page breaks
    clean_pdf_text(str(output_txt), str(cleaned_txt))
    
    # Read the cleaned text file
    return get_lines_from_text(str(cleaned_txt))

def get_lines_from_text(text_path: str):
    """Read text file and return as list of lines, skipping boilerplate."""
    lines = []
    
    try:
        with open(text_path, 'r', encoding='utf-8') as f:
            page_num = 0
            for raw in f:
                # Detect page breaks (form feed character or specific patterns)
                if '\f' in raw or 'Page ' in raw and re.match(r'^\s*Page\s+\d+', raw):
                    lines.append(f"__PAGE_BREAK_{page_num}__")
                    page_num += 1
                    continue
                
                s = clean_line(raw)
                if not s or is_noise(s):
                    continue
                lines.append(s)
    except Exception as e:
        print(f"[ERROR] Failed to read text file {text_path}: {e}")
        sys.exit(1)
    
    return lines

def is_probable_name(s: str) -> bool:
    if not s: return False
    
    # CRITICAL FIX: Explicit string matching for boilerplate that escapes regex
    s_stripped = s.strip('"').strip()  # Remove quotes and whitespace
    if s_stripped in EXPLICIT_BOILERPLATE_STRINGS:
        return False
    
    # CRITICAL FIX: Starts-with check for boilerplate variations
    if s_stripped.startswith("This register is owned in the Non-secure space"):
        return False
    
    low = s.lower()
    if low in HEADER_LABELS: return False
    if any(low.startswith(p) for p in BAD_NAME_PREFIXES): return False
    if RESET_NOISE_RE.search(s): return False
    if is_addr_line(s) or is_addr_token(s) or is_heading(s) or is_section_heading(s) or is_type_token(s):
        return False
    if s.startswith("__PAGE_BREAK_"): return False
    
    # Filter out document boilerplate that shouldn't be register names
    if document_boilerplate_re.search(s):
        return False
    
    # ENHANCED: Filter out boilerplate sentences that start with specific patterns
    if boilerplate_sentence_re.match(s):
        return False
    
    # ENHANCED: Reject extremely long strings that are likely paragraphs, not register names
    # Typical register names are under 100 characters; boilerplate sentences are much longer
    if len(s) > 120:  # Conservative threshold to catch paragraph-length boilerplate
        return False
    
    # ENHANCED: Reject PDF extraction artifacts that concatenate text without spaces
    if is_reserved_concatenation_artifact(s):
        return False
    
    # ENHANCED: Reject single-word entries that are likely artifacts or table headers
    if s == "Arm":
        return False
    
    # ENHANCED: Reject strings that contain multiple sentences (period + space + capital letter)
    if re.search(r'\. [A-Z]', s):
        return False
    
    # Hot fix: Handle "ReservedReserved" case - likely a PDF extraction artifact
    if s == "ReservedReserved":
        return True  # Allow it as a name but will be cleaned later
    
    # ENHANCED: Allow specific special character registers
    # NOTE: Removed standalone '-' as it causes false positives with descriptions like "1-"
    if s in {'+', '*', '/', '%'}:
        return True
    
    # CRITICAL FIX: Reject patterns like "1-", "2-" etc which are from sub-bit descriptions
    # These appear when PDF extraction includes sub-bit definitions within field descriptions
    if re.match(r'^\d+-$', s):
        return False
    
    # ENHANCED: Reject standalone hyphen or hyphen with just numbers
    if s == '-' or re.match(r'^[\d\-]+$', s):
        return False
    
    # require letters/underscore somewhere; avoids misreading offsets/ranges as names
    return bool(re.search(r'[A-Za-z_]', s))

def is_name_continuation(s: str) -> bool:
    # Names sometimes wrap after an underscore. Accept purely [A-Za-z0-9_]+ fragments as continuation.
    if not s or s.startswith("__PAGE_BREAK_"): return False
    if is_type_token(s) or is_heading(s) or is_section_heading(s): return False
    low = s.lower()
    if low in HEADER_LABELS or any(low.startswith(p) for p in BAD_NAME_PREFIXES): return False
    if RESET_NOISE_RE.search(s): return False
    return bool(re.fullmatch(r'[A-Za-z0-9_]+', s))

def normalize_addr(expr: str) -> str:
    expr = re.sub(r'\s+', ' ', expr.strip())
    # normalize spaces around punctuation
    expr = re.sub(r'\s*:\s*', ' : ', expr)
    expr = re.sub(r'\s*,\s*', ', ', expr)
    expr = re.sub(r'\s+', ' ', expr)
    # Keep "A + B" format as-is for offset+size notation (don't convert to range)
    # expr = re.sub(r'(0x[0-9A-Fa-f]+)\s*\+\s*(0x[0-9A-Fa-f]+)', r'\1 : \2', expr)
    return expr

# ------------------ Parsers ------------------
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

def parse_register_tables(lines):
    rows = []
    current_table = None
    in_register_mode = False
    register_summary_tables = []  # Track register summary tables found
    skipped_tables = []  # Track tables we skip for diagnostics

    pending_addr = ""  # buffer chained address tokens until a name is seen

    i = 0
    N = len(lines)
    while i < N:
        s = lines[i]

        if is_heading(s):
            # New table; commit nothing, reset buffer
            current_table = s
            s_lower = s.lower()
            
            # REVERTED: Only detect "register summary" tables as per user request
            in_register_mode = ('register summary' in s_lower)
            
            if in_register_mode:
                register_summary_tables.append(s)
            elif 'register' in s_lower:
                # Track skipped tables for diagnostics
                skipped_tables.append(s)
            
            pending_addr = ""
            i += 1
            continue

        if not in_register_mode:
            i += 1
            continue

        # Skip page breaks / column headers with ligatures
        if s.startswith("__PAGE_BREAK_") or s.lower() in HEADER_LABELS or re.match(r'^Oﬀset\s+Name\s+', s):
            i += 1
            continue
        
        # Check for section header (e.g., "8.3.1.1 por_apb_node_info") which marks end of table
        if re.match(r'^\s*8\.3\.', s):
            # This is a detailed register description section, not part of the summary table
            in_register_mode = False
            continue
        
        # NEW: Handle pdftotext format with space-separated columns
        # Pattern 1: Multi-segment array format "{0-15} 0xD80 : 0xDF8; {16-47} 0x2880 : 0x2978 register_name RW description"
        # IMPORTANT: This pattern must be checked BEFORE the single array pattern to avoid false matches
        multi_segment_match = re.match(r'^(\{[\d-]+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+(?:\s*;\s*\{[\d-]+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+)+)\s*(\S+)\s+(\S+)?\s*(.*)?', s)
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
            
        # Pattern 2: Single array format "{0-31} 0x3000 : 0x31F8    register_name    RW    description"
        array_match = re.match(r'^(\{\d+-\d+\}\s+(?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+)\s*(\S+)\s+(\S+)?\s*(.*)?', s)
        if array_match:
            offset = array_match.group(1).strip()
            name = array_match.group(2).strip()
            type_token = array_match.group(3).strip() if array_match.group(3) else "-"
            desc = array_match.group(4).strip() if array_match.group(4) else name
            
            # Validate type token
            if not is_type_token(type_token):
                desc = type_token + " " + desc if type_token != "-" else desc
                type_token = "-"
            
            rows.append({
                "table": current_table,
                "offset": offset,
                "name": name,
                "type": type_token,
                "description": desc,
            })
            i += 1
            continue
        
        # Pattern 3: Range format "0x100 : 0x200    register_name    RW    description"
        range_match = re.match(r'^((?:0x|16\'h)[0-9A-Fa-f]+\s*:\s*(?:0x|16\'h)[0-9A-Fa-f]+)\s+(\S+)\s+(\S+)?\s*(.*)?', s)
        if range_match:
            offset = range_match.group(1).strip()
            name = range_match.group(2).strip()
            type_token = range_match.group(3).strip() if range_match.group(3) else "-"
            desc = range_match.group(4).strip() if range_match.group(4) else name
            
            # Validate type token
            if not is_type_token(type_token):
                desc = type_token + " " + desc if type_token != "-" else desc
                type_token = "-"
            
            rows.append({
                "table": current_table,
                "offset": offset,
                "name": name,
                "type": type_token,
                "description": desc,
            })
            i += 1
            continue
        
        # Pattern 4: Offset+Size format "0x100 + 0x80    register_name    RW    description"
        offset_plus_match = re.match(r'^((?:0x|16\'h)[0-9A-Fa-f]+\s*\+\s*(?:0x|16\'h)[0-9A-Fa-f]+)\s+(\S+)\s+(\S+)?\s*(.*)?', s)
        if offset_plus_match:
            offset = offset_plus_match.group(1).strip()
            name = offset_plus_match.group(2).strip()
            type_token = offset_plus_match.group(3).strip() if offset_plus_match.group(3) else "-"
            desc = offset_plus_match.group(4).strip() if offset_plus_match.group(4) else name
            
            # Validate type token
            if not is_type_token(type_token):
                desc = type_token + " " + desc if type_token != "-" else desc
                type_token = "-"
            
            # Validate name is not noise
            if is_probable_name(name):
                rows.append({
                    "table": current_table,
                    "offset": offset,
                    "name": name,
                    "type": type_token,
                    "description": desc,
                })
            i += 1
            continue
        
        # Pattern 5: Simple format "0x100    register_name    RW    description"
        simple_match = re.match(r'^((?:0x|16\'h)[0-9A-Fa-f]+)\s+(\S+)\s+(\S+)?\s*(.*)?', s)
        if simple_match:
            offset = simple_match.group(1).strip()
            name = simple_match.group(2).strip()
            type_token = simple_match.group(3).strip() if simple_match.group(3) else "-"
            desc = simple_match.group(4).strip() if simple_match.group(4) else name
            
            # Validate type token
            if not is_type_token(type_token):
                desc = type_token + " " + desc if type_token != "-" else desc
                type_token = "-"
            
            # Validate name is not noise
            if is_probable_name(name):
                rows.append({
                    "table": current_table,
                    "offset": offset,
                    "name": name,
                    "type": type_token,
                    "description": desc,
                })
            i += 1
            continue

        # ENHANCED: Check if this line has both offset and name concatenated
        # Pattern: "0xXXXX register_name"
        offset_name_match = re.match(r'^((?:0x|16\'h)[0-9A-Fa-f]+)\s+([A-Za-z_][A-Za-z0-9_]*(?:[+-][A-Za-z0-9_]+)*)$', s)
        if offset_name_match:
            # Found offset and name on same line
            pending_addr = offset_name_match.group(1)
            name = offset_name_match.group(2)
            i += 1
            
            # Look for type
            typ = ""
            if i < N and is_type_token(lines[i]):
                typ = lines[i]
                i += 1
            
            # Get description
            desc_parts = []
            while i < N:
                t = lines[i]
                if t.startswith("__PAGE_BREAK_") or t.lower() in HEADER_LABELS:
                    i += 1
                    continue
                if is_heading(t) or is_section_heading(t) or is_bits_token(t):
                    break
                if is_addr_line(t) or is_offset_token(t) or is_range_token(t) or is_addr_token(t):
                    break
                if t.lower().startswith(tuple(BAD_NAME_PREFIXES)) or RESET_NOISE_RE.search(t):
                    break
                if boilerplate_sentence_re.match(t):
                    i += 1
                    continue
                if document_boilerplate_re.search(t):
                    clean_part = document_boilerplate_re.split(t)[0].strip()
                    if clean_part:
                        desc_parts.append(clean_part)
                    break
                desc_parts.append(t)
                i += 1
            
            # Add the row
            rows.append({
                "table": current_table,
                "offset": pending_addr,
                "name": name,
                "type": typ.strip() if typ else "-",
                "description": " ".join(desc_parts).strip() if desc_parts else name,
            })
            pending_addr = ""
            continue
        
        # Accumulate address-only content into the buffer
        if is_addr_line(s) or is_offset_token(s) or is_range_token(s) or is_addr_token(s):
            pending_addr = (pending_addr + " " + s).strip()
            i += 1
            continue

        # If we reached another section/heading and we still have a buffer, drop it (no matching name)
        if is_section_heading(s):
            pending_addr = ""
            i += 1
            continue

        # If this line looks like a name, we try to build a row out of (pending_addr + this name)
        if is_probable_name(s):
            name = s
            i += 1

            # Join wrapped name fragments (e.g., name endswith '_' and next line continues)
            while i < N and is_name_continuation(lines[i]):
                frag = lines[i]
                if name.endswith('_'):
                    name = name + frag
                else:
                    # conservative join without space to preserve snake_case
                    name = name + frag
                i += 1
            
            # ENHANCED: Final validation after name joining - reject if it became boilerplate
            name_stripped = name.strip('"').strip()  # Remove quotes and whitespace
            if (boilerplate_sentence_re.match(name) or 
                len(name) > 120 or 
                re.search(r'\. [A-Z]', name) or
                name_stripped in EXPLICIT_BOILERPLATE_STRINGS or
                name_stripped.startswith("This register is owned in the Non-secure space")):
                # This joined name is actually boilerplate - skip this row entirely
                pending_addr = ""
                continue

            # Find TYPE - look ahead a bit more aggressively to handle missing types
            typ = ""
            lookahead_limit = min(i + 5, N)  # Look ahead up to 5 lines for type
            j = i
            while j < lookahead_limit:
                t = lines[j]
                if t.startswith("__PAGE_BREAK_") or t.lower() in HEADER_LABELS:
                    j += 1
                    continue
                if is_type_token(t):
                    typ = t
                    i = j + 1  # Update main pointer to after the type
                    break
                # If a new address block starts before we find a type, we still allow a row (type empty)
                if is_addr_line(t) or is_offset_token(t) or is_range_token(t) or is_addr_token(t) or is_heading(t) or is_section_heading(t):
                    i = j  # Set main pointer to current position
                    break
                # Avoid eating obvious reset/attribute headers into description
                if t.lower().startswith(tuple(BAD_NAME_PREFIXES)) or RESET_NOISE_RE.search(t):
                    i = j  # Set main pointer to current position
                    break
                j += 1
            else:
                # If we exhausted the lookahead without finding type or break condition
                i = j

            # Description until next row start/heading/section/bits
            desc_parts = []
            while i < N:
                t = lines[i]
                if t.startswith("__PAGE_BREAK_") or t.lower() in HEADER_LABELS:
                    i += 1
                    continue
                if is_heading(t) or is_section_heading(t) or is_bits_token(t):
                    break
                if is_addr_line(t) or is_offset_token(t) or is_range_token(t) or is_addr_token(t):
                    # next row is beginning; stop description
                    break
                # Avoid adding reset blurbs or table labels
                if t.lower().startswith(tuple(BAD_NAME_PREFIXES)) or RESET_NOISE_RE.search(t):
                    break
                # ENHANCED: Filter out boilerplate sentences from descriptions
                if boilerplate_sentence_re.match(t):
                    # Skip this entire line - it's boilerplate
                    i += 1
                    continue
                # Filter out document boilerplate from descriptions
                if document_boilerplate_re.search(t):
                    # Split on boilerplate and only keep the part before it
                    clean_part = document_boilerplate_re.split(t)[0].strip()
                    if clean_part:
                        desc_parts.append(clean_part)
                    break
                desc_parts.append(t)
                i += 1

            # Only emit a row if we have both an address buffer and a name
            if pending_addr.strip():
                # ENHANCED: Final validation before creating the row
                final_name = name.strip()
                final_description = " ".join(desc_parts).strip()
                
                # Skip if the final name is still boilerplate despite earlier checks
                final_name_stripped = final_name.strip('"').strip()  # Remove quotes and whitespace
                if (boilerplate_sentence_re.match(final_name) or 
                    document_boilerplate_re.search(final_name) or 
                    len(final_name) > 120 or 
                    re.search(r'\. [A-Z]', final_name) or
                    final_name_stripped in EXPLICIT_BOILERPLATE_STRINGS or
                    final_name_stripped.startswith("This register is owned in the Non-secure space")):
                    # Reset buffer and continue without creating a row
                    pending_addr = ""
                    continue
                
                # Skip if description is primarily boilerplate (more than 80% boilerplate)
                if final_description and len(final_description) > 50:
                    if (boilerplate_sentence_re.match(final_description) or
                        (document_boilerplate_re.search(final_description) and 
                         len(document_boilerplate_re.sub('', final_description).strip()) < len(final_description) * 0.2)):
                        # This description is mostly boilerplate - use a generic description instead
                        final_description = "-"
                
                rows.append({
                    "table": current_table,
                    "offset": normalize_addr(pending_addr),
                    "name": final_name,
                    "type": typ.strip(),
                    "description": final_description,
                })
            # Reset buffer after committing a row
            pending_addr = ""
            continue

        # Any other content — just advance (do not clear buffer; we might still see the name next)
        i += 1

    # Diagnostic output for register summary tables
    print(f"[INFO] Found {len(register_summary_tables)} register summary tables")
    
    # Diagnostic output for skipped tables
    if skipped_tables:
        print(f"[DEBUG] Skipped {len(skipped_tables)} tables with 'register' in name:")
        for table in skipped_tables[:5]:  # Show first 5 skipped
            print(f"  - {table}")
        if len(skipped_tables) > 5:
            print(f"  ... and {len(skipped_tables) - 5} more")

    return rows

def find_type_token_position(text):
    """
    Find the rightmost valid type token in text.
    Returns (start_pos, end_pos, token) or (None, None, None) if not found.
    """
    best_match = (None, None, None)
    
    # Search for each type token (longest first to handle R/W1C before RW)
    for token in SORTED_TYPE_TOKENS:
        # Use word boundaries to avoid partial matches
        pattern = r'\b' + re.escape(token) + r'\b'
        matches = list(re.finditer(pattern, text))
        if matches:
            # Get the rightmost match
            last_match = matches[-1]
            # Update if this is further right than current best
            if best_match[0] is None or last_match.start() > best_match[0]:
                best_match = (last_match.start(), last_match.end(), token)
    
    return best_match

def parse_attribute_tables(lines):
    rows = []
    current_table = None
    in_attr_mode = False
    attribute_tables = []  # Track attribute tables found
    current_reg_name = None

    i = 0
    N = len(lines)
    while i < N:
        s = lines[i]

        if is_heading(s):
            current_table = s
            in_attr_mode = ('attribute' in s.lower())
            if in_attr_mode:
                attribute_tables.append(s)
                # Extract register name from table header
                # e.g., "Table 8-24: por_ccg_ha_rcr attributes" -> "por_ccg_ha_rcr"
                match = re.match(r'^Table\s+\d+-\d+:\s+(\S+)\s+attributes', s, re.IGNORECASE)
                if match:
                    current_reg_name = match.group(1)
            i += 1
            continue

        if not in_attr_mode:
            i += 1
            continue

        # Skip column headers including those with ligatures
        if s.startswith("__PAGE_BREAK_") or s.lower() in HEADER_LABELS or re.match(r'^Bits\s+Name\s+', s):
            i += 1
            continue
        
        # NEW: Handle pdftotext format for attributes
        # Pattern: "[63:32]    Reserved    Reserved    RO    -"
        # Or: "[15:0]    field_name    Description text    RW    0x00"
        # Enhanced to handle field names with spaces in template expressions like htg#{index*8 + 7}_num_hn
        # First try to match field names with template expressions that may contain spaces
        bits_match = re.match(r'^(\[\d+(?::\d+)?\])\s+([a-zA-Z_][a-zA-Z0-9_]*(?:#{[^}]+}[a-zA-Z0-9_]*)?)\s+(.*?)$', s)
        if not bits_match:
            # Fallback to original pattern for simpler field names
            bits_match = re.match(r'^(\[\d+(?::\d+)?\])\s+(\S+)(?:\s+(.*?))?$', s)
        if bits_match:
            bits = bits_match.group(1)
            field_name = bits_match.group(2)
            remaining = bits_match.group(3).strip() if bits_match.group(3) else ""
            
            # Skip sub-bit definitions
            bits_val = bits.strip('[]')
            if ':' not in bits_val and bits_val.isdigit():
                # Single bit like [0], [1] - likely sub-bit definition
                # Check if field name looks like a sub-bit description
                if re.match(r'^\d+-', field_name) or field_name.lower() in ('snoop', 'allocate', 'cacheable', 'device', 'ewa'):
                    i += 1
                    continue
            
            # Collect full text including multi-line continuations first
            full_text = remaining if remaining else ""
            continuation_lines = []
            
            # Look ahead for continuation lines (indented lines that aren't new entries)
            j = i + 1
            while j < N:
                next_line = lines[j]
                next_stripped = next_line.strip()
                
                # Check if this is a continuation line
                if (next_stripped and 
                    not next_stripped.startswith('[') and 
                    not is_heading(next_stripped) and
                    not re.match(r'^Bits\s+Name\s+', next_stripped) and
                    not next_stripped.startswith("__PAGE_BREAK_") and
                    next_stripped.lower() not in HEADER_LABELS):
                    
                    # Check if significantly indented (at least 25 spaces typical for description column continuations)
                    # Continuation lines in attribute tables are indented to align with description column
                    # Different tables have different column alignments, so we use a lower threshold
                    indent_len = len(next_line) - len(next_line.lstrip())
                    if indent_len >= 25:
                        continuation_lines.append(next_stripped)
                        j += 1
                    else:
                        # Not indented enough, stop looking
                        break
                else:
                    # Hit a clear boundary
                    break
            
            # Combine all text for parsing
            if continuation_lines:
                full_text = full_text + " " + " ".join(continuation_lines) if full_text else " ".join(continuation_lines)
                i = j - 1  # Update main index to skip processed continuation lines
            
            # Now use type token anchoring to parse the full text
            desc = ""
            typ = "-"
            reset = "-"
            
            if full_text:
                # Find the rightmost type token in the full text
                type_start, type_end, type_token = find_type_token_position(full_text)
                
                if type_token:
                    # Found a type token - use it to split the text
                    typ = type_token
                    
                    # Description is everything before the type token
                    desc = full_text[:type_start].strip()
                    
                    # Reset is everything after the type token
                    reset_text = full_text[type_end:].strip()
                    if reset_text:
                        # Extract the first token as reset value
                        reset_tokens = reset_text.split()
                        if reset_tokens:
                            reset = reset_tokens[0]
                            # If there's more text after reset, it might be description continuation
                            if len(reset_tokens) > 1:
                                extra_desc = " ".join(reset_tokens[1:])
                                # Only add if it doesn't look like a valid reset value
                                if not re.match(r'^(0x[0-9a-fA-F]+|0b[01]+|\d+|-)$', extra_desc):
                                    desc = desc + " " + extra_desc if desc else extra_desc
                else:
                    # No type token found - treat entire text as description
                    desc = full_text
            
            # Validate and clean up reset value
            if reset and reset not in ["-", "0", "1"]:
                # Auto-correct common incomplete values
                if reset == "Configuration":
                    reset = "Configuration dependent"
                elif reset == "Implementation":
                    reset = "Implementation defined"
                elif reset in ["dependent", "defined"]:
                    # These are fragments - likely parsing error
                    desc = desc + " " + reset if desc else reset
                    reset = "-"
                # Validate reset value format
                elif not re.match(r'^(0x[0-9a-fA-F]+|0b[01]+|\d+|Configuration dependent|Implementation defined|-)$', reset):
                    # Check if it might be a valid but unusual format
                    if reset.startswith("0X"):  # Capital X
                        reset = "0x" + reset[2:]  # Convert to lowercase x
                    elif reset.startswith("0B"):  # Capital B
                        reset = "0b" + reset[2:]  # Convert to lowercase b
                    else:
                        # Invalid reset value - likely grabbed wrong text
                        # Common wrong values we've seen: "and", "fields", "attribute", etc.
                        desc = desc + " " + reset if desc else reset
                        reset = "-"
            
            # Don't add if field_name is clearly noise
            if field_name and is_probable_name(field_name) and not is_reserved_concatenation_artifact(field_name):
                rows.append({
                    "table": current_table,
                    "register_name": current_reg_name or "",
                    "bits": bits,
                    "field_name": field_name,
                    "description": desc,
                    "type": typ,
                    "reset": reset
                })
            
            i += 1
            continue

        # OLD: Original parsing logic for non-bits lines
        if is_bits_token(s):
            bits = s.strip('[]')
            
            # CRITICAL FIX: Check if this is a sub-bit definition within a description
            # Sub-bits are single digit patterns like [0], [1], [2] etc. that appear 
            # within multi-bit field descriptions
            if ':' not in bits and bits.isdigit():
                bit_val = int(bits)
                # Check if the next line looks like a sub-bit description fragment
                if i + 1 < N:
                    next_line = lines[i + 1].strip()
                    # Sub-bit descriptions often start with patterns like "1-", "snoop attr", etc.
                    # or are fragments of the parent field's description
                    if (re.match(r'^\d+-', next_line) or  # "1- persistent device"
                        (next_line and len(next_line) < 30 and not is_probable_name(next_line)) or
                        next_line.lower().startswith(('snoop', 'allocate', 'cacheable', 'device', 'ewa'))):
                        # This is likely a sub-bit definition within a larger field's description
                        # Skip it entirely
                        i += 1
                        continue
            
            i += 1
            # Skip header labels / page breaks
            while i < N and (lines[i].lower() in HEADER_LABELS or lines[i].startswith("__PAGE_BREAK_")):
                i += 1

            name = ""
            if i < N and is_probable_name(lines[i]):
                name = lines[i].strip()
                i += 1
                # join wrapped fragments if any
                while i < N and is_name_continuation(lines[i]):
                    frag = lines[i]
                    if name.endswith('_'):
                        name = name + frag
                    else:
                        name = name + frag
                    i += 1

            # Description until we see a Type token (or a new row/table/section)
            desc_parts = []
            while i < N:
                t = lines[i]
                if is_type_token(t) or is_heading(t) or is_section_heading(t):
                    break
                if t.lower() in HEADER_LABELS or t.startswith("__PAGE_BREAK_"):
                    i += 1; continue
                if is_bits_token(t) and desc_parts:
                    break
                if is_addr_line(t) or is_offset_token(t) or is_range_token(t) or is_addr_token(t):
                    # very unlikely in attributes; but stop to be safe
                    break
                # avoid stray "Reset value" etc.
                if t.lower().startswith(tuple(BAD_NAME_PREFIXES)) or RESET_NOISE_RE.search(t):
                    break
                    
                # CRITICAL FIX: If we have no name yet and this is the first desc part,
                # it might contain both name and description combined
                if not name and not desc_parts:
                    # This could be "FieldName Description text..."
                    # Check if it looks like it starts with a field name
                    # Field names are typically one word with letters/numbers/underscores followed by a space
                    # Common patterns: field_name, FieldName, FIELD_NAME, field123_name
                    if t and re.match(r'^[A-Za-z_][A-Za-z0-9_#{}]*(?:\[[^\]]*\])?\s', t):
                        # Likely starts with a field name (allows lowercase too)
                        name = t
                        i += 1
                        # Don't add to desc_parts, will be handled by field separation later
                    else:
                        desc_parts.append(t)
                        i += 1
                else:
                    desc_parts.append(t)
                    i += 1

            typ = ""
            reset = ""
            if i < N and is_type_token(lines[i]):
                typ = lines[i].strip()
                i += 1
                # Skip headers / page breaks
                while i < N and (lines[i].lower() in HEADER_LABELS or lines[i].startswith("__PAGE_BREAK_")):
                    i += 1
                if i < N and not (is_bits_token(lines[i]) or is_heading(lines[i]) or is_section_heading(lines[i])):
                    reset_candidate = lines[i].strip()
                    # don't keep obvious noise
                    if not (reset_candidate.lower().startswith(tuple(BAD_NAME_PREFIXES)) or RESET_NOISE_RE.search(reset_candidate)):
                        reset = reset_candidate
                    i += 1

            # Separate field name from embedded description if present
            field_name, extracted_desc = separate_field_name_from_description(name)
            
            # Combine descriptions - use extracted if no separate description found
            final_description = " ".join(desc_parts).strip()
            if not final_description and extracted_desc:
                # If desc_parts is empty but we extracted a description from the name, use it
                final_description = extracted_desc
            elif extracted_desc and final_description and not final_description.startswith(extracted_desc):
                # If we have both, combine them intelligently
                final_description = extracted_desc + " " + final_description
            elif not final_description and not extracted_desc and desc_parts == []:
                # If we have no description at all, it might all be in the name field
                # This handles the case where name contains both name and description
                final_description = extracted_desc if extracted_desc else ""
            
            # Extract embedded type and reset from description if type/reset are missing
            extracted_type, extracted_reset, cleaned_description = extract_embedded_type_and_reset(final_description)
            
            # Use extracted values if original type/reset are missing or empty
            final_type = typ if typ and typ != "-" else extracted_type
            final_reset = reset if reset and reset != "-" else extracted_reset
            final_description = cleaned_description if extracted_type else final_description
            
            # Apply smart defaults for fields still missing type/reset values
            if not final_type or final_type == "-":
                final_type, final_reset = infer_missing_type_and_reset(field_name if field_name else name, current_table)
                if not final_reset or final_reset == "-":
                    # Keep extracted reset if we have it, otherwise use inferred
                    final_reset = extracted_reset if extracted_reset else final_reset
            
            rows.append({
                "table": current_table,
                "register_name": current_reg_name or "",
                "bits": bits,
                "field_name": field_name if field_name else name,
                "description": final_description,
                "type": final_type,
                "reset": final_reset
            })
            continue

        i += 1

    # Diagnostic output for attribute tables
    print(f"[INFO] Found {len(attribute_tables)} attribute tables")
    
    return rows

# ------------------ Hot Fix Functions ------------------
def clean_reserved_name(name: str) -> str:
    """Hot fix: Clean up common PDF extraction artifacts in names"""
    if name == "ReservedReserved":
        return "Reserved"
    # Also handle potential other duplications
    if name == "RESRES" or name == "IMPLIMPLEM":
        return "Reserved"
    return name

def extract_embedded_type_and_reset(description: str) -> tuple:
    """
    Extract embedded type and reset values from description field.
    
    Handles patterns like:
    - "...description text W1C 0b0" -> ("W1C", "0x0", "description text")
    - "...description text RO 0b1" -> ("RO", "0x1", "description text")
    
    Returns: (extracted_type, extracted_reset_hex, cleaned_description)
    """
    if not description:
        return "", "", description
    
    # Pattern to match TYPE_TOKEN followed by reset value at end of description
    # Use pre-sorted TYPE_TOKENS for longest-first matching to avoid conflicts
    pattern = r'\s+(' + '|'.join(SORTED_TYPE_TOKENS) + r')\s+(0b[01]+|0x[0-9A-Fa-f]+|-)\s*$'
    match = re.search(pattern, description)
    
    if match:
        extracted_type = match.group(1)
        extracted_reset = match.group(2)
        
        # Convert binary reset values to hex format
        if extracted_reset.startswith('0b'):
            try:
                # Convert binary to integer, then to hex
                binary_value = int(extracted_reset[2:], 2)
                extracted_reset_hex = f"0x{binary_value:x}" if binary_value > 0 else "0x0"
            except ValueError:
                # If conversion fails, keep original
                extracted_reset_hex = extracted_reset
        elif extracted_reset.startswith('0x') or extracted_reset == '-':
            # Already hex or dash, keep as-is
            extracted_reset_hex = extracted_reset
        else:
            # Unknown format, keep as-is
            extracted_reset_hex = extracted_reset
        
        # Remove the matched pattern from description
        cleaned_description = description[:match.start()].strip()
        return extracted_type, extracted_reset_hex, cleaned_description
    
    return "", "", description

def infer_missing_type_and_reset(field_name: str, table_name: str) -> tuple:
    """
    Infer missing type and reset values based on field name patterns and context.
    
    Args:
        field_name: The name of the field missing type/reset
        table_name: The table/register context
    
    Returns:
        tuple: (inferred_type, inferred_reset)
    """
    if not field_name:
        return "RW", "0x0"
    
    field_lower = field_name.lower()
    table_lower = table_name.lower() if table_name else ""
    
    # Error status/reporting fields - typically read-only
    if any(pattern in field_lower for pattern in ['ierr', 'serr', 'errstatus', 'error']):
        return "RO", "-"  # Implementation-defined
    
    # Performance monitoring event IDs - read-write configuration
    if 'pmu_event' in field_lower and '_id' in field_lower:
        return "RW", "0x0"
    
    # Credit control fields - read-write configuration  
    if any(pattern in field_lower for pattern in ['num_', '_crds', 'credits']):
        return "RW", "0x0"
    
    # Control and configuration fields
    if any(pattern in field_lower for pattern in ['_ctl', '_cfg', '_config', '_control']):
        return "RW", "0x0"
    
    # Selection and enable fields
    if any(pattern in field_lower for pattern in ['_sel', '_en', '_enable', '_disable']):
        return "RW", "0x0"
    
    # Memory attributes and capabilities
    if any(pattern in field_lower for pattern in ['memory_attributes', 'capabilities', '_cap']):
        return "RO", "-"  # Usually implementation-defined
    
    # Address and offset fields
    if any(pattern in field_lower for pattern in ['offset', 'address', '_addr']):
        return "RW", "0x0"
    
    # Register offset table entries
    if 'registeroffset' in field_lower:
        return "RO", "-"  # Implementation-defined
    
    # Version and architecture fields
    if any(pattern in field_lower for pattern in ['archver', 'archrevision', 'archpart']):
        return "RO", "-"  # Implementation-defined
    
    # Status fields
    if 'status' in field_lower:
        return "RO", "0x0"
    
    # Change tracking fields (likely event counters)
    if field_lower == 'change':
        return "RO", "0x0"
    
    # Cache and memory control
    if any(pattern in field_lower for pattern in ['cache', 'allocate', 'cacheable']):
        return "RW", "0x0"
    
    # Default for control registers: read-write with zero reset
    if any(pattern in table_lower for pattern in ['_ctl', '_cfg', '_config']):
        return "RW", "0x0"
    
    # Conservative default: read-write with zero reset
    return "RW", "0x0"

def separate_field_name_from_description(name_str: str) -> tuple:
    """
    Separate field name from embedded description using space as delimiter.
    Also handles cases where binary values (0b0, 0b1) are concatenated to field names.
    
    Input: "drop_transactions_on_inbound_cxl_viral When set, write/read requests..."
    Output: ("drop_transactions_on_inbound_cxl_viral", "When set, write/read requests...")
    
    Input: "chi_pftgt_hint_disable0b1 CHI Prefetch target..."
    Output: ("chi_pftgt_hint_disable", "0b1 CHI Prefetch target...")
    """
    if not name_str:
        return '', ''
    
    name_str = str(name_str).strip()
    
    # First check if field name ends with binary value pattern (0b0, 0b1, etc.)
    binary_pattern = re.match(r'^(.+?)(0b[01]+)(.*)$', name_str)
    if binary_pattern:
        field_name = binary_pattern.group(1)
        binary_val = binary_pattern.group(2)
        rest = binary_pattern.group(3).strip()
        
        # Combine binary value with rest as description
        if rest:
            description = f"{binary_val} {rest}"
        else:
            description = binary_val
        
        return field_name, description
    
    # Otherwise, split on first space that's not inside brackets
    # This handles cases like htg#{index*4 + 3}_hn_cal_mode_en where spaces can be inside {}
    
    in_brackets = False
    bracket_depth = 0
    split_pos = -1
    
    for i, char in enumerate(name_str):
        if char == '{':
            bracket_depth += 1
            in_brackets = True
        elif char == '}':
            bracket_depth -= 1
            if bracket_depth == 0:
                in_brackets = False
        elif char == ' ' and not in_brackets:
            # Found first space outside brackets
            split_pos = i
            break
    
    if split_pos > 0:
        field_name = name_str[:split_pos]
        description = name_str[split_pos+1:]
        return field_name, description
    
    # No space found outside brackets - return whole string as field name
    return name_str, ''

def separate_name_and_type(name: str) -> tuple:
    """
    FIXED: Separate type tokens that were accidentally concatenated to register names.
    This addresses the parsing issue where type tokens like "RW" appear concatenated 
    in the name field, both with and without spaces.
    
    Examples:
        "register_name RW" -> ("register_name", "RW")
        "sys_cache_reg0-3RW" -> ("sys_cache_reg0-3", "RW")
        "some_registerRO" -> ("some_register", "RO")
        "ARROW" -> ("ARROW", "")  # Not separated - legitimate word
    
    Returns: (cleaned_name, extracted_type)
    """
    if not name:
        return name, ""
    
    # First check for space-separated type tokens (existing logic)
    parts = name.split()
    if len(parts) >= 2:
        last_part = parts[-1]
        if is_type_token(last_part):
            # Found a type token at the end - separate it
            cleaned_name = " ".join(parts[:-1])
            return cleaned_name, last_part
    
    # NEW: Check for directly concatenated type tokens (no space)
    # Use pre-sorted tokens for performance
    for token in SORTED_TYPE_TOKENS:
        if name.endswith(token):
            # Extract the potential name part
            potential_name = name[:-len(token)]
            
            # Validate that this is a legitimate separation
            if is_valid_name_type_separation(potential_name, token, name):
                return potential_name, token
    
    return name, ""

def is_valid_name_type_separation(potential_name: str, token: str, original_name: str) -> bool:
    """
    Validate that separating a type token from a name makes sense.
    This prevents false positives where legitimate names end with type-like strings.
    
    Examples:
        ("sys_cache_reg0-3", "RW", "sys_cache_reg0-3RW") -> True
        ("ARR", "OW", "ARROW") -> False  # Prevents breaking legitimate words
        ("register_name", "RW", "register_nameRW") -> True
    
    Args:
        potential_name: The candidate name after removing the type token
        token: The type token that was found
        original_name: The original concatenated string
    
    Returns:
        bool: True if the separation is valid, False otherwise
    """
    if not potential_name:
        return False
    
    # Name must contain at least one letter or underscore
    if not re.search(r'[A-Za-z_]', potential_name):
        return False
    
    # For very short potential names, be more conservative
    if len(potential_name) < MIN_NAME_LENGTH:
        return False
    
    # Common patterns that suggest a valid separation:
    # 1. Name ends with a number or hyphen before the type (common in register names)
    if re.search(r'[0-9-]$', potential_name):
        return True
    
    # 2. Name ends with an underscore (snake_case pattern)
    if potential_name.endswith('_'):
        return True
    
    # 3. For longer names (likely legitimate register names), allow separation
    if len(potential_name) >= LONG_NAME_THRESHOLD:
        return True
    
    # 4. Be cautious with short names that might be false positives
    # For example, "ROW" -> "RO" + "W" would be wrong
    # But "register_nameRW" -> "register_name" + "RW" is likely correct
    
    # Allow if the potential name looks like a typical register name pattern
    if re.match(r'^[a-z][a-z0-9_]*[a-z0-9]$', potential_name, re.IGNORECASE):
        return True
    
    return False

def clean_rows(rows: list, is_attr: bool = False) -> list:
    """
    Apply hot fixes to clean up extracted rows.
    
    This function:
    - Filters out invalid register entries (noise/junk data)
    - Separates type tokens accidentally concatenated to register names
    - Cleans up common PDF extraction artifacts (e.g., "ReservedReserved")
    - Normalizes empty/dash fields
    - Sets appropriate descriptions for Reserved fields
    
    Examples:
        Input row: {"name": "register_nameRW", "type": ""}
        Output row: {"name": "register_name", "type": "RW"}
    
    Args:
        rows: List of row dictionaries to clean
        is_attr: Whether these are attribute rows (vs register rows)
    
    Returns:
        list: Cleaned rows with fixes applied
    """
    cleaned = []
    for row in rows:
        # Determine which column contains the name based on whether this is an attribute row
        name_key = 'field_name' if is_attr else 'name'
        
        # ENHANCED: Skip invalid register entries that are actually noise/junk data
        if name_key in row:
            name_lower = row[name_key].lower()
            # Skip entries that are clearly document boilerplate/metadata
            if name_lower in ['non-confidential', 'usage constraints', 'usage constraint']:
                continue
            # Skip entries that contain document boilerplate patterns
            if document_boilerplate_re.search(row[name_key]):
                continue
            # ENHANCED: Skip entries that match boilerplate sentence patterns
            if boilerplate_sentence_re.match(row[name_key]):
                continue
            # CRITICAL FIX: Explicit filtering for remaining boilerplate entries
            name_stripped = row[name_key].strip('"').strip()  # Remove quotes and whitespace
            if name_stripped in EXPLICIT_BOILERPLATE_STRINGS:
                continue
            if name_stripped.startswith("This register is owned in the Non-secure space"):
                continue
            # ENHANCED: Skip entries with extremely long names (paragraph-length boilerplate)
            if len(row[name_key]) > 120:
                continue
            # ENHANCED: Skip entries that contain multiple sentences
            if re.search(r'\. [A-Z]', row[name_key]):
                continue
            
            # CRITICAL FIX: Skip malformed "Reserved" entries with concatenated text
            if is_reserved_concatenation_artifact(row[name_key]):
                continue
        
        # FIXED: Separate type tokens that were accidentally concatenated to names
        if name_key in row:
            original_name = row[name_key]
            cleaned_name, extracted_type = separate_name_and_type(original_name)
            row[name_key] = clean_reserved_name(cleaned_name)
            
            # If we found a type in the name and the type field is empty, use the extracted type
            if extracted_type and ('type' not in row or not row['type'] or row['type'] == "-"):
                row['type'] = extracted_type
        
        # Clean empty or dash-only fields
        for key in row:
            if row[key] == "‑" or row[key] == "−":  # Unicode dashes
                row[key] = "-"
            elif row[key] == "" and key in ['type', 'reset', 'description']:
                row[key] = "-"
        
        # Hot fix: For Reserved fields, ensure description is properly set
        if name_key in row and row[name_key] == 'Reserved' and 'description' in row:
            if not row['description'] or row['description'] == "-":
                row['description'] = "Reserved for future use"
        
        cleaned.append(row)
    return cleaned

# ------------------ Concatenation Splitting ------------------
def split_concatenated_registers(rows: list) -> list:
    """
    Split concatenated register entries that were incorrectly merged in the description field.
    
    PDF extraction sometimes concatenates multiple register entries on the same line,
    causing them to be parsed as a single row with a very long description.
    This function detects and splits them into separate rows.
    
    Example:
        Input: description = "por_reg1 0xD908 por_reg2 RW por_reg2 0xF700 por_reg3 RO por_reg3"
        Output: Multiple separate register rows
    """
    import re
    
    # Pattern to detect register entries: offset (0x...) followed by name and type
    # This matches patterns like: "0xD908 por_ccla_pmu_event_sel RW"
    # Also handles names with embedded spaces from PDF extraction artifacts
    # The name pattern allows for register-like names that may have spaces
    register_pattern = re.compile(r'(0x[0-9A-Fa-f]+)\s+([a-zA-Z_][a-zA-Z0-9_\- ]*?)\s+(' + '|'.join(TYPE_TOKENS) + r')\b')
    
    expanded_rows = []
    
    for row in rows:
        # Check if description field contains concatenated registers
        if 'description' in row and row['description']:
            desc = row['description']
            
            # Look for register patterns in the description
            matches = list(register_pattern.finditer(desc))
            
            if matches:
                # First, add the original row with cleaned description
                # Keep only the part before the first embedded register
                first_match_pos = matches[0].start()
                if first_match_pos > 0:
                    # Keep original row with truncated description
                    clean_desc = desc[:first_match_pos].strip()
                    row['description'] = clean_desc if clean_desc else row.get('name', '')
                    expanded_rows.append(row.copy())
                else:
                    # The description starts with a register pattern, keep original row as-is
                    row['description'] = row.get('name', '')
                    expanded_rows.append(row.copy())
                
                # Extract each embedded register as a new row
                for match in matches:
                    offset = match.group(1)
                    name = match.group(2)
                    reg_type = match.group(3)
                    
                    # Clean up the name - remove spaces that shouldn't be there
                    # Spaces after underscores are PDF extraction artifacts
                    name = name.replace('_ ', '_')
                    
                    # Find description for this register (text after the type until next register or end)
                    desc_start = match.end()
                    desc_end = len(desc)
                    
                    # Look for next register pattern
                    for next_match in matches:
                        if next_match.start() > match.end():
                            desc_end = next_match.start()
                            break
                    
                    # Extract description text
                    reg_desc = desc[desc_start:desc_end].strip()
                    
                    # Remove redundant name from description if it starts with the name
                    if reg_desc.startswith(name):
                        reg_desc = reg_desc[len(name):].strip()
                    
                    # Create new row for this register
                    new_row = {
                        'table': row.get('table', ''),
                        'offset': offset,
                        'name': name,
                        'type': reg_type,
                        'description': reg_desc if reg_desc else name
                    }
                    
                    # Skip if this looks like a duplicate or noise
                    if name and not name.startswith('0x'):
                        expanded_rows.append(new_row)
            else:
                # No concatenation detected, keep row as-is
                expanded_rows.append(row)
        else:
            # No description field or empty description, keep row as-is
            expanded_rows.append(row)
    
    return expanded_rows

# ------------------ Fix for missing high-order Reserved fields ------------------
def determine_64bit_registers(df_regs):
    """
    Analyze register offsets to determine which registers are 64-bit.
    64-bit registers have 8-byte aligned offsets (0x8 difference).
    32-bit registers have 4-byte aligned offsets (0x4 difference).
    
    Returns: dict mapping register_name -> bit_width (32 or 64)
    """
    register_sizes = {}
    
    # Group by table to analyze offset patterns within each table
    for table_name in df_regs['table'].unique():
        table_regs = df_regs[df_regs['table'] == table_name].copy()
        
        # Parse offsets to numeric values for analysis
        offsets = []
        names = []
        for _, row in table_regs.iterrows():
            offset_str = str(row['offset'])
            name = row['name']
            
            # Handle simple offset format (0xNNNN)
            if offset_str.startswith('0x') and ':' not in offset_str:
                try:
                    offset_val = int(offset_str, 16)
                    offsets.append(offset_val)
                    names.append(name)
                except:
                    continue
            # Handle array format ({N-M} 0xSTART : 0xEND)
            elif ':' in offset_str:
                # Extract the start offset
                match = re.search(r'0x([0-9A-Fa-f]+)', offset_str)
                if match:
                    try:
                        offset_val = int(match.group(1), 16)
                        offsets.append(offset_val)
                        names.append(name)
                    except:
                        continue
        
        # Analyze offset differences to determine register sizes
        if len(offsets) > 1:
            # Sort by offset to analyze sequential registers
            sorted_pairs = sorted(zip(offsets, names))
            
            for i in range(len(sorted_pairs) - 1):
                curr_offset, curr_name = sorted_pairs[i]
                next_offset, next_name = sorted_pairs[i + 1]
                
                diff = next_offset - curr_offset
                
                # Common patterns:
                # 4 = 32-bit register
                # 8 = 64-bit register
                # Larger differences may indicate arrays or gaps
                
                if diff == 8:
                    # Strong evidence of 64-bit register
                    register_sizes[curr_name] = 64
                elif diff == 4:
                    # Evidence of 32-bit register
                    register_sizes[curr_name] = 32
                elif diff % 8 == 0 and diff > 8:
                    # Likely 64-bit with gap or array
                    register_sizes[curr_name] = 64
                elif diff % 4 == 0 and diff > 4:
                    # Could be 32-bit with gap
                    if curr_name not in register_sizes:
                        register_sizes[curr_name] = 32
            
            # Handle the last register in sequence
            # If previous registers in the block were 64-bit, assume last is too
            if sorted_pairs:
                last_name = sorted_pairs[-1][1]
                if last_name not in register_sizes:
                    # Check if most registers in this table are 64-bit
                    sizes_in_table = [register_sizes.get(n, 0) for n in names if n in register_sizes]
                    if sizes_in_table and sum(s == 64 for s in sizes_in_table) > sum(s == 32 for s in sizes_in_table):
                        register_sizes[last_name] = 64
    
    return register_sizes

def add_missing_highorder_reserved_fields(df_attrs, register_sizes):
    """
    Add missing Reserved fields for 64-bit registers.
    
    For 64-bit registers, detect and fill ALL gaps in bit coverage,
    not just high-order bits.
    """
    new_rows = []
    added_count = 0
    
    # First, process existing rows
    for _, row in df_attrs.iterrows():
        new_rows.append(row.to_dict())
    
    # Group by table and register name to analyze bit coverage
    for table_name in df_attrs['table'].unique():
        table_attrs = df_attrs[df_attrs['table'] == table_name]
        
        # Extract register name from table name
        # e.g., "Table 8-17: por_ccg_ha_cfg_ctl attributes" -> "por_ccg_ha_cfg_ctl"
        # Include hyphens to match names like "por_ccg_ha_link0-2_cache_id_ctl"
        match = re.search(r':\s*([a-zA-Z0-9_\-]+)\s+attributes', table_name, re.IGNORECASE)
        if not match:
            continue
            
        register_name = match.group(1)
        
        # Check if this is a 64-bit register
        reg_size = register_sizes.get(register_name)
        if reg_size != 64 and reg_size != 32:
            continue
        
        # Determine the expected max bit (31 for 32-bit, 63 for 64-bit)
        expected_max_bit = 63 if reg_size == 64 else 31
        
        # Build a bit coverage map
        covered_bits = set()
        for _, row in table_attrs.iterrows():
            bits_str = str(row['bits'])
            
            # Parse different bit formats
            if ':' in bits_str:
                # Range format like "31:16" or "63:32"
                parts = bits_str.split(':')
                if len(parts) == 2:
                    try:
                        high = int(parts[0])
                        low = int(parts[1])
                        for bit in range(low, high + 1):
                            covered_bits.add(bit)
                    except ValueError:
                        continue
            else:
                # Single bit format like "0" or "31"
                try:
                    bit = int(bits_str)
                    covered_bits.add(bit)
                except ValueError:
                    continue
        
        # Find gaps in bit coverage
        gaps = []
        if covered_bits:
            min_covered = min(covered_bits)
            max_covered = max(covered_bits)
            
            # Check for gaps between covered bits
            for bit in range(0, expected_max_bit + 1):
                if bit not in covered_bits:
                    # Start of a gap
                    if not gaps or bit != gaps[-1][1] + 1:
                        gaps.append([bit, bit])
                    else:
                        # Extend current gap
                        gaps[-1][1] = bit
            
            # Consolidate gaps into ranges
            reserved_ranges = []
            for gap_start, gap_end in gaps:
                if gap_start == gap_end:
                    reserved_ranges.append(str(gap_start))
                else:
                    reserved_ranges.append(f"{gap_end}:{gap_start}")
        else:
            # No bits covered at all - add full range
            reserved_ranges = [f"{expected_max_bit}:0"]
        
        # Add Reserved fields for all gaps
        for reserved_bits in reserved_ranges:
            # Check if this Reserved field already exists
            exists = False
            for _, existing in table_attrs.iterrows():
                if str(existing['bits']) == reserved_bits and 'reserved' in str(existing['name']).lower():
                    exists = True
                    break
            
            if not exists:
                new_row = {
                    'table': table_name,
                    'bits': reserved_bits,
                    'name': 'Reserved',
                    'description': 'Reserved for future use',
                    'type': 'RO',
                    'reset': '-'
                }
                new_rows.append(new_row)
                added_count += 1
                print(f"[INFO] Added [{reserved_bits}] Reserved field for {register_name}")
    
    if added_count > 0:
        print(f"[INFO] Total Reserved fields added: {added_count}")
    
    return pd.DataFrame(new_rows)

# ------------------ Fix for missing attribute tables ------------------
def inject_missing_hdm_decoder_fields(df_attrs, df_regs):
    """
    Inject known missing fields for hdm_decoder registers that have no attributes.
    This is a workaround for PDF extraction failures on specific tables.
    """
    new_rows = []
    injected_count = 0
    
    # Known missing hdm_decoder field definitions based on CXL specification
    missing_definitions = {
        'por_ccla_cxl_hdm_decoder_0-7_base_low': [
            {'bits': '31:28', 'name': 'Memory_Base_Low_#{index}', 
             'description': 'Corresponds to bits 31:28 of the base of the address range covered by HDM decoder', 
             'type': 'RWL', 'reset': '0x0'}
        ],
        'por_ccla_cxl_hdm_decoder_0-7_base_high': [
            {'bits': '31:0', 'name': 'Memory_Base_High_#{index}', 
             'description': 'Corresponds to bits 63:32 of the base of the address range covered by HDM decoder', 
             'type': 'RWL', 'reset': '0x0'}
        ],
        'por_cxlapb_cxl_hdm_decoder_0-7_base_low': [
            {'bits': '31:28', 'name': 'Memory_Base_Low_#{index}', 
             'description': 'Corresponds to bits 31:28 of the base of the address range covered by HDM decoder', 
             'type': 'RWL', 'reset': '0x0'}
        ],
        'por_cxlapb_cxl_hdm_decoder_0-7_base_high': [
            {'bits': '31:0', 'name': 'Memory_Base_High_#{index}', 
             'description': 'Corresponds to bits 63:32 of the base of the address range covered by HDM decoder', 
             'type': 'RWL', 'reset': '0x0'}
        ],
        'por_ccla_dvsec_cxl_range_1_base_high': [
            {'bits': '31:0', 'name': 'Memory_Base_High', 
             'description': 'Memory Base High', 
             'type': 'RW', 'reset': '0x0'}
        ],
        'por_ccla_dvsec_cxl_range_2_base_high': [
            {'bits': '31:0', 'name': 'Memory_Base_High', 
             'description': 'Memory Base High', 
             'type': 'RW', 'reset': '0x0'}
        ],
        'por_cxlapb_dvsec_cxl_range_1_base_high': [
            {'bits': '31:0', 'name': 'Memory_Base_High', 
             'description': 'Memory Base High', 
             'type': 'RW', 'reset': '0x0'}
        ],
        'por_cxlapb_dvsec_cxl_range_2_base_high': [
            {'bits': '31:0', 'name': 'Memory_Base_High', 
             'description': 'Memory Base High', 
             'type': 'RW', 'reset': '0x0'}
        ]
    }
    
    # Check which registers have no attributes or only Reserved fields
    registers_with_attrs = set(df_attrs['table'].str.extract(r':\s*([a-zA-Z0-9_\-]+)\s+attributes', expand=False).dropna())
    all_registers = set(df_regs['name'])
    registers_without_attrs = all_registers - registers_with_attrs
    
    # Also check for registers that only have Reserved fields (need real fields)
    registers_needing_fields = set(registers_without_attrs)
    for reg_name in registers_with_attrs:
        reg_fields = df_attrs[df_attrs['table'].str.contains(f'{reg_name}\\s+attributes', regex=True, na=False)]
        if not reg_fields.empty:
            # Check if all fields are Reserved
            non_reserved = reg_fields[~reg_fields['name'].str.lower().str.contains('reserved', na=False)]
            if non_reserved.empty:
                # Only has Reserved fields, needs real fields
                if reg_name in missing_definitions:
                    registers_needing_fields.add(reg_name)
    
    print(f"[INFO] Found {len(registers_without_attrs)} registers without attributes")
    print(f"[INFO] Found {len(registers_needing_fields)} registers needing field injection")
    
    # Inject known missing fields
    for reg_name, fields in missing_definitions.items():
        if reg_name in registers_needing_fields:
            # Find the table name from register summaries
            reg_info = df_regs[df_regs['name'] == reg_name]
            if not reg_info.empty:
                table_name = reg_info.iloc[0]['table']
                # Extract table number
                table_match = re.match(r'(Table\s+\d+-\d+):', table_name)
                if table_match:
                    # Create attribute table name (guess the table number)
                    # For hdm_decoder, we know the pattern
                    if 'hdm_decoder_0-7_base_high' in reg_name:
                        if 'por_ccla' in reg_name:
                            attr_table = f"Table 8-121: {reg_name} attributes"
                        elif 'por_cxlapb' in reg_name:
                            attr_table = f"Table 8-281: {reg_name} attributes"
                    else:
                        # Generic pattern - use next table number
                        base_num = int(re.search(r'Table\s+\d+-(\d+):', table_name).group(1))
                        attr_table = f"Table 8-{base_num + 1}: {reg_name} attributes"
                    
                    for field in fields:
                        new_row = {
                            'table': attr_table,
                            'bits': field['bits'],
                            'name': field['name'],
                            'description': field['description'],
                            'type': field['type'],
                            'reset': field['reset']
                        }
                        new_rows.append(new_row)
                        injected_count += 1
                    
                    print(f"[INFO] Injected {len(fields)} fields for {reg_name}")
    
    # Add fallback fields for any remaining registers without attributes
    for reg_name in registers_without_attrs:
        if reg_name not in missing_definitions:
            reg_info = df_regs[df_regs['name'] == reg_name]
            if not reg_info.empty:
                table_name = reg_info.iloc[0]['table']
                # Determine register size based on offset pattern or name
                reg_size = 32  # Default
                if any(pattern in reg_name for pattern in ['_high', '_low', 'base', 'size', 'control']):
                    reg_size = 32  # These are typically 32-bit parts of 64-bit values
                
                # Create a generic data field
                attr_table = f"Table X-X: {reg_name} attributes (generated)"
                new_row = {
                    'table': attr_table,
                    'bits': f'{reg_size-1}:0',
                    'name': 'data',
                    'description': f'{reg_name} data (fallback field - original attributes missing)',
                    'type': reg_info.iloc[0].get('type', 'RW'),
                    'reset': '0x0'
                }
                new_rows.append(new_row)
                injected_count += 1
                print(f"[WARNING] Added fallback field for {reg_name} (no known definition)")
    
    if injected_count > 0:
        print(f"[INFO] Total fields injected: {injected_count}")
    
    return new_rows

def remove_spurious_reserved_entries(df):
    """
    Remove spurious Reserved entries that come from bit diagrams.
    These typically appear at the same offset as legitimate registers.
    """
    if df.empty:
        return df
    
    # Track rows to remove
    spurious_rows = []
    
    # Group by table and offset to find duplicates at same address
    for (table, offset), group in df.groupby(['table', 'offset']):
        if len(group) > 1:
            # Multiple registers at same offset - check for Reserved
            for idx, row in group.iterrows():
                name = str(row['name']).strip()
                # Mark spurious if name starts with "Reserved" and there's another register at same offset
                if name.lower().startswith('reserved'):
                    # Check if there's a non-Reserved entry at same offset
                    other_names = [str(r['name']).strip() for i, r in group.iterrows() if i != idx]
                    if any(not n.lower().startswith('reserved') for n in other_names):
                        spurious_rows.append(idx)
        elif len(group) == 1:
            # Single register - remove if it's just "Reserved" variants at common offsets
            row = group.iloc[0]
            name = str(row['name']).strip()
            offset_val = str(row['offset']).strip()
            
            # Remove standalone Reserved entries that are clearly from diagrams
            # These patterns come from bit field diagrams in register detail sections
            if (name.lower() == 'reserved' or 
                'reserved logical_id' in name.lower() or
                'reserveddtc_domain' in name.lower() or
                'reserved mem_data_credits' in name.lower() or
                (name.lower().startswith('reserved') and ('mem_data_credits' in name.lower() or
                                                           'logical_id' in name.lower() or
                                                           'dtc_domain' in name.lower() or
                                                           'num_device_port' in name.lower()))):
                # These are from bit field diagrams, not real registers
                spurious_rows.append(row.name)
    
    # Drop the spurious rows
    if spurious_rows:
        print(f"[INFO] Removing {len(spurious_rows)} spurious Reserved entries")
        df = df.drop(index=spurious_rows)
    
    return df

# ------------------ Driver ------------------
def extract(pdf_path: str, out_dir: str = "L1_pdf_analysis"):
    lines = get_all_lines(pdf_path)
    
    
    reg_rows = parse_register_tables(lines)
    attr_rows = parse_attribute_tables(lines)
    
    # Split concatenated register entries BEFORE other fixes
    reg_rows = split_concatenated_registers(reg_rows)
    
    # Apply hot fixes
    reg_rows = clean_rows(reg_rows, is_attr=False)
    attr_rows = clean_rows(attr_rows, is_attr=True)

    df_regs = pd.DataFrame(reg_rows)
    df_attrs = pd.DataFrame(attr_rows)

    # De-duplicate identical rows that can arise from odd page splits
    if not df_regs.empty:
        # hard filter: drop rows whose name contains reset-noise
        df_regs = df_regs[~df_regs['name'].str.contains(RESET_NOISE_RE, na=False, regex=True)]
        
        # Remove spurious Reserved entries from bit diagrams
        df_regs = remove_spurious_reserved_entries(df_regs)
        
        df_regs = df_regs.drop_duplicates(subset=["table","offset","name"], keep="first")
    if not df_attrs.empty:
        df_attrs = df_attrs.drop_duplicates()
    
    # Fix missing high-order Reserved fields for 64-bit registers
    # DISABLED: Field injection features - no longer adding Reserved fields or fallback fields
    # if not df_regs.empty and not df_attrs.empty:
    #     print("[INFO] Analyzing register offsets to identify 64-bit registers...")
    #     register_sizes = determine_64bit_registers(df_regs)
    #     
    #     print("[INFO] Adding missing high-order Reserved fields...")
    #     df_attrs = add_missing_highorder_reserved_fields(df_attrs, register_sizes)
    #     
    #     # Inject missing fields for registers that have no attributes
    #     print("[INFO] Checking for registers with missing attribute tables...")
    #     missing_fields = inject_missing_hdm_decoder_fields(df_attrs, df_regs)
    #     if missing_fields:
    #         # Append the injected fields to the attributes dataframe
    #         df_attrs = pd.concat([df_attrs, pd.DataFrame(missing_fields)], ignore_index=True)

    # Ensure output directory exists
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)

    out_regs = out_dir_path / "all_register_summaries.csv"
    out_attrs = out_dir_path / "all_register_attributes.csv"
    df_regs.to_csv(out_regs, index=False)
    df_attrs.to_csv(out_attrs, index=False)
    return {
        "register_rows": len(df_regs),
        "attribute_rows": len(df_attrs),
        "out_regs": str(out_regs),    # JSON-serializable
        "out_attrs": str(out_attrs)   # JSON-serializable
    }

def test_name_type_separation():
    """Quick test of the name/type separation fix"""
    test_cases = [
        "sys_cache_grp_hashed_regions_cxg_sa_nodeid_reg0-3RW",
        "register_nameRO",
        "some_register RW",
        "ARROW",  # Should not be separated
        "normal_name"
    ]
    
    print("Testing name/type separation fix:")
    for name in test_cases:
        clean_name, extracted_type = separate_name_and_type(name)
        print(f"  '{name}' -> name:'{clean_name}', type:'{extracted_type}'")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python l1_pdf_analysis.py <pdf_path> [out_dir]")
        print("       python l1_pdf_analysis.py --test  (to test the fix)")
        print("       python l1_pdf_analysis.py --from-text <text_path> [out_dir]  (to use existing text file)")
        print("Default output directory: L1_pdf_analysis/")
        sys.exit(1)
    
    if sys.argv[1] == "--test":
        test_name_type_separation()
        sys.exit(0)
    
    if sys.argv[1] == "--from-text":
        # Allow processing from existing text file
        if len(sys.argv) < 3:
            print("Usage: python l1_pdf_analysis.py --from-text <text_path> [out_dir]")
            sys.exit(1)
        text_path = sys.argv[2]
        out_dir = sys.argv[3] if len(sys.argv) >= 4 else "L1_pdf_analysis"
        
        # Check if we have a cleaned version and use it
        text_dir = os.path.dirname(text_path)
        cleaned_path = os.path.join(text_dir, "output_cleaned.txt")
        
        if os.path.exists(cleaned_path):
            print(f"[INFO] Using cleaned text file: {cleaned_path}")
            final_text_path = cleaned_path
        else:
            print(f"[INFO] Cleaning text file first...")
            clean_pdf_text(text_path, cleaned_path)
            final_text_path = cleaned_path
        
        # Temporarily replace get_all_lines to use text file directly
        original_get_all_lines = globals()['get_all_lines']
        globals()['get_all_lines'] = lambda _: get_lines_from_text(final_text_path)
        print(json.dumps(extract("dummy.pdf", out_dir)))
        globals()['get_all_lines'] = original_get_all_lines
    else:
        pdf_path = sys.argv[1]
        out_dir = sys.argv[2] if len(sys.argv) >= 3 else "L1_pdf_analysis"
        print(json.dumps(extract(pdf_path, out_dir)))
