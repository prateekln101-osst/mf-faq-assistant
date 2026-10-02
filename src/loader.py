"""Fetch and clean documents listed in data/sources.csv.

Each row is fetched once (one retry on transient failure). Raw bytes are saved
under data/raw/. Cleaned sections are saved under data/cleaned/ and returned as
{"heading", "text"} plus fetched_date. Failures are recorded and the run continues.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
SOURCES_CSV = ROOT / "data" / "sources.csv"
RAW_DIR = ROOT / "data" / "raw"
CLEANED_DIR = ROOT / "data" / "cleaned"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TIMEOUT_SECONDS = 30
MIN_USEFUL_CHARS = 500
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
REMOVE_TAGS = {"script", "style", "noscript", "nav", "footer", "iframe", "svg", "form"}
CHROME_CLASS = re.compile(r"(nav|footer)", re.IGNORECASE)
KEEP_CHROME_CLASS = re.compile(
    r"headerCell|popupHeader|accordionHeader|tableRowHeader|headerRow|schemeName"
)

FALLBACK_HINT = (
    "Page looks JavaScript-rendered or nearly empty. "
    "Fallback: render it with a headless browser, save the rendered HTML to "
    "data/raw/<id>.html and re-run, or replace the URL with an official AMC/AMFI/SEBI document."
)


@dataclass
class Source:
    id: str
    url: str
    publisher: str
    publisher_type: str
    scheme_name: str
    scheme_category: str
    doc_type: str


@dataclass
class LoadResult:
    source: Source
    status: str
    fetched_date: str
    sections: list[dict] = field(default_factory=list)
    char_count: int = 0
    heading_count: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    raw_path: str = ""


def load_registry(path: Path | None = None) -> list[Source]:
    csv_path = path or SOURCES_CSV
    sources: list[Source] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {
            "id",
            "url",
            "publisher",
            "publisher_type",
            "scheme_name",
            "scheme_category",
            "doc_type",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{csv_path} is missing columns: {', '.join(sorted(missing))}")
        for row in reader:
            url = (row.get("url") or "").strip()
            source_id = (row.get("id") or "").strip()
            if not source_id or not url:
                continue
            sources.append(
                Source(
                    id=source_id,
                    url=url,
                    publisher=(row.get("publisher") or "").strip(),
                    publisher_type=(row.get("publisher_type") or "").strip(),
                    scheme_name=(row.get("scheme_name") or "").strip(),
                    scheme_category=(row.get("scheme_category") or "").strip(),
                    doc_type=(row.get("doc_type") or "").strip(),
                )
            )
    return sources


def fetch(url: str) -> tuple[bytes, str, str]:
    """GET url with one retry. Returns (body, content_type, error)."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }
    last_error = "request failed"
    for _attempt in range(2):
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS, allow_redirects=True)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if response.status_code >= 500 or response.status_code == 429:
            last_error = f"HTTP {response.status_code}"
            continue
        if response.status_code >= 400:
            return b"", response.headers.get("Content-Type", ""), f"HTTP {response.status_code}"
        return response.content, response.headers.get("Content-Type", ""), ""
    return b"", "", last_error


def _extension(content: bytes, content_type: str, url: str) -> str:
    lowered = content_type.lower()
    if content.startswith(b"%PDF") or "pdf" in lowered or url.lower().split("?")[0].endswith(".pdf"):
        return "pdf"
    return "html"


def _normalize_ws(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _flatten_table(table: Tag) -> list[str]:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [_normalize_ws(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    if not rows:
        return []
    if all(len(row) == 2 for row in rows):
        return [f"{label}: {value}" for label, value in rows]
    if len(rows) >= 2:
        headers = rows[0]
        lines: list[str] = []
        for row in rows[1:]:
            for index, cell in enumerate(row):
                label = headers[index] if index < len(headers) else f"column {index + 1}"
                lines.append(f"{label}: {cell}")
        return lines
    return [" | ".join(rows[0])]


def _flatten_definition_list(dl: Tag) -> list[str]:
    lines: list[str] = []
    for dt in dl.find_all("dt"):
        label = _normalize_ws(dt.get_text(" ", strip=True))
        dd = dt.find_next_sibling("dd")
        value = _normalize_ws(dd.get_text(" ", strip=True)) if dd else ""
        if label and value:
            lines.append(f"{label}: {value}")
        elif label:
            lines.append(label)
    return lines


def _has_block_child(element: Tag) -> bool:
    return element.find(["p", "li", "table", "dl", "h1", "h2", "h3", "h4", "h5", "h6", "div", "section"]) is not None


def _is_chrome(tag: Tag) -> bool:
    if not tag.attrs:
        return False
    classes = " ".join(tag.get("class") or [])
    if not classes or KEEP_CHROME_CLASS.search(classes):
        return False
    return CHROME_CLASS.search(classes) is not None


def _html_to_text(fragment: str) -> str:
    return _normalize_ws(BeautifulSoup(fragment, "lxml").get_text(" ", strip=True))


def _faq_sections(soup: BeautifulSoup) -> list[dict]:
    sections: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if "FAQPage" not in raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        entities = data.get("mainEntity") if isinstance(data, dict) else None
        if not isinstance(entities, list):
            continue
        for item in entities:
            if not isinstance(item, dict):
                continue
            question = _normalize_ws(str(item.get("name") or ""))
            answer_html = str((item.get("acceptedAnswer") or {}).get("text") or "")
            answer = _html_to_text(answer_html)
            if question and answer:
                sections.append({"heading": question, "text": answer})
    return sections


def _label_value_line(element: Tag) -> str:
    """Turn a two-child stat block into one 'label: value' line."""
    children = []
    for child in element.find_all(recursive=False):
        if not isinstance(child, Tag) or child.name in HEADING_TAGS | {"table", "dl"}:
            continue
        text = _normalize_ws(child.get_text(" ", strip=True))
        if text:
            children.append(text)
    if len(children) != 2:
        return ""
    label, value = children
    if len(label) > 60 or len(value) > 180:
        return ""
    if len(label.split()) > 8 or len(value.split()) > 16:
        return ""
    return f"{label}: {value}"


def clean_html(html: str) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    soup = BeautifulSoup(html, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = _normalize_ws(soup.title.string)

    faq_sections = _faq_sections(soup)
    raw_text_len = len(soup.get_text(" ", strip=True))
    removable = [
        tag
        for tag in soup.find_all(True)
        if isinstance(tag, Tag) and tag.attrs is not None and (tag.name in REMOVE_TAGS or _is_chrome(tag))
    ]
    for tag in removable:
        if tag.parent is not None:
            tag.decompose()

    root = soup.find("main") or soup.find("article") or soup.body or soup
    sections: list[dict] = []
    current_heading = title or "Document"
    current_parts: list[str] = []
    consumed: set[int] = set()

    def flush() -> None:
        nonlocal current_parts
        text = _normalize_ws("\n".join(current_parts))
        current_parts = []
        if text:
            sections.append({"heading": current_heading or "Document", "text": text})

    for element in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "dl", "div"]):
        if not isinstance(element, Tag) or id(element) in consumed:
            continue
        if element.find_parent(["table", "dl"]):
            continue
        if element.name in HEADING_TAGS:
            flush()
            heading = _normalize_ws(element.get_text(" ", strip=True))
            if heading:
                current_heading = heading
            continue
        if element.name == "table":
            current_parts.extend(_flatten_table(element))
            continue
        if element.name == "dl":
            current_parts.extend(_flatten_definition_list(element))
            continue
        if element.name == "li" and element.find_parent("li"):
            continue
        if element.name == "div":
            paired = _label_value_line(element)
            if paired:
                current_parts.append(paired)
                for child in element.find_all(True):
                    consumed.add(id(child))
                continue
            if _has_block_child(element):
                direct = _normalize_ws(
                    " ".join(
                        piece.strip()
                        for piece in element.find_all(string=True, recursive=False)
                        if piece and piece.strip()
                    )
                )
                if direct:
                    current_parts.append(direct)
                continue
        text = _normalize_ws(element.get_text(" ", strip=True))
        if text:
            current_parts.append(text)
    flush()
    sections.extend(faq_sections)

    if not sections and title:
        sections.append({"heading": title, "text": ""})

    cleaned_len = sum(len(section["text"]) for section in sections)
    if raw_text_len > 2000 and cleaned_len < MIN_USEFUL_CHARS:
        warnings.append(
            "Fetched HTML is large but cleaned text is short, which usually means the facts are rendered by JavaScript."
        )
    elif cleaned_len < MIN_USEFUL_CHARS:
        warnings.append("Cleaned text is nearly empty.")
    if warnings:
        warnings.append(FALLBACK_HINT)
    return sections, warnings


def clean_pdf(path: Path) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    reader = PdfReader(str(path))
    sections: list[dict] = []
    for index, page in enumerate(reader.pages, start=1):
        text = _normalize_ws(page.extract_text() or "")
        if text:
            sections.append({"heading": f"Page {index}", "text": text})
    cleaned_len = sum(len(section["text"]) for section in sections)
    if cleaned_len < MIN_USEFUL_CHARS:
        warnings.append("Extracted PDF text is nearly empty.")
        warnings.append(FALLBACK_HINT)
    return sections, warnings


def _write_cleaned(result: LoadResult) -> None:
    CLEANED_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": result.source.id,
        "url": result.source.url,
        "publisher": result.source.publisher,
        "publisher_type": result.source.publisher_type,
        "scheme_name": result.source.scheme_name,
        "scheme_category": result.source.scheme_category,
        "doc_type": result.source.doc_type,
        "fetched_date": result.fetched_date,
        "status": result.status,
        "warnings": result.warnings,
        "error": result.error,
        "sections": result.sections,
    }
    json_path = CLEANED_DIR / f"{result.source.id}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"id: {result.source.id}",
        f"url: {result.source.url}",
        f"fetched_date: {result.fetched_date}",
        f"status: {result.status}",
    ]
    if result.error:
        lines.append(f"error: {result.error}")
    for warning in result.warnings:
        lines.append(f"warning: {warning}")
    lines.append("")
    for section in result.sections:
        lines.append(f"## {section['heading']}")
        lines.append("")
        lines.append(section["text"])
        lines.append("")
    (CLEANED_DIR / f"{result.source.id}.txt").write_text("\n".join(lines), encoding="utf-8")


def load_source(source: Source, fetched_on: date | None = None) -> LoadResult:
    fetched_date = (fetched_on or date.today()).isoformat()
    result = LoadResult(source=source, status="failed", fetched_date=fetched_date)
    body, content_type, error = fetch(source.url)
    saved_html = RAW_DIR / f"{source.id}.html"
    if (error or not body) and saved_html.exists() and saved_html.stat().st_size > 2000:
        body = saved_html.read_bytes()
        content_type = "text/html"
        result.warnings.append(f"used saved HTML because the live fetch failed ({error})")
        error = ""
    if error or not body:
        result.error = error or "empty response"
        result.warnings.append(result.error)
        _write_cleaned(result)
        return result

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ext = _extension(body, content_type, source.url)
    raw_path = RAW_DIR / f"{source.id}.{ext}"
    raw_path.write_bytes(body)
    result.raw_path = str(raw_path)

    try:
        if ext == "pdf":
            sections, warnings = clean_pdf(raw_path)
        else:
            html = body.decode("utf-8", errors="replace")
            sections, warnings = clean_html(html)
    except Exception as exc:  # keep the run going; raw snapshot is already saved
        result.error = f"parse error: {exc}"
        result.warnings.append(result.error)
        _write_cleaned(result)
        return result

    result.sections = sections
    result.warnings.extend(warnings)
    result.char_count = sum(len(section["text"]) for section in sections)
    result.heading_count = len({section["heading"] for section in sections if section["text"]})
    result.status = "empty" if result.char_count < MIN_USEFUL_CHARS else "ok"
    _write_cleaned(result)
    return result


def load_all(path: Path | None = None) -> list[LoadResult]:
    results: list[LoadResult] = []
    for source in load_registry(path):
        try:
            results.append(load_source(source))
        except Exception as exc:
            fetched_date = date.today().isoformat()
            failed = LoadResult(
                source=source,
                status="failed",
                fetched_date=fetched_date,
                error=str(exc),
                warnings=[str(exc)],
            )
            _write_cleaned(failed)
            results.append(failed)
    return results


def format_summary(results: list[LoadResult]) -> str:
    lines = ["id\tstatus\tchars\theadings\tnotes"]
    for result in results:
        notes = result.error or " | ".join(result.warnings)
        notes = notes.replace("\t", " ").replace("\n", " ")
        lines.append(
            f"{result.source.id}\t{result.status}\t{result.char_count}\t{result.heading_count}\t{notes}"
        )
    ok = sum(1 for result in results if result.status == "ok")
    empty = sum(1 for result in results if result.status == "empty")
    failed = sum(1 for result in results if result.status == "failed")
    lines.append("")
    lines.append(f"total={len(results)} ok={ok} empty={empty} failed={failed}")
    return "\n".join(lines)


def main() -> int:
    if not SOURCES_CSV.exists():
        print(f"Missing source registry: {SOURCES_CSV}", file=sys.stderr)
        return 1
    results = load_all()
    print(format_summary(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
