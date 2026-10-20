# /// script
# requires-python = ">=3.11"
# dependencies = ["curl-cffi", "pillow"]
# ///
"""Cache official SOLIDWORKS result previews beside practice drawings.

Usage: uv run --script tools/download_practice_previews.py
Existing JPEGs are validated and reused; missing HTTP resources are reported.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

from curl_cffi import requests
from PIL import Image

BASE_URL = "https://www.solidworks.com/sites/default/filesapi/practice-problems/thumbnails/"


def download(document):
    stem = document.stem.removesuffix("_ENG")
    target = document.with_name(f"{stem}_preview.jpg")
    if target.is_symlink():
        raise ValueError(f"Refusing symbolic link: {target}")
    if target.exists():
        with Image.open(target) as image:
            if image.format != "JPEG":
                raise ValueError(f"Not JPEG: {target}")
            image.verify()
    else:
        response = requests.get(f"{BASE_URL}{stem}.jpg", impersonate="chrome", timeout=30)
        if response.status_code == 404:
            return f"MISSING {stem}: HTTP 404"
        response.raise_for_status()
        with Image.open(BytesIO(response.content)) as image:
            if image.format != "JPEG":
                raise ValueError(f"Not JPEG: {response.url}")
            image.verify()
        with target.open("xb") as output:
            output.write(response.content)
    original = document.read_text()
    text = original
    preview = f"![ПРЕВЬЮ]({quote(target.name)})"
    drawing = f"![Чертёж]({quote(document.with_suffix('.jpg').name)})"
    if text.count(drawing) != 1:
        raise ValueError(f"Expected one drawing link: {document}")
    if preview not in text:
        anchor = "## Чертёж" if "## Чертёж" in text else drawing
        text = text.replace(anchor, preview + "\n\n" + anchor, 1)
    for heading, image in (("## Превью", preview), ("## Чертёж", drawing)):
        if heading not in text:
            text = text.replace(image, heading + "\n\n" + image, 1)
    if text != original:
        document.write_text(text)
    return f"OK {stem}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path,
                        default=Path(__file__).resolve().parents[1] / "PracticeProblems_ALL250_CSWA")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", nargs="+", help="Task stems without _ENG, e.g. PracticeProblems_10_1")
    args = parser.parse_args()
    documents = sorted(args.corpus.glob("Level*/*.md"))
    if args.only:
        documents = [path for path in documents if path.stem.removesuffix("_ENG") in args.only]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(download, documents))
    for result in results:
        print(result)
    missing = [result for result in results if result.startswith("MISSING")]
    print(f"Cached {len(results) - len(missing)}/{len(results)} previews; missing {len(missing)}")
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
