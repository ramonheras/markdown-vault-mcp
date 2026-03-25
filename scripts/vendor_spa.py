#!/usr/bin/env python3
"""Vendor CDN dependencies into static/app.html for offline use.

Downloads pinned library versions and inlines them into the SPA HTML,
eliminating runtime CDN dependencies.  The source template is
``static/app.src.html`` (human-editable, with CDN ``<script src>`` tags);
this script produces ``static/app.html`` (self-contained, committed).

Usage::

    python scripts/vendor_spa.py              # Generate app.html
    python scripts/vendor_spa.py --check      # Verify app.html is up-to-date
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Vendored dependency versions — bump here when upgrading
# ---------------------------------------------------------------------------

VENDORED_VERSIONS: dict[str, dict[str, str]] = {
    "vis-network": {
        "version": "10.0.2",
        "url": "https://unpkg.com/vis-network@10.0.2/standalone/umd/vis-network.min.js",
        "sha256": "92a2603c7125a249f1b61f3c3a316b4041ef47b32f4433484e3471f140f91485",
        "type": "script",
    },
    "marked": {
        "version": "17.0.5",
        "url": "https://unpkg.com/marked@17.0.5/lib/marked.umd.js",
        "sha256": "0db7abc826b5ac76f6ed11951ae34074ba50438ce6ea8d52889203779e5cbbad",
        "type": "script",
    },
    "dompurify": {
        "version": "3.3.3",
        "url": "https://unpkg.com/dompurify@3.3.3/dist/purify.min.js",
        "sha256": "a95e028e5efd6a7413d1d18d6d9f918fdad19e2be6e962fcbaa10ab1b364725c",
        "type": "script",
    },
    "ext-apps": {
        "version": "1.3.1",
        "url": "https://unpkg.com/@modelcontextprotocol/ext-apps@1.3.1/app-with-deps",
        "sha256": "36495489aa8939e4eb7421c8a03c220b9f502d79e87895f88599eb6c02377fdd",
        "type": "module",
        "import_specifier": "@modelcontextprotocol/ext-apps",
    },
}

# Marker embedded in generated output for offline --check validation
_SOURCE_HASH_MARKER = "<!-- vendor-spa-source-sha256:{hash} -->"
_SOURCE_HASH_RE = re.compile(r"<!-- vendor-spa-source-sha256:([0-9a-f]{64}) -->")

_STATIC_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "markdown_vault_mcp" / "static"
)
_SRC_HTML = _STATIC_DIR / "app.src.html"
_OUT_HTML = _STATIC_DIR / "app.html"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _download(url: str) -> bytes:
    """Download *url* and return its raw bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": "vendor-spa/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        raise SystemExit(f"ERROR: failed to download {url}: {exc}") from exc


def _source_hash(src_html: str) -> str:
    """SHA-256 of source template + all vendored config fields."""
    h = hashlib.sha256(src_html.encode("utf-8"))
    for name in sorted(VENDORED_VERSIONS):
        cfg = VENDORED_VERSIONS[name]
        h.update(f"{name}={sorted(cfg.items())}".encode())
    return h.hexdigest()


def _inline_script(html: str, name: str, cfg: dict[str, str], js: str) -> str:
    """Replace ``<script src="…{name}…"></script>`` with an inline block."""
    if "</script>" in js.lower():
        raise ValueError(
            f"Vendored JS for '{name}' contains '</script>' — cannot safely inline"
        )
    pattern = re.compile(
        rf"<script\s+src=\"[^\"]*{re.escape(name)}[^\"]*\">\s*</script>",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if not match:
        raise ValueError(f"No <script src> tag matched for '{name}'")
    tag = f"<script>/* {name}@{cfg['version']} (vendored) */\n{js}</script>"
    return html[: match.start()] + tag + html[match.end() :]


def _inline_module(html: str, _name: str, cfg: dict[str, str], js: str) -> str:
    """Replace an ES module CDN import with an import-map + data-URI."""
    specifier = cfg["import_specifier"]
    b64 = base64.b64encode(js.encode()).decode("ascii")
    data_uri = f"data:text/javascript;base64,{b64}"

    import_map_obj = {"imports": {specifier: data_uri}}
    import_map = f'<script type="importmap">\n{json.dumps(import_map_obj)}\n</script>\n'

    # Insert the import map immediately before <script type="module">
    html = html.replace(
        '<script type="module">', import_map + '<script type="module">', 1
    )

    # Rewrite the import URL → bare specifier (derive pattern from cfg["url"])
    cdn_url = re.escape(cfg["url"])
    import_pattern = rf'from\s+"{cdn_url}"'
    new_html = re.sub(import_pattern, f'from "{specifier}"', html)
    if new_html == html:
        raise ValueError(
            f"Import rewrite failed: no 'from \"{cfg['url']}\"' found in HTML"
        )
    return new_html


def _verify_no_cdn_urls(html: str) -> None:
    """Verify no CDN URLs remain in the generated output."""
    for name, cfg in VENDORED_VERSIONS.items():
        url = cfg["url"]
        if url in html:
            raise ValueError(f"CDN URL for '{name}' still present in output: {url}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    """Entry point.  Returns 0 on success, 1 on failure."""
    check_mode = "--check" in sys.argv

    if not _SRC_HTML.exists():
        print(f"ERROR: source template not found: {_SRC_HTML}", file=sys.stderr)
        return 1

    src_text = _SRC_HTML.read_text(encoding="utf-8")

    # --check: offline validation via embedded source hash
    if check_mode:
        if not _OUT_HTML.exists():
            print(
                f"ERROR: {_OUT_HTML} does not exist — "
                "run  python scripts/vendor_spa.py  to generate it.",
                file=sys.stderr,
            )
            return 1
        current = _OUT_HTML.read_text(encoding="utf-8")
        m = _SOURCE_HASH_RE.search(current)
        if not m:
            print(
                "ERROR: app.html missing source hash marker — "
                "run  python scripts/vendor_spa.py  to regenerate.",
                file=sys.stderr,
            )
            return 1
        expected = _source_hash(src_text)
        if m.group(1) == expected:
            print("OK: app.html is up-to-date.")
            return 0
        print(
            "ERROR: app.html is out of date — "
            "run  python scripts/vendor_spa.py  to regenerate.",
            file=sys.stderr,
        )
        return 1

    # Generate mode: download, verify integrity, and inline
    html = src_text
    for name, cfg in VENDORED_VERSIONS.items():
        print(f"  Downloading {name}@{cfg['version']} …")
        raw = _download(cfg["url"])
        sha = hashlib.sha256(raw).hexdigest()
        print(f"    {len(raw):,} bytes  SHA-256: {sha[:16]}…")

        expected_sha = cfg["sha256"]
        if sha != expected_sha:
            print(
                f"ERROR: SHA-256 mismatch for {name}@{cfg['version']}\n"
                f"  expected: {expected_sha}\n"
                f"  got:      {sha}",
                file=sys.stderr,
            )
            return 1

        try:
            js = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SystemExit(
                f"ERROR: {name} download is not valid UTF-8: {exc}"
            ) from exc

        if cfg["type"] == "script":
            html = _inline_script(html, name, cfg, js)
        elif cfg["type"] == "module":
            html = _inline_module(html, name, cfg, js)
        else:
            raise ValueError(f"Unknown dependency type '{cfg['type']}' for '{name}'")

    _verify_no_cdn_urls(html)

    # Embed source hash for offline --check validation (use rfind to target
    # the actual HTML </head>, not occurrences inside inlined JS)
    marker = _SOURCE_HASH_MARKER.format(hash=_source_hash(src_text))
    idx = html.rfind("</head>")
    if idx == -1:
        raise ValueError("No </head> tag found in generated HTML")
    html = html[:idx] + marker + "\n" + html[idx:]

    # Ensure trailing newline
    if not html.endswith("\n"):
        html += "\n"

    _OUT_HTML.write_text(html, encoding="utf-8")
    print(f"\nWrote {_OUT_HTML} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
