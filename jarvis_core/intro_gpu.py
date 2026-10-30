"""Intros de demarrage sur la carte graphique : de la vraie lumiere autour de l'orbe.

Meme fenetre transparente et memes styles que `cinematic.Painter`, qui reste le
repli sans carte graphique. Tout est dessine par un shader : halos, trainees,
ondes de choc a dispersion chromatique, particules en 3D. Rien n'est plein ecran,
et les bords de la fenetre sont toujours entierement transparents.

Le texte (console, « JARVIS ») est trace par PIL, avec son propre halo, par-dessus.
"""

from __future__ import annotations

import colorsys

from . import cinematic

ORB_REACH = 0.17          # rayon visible de l'orbe, en unites de la fenetre (1 = bord)
MODES = {style: index for index, style in enumerate(cinematic.STYLES)}

VERTEX = """
#version 330
in vec2 pos;
out vec2 uv;
void main() { uv = pos; gl_Position = vec4(pos, 0.0, 1.0); }
"""

FRAGMENT = """
#version 330
in vec2 uv;
out vec4 color;
uniform float t;
uniform float fade;
uniform float R;
uniform int mode;
uniform vec3 c1;       // couleur du theme
uniform vec3 c2;       // sa voisine sur le cercle des couleurs
uniform vec4 panel;    // console : x, y, demi-largeur, demi-hauteur

const float TAU = 6.2831853;
float hash(float n) { return fract(sin(n * 12.9898) * 43758.5453); }
float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash2(i), hash2(i + vec2(1, 0)), f.x),
               mix(hash2(i + vec2(0, 1)), hash2(i + vec2(1, 1)), f.x), f.y);
}
float fbm(vec2 p) { return 0.5 * noise(p) + 0.3 * noise(p * 2.1) + 0.2 * noise(p * 4.3); }
float ease(float x) { x = clamp(x, 0.0, 1.0); return 1.0 - pow(1.0 - x, 3.0); }
float bump(float x, float a, float b) { return smoothstep(a, (a + b) * 0.5, x) * smoothstep(b, (a + b) * 0.5, x); }
// Un trait net et son halo : d = distance au trait.
float neon(float d, float w) { return smoothstep(w, w * 0.25, d) * 1.5 + 0.35 * pow(w * 1.5 / (d + w * 1.5), 2.0); }
float arcOf(float a, float start, float extent) {
    float d = mod(a - start, TAU);
    return smoothstep(0.0, 0.015, d) * smoothstep(extent, extent - 0.015, d) * (0.15 + 0.85 * d / extent);
}

vec3 anneaux(vec2 p, float l, float a) {
    float open = ease(t / 0.8) * (1.0 - ease((t - 1.75) / 0.7));
    vec3 col = vec3(0.0);
    for (int i = 0; i < 4; i++) {
        float fi = float(i);
        float s = 1.25 + fi * 0.33;
        float r = R * 1.1 * (1.0 + (s - 1.0) * 1.7 * open);
        float speed = (i % 2 == 0 ? 1.0 : -1.0) * (2.4 - fi * 0.45);
        float extent = (i == 2) ? 1.9 : (i == 1 ? 3.0 : (i == 3 ? 4.9 : 4.4));
        float w = (i == 2 ? 0.0075 : 0.0032);
        float m = arcOf(a, t * speed + fi * 1.1, extent) + arcOf(a, t * speed + fi * 1.1 + 3.6, 0.45);
        col += mix(c1, c2, fi / 3.0) * m * neon(abs(l - r), w) * (0.5 + 0.5 * open);
    }
    float r2 = R * 1.1 * (1.0 + 1.95 * open);
    float tk = fract(a / TAU * 72.0 + t * 0.35);
    float major = step(0.5, fract((a / TAU * 72.0 + t * 0.35) / 12.0 + 0.04) * 2.0 - 1.0 + 0.92);
    float h = mix(0.008, 0.02, major);
    col += c1 * 0.9 * smoothstep(0.2, 0.02, abs(tk - 0.5)) * smoothstep(h, h * 0.7, abs(l - r2 + h)) * open;
    float sweep = pow(0.5 + 0.5 * cos(a - t * 3.0), 18.0);          // balayage lumineux
    col += mix(c1, vec3(1.0), 0.4) * sweep * neon(abs(l - r2), 0.002) * open;
    float close = bump(t, 1.95, 2.55);                               // tout se referme : eclair
    col += mix(c1, vec3(1.0), 0.6) * close * 0.0012 / (pow(l - R * 1.05, 2.0) + 0.0012);
    return col + c1 * 0.3 * open * R * R / (l * l + 0.01);
}

vec3 wave(float l, float a, float start, vec3 tint) {
    float x = (t - start) / 1.5;
    if (x <= 0.0 || x >= 1.0) return vec3(0.0);
    float r = R * (1.05 + 4.3 * ease(x));
    float wob = 0.012 * (fbm(vec2(a * 3.0, t * 2.0 + start * 9.0)) - 0.5);
    float w = mix(0.012, 0.0025, x);
    float front = l - r + wob;
    vec3 band;
    band.r = neon(abs(front - 0.006 * (1.0 - x)), w);                // dispersion chromatique
    band.g = neon(abs(front), w);
    band.b = neon(abs(front + 0.006 * (1.0 - x)), w);
    float wake = smoothstep(-0.14, 0.0, front) * step(front, 0.0) * 0.28;   // sillage
    float sparks = smoothstep(0.82, 1.0, noise(vec2(a * 18.0, start * 13.0))) * bump(front, -0.03, 0.01) * 2.2;
    return (band * mix(tint, vec3(1.0), 0.25) + tint * wake + mix(tint, vec3(1.0), 0.6) * sparks) * pow(1.0 - x, 1.4);
}
vec3 onde(vec2 p, float l, float a) {
    vec3 col = wave(l, a, 0.0, c1) + wave(l, a, 0.42, mix(c1, c2, 0.5)) + wave(l, a, 0.84, c2);
    float swell = bump(t, 0.0, 1.5);
    return col + c1 * 0.3 * swell * R * R / (l * l + 0.01);
}

vec3 constellation(vec2 p, float l, float a) {
    float gather = ease(t / 2.05);
    vec3 col = vec3(0.0);
    // Une nebuleuse tourbillonne et se resserre.
    vec2 q = vec2(log(l + 0.03) * 2.2 + t * 0.5, a * 2.0 / TAU * 3.0 + l * 4.0 - t * 0.9);
    float cloud = pow(fbm(q * 2.3), 2.4) * 2.6;
    float zone = smoothstep(1.0 - 0.5 * gather, R, l) * smoothstep(R * 0.7, R * 1.3, l);
    col += mix(c2, c1, cloud) * cloud * zone * 0.4 * (1.0 - gather * 0.5);
    for (int i = 0; i < 64; i++) {
        float fi = float(i);
        float ang = hash(fi) * TAU, dist = 0.45 + 0.55 * hash(fi + 40.0);
        float spin = 0.7 + 1.0 * hash(fi + 80.0), tilt = 0.45 + 0.55 * hash(fi + 120.0);
        float delay = hash(fi + 160.0) * 0.35;
        float g = ease((t - delay) / (2.05 - delay));
        float w = t * spin * (1.6 + 2.8 * g);
        float reach = R * 1.05 + (0.8 * dist) * (1.0 - g);
        vec2 s = vec2(cos(ang + w), sin(ang + w) * tilt) * reach;
        float wb = (t - 0.022) * spin * (1.6 + 2.8 * g);
        vec2 s0 = vec2(cos(ang + wb), sin(ang + wb) * tilt) * reach;
        vec2 ba = s0 - s, pa = p - s;
        float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-5), 0.0, 1.0);
        float d = length(pa - ba * h);                              // trainee de l'etoile
        float depth = 0.55 + 0.45 * sin(ang + w);
        float size = (0.0016 + 0.0026 * hash(fi + 200.0)) * (0.5 + depth);
        col += mix(c1, vec3(1.0), 0.5 + 0.4 * hash(fi + 240.0)) * (size * size / (d * d + size * size * 0.25))
             * depth * (0.45 + 0.55 * (1.0 - h));
    }
    float impact = bump(t, 1.95, 2.55);
    col += mix(c1, vec3(1.0), 0.65) * impact * (0.0011 / (pow(l - R * 1.05 - (t - 1.95) * 0.16, 2.0) + 0.0009));
    return col + c1 * impact * 0.9 * R * R / (l * l + 0.008);
}

vec3 radar(vec2 p, float l, float a) {
    float big = R * 4.6;
    float sweep = TAU * clamp(t / 1.95, 0.0, 1.0);
    vec3 col = vec3(0.0);
    float inside = smoothstep(big, big - 0.004, l);
    col += c1 * neon(abs(l - big), 0.0028) * 0.8;
    for (int i = 1; i < 4; i++) {
        col += c1 * 0.2 * neon(abs(l - big * float(i) * 0.25), 0.0016);
    }
    vec2 ap = abs(p);
    float cross_ = min(ap.x, ap.y);
    col += c1 * 0.14 * smoothstep(0.0018, 0.0006, cross_) * inside;
    float grid = smoothstep(0.03, 0.0, abs(fract(a / TAU * 72.0) - 0.5)) * bump(l, big - 0.02, big);
    col += c1 * 0.6 * grid;
    float behind = mod(sweep - a, TAU);
    float trail = exp(-behind * 2.4) * inside * step(behind, sweep + 0.001);
    col += mix(c1, c2, behind / TAU) * trail * 0.55 * (0.72 + 0.28 * fbm(vec2(l * 26.0, a * 8.0)));
    float beam = smoothstep(0.03, 0.0, min(behind, TAU - behind)) * inside * 1.6;
    col += mix(c1, vec3(1.0), 0.6) * beam;
    for (int i = 0; i < 9; i++) {                                    // echos reperes par le balayage
        float fi = float(i);
        float ba = hash(fi + 3.0) * TAU;
        float br = R * 1.5 + (big - R * 1.7) * hash(fi + 17.0);
        vec2 b = vec2(cos(ba), sin(ba)) * br;
        float age = mod(sweep - ba, TAU);
        float lit = step(ba, sweep) * exp(-age * 1.1);
        float d = length(p - b);
        col += mix(c1, vec3(1.0), 0.5) * lit * (0.00006 / (d * d + 0.00002)) * 0.5;
        col += c1 * lit * neon(abs(d - age * 0.016), 0.0014) * 0.45 * step(age, 1.8);
    }
    float flash = bump(t, 1.9, 2.55);
    col += mix(c1, vec3(1.0), 0.6) * flash * 0.0011 / (pow(l - big * (0.3 + 0.75 * smoothstep(1.9, 2.55, t)), 2.0) + 0.0009);
    return col;
}

float petal(float a, float l, float n, float spin, float len, float fat) {
    float x = mod(a + spin, TAU / n) - TAU / n * 0.5;
    float px = l * cos(x), py = l * sin(x);                          // repere du petale
    float u = clamp(px / len, 0.0, 1.0);
    return abs(py) - fat * pow(sin(3.14159 * u), 0.8) * (1.0 - 0.28 * u) + (px > len || px < 0.0 ? 1.0 : 0.0);
}
vec3 eclosion(vec2 p, float l, float a) {
    float bloom = ease(t / 1.05) * (1.0 - ease((t - 1.65) / 0.85));
    vec3 col = vec3(0.0);
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float len = R * (1.0 + (1.7 + 0.72 * fi) * bloom);
        float fat = R * (0.1 + 0.26 * bloom) * (1.0 - fi * 0.14);
        float spin = t * (0.4 - fi * 0.13) + fi * 0.26;
        float d = petal(a, l, 8.0 + fi * 0.0, spin, len, fat);
        float rim = neon(abs(d), 0.0028);
        float body = smoothstep(0.004, -0.05, d) * 0.3;
        float veins = 0.65 + 0.35 * sin(l * 110.0 - t * 5.0);
        vec3 hue = mix(c1, c2, 0.5 + 0.5 * sin(l * 15.0 - t * 2.0 + fi * 1.8));   // irise
        col += hue * (rim + body * veins) * (1.0 - fi * 0.22);
    }
    for (int i = 0; i < 26; i++) {                                   // pollen de lumiere
        float fi = float(i);
        float ang = hash(fi + 7.0) * TAU + t * 0.3;
        float life = fract(t * (0.34 + 0.2 * hash(fi + 2.0)) + hash(fi + 9.0));
        vec2 s = vec2(cos(ang), sin(ang)) * R * (1.1 + 3.6 * life * bloom);
        float d = length(p - s);
        float size = 0.0024 * (1.0 - life);
        col += mix(c1, vec3(1.0), 0.6) * (size * size / (d * d + size * size * 0.3)) * bloom;
    }
    return col + c1 * 0.5 * bloom * R * R / (l * l + 0.01);
}

vec3 terminal(vec2 p) {
    vec2 q = abs(p - panel.xy) - panel.zw;
    float box = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - 0.012;
    float appear = ease(t / 0.45);
    float inside = smoothstep(0.002, -0.002, box);
    vec2 local = (p - panel.xy) / panel.zw;
    vec3 col = vec3(0.012, 0.022, 0.04) * inside * 2.0;
    float scan = 0.5 + 0.5 * sin(p.y * 620.0);                       // balayage de l'ecran
    col += c1 * inside * 0.03 * scan;
    col += c1 * inside * 0.14 * pow(max(0.0, 1.0 - abs(local.y - (fract(t * 0.55) * 2.6 - 1.3)) * 3.0), 3.0);
    col += c1 * neon(abs(box), 0.0024) * 0.7;
    col += c1 * 0.1 * smoothstep(0.1, 0.0, box) * (1.0 - inside);    // lueur autour
    float bracket = step(max(abs(local.x), abs(local.y)), 2.0) * step(0.9, abs(local.x)) * step(0.72, abs(local.y));
    col += mix(c1, vec3(1.0), 0.5) * bracket * smoothstep(0.003, 0.0, abs(box)) * 1.2;   // coins vifs
    float noiseBand = step(0.985, noise(vec2(p.y * 80.0, floor(t * 22.0)))) * inside * 0.1;
    return (col + c1 * noiseBand) * appear;
}

vec3 minimal(vec2 p, float l, float a) {
    float y = -R * 2.05;
    float spread = ease(t / 1.2);
    float dy = abs(p.y - y);
    float dx = abs(p.x);
    // Reflet anamorphique, comme une lentille de cinema.
    float streak = exp(-dy * 95.0) * smoothstep(0.82 * spread + 0.001, 0.0, dx) * 1.3;
    vec3 col = mix(c1, c2, 0.4) * streak;
    col += mix(c1, vec3(1.0), 0.8) * exp(-dy * 620.0) * smoothstep(0.62 * spread + 0.001, 0.0, dx);
    float head = -0.68 + 1.36 * ease(t / 1.45);                      // point lumineux qui ecrit
    float d = length(p - vec2(head, y));
    col += mix(c1, vec3(1.0), 0.7) * 0.0012 / (d * d + 0.0007) * (1.0 - smoothstep(1.1, 1.6, t));
    for (int i = 0; i < 18; i++) {                                   // poussiere qui s'en echappe
        float fi = float(i);
        float born = hash(fi + 1.0) * 1.3;
        float age = t - born;
        if (age < 0.0 || age > 1.1) continue;
        vec2 s = vec2(-0.68 + 1.36 * ease(born / 1.45) + (hash(fi + 5.0) - 0.5) * 0.12 * age,
                      y - 0.22 * age * hash(fi + 8.0) + 0.09 * age);
        float dd = length(p - s);
        float size = 0.0022 * (1.0 - age / 1.1);
        col += mix(c1, vec3(1.0), 0.6) * size * size / (dd * dd + size * size * 0.3);
    }
    return col;
}

void main() {
    vec2 p = uv;
    float l = length(p);
    float a = mod(atan(p.x, p.y), TAU);                              // 0 en haut, sens horaire
    vec3 c;
    if (mode == 0) c = anneaux(p, l, a);
    else if (mode == 1) c = onde(p, l, a);
    else if (mode == 2) c = constellation(p, l, a);
    else if (mode == 3) c = radar(p, l, a);
    else if (mode == 4) c = eclosion(p, l, a);
    else if (mode == 5) c = terminal(p);
    else c = minimal(p, l, a);
    if (mode != 5 && mode != 6) c *= smoothstep(R * 0.9, R * 1.04, l);   // l'orbe reste nette
    c *= fade;
    c *= smoothstep(1.0, 0.8, l);                                    // jamais de coupure au bord
    c = 1.0 - exp(-c * 1.5);                                         // lumiere douce, sans aplat
    float alpha = max(max(c.r, c.g), c.b);
    float dither = (hash2(p * 917.0 + t) - 0.5) / 255.0;             // pas de bandes dans les halos
    alpha = clamp(pow(alpha, 0.82) + dither, 0.0, 1.0);
    if (mode == 5) {
        vec2 q = abs(p - panel.xy) - panel.zw;
        float box = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - 0.012;
        alpha = max(alpha, smoothstep(0.002, -0.002, box) * 0.82 * fade * ease(t / 0.45));
    }
    color = vec4(c / max(alpha, 0.004), alpha);
    color.rgb = clamp(color.rgb, 0.0, 1.0);
}
"""


def _neighbour(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    """Une couleur voisine de l'accent : donne de la profondeur sans changer le theme."""
    h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    return colorsys.hsv_to_rgb((h + 0.09) % 1.0, min(1.0, s * 0.85 + 0.1), min(1.0, v * 1.05))


class GpuPainter(cinematic.Painter):
    """Meme interface que `cinematic.Painter`, dessin sur la carte graphique."""

    def __init__(self, style, size, orb, accent, lang="fr", lines=None):
        super().__init__(style, size, orb, accent, lang, lines)
        import moderngl
        import numpy as np

        from . import orb_gpu

        if not orb_gpu.available():
            raise RuntimeError("OpenGL indisponible")
        self.ctx = orb_gpu._context
        self._moderngl = moderngl
        self.program = self.ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self.vbo = self.ctx.buffer(quad.tobytes())
        self.vao = self.ctx.simple_vertex_array(self.program, self.vbo, "pos")
        self.fbo = self.ctx.simple_framebuffer((self.size, self.size), components=4)
        self.zoom = self.size / 571.0            # textes a l'echelle de l'ecran
        self._set("R", ORB_REACH)
        self._set("mode", MODES[self.style])
        self._set("c1", tuple(c / 255 for c in self.accent))
        self._set("c2", _neighbour(self.accent))
        self.panel = self._panel_box()
        self._set("panel", self.panel)
        self._text_cache: dict = {}

    def _set(self, name, value) -> None:
        if name in self.program:
            self.program[name].value = value

    def _panel_box(self) -> tuple[float, float, float, float]:
        """Console : au-dessus de l'orbe (x, y, demi-largeur, demi-hauteur en unites shader)."""
        step = 15 * self.zoom / (self.size / 2)
        half_h = (len(self.lines) * step + 24 * self.zoom / (self.size / 2)) / 2
        half_w = 0.74
        bottom = ORB_REACH * 1.25
        top_limit = 0.84 - half_h
        return 0.0, min(bottom + half_h, top_limit), half_w, half_h

    def frame(self, t: float):
        from PIL import Image

        fade = min(1.0, t / 0.25) * min(1.0, max(0.0, (cinematic.DURATION - t) / cinematic.FADE))
        self._set("t", float(t))
        self._set("fade", float(fade))
        self.fbo.use()
        self.ctx.disable(self._moderngl.BLEND)
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)
        self.vao.render(self._moderngl.TRIANGLE_STRIP)
        image = Image.frombytes("RGBA", (self.size, self.size), self.fbo.read(components=4))
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
        self._text(image, t, fade)
        return image

    # -- texte ---------------------------------------------------------------- #
    def _glow_text(self, image, position, text, font, alpha, light=0.75) -> None:
        """Trace `text` avec un halo (image du texte mise en cache)."""
        from PIL import Image, ImageDraw, ImageFilter

        if not text or alpha <= 0.01:
            return
        key = (text, id(font), light)
        layer = self._text_cache.get(key)
        if layer is None:
            box = ImageDraw.Draw(image).textbbox((0, 0), text, font=font)
            margin = 14
            size = (box[2] + margin * 2, box[3] + margin * 2)
            r, g, b = (int(c + (255 - c) * light) for c in self.accent)
            sharp = Image.new("RGBA", size, (r, g, b, 0))
            ImageDraw.Draw(sharp).text((margin, margin), text, font=font, fill=(r, g, b, 255))
            halo = sharp.filter(ImageFilter.GaussianBlur(4))
            halo.putalpha(halo.getchannel("A").point(lambda v: min(255, int(v * 1.4))))
            tinted = Image.new("RGBA", size, tuple(self.accent) + (0,))
            tinted.putalpha(halo.getchannel("A"))
            layer = Image.alpha_composite(tinted, sharp)
            self._text_cache[key] = layer
        shown = layer
        if alpha < 0.99:
            shown = layer.copy()
            shown.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
        image.alpha_composite(shown, (max(0, int(position[0] - 14)), max(0, int(position[1] - 14))))

    def _text(self, image, t: float, fade: float) -> None:
        half = self.size / 2
        if self.style == "terminal":
            font = self._font_of(round(11 * self.zoom), True)
            x0 = half + (self.panel[0] - self.panel[2]) * half + 12 * self.zoom
            y0 = half - (self.panel[1] + self.panel[3]) * half + 10 * self.zoom
            shown = t / 2.0 * len(self.lines)
            for index, line in enumerate(self.lines):
                part = shown - index
                if part <= 0:
                    break
                count = int(len(line) * min(1.0, part * 1.5))
                light = 0.55 if index < len(self.lines) - 1 else 0.1
                self._glow_text(image, (x0, y0 + index * 15 * self.zoom), line[:count], font, fade, light)
        elif self.style == "minimal":
            font = self._font_of(round(20 * self.zoom), False)
            word = "J A R V I S"
            letters = int(cinematic._ease(t / 1.4) * len(word) + 0.5)
            full_width = font.getbbox(word)[2]
            y = half + ORB_REACH * 2.05 * half - 36 * self.zoom
            self._glow_text(image, (half - full_width / 2, y), word[:letters], font, fade)
        elif self.style == "anneaux":
            font = self._font_of(round(11 * self.zoom), False)
            text = "JARVIS · EN LIGNE" if self.lang == "fr" else "JARVIS · ONLINE"
            open_ = cinematic._ease((t - 0.35) / 0.6) * (1 - cinematic._ease((t - 1.75) / 0.6))
            width = font.getbbox(text)[2]
            self._glow_text(image, (half - width / 2, half + half * 0.78), text, font, fade * open_)

    def _font_of(self, size: int, mono: bool):
        key = ("font", size, mono)
        if key not in self._text_cache:
            self._text_cache[key] = cinematic._font(size, mono=mono)
        return self._text_cache[key]

    def close(self) -> None:
        for item in (self.vao, self.vbo, self.fbo, self.program):
            try:
                item.release()
            except Exception:
                pass


__all__ = ["GpuPainter", "MODES"]
