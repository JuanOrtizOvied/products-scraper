import subprocess
import sys


def test_classify_one_dry_run_works():
    """--no-api mode should print prompt preview without calling LLM."""
    # encoding="utf-8" is required on Windows: the CLI reconfigures its stdout
    # to utf-8 (see classify_one.py) to handle non-ASCII chars like "Pú", "á",
    # "→" in the prompt, so the parent must decode as utf-8 too. Without this,
    # the default cp1252 decode mangles those bytes and the assertion below
    # fails on a replacement-char mismatch.
    result = subprocess.run(
        [sys.executable, "-m", "scraper.scripts.classify_one", "--no-api", "Credicorp Crecimiento"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "System prompt" in result.stdout
    assert "Mercados Públicos" in result.stdout  # taxonomías presentes
