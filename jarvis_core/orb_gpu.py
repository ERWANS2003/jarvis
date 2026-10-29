"""Horizon 6 - rendu « ultra » de l'orbe sur la carte graphique (OpenGL).

Un shader trace, pour chaque pixel, un rayon vers une sphere dont la surface
est deformee par un bruit 3D anime (lancer de rayons sur champ de distance).
On obtient une vraie forme en relief, eclairee :

  * lumiere douce + reflet speculaire ;
  * irisation facon film mince (nacre) qui depend de l'angle de vue ;
  * bords lumineux (effet de Fresnel) et lueur interne ;
  * halo exterieur et fines particules ;
  * bandes de couleur qui defilent (theme plasma).

Le rendu se fait en double resolution puis est reduit (anticrenelage 4x), a
60 images/s sans charger le processeur. Meme interface que les rendus
Pillow : `frame(state, phase, level, hover=, pulse=)`. Si OpenGL n'est pas
disponible, `available()` le dit et l'orbe garde son rendu processeur.
"""

from __future__ import annotations

import math

from . import orb_materials as _materials
from .text import log

VERTEX = """
#version 330
in vec2 pos;
out vec2 uv;
void main() { uv = pos; gl_Position = vec4(pos, 0.0, 1.0); }
"""

FRAGMENT_HEAD = """
#version 330
in vec2 uv;
out vec4 color;

uniform float time;      // temps anime (selon l'etat)
uniform float clock;     // temps reel (levitation, particules)
uniform float level;     // volume de la voix (0..1)
uniform float pulse;     // sursaut (0..1)
uniform float hover;     // survol (0..1)
uniform float ripple;    // amplitude des vagues
uniform float radius;    // rayon de base (unites de l'ecran : 1 = bord)
uniform int   mode;      // matiere : voir orb_materials.MODES
uniform vec3  c0;
uniform vec3  c1;
uniform vec3  c2;
uniform vec3  c3;
uniform vec3  tint;
uniform float tint_part;
uniform float glow;
uniform float fade;
uniform float glass;     // coque de verre (0 = sans, 1 = pleine)

// --- bruit 3D (simplex, Ashima Arts / Stefan Gustavson, domaine public) --- //
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
float snoise(vec3 v) {
    const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
    const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
    vec3 i = floor(v + dot(v, C.yyy));
    vec3 x0 = v - i + dot(i, C.xxx);
    vec3 g = step(x0.yzx, x0.xyz);
    vec3 l = 1.0 - g;
    vec3 i1 = min(g.xyz, l.zxy);
    vec3 i2 = max(g.xyz, l.zxy);
    vec3 x1 = x0 - i1 + C.xxx;
    vec3 x2 = x0 - i2 + C.yyy;
    vec3 x3 = x0 - D.yyy;
    i = mod289(i);
    vec4 p = permute(permute(permute(i.z + vec4(0.0, i1.z, i2.z, 1.0))
             + i.y + vec4(0.0, i1.y, i2.y, 1.0)) + i.x + vec4(0.0, i1.x, i2.x, 1.0));
    float n_ = 0.142857142857;
    vec3 ns = n_ * D.wyz - D.xzx;
    vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
    vec4 x_ = floor(j * ns.z);
    vec4 y_ = floor(j - 7.0 * x_);
    vec4 x = x_ * ns.x + ns.yyyy;
    vec4 y = y_ * ns.x + ns.yyyy;
    vec4 h = 1.0 - abs(x) - abs(y);
    vec4 b0 = vec4(x.xy, y.xy);
    vec4 b1 = vec4(x.zw, y.zw);
    vec4 s0 = floor(b0) * 2.0 + 1.0;
    vec4 s1 = floor(b1) * 2.0 + 1.0;
    vec4 sh = -step(h, vec4(0.0));
    vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
    vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
    vec3 p0 = vec3(a0.xy, h.x);
    vec3 p1 = vec3(a0.zw, h.y);
    vec3 p2 = vec3(a1.xy, h.z);
    vec3 p3 = vec3(a1.zw, h.w);
    vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
    p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
    vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
    m = m * m;
    return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

"""
FRAGMENT = FRAGMENT_HEAD + _materials.GLSL

# Parametres par theme : couleurs (0..1), mode, halo, amplitude des vagues.
def _c(r, g, b):
    return (r / 255.0, g / 255.0, b / 255.0)


GPU_THEMES = {
    "opale": {"colors": (_c(250, 170, 200), _c(176, 156, 255), _c(255, 206, 160), _c(140, 228, 210)),
              "mode": 0, "glow": 0.35, "ripple": 0.075},
    "aurore": {"colors": (_c(80, 226, 248), _c(88, 124, 255), _c(170, 146, 250), _c(112, 196, 255)),
               "mode": 0, "glow": 0.4, "ripple": 0.075},
    "nebuleuse": {"colors": (_c(70, 210, 255), _c(110, 64, 255), _c(220, 70, 220), _c(50, 80, 230)),
                  "mode": 0, "glow": 0.8, "ripple": 0.085},
    "plasma": {"colors": (_c(40, 224, 232), _c(40, 128, 240), _c(150, 96, 232), _c(118, 232, 204)),
               "mode": 1, "glow": 0.5, "ripple": 0.13},
}
# Themes du catalogue (orb_themes) : palettes et matieres (orb_materials).
from . import orb_themes as _catalog  # noqa: E402

_catalog.register(GPU_THEMES, {}, {})

STATE_TINTS = {"listening": (_c(84, 240, 196), 0.28), "thinking": (_c(210, 120, 255), 0.3)}
STATE_SPEED = {"ready": 0.6, "listening": 1.1, "thinking": 1.8, "speaking": 1.3}

_context = None


def available() -> bool:
    """Vrai si un contexte OpenGL 3.3 peut etre cree (carte graphique)."""
    global _context
    try:
        import moderngl  # noqa: F401
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    if _context is None:
        try:
            import moderngl

            _context = moderngl.create_standalone_context()
        except Exception as exc:
            log(f"[orbe] rendu GPU indisponible : {exc}")
            _context = False
    return bool(_context)


class GpuRenderer:
    """Rendu ultra sur la carte graphique, avec anticrenelage 4x."""

    SUPERSAMPLE = 2

    def __init__(self, theme: str = "opale", size: int = 168, radius: int = 42):
        import moderngl
        import numpy as np

        if not available():
            raise RuntimeError("OpenGL indisponible")
        self.theme = theme if theme in GPU_THEMES else "opale"
        self.style = GPU_THEMES[self.theme]
        self.size = int(size)
        self.radius = float(radius) * 1.08 / (self.size / 2)   # en unites d'ecran
        self.ctx = _context
        self.program = self.ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self.vbo = self.ctx.buffer(quad.tobytes())
        self.vao = self.ctx.simple_vertex_array(self.program, self.vbo, "pos")
        big = self.size * self.SUPERSAMPLE
        self.fbo = self.ctx.simple_framebuffer((big, big), components=4)
        self._tint = [(0.0, 0.0, 0.0), 0.0]
        self._moderngl = moderngl
        self.glass = 1.0   # effet verre (reglage de l'orbe)

    def _uniform(self, name, value):
        if name in self.program:
            self.program[name].value = value

    def frame(self, state: str, phase: float, level: float | None = None, *,
              hover: float = 0.0, pulse: float = 0.0, fade: float = 1.0):
        from PIL import Image

        state = state if state in STATE_SPEED else "ready"
        voice = (level or 0.0) if state in ("speaking", "listening") else 0.0
        target, part = STATE_TINTS.get(state, ((0.0, 0.0, 0.0), 0.0))
        current, current_part = self._tint
        self._tint = [tuple(a + (b - a) * 0.12 for a, b in zip(current, target)),
                      current_part + (part - current_part) * 0.12]
        style = self.style
        colors = style["colors"]
        radius = self.radius * (1.0 + 0.025 * math.sin(phase * 1.2)) \
            * (1.0 + 0.07 * voice + 0.10 * pulse + 0.05 * hover)
        ripple = style["ripple"] * (1.0 + 0.8 * voice + 1.2 * pulse
                                    + (0.3 if state == "thinking" else 0.0))
        for name, value in (("time", phase * STATE_SPEED[state]), ("clock", phase),
                            ("level", voice), ("pulse", pulse), ("hover", hover),
                            ("ripple", ripple), ("radius", radius), ("mode", style["mode"]),
                            ("c0", colors[0]), ("c1", colors[1]), ("c2", colors[2]),
                            ("c3", colors[3]), ("tint", self._tint[0]),
                            ("tint_part", self._tint[1]), ("glow", style["glow"]),
                            ("fade", fade), ("glass", float(self.glass))):
            self._uniform(name, value)
        self.fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)
        self.vao.render(self._moderngl.TRIANGLE_STRIP)
        big = self.size * self.SUPERSAMPLE
        image = Image.frombytes("RGBA", (big, big), self.fbo.read(components=4))
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        return image.reduce(self.SUPERSAMPLE)


_previews: dict = {}
_preview_renderers: dict = {}


def preview(theme: str, size: int):
    """Petite image 3D d'un theme (pastilles du menu), gardee en cache."""
    key = (theme, int(size))
    if key not in _previews:
        renderer = _preview_renderers.get(int(size))
        if renderer is None:
            renderer = GpuRenderer("opale", int(size), max(4, round(size * 0.34)))
            _preview_renderers[int(size)] = renderer
        renderer.theme = theme if theme in GPU_THEMES else "opale"
        renderer.style = GPU_THEMES[renderer.theme]
        renderer._tint = [(0.0, 0.0, 0.0), 0.0]
        _previews[key] = renderer.frame("ready", 3.2)
    return _previews[key]


__all__ = ["GpuRenderer", "GPU_THEMES", "available", "preview"]
