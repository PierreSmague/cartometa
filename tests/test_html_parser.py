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


def test_thematic_h3_without_step_keeps_current_tier():
    """The USA page subdivides Step 2 with thematic h3s ("Road Features",
    "Poles", "Bollards"...): those blocks are still Step 2 material."""
    html = (
        '<h3>Step 2 - Regional and state-specific clues</h3>'
        '<div id="REG1" class="relative group/bk"><p><strong>A</strong> clue.</p></div>'
        '<h3>Road Features</h3>'
        '<div id="REG2" class="relative group/bk"><p><strong>B</strong> clue.</p></div>'
    )
    metas, anomalies = parse_page(html, "US", "https://x/usa")
    assert {m.id: m.tier for m in metas} == {"REG1": "regional", "REG2": "regional"}
    assert anomalies == []


def test_empty_h3_inside_a_block_does_not_end_the_section():
    """The USA Spotlight contains a block with a decorative empty <h3>: the
    blocks that follow are still Step 3 material."""
    html = (
        '<h3>Step 3 - Spotlight</h3>'
        '<div id="SPOT1" class="relative group/bk">'
        '<h3 class="font-medium text-center pb-0"></h3>'
        '<p><strong>A</strong> spot.</p>'
        '</div>'
        '<div id="SPOT2" class="relative group/bk"><p><strong>B</strong> spot.</p></div>'
    )
    metas, _ = parse_page(html, "US", "https://x/usa")
    assert {m.id: m.tier for m in metas} == {"SPOT1": "spot", "SPOT2": "spot"}


def test_blocks_before_step_1_are_still_ignored():
    html = (
        '<h3>About this guide</h3>'
        '<div id="INTRO" class="relative group/bk"><p><strong>Not</strong> a meta.</p></div>'
        '<h3>Step 1 - Identifying the country</h3>'
        '<div id="REAL" class="relative group/bk"><p><strong>A</strong> clue.</p></div>'
    )
    metas, _ = parse_page(html, "US", "https://x/usa")
    assert [m.id for m in metas] == ["REAL"]


def test_block_without_paragraph_is_reported_as_anomaly_not_crash():
    html = '<h3>Step 2 - Regional</h3><div id="BAD" class="relative group/bk"><strong>x</strong></div>'
    metas, anomalies = parse_page(html, "PL", "https://x/poland")
    assert metas == []
    assert any("BAD" in a for a in anomalies)


def test_block_without_strong_at_all_uses_first_sentence_not_anomaly():
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="BAD" class="relative group/bk">'
        '<p>No bold here. Second sentence follows.</p>'
        '</div>'
    )
    metas, anomalies = parse_page(html, "PL", "https://x/poland")
    assert anomalies == []
    assert metas[0].title == "No bold here."
    assert metas[0].description == "No bold here. Second sentence follows."


def test_title_keeps_strong_when_it_opens_the_paragraph():
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="OPEN" class="relative group/bk">'
        '<p><strong>Bollards</strong> are white with a red stripe.</p>'
        '</div>'
    )
    metas, _ = parse_page(html, "PL", "https://x/poland")
    assert metas[0].title == "Bollards"


def test_title_tolerates_insignificant_punctuation_before_leading_strong():
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="PUNC" class="relative group/bk">'
        '<p>— <strong>Bollards</strong> are white with a red stripe.</p>'
        '</div>'
    )
    metas, _ = parse_page(html, "PL", "https://x/poland")
    assert metas[0].title == "Bollards"


def test_title_merges_consecutive_leading_strong_runs():
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="TWIN" class="relative group/bk">'
        '<p><strong>Regional</strong> <strong>roads</strong> have 3-digit numbers.</p>'
        '</div>'
    )
    metas, _ = parse_page(html, "PL", "https://x/poland")
    assert metas[0].title == "Regional roads"


def test_title_merges_consecutive_leading_strong_runs_across_span_wrapped_whitespace():
    """Reproduces the real Plonk It HTML, where the separator between two leading
    <strong>s is a space wrapped in a <span>, not a plain text node."""
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="TWIN2" class="relative group/bk">'
        '<p><strong><span>Regional</span></strong><span> </span>'
        '<strong><span>roads</span></strong><span> have 3-digit numbers.</span></p>'
        '</div>'
    )
    metas, _ = parse_page(html, "PL", "https://x/poland")
    assert metas[0].title == "Regional roads"


def test_title_falls_back_to_first_sentence_when_strong_is_mid_sentence():
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="MID" class="relative group/bk">'
        '<p>Poles with <strong>yellow markings</strong> are found in western Poland. '
        'A second sentence.</p>'
        '</div>'
    )
    metas, _ = parse_page(html, "PL", "https://x/poland")
    assert metas[0].title == "Poles with yellow markings are found in western Poland."


def test_title_first_sentence_not_split_on_abbreviation():
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="ABBR" class="relative group/bk">'
        '<p>Dr. Kowalski says hello loudly. He then leaves the room.</p>'
        '</div>'
    )
    metas, _ = parse_page(html, "PL", "https://x/poland")
    assert metas[0].title == "Dr. Kowalski says hello loudly."


def test_title_first_sentence_not_split_on_url_dot():
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="URL" class="relative group/bk">'
        '<p>See https://example.com/path for details. It helps a lot.</p>'
        '</div>'
    )
    metas, _ = parse_page(html, "PL", "https://x/poland")
    assert metas[0].title == "See https://example.com/path for details."


def test_title_truncates_unreasonably_long_first_sentence():
    long_sentence = (
        "This is a very long clue description that keeps going on and on "
        "without any punctuation at all to stop it for quite a long while, "
        "well beyond what any reasonable title should ever need to contain"
    )
    html = (
        '<h3>Step 2 - Regional</h3>'
        '<div id="LONG" class="relative group/bk">'
        f'<p>{long_sentence}.</p>'
        '</div>'
    )
    metas, _ = parse_page(html, "PL", "https://x/poland")
    title = metas[0].title
    assert title.endswith("…")
    assert len(title) <= 185
    assert not title.endswith(" …")
