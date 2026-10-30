"""Tests : plusieurs demandes, corrections, fenetres, ecran, bureau, previsions, humeurs, telephone.

Aucune vraie fenetre, aucun vrai reglage d'ecran, aucun fichier du vrai bureau.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from jarvis_core import corrections as C
from jarvis_core import desktop as D
from jarvis_core import extras as X
from jarvis_core import hearing as H
from jarvis_core import intents as I
from jarvis_core import orb_mood as M
from jarvis_core import phone as P
from jarvis_core import pilot
from jarvis_core import proactive
from jarvis_core import tts
from jarvis_core import vad


# -- plusieurs demandes ------------------------------------------------------ #
def test_several_requests_in_one_sentence():
    known = {"mets pause": "pause", "ouvre youtube": "youtube", "ouvre spotify": "spotify"}
    ask = lambda text: known.get(text.lower())    # noqa: E731
    assert I.quick_many("Mets pause et ouvre YouTube", ask) == (["pause", "youtube"], None)
    assert I.quick_many("Ouvre YouTube et Spotify", ask) == (["youtube", "spotify"], None)
    assert I.quick_many("mets pause puis raconte une blague", ask) == (["pause"], "raconte une blague")
    # La premiere n'est pas une commande : rien n'est execute.
    assert I.quick_many("le lien entre Paris et ouvre YouTube", ask) == ([], None)
    assert I.quick_many("mets pause", ask) == ([], None)


# -- corrections ------------------------------------------------------------- #
def test_corrections_replay_and_learn_only_lookalikes():
    path = Path(tempfile.mkdtemp()) / "c.json"
    fixes = C.Corrections(path)
    fix = fixes.handle("Non, je voulais dire Ouedraogo", "appelle Wedrogo demain")
    assert fix == {"replay": "appelle Ouedraogo demain"}
    assert C.Corrections(path).apply("écris à wedrogo") == "écris à Ouedraogo"
    # Changement d'avis : la phrase est rejouee, rien n'est retenu.
    fixes = C.Corrections(Path(tempfile.mkdtemp()) / "c.json")
    assert fixes.handle("non je voulais dire Paris", "la météo à Lyon")["replay"] == "Paris"
    assert fixes.rules == {}
    assert fixes.handle("bonjour", "la météo à Lyon") is None


def test_explicit_correction_rule_and_forget():
    fixes = C.Corrections(Path(tempfile.mkdtemp()) / "c.json")
    assert fixes.handle("Quand je dis Polo, je veux dire Paul", None)["answer"].startswith("Compris")
    assert fixes.apply("appelle polo") == "appelle Paul"
    assert "1 corrections" in fixes.handle("oublie tes corrections", None)["answer"]
    assert fixes.apply("appelle polo") == "appelle polo"


# -- fenetres ---------------------------------------------------------------- #
class FakeWindows:
    def __init__(self):
        self.calls = []
        self.windows = [(1, "Bloc-notes"), (2, "YouTube - Chrome")]

    def list(self):
        return self.windows

    def find(self, name=None):
        if not name:
            return self.windows[0][0] if self.windows else None
        return next((h for h, t in self.windows if name in t.lower()), None)

    def __getattr__(self, name):
        return lambda *a: self.calls.append((name, *a))


def _win(text):
    api = FakeWindows()
    return pilot.answer(text, "fr", windows_api=api), api.calls


def test_window_commands():
    assert _win("Ferme cette fenêtre") == ("C'est fait.", [("close", 1)])
    assert _win("ferme chrome") == ("C'est fait.", [("close", 2)])
    assert _win("réduis la fenêtre") == ("C'est fait.", [("minimize", 1)])
    assert _win("agrandis chrome") == ("C'est fait.", [("maximize", 2)])
    assert _win("mets cette fenêtre à gauche") == ("C'est fait.", [("snap", 1, "left")])
    assert _win("mets les fenêtres côte à côte")[1] == [("snap", 1, "left"), ("snap", 2, "right")]
    assert _win("réduis tout")[1] == [("minimize_all",)]
    assert _win("va sur chrome")[1] == [("focus", 2)]


def test_window_commands_never_guess():
    assert _win("ferme") == (None, [])                  # verbe seul : phrase coupee
    assert _win("ferme la porte") == (None, [])         # aucune fenetre de ce nom
    assert _win("mets le son à droite") == (None, [])


# -- ecran ------------------------------------------------------------------- #
class FakeDisplay:
    def __init__(self, level=50, ok=True):
        self.level, self.ok, self.night_state = level, ok, None

    def brightness(self):
        return self.level

    def set_brightness(self, percent):
        self.level = percent
        return self.ok

    def night(self, on):
        self.night_state = on
        return self.ok


def test_brightness_and_night_mode():
    api = FakeDisplay()
    ask = lambda text: pilot.answer(text, "fr", display_api=api)    # noqa: E731
    assert ask("mets la luminosité à 40 %") == "Luminosité à 40 %."
    assert ask("baisse la luminosité") == "Luminosité à 20 %."
    assert ask("monte la luminosité") == "Luminosité à 40 %."
    assert ask("active le mode nuit") == "Mode nuit activé."
    assert api.night_state is True
    assert ask("désactive le mode nuit") == "Mode nuit désactivé."
    assert api.night_state is False
    assert pilot.answer("baisse la luminosité", "fr", display_api=FakeDisplay(ok=False)) == \
        "Je ne peux pas régler la luminosité de cet écran."


def test_night_ramp_lowers_blue_only():
    ramp = pilot.night_ramp(pilot.NIGHT_RGB)
    assert ramp[0][255] == 65535 and ramp[2][255] < ramp[1][255] < ramp[0][255]
    assert pilot.night_ramp((1.0, 1.0, 1.0))[2][255] == 65535


# -- bureau ------------------------------------------------------------------ #
def _desktop():
    folder = Path(tempfile.mkdtemp())
    for name in ("Facture_EDF_2026.pdf", "facture-orange.pdf", "CV Erwan.docx", "vacances_01.jpg",
                 "vacances_02.jpg", "unique.txt", "Chrome.lnk", "desktop.ini"):
        (folder / name).write_text(name, encoding="utf-8")
    (folder / "Projet").mkdir()
    return folder


def test_plan_reads_names_and_moves_nothing():
    folder = _desktop()
    before = sorted(p.name for p in folder.iterdir())
    plan = D.make_plan(folder)
    assert plan["Factures"] == ["Facture_EDF_2026.pdf", "facture-orange.pdf"]
    assert plan["CV et emploi"] == ["CV Erwan.docx"]
    assert plan["Vacances"] == ["vacances_01.jpg", "vacances_02.jpg"]
    assert "unique.txt" not in sum(plan.values(), [])
    assert sorted(p.name for p in folder.iterdir()) == before


def test_tidy_needs_confirmation_and_can_be_undone():
    folder = _desktop()
    org = D.DesktopOrganizer(folder, folder.parent / f"undo-{folder.name}.json")
    ask = lambda text: pilot.answer(text, "fr", organizer=org)    # noqa: E731
    assert ask("confirme le rangement").startswith("Dis d'abord")
    assert (folder / "unique.txt").exists() and (folder / "vacances_01.jpg").exists()
    assert ask("Range mon bureau selon le nom des fichiers").startswith("Je propose de ranger 5 fichiers")
    assert (folder / "vacances_01.jpg").exists()              # rien n'a bouge
    assert ask("confirme le rangement").startswith("C'est rangé : 5 fichiers")
    assert (folder / D.ROOT_NAME / "Vacances" / "vacances_01.jpg").exists()
    assert (folder / "Chrome.lnk").exists() and (folder / "Projet").is_dir()
    assert (folder / "unique.txt").exists()
    assert ask("annule le rangement").startswith("C'est annulé : 5 fichiers")
    assert (folder / "vacances_01.jpg").exists() and not (folder / D.ROOT_NAME).exists()


def test_tidy_never_overwrites():
    folder = _desktop()
    target = folder / D.ROOT_NAME / "Factures"
    target.mkdir(parents=True)
    (target / "facture-orange.pdf").write_text("ancien", encoding="utf-8")
    org = D.DesktopOrganizer(folder, folder.parent / f"undo-{folder.name}.json")
    org.propose()
    org.apply()
    assert (target / "facture-orange.pdf").read_text(encoding="utf-8") == "ancien"
    assert (target / "facture-orange (2).pdf").read_text(encoding="utf-8") == "facture-orange.pdf"


# -- previsions -------------------------------------------------------------- #
def _forecast(city, lang, offset):
    return {"city": city.title(), "code": 63, "max": 12.4, "min": 5.6, "rain": 70, "wind": 20}


def _meteo(text):
    return X.answer(text, "fr", dt.datetime(2026, 10, 30, 9, 0), home_city="Lyon", forecast_fn=_forecast)


def test_forecast_and_rain_questions():
    assert _meteo("Quel temps fera-t-il demain ?") == \
        "Demain à Lyon : pluie modérée, de 6 à 12 degrés, 70 % de risque de pluie."
    assert _meteo("la météo de demain à Marseille").startswith("Demain à Marseille")
    assert _meteo("Est-ce qu'il va pleuvoir demain ?") == \
        "Oui, c'est probable demain à Lyon : 70 % de risque de pluie."
    assert _meteo("faut-il un parapluie").startswith("Oui, c'est probable aujourd'hui")


def test_evening_alert_once_a_day_and_only_if_useful():
    sent = []
    watcher = proactive.Watcher("fr", lambda text, speak: sent.append(text), city=lambda: "Lyon",
                                sensors={"battery": lambda: None, "idle": lambda: 0.0,
                                         "rain": lambda c: False, "tomorrow": lambda c: "Demain, orage."})
    evening = dt.datetime(2026, 10, 30, 19, 0)
    assert watcher.check(now=1.0, clock=evening) == ["Demain, orage."]
    assert watcher.check(now=2.0, clock=evening) == []
    assert X.tomorrow_alert({"city": "Lyon", "code": 3, "max": 15, "min": 5, "rain": 10, "wind": 10}, "fr") is None
    assert "gel" in X.tomorrow_alert({"city": "Lyon", "code": 3, "max": 2, "min": -4, "rain": 0, "wind": 0}, "fr")


# -- voix -------------------------------------------------------------------- #
def test_whisper_requests_and_gain():
    assert I.whisper_request("Chuchote") is True
    assert I.whisper_request("parle plus bas") is True
    assert I.whisper_request("Parle normalement") is False
    assert I.whisper_request("baisse le son") is None

    class Engine:
        volume = 1.0

    engine = Engine()
    tts.apply_gain(engine, tts.WHISPER_GAIN)
    assert engine.volume == tts.WHISPER_GAIN
    tts.apply_gain(engine, 1.0)
    assert engine.volume == 1.0


def test_noise_floor_follows_the_room():
    detector = vad.EnergyVAD(vad.VADConfig())
    loud = (b"\x00\x10" * 240)                # bruit continu de type television
    before = detector.is_speech(loud)
    for _ in range(40):
        detector.adapt(loud)
    assert before is True and detector.is_speech(loud) is False
    assert detector.is_speech(b"\x00\x40" * 240) is True   # une voix proche passe encore


def test_language_guidance():
    assert H.language_line(H.Heard("hello", language="en"), "fr").startswith("The user just spoke English")
    assert H.language_line(H.Heard("bonjour", language="fr"), "fr") == ""
    assert H.spoken_language(None, "fr") == "fr"


# -- humeurs ----------------------------------------------------------------- #
def test_mood_tints():
    assert M.tint_for(12) == ((255, 255, 255), 0.0)
    assert M.tint_for(22)[1] > 0 and M.tint_for(18)[0] != M.tint_for(22)[0]
    assert M.tint_for(12, "rain")[1] > 0
    assert M.weather_kind(95) == "storm" and M.weather_kind(63) == "rain" and M.weather_kind(0) == "sun"

    from PIL import Image

    image = Image.new("RGBA", (4, 4), (100, 100, 100, 77))
    tinted = M.apply_tint(image, (255, 0, 0), 0.5)
    assert tinted.getpixel((0, 0))[3] == 77 and tinted.getpixel((0, 0))[0] > 100
    assert M.apply_tint(image, (255, 0, 0), 0.0) is image


# -- telephone --------------------------------------------------------------- #
def _post(port, text, key):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/ask", method="POST",
                                     data=json.dumps({"text": text}).encode("utf-8"),
                                     headers={"X-Jarvis-Key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def test_phone_requires_the_key():
    key = "k" * 32
    server, port = P.start(lambda text: f"écho {text}", port=18766, key=key, host="127.0.0.1")
    try:
        assert _post(port, "salut", key) == (200, {"reply": "écho salut"})
        assert _post(port, "salut", "mauvaise")[0] == 403
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as response:
            assert key not in response.read().decode("utf-8")     # la page ne contient pas la cle
    finally:
        server.shutdown()
        server.server_close()


def test_phone_refuses_public_addresses():
    assert P.is_local_client("192.168.1.20") and P.is_local_client("10.0.0.3")
    assert P.is_local_client("127.0.0.1")
    assert not P.is_local_client("8.8.8.8")


def test_phone_conversation_is_separate_and_silent():
    calls = []

    def turn(text, history, on_sentence, on_tool, on_status):
        calls.append(text)
        on_sentence("Bonjour.")
        on_sentence("Ça va ?")

    bridge = P.PhoneBridge(None, {}, None, turn=turn)
    assert bridge.ask("salut") == "Bonjour. Ça va ?"
    assert calls == ["salut"]
