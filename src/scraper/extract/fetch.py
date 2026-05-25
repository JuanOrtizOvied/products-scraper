"""HTTP fetcher with dual backend: Scrapling (default) + legacy httpx/Playwright."""
from __future__ import annotations

import asyncio
import re

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = structlog.get_logger()

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36 SabbiBot/0.1"
)
_DEFAULT_TIMEOUT = 30.0
_NOSCRIPT_JS_PATTERN = re.compile(
    r"<noscript>[^<]*(enable\s+javascript|javascript\s+must\s+be\s+enabled)",
    re.IGNORECASE,
)


class FetchError(RuntimeError):
    """Raised when a URL cannot be fetched (timeout, network, non-2xx)."""


def is_js_rendered(html: str) -> bool:
    """Heuristic: page needs JS to be usable.

    Signals (any triggers True):
    - <noscript>...enable javascript> pattern.
    - Visible body text after strip is below 1500 chars.
    - Modest body (<3000 chars) but with ≥30 <a> tags (SPA shell with nav).
    """
    if _NOSCRIPT_JS_PATTERN.search(html):
        return True
    num_links = len(re.findall(r"<a\b", html, re.IGNORECASE))
    visible = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r"<style[^>]*>.*?</style>", "", visible, flags=re.DOTALL | re.IGNORECASE)
    visible = re.sub(r"<[^>]+>", "", visible)
    body_len = len(visible.strip())
    if body_len < 1500:
        return True
    if body_len < 3000 and num_links >= 30:
        return True
    return False


def _get_backend() -> str:
    """Return the configured fetcher backend ('scrapling' or 'legacy')."""
    from scraper.config import get_settings

    return get_settings().fetcher_backend


async def _fetch_with_scrapling(url: str, timeout: float = 30.0) -> str:
    """Fetch HTML using Scrapling's StealthyFetcher (runs sync in executor)."""
    from scrapling.fetchers import StealthyFetcher

    loop = asyncio.get_event_loop()
    page = await loop.run_in_executor(
        None, lambda: StealthyFetcher.fetch(url, headless=True, network_idle=True)
    )
    return str(page.html_content)


async def _fetch_bytes_with_scrapling(url: str, timeout: float = 30.0) -> bytes:
    """Fetch raw bytes using Scrapling's Fetcher (runs sync in executor)."""
    from scrapling.fetchers import Fetcher

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None, lambda: Fetcher.get(url)
    )
    return response.body


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    reraise=True,
)
async def _fetch_with_httpx(url: str, timeout: float) -> str:
    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(
        timeout=timeout, headers=headers, follow_redirects=True
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


async def fetch_url(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    """Fetch URL HTML. Routes to scrapling or legacy httpx based on config."""
    backend = _get_backend()
    try:
        if backend == "scrapling":
            html = await _fetch_with_scrapling(url, timeout)
        else:
            html = await _fetch_with_httpx(url, timeout)
        log.info("fetch_url_success", url=url, backend=backend, length=len(html))
        return html
    except FetchError:
        raise
    except httpx.TimeoutException as e:
        raise FetchError(f"Timeout fetching {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code} for {url}") from e
    except httpx.TransportError as e:
        raise FetchError(f"Transport error for {url}: {e}") from e
    except Exception as e:
        raise FetchError(f"Fetch failed for {url} ({backend}): {e}") from e


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=10),
    reraise=True,
)
async def _fetch_bytes_with_httpx(url: str, timeout: float) -> bytes:
    headers = {"User-Agent": _USER_AGENT}
    async with httpx.AsyncClient(
        timeout=timeout, headers=headers, follow_redirects=True
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.content


async def fetch_url_bytes(url: str, timeout: float = _DEFAULT_TIMEOUT) -> bytes:
    """Fetch URL raw bytes. Routes to scrapling or legacy httpx based on config."""
    backend = _get_backend()
    try:
        if backend == "scrapling":
            data = await _fetch_bytes_with_scrapling(url, timeout)
        else:
            data = await _fetch_bytes_with_httpx(url, timeout)
        log.info("fetch_url_bytes_success", url=url, backend=backend, bytes=len(data))
        return data
    except FetchError:
        raise
    except httpx.TimeoutException as e:
        raise FetchError(f"Timeout fetching {url}: {e}") from e
    except httpx.HTTPStatusError as e:
        raise FetchError(f"HTTP {e.response.status_code} for {url}") from e
    except httpx.TransportError as e:
        raise FetchError(f"Transport error for {url}: {e}") from e
    except Exception as e:
        raise FetchError(f"Fetch failed for {url} ({backend}): {e}") from e


async def fetch_with_playwright(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    """Render page with Chromium for JS-heavy sites."""
    # Lazy import so Playwright isn't required for pure-httpx paths
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=_USER_AGENT)
                page = await context.new_page()
                await page.goto(url, timeout=timeout * 1000)
                await page.wait_for_load_state("networkidle", timeout=timeout * 1000)
                html = await page.content()
                log.info("fetch_playwright_success", url=url, length=len(html))
                return html
            finally:
                await browser.close()
    except Exception as e:
        raise FetchError(f"Playwright fetch failed for {url}: {e}") from e
