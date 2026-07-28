from cartometa.extract.html_parser import parse_page

PAGE = """
<h1>Poland</h1>
<h3>Step 1 - Identifying Poland</h3>
<div id="AAAA" class="relative group/bk">
  <img srcset="f/bollard_006.webp 450w, f/bollard_005.webp 1920w" src="f/bollard_006.webp">
  <p><strong>Bollards</strong> are white with a red stripe.</p>
</div>
<h3>Step 2 - Regional and voivodeship-specific clues</h3>
<div id="1VXO" class="relative group/bk">
  <a href="https://maps.app.goo.gl/JmGQh1"><img srcset="f/orchards_004.webp 600w, f/orchards_005.webp 1920w"></a>
  <p><strong>Orchards</strong> are mostly concentrated around Grojec.</p>
</div>
<h3>Step 3 - Spotlight</h3>
<div id="TATR" class="relative group/bk">
  <a href="https://goo.gl/maps/axmv3M"><img srcset="f/tatra_002.webp 1200w"></a>
  <p><strong>Tatra Mountains</strong> are visible in the far south.</p>
</div>
<h3>Step 4 - Maps and resources</h3>
<div id="ZZZZ" class="relative group/bk"><p><strong>Links</strong> here.</p></div>
"""


def test_parses_one_record_per_tip_block_ignoring_step_4():
    metas, anomalies = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    assert [m.id for m in metas] == ["AAAA", "1VXO", "TATR"]
    assert anomalies == []


def test_tier_comes_from_preceding_heading():
    metas, _ = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    assert {m.id: m.tier for m in metas} == {
        "AAAA": "country", "1VXO": "regional", "TATR": "spot",
    }


def test_title_is_strong_and_description_is_full_paragraph():
    metas, _ = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    orchards = next(m for m in metas if m.id == "1VXO")
    assert orchards.title == "Orchards"
    assert orchards.description == "Orchards are mostly concentrated around Grojec."


def test_selects_widest_srcset_variant():
    metas, _ = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    assert next(m for m in metas if m.id == "1VXO").image == "f/orchards_005.webp"
    assert next(m for m in metas if m.id == "AAAA").image == "f/bollard_005.webp"


def test_captures_maps_url_and_builds_anchored_source_url():
    metas, _ = parse_page(PAGE, "PL", "https://www.plonkit.net/poland")
    tatra = next(m for m in metas if m.id == "TATR")
    assert tatra.maps_url == "https://goo.gl/maps/axmv3M"
    assert tatra.source_url == "https://www.plonkit.net/poland#TATR"
    assert next(m for m in metas if m.id == "AAAA").maps_url is None


def test_block_without_strong_is_reported_as_anomaly_not_crash():
    html = '<h3>Step 2 - Regional</h3><div id="BAD" class="relative group/bk"><p>no strong</p></div>'
    metas, anomalies = parse_page(html, "PL", "https://x/poland")
    assert metas == []
    assert any("BAD" in a for a in anomalies)
