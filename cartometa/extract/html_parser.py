from __future__ import annotations
import re
from datetime import datetime, timezone
from urllib.parse import unquote
from selectolax.parser import HTMLParser
from cartometa.models import MetaRecord, TIER_COUNTRY, TIER_REGIONAL, TIER_SPOT

TIER_BY_STEP = {"1": TIER_COUNTRY, "2": TIER_REGIONAL, "3": TIER_SPOT}
STEP_RE = re.compile(r"step\s*(\d)", re.IGNORECASE)
MAPS_RE = re.compile(r"^https://(maps\.app\.goo\.gl|goo\.gl/maps)/", re.IGNORECASE)


def _clean_text(node) -> str:
    """Texte complet du noeud, espaces entre éléments préservés et normalisés."""
    return re.sub(r"\s+", " ", node.text(strip=False)).strip()


def _widest_srcset(node) -> str | None:
    """Retient l'URL de plus grande largeur déclarée, sinon le src."""
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
            continue  # Step 4 et hors-section : ignorés volontairement

        strong = node.css_first("strong")
        paragraph = node.css_first("p")
        if strong is None or paragraph is None:
            anomalies.append(f"bloc {block_id}: titre ou description absent, ignoré")
            continue

        image_node = node.css_first("img")
        link = next(
            (a.attributes.get("href") for a in node.css("a")
             if a.attributes.get("href") and MAPS_RE.match(a.attributes["href"])),
            None,
        )

        metas.append(MetaRecord(
            id=block_id,
            country=country,
            tier=current_tier,
            title=_clean_text(strong),
            description=_clean_text(paragraph),
            category="autre",
            source_url=f"{base_url}#{block_id}",
            extracted_at=now,
            image=_widest_srcset(image_node) if image_node is not None else None,
            maps_url=link,
        ))
    return metas, anomalies
