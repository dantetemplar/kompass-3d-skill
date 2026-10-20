"""Read-only access to the prepared SDK index; portable with the skill directory."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3


SECTIONS = {
    "ksapi": "API интерфейсов. KsAPI",
    "api7": "API интерфейсов. Версия 7",
    "api5": "API интерфейсов. Версия 5",
}


class Documentation:
    def __init__(self, path: Path):
        self.path = path if path.is_file() else path / "index.sqlite3"
        if not self.path.is_file():
            raise FileNotFoundError(
                f"SDK index not found: {self.path}. "
                "Run uv run --script prepare/prepare_docs.py with the installed KsAPI environment."
            )
        self.connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        try:
            metadata = dict(self.connection.execute("SELECT key, value FROM meta"))
            if metadata.get("schema_version") != "1":
                raise ValueError("Unsupported SDK index schema; rebuild with prepare/prepare_docs.py")
            manifest_path = self.path.parent / "llm/manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("source", {}).get("sha256") != metadata.get("source_sha256"):
                    raise ValueError("Stale SDK index does not match manifest; rebuild with prepare/prepare_docs.py")
        except (sqlite3.Error, ValueError):
            self.connection.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connection.close()

    @staticmethod
    def record(row) -> dict:
        page = dict(row)
        page["title_path"] = json.loads(page["title_path"])
        return page

    def resolve(self, identifier: str, section: str = "ksapi") -> dict:
        # Explicit canonical keys always win over aliases. Short IDs can be ambiguous.
        rows = self.connection.execute("SELECT * FROM pages WHERE key = ?", (identifier,)).fetchall()
        if not rows:
            rows = self.connection.execute(
                "SELECT * FROM pages WHERE source_html = ? OR id = ?", (identifier, identifier)
            ).fetchall()
        if not rows:
            condition = "" if section == "any" else " AND s.section = ?"
            params = (identifier,) if section == "any" else (identifier, SECTIONS[section])
            rows = self.connection.execute(
                "SELECT DISTINCT p.* FROM symbols s JOIN pages p ON p.key = s.page_key "
                "WHERE s.symbol = ?" + condition + " ORDER BY p.key", params
            ).fetchall()
        if not rows:
            raise ValueError(f"Documentation page not found: {identifier}")
        if len(rows) > 1:
            choices = ", ".join(row["key"] for row in rows)
            raise ValueError(f"Ambiguous documentation id {identifier!r}; use canonical key: {choices}")
        return self.record(rows[0])

    def get_pages(self, identifiers: list[str], section: str = "ksapi") -> list[dict]:
        result = []
        for identifier in identifiers:
            try:
                result.append(self.resolve(identifier, section))
            except ValueError as error:
                result.append({"requested": identifier, "error": str(error)})
        return result

    def search(self, query: str, section: str, limit: int, offset: int = 0) -> dict:
        # Treat input as text, never FTS syntax; prefix matching supports partial names.
        tokens = re.findall(r"\w+", query, re.UNICODE)
        if not tokens:
            return {"total": 0, "next_offset": None, "results": []}
        expression = " AND ".join('"' + token.replace('"', '""') + '"*' for token in tokens)
        where = "pages_fts MATCH ?"
        params: list = [expression]
        if section != "any":
            where += " AND p.section = ?"
            params.append(SECTIONS[section])
        base = " FROM pages_fts JOIN pages p ON p.key = pages_fts.key WHERE " + where
        total = self.connection.execute("SELECT count(*)" + base, params).fetchone()[0]
        rows = self.connection.execute(
            "SELECT p.*, bm25(pages_fts, 0, 8, 1, 12) AS rank" + base
            + " ORDER BY rank, p.key LIMIT ? OFFSET ?", [*params, limit, offset]
        ).fetchall()
        results = []
        for row in rows:
            page = self.record(row)
            content = page.pop("content")
            positions = [content.casefold().find(token.casefold()) for token in tokens]
            start = max(0, min((pos for pos in positions if pos >= 0), default=0) - 100)
            page["excerpt"] = content[start:start + 700]
            results.append(page)
        return {
            "total": total, "next_offset": offset + limit if offset + limit < total else None,
            "results": results,
        }

    def toc(self, identifier: str | None, section: str, limit: int, offset: int) -> dict:
        params: list = []
        if identifier is not None:
            page = self.resolve(identifier, section)
            sql = "SELECT p.* FROM toc t JOIN pages p ON p.key = t.child WHERE t.parent = ?"
            params.append(page["key"])
            order = " ORDER BY t.position, p.key"
        else:
            page = None
            sql = (
                "SELECT p.* FROM pages p WHERE p.key NOT IN "
                "(SELECT child FROM toc WHERE parent IS NOT NULL AND child IS NOT NULL)"
            )
            order = " ORDER BY p.key"
        if section != "any":
            sql += " AND p.section = ?"
            params.append(SECTIONS[section])
        total = self.connection.execute("SELECT count(*) FROM (" + sql + ")", params).fetchone()[0]
        rows = self.connection.execute(sql + order + " LIMIT ? OFFSET ?", [*params, limit, offset])
        result = {
            "total": total, "next_offset": offset + limit if offset + limit < total else None,
            "results": [self.summary(self.record(row)) for row in rows],
        }
        if page:
            result["page"] = self.summary(page)
            result["parents"] = [
                self.summary(self.record(row)) for row in self.connection.execute(
                    "SELECT p.* FROM toc t JOIN pages p ON p.key = t.parent "
                    "WHERE t.child = ? ORDER BY p.key", (page["key"],)
                )
            ]
        return result

    @staticmethod
    def summary(page: dict) -> dict:
        return {key: page[key] for key in ("key", "id", "title", "section", "symbol", "source_html")}

    def links(self, identifier: str, section: str, limit: int, offset: int) -> dict:
        page = self.resolve(identifier, section)
        total = self.connection.execute(
            "SELECT count(*) FROM links WHERE source = ?", (page["key"],)
        ).fetchone()[0]
        rows = self.connection.execute(
            "SELECT l.target, l.fragment, l.label, p.title, p.symbol "
            "FROM links l LEFT JOIN pages p ON p.key = l.target WHERE l.source = ? "
            "ORDER BY l.target, l.fragment, l.label LIMIT ? OFFSET ?", (page["key"], limit, offset)
        )
        return {
            "page": self.summary(page), "total": total,
            "next_offset": offset + limit if offset + limit < total else None,
            "results": [dict(row) for row in rows],
        }
