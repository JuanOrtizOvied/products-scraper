from unittest.mock import patch

import pytest


def test_is_js_rendered_short_body():
    from scraper.extract.fetch import is_js_rendered

    html = "<html><body></body></html>"
    assert is_js_rendered(html) is True


def test_is_js_rendered_enable_javascript_noscript():
    from scraper.extract.fetch import is_js_rendered

    html = """<html><body>
        <noscript>Please enable JavaScript to view this site</noscript>
        <div id="app"></div>
    </body></html>"""
    assert is_js_rendered(html) is True


def test_is_js_rendered_normal_content():
    from scraper.extract.fetch import is_js_rendered

    # Body must exceed 1500 visible chars after strip
    html = "<html><body>" + ("<p>real content here</p>" * 100) + "</body></html>"
    assert is_js_rendered(html) is False


def test_is_js_rendered_spa_shell_many_links():
    from scraper.extract.fetch import is_js_rendered

    # Body around 2000 chars + 40 <a> tags = shell-like SPA
    nav = "".join(f'<a href="/p{i}">Nav{i}</a>' for i in range(40))
    body = "<p>short intro</p>" * 30  # ~540 chars visible body
    html = f"<html><body>{nav}{body}</body></html>"
    assert is_js_rendered(html) is True


async def test_fetch_url_httpx_returns_html(httpx_mock):
    from scraper.extract.fetch import fetch_url

    httpx_mock.add_response(
        url="https://example.com/ficha",
        text="<html><body>content</body></html>",
        status_code=200,
    )
    with patch("scraper.extract.fetch._get_backend", return_value="legacy"):
        html = await fetch_url("https://example.com/ficha")
    assert "content" in html


@pytest.mark.httpx_mock(
    assert_all_requests_were_expected=False,
    can_send_already_matched_responses=True,
)
async def test_fetch_url_timeout_raises(httpx_mock):
    import httpx as hx

    from scraper.extract.fetch import FetchError, fetch_url

    httpx_mock.add_exception(hx.TimeoutException("timed out"))
    with patch("scraper.extract.fetch._get_backend", return_value="legacy"):
        with pytest.raises(FetchError):
            await fetch_url("https://slow.example.com/x", timeout=1.0)
