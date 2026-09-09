"""
package_verify.py
Autonomous Packaging and Verification Suite for 'brand-ai-readiness-audit'.

Responsibilities:
1. Build 'brand-ai-readiness-audit.zip' with clean directory root containing all mandatory assets:
   - marketplace.json, README.md, requirements.txt, pyproject.toml, PROJECT.md, TEST_INFRA.md, TEST_READY.md
   - brand_ai_audit/ (CLI distribution bridge)
   - skills/ (5 skills + shared utils)
   - tests/ (complete verification suite + mock server)
   - Excludes: .git/, .agents/, __pycache__/, .pytest_cache/, *.pyc, *.pyo, temporary files.
2. Verify the generated zip archive:
   - Size check (> 0 bytes, <= 50 MB per hackathon rule).
   - Zip header & CRC32 integrity check.
   - Zero prohibited metadata or compiled artifacts.
   - All 5 skills (SKILL.md + scripts) and marketplace manifest present.
3. Extract to an isolated temporary directory and execute:
   - Full test suite via unittest discover.
   - Standalone CLI execution of the audit-orchestrator entrypoint against local MockServer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

# Ensure stdout handles UTF-8 safely on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
ZIP_OUTPUT_NAME = "brand-ai-readiness-audit.zip"
ZIP_OUTPUT_PATH = PROJECT_ROOT / ZIP_OUTPUT_NAME

REQUIRED_ROOT_FILES = [
    "marketplace.json",
    "README.md",
    "requirements.txt",
    "pyproject.toml",
    "PROJECT.md",
    "TEST_INFRA.md",
    "TEST_READY.md",
    "SECURITY.md",
    "sample_audit_report.json",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    ".gitignore",
]

REQUIRED_SKILLS = [
    ("audit-orchestrator", "run_audit.py"),
    ("crawl-render-audit", "check_crawler_render.py"),
    ("structured-data-audit", "check_structured_data.py"),
    ("freshness-corroboration", "check_freshness.py"),
    ("engagement-bounce-audit", "check_engagement.py"),
]

EXCLUDED_DIR_NAMES = {
    ".git",
    ".agents",
    "__pycache__",
    ".pytest_cache",
    ".idea",
    ".vscode",
    ".gemini",
}

EXCLUDED_FILE_PATTERNS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".DS_Store",
    "Thumbs.db",
    ZIP_OUTPUT_NAME.lower(),
    "package_verify.py",
    "build_report.py",
    "test_sample_output.json",
    "test_sample_report.html",
}


def compute_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def should_include_path(rel_path: Path) -> bool:
    """Determine whether a relative path should be included in the zip archive."""
    parts = rel_path.parts
    for part in parts:
        if part in EXCLUDED_DIR_NAMES:
            return False

    name = rel_path.name
    if name.lower() in EXCLUDED_FILE_PATTERNS:
        return False

    for pattern in EXCLUDED_FILE_PATTERNS:
        if pattern.startswith(".") and name.endswith(pattern):
            return False

    return True


def collect_package_files(project_root: Path) -> list[tuple[Path, str]]:
    """
    Collect all files to be packaged with their relative archive names.
    Returns list of (absolute_source_path, archive_relative_path).
    """
    files_to_pack: list[tuple[Path, str]] = []

    # 1. Root files
    for filename in REQUIRED_ROOT_FILES:
        src = project_root / filename
        if not src.is_file():
            raise FileNotFoundError(f"Mandatory root file not found: {filename}")
        files_to_pack.append((src, filename))

    # 2. Package directories
    package_dirs = ["skills", "brand_ai_audit", "tests", "docs", "benchmarks"]
    for pdir in package_dirs:
        target_dir = project_root / pdir
        if not target_dir.is_dir():
            raise FileNotFoundError(f"Mandatory directory not found: {pdir}")

        for root, dirs, files in os.walk(target_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]
            for f in files:
                src = Path(root) / f
                rel = src.relative_to(project_root)
                if should_include_path(rel):
                    archive_name = rel.as_posix()
                    files_to_pack.append((src, archive_name))

    # Sort files deterministically
    files_to_pack.sort(key=lambda item: item[1])
    return files_to_pack


def build_package(project_root: Path, output_zip: Path) -> dict:
    """
    Build the clean distribution zip package.
    Returns a dictionary of build statistics.
    """
    print(f"[*] Building package archive: {output_zip.name}")
    start_time = time.time()

    files = collect_package_files(project_root)
    print(f"[*] Collected {len(files)} target files for packaging.")

    if output_zip.exists():
        output_zip.unlink()

    total_uncompressed_bytes = 0
    with zipfile.ZipFile(output_zip, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src_path, arc_name in files:
            file_stat = src_path.stat()
            total_uncompressed_bytes += file_stat.st_size
            zf.write(src_path, arc_name)

    elapsed = time.time() - start_time
    compressed_bytes = output_zip.stat().st_size
    ratio = (1.0 - (compressed_bytes / total_uncompressed_bytes)) * 100 if total_uncompressed_bytes > 0 else 0

    stats = {
        "output_path": str(output_zip),
        "file_count": len(files),
        "uncompressed_bytes": total_uncompressed_bytes,
        "compressed_bytes": compressed_bytes,
        "compression_ratio_pct": round(ratio, 2),
        "sha256": compute_sha256(output_zip),
        "build_duration_sec": round(elapsed, 4),
    }

    print(f"[+] Package created successfully in {stats['build_duration_sec']}s")
    print(f"    - File Count         : {stats['file_count']}")
    print(f"    - Uncompressed Size  : {stats['uncompressed_bytes']:,} bytes")
    print(f"    - Compressed Size    : {stats['compressed_bytes']:,} bytes ({stats['compression_ratio_pct']}% saved)")
    print(f"    - SHA-256            : {stats['sha256']}")
    return stats


def verify_package(zip_path: Path) -> bool:
    """
    Perform deep verification of the distribution zip package:
    1. Archive existence and non-zero size (<= 50 MB)
    2. Zip header and CRC32 integrity check
    3. Structural inspection (zero prohibited files, all mandatory files present)
    4. Unpack into an isolated temporary directory
    5. Content checksum matching
    6. Execute full test suite inside extracted environment
    7. Execute standalone entrypoint CLI audit test against MockServer
    """
    print("\n" + "=" * 78)
    print("  PACKAGE ARCHIVE VERIFICATION & ISOLATED EXECUTION AUDIT")
    print("=" * 78)

    # 1. Existence and size
    if not zip_path.is_file():
        print(f"[!] FAIL: Zip archive does not exist at {zip_path}")
        return False

    size = zip_path.stat().st_size
    if size == 0:
        print("[!] FAIL: Zip archive is empty (0 bytes).")
        return False
    if size > 50 * 1024 * 1024:
        print(f"[!] FAIL: Archive size ({size:,} bytes) exceeds 50 MB limit.")
        return False
    print(f"[PASS] Archive file exists ({size:,} bytes, <= 50 MB constraint satisfied).")

    # 2. Zip integrity
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            corrupt = zf.testzip()
            if corrupt is not None:
                print(f"[!] FAIL: Archive CRC corruption detected in member: {corrupt}")
                return False
            namelist = zf.namelist()
    except Exception as e:
        print(f"[!] FAIL: Error opening zip file: {e}")
        return False
    print(f"[PASS] Archive zip structure and CRC32 checksums verified valid ({len(namelist)} entries).")

    # 3. Exclusions check
    for item in namelist:
        parts = item.split("/")
        for p in parts:
            if p in EXCLUDED_DIR_NAMES:
                print(f"[!] FAIL: Prohibited directory '{p}' found in zip entry: {item}")
                return False
        for ext in [".pyc", ".pyo", ".pyd"]:
            if item.endswith(ext):
                print(f"[!] FAIL: Prohibited compiled artifact found in zip: {item}")
                return False

    print("[PASS] Zero excluded metadata directories (.agents, .git) or compiled files (__pycache__, *.pyc) in archive.")

    # 4. Mandatory files check
    for req in REQUIRED_ROOT_FILES:
        if req not in namelist:
            print(f"[!] FAIL: Mandatory root file missing from archive: {req}")
            return False
    print(f"[PASS] All {len(REQUIRED_ROOT_FILES)} mandatory root documentation and configuration files present.")

    # Check 5 skills
    for skill_name, script_name in REQUIRED_SKILLS:
        skill_md = f"skills/{skill_name}/SKILL.md"
        skill_script = f"skills/{skill_name}/scripts/{script_name}"
        if skill_md not in namelist:
            print(f"[!] FAIL: SKILL.md missing for skill '{skill_name}': {skill_md}")
            return False
        if skill_script not in namelist:
            print(f"[!] FAIL: Script missing for skill '{skill_name}': {skill_script}")
            return False
    print("[PASS] All 5 skills, SKILL.md specifications, and Python scripts present.")

    # Check essential test infrastructure
    essential_tests = [
        "tests/mock_server.py",
        "tests/bootstrap.py",
        "tests/conftest.py",
        "tests/test_marketplace.py",
        "tests/test_skills.py",
        "tests/test_resilience.py",
        "tests/test_performance.py",
        "tests/test_bug_fixes.py",
    ]
    for t in essential_tests:
        if t not in namelist:
            print(f"[!] FAIL: Essential test file missing: {t}")
            return False
    print("[PASS] Complete test suite and mock server infrastructure present in archive.")

    # 5. Extraction into temporary isolated sandbox
    with tempfile.TemporaryDirectory(prefix="brand_ai_audit_test_") as temp_dir:
        temp_path = Path(temp_dir)
        print(f"\n[*] Extracting archive into isolated sandbox: {temp_path}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(temp_path)

        # Verify marketplace.json in extracted folder
        m_json_path = temp_path / "marketplace.json"
        try:
            with open(m_json_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            if len(manifest_data.get("skills", [])) != 5:
                print(f"[!] FAIL: Extracted marketplace.json skills count is {len(manifest_data.get('skills', []))}, expected 5")
                return False
            entrypoints = [s["name"] for s in manifest_data["skills"] if s.get("entrypoint") is True]
            if entrypoints != ["audit-orchestrator"]:
                print(f"[!] FAIL: Entrypoint invariant violated in extracted manifest: {entrypoints}")
                return False
            print("[PASS] Extracted marketplace.json manifest parsed and validated.")
        except Exception as e:
            print(f"[!] FAIL: Failed to parse extracted marketplace.json: {e}")
            return False

        # 6. Execute full test suite inside extracted directory
        print("\n[*] Executing full test suite inside isolated sandbox...")
        test_env = os.environ.copy()
        test_env["PYTHONPATH"] = str(temp_path)
        test_env["AUDIT_ALLOW_LOCAL_TEST"] = "1"

        test_proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            cwd=str(temp_path),
            env=test_env,
            capture_output=True,
            text=True,
        )

        print("\n--- Extracted Sandbox Test Output ---")
        print(test_proc.stdout)
        if test_proc.stderr:
            print("--- Extracted Test Stderr ---")
            print(test_proc.stderr)

        if test_proc.returncode != 0:
            print(f"[!] FAIL: Test suite failed inside extracted sandbox with exit code {test_proc.returncode}")
            return False
        print("[PASS] Full test suite PASSED inside extracted sandbox with 0 errors.")

        # 7. Execute standalone CLI audit test with mock server in sandbox
        print("\n[*] Executing standalone CLI audit sanity check against mock server...")
        mock_server_script = (
            f"import sys, time; sys.path.insert(0, r'{temp_path}'); "
            f"from tests.mock_server import MockServer; "
            f"s = MockServer(); url = s.start(); print(url, flush=True); "
            f"time.sleep(15); s.stop()"
        )
        mock_proc = subprocess.Popen(
            [sys.executable, "-c", mock_server_script],
            cwd=str(temp_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            mock_url = mock_proc.stdout.readline().strip()
            if not mock_url.startswith("http"):
                print(f"[!] FAIL: Could not start sandbox mock server: {mock_url}")
                mock_proc.kill()
                return False

            print(f"[*] Sandbox Mock Server active at {mock_url}")

            orch_script = temp_path / "skills" / "audit-orchestrator" / "scripts" / "run_audit.py"
            audit_proc = subprocess.run(
                [sys.executable, str(orch_script), "--url", f"{mock_url}/clean"],
                cwd=str(temp_path),
                env=test_env,
                capture_output=True,
                text=True,
            )

            if audit_proc.returncode != 0:
                print(f"[!] FAIL: Orchestrator CLI failed on /clean with exit code {audit_proc.returncode}: {audit_proc.stderr}")
                return False

            try:
                report = json.loads(audit_proc.stdout)
                if report.get("site") != f"{mock_url}/clean":
                    print(f"[!] FAIL: Report site mismatch: {report.get('site')}")
                    return False
                if report.get("summary", {}).get("total_findings") != 0 or report.get("geo_score") != 100:
                    print(f"[!] FAIL: Clean site report had unexpected findings or score: {report.get('summary')}, score: {report.get('geo_score')}")
                    return False
                print(f"[PASS] Orchestrator CLI successfully audited clean site: 0 findings reported, GEO Score {report.get('geo_score')}/100.")
            except json.JSONDecodeError as e:
                print(f"[!] FAIL: Orchestrator did not output valid JSON: {e}\nOutput was: {audit_proc.stdout}")
                return False

        finally:
            mock_proc.terminate()
            try:
                mock_proc.wait(timeout=2)
            except Exception:
                mock_proc.kill()

    print("\n" + "=" * 78)
    print("  PACKAGE VERIFICATION COMPLETE — 100% SUCCESS")
    print("=" * 78)
    return True


def main():
    parser = argparse.ArgumentParser(description="Package and verify brand-ai-readiness-audit distribution.")
    parser.add_argument("--package-only", action="store_true", help="Only build the zip package without verification.")
    parser.add_argument("--verify-only", action="store_true", help="Only verify the existing zip package.")
    args = parser.parse_args()

    output_zip = ZIP_OUTPUT_PATH

    if args.verify_only:
        success = verify_package(output_zip)
        sys.exit(0 if success else 1)

    stats = build_package(PROJECT_ROOT, output_zip)

    if not args.package_only:
        success = verify_package(output_zip)
        if not success:
            sys.exit(1)

    # Sync package to parent directory (workspace root)
    workspace_zip = PROJECT_ROOT.parent / ZIP_OUTPUT_NAME
    if workspace_zip.parent.exists():
        try:
            shutil.copy2(output_zip, workspace_zip)
            print(f"[+] Synced package to workspace root: {workspace_zip}")
        except Exception as e:
            print(f"[!] Note: Could not sync to workspace root: {e}")

    print(f"\n[+] Done. Distribution ready at: {output_zip}")
    sys.exit(0)


if __name__ == "__main__":
    main()
