from cartometa.extract.maps_links import resolve_maps_url, extract_latlon

REDIRECT = "https://www.google.com/maps/@49.302333,20.0088885,3a,45.1y,155.29h,90.27t,0.33r/data=!3m6"

# Format observé lors du rejeu des liens en échec (relecture finale) : les
# vieux liens `goo.gl/maps` ne redirigent pas tous vers un `/@lat,lon`, une
# partie redirige vers un viewer panorama Street View où les coordonnées sont
# dans le paramètre de requête `viewpoint=lat,lon`, pas dans le chemin. Ce
# n'était pas du throttling Google : c'est un deuxième format de réponse que
# le premier motif ne couvrait pas.
PANO_REDIRECT = (
    "https://www.google.com/maps/@?api=1&map_action=pano&pano=JtD093Ix2cWNVVBR89Pf0w"
    "&viewpoint=54.720839,18.621438&heading=308.13&pitch=-11.37&fov=133.16&shorturl=1&ucbcb=1"
)


def test_extract_latlon_from_redirect_url():
    assert extract_latlon(REDIRECT) == (49.302333, 20.0088885)


def test_extract_latlon_returns_none_when_absent():
    assert extract_latlon("https://www.google.com/maps/place/Krakow") is None


def test_extract_latlon_from_panorama_viewpoint_redirect():
    assert extract_latlon(PANO_REDIRECT) == (54.720839, 18.621438)


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


def test_cached_null_is_not_retried_by_default():
    """Comportement conservé : un échec en cache reste un échec, sans réseau."""
    calls = []

    def opener(url):
        calls.append(url)
        return REDIRECT

    cache = {"https://goo.gl/maps/dead": None}
    assert resolve_maps_url("https://goo.gl/maps/dead", cache, opener) is None
    assert calls == []
    assert cache["https://goo.gl/maps/dead"] is None


def test_cached_null_is_retried_when_asked_and_succeeds():
    calls = []

    def opener(url):
        calls.append(url)
        return REDIRECT

    cache = {"https://goo.gl/maps/dead": None}
    result = resolve_maps_url("https://goo.gl/maps/dead", cache, opener, retry_failed=True)
    assert result == (49.302333, 20.0088885)
    assert calls == ["https://goo.gl/maps/dead"]
    assert cache["https://goo.gl/maps/dead"] == [49.302333, 20.0088885]


def test_cached_null_retried_and_still_failing_stays_null():
    def opener(url):
        raise OSError("still throttled")

    cache = {"https://goo.gl/maps/dead": None}
    result = resolve_maps_url("https://goo.gl/maps/dead", cache, opener, retry_failed=True)
    assert result is None
    assert cache["https://goo.gl/maps/dead"] is None


def test_retry_failed_does_not_affect_already_resolved_links():
    """Un lien déjà résolu ne doit pas être re-tapé sur le réseau même avec retry_failed."""
    calls = []

    def opener(url):
        calls.append(url)
        return REDIRECT

    cache = {"https://goo.gl/maps/ok": [49.0, 20.0]}
    result = resolve_maps_url("https://goo.gl/maps/ok", cache, opener, retry_failed=True)
    assert result == (49.0, 20.0)
    assert calls == []
