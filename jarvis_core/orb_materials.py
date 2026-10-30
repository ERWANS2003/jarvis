"""Matieres de l'orbe en relief (shader GLSL du rendu ultra).

Chaque matiere deforme la surface (le relief est donc reel : silhouette,
ombres et reflets suivent la forme) puis la colore a sa facon :

  0 nacre        sphere liquide irisee (d'origine)
  1 plasma       bandes liquides qui defilent (d'origine)
  2 cristal      gemme taillee : facettes planes, eclats, dispersion
  3 planete      continents en relief, oceans, nuages, atmosphere
  4 magma        croute de roche fendue, failles incandescentes
  5 chrome       metal liquide qui reflete un decor
  6 reacteur     plaques gravees, lignes d'energie qui circulent
  7 oeil         iris fibreux, cornee bombee, pupille qui suit la voix
  8 trou noir    horizon noir, disque d'accretion, effet de lentille
  9 cellules     bosses organiques, sillons lumineux
  10 hologramme  sphere filaire translucide, balayage
  11 marbre      pierre polie veinee, veines gravees
  12 orage       nuages bombes, eclairs internes

La partie commune (bruit, uniformes) est dans `orb_gpu.FRAGMENT_HEAD`.
"""

MODES = {"nacre": 0, "plasma": 1, "cristal": 2, "planete": 3, "magma": 4, "chrome": 5,
         "reacteur": 6, "oeil": 7, "trou_noir": 8, "cellules": 9, "hologramme": 10,
         "marbre": 11, "orage": 12}

GLSL = """
float hash(float n) { return fract(sin(n) * 43758.5453); }
vec3 hash3(vec3 p) {
    p = vec3(dot(p, vec3(127.1, 311.7, 74.7)), dot(p, vec3(269.5, 183.3, 246.1)),
             dot(p, vec3(113.5, 271.9, 124.6)));
    return fract(sin(p) * 43758.5453);
}
float fbm(vec3 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 4; i++) { s += a * snoise(p); p = p * 2.03 + 11.7; a *= 0.5; }
    return s;
}
// Voronoi 3D : (F1, F2, identifiant de cellule).
vec3 voronoi(vec3 x) {
    vec3 cell = floor(x), f = fract(x);
    float f1 = 8.0, f2 = 8.0, id = 0.0;
    for (int k = -1; k <= 1; k++)
    for (int j = -1; j <= 1; j++)
    for (int i = -1; i <= 1; i++) {
        vec3 g = vec3(float(i), float(j), float(k));
        vec3 o = hash3(cell + g);
        vec3 r = g + o - f;
        float d = dot(r, r);
        if (d < f1) { f2 = f1; f1 = d; id = dot(cell + g, vec3(7.0, 157.0, 113.0)); }
        else if (d < f2) { f2 = d; }
    }
    return vec3(sqrt(f1), sqrt(f2), id);
}
vec3 rotY(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z); }
vec3 rotX(vec3 p, float a) { float c = cos(a), s = sin(a); return vec3(p.x, c * p.y - s * p.z, s * p.y + c * p.z); }

// Directions des facettes du cristal (spirale de Fibonacci).
vec3 facetDir(int i) {
    float fi = float(i) + 0.5;
    float y = 1.0 - 2.0 * fi / 26.0;
    float r = sqrt(max(0.0, 1.0 - y * y));
    float a = fi * 2.39996;
    return vec3(cos(a) * r, y, sin(a) * r);
}
vec3 eyeLook() {
    // Regard qui saute d'un point a l'autre (saccades) puis se pose.
    float k = floor(time * 0.45);
    float f = smoothstep(0.0, 0.18, fract(time * 0.45));
    vec2 a = (vec2(hash(k * 3.1), hash(k * 7.3)) - 0.5) * 0.7;
    vec2 b = (vec2(hash((k + 1.0) * 3.1), hash((k + 1.0) * 7.3)) - 0.5) * 0.7;
    vec2 g = mix(mix(a, b, f), eye_look.xy, eye_look.z);
    return normalize(vec3(g.x, g.y * 0.8, 1.0));
}

float shape(vec3 p) {
    if (mode == 2) {                               // cristal : polyedre a 26 faces
        vec3 q = rotX(rotY(p, time * 0.25), 0.35);
        float d = -1.0;
        for (int i = 0; i < 26; i++) d = max(d, dot(q, facetDir(i)));
        return d - radius * 0.93;
    }
    if (mode == 3) {                               // planete : relief des continents
        vec3 q = rotY(p, time * 0.18);
        float h = fbm(normalize(q) * 2.1);
        return length(p) - radius * (1.0 + 0.045 * max(h - 0.02, 0.0));
    }
    if (mode == 4) {                               // magma : plaques et failles
        vec3 v = voronoi(rotY(p, time * 0.08) * 3.4);
        float crack = smoothstep(0.0, 0.09, v.y - v.x);
        return length(p) - radius * (0.975 + 0.035 * crack + 0.01 * snoise(p * 9.0));
    }
    if (mode == 5) {                               // chrome : liquide plus ample
        float n = snoise(p * 1.1 + vec3(0.0, 0.0, time * 0.35)) * 0.75
                + snoise(p * 2.4 - vec3(time * 0.25, 0.0, 0.0)) * 0.25;
        return length(p) - radius * (1.0 + ripple * 1.5 * n);
    }
    if (mode == 6) {                               // reacteur : rainures gravees
        vec3 q = rotY(p, time * 0.3);
        vec3 n = normalize(q);
        float u = atan(n.z, n.x) * 6.0 / 3.1416;
        float v = asin(clamp(n.y, -1.0, 1.0)) * 5.0 / 3.1416;
        float g = min(abs(fract(u) - 0.5), abs(fract(v) - 0.5));
        float groove = 1.0 - smoothstep(0.43, 0.49, 0.5 - g);
        return length(p) - radius * (1.0 - 0.03 * (1.0 - groove));
    }
    if (mode == 7) {                               // oeil : cornee bombee
        float c = dot(normalize(p), eyeLook());
        return length(p) - radius * (1.0 + 0.07 * smoothstep(0.82, 1.0, c));
    }
    if (mode == 8) return length(p) - radius * 0.5; // trou noir : horizon
    if (mode == 9) {                               // cellules : bosses
        vec3 v = voronoi(rotY(p, time * 0.1) * 3.6 + vec3(0.0, time * 0.05, 0.0));
        float bump = smoothstep(0.0, 0.32, v.y - v.x);
        return length(p) - radius * (0.96 + 0.07 * sqrt(bump));
    }
    if (mode == 11) {                              // marbre : veines gravees
        float w = fbm(rotY(p, time * 0.1) * 1.6);
        float vein = abs(sin((p.x * 3.0 + p.y * 2.0 + w * 5.0) * 2.0));
        return length(p) - radius * (1.0 - 0.012 * (1.0 - smoothstep(0.0, 0.15, vein)));
    }
    if (mode == 12) {                              // orage : nuages bombes
        float n = fbm(p * 1.7 + vec3(time * 0.12, 0.0, time * 0.05));
        return length(p) - radius * (0.95 + 0.2 * max(n, -0.2) + ripple * 0.3 * snoise(p * 3.0 + time * 0.3));
    }
    if (mode == 10) return length(p) - radius;     // hologramme : sphere nette
    // nacre et plasma : grandes ondulations lentes, surface liquide et lisse.
    float n = snoise(p * 1.15 + vec3(0.0, 0.0, time * 0.32)) * 0.7
            + snoise(p * 2.3 - vec3(time * 0.22, 0.0, 0.0)) * 0.3
            + snoise(p * 4.2 + vec3(0.0, time * 0.4, 0.0)) * 0.06 * level;
    return length(p) - radius * (1.0 + ripple * n);
}

vec3 normalAt(vec3 p) {
    vec2 e = vec2(0.002, 0.0);
    return normalize(vec3(shape(p + e.xyy) - shape(p - e.xyy),
                          shape(p + e.yxy) - shape(p - e.yxy),
                          shape(p + e.yyx) - shape(p - e.yyx)));
}

vec3 palette(float t) {
    t = fract(t) * 4.0;
    vec3 a = t < 1.0 ? c0 : t < 2.0 ? c1 : t < 3.0 ? c2 : c3;
    vec3 b = t < 1.0 ? c1 : t < 2.0 ? c2 : t < 3.0 ? c3 : c0;
    float f = smoothstep(0.0, 1.0, fract(t));
    return mix(a, b, f);
}

// Decor reflechi par le chrome : ciel, horizon, deux boites a lumiere.
vec3 environment(vec3 r) {
    vec3 sky = mix(c1 * 0.35, c0, smoothstep(-0.2, 0.9, r.y));
    float horizon = exp(-abs(r.y) * 14.0);
    sky = mix(sky, c2, horizon * 0.8);
    sky += vec3(1.0) * smoothstep(0.92, 0.99, dot(r, normalize(vec3(-0.6, 0.6, 0.5)))) * 1.2;
    sky += c3 * smoothstep(0.95, 0.995, dot(r, normalize(vec3(0.7, -0.1, 0.6))));
    if (r.y < 0.0) {                                   // sol : damier qui fuit + reflet du ciel
        vec2 fl = r.xz / max(-r.y, 0.15) * 0.55;
        vec2 cellf = abs(fract(fl) - 0.5);
        float check = smoothstep(0.42, 0.5, max(cellf.x, cellf.y));      // joints du carrelage
        vec3 floorCol = mix(c1 * 0.8, mix(c2, c3, 0.5) * 0.9, 0.35 + 0.65 * check);
        floorCol = mix(floorCol, c0 * 0.55, exp(r.y * 4.0) * 0.8);       // brume au loin
        sky = mix(sky, floorCol, smoothstep(0.0, -0.12, r.y));
    }
    return sky;
}

// Disque d'accretion du trou noir (dans le plan de l'ecran, incline).
vec4 accretion(vec2 q, float core) {
    float tilt = 0.26;
    vec2 e = vec2(q.x, q.y / tilt);
    float r = length(e);
    float inner = core * 1.45, outer = core * 3.0;
    float band = smoothstep(inner, inner + 0.02, r) * (1.0 - smoothstep(outer - 0.12, outer, r));
    float a = atan(e.y, e.x);
    float swirl = snoise(vec3(cos(a - time * 1.4 / max(r, 0.05)) * r * 5.0,
                              sin(a - time * 1.4 / max(r, 0.05)) * r * 5.0, time * 0.2)) * 0.5 + 0.5;
    float heat = 1.0 - (r - inner) / (outer - inner);
    vec3 col = mix(mix(c1, c0, heat), c3, pow(max(heat, 0.0), 3.0));
    float doppler = 1.0 + 0.7 * clamp(-q.x / max(r, 0.05), -1.0, 1.0);
    float k = band * (0.45 + 0.75 * swirl) * doppler * (1.0 + level * 0.8 + pulse);
    // Image du disque arriere, courbee au-dessus de l'horizon (lentille).
    float ring = length(q) - core * 1.18;
    float lens = exp(-ring * ring * 900.0) * (0.6 + 0.4 * swirl) * (q.y > -core * 0.2 ? 1.0 : 0.35);
    return vec4(col * k + c3 * lens * 1.3, clamp(k + lens, 0.0, 1.0));
}

void main() {
    vec2 q = uv;
    q -= vec2(0.03 * sin(clock * 0.5), 0.05 * sin(clock * 0.8 + 0.6));   // levitation
    vec3 ro = vec3(q, 2.2);
    vec3 rd = vec3(0.0, 0.0, -1.0);
    float t = 0.0;
    float minDist = 10.0;
    bool hit = false;
    vec3 p;
    for (int i = 0; i < 110; i++) {
        p = ro + rd * t;
        float d = shape(p);
        minDist = min(minDist, d);
        if (d < 0.0012) { hit = true; break; }
        t += d * 0.5;
        if (t > 4.0) break;
    }

    vec3 col = vec3(0.0);
    float alpha = 0.0;
    vec3 haloColor = mix(c1, c0, 0.5);
    if (hit) {
        vec3 n = normalAt(p);
        vec3 v = -rd;
        vec3 l = normalize(vec3(-0.5, 0.7, 0.8));
        float diff = clamp(dot(n, l) * 0.5 + 0.5, 0.0, 1.0);
        float lambert = clamp(dot(n, l), 0.0, 1.0);
        float fres = pow(1.0 - clamp(dot(n, v), 0.0, 1.0), 2.5);
        vec3 h = normalize(l + v);
        float nh = clamp(dot(n, h), 0.0, 1.0);
        float spec = pow(nh, 90.0);
        float sheen = pow(nh, 8.0) * 0.18;
        alpha = 1.0;

        if (mode == 2) {                                   // cristal
            vec3 q2 = rotX(rotY(p, time * 0.25), 0.35);
            float best = -9.0; int face = 0;
            for (int i = 0; i < 26; i++) { float d = dot(q2, facetDir(i)); if (d > best) { best = d; face = i; } }
            float fh = hash(float(face) * 1.7);
            vec3 inside = mix(mix(c0, c1, fh), c2, hash(float(face) * 4.1) * 0.6);
            vec3 refr = refract(rd, n, 0.66);
            inside *= 0.5 + 0.55 * smoothstep(-0.6, 0.8, refr.y);
            // Fractures internes vues a travers la facette (refraction).
            vec3 fr = voronoi(refr * 2.6 + q2 * 1.8 + vec3(time * 0.05));
            float fracture = 1.0 - smoothstep(0.0, 0.06, fr.y - fr.x);
            inside += mix(c2, vec3(1.0), 0.3) * fracture * 0.45;
            inside *= 0.8 + 0.35 * snoise(refr * 3.0 + float(face));
            vec3 disp = 0.5 + 0.5 * cos(6.2832 * (fres * 1.6 + fh + vec3(0.0, 0.33, 0.67)));
            float sparkle = smoothstep(0.55, 0.9, snoise(p * 26.0 + vec3(clock * 1.5)));
            float glint = step(0.86, hash(float(face) + floor(clock * 2.5))) * pow(nh, 6.0);
            col = inside * (0.45 + 0.7 * lambert) + disp * fres * 0.55;
            col += vec3(1.0) * (pow(nh, 260.0) * 0.35 + sparkle * pow(nh, 4.0) * 0.9
                                + glint * 0.5 + spec * 0.15);
            col += c2 * 0.3 * (pulse + level);
            alpha = mix(0.9, 0.98, fres);
        } else if (mode == 3) {                            // planete
            vec3 q2 = rotY(p, time * 0.18);
            vec3 dir = normalize(q2);
            float hgt = fbm(dir * 2.1);
            float lat = abs(dir.y);
            vec3 ocean = mix(c1 * 0.55, c1, smoothstep(-0.35, 0.0, hgt));
            vec3 land = mix(c0, c2, smoothstep(0.05, 0.3, hgt));
            land = mix(land, vec3(0.95), smoothstep(0.32, 0.42, hgt));              // sommets
            vec3 surf = hgt > 0.02 ? land : ocean;
            surf = mix(surf, vec3(0.96), smoothstep(0.78, 0.9, lat));                // poles
            float clouds = smoothstep(0.08, 0.5, fbm(rotY(p, time * 0.24) * 2.6 + vec3(0.0, time * 0.03, 0.0)));
            float day = clamp(dot(n, l) * 1.2 + 0.25, 0.0, 1.0);
            col = surf * (0.12 + 0.95 * day);
            col += (hgt <= 0.02 ? 1.0 : 0.15) * vec3(1.0) * pow(nh, 60.0) * 0.6 * day; // reflet de l'ocean
            col = mix(col, vec3(1.0) * (0.25 + 0.8 * day), clouds * 0.85);
            col += (1.0 - day) * c2 * 0.18 * step(0.1, hgt) * hash(floor(dir.x * 90.0) + floor(dir.y * 90.0) * 7.0); // villes
            col = mix(col, c3, fres * 0.75);                                        // atmosphere
            haloColor = c3;
        } else if (mode == 4) {                            // magma
            vec3 vq = rotY(p, time * 0.08) * 3.4;
            vec3 vr = voronoi(vq);
            float edge = vr.y - vr.x;
            float crack = 1.0 - smoothstep(0.0, 0.07, edge);
            float heat = 0.75 + 0.35 * sin(time * 2.2 + vr.z) + 0.6 * level + pulse;
            vec3 rock = mix(c1 * 0.25, c1 * 0.55, fbm(vq * 1.7) * 0.5 + 0.5);
            col = rock * (0.25 + 0.9 * lambert) + vec3(1.0) * spec * 0.25;
            vec3 lava = mix(c0, c3, crack * crack);
            col = mix(col, lava * heat * 1.4, crack);
            col += c0 * 0.35 * smoothstep(0.2, 0.0, edge) * heat;                 // braise sous la croute
            haloColor = c0;
        } else if (mode == 5) {                            // chrome
            vec3 r = reflect(rd, n);
            vec3 env = environment(r);
            col = env * mix(c3 * 0.6 + 0.4, vec3(1.0), fres);
            col += vec3(1.0) * pow(nh, 200.0) * 1.5;
            col += c0 * 0.2 * (pulse + level);
        } else if (mode == 6) {                            // reacteur
            vec3 q2 = rotY(p, time * 0.3);
            vec3 dn = normalize(q2);
            float u = atan(dn.z, dn.x) * 6.0 / 3.1416;
            float vv = asin(clamp(dn.y, -1.0, 1.0)) * 5.0 / 3.1416;
            float g = min(abs(fract(u) - 0.5), abs(fract(vv) - 0.5));
            float line = smoothstep(0.43, 0.49, 0.5 - g);
            float flow = 0.5 + 0.5 * sin(u * 3.1416 * 2.0 - time * 5.0 + vv * 2.0);
            vec3 metal = mix(vec3(0.22, 0.25, 0.3), c1 * 0.6, 0.35);
            metal *= 0.85 + 0.15 * snoise(vec3(u * 9.0, vv * 2.0, 0.0));           // metal brosse
            col = metal * (0.3 + 0.9 * lambert) + vec3(1.0) * pow(nh, 70.0) * 0.8;
            col = mix(col, c0 * (1.2 + 0.8 * flow + level + pulse), line);
            float core = smoothstep(0.93, 0.97, dot(n, v));
            col = mix(col, mix(c0, vec3(1.0), 0.5) * (1.3 + level), core * (0.6 + 0.4 * sin(clock * 3.0)));
            haloColor = c0;
        } else if (mode == 7) {                            // oeil
            vec3 L = eyeLook();
            vec3 dn = normalize(p);
            float c = dot(dn, L);
            float ang = acos(clamp(c, -1.0, 1.0));
            vec3 t1 = normalize(cross(L, vec3(0.0, 1.0, 0.0)));
            vec3 t2 = cross(L, t1);
            float polar = atan(dot(dn, t2), dot(dn, t1));
            float irisR = 0.5, pupilR = 0.17 * eye_pupil * (1.0 + 0.7 * level + 0.4 * pulse - 0.25 * hover);
            float fibers = snoise(vec3(cos(polar) * 3.0, sin(polar) * 3.0, ang * 14.0)) * 0.5 + 0.5;
            vec3 iris = mix(c0, c1, smoothstep(pupilR, irisR, ang));
            iris = mix(iris, c2, fibers * 0.55) * (0.6 + 0.6 * fibers);
            iris = mix(iris, c1 * 0.3, smoothstep(irisR - 0.06, irisR, ang));       // limbe sombre
            vec3 sclera = mix(vec3(0.95, 0.93, 0.92), c3, 0.12);
            float veins = smoothstep(0.55, 0.75, abs(snoise(dn * 7.0))) * smoothstep(0.9, 1.6, ang);
            sclera = mix(sclera, vec3(0.8, 0.25, 0.3), veins * 0.35);
            vec3 surf = ang < irisR ? iris : sclera;
            surf = ang < pupilR ? vec3(0.02) : surf;
            col = surf * (0.35 + 0.8 * lambert);
            col += vec3(1.0) * (pow(nh, 300.0) * 2.0 + pow(nh, 30.0) * 0.15);       // cornee humide
            col = mix(col, vec3(1.0), fres * 0.2);
            // Paupieres : elles se referment sur l'oeil en suivant sa courbure.
            float upper = mix(-0.12, 1.02, eye_open) - 0.22 * dn.x * dn.x;
            float lower = mix(-0.12, -1.10, eye_open) + 0.18 * dn.x * dn.x;
            float edge = max(dn.y - upper, lower - dn.y);
            vec3 lidTone = mix(c1, c3, 0.25) * (0.28 + 0.75 * lambert);
            lidTone += vec3(1.0) * pow(nh, 18.0) * 0.08;
            col = mix(col, col * 0.45, smoothstep(-0.07, 0.0, edge));               // ombre portee
            col = mix(col, lidTone, smoothstep(-0.008, 0.012, edge));
        } else if (mode == 8) {                            // trou noir
            col = vec3(0.0);
            col += c3 * pow(fres, 3.0) * 1.6;                                     // anneau de photons
            vec4 disk = accretion(q, radius * 0.5);
            if (q.y < 0.0) { col = mix(col, disk.rgb, disk.a); }                 // disque devant l'horizon
            haloColor = c0;
        } else if (mode == 9) {                            // cellules
            vec3 vq = rotY(p, time * 0.1) * 3.6 + vec3(0.0, time * 0.05, 0.0);
            vec3 vr = voronoi(vq);
            float edge = vr.y - vr.x;
            float groove = 1.0 - smoothstep(0.0, 0.12, edge);
            vec3 cellCol = mix(c0, c2, hash(vr.z));
            col = cellCol * (0.35 + 0.8 * lambert) + vec3(1.0) * (spec * 0.6 + sheen);
            col = mix(col, c1 * (1.2 + level + pulse), groove * 0.85);
            col += c3 * pow(fres, 2.0) * 0.5;                                     // translucidite
            alpha = mix(0.98, 0.85, fres);
        } else if (mode == 10) {                           // hologramme
            vec3 q2 = rotY(p, time * 0.35);
            vec3 dn = normalize(q2);
            float u = atan(dn.z, dn.x) * 12.0 / 6.2832;
            float vv = asin(clamp(dn.y, -1.0, 1.0)) * 8.0 / 3.1416;
            float gu = abs(fract(u) - 0.5), gv = abs(fract(vv) - 0.5);
            float line = max(smoothstep(0.44, 0.5, gu), smoothstep(0.44, 0.5, gv));
            float scan = smoothstep(0.96, 1.0, sin(p.y * 38.0 - clock * 7.0));
            float flicker = 0.85 + 0.15 * step(0.5, hash(floor(clock * 14.0)));
            col = c0 * (line * 1.5 + 0.12) + c1 * fres * 0.8 + c2 * scan * 0.6;
            col *= flicker * (1.0 + level * 0.6 + pulse * 0.5);
            alpha = clamp(0.12 + line * 0.85 + fres * 0.55 + scan * 0.3, 0.0, 1.0);
            haloColor = c0;
        } else if (mode == 11) {                           // marbre
            vec3 q2 = rotY(p, time * 0.1);
            float w = fbm(q2 * 1.6);
            float vein = abs(sin((p.x * 3.0 + p.y * 2.0 + w * 5.0) * 2.0));
            float big = 1.0 - smoothstep(0.0, 0.26, vein);
            float fine = 1.0 - smoothstep(0.0, 0.05, abs(sin((p.y * 5.0 - p.z * 3.0 + fbm(q2 * 3.2) * 4.0) * 2.0)));
            vec3 stone = mix(c0, c0 * 0.88, fbm(q2 * 4.0) * 0.5 + 0.5);
            stone = mix(stone, c1, big * big * 0.95);
            stone = mix(stone, c2, max(fine * 0.75, smoothstep(0.75, 1.0, big) * 0.8));
            vec3 r = reflect(rd, n);
            col = stone * (0.45 + 0.65 * lambert) + environment(r) * fres * 0.25;
            col += vec3(1.0) * (pow(nh, 160.0) * 1.1 + sheen * 0.6);               // poli
        } else if (mode == 12) {                           // orage
            float dens = fbm(p * 3.2 + vec3(time * 0.15, 0.0, 0.0)) * 0.5 + 0.5;
            float top = smoothstep(-0.3, 0.9, n.y);                             // dessus eclaire
            vec3 cloud = mix(c1 * 0.18, c0 * 1.15, clamp(lambert * 0.75 + top * 0.35 + dens * 0.25 - 0.15, 0.0, 1.0));
            cloud += c3 * pow(fres, 1.8) * 0.55;                                  // liseré argente
            cloud += c2 * 0.18 * (1.0 - lambert) * dens;                          // lueur interne
            float strike = step(0.9 - 0.25 * level, hash(floor(clock * 5.0))) + pulse;
            vec2 bolt = q - vec2(hash(floor(clock * 5.0) * 3.0) - 0.5, 0.0) * radius;
            float zig = abs(bolt.x + 0.04 * snoise(vec3(bolt.y * 18.0, floor(clock * 5.0), 0.0)));
            float flash = clamp(strike, 0.0, 1.0);
            col = cloud * (0.35 + 0.7 * diff);
            col += c3 * flash * (0.35 * dens + 1.4 * smoothstep(0.012, 0.0, zig));
            col += c2 * 0.15 * fres;
            alpha = mix(0.98, 0.75, fres);
            haloColor = mix(c1, c3, flash * 0.6);
        } else if (mode == 1) {                            // plasma
            float band = p.y * 0.9 + snoise(p * 2.0 + time * 0.2) * 0.18 + time * 0.08;
            vec3 base = mix(palette(band), tint, tint_part);
            col = base * (0.66 + 0.4 * diff) + base * 0.14 * (1.0 - diff);
            col += vec3(1.0) * (spec * (0.7 + 0.3 * hover) + sheen);
            col = mix(col, vec3(1.0), fres * 0.32);
            col += base * 0.25 * (pulse + level * 0.6);
            alpha = mix(0.96, 0.8, fres);
        } else {                                           // nacre
            float m = snoise(p * 1.3 + vec3(time * 0.15)) * 0.5 + 0.5;
            float k = snoise(p * 2.1 - vec3(0.0, time * 0.12, 0.0)) * 0.5 + 0.5;
            vec3 base = mix(mix(c0, c1, m), mix(c2, c3, k), 0.5);
            vec3 irid = 0.5 + 0.5 * cos(6.2832 * (fres * 0.7 + p.y * 0.2 + time * 0.04
                                                  + vec3(0.0, 0.33, 0.67)));
            base = mix(base, irid, 0.1 + 0.16 * fres);
            base = mix(base, tint, tint_part);
            col = base * (0.66 + 0.4 * diff) + base * 0.14 * (1.0 - diff);
            col += vec3(1.0) * (spec * (0.7 + 0.3 * hover) + sheen);
            col = mix(col, vec3(1.0), fres * 0.32);
            col += base * 0.25 * (pulse + level * 0.6);
            alpha = mix(0.96, 0.8, fres);
        }
        if (mode >= 2) col = mix(col, col * 0.6 + tint * 0.6, tint_part * 0.5);    // teinte d'etat
    }

    if (!hit) {
        float g = exp(-max(minDist, 0.0) * 18.0) * glow * (0.75 + 0.6 * pulse + 0.5 * level);
        col = haloColor;
        alpha = g;
        if (mode == 8) {
            vec4 disk = accretion(q, radius * 0.5);
            col = mix(haloColor, disk.rgb, disk.a);
            alpha = max(alpha * 0.4, disk.a);
        }
    }

    // Coque de verre autour de l'orbe : reflets, bord lumineux, irisation, transparence.
    float Rs = (mode == 8 ? radius * 0.64 : radius * 1.14) * (1.0 + 0.04 * level + 0.05 * pulse);
    float r2 = dot(q, q);
    if (glass > 0.0 && r2 < Rs * Rs) {
        vec2 u = q / Rs;
        vec3 gn = normalize(vec3(u, sqrt(max(1.0 - dot(u, u), 0.0))));
        float gf = pow(1.0 - gn.z, 2.4);                                    // Fresnel
        vec3 gl = normalize(vec3(-0.5, 0.7, 0.8));
        float gspec = pow(max(dot(reflect(vec3(0.0, 0.0, -1.0), gn), gl), 0.0), 70.0);
        float crescent = smoothstep(0.05, 0.0, abs(length(u - vec2(0.1, -0.1)) - 0.8))
                       * smoothstep(-0.1, 0.7, u.y - u.x * 0.6);            // reflet en croissant
        float window = smoothstep(0.16, 0.0, length((u - vec2(-0.38, 0.44)) * vec2(1.0, 1.7)));
        float caustic = smoothstep(0.3, 0.0, length(u - vec2(0.32, -0.55)));  // lumiere concentree
        vec3 rim = 0.5 + 0.5 * cos(6.2832 * (gf * 1.4 + clock * 0.03 + vec3(0.0, 0.33, 0.67)));
        vec3 glassCol = mix(vec3(1.0), rim, 0.4 * gf);
        float ga = clamp(0.02 + gf * 0.55 + gspec * 0.9 + crescent * 0.35 + window * 0.5, 0.0, 1.0) * glass;
        alpha *= mix(1.0, 0.9, glass * (1.0 - gf));                         // on voit au travers
        col += c0 * caustic * 0.25 * glass * alpha;
        float outA = ga + alpha * (1.0 - ga);
        col = (glassCol * ga + col * alpha * (1.0 - ga)) / max(outA, 0.001);
        alpha = outA;
    }

    // Particules qui derivent autour.
    for (int i = 0; i < 26; i++) {
        float fi = float(i);
        float life = fract(clock * (0.05 + 0.07 * hash(fi * 3.1)) + hash(fi));
        float ang = 6.2832 * hash(fi * 7.7) + clock * 0.1 * (hash(fi) - 0.5);
        float reach = radius * ((mode == 8 ? 1.9 : 1.15) + 0.6 * life);
        vec2 pp = vec2(cos(ang), sin(ang)) * reach;
        float d = length(q - pp);
        float s = smoothstep(0.012, 0.0, d) * sin(3.1416 * life) * (0.4 + 0.6 * hash(fi * 1.7));
        col = mix(col, c0 + 0.3, s * (1.0 - alpha * 0.5));
        alpha = max(alpha, s * 0.9);
    }

    color = vec4(clamp(col, 0.0, 1.0), clamp(alpha, 0.0, 1.0) * fade);
}
"""

__all__ = ["GLSL", "MODES"]
