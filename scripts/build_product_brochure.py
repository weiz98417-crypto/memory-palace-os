"""Build the externally shareable, self-contained product brochure."""

from __future__ import annotations

import argparse
import base64
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_DIR = ROOT / "static" / "product"
TEMPLATE_PATH = PRODUCT_DIR / "index.template.html"
STYLE_PATH = PRODUCT_DIR / "styles.css"
SCRIPT_PATH = PRODUCT_DIR / "app.js"
OUTPUT_PATH = PRODUCT_DIR / "index.html"

STYLESHEET_PATTERN = re.compile(r'^\s*<link rel="stylesheet" href="styles\.css[^\"]*">\s*$', re.MULTILINE)
SCRIPT_PATTERN = re.compile(r'^\s*<script src="app\.js[^\"]*" defer></script>\s*$', re.MULTILINE)
DATA_IMAGE_PATTERN = re.compile(r'\sdata-image="assets/[^"]+"')
ASSET_PATTERN = re.compile(r'assets/(?P<name>[A-Za-z0-9._-]+)')


def asset_data_uri(asset_name: str) -> str:
    path = PRODUCT_DIR / "assets" / asset_name
    if not path.is_file():
        raise FileNotFoundError(f"Missing brochure asset: {path}")

    mime_type = "image/svg+xml" if path.suffix.lower() == ".svg" else "image/png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def build_html() -> str:
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    styles = STYLE_PATH.read_text(encoding="utf-8")
    script = SCRIPT_PATH.read_text(encoding="utf-8")

    html, stylesheet_count = STYLESHEET_PATTERN.subn(lambda _: f"\n  <style>\n{styles}\n  </style>", html)
    html, script_count = SCRIPT_PATTERN.subn(lambda _: f"\n  <script>\n{script}\n  </script>", html)
    if stylesheet_count != 1 or script_count != 1:
        raise RuntimeError("The brochure template must contain exactly one stylesheet and one script marker")

    # The lightbox reads the embedded child image directly, so data-image only
    # needs to remain as a behavior hook and does not duplicate large Base64 data.
    html = DATA_IMAGE_PATTERN.sub(" data-image", html)
    encoded_assets: dict[str, str] = {}

    def replace_asset(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in encoded_assets:
            encoded_assets[name] = asset_data_uri(name)
        return encoded_assets[name]

    html = ASSET_PATTERN.sub(replace_asset, html)
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail when index.html is not up to date")
    args = parser.parse_args()

    generated = build_html()
    if args.check:
        if not OUTPUT_PATH.is_file() or OUTPUT_PATH.read_text(encoding="utf-8") != generated:
            raise SystemExit("static/product/index.html is stale; run scripts/build_product_brochure.py")
        print(f"Up to date: {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")
        return 0

    OUTPUT_PATH.write_text(generated, encoding="utf-8", newline="\n")
    print(f"Built {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
