"""Piloter Windows a la voix : fenetres, luminosite, mode nuit, rangement du bureau.

Les titres de fenetres sont lus sur le PC seulement et ne partent jamais au
modele. Fermer une fenetre envoie la demande normale (WM_CLOSE) : une
application avec un travail non enregistre pose sa question habituelle.

Le mode nuit teinte l'ecran par la table de couleurs de la carte graphique :
aucun reglage de Windows n'est modifie, et un redemarrage remet tout a zero.
"""

from __future__ import annotations

import atexit
import os
import re
import subprocess
import sys

from .extras import aligned

BRIGHTNESS_STEP = 20
NIGHT_RGB = (1.0, 0.82, 0.58)        # le bleu baisse, le rouge reste


# --------------------------------------------------------------------------- #
# Fenetres
# --------------------------------------------------------------------------- #
class Windows:
    """Fenetres de premier niveau, sauf celles de Jarvis lui-meme."""

    WM_CLOSE, SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 0x0010, 6, 3, 9

    def __init__(self):
        import ctypes

        self.user32 = ctypes.windll.user32
        self.ctypes = ctypes

    def _title(self, hwnd) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        buffer = self.ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _pid(self, hwnd) -> int:
        from ctypes import wintypes

        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, self.ctypes.byref(pid))
        return pid.value

    def list(self) -> list[tuple[int, str]]:
        """(hwnd, titre) de l'avant vers l'arriere."""
        from ctypes import wintypes

        found: list[tuple[int, str]] = []
        own = os.getpid()
        proto = self.ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _param):
            GW_OWNER, GWL_EXSTYLE, WS_EX_TOOLWINDOW = 4, -20, 0x80
            if not self.user32.IsWindowVisible(hwnd) or self.user32.IsIconic(hwnd):
                return True
            if self.user32.GetWindow(hwnd, GW_OWNER):
                return True
            if self.user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            title = self._title(hwnd)
            if title and title not in ("Program Manager", "Paramètres") and self._pid(hwnd) != own:
                found.append((int(hwnd), title))
            return True

        self.user32.EnumWindows(proto(visit), 0)
        return found

    def find(self, name: str | None = None) -> int | None:
        windows = self.list()
        if not name:
            return windows[0][0] if windows else None
        wanted = aligned(name)[0]
        for hwnd, title in windows:
            if wanted in aligned(title)[0]:
                return hwnd
        return None

    def close(self, hwnd: int) -> None:
        self.user32.PostMessageW(hwnd, self.WM_CLOSE, 0, 0)

    def minimize(self, hwnd: int) -> None:
        self.user32.ShowWindow(hwnd, self.SW_MINIMIZE)

    def maximize(self, hwnd: int) -> None:
        self.user32.ShowWindow(hwnd, self.SW_MAXIMIZE)

    def focus(self, hwnd: int) -> None:
        self.user32.ShowWindow(hwnd, self.SW_RESTORE)
        self.user32.SetForegroundWindow(hwnd)

    def _work_area(self) -> tuple[int, int, int, int]:
        from ctypes import wintypes

        rect = wintypes.RECT()
        self.user32.SystemParametersInfoW(0x0030, 0, self.ctypes.byref(rect), 0)   # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top

    def snap(self, hwnd: int, side: str) -> None:
        left, top, width, height = self._work_area()
        half = width // 2
        self.user32.ShowWindow(hwnd, self.SW_RESTORE)
        self.user32.MoveWindow(hwnd, left if side == "left" else left + half, top, half, height, True)

    def minimize_all(self) -> None:
        from .pc import tap

        self.user32.keybd_event(0x5B, 0, 0, 0)     # Windows + D
        tap(0x44)
        self.user32.keybd_event(0x5B, 0, 2, 0)


_NAME = r"(?: (?:la |le |l'|sur |de |du )?(?P<name>(?!fenetre)[a-z0-9' .-]{2,30}?))?"
_THIS = r"(?: (?:cette|la|ma|this|the|my) (?:fenetre|window))?"
WIN_CLOSE = re.compile(r"^(?:ferme|quitte|close|quit)" + _THIS + r"(?: (?:la |le |l')?(?P<name>[a-z0-9' .-]{2,30}))?$")
WIN_MIN = re.compile(r"^(?:reduis|reduit|minimise|minimize)" + _THIS + r"(?: (?:la |le |l')?(?P<name>(?!tout|les)[a-z0-9' .-]{2,30}))?$")
WIN_MAX = re.compile(r"^(?:agrandis|agrandit|maximise|maximize|plein ecran)" + _THIS + r"(?: (?:la |le |l')?(?P<name>[a-z0-9' .-]{2,30}))?$")
WIN_ALL = re.compile(r"^(?:reduis|reduit|minimise|cache) (?:tout|toutes les fenetres|les fenetres)$|"
                     r"^(?:montre|affiche)(?:-moi| moi)? le bureau$|^(?:minimize all|show (?:the )?desktop)$")
WIN_SNAP = re.compile(r"^(?:mets|met|place|deplace|colle|put|move)(?: (?:cette fenetre|la fenetre|this window|"
                      r"(?:la |le |l')?(?P<name>[a-z0-9' .-]{2,30}?)))? (?:a |sur la |to the |on the )?"
                      r"(?P<side>gauche|droite|left|right)$")
WIN_SIDE = re.compile(r"^(?:mets|met|place|put)(?: les| mes| ces)?(?: deux| 2)?(?: fenetres?| windows?) "
                      r"(?:cote a cote|side by side)$|^(?:cote a cote|side by side)$")
WIN_FOCUS = re.compile(r"^(?:va sur|passe sur|bascule sur|reviens sur|montre(?:-moi)?|switch to|go to) "
                       r"(?:la fenetre |la |le |l')?(?P<name>[a-z0-9' .-]{2,30})$")


def windows_answer(plain: str, lang: str, api=None) -> str | None:
    if not any(p.match(plain) for p in (WIN_CLOSE, WIN_MIN, WIN_MAX, WIN_ALL, WIN_SNAP, WIN_SIDE, WIN_FOCUS)):
        return None
    if plain in ("ferme", "quitte", "close", "quit", "reduis", "reduit", "minimise", "minimize",
                 "agrandis", "agrandit", "maximise", "maximize"):
        return None                     # un verbe seul : phrase coupee, on ne ferme rien
    if api is None:
        if sys.platform != "win32":
            return None
        api = Windows()
    fr = lang == "fr"
    done = "C'est fait." if fr else "Done."
    missing = "Je ne trouve pas cette fenêtre." if fr else "I can't find that window."
    if WIN_ALL.match(plain):
        api.minimize_all()
        return done
    if WIN_SIDE.match(plain):
        windows = api.list()
        if len(windows) < 2:
            return "Il me faut deux fenêtres ouvertes." if fr else "I need two open windows."
        api.snap(windows[0][0], "left")
        api.snap(windows[1][0], "right")
        return done
    match = WIN_SNAP.match(plain)
    if match:
        hwnd = api.find(match.group("name"))
        if hwnd is None:
            return missing if not match.group("name") else None
        api.snap(hwnd, "left" if match.group("side") in ("gauche", "left") else "right")
        return done
    for pattern, action in ((WIN_MIN, api.minimize), (WIN_MAX, api.maximize), (WIN_CLOSE, api.close)):
        match = pattern.match(plain)
        if match:
            name = match.groupdict().get("name")
            hwnd = api.find(name)
            if hwnd is None:
                # « ferme le fichier » n'est pas une fenetre : le modele s'en charge.
                return missing if not name else None
            action(hwnd)
            return done
    match = WIN_FOCUS.match(plain)
    hwnd = api.find(match.group("name"))
    if hwnd is None:
        return None                     # « va sur YouTube » : les autres commandes s'en chargent
    api.focus(hwnd)
    return done


# --------------------------------------------------------------------------- #
# Luminosite et mode nuit
# --------------------------------------------------------------------------- #
def _powershell(script: str) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=8, creationflags=flags)
    if done.returncode:
        raise OSError(done.stderr.strip()[:200])
    return done.stdout.strip()


class Display:
    def __init__(self):
        self._saved = None

    def brightness(self) -> int | None:
        """Luminosite de l'ecran integre ; None pour un ecran externe."""
        try:
            value = _powershell("(Get-CimInstance -Namespace root/WMI -ClassName "
                                "WmiMonitorBrightness -ErrorAction Stop).CurrentBrightness")
            return int(value.split()[0])
        except Exception:
            return None

    def set_brightness(self, percent: int) -> bool:
        percent = min(100, max(0, int(percent)))
        try:
            _powershell("Invoke-CimMethod -InputObject (Get-CimInstance -Namespace root/WMI "
                        "-ClassName WmiMonitorBrightnessMethods -ErrorAction Stop) -MethodName "
                        f"WmiSetBrightness -Arguments @{{Timeout=[uint32]1;Brightness=[byte]{percent}}} "
                        "-ErrorAction Stop | Out-Null")
            return True
        except Exception:
            return False

    def _gamma(self, ramp) -> bool:
        import ctypes

        hdc = ctypes.windll.user32.GetDC(0)
        try:
            return bool(ctypes.windll.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
        finally:
            ctypes.windll.user32.ReleaseDC(0, hdc)

    def night(self, on: bool) -> bool:
        """Teinte chaude de tout l'ecran, ou retour aux couleurs d'avant."""
        import ctypes

        if not on:
            if self._saved is None:
                ramp = night_ramp((1.0, 1.0, 1.0))
            else:
                ramp, self._saved = self._saved, None
            return self._gamma(ramp)
        if self._saved is None:
            saved = (ctypes.c_ushort * 256 * 3)()
            hdc = ctypes.windll.user32.GetDC(0)
            try:
                ctypes.windll.gdi32.GetDeviceGammaRamp(hdc, ctypes.byref(saved))
            finally:
                ctypes.windll.user32.ReleaseDC(0, hdc)
            self._saved = saved
            atexit.register(lambda: self._saved is not None and self.night(False))
        return self._gamma(night_ramp(NIGHT_RGB))


def night_ramp(rgb: tuple[float, float, float]):
    """Table de 3 x 256 valeurs : chaque canal est multiplie par son facteur."""
    import ctypes

    ramp = (ctypes.c_ushort * 256 * 3)()
    for channel, factor in enumerate(rgb):
        for index in range(256):
            ramp[channel][index] = min(65535, int(index * 257 * factor))
    return ramp


LIGHT = r"(?:la |l')?(?:luminosite|brightness|ecran)"
LIGHT_SET = re.compile(r"^(?:mets|met|regle|set)(?: moi)? " + LIGHT + r" (?:a|to) (\d{1,3})(?: ?%| pour ?cent| percent)?$")
LIGHT_UP = re.compile(r"^(?:monte|augmente|increase|raise|turn up) " + LIGHT + r"$|^(?:plus|more) (?:de )?lumin\w+$")
LIGHT_DOWN = re.compile(r"^(?:baisse|diminue|reduis|decrease|lower|turn down) " + LIGHT + r"$|^(?:moins|less) (?:de )?lumin\w+$")
NIGHT_ON = re.compile(r"^(?:(?:active|mets|met|lance|passe en|enable|turn on) )?(?:le )?(?:mode nuit|night mode|filtre (?:de )?lumiere bleue)$")
NIGHT_OFF = re.compile(r"^(?:desactive|enleve|coupe|arrete|retire|quitte|sors du|disable|turn off) (?:le )?"
                       r"(?:mode nuit|night mode|filtre (?:de )?lumiere bleue)$")


def display_answer(plain: str, lang: str, api=None) -> str | None:
    fr = lang == "fr"
    night = True if NIGHT_ON.match(plain) else False if NIGHT_OFF.match(plain) else None
    set_to = LIGHT_SET.match(plain)
    up, down = LIGHT_UP.match(plain), LIGHT_DOWN.match(plain)
    if night is None and not (set_to or up or down):
        return None
    if api is None:
        if sys.platform != "win32":
            return None
        api = _default_display()
    if night is not None:
        if not api.night(night):
            return ("Ta carte graphique refuse le mode nuit." if fr
                    else "Your graphics card refuses night mode.")
        if night:
            return "Mode nuit activé." if fr else "Night mode on."
        return "Mode nuit désactivé." if fr else "Night mode off."
    if set_to:
        target = min(100, int(set_to.group(1)))
    else:
        current = api.brightness()
        if current is None:
            return _no_brightness(fr)
        target = min(100, max(0, current + (BRIGHTNESS_STEP if up else -BRIGHTNESS_STEP)))
    if not api.set_brightness(target):
        return _no_brightness(fr)
    return f"Luminosité à {target} %." if fr else f"Brightness at {target} percent."


def _no_brightness(fr: bool) -> str:
    return ("Je ne peux pas régler la luminosité de cet écran." if fr
            else "I can't change the brightness of this screen.")


_DISPLAY: Display | None = None


def _default_display() -> Display:
    """Une seule instance : c'est elle qui se souvient des couleurs d'origine."""
    global _DISPLAY
    if _DISPLAY is None:
        _DISPLAY = Display()
    return _DISPLAY


# --------------------------------------------------------------------------- #
# Rangement du bureau
# --------------------------------------------------------------------------- #
TIDY = re.compile(r"^(?:range|classe|trie|organise|tidy|sort|organize)(?: moi| -moi|-moi)? (?:(?:les |tous les )?"
                  r"(?:fichiers|elements) (?:de |du |sur )(?:mon |le )?bureau|(?:mon |le )bureau|my desktop|the desktop)"
                  r"(?: (?:par|selon le|d'apres le|by) (?:nom|name)(?: (?:du|des) fichiers?)?)?$")
TIDY_ALL = re.compile(r"^(?:range|classe|trie|organise)(?: moi|-moi)? (?:tout (?:le|mon) bureau|tout sur (?:le|mon) bureau)$|"
                      r"^tidy everything$")
TIDY_FOLDERS = re.compile(r"^(?:range|classe|trie|organise)(?: moi|-moi)?(?: aussi)? (?:les |mes )?dossiers(?: (?:du|de mon|sur le|sur mon) bureau)?$|"
                          r"^(?:tidy|sort) (?:the |my )?folders(?: too)?$")
TIDY_SHORTCUTS = re.compile(r"^(?:range|classe|trie|organise)(?: moi|-moi)?(?: aussi)? (?:les |mes )?(?:raccourcis|icones)(?: (?:du|de mon|sur le|sur mon) bureau)?$|"
                            r"^(?:tidy|sort) (?:the |my )?shortcuts(?: too)?$")
TIDY_AGAIN = re.compile(r"^(?:refais|recommence|ameliore|revois|reprends)(?: le| mon)? (?:rangement|classement)(?: du bureau)?$|"
                        r"^redo the tidy up$")
TIDY_DETAILS = re.compile(r"^(?:detaille|details?|montre|explique|lis)(?:-moi| moi)?(?: le)? (?:rangement|plan)(?: du rangement)?$|"
                          r"^detail the tidy up$")
TIDY_RENAME = re.compile(r"^renomme(?: le)? dossier (?P<old>.{2,40}?) en (?P<new>.{2,40})$|"
                         r"^rename(?: the)? folder (?P<old2>.{2,40}?) (?:to|as) (?P<new2>.{2,40})$")
TIDY_LEAVE = re.compile(r"^(?:laisse|garde)(?: moi)? (?:le |la |les |l'|mon |ma |mes )?(?P<what>.{2,40}?) sur (?:le|mon) bureau$|"
                        r"^ne (?:range|bouge|touche) pas (?:a )?(?:le |la |les |l'|mon |ma |mes )?(?P<what2>.{2,40})$|"
                        r"^leave (?:the |my )?(?P<what3>.{2,40}?) on (?:the|my) desktop$")
TIDY_CONFIRM = re.compile(r"^(?:confirme|valide|fais|lance|confirm|do)(?: le)? (?:rangement|the tidy up|tidy up)$|"
                          r"^(?:oui )?(?:vas-y|fais-le) (?:range|pour le rangement)$")
TIDY_UNDO = re.compile(r"^(?:annule|defais|undo)(?: le)?(?: dernier)? (?:rangement|the tidy up|tidy up)$|"
                       r"^(?:remets|replace|put back) (?:tout |les fichiers )?(?:sur |comme avant sur )?(?:mon |le )?bureau"
                       r"(?: comme avant)?$")


def desktop_answer(plain: str, orig: str, lang: str, organizer=None) -> str | None:
    patterns = (TIDY, TIDY_ALL, TIDY_FOLDERS, TIDY_SHORTCUTS, TIDY_AGAIN, TIDY_DETAILS, TIDY_RENAME,
                TIDY_LEAVE, TIDY_CONFIRM, TIDY_UNDO)
    if not any(pattern.match(plain) for pattern in patterns):
        return None
    from . import desktop

    organizer = organizer or _default_organizer()
    fr = lang == "fr"
    if TIDY.match(plain):
        return desktop.say_plan(organizer.propose(), lang)
    if TIDY_ALL.match(plain):
        return desktop.say_plan(organizer.propose(folders=True, shortcuts=True), lang)
    if TIDY_FOLDERS.match(plain):
        return desktop.say_plan(organizer.propose(folders=True), lang)
    if TIDY_SHORTCUTS.match(plain):
        return desktop.say_plan(organizer.propose(shortcuts=True), lang)
    if TIDY_AGAIN.match(plain):
        return desktop.say_plan(organizer.propose(again=True), lang)
    if TIDY_DETAILS.match(plain):
        return desktop.say_details(organizer.plan(), lang)
    match = TIDY_RENAME.match(plain)
    if match:
        slot = "old" if match.group("old") else "old2"
        target = "new" if slot == "old" else "new2"
        old = match.group(slot)
        new = orig[match.start(target):match.end(target)].strip().capitalize()
        if not organizer.rename(old, new):
            return (f"Je ne trouve pas le dossier {old} dans le plan." if fr
                    else f"I can't find the folder {old} in the plan.")
        return f"D'accord, le dossier s'appellera {new}." if fr else f"All right, the folder will be {new}."
    match = TIDY_LEAVE.match(plain)
    if match:
        what = match.group("what") or match.group("what2") or match.group("what3")
        count = organizer.leave(what)
        if not count:
            return (f"Rien ne correspond à {what} dans le plan." if fr
                    else f"Nothing matches {what} in the plan.")
        return (f"D'accord, je laisse {count} éléments sur le bureau." if fr and count > 1
                else "D'accord, je le laisse sur le bureau." if fr
                else f"All right, leaving {count} item(s) on the desktop.")
    if TIDY_UNDO.match(plain):
        count = organizer.undo()
        if not count:
            return "Il n'y a aucun rangement à annuler." if fr else "There is no tidy up to undo."
        return f"C'est annulé : {count} éléments sont revenus à leur place." if fr \
            else f"Undone: {count} items are back where they were."
    if not organizer.pending():
        return ("Dis d'abord « range mon bureau » pour voir ce que je propose." if fr
                else "First say 'tidy my desktop' to see what I suggest.")
    moved, failed = organizer.apply()
    text = (f"C'est rangé : {moved} éléments dans le dossier {desktop.ROOT_NAME}." if fr
            else f"Done: {moved} items in the {desktop.ROOT_NAME} folder.")
    if failed:
        text += (f" {failed} n'ont pas pu bouger, sans doute ouverts." if fr
                 else f" {failed} could not move, probably open.")
    return text + (" Dis « annule le rangement » pour revenir en arrière." if fr
                   else " Say 'undo the tidy up' to go back.")


_ORGANIZER = None


def _default_organizer():
    global _ORGANIZER
    if _ORGANIZER is None:
        from .desktop import DesktopOrganizer

        _ORGANIZER = DesktopOrganizer()
    return _ORGANIZER


PHONE_PAIR = re.compile(r"^(?:connecte|appaire|relie|active|ouvre|lance|connect|pair)(?: l'acces)?(?: a| de| pour| au)?"
                        r" (?:mon |le |ma |my |the )?(?:telephone|portable|smartphone|phone|mobile)$|"
                        r"^(?:acces|jarvis sur) (?:mon |le )?(?:telephone|portable)$")


def phone_answer(plain: str, lang: str) -> str | None:
    if not PHONE_PAIR.match(plain):
        return None
    from . import phone

    fr = lang == "fr"
    if not phone.open_pairing():
        return ("L'accès téléphone n'a pas pu démarrer." if fr
                else "Phone access could not start.")
    return ("Scanne le QR code affiché sur l'écran avec ton téléphone, sur le même Wi-Fi." if fr
            else "Scan the QR code on screen with your phone, on the same Wi-Fi.")


# La version MVP garde ce qui se montre sans risque : devant une salle, rien ne doit
# deplacer des fichiers, fermer le diaporama ou ouvrir un acces reseau.
MVP_MODE = False
OUTSIDE_MVP = (WIN_CLOSE, WIN_ALL, TIDY, TIDY_ALL, TIDY_FOLDERS, TIDY_SHORTCUTS, TIDY_AGAIN,
               TIDY_CONFIRM, TIDY_UNDO, PHONE_PAIR)


def answer(text: str, lang: str, windows_api=None, display_api=None, organizer=None) -> str | None:
    plain, orig = aligned(text)
    if not plain or len(plain.split()) > 14:
        return None
    if MVP_MODE and any(pattern.match(plain) for pattern in OUTSIDE_MVP):
        return ("Cette commande existe, mais elle est désactivée dans la version de présentation."
                if lang == "fr" else "This command exists, but it is turned off in the demo version.")
    return (desktop_answer(plain, orig, lang, organizer)
            or phone_answer(plain, lang)
            or display_answer(plain, lang, display_api)
            or windows_answer(plain, lang, windows_api))


__all__ = ["answer", "Windows", "Display", "night_ramp"]
