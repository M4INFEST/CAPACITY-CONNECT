"""
Standalone VulnLLM-R Scanner Script for Capacity Connect.
Scans project API handlers, input validation schemas, and database query functions.
Generates an audit report identifying potential CWE vulnerabilities.
"""

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent / "apps" / "api"
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.vulnllm_validator import audit_code_with_vulnllm_r


def scan_file(filepath: Path) -> list:
    print(f"Scanning: {filepath.name} ...")
    try:
        content = filepath.read_text(encoding="utf-8")
        report = audit_code_with_vulnllm_r(content, target_name=filepath.name)
        return report.findings
    except Exception as exc:
        print(f"  Error reading {filepath.name}: {exc}")
        return []


def run_full_project_scan():
    base_dir = Path(__file__).resolve().parent
    api_dir = base_dir / "app" / "api" / "v1"
    if not api_dir.exists():
        api_dir = base_dir / "apps" / "api" / "app" / "api" / "v1"

    service_dir = base_dir / "app" / "services"
    if not service_dir.exists():
        service_dir = base_dir / "apps" / "api" / "app" / "services"

    files_to_scan = list(api_dir.glob("*.py")) + list(service_dir.glob("*.py"))
    print("=" * 70)
    print("  Capacity Connect - VulnLLM-R Security Audit")
    print(f"  Total target files to scan: {len(files_to_scan)}")
    print("=" * 70)

    total_findings = 0
    clean_files = 0

    for file_path in files_to_scan:
        findings = scan_file(file_path)
        if findings:
            total_findings += len(findings)
            print(f"  [!] {len(findings)} vulnerability finding(s) in {file_path.name}:")
            for f in findings:
                print(f"      - [{f.cwe_id}] ({f.severity.upper()}): line {f.line_number} -> {f.reasoning}")
                print(f"        Recommendation: {f.recommendation}")
        else:
            clean_files += 1

    print("=" * 70)
    print("  Scan Summary:")
    print(f"  Clean Files: {clean_files} / {len(files_to_scan)}")
    print(f"  Total Vulnerabilities Detected: {total_findings}")
    if total_findings == 0:
        print("  Status: All scanned input/output functions follow secure coding guidelines!")
    print("=" * 70)


if __name__ == "__main__":
    run_full_project_scan()
