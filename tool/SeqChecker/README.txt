SeqChecker - EXR Sequence Validator
====================================

CLI Usage:
----------
seqchecker.exe <directory> [options]

Options:
  -o, --output <file>  Save report to specific path (default: auto-save to parent folder)
  -j, --json           Output in JSON format
  -q, --quiet          Suppress progress output
  -h, --help           Show help message

Examples:
---------
# Basic scan (auto-saves report to parent folder)
seqchecker.exe "P:\renders\shot01\SBS"

# Specify output path
seqchecker.exe "P:\renders\shot01\SBS" -o "D:\reports\shot01_report.txt"

# JSON output
seqchecker.exe "P:\renders\shot01\SBS" -j -o "D:\reports\shot01_report.json"

# Quiet mode (no console output)
seqchecker.exe "P:\renders\shot01\SBS" -q

Exit Codes:
-----------
0 = All files valid, no missing frames
1 = Errors found or missing frames detected

Report Output:
--------------
Auto-saved to: <parent_folder>/<sequence_name>_report.txt

Report format (text):
  RE-RENDER_FRAMES:
  123,456,789,1001,1002,1003

  ================================================================================
                           EXR SEQUENCE VALIDATION REPORT
  ================================================================================
  ... (summary, errors, missing frames)

Integration Example (Python):
-----------------------------
import subprocess
import re

result = subprocess.run(
    ['seqchecker.exe', r'P:\renders\shot01\SBS', '-q'],
    capture_output=True, text=True
)

# Read auto-generated report
with open(r'P:\renders\shot01\sequence_name_report.txt', 'r') as f:
    content = f.read()

# Parse re-render frames
match = re.search(r'RE-RENDER_FRAMES:\n([\d,]+)', content)
if match:
    frames = [int(x) for x in match.group(1).split(',')]
    print(f"Frames to re-render: {frames}")

Integration Example (Batch):
----------------------------
@echo off
seqchecker.exe "%1" -q
if %ERRORLEVEL% EQU 0 (
    echo All files OK
) else (
    echo Issues found - check report
)

Integration Example (PowerShell):
---------------------------------
$result = & .\seqchecker.exe "P:\renders\shot01\SBS" -q
if ($LASTEXITCODE -eq 0) {
    Write-Host "All files valid"
} else {
    $report = Get-Content "P:\renders\shot01\sequence_name_report.txt" -Raw
    if ($report -match "RE-RENDER_FRAMES:\r?\n([\d,]+)") {
        $frames = $matches[1] -split ","
        Write-Host "Re-render frames: $frames"
    }
}
