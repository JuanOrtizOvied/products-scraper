import subprocess
import sys


def test_extract_one_requires_url_or_pdf():
    """Calling without --url or --pdf should error."""
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.extract_one"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode != 0


def test_extract_one_mutually_exclusive():
    """--url and --pdf together should error."""
    result = subprocess.run(
        [
            sys.executable, "-m", "scraper.scripts.extract_one",
            "--url", "https://x.com", "--pdf", "x.pdf",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    assert result.returncode != 0
