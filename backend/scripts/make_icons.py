"""Render frontend/public/favicon.svg into favicon.ico (16-256 px, used by `just shortcut`).

The SVG is the only source of the logo; rerun this after changing it:
    cd backend && uv run python scripts/make_icons.py
"""

import asyncio
import struct
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
SVG = ROOT / "frontend" / "public" / "favicon.svg"
ICO = ROOT / "frontend" / "public" / "favicon.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 256)


async def render(svg: str, sizes: tuple[int, ...]) -> list[bytes]:
    """PNG per size; the light color scheme gives the black tile."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(color_scheme="light")
        pngs = []
        for size in sizes:
            await page.set_viewport_size({"width": size, "height": size})
            await page.set_content(
                "<style>html, body { margin: 0; background: transparent }"
                f" svg {{ display: block; width: {size}px; height: {size}px }}</style>{svg}"
            )
            pngs.append(await page.screenshot(omit_background=True))
        await browser.close()
    return pngs


def pack_ico(images: list[tuple[int, bytes]]) -> bytes:
    """ICO container with PNG-compressed entries (Windows Vista and later)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        side = 0 if size >= 256 else size  # 0 means 256 in the directory entry
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        blobs += png
    return header + entries + blobs


def main() -> None:
    pngs = asyncio.run(render(SVG.read_text(), SIZES))
    ICO.write_bytes(pack_ico(list(zip(SIZES, pngs, strict=True))))
    print(f"Wrote {ICO} ({ICO.stat().st_size / 1024:.0f} KB, sizes {', '.join(map(str, SIZES))})")


if __name__ == "__main__":
    main()
