from cartometa.extract.maps_links import resolve_maps_url, extract_latlon

REDIRECT = "https://www.google.com/maps/@49.302333,20.0088885,3a,45.1y,155.29h,90.27t,0.33r/data=!3m6"


def test_extract_latlon_from_redirect_url():
    assert extract_latlon(REDIRECT) == (49.302333, 20.0088885)


def test_extract_latlon_returns_none_when_absent():
    assert extract_latlon("https://www.google.com/maps/place/Krakow") is None


def test_resolve_uses_redirect_location_without_fetching_target():
    calls = []

    def opener(url):
        calls.append(url)
        return REDIRECT

    cache = {}
    assert resolve_maps_url("https://goo.gl/maps/abc", cache, opener) == (49.302333, 20.0088885)
    assert calls == ["https://goo.gl/maps/abc"]


def test_resolve_is_cached_and_hits_network_once():
    calls = []

    def opener(url):
        calls.append(url)
        return REDIRECT

    cache = {}
    resolve_maps_url("https://goo.gl/maps/abc", cache, opener)
    resolve_maps_url("https://goo.gl/maps/abc", cache, opener)
    assert len(calls) == 1


def test_unresolvable_link_is_cached_as_null_and_returns_none():
    def opener(url):
        raise OSError("timeout")

    cache = {}
    assert resolve_maps_url("https://goo.gl/maps/dead", cache, opener) is None
    assert cache["https://goo.gl/maps/dead"] is None
