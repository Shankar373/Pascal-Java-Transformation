"""Static checks on the dashboard assets: CSP-safe, no external resources."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "tools" / "p1" / "web"
FORBIDDEN_JS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function",
                "document.write", "setTimeout(\"", "setInterval(\"")
#: the SVG namespace is an identifier, not a network reference
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
EXTERNAL = re.compile(r"(?:https?:)?//[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.attrs: list[tuple[str, str, str]] = []
        self.tags: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        for name, value in attrs:
            if name == "id" and value:
                self.ids.add(value)
            self.attrs.append((tag, name, value or ""))


@pytest.fixture(scope="module")
def html_info() -> _Collector:
    parser = _Collector()
    parser.feed((WEB / "index.html").read_text(encoding="utf-8"))
    return parser


@pytest.fixture(scope="module")
def js_text() -> str:
    return (WEB / "app.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("token", FORBIDDEN_JS)
def test_js_has_no_unsafe_dom_or_eval_constructs(js_text, token):
    assert token not in js_text


def test_html_has_no_inline_script_style_or_event_handlers(html_info):
    html = (WEB / "index.html").read_text(encoding="utf-8").lower()
    assert "<style" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    for tag, name, _ in html_info.attrs:
        assert not name.startswith("on"), (tag, name)
        assert name != "style", tag


def test_no_external_resources_anywhere(html_info, js_text):
    css = (WEB / "app.css").read_text(encoding="utf-8")
    for tag, name, value in html_info.attrs:
        if name in ("src", "href", "action", "data", "poster"):
            assert not EXTERNAL.match(value), (tag, name, value)
            assert value.startswith(("/", "#")), (tag, name, value)
    assert not EXTERNAL.search(js_text.replace(SVG_NAMESPACE, ""))
    assert "@import" not in css and "url(" not in css
    assert not EXTERNAL.search(css)


def test_every_id_the_js_looks_up_exists_in_the_html(html_info, js_text):
    looked_up = set(re.findall(r"(?:getElementById|byId)\(\s*[\"']([\w-]+)[\"']", js_text))
    looked_up |= set(re.findall(r"put\(\s*[\"']([\w-]+)[\"']", js_text))
    looked_up |= set(re.findall(r"querySelector(?:All)?\(\s*[\"']#([\w-]+)", js_text))
    looked_up |= {m for pair in re.findall(r"\[\s*[\"']([\w-]+)[\"']\s*,\s*[\"']?[\w-]+[\"']?\s*\]", js_text)
                  for m in [pair] if m.startswith(("nav-", "tab-", "tool-", "icon-", "btn-", "form-"))}
    looked_up = {i for i in looked_up if not i.endswith("-")}  # dynamic prefixes: see next test
    assert looked_up, "expected the script to look up elements by id"
    missing = sorted(looked_up - html_info.ids)
    assert not missing, f"ids used by app.js but absent from index.html: {missing}"


def test_dynamic_id_prefixes_resolve_to_real_elements(html_info):
    for kind in ("git", "zip", "directory"):
        assert f"card-{kind}" in html_info.ids and f"form-{kind}" in html_info.ids
    for name in ("tab-ingest", "tab-recent", "radio-directory", "zip-progress", "btn-git", "btn-zip", "btn-directory"):
        assert name in html_info.ids


def test_html_landmarks_and_accessibility_hooks(html_info):
    for tag in ("header", "nav", "main", "aside", "section", "form", "h1"):
        assert tag in html_info.tags, tag
    attrs = {(n, v) for _, n, v in html_info.attrs}
    assert ("role", "tablist") in attrs and ("role", "tabpanel") in attrs
    assert ("aria-live", "polite") in attrs and ("role", "alert") in attrs
    assert ("lang", "en") in attrs
    assert ("rel", "noopener") in attrs
    assert any(n == "for" for n, _ in attrs), "form fields must have associated labels"


def test_planned_stages_are_not_interactive_or_complete(html_info):
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for number in range(2, 7):
        block = html.split(f"Stage {number}</span>")[1].split("</li>")[0]
        assert "Planned" in block
    planned = re.findall(r'<li class="stage is-planned"[^>]*>', html)
    assert len(planned) == 5 and all('aria-disabled="true"' in p for p in planned)
    stage_list = html.split('<ol class="stage-list">')[1].split("</ol>")[0]
    assert "<a " not in stage_list and "<button" not in stage_list


def test_css_respects_reduced_motion_and_has_focus_styles():
    css = (WEB / "app.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css
    assert ":focus-visible" in css


def test_js_sends_the_csrf_header_on_posts(js_text):
    assert js_text.count("X-P1-Request") >= 2  # fetch helper and upload helper


def test_js_never_hardcodes_the_mockup_sample_values(js_text):
    for sample in ("legacy-pascal-erp", "4,892", "ERPSystem", "CP-2025", "3f7a2e9"):
        assert sample not in js_text
