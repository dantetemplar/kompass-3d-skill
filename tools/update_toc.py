# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Update the existing Table of Contents from Markdown H2/H3 headings."""
import argparse
from pathlib import Path
import re


DEFAULT_DOCUMENT = (
    Path(__file__).resolve().parents[1] / "skills" / "kompass-3d-skill" / "SKILL.md"
)
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def headings(lines):
    """Yield (line index, level, title), excluding frontmatter and fenced code."""
    frontmatter = bool(lines and lines[0].strip() == "---")
    fence = None
    for index, line in enumerate(lines):
        if frontmatter:
            if index > 0 and line.strip() in ("---", "..."):
                frontmatter = False
            continue
        if fence:
            closing = re.fullmatch(r" {0,3}(" + re.escape(fence[0]) + r"+)[ \t]*", line.rstrip("\r\n"))
            if closing and len(closing[1]) >= len(fence):
                fence = None
            continue
        opening = FENCE.match(line)
        if opening and not (opening[1][0] == "`" and "`" in opening[2]):
            fence = opening[1]
            continue
        match = HEADING.match(line)
        if match:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", match[2])
            yield index, len(match[1]), title


def plain_title(title):
    title = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", title)
    return re.sub(r"[`*~]", "", title)


def update_toc(text):
    lines = text.splitlines(keepends=True)
    sections = list(headings(lines))
    toc = [section for section in sections if section[1:] == (2, "Table of Contents")]
    if len(toc) != 1:
        raise ValueError("Expected exactly one '## Table of Contents' heading")
    start = toc[0][0]
    end = next((index for index, level, _ in sections if index > start and level <= 2), len(lines))
    newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
    used = set()
    entries = []
    for index, level, title in sections:
        if start < index < end:
            continue
        label = plain_title(title)
        base = re.sub(r"[^\w\- ]", "", label.lower()).replace(" ", "-")
        anchor = base
        suffix = 0
        while anchor in used:
            suffix += 1
            anchor = f"{base}-{suffix}"
        used.add(anchor)
        if level in (2, 3) and index != start:
            label = label.replace("\\", "\\\\").replace("[", r"\[").replace("]", r"\]")
            entries.append(f"{'  ' * (level - 2)}- [{label}](#{anchor})")
    contents = newline + newline.join(entries) + newline * 2
    return "".join(lines[:start + 1]) + contents + "".join(lines[end:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--check", action="store_true", help="Exit with code 1 if the TOC needs updating")
    args = parser.parse_args()
    with args.document.open(encoding="utf-8", newline="") as source:
        original = source.read()
    updated = update_toc(original)
    if updated == original:
        print(f"TOC актуален: {args.document}")
        return 0
    if args.check:
        print(f"TOC требует обновления: {args.document}")
        return 1
    with args.document.open("w", encoding="utf-8", newline="") as output:
        output.write(updated)
    print(f"TOC обновлён: {args.document}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
