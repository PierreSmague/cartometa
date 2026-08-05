from __future__ import annotations
import re
from datetime import datetime, timezone
from urllib.parse import unquote
from selectolax.parser import HTMLParser
from cartometa.models import MetaRecord, TIER_COUNTRY, TIER_REGIONAL, TIER_SPOT

TIER_BY_STEP = {"1": TIER_COUNTRY, "2": TIER_REGIONAL, "3": TIER_SPOT}
STEP_RE = re.compile(r"step\s*(\d)", re.IGNORECASE)
MAPS_RE = re.compile(r"^https://(maps\.app\.goo\.gl|goo\.gl/maps)/", re.IGNORECASE)

# Punctuation/whitespace tolerated before a <strong> that still counts as
# "opening" the paragraph (em dash, quotes, colon...).
_LEADING_INSIGNIFICANT_RE = re.compile(
    r'^[\s"\'‘’“”«»\-‐‑‒–—:;,.]*$'
)

# Common abbreviations whose period does not end a sentence.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "vs", "etc", "e.g", "i.e", "u.s", "u.k",
    "ave", "inc", "jr", "sr", "prof", "no", "approx", "fig", "vol", "cf",
}

MAX_TITLE_LENGTH = 180


def _clean_text(node) -> str:
    """Full text of the node, whitespace between elements preserved and normalised."""
    return re.sub(r"\s+", " ", node.text(strip=False)).strip()


def _truncate_readably(text: str) -> str:
    """Truncate cleanly at the last word boundary, never exceeding MAX_TITLE_LENGTH."""
    if len(text) <= MAX_TITLE_LENGTH:
        return text
    truncated = text[:MAX_TITLE_LENGTH]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip(" ,.;:") + "…"


def _first_sentence(text: str) -> str:
    """First sentence of `text`, immune to abbreviations and to periods in URLs."""
    text = text.strip()
    for match in re.finditer(r"[.!?]", text):
        pos = match.start()
        after = text[pos + 1:]
        if after and not after[0].isspace():
            # A period immediately followed by a character (URL, decimal, glued-on
            # abbreviation): this is not the end of a sentence.
            continue
        preceding = text[:pos]
        word_match = re.search(r"[\w.]+$", preceding)
        word = word_match.group(0).lower() if word_match else ""
        if word in _ABBREVIATIONS or (len(word) == 1 and word.isalpha()):
            continue
        return _truncate_readably(text[: pos + 1].strip())
    return _truncate_readably(text)


def _visible_text(node) -> str:
    """Visible text of a direct paragraph child, be it a raw text node or an
    element (e.g. a <span> wrapping nothing but a space)."""
    return node.text() if node.tag == "-text" else _clean_text(node)


def _derive_title(paragraph, description: str) -> str:
    """Title: the <strong> if it opens the paragraph (insignificant punctuation or
    whitespace tolerated before it, consecutive leading <strong>s merged even when
    separated by HTML containing only whitespace), otherwise the first sentence of
    the description."""
    children = list(paragraph.iter(include_text=True))
    i = 0
    leading = ""
    while i < len(children) and children[i].tag != "strong":
        leading += _visible_text(children[i])
        i += 1

    if (
        i < len(children)
        and children[i].tag == "strong"
        and _LEADING_INSIGNIFICANT_RE.match(leading)
    ):
        parts = []
        while i < len(children):
            node = children[i]
            if node.tag == "strong":
                parts.append(_clean_text(node))
                i += 1
                continue
            if _visible_text(node).strip() != "":
                break
            # Insignificant whitespace: we only merge across it if it leads to
            # another <strong>, otherwise we stop without consuming it needlessly.
            j = i + 1
            while j < len(children) and _visible_text(children[j]).strip() == "":
                j += 1
            if j < len(children) and children[j].tag == "strong":
                i = j
                continue
            break
        title = " ".join(p for p in parts if p)
        if title:
            return title

    return _first_sentence(description)


def _widest_srcset(node) -> str | None:
    """Keep the URL with the largest declared width, otherwise the src."""
    srcset = node.attributes.get("srcset")
    if srcset:
        best, best_w = None, -1
        for candidate in srcset.split(","):
            parts = candidate.strip().split()
            if len(parts) == 2 and parts[1].endswith("w"):
                width = int(parts[1][:-1])
                if width > best_w:
                    best, best_w = parts[0], width
        if best:
            return unquote(best)
    src = node.attributes.get("src")
    return unquote(src) if src else None


def parse_page(html: str, country: str, base_url: str) -> tuple[list[MetaRecord], list[str]]:
    tree = HTMLParser(html)
    now = datetime.now(timezone.utc).isoformat()
    metas: list[MetaRecord] = []
    anomalies: list[str] = []
    current_tier: str | None = None

    body = tree.css_first("body") or tree.root
    for node in body.traverse(include_text=False):
        if node.tag not in ("h3", "div"):
            continue
        if node.tag == "h3":
            match = STEP_RE.search(node.text(strip=True))
            current_tier = TIER_BY_STEP.get(match.group(1)) if match else None
            continue

        classes = node.attributes.get("class") or ""
        block_id = node.attributes.get("id")
        if "group/bk" not in classes or not block_id:
            continue
        if current_tier is None:
            continue  # Step 4 and out-of-section: deliberately ignored

        paragraph = node.css_first("p")
        if paragraph is None:
            anomalies.append(f"block {block_id}: description missing, skipped")
            continue

        image_node = node.css_first("img")
        link = next(
            (a.attributes.get("href") for a in node.css("a")
             if a.attributes.get("href") and MAPS_RE.match(a.attributes["href"])),
            None,
        )

        description = _clean_text(paragraph)
        metas.append(MetaRecord(
            id=block_id,
            country=country,
            tier=current_tier,
            title=_derive_title(paragraph, description),
            description=description,
            category="autre",
            source_url=f"{base_url}#{block_id}",
            extracted_at=now,
            image=_widest_srcset(image_node) if image_node is not None else None,
            maps_url=link,
        ))
    return metas, anomalies
