from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import unquote

from selectolax.parser import HTMLParser

from cartometa.extract.categories import FALLBACK
from cartometa.extract.html_parser import MAPS_RE, _clean_text
from cartometa.models import MetaRecord, ORIGIN_RMRG, TIER_REGIONAL

# RMRG sections -> Cartometa taxonomy. Agriculture files under vegetation (the
# taxonomy has no agriculture pill, the spec folds farming into vegetation);
# the other five map 1:1. An unknown section falls back to `autre` with an
# anomaly: RMRG may add sections, and half-classified is better than dropped.
SECTION_CATEGORIES = {
    "landscape": "landscape",
    "agriculture": "vegetation",
    "vegetation": "vegetation",
    "architecture": "architecture",
    "infrastructure": "infrastructure",
    "culture": "culture",
}

_TRAILING_DIGITS_RE = re.compile(r"\d+$")


def title_from_slug(slug: str) -> str:
    """`water-plots1` -> "Water plots": the RMRG slugs are descriptive names
    chosen by the authors, shorter and more stable than a first sentence. The
    trailing digits only disambiguate several photos of the same clue."""
    text = " ".join(_TRAILING_DIGITS_RE.sub("", slug).replace("-", " ").replace("_", " ").split())
    return text[:1].upper() + text[1:]


def _maps_link(item) -> str | None:
    """The image-link href when it is a Maps link, else the first Maps link
    anywhere in the block (some metas only link Maps from their description)."""
    image_link = item.css_first("a.image-link")
    if image_link is not None:
        href = image_link.attributes.get("href")
        if href and MAPS_RE.match(href):
            return href
    return next(
        (a.attributes.get("href") for a in item.css("a")
         if a.attributes.get("href") and MAPS_RE.match(a.attributes["href"])),
        None,
    )


def _src(item, selector: str) -> str | None:
    node = item.css_first(selector)
    if node is None:
        return None
    src = node.attributes.get("src")
    return unquote(src) if src else None


def parse_rmrg_page(html: str, country: str, base_url: str) -> tuple[list[MetaRecord], list[str]]:
    """The RMRG counterpart of `parse_page`: one MetaRecord per `.meta-item`.

    `image` and `overlay` hold the raw decoded srcs, relative to the saved
    page — resolving them against the disk is the CLI's job, like Plonk It.
    """
    tree = HTMLParser(html)
    now = datetime.now(timezone.utc).isoformat()
    metas: list[MetaRecord] = []
    anomalies: list[str] = []

    for section in tree.css("div.category-section"):
        heading = section.css_first("h3.category-title")
        name = _clean_text(heading).lower() if heading is not None else ""
        category = SECTION_CATEGORIES.get(name)
        if category is None:
            anomalies.append(
                f"section '{name}': not in the known taxonomy, metas filed under '{FALLBACK}'"
            )
            category = FALLBACK

        for item in section.css("div.meta-item"):
            block_id = item.attributes.get("id")
            if not block_id:
                anomalies.append(f"section '{name}': meta-item without id, skipped")
                continue
            description_node = item.css_first("div.meta-description")
            if description_node is None:
                anomalies.append(f"block {block_id}: description missing, skipped")
                continue
            slug = item.attributes.get("data-item-slug") or block_id.rsplit("/", 1)[-1]
            description = _clean_text(description_node)
            metas.append(MetaRecord(
                id=block_id,
                country=country,
                tier=TIER_REGIONAL,
                title=title_from_slug(slug),
                description=description,
                category=category,
                source_url=f"{base_url}#{block_id}",
                extracted_at=now,
                origin=ORIGIN_RMRG,
                image=_src(item, ".base-image img"),
                maps_url=_maps_link(item),
                overlay=_src(item, ".svg-overlay-container img"),
            ))
    return metas, anomalies
