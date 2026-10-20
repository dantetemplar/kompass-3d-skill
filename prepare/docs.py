"""Offline, standard-library-only conversion of installed KOMPAS WebHelp.

Adapted from kompas_3d_api/scripts/convert_kompas_docs.py. JavaScript is
parsed as data, never executed; archive members are read without extraction.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import posixpath
import re
import sqlite3
import tempfile
import zipfile
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from environment import validate_output

SCHEMA_VERSION = "1"
NATIVE_SECTION = "API интерфейсов. KsAPI"
PAGE_COLUMNS = (
    "key", "id", "title", "section", "source_html", "content", "title_path",
    "parent", "prev", "next", "symbol",
)
SQL_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE pages(
    key TEXT PRIMARY KEY, id TEXT, title TEXT, section TEXT, source_html TEXT,
    content TEXT, title_path TEXT, parent TEXT, prev TEXT, next TEXT, symbol TEXT
);
CREATE VIRTUAL TABLE pages_fts USING fts5(key UNINDEXED, title, content, symbol);
CREATE TABLE links(source TEXT, target TEXT, fragment TEXT, label TEXT);
CREATE TABLE toc(parent TEXT, child TEXT, position INTEGER);
CREATE TABLE symbols(symbol TEXT, section TEXT, page_key TEXT);
CREATE INDEX symbols_lookup ON symbols(symbol, section);
CREATE INDEX links_source ON links(source);
CREATE INDEX toc_parent ON toc(parent, position);
"""
SKIP_TAGS = {"script", "style", "noscript", "svg"}
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_SYMBOL = r"[A-Za-z_][A-Za-z0-9_]*"
_JS_ATOM = re.compile(r"(?:true|false|null)(?![\w$])|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


class JSLiteralParser:
    """A deliberately small JS object/array/string literal parser, not JS eval."""

    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def whitespace(self) -> None:
        while self.pos < len(self.text):
            if self.text[self.pos].isspace() or self.text[self.pos] == "\ufeff":
                self.pos += 1
            elif self.text.startswith("//", self.pos):
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end + 1
            elif self.text.startswith("/*", self.pos):
                end = self.text.find("*/", self.pos + 2)
                if end < 0:
                    raise ValueError("Unterminated JavaScript comment")
                self.pos = end + 2
            else:
                break

    def consume(self, expected: str) -> None:
        self.whitespace()
        if not self.text.startswith(expected, self.pos):
            raise ValueError(f"Expected {expected!r} at offset {self.pos}")
        self.pos += len(expected)

    def string(self) -> str:
        delimiter = self.text[self.pos]
        self.pos += 1
        parts: list[str] = []
        escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == delimiter:
                # JavaScript uses UTF-16; combine escaped surrogate pairs safely.
                return "".join(parts).encode("utf-16-le", "surrogatepass").decode("utf-16-le")
            if char in "\r\n":
                raise ValueError("Unescaped newline in JavaScript string")
            if char != "\\":
                parts.append(char)
                continue
            if self.pos == len(self.text):
                break
            char = self.text[self.pos]
            self.pos += 1
            if char in "ux":
                size = 4 if char == "u" else 2
                digits = self.text[self.pos:self.pos + size]
                if len(digits) != size or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                    raise ValueError("Malformed JavaScript Unicode/hex escape")
                parts.append(chr(int(digits, 16)))
                self.pos += size
            elif char in "\r\n":
                if char == "\r" and self.text[self.pos:self.pos + 1] == "\n":
                    self.pos += 1
            else:
                parts.append(escapes.get(char, char))
        raise ValueError("Unterminated JavaScript string")

    def value(self):
        self.whitespace()
        if self.pos == len(self.text):
            raise ValueError("Missing JavaScript literal")
        char = self.text[self.pos]
        if char in "\"'":
            return self.string()
        if char in "[{":
            self.pos += 1
            result = [] if char == "[" else {}
            end = "]" if char == "[" else "}"
            self.whitespace()
            while self.text[self.pos:self.pos + 1] != end:
                if char == "[":
                    result.append(self.value())
                else:
                    self.whitespace()
                    if self.text[self.pos:self.pos + 1] in ("\"", "'"):
                        key = self.string()
                    else:
                        match = _IDENTIFIER.match(self.text, self.pos)
                        if not match:
                            raise ValueError(f"Invalid object key at {self.pos}")
                        key = match.group()
                        self.pos = match.end()
                    self.consume(":")
                    if key in result:
                        raise ValueError(f"Duplicate object key: {key}")
                    result[key] = self.value()
                self.whitespace()
                if self.text[self.pos:self.pos + 1] == end:
                    break
                self.consume(",")
                self.whitespace()
            self.consume(end)
            return result
        match = _JS_ATOM.match(self.text, self.pos)
        if not match:
            raise ValueError(f"Executable or unsupported JavaScript at {self.pos}")
        token = match.group()
        self.pos += len(token)
        return json.loads(token)


def parse_js_call(text: str, function: str) -> dict:
    """Read exactly one known Help+Manual call containing a literal object."""
    parser = JSLiteralParser(text)
    parser.consume(function)
    parser.consume("(")
    result = parser.value()
    parser.consume(")")
    parser.whitespace()
    if parser.text[parser.pos:parser.pos + 1] == ";":
        parser.pos += 1
    parser.whitespace()
    if parser.pos != len(text) or not isinstance(result, dict):
        raise ValueError("Unexpected JavaScript after metadata literal")
    return result


def clean_ws(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def link_token(index: int) -> str:
    return f"__kompas_sdk_href_{index}__"


class HTMLToMarkdown(HTMLParser):
    """Keep readable text, code, anchors and link labels, dropping active HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[dict] = []
        self.anchors: list[str] = []
        self.skip_stack: list[str] = []
        self.href_stack: list[tuple[int, int] | None] = []
        self.pre_depth = 0
        self.pre_parts: list[str] | None = None
        self.blocks: list[str] = []
        self.tables: list[dict] = []

    def protected_block(self, content: str) -> str:
        token = f"__kompas_sdk_block_{len(self.blocks)}__"
        self.blocks.append(content)
        return token

    def restore_blocks(self, content: str) -> str:
        # Nested tables can contain earlier protected blocks.
        for index in reversed(range(len(self.blocks))):
            content = content.replace(f"__kompas_sdk_block_{index}__", self.blocks[index])
        return content

    def finish_cell(self) -> None:
        table = self.tables[-1]
        if table["cell"] is None:
            return
        cell = table["cell"]
        text = self.restore_blocks(clean_ws("".join(self.parts)))
        cell["text"] = re.sub(r"\n+", "<br>", text.replace("|", "\\|"))
        table["rows"][-1].append(cell)
        table["cell"] = None
        self.parts = table["parts"]

    def finish_table(self) -> None:
        self.finish_cell()
        table = self.tables.pop()
        self.parts = table["parts"]
        grid: list[list[str]] = []
        occupied: set[tuple[int, int]] = set()
        header = False
        for row_index, cells in enumerate(table["rows"]):
            while len(grid) <= row_index:
                grid.append([])
            column = 0
            for cell in cells:
                while (row_index, column) in occupied:
                    column += 1
                for delta_row in range(cell["rowspan"]):
                    target_row = row_index + delta_row
                    while len(grid) <= target_row:
                        grid.append([])
                    for delta_column in range(cell["colspan"]):
                        target_column = column + delta_column
                        while len(grid[target_row]) <= target_column:
                            grid[target_row].append("")
                        occupied.add((target_row, target_column))
                grid[row_index][column] = cell["text"]
                header = header or (row_index == 0 and cell["header"])
                column += cell["colspan"]
        width = max((len(row) for row in grid), default=0)
        if not width:
            return
        for row in grid:
            row.extend([""] * (width - len(row)))
        if not header:
            grid.insert(0, [f"Column {index + 1}" for index in range(width)])
        lines = ["| " + " | ".join(grid[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
        lines.extend("| " + " | ".join(row) + " |" for row in grid[1:])
        self.parts.append("\n" + self.protected_block("\n".join(lines)) + "\n")

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if self.skip_stack:
            if tag in SKIP_TAGS:
                self.skip_stack.append(tag)
            return
        if tag in SKIP_TAGS:
            self.skip_stack.append(tag)
            return
        anchor = attr.get("id") or (attr.get("name") if tag == "a" else None)
        if anchor and anchor not in self.anchors:
            self.anchors.append(anchor)
        if self.pre_parts is not None:
            if tag == "br":
                self.pre_parts.append("\n")
            return
        if tag == "pre":
            self.pre_depth = 1
            self.pre_parts = []
            return
        if tag == "table":
            self.tables.append({"parts": self.parts, "rows": [], "cell": None})
            return
        if self.tables and tag == "tr":
            self.finish_cell()
            self.tables[-1]["rows"].append([])
            return
        if self.tables and tag in {"td", "th"}:
            self.finish_cell()
            table = self.tables[-1]
            if not table["rows"]:
                table["rows"].append([])
            spans = {}
            for name in ("colspan", "rowspan"):
                raw = attr.get(name) or "1"
                spans[name] = max(1, min(1000, int(raw))) if raw.isdecimal() else 1
            table["cell"] = {"header": tag == "th", **spans}
            self.parts = []
            return
        if self.tables and self.tables[-1]["cell"] is None:
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if re.fullmatch(r"h[1-6]", tag):
            self.parts.append("#" * int(tag[1]) + " ")
        if tag == "li":
            self.parts.append("- ")
        if tag == "code" and not self.pre_depth:
            self.parts.append("`")
        if tag == "a":
            href = attr.get("href", "")
            scheme = urlsplit(href).scheme.lower()
            if href and scheme not in {"javascript", "data", "vbscript"}:
                index = len(self.links)
                self.links.append({"href": href, "label": ""})
                self.parts.append("[")
                self.href_stack.append((index, len(self.parts)))
            else:
                self.href_stack.append(None)
        if tag == "img" and attr.get("alt"):
            self.parts.append(f"[image: {attr['alt']}]")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {"br", "hr", "img", "input", "meta", "link"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.skip_stack:
            if tag == self.skip_stack[-1]:
                self.skip_stack.pop()
            return
        if self.pre_parts is not None:
            if tag == "pre":
                content = "".join(self.pre_parts).replace("\r\n", "\n").replace("\r", "\n")
                longest = max((len(match.group()) for match in re.finditer(r"`+", content)), default=0)
                fence = "`" * max(3, longest + 1)
                block = fence + "\n" + content + ("" if content.endswith("\n") else "\n") + fence
                if self.tables:
                    # A fenced block cannot span Markdown table rows; safe HTML
                    # preserves whitespace inside the same logical table cell.
                    encoded = html.escape(content).replace("|", "&#124;").replace("\n", "&#10;")
                    block = "<pre>" + encoded + "</pre>"
                self.pre_parts = None
                self.pre_depth = 0
                self.parts.append("\n" + self.protected_block(block) + "\n")
            return
        if self.tables and tag in {"td", "th", "tr"}:
            self.finish_cell()
            return
        if self.tables and tag == "table":
            self.finish_table()
            return
        if self.tables and self.tables[-1]["cell"] is None:
            return
        if tag == "a" and self.href_stack:
            active = self.href_stack.pop()
            if active:
                index, start = active
                self.links[index]["label"] = clean_ws("".join(self.parts[start:]))
                self.parts.append(f"](<{link_token(index)}>)")
        if tag == "code" and not self.pre_depth:
            self.parts.append("`")
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_stack:
            return
        if self.pre_parts is not None:
            self.pre_parts.append(data)
        elif not self.tables or self.tables[-1]["cell"] is not None:
            self.parts.append(data)

    def markdown(self) -> str:
        return self.restore_blocks(clean_ws("".join(self.parts)))


def html_to_markdown(fragment: str) -> str:
    parser = HTMLToMarkdown()
    parser.feed(fragment)
    parser.close()
    content = parser.markdown()
    return replace_link_tokens(content, [link["href"] for link in parser.links])


def safe_name(value: str, limit: int = 70) -> str:
    value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    # Bound UTF-8 byte length too (common Linux filename limit is 255 bytes).
    return value[:limit].encode("utf-8")[:160].decode("utf-8", "ignore").strip("._") or "unnamed"


def digest_name(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def canonical_key(source_html: str) -> str:
    """Full archive-relative HTML path, not a collision-prone basename/stem."""
    return "webhelp:" + source_html


def source_html_for_js(source_js: str) -> str:
    parts = list(PurePosixPath(source_js).parts)
    parts.remove("jstopics")
    return str(PurePosixPath(*parts).with_suffix(".html"))


def infer_symbol(title: str, title_path: list[str]) -> str | None:
    """Infer Owner.Member only from an explicit owner and member breadcrumb."""
    owner = None
    owner_pattern = rf"(?:Интерфейс|Структура|Перечисление|Класс)\s+({_SYMBOL})(?![A-Za-z0-9_])"
    for part in title_path:
        match = re.match(owner_pattern, part, re.I)
        if match:
            owner = match.group(1)
    if owner is None:
        return None
    if re.match(owner_pattern, title, re.I):
        return owner
    # Group headings (methods/properties/examples) are not member definitions.
    member_group = any(re.match(rf"{re.escape(owner)}\s*[-–—]\s*(?:методы|свойства|события)\b", part, re.I) for part in title_path[:-1])
    member = re.match(rf"({_SYMBOL})(?:\s*\([^)]*\))?\s*[-–—]\s+", title)
    if member_group and member and member.group(1) != owner:
        return f"{owner}.{member.group(1)}"
    return None


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _read_member(archive: zipfile.ZipFile, name: str, sources: list[dict]) -> str:
    raw = archive.read(name)
    sources.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)})
    return raw.decode("utf-8-sig")


def read_archive(zip_path: Path) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
    """Return pages, raw TOC roots, raw keyword roots, source hashes and errors."""
    pages, toc, keywords, sources, errors = [], [], [], [], []
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(info.filename for info in archive.infolist() if not info.is_dir())
        if len(set(names)) != len(names):
            raise ValueError("Duplicate ZIP member paths")
        for name in names:
            parts = PurePosixPath(name).parts
            if "jstopics" not in parts or not name.endswith(".js"):
                continue
            if name.startswith("/") or ".." in parts or "\\" in name:
                raise ValueError(f"Unsafe topic path: {name}")
            try:
                data = parse_js_call(_read_member(archive, name, sources), "hmLoadTopic")
                source_html = source_html_for_js(name)
                title = clean_ws(html.unescape(data.get("hmTitle", ""))) or PurePosixPath(name).stem
                title_path = [clean_ws(html.unescape(part)) for part in data.get("hmTitlePath", "").split(">") if clean_ws(part)] or [title]
                parser = HTMLToMarkdown()
                parser.feed(data.get("hmBody", ""))
                parser.close()
                pages.append({
                    "key": canonical_key(source_html), "id": PurePosixPath(source_html).stem,
                    "title": title, "section": title_path[0], "source_html": source_html,
                    "source_js": name, "title_path": title_path,
                    "parent": data.get("hmParentLink") or None,
                    "prev": data.get("hmPrevLink") or None, "next": data.get("hmNextLink") or None,
                    "symbol": infer_symbol(title, title_path),
                    "content": parser.markdown() or clean_ws(html.unescape(data.get("hmDescription", ""))),
                    "links": parser.links, "anchors": parser.anchors,
                })
            except (ValueError, UnicodeError, TypeError, AttributeError) as exc:
                errors.append({"source": name, "error": str(exc)})
        for suffix, function, field, target in (
            ("js/hmcontent.js", "hmLoadTOC", "items", toc),
            ("js/hmkwindex.js", "hmLoadIndex", "keywords", keywords),
        ):
            matching = [name for name in names if name == suffix or name.endswith("/" + suffix)]
            if not matching:
                errors.append({"source": suffix, "error": "Metadata member missing"})
            for name in matching:
                try:
                    data = parse_js_call(_read_member(archive, name, sources), function)
                    root = name[:-len(suffix)]
                    target.extend({"archive_root": root, "item": item} for item in data[field])
                except (ValueError, UnicodeError, KeyError, TypeError) as exc:
                    errors.append({"source": name, "error": str(exc)})
    keys = [page["key"] for page in pages]
    if len(set(keys)) != len(keys):
        raise ValueError("Multiple topics map to the same canonical HTML key")
    if not pages:
        raise ValueError("No valid WebHelp topics found")
    return sorted(pages, key=lambda page: page["key"]), toc, keywords, sources, errors


class LinkResolver:
    def __init__(self, pages: list[dict]):
        self.pages = {page["key"]: page for page in pages}
        self.paths = {page["source_html"]: page["key"] for page in pages}
        self.casefold_paths: dict[str, list[str]] = defaultdict(list)
        for path, key in self.paths.items():
            self.casefold_paths[path.casefold()].append(key)
        self.unresolved: list[dict] = []

    def resolve(self, href: str, source_html: str, kind: str = "link") -> tuple[str | None, str]:
        href = html.unescape(href).strip()
        parsed = urlsplit(href)
        fragment = unquote(parsed.fragment)
        if parsed.scheme or parsed.netloc:
            return None, fragment
        raw_path = unquote(parsed.path).replace("\\", "/")
        path = posixpath.normpath(posixpath.join(posixpath.dirname(source_html), raw_path)) if raw_path else source_html
        key = self.paths.get(path)
        if key is None:
            candidates = self.casefold_paths.get(path.casefold(), [])
            if len(candidates) == 1:
                key = candidates[0]
        if key is None:
            self.unresolved.append({"source": canonical_key(source_html), "target": href, "kind": kind})
        return key, fragment


def normalize_records(pages: list[dict], toc_roots: list[dict], keyword_roots: list[dict]) -> tuple[list[dict], list[dict], LinkResolver]:
    resolver = LinkResolver(pages)
    for page in pages:
        for field in ("parent", "prev", "next"):
            raw = page[field]
            if raw:
                page[field], _ = resolver.resolve(raw, page["source_html"], field)
        for link in page["links"]:
            link["target"], link["fragment"] = resolver.resolve(link["href"], page["source_html"])
    toc = []

    def visit_toc(item: dict, parent: str | None, root: str, position: int) -> None:
        target, _ = resolver.resolve(item.get("hf", ""), root + "index.html", "toc")
        if target:
            toc.append({"parent": parent, "child": target, "position": position})
        for index, child in enumerate(item.get("items", [])):
            visit_toc(child, target or parent, root, index)

    root_positions: Counter = Counter()
    for wrapped in toc_roots:
        root = wrapped["archive_root"]
        visit_toc(wrapped["item"], None, root, root_positions[root])
        root_positions[root] += 1
    keywords = []

    def visit_keyword(item: dict, path: list[str], root: str) -> None:
        keyword = item.get("kw", "")
        hrefs = item.get("hrefs", [])
        targets = []
        for href in hrefs:
            key, fragment = resolver.resolve(href, root + "index.html", "keyword")
            targets.append({"key": key, "fragment": fragment, "href": href})
        keywords.append({"keyword": keyword, "path": path + [keyword], "hrefs": hrefs,
                         "captions": item.get("captions", []), "targets": targets})
        for child in item.get("subkw", []):
            visit_keyword(child, path + [keyword], root)

    for wrapped in keyword_roots:
        visit_keyword(wrapped["item"], [], wrapped["archive_root"])
    return toc, keywords, resolver


def replace_link_tokens(content: str, targets: list[str]) -> str:
    return re.sub(r"__kompas_sdk_href_([0-9]+)__", lambda match: targets[int(match.group(1))], content)


def page_record(page: dict) -> dict:
    record = dict(page)
    record["content"] = replace_link_tokens(page["content"], [
        (link["target"] + ("#" + quote(link["fragment"]) if link["fragment"] else "")) if link["target"] else link["href"]
        for link in page["links"]
    ])
    return record


def write_jsonl(path: Path, records) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_database(path: Path, pages: list[dict], toc: list[dict], source_sha256: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(SQL_SCHEMA)
        connection.executemany("INSERT INTO meta VALUES (?,?)", [("schema_version", SCHEMA_VERSION), ("source_sha256", source_sha256)])
        for page in pages:
            record = page_record(page)
            record["title_path"] = json.dumps(record["title_path"], ensure_ascii=False, separators=(",", ":"))
            connection.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?,?,?,?)", [record[column] for column in PAGE_COLUMNS])
            connection.execute("INSERT INTO pages_fts(key,title,content,symbol) VALUES (?,?,?,?)", [record[column] for column in ("key", "title", "content", "symbol")])
            connection.executemany("INSERT INTO links VALUES (?,?,?,?)", [
                (page["key"], link["target"], link["fragment"], link["label"]) for link in page["links"] if link["target"]
            ])
            if page["symbol"]:
                connection.execute("INSERT INTO symbols VALUES (?,?,?)", (page["symbol"], page["section"], page["key"]))
        connection.executemany("INSERT INTO toc VALUES (?,?,?)", [(edge["parent"], edge["child"], edge["position"]) for edge in toc])
        connection.execute("INSERT INTO pages_fts(pages_fts) VALUES ('optimize')")
    # Explicitly close: sqlite's context manager only commits/rolls back.
    connection.close()


def _page_anchor(key: str) -> str:
    return "page-" + digest_name(key)


def _fragment_anchor(key: str, fragment: str) -> str:
    return _page_anchor(key) + "-" + digest_name(fragment)


def assign_markdown_locations(pages: list[dict]) -> None:
    """Store output-root-relative paths and fragment IDs before serializing JSONL."""
    for page in pages:
        section = page["section"]
        owner = page["symbol"].split(".")[0] if page["symbol"] else "_other"
        directory = f"{safe_name(section)}__{digest_name(section)}"
        filename = f"{safe_name(owner)}__{digest_name(owner)}.md"
        page["markdown_path"] = str(PurePosixPath("llm", "api_objects", directory, filename))
        page["markdown_fragment"] = _page_anchor(page["key"])


def write_markdown(llm: Path, pages: list[dict], resolver: LinkResolver) -> tuple[int, list[str]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    locations = {}
    files = []
    for page in pages:
        owner = page["symbol"].split(".")[0] if page["symbol"] else "_other"
        groups[(page["section"], owner)].append(page)
        locations[page["key"]] = PurePosixPath(page["markdown_path"]).relative_to("llm")
    section_links: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for (section, owner), items in sorted(groups.items()):
        location = locations[items[0]["key"]]
        path = llm / str(location)
        path.parent.mkdir(parents=True, exist_ok=True)
        section_links[section].append((owner, str(location), len(items)))
        lines = [f"# {owner}", "", f"Section: {section}", ""]
        for page in sorted(items, key=lambda item: (len(item["title_path"]), item["title_path"], item["key"])):
            lines += [f'<a id="{page["markdown_fragment"]}"></a>', "", f"## {page['title']}", "",
                      f"Source: `{page['key']}`", "", f"Path: {' > '.join(page['title_path'])}", ""]
            for anchor in page["anchors"]:
                lines += [f'<a id="{_fragment_anchor(page["key"], anchor)}"></a>']
            targets = []
            for link in page["links"]:
                if link["target"]:
                    target_page = resolver.pages[link["target"]]
                    anchor = _page_anchor(link["target"])
                    if link["fragment"] in target_page["anchors"]:
                        anchor = _fragment_anchor(link["target"], link["fragment"])
                    relative = posixpath.relpath(str(locations[link["target"]]), str(location.parent))
                    targets.append(quote(relative, safe="/._-") + "#" + anchor)
                elif urlsplit(link["href"]).scheme in {"http", "https", "mailto"}:
                    targets.append(link["href"].replace(">", "%3E"))
                else:
                    # Keep unresolved raw links in JSON diagnostics, not broken local Markdown.
                    targets.append("#" + _page_anchor(page["key"]))
            lines += [replace_link_tokens(page["content"], targets), ""]
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
        files.append("llm/" + str(location))
    lines = ["# KOMPAS SDK documentation", "", f"Pages: {len(pages)}", "",
             "- [Pages JSONL](pages.jsonl)", "- [Keywords JSONL](keywords.jsonl)", "- [Manifest](manifest.json)",
             "- [SQLite FTS5 index](../index.sqlite3)", ""]
    for section, entries in sorted(section_links.items()):
        lines += [f"## {section}", ""]
        for owner, location, count in entries:
            lines.append(f"- [{owner}](<{quote(location, safe='/._-')}>): {count} pages")
        lines.append("")
    (llm / "index.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    files.append("llm/index.md")
    return len(groups), files


def _safe_generated_path(out: Path, relative: str) -> Path:
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or ".." in parts or "\\" in relative:
        raise ValueError(f"Unsafe output path: {relative}")
    allowed = relative in {"index.sqlite3", "llm/pages.jsonl", "llm/keywords.jsonl", "llm/manifest.json", "llm/index.md"}
    allowed = allowed or (len(parts) == 4 and parts[:2] == ("llm", "api_objects") and parts[-1].endswith(".md") and "__" in parts[2] and "__" in parts[3])
    if not allowed:
        raise ValueError(f"Not a generated artifact: {relative}")
    path = out.joinpath(*parts)
    current = out
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Refusing output symlink: {current}")
    return path


def publish_artifacts(stage: Path, out: Path, files: list[str]) -> None:
    """Atomic per-artifact replacement; never remove an arbitrary output tree.

    The manifest is published last as the generation commit marker. Only stale
    Markdown paths named by our previous matching manifest may be unlinked.
    """
    old_files = []
    manifest_path = _safe_generated_path(out, "llm/manifest.json")
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("generator") == "kompas-sdk-docs":
            old_files = old.get("generated_files", [])
    paths = {name: _safe_generated_path(out, name) for name in files}
    for name in sorted(set(old_files) - set(files)):
        if not name.startswith("llm/api_objects/"):
            continue
        stale = _safe_generated_path(out, name)
        if stale.is_file():
            stale.unlink()
    for name in sorted(files, key=lambda item: (item == "llm/manifest.json", item)):
        destination = paths[name]
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage / name, destination)


def prepare_docs(zip_path: Path, out: Path, install: Path = Path("/opt/ascon/kompas3d-v25")) -> dict:
    """Generate the local docs cache, returning the same summary as the CLI."""
    validate_output(out, install)
    zip_path = zip_path.resolve(strict=True)
    out = out.absolute()
    source_sha256 = sha256_file(zip_path)
    pages, raw_toc, raw_keywords, sources, errors = read_archive(zip_path)
    toc, keywords, resolver = normalize_records(pages, raw_toc, raw_keywords)
    assign_markdown_locations(pages)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".kompas-docs-", dir=out) as temporary:
        stage = Path(temporary)
        llm = stage / "llm"
        llm.mkdir()
        write_jsonl(llm / "pages.jsonl", (page_record(page) for page in pages))
        write_jsonl(llm / "keywords.jsonl", keywords)
        write_database(stage / "index.sqlite3", pages, toc, source_sha256)
        group_count, files = write_markdown(llm, pages, resolver)
        files += ["index.sqlite3", "llm/pages.jsonl", "llm/keywords.jsonl", "llm/manifest.json"]
        counts = {
            "pages": len(pages), "sections": len({page["section"] for page in pages}),
            "api_objects": group_count, "keywords": len(keywords), "toc": len(toc),
            "links": sum(bool(link["target"]) for page in pages for link in page["links"]),
            "symbols": sum(page["symbol"] is not None for page in pages),
            "errors": len(errors), "unresolved_links": len(resolver.unresolved),
        }
        manifest = {
            "generator": "kompas-sdk-docs", "schema_version": SCHEMA_VERSION,
            "source": {"path": str(zip_path), "sha256": source_sha256, "size": zip_path.stat().st_size,
                       "namespace": "webhelp", "members": sorted(sources, key=lambda item: item["path"])},
            "package": {"product": "KOMPAS-3D", "install": str(install.absolute()),
                        "installation_name": install.name, "help_archive": zip_path.name},
            "schemas": {
                "pages_jsonl": {**{column: "string|null" if column in {"parent", "prev", "next", "symbol"} else "string" for column in PAGE_COLUMNS},
                                "title_path": "array<string>", "source_js": "string", "anchors": "array<string>",
                                "markdown_path": "string: output-root-relative POSIX path",
                                "markdown_fragment": "string: exact page anchor ID without #",
                                "links": "array<{href:string,label:string,target:canonical-key|null,fragment:string}>"},
                "keywords_jsonl": {"keyword": "string", "path": "array<string>", "hrefs": "array<string>",
                                   "captions": "array<string>", "targets": "array<{key:canonical-key|null,fragment:string,href:string}>"},
                "sqlite": SQL_SCHEMA.strip(), "canonical_key": "webhelp:<full archive-relative HTML path>",
                "title_path_sqlite": "JSON array of strings", "toc_root_parent": None,
                "unresolved_links": "array<{source:canonical-key,target:raw-href,kind:string}>",
            },
            "counts": counts, "sections": dict(sorted(Counter(page["section"] for page in pages).items())),
            "errors": errors, "unresolved_links": resolver.unresolved,
            "generated_files": sorted(files),
        }
        (llm / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        publish_artifacts(stage, out, files)
    return {**counts, "schema_version": SCHEMA_VERSION, "source_sha256": source_sha256, "out": str(out)}
