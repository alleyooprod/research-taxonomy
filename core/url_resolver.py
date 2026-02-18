"""URL resolution, validation, and parsing from files."""
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SHORTENER_PATTERNS = [
    r'bit\.ly', r'tinyurl\.com', r'linktr\.ee', r'linkin\.bio',
    r'beacons\.ai', r'msha\.ke', r'heylink\.me', r't\.co',
]

AGGREGATOR_DOMAINS = ['linktr.ee', 'linkin.bio', 'beacons.ai', 'msha.ke']

# Domains to skip when extracting company URLs from aggregator pages
# NOTE: Aggregator domains are NOT listed here — they get recursively resolved instead
SKIP_DOMAINS = [
    'instagram.com', 'twitter.com', 'x.com', 'facebook.com',
    'linkedin.com', 'tiktok.com', 'youtube.com', 'threads.net',
    'pinterest.com', 'snapchat.com', 'whatsapp.com',
    'spotify.com', 'apple.com/music', 'music.amazon',
    'paypal.me', 'venmo.com', 'cash.app', 'ko-fi.com',
    'patreon.com', 'gofundme.com', 'buymeacoffee.com',
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}


def _is_aggregator_url(url):
    """Check if a URL belongs to a known aggregator domain."""
    return any(domain in url.lower() for domain in AGGREGATOR_DOMAINS)


def _is_shortener_url(url):
    """Check if a URL belongs to a known shortener domain."""
    shortener_domains = ['bit.ly', 'tinyurl.com', 't.co', 'heylink.me']
    return any(domain in url.lower() for domain in shortener_domains)


def _extract_company_url_from_links(links):
    """Given a list of hrefs, find the most likely company URL.

    Skips social/payment domains. If an aggregator or shortener link is found,
    it's kept as a secondary candidate to be resolved further.
    """
    candidates = []
    aggregator_candidates = []
    for href in links:
        if not href or not href.startswith('http'):
            continue
        if any(skip in href.lower() for skip in SKIP_DOMAINS):
            continue
        if _is_aggregator_url(href) or _is_shortener_url(href):
            aggregator_candidates.append(href)
            continue
        candidates.append(href)
    # Prefer direct company URLs; fall back to aggregator links for recursive resolution
    if candidates:
        return candidates[0]
    if aggregator_candidates:
        return aggregator_candidates[0]
    return None


def _resolve_aggregator_with_playwright(url):
    """Use Playwright to render a JS-heavy aggregator page and extract links."""
    import asyncio
    from playwright.async_api import async_playwright

    async def _scrape():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)  # Wait for JS to render links
                hrefs = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('a[href]'))
                        .map(a => a.href)
                        .filter(h => h.startsWith('http'))
                """)
                return hrefs
            except Exception:
                return []
            finally:
                await browser.close()

    return asyncio.run(_scrape())


def resolve_shortened_url(url, _depth=0):
    """Resolve shortened URLs and link aggregators to actual destination.
    Returns (resolved_url, success_bool).

    Recursively follows aggregator-to-aggregator chains (max depth 3).
    """
    MAX_DEPTH = 3
    if _depth >= MAX_DEPTH:
        return url, False

    try:
        is_shortener = any(re.search(p, url) for p in SHORTENER_PATTERNS)
        is_aggregator = any(domain in url for domain in AGGREGATOR_DOMAINS)

        if not is_shortener and not is_aggregator:
            return url, True

        if is_aggregator:
            # Fast path: try requests + BeautifulSoup first
            company_url = None
            try:
                response = requests.get(url, timeout=10, headers=HEADERS)
                soup = BeautifulSoup(response.text, 'html.parser')
                hrefs = [link['href'] for link in soup.find_all('a', href=True)]
                company_url = _extract_company_url_from_links(hrefs)
            except Exception:
                pass

            # Fallback: use Playwright for JS-rendered aggregator pages
            if not company_url:
                try:
                    hrefs = _resolve_aggregator_with_playwright(url)
                    company_url = _extract_company_url_from_links(hrefs)
                except Exception as e:
                    print(f"  Warning: Playwright fallback failed for {url}: {e}")

            if company_url:
                # If the extracted URL is itself an aggregator/shortener, resolve recursively
                if _is_aggregator_url(company_url) or _is_shortener_url(company_url):
                    return resolve_shortened_url(company_url, _depth=_depth + 1)
                return company_url, True

            return url, False
        else:
            # Plain shortener (bit.ly, tinyurl, t.co, etc.) — follow redirects
            response = requests.head(url, allow_redirects=True, timeout=10)
            resolved = response.url
            # If the shortener resolved to an aggregator, resolve that too
            if _is_aggregator_url(resolved):
                return resolve_shortened_url(resolved, _depth=_depth + 1)
            return resolved, True

    except Exception as e:
        print(f"  Warning: Could not resolve {url}: {e}")
        return url, False


def validate_url(url):
    """Check if a URL is accessible. Returns (is_valid, reason)."""
    try:
        response = requests.head(url, timeout=10, allow_redirects=True, headers=HEADERS)
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}"
        return True, "OK"
    except requests.Timeout:
        return False, "Timeout"
    except requests.ConnectionError:
        return False, "Connection error"
    except Exception as e:
        return False, str(e)


def resolve_and_validate(url):
    """Full pipeline: resolve shortened URL then validate.
    Returns dict with url, resolved_url, status, reason.
    """
    resolved, resolved_ok = resolve_shortened_url(url)
    if not resolved_ok:
        return {
            'source_url': url,
            'url': resolved,
            'status': 'needs_review',
            'reason': 'Could not fully resolve link',
        }

    is_valid, reason = validate_url(resolved)
    return {
        'source_url': url,
        'url': resolved,
        'status': 'valid' if is_valid else 'error',
        'reason': reason,
    }


def extract_urls_from_text(text):
    """Extract URLs from freeform text, including bare domains without https://."""
    # Match full URLs with protocol
    pattern = r'https?://[^\s<>"{}|\\^`\[\])\',$]+'
    urls = re.findall(pattern, text)

    # Also match bare domains (e.g. "spectrum.life", "yulife.com")
    bare_domain_pattern = r'(?<![/@\w])([a-zA-Z0-9][-a-zA-Z0-9]*\.(?:com|org|net|io|co|life|health|ai|app|tech|dev|uk|de|fr|eu|us|ca|au|nz|ie|nl|se|no|fi|dk|es|it|pt|ch|at|be|in|sg|hk|jp|kr|br|mx|za|pl|cz|hu|ro|bg|hr|lt|lv|ee|sk|si)(?:\.[a-z]{2})?)(?:/[^\s<>"{}|\\^`\[\])\',$]*)?'
    bare_matches = re.findall(bare_domain_pattern, text)
    for domain in bare_matches:
        domain = domain.rstrip('.,;:!?)')
        full_url = f"https://{domain}"
        # Don't add if we already have this URL with protocol
        if full_url not in urls and f"http://{domain}" not in urls:
            urls.append(full_url)

    # Clean trailing punctuation
    cleaned = []
    for url in urls:
        url = url.rstrip('.,;:!?)')
        cleaned.append(url)
    return list(set(cleaned))


def parse_file(filepath):
    """Parse URLs from various file formats."""
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext in ['.txt', '.md']:
        text = path.read_text(encoding='utf-8')
        return extract_urls_from_text(text)

    elif ext == '.csv':
        import pandas as pd
        df = pd.read_csv(path)
        for col_name in ['url', 'link', 'URL', 'Link', 'website']:
            if col_name in df.columns:
                return df[col_name].dropna().tolist()
        return df.iloc[:, 0].dropna().tolist()

    elif ext in ['.xlsx', '.xls']:
        import pandas as pd
        df = pd.read_excel(path)
        for col_name in ['url', 'link', 'URL', 'Link', 'website']:
            if col_name in df.columns:
                return df[col_name].dropna().tolist()
        return df.iloc[:, 0].dropna().tolist()

    else:
        raise ValueError(f"Unsupported file format: {ext}")
