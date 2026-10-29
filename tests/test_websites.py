"""Tests de l'ouverture de sites web : rien n'est ouvert pour de vrai."""

from __future__ import annotations

from jarvis_core import tools as T
from jarvis_core import websites as W
from jarvis_core.i18n import STRINGS


def test_known_sites_aliases_and_addresses():
    assert W.resolve("YouTube") == "https://www.youtube.com"
    assert W.resolve("le site youtube") == "https://www.youtube.com"
    assert W.resolve("mail") == "https://mail.google.com"
    assert W.resolve("Météo") == "https://meteofrance.com"
    assert W.resolve("lemonde.fr") == "https://lemonde.fr"
    assert W.resolve("https://exemple.org/page?x=1") == "https://exemple.org/page?x=1"
    assert W.resolve("un site imaginaire") is None


def test_dangerous_addresses_are_refused():
    for bad in ("file:///C:/Windows/system32", "javascript:alert(1)", "C:\\secret.txt",
                "ftp://exemple.org", "cmd /c del *", ""):
        assert W.resolve(bad) is None, bad
        assert W.open_url(bad, opener=lambda _u: True) is False, bad


def test_search_urls_are_encoded():
    assert W.search_url("YouTube", "tutos python") == \
        "https://www.youtube.com/results?search_query=tutos+python"
    assert W.search_url("maps", "boulangerie & café") == \
        "https://www.google.com/maps/search/boulangerie+%26+caf%C3%A9"
    assert W.search_url("inconnu", "x") is None
    assert W.search_url("google", "  ") is None


def test_website_tools_open_through_the_browser():
    opened = []
    original = W.webbrowser.open
    W.webbrowser.open = lambda url: opened.append(url) or True
    try:
        ctx = T.ToolContext(lang="fr", strings=STRINGS["fr"])
        tools = {t.name: t for t in T.build_tools(ctx)}
        assert tools["open_website"].invoke({"site": "YouTube"}) == "J'ouvre YouTube."
        answer = tools["search_on_site"].invoke({"query": "lofi", "site": "youtube"})
        assert answer == "Voici les résultats pour lofi sur youtube."
        assert tools["open_website"].invoke({"site": "javascript:alert(1)"}) == \
            STRINGS["fr"]["site_unknown"]
        assert opened == ["https://www.youtube.com",
                          "https://www.youtube.com/results?search_query=lofi"]
    finally:
        W.webbrowser.open = original
