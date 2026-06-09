from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "platform-data"
DB_PATH = DATA_DIR / "icm-platform.sqlite3"
TEST_CASE_DIR = ROOT / "test-cases" / "icm"
REPORT_DIR = ROOT / "reports" / "runs"
OBSERVED_ASSET_DIR = ROOT / "reports" / "observed-assets"
SCREENSHOTS_LATEST_DIR = ROOT / "screenshots" / "latest"
SCREENSHOTS_RUNS_DIR = ROOT / "screenshots" / "runs"
SPEC_FILE = ROOT.parent / "doc" / "qa" / "functional-test-case-standard.md"
