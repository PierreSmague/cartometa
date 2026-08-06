from __future__ import annotations

from cartometa.extract.rmrg import SECTION_CATEGORIES, parse_rmrg_page, title_from_slug
from cartometa.models import ORIGIN_RMRG, TIER_REGIONAL

BASE_URL = "https://rmrg.me/bangladesh/"

PAGE = """
<div class="category-section" id="landscape-section">
  <div class="category-header"><h3 class="category-title">Landscape</h3></div>
  <div class="meta-list">
    <div class="meta-item" id="landscape/water-plots1" data-item-slug="water-plots1">
      <div class="meta-image-wrapper">
        <a href="https://maps.app.goo.gl/dkf3fRftJGQCvMet9" target="_blank" class="image-link">
          <div class="image-with-overlay">
            <div class="base-image"><img src="Files/water-plots1_8PNy.webp" alt=""></div>
            <div class="svg-overlay-container"><img src="Files/water-plots1_8PNy.svg" class="svg-overlay"></div>
          </div>
        </a>
      </div>
      <div class="meta-content"><div class="meta-description">In the <strong>far south</strong>,
        roads run through   <strong>water plots</strong>.</div></div>
    </div>
  </div>
</div>
<div class="category-section" id="agriculture-section">
  <div class="category-header"><h3 class="category-title">Agriculture</h3></div>
  <div class="meta-list">
    <div class="meta-item" id="agriculture/betel-farms" data-item-slug="betel-farms">
      <div class="meta-image-wrapper">
        <div class="base-image"><img src="Files/betel-farms_8PNy.webp" alt=""></div>
      </div>
      <div class="meta-content"><div class="meta-description">Betel leaf farms, with a
        <a href="https://maps.app.goo.gl/AAAABBBBCCCCDDDD">good example here</a>.</div></div>
    </div>
  </div>
</div>
<div class="category-section" id="architecture-section">
  <div class="category-header"><h3 class="category-title">Architecture</h3></div>
  <div class="subcategory-section" id="architecture-wood-frames-section">
    <h4 class="subcategory-title">Wood Frames</h4>
    <div class="meta-list">
      <div class="meta-item" id="architecture/wood-frames/wood-frame-houses" data-item-slug="wood-frame-houses">
        <div class="meta-content"><div class="meta-description">Wood frame houses.</div></div>
      </div>
    </div>
  </div>
</div>
<div class="learnable-maps-section">
  <div class="learnable-maps-header"><h3 class="learnable-maps-title">Learnable Meta Maps</h3></div>
</div>
"""


def test_metas_carry_the_rmrg_identity():
    metas, anomalies = parse_rmrg_page(PAGE, "BD", BASE_URL)
    assert anomalies == []
    assert [m.id for m in metas] == [
        "landscape/water-plots1",
        "agriculture/betel-farms",
        "architecture/wood-frames/wood-frame-houses",
    ]
    first = metas[0]
    assert first.country == "BD"
    assert first.tier == TIER_REGIONAL
    assert first.origin == ORIGIN_RMRG
    assert first.source_url == "https://rmrg.me/bangladesh/#landscape/water-plots1"


def test_category_comes_from_the_section_heading():
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    by_id = {m.id: m for m in metas}
    assert by_id["landscape/water-plots1"].category == "landscape"
    # Agriculture files under vegetation: the taxonomy has no agriculture pill.
    assert by_id["agriculture/betel-farms"].category == "vegetation"
    # A meta inside an h4 subsection still belongs to its h3 section.
    assert by_id["architecture/wood-frames/wood-frame-houses"].category == "architecture"


def test_unknown_section_falls_back_with_an_anomaly():
    page = PAGE.replace(">Landscape<", ">Wildlife<")
    metas, anomalies = parse_rmrg_page(page, "BD", BASE_URL)
    assert metas[0].category == "autre"
    assert any("wildlife" in a.lower() for a in anomalies)


def test_title_is_the_humanised_slug():
    assert title_from_slug("water-plots1") == "Water plots"
    assert title_from_slug("alternating-brick-corners") == "Alternating brick corners"
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    assert metas[0].title == "Water plots"


def test_description_text_is_normalised():
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    assert metas[0].description == "In the far south, roads run through water plots."


def test_maps_url_prefers_the_image_link_then_falls_back_to_the_text():
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    by_id = {m.id: m for m in metas}
    assert by_id["landscape/water-plots1"].maps_url == "https://maps.app.goo.gl/dkf3fRftJGQCvMet9"
    # No image-link on this block: the maps link inside the description is used.
    assert by_id["agriculture/betel-farms"].maps_url == "https://maps.app.goo.gl/AAAABBBBCCCCDDDD"
    assert by_id["architecture/wood-frames/wood-frame-houses"].maps_url is None


def test_image_and_overlay_are_the_raw_decoded_srcs():
    metas, _ = parse_rmrg_page(PAGE, "BD", BASE_URL)
    by_id = {m.id: m for m in metas}
    assert by_id["landscape/water-plots1"].image == "Files/water-plots1_8PNy.webp"
    assert by_id["landscape/water-plots1"].overlay == "Files/water-plots1_8PNy.svg"
    assert by_id["agriculture/betel-farms"].overlay is None
    assert by_id["architecture/wood-frames/wood-frame-houses"].image is None


def test_block_without_description_is_skipped_with_an_anomaly():
    page = PAGE.replace(
        '<div class="meta-content"><div class="meta-description">Wood frame houses.</div></div>',
        "",
    )
    metas, anomalies = parse_rmrg_page(page, "BD", BASE_URL)
    assert [m.id for m in metas] == ["landscape/water-plots1", "agriculture/betel-farms"]
    assert any("wood-frame-houses" in a for a in anomalies)


def test_section_mapping_covers_the_six_known_sections():
    assert SECTION_CATEGORIES == {
        "landscape": "landscape",
        "agriculture": "vegetation",
        "vegetation": "vegetation",
        "architecture": "architecture",
        "infrastructure": "infrastructure",
        "culture": "culture",
    }
