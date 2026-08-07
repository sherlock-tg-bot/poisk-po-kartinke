#!/usr/bin/env python3
"""Autonomous content checks for this single-keyword repository."""

from __future__ import annotations

import html.parser
import html as html_lib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "metadata.json",
    "README.md",
    "FAQ.md",
    "SECURITY.md",
    "index.html",
    "scripts/validate.py",
    ".github/workflows/validate.yml",
)
CTA_LABEL = "Открыть в Telegram"
PROHIBITED_DIRECT_HOSTS = ("sherlockbot.is", "glazboga.is", "t.me", "telegram.me")


class PageParser(html.parser.HTMLParser):
    """Small HTML parser used without third-party dependencies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.h1_text: list[str] = []
        self.title_text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.canonical_hrefs: list[str] = []
        self._in_h1 = False
        self._in_title = False
        self._current_link: str | None = None
        self._current_link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        attributes = dict(attrs)
        if tag == "h1":
            self._in_h1 = True
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            self._current_link = attributes.get("href") or ""
            self._current_link_text = []
        elif tag == "link" and attributes.get("rel", "").lower() == "canonical":
            self.canonical_hrefs.append(attributes.get("href") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_h1 = False
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._current_link is not None:
            self.links.append((self._current_link, "".join(self._current_link_text).strip()))
            self._current_link = None
            self._current_link_text = []

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self.h1_text.append(data)
        if self._in_title:
            self.title_text.append(data)
        if self._current_link is not None:
            self._current_link_text.append(data)


def fail(message: str) -> None:
    print(f"ERROR: {message}")


def direct_prohibited_urls(text: str) -> list[str]:
    pattern = re.compile(r"https?://(?:www\.)?(?:sherlockbot\.is|glazboga\.is|t\.me|telegram\.me)(?=[/:?#\s]|$)", re.I)
    return pattern.findall(text)


def check_required_files(errors: list[str]) -> None:
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required file: {relative}")


def check_metadata(metadata: dict, errors: list[str]) -> tuple[str, str, str]:
    keyword = metadata.get("keyword")
    slug = metadata.get("slug")
    target_url = metadata.get("target_url")
    if not isinstance(keyword, str) or not keyword.strip():
        errors.append("metadata.keyword must be a non-empty string")
        keyword = ""
    if not isinstance(slug, str) or not slug.strip():
        errors.append("metadata.slug must be a non-empty string")
        slug = ""
    if not isinstance(target_url, str) or not target_url.strip():
        errors.append("metadata.target_url must be a non-empty string")
        target_url = ""
    else:
        parsed = urlparse(target_url)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append("metadata.target_url must be an https URL")
    return keyword, slug, target_url


def check_markdown(keyword: str, target_url: str, errors: list[str]) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    faq = (ROOT / "FAQ.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    h1 = re.search(r"^#\s+(.+)$", readme, re.MULTILINE)
    if not h1 or keyword.casefold() not in h1.group(1).casefold():
        errors.append("README H1 must naturally contain metadata.keyword")
    if keyword.casefold() not in readme.casefold():
        errors.append("README must contain metadata.keyword")
    if keyword.casefold() not in faq.casefold():
        errors.append("FAQ must contain metadata.keyword")
    if target_url not in readme[:1200]:
        errors.append("target_url must be used in the beginning of README")
    if target_url not in readme[-900:]:
        errors.append("target_url must be used in the final README block")
    if target_url not in security:
        errors.append("target_url must be present in SECURITY.md")
    if len(re.findall(r"^##\s+", faq, re.MULTILINE)) < 4:
        errors.append("FAQ must contain at least 4 substantive questions")
    for phrase, filename in (
        ("Ограничения метода", "README.md"),
        ("первоисточник", "README.md"),
        ("преследования", "README.md"),
        ("согласия", "SECURITY.md"),
    ):
        content = readme if filename == "README.md" else security
        if phrase.casefold() not in content.casefold():
            errors.append(f"{filename} is missing required safety/content topic: {phrase}")

    all_markdown = readme + "\n" + faq + "\n" + security
    for url in direct_prohibited_urls(all_markdown):
        errors.append(f"prohibited direct CTA URL in markdown: {url}")
    if "img.shields.io" in readme or "img.shields.io" in faq or "img.shields.io" in security:
        errors.append("external badges are not allowed")
    expected_badge = f"https://github.com/sherlock-tg-bot/{json.loads((ROOT / 'metadata.json').read_text(encoding='utf-8'))['slug']}/actions/workflows/validate.yml/badge.svg"
    badges = re.findall(r"!\[[^\]]*\]\((https?://[^)]+)\)", readme)
    if badges != [expected_badge]:
        errors.append("README must contain only the repository workflow badge")


def check_html(keyword: str, target_url: str, errors: list[str]) -> None:
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    parser = PageParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # pragma: no cover - defensive parser guard
        errors.append(f"index.html cannot be parsed: {exc}")
        return

    if "html" not in parser.tags or "head" not in parser.tags or "body" not in parser.tags:
        errors.append("index.html must contain html, head and body")
    if keyword.casefold() not in "".join(parser.h1_text).casefold():
        errors.append("index.html H1 must contain metadata.keyword")
    if not "".join(parser.title_text).strip():
        errors.append("index.html must have a non-empty title")
    cta_links = [(href, text) for href, text in parser.links if text == CTA_LABEL]
    if not cta_links or any(href != target_url for href, _ in cta_links):
        errors.append("index.html CTA must use the exact target_url and required label")
    escaped_target_url = html_lib.escape(target_url, quote=True)
    if target_url not in html and escaped_target_url not in html:
        errors.append("index.html must contain metadata.target_url")
    for href in parser.canonical_hrefs:
        if href == target_url or "sherlockbot.is" in href or "glazboga.is" in href:
            errors.append("index.html canonical must not point to the CTA or service domain")
    for url in direct_prohibited_urls(html):
        if url.casefold() != urlparse(target_url).scheme + "://" + urlparse(target_url).netloc.casefold():
            errors.append(f"prohibited direct URL in index.html: {url}")
    if "analytics" in html.casefold() or "metrika" in html.casefold():
        errors.append("analytics code or analytics text is not allowed")


def check_workflow(errors: list[str]) -> None:
    workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    if "name: Content validation" not in workflow:
        errors.append("workflow name must be Content validation")
    if "python3 scripts/validate.py" not in workflow:
        errors.append("workflow must run python3 scripts/validate.py")


def main() -> int:
    errors: list[str] = []
    check_required_files(errors)
    metadata_path = ROOT / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"metadata.json is invalid: {exc}")
        metadata = {}

    keyword, slug, target_url = check_metadata(metadata, errors)
    if keyword and target_url:
        check_markdown(keyword, target_url, errors)
        check_html(keyword, target_url, errors)
    if slug:
        check_workflow(errors)

    if errors:
        for error in errors:
            fail(error)
        print(f"Validation failed with {len(errors)} error(s).")
        return 1
    print("Validation passed: required files, keyword, CTA, safety content, badge and HTML checks are OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
