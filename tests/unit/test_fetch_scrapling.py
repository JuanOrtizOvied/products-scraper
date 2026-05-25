"""Tests for dual-backend fetch (scrapling vs legacy)."""

from unittest.mock import AsyncMock, patch

import pytest

from scraper.extract.fetch import FetchError, is_js_rendered


def test_is_js_rendered_short_body():
    html = "<html><body></body></html>"
    assert is_js_rendered(html) is True


def test_is_js_rendered_normal_content():
    html = "<html><body>" + ("<p>real content here</p>" * 100) + "</body></html>"
    assert is_js_rendered(html) is False


def test_fetch_error_is_runtime_error():
    assert isinstance(FetchError("test"), RuntimeError)


async def test_fetch_url_scrapling_backend():
    with patch(
        "scraper.extract.fetch._get_backend", return_value="scrapling"
    ), patch(
        "scraper.extract.fetch._fetch_with_scrapling",
        new_callable=AsyncMock,
        return_value="<html>scrapling</html>",
    ) as mock_fn:
        from scraper.extract.fetch import fetch_url

        html = await fetch_url("https://example.com")
        assert "scrapling" in html
        mock_fn.assert_called_once()


async def test_fetch_url_bytes_scrapling_backend():
    with patch(
        "scraper.extract.fetch._get_backend", return_value="scrapling"
    ), patch(
        "scraper.extract.fetch._fetch_bytes_with_scrapling",
        new_callable=AsyncMock,
        return_value=b"%PDF-1.4",
    ) as mock_fn:
        from scraper.extract.fetch import fetch_url_bytes

        data = await fetch_url_bytes("https://example.com/doc.pdf")
        assert data.startswith(b"%PDF")


async def test_fetch_url_scrapling_error_wraps():
    with patch(
        "scraper.extract.fetch._get_backend", return_value="scrapling"
    ), patch(
        "scraper.extract.fetch._fetch_with_scrapling",
        new_callable=AsyncMock,
        side_effect=Exception("refused"),
    ):
        from scraper.extract.fetch import fetch_url

        with pytest.raises(FetchError, match="refused"):
            await fetch_url("https://example.com")


async def test_fetch_url_legacy_backend():
    """Legacy backend still works when selected."""
    with patch(
        "scraper.extract.fetch._get_backend", return_value="legacy"
    ), patch(
        "scraper.extract.fetch._fetch_with_httpx",
        new_callable=AsyncMock,
        return_value="<html>legacy</html>",
    ) as mock_fn:
        from scraper.extract.fetch import fetch_url

        html = await fetch_url("https://example.com")
        assert "legacy" in html
        mock_fn.assert_called_once()


async def test_fetch_url_bytes_legacy_backend():
    """Legacy bytes backend still works when selected."""
    with patch(
        "scraper.extract.fetch._get_backend", return_value="legacy"
    ), patch(
        "scraper.extract.fetch._fetch_bytes_with_httpx",
        new_callable=AsyncMock,
        return_value=b"%PDF-legacy",
    ) as mock_fn:
        from scraper.extract.fetch import fetch_url_bytes

        data = await fetch_url_bytes("https://example.com/doc.pdf")
        assert data.startswith(b"%PDF")
