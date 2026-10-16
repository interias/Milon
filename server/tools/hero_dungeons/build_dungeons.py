"""Baut Strecken-Verliese aus OSM-Wegen (BRouter, Profil Wandern) um öffentliche Landmarken bei Wesel.

Ergebnis: server/app/data/hero_dungeons.json — je Verlies 2–4 Abschnitte (Bosse) als lat/lon-Polylinien.
"""
import json, math, pathlib, random, sys, time, urllib.parse, urllib.request

HERE = pathlib.Path(__file__).parent
PLACES = json.loads((HERE / "places.json").read_text(encoding="utf-8"))
OUT = pathlib.Path(__file__).resolve().parents[2] / "app" / "hero_dungeons.json"
CACHE = HERE / "routes_cache.json"
UA = {"User-Agent": "milon-hero-research/1.0 (personal fitness project)"}

# (key, Name, Typ, Muster, Ort(e), Radius km, Beschreibung)
SPECS = [
    # Wasser
    ("auesee", "Spiegel des Auesees", "wasser", "lake", "Auesee, Wesel", 0.08, "Eine Runde um den Auesee – das Wasser hält still, die Wächter nicht."),
    ("schwarzes_wasser", "Moor des Schwarzen Wassers", "wasser", "lake", "Schwarzes Wasser, Wesel", 0.2, "Dunkles Heidewasser im Diersfordter Wald, umringt von Irrlichtern."),
    ("tenderingssee", "Tiefen des Tenderingssees", "wasser", "lake", "Tenderingssee, Hünxe", 0.08, "Ein Baggersee mit kaltem Grund und warmen Ufern."),
    ("suedsee", "Römerhafen am Südsee", "wasser", "lake", "Xantener Südsee", 0.08, "Wo einst Legionen anlegten, kreisen heute Segel – und Schatten."),
    ("nordsee", "Nebel über dem Nordsee", "wasser", "lake", "Xantener Nordsee", 0.08, "Morgens liegt hier Nebel, der Namen flüstert."),
    ("hagener_meer", "Ufer des Hagener Meeres", "wasser", "lake", "Hagener Meer", 0.04, "Ein stilles Meer ohne Gezeiten, aber mit Wächtern."),
    # Wald
    ("diersfordter_wald", "Herz des Diersfordter Waldes", "wald", "area", "Diersfordter Wald", 1.5, "Kiefern, Heide und Dünen – das älteste Revier des Niederrheins."),
    ("drevenacker_duenen", "Wandernde Dünen von Drevenack", "wald", "area", "Drevenacker Dünen", 0.8, "Sand unter Kiefern, der sich nachts angeblich bewegt."),
    ("daemmerwald", "Dämmerwald", "wald", "area", "Dämmerwald, Schermbeck", 1.6, "Der Name ist Warnung genug."),
    ("leucht", "Leuchtwald von Alpen", "wald", "area", "Die Leucht, Alpen", 1.2, "Ein Höhenzug voller Buchen, in dem Glühwürmchen Wache halten."),
    ("hees", "Hochwald der Hees", "wald", "area", "Hees, Xanten", 1.0, "Der Wald über Xanten, in dem römische Münzen im Laub liegen."),
    # Aue & Deich
    ("lippeaue", "Pfad der Lippeauen", "aue", "village", "Lippeaue, Wesel", 0.9, "Altarme, Weiden und Störche an der Mündung der Lippe."),
    ("momm", "Sümpfe der Momm-Niederung", "aue", "area", "Momm-Niederung", 1.0, "Feuchtwiesen, in denen jeder Schritt schmatzt."),
    ("bislicher_insel", "Altrhein der Bislicher Insel", "aue", "village", "Bislicher Insel", 0.8, "Der alte Rhein hat sich zurückgezogen – seine Hüter nicht."),
    ("rheindeich", "Deich der Flussbarone", "deich", "line", "Fort Blücher, Wesel|Büderich, Wesel|Ginderich", 0, "Über den Rheindeich vom Fort Blücher bis nach Ginderich."),
    ("festungsring", "Festungsring von Wesel", "deich", "line", "Zitadelle Wesel|Rheinpromenade Wesel|Lauerhaas, Wesel|Zitadelle Wesel", 0, "Zitadelle, Rhein und Wälle der alten Hansestadt."),
    # Feld
    ("feldmark", "Felder der Feldmark", "feld", "area", "Feldmark, Wesel", 0.9, "Feldwege, Hecken und ein Himmel ohne Ende."),
    ("obrighoven", "Hecken von Obrighoven", "feld", "area", "Obrighoven", 1.1, "Ein Labyrinth aus Feldwegen und Wallhecken."),
    ("bergerfurth", "Furt von Bergerfurth", "feld", "area", "Bergerfurth, Wesel", 0.9, "Wo einst die Furt war, wartet heute der Fährmann."),
    ("boenninghardt", "Höhen der Bönninghardt", "feld", "village", "Bönninghardt", 1.3, "Die Heide auf dem Höhenrücken – Wind von allen Seiten."),
    # Dorf
    ("bislich", "Fährdorf Bislich", "dorf", "village", "Bislich", 0.9, "Ein Deichdorf mit Fähre, Kirchturm und Geschichten."),
    ("flueren", "Gassen von Flüren", "dorf", "area", "Flüren", 0.8, "Zwischen Rhein und Wald – das Dorf der Fischer."),
    ("ginderich", "Wallfahrt nach Ginderich", "dorf", "area", "Ginderich", 0.8, "Ein Pilgerdorf, in dem die Glocken die Runde zählen."),
    ("diersfordt", "Schlosshof Diersfordt", "dorf", "line", "Schloss Diersfordt|Diersfordt|Schwarzes Wasser, Wesel|Schloss Diersfordt", 0, "Vom Wasserschloss durchs Dorf zum Heidewasser und zurück."),
    ("drevenack", "Kirchspiel Drevenack", "dorf", "village", "Drevenack", 0.9, "Ein Dorf an der Lippe mit langen Feldwegen."),
    ("ringenberg", "Schloss Ringenberg", "dorf", "village", "Schloss Ringenberg", 0.8, "Ein Wasserschloss, in dem heute Künstler spuken."),
    ("bruenen", "Heide von Brünen", "dorf", "village", "Brünen", 1.1, "Ein Heidedorf an der Grenze zum Münsterland."),
    ("marienthal", "Kloster Marienthal", "dorf", "village", "Marienthal, Hamminkeln", 1.0, "Ein Klosterdorf, in dem Schweigen eine Kunst ist."),
    ("krudenburg", "Lippefähre Krudenburg", "dorf", "village", "Krudenburg", 0.8, "Das kleinste Dorf mit der größten Fährgeschichte."),
    ("mehrhoog", "Bahnwärter von Mehrhoog", "dorf", "village", "Mehrhoog", 1.1, "Wo die Züge halten, beginnen die Feldwege."),
    ("wardt", "Wardter Rheinbogen", "dorf", "village", "Wardt, Xanten", 1.1, "Ein Dorf zwischen zwei Seen und dem Rhein."),
    ("loikum", "Wiesen von Loikum", "dorf", "village", "Loikum", 1.1, "Weite Wiesen, auf denen Störche Hof halten."),
    ("dingden", "Heideweg nach Dingden", "dorf", "village", "Dingden", 1.2, "Ein Dorf mit Heide, Bach und Kreuzweg."),
    ("gahlen", "Gahlener Lippeufer", "dorf", "village", "Gahlen", 1.3, "Am Lippeufer, wo Kanal und Fluss sich kreuzen."),
    ("isselburg", "Wasserburg von Isselburg", "dorf", "village", "Isselburg", 1.3, "Weit im Norden: eine Stadt an der Issel und Burgen ringsum."),
]
BOSSES = {
    "wasser": ["Ufergeist", "Schlammkrake", "Hechtkönig", "Nebelnixe", "Reiherfürst", "Tiefenwächter"],
    "wald": ["Borkenbiest", "Harzwächter", "Kiefernkönig", "Dünenwurm", "Eulenmutter", "Wurzelgreif"],
    "aue": ["Weidenhexe", "Storchenkönig", "Schilfwyrm", "Auengeist", "Biberbaron", "Unkenfürst"],
    "deich": ["Deichgraf", "Flussbaron", "Zöllner", "Wallmeister", "Schleusenwart", "Festungsgeist"],
    "feld": ["Krähenkönig", "Vogelscheuche", "Heckenkobold", "Pflugriese", "Windmüller", "Feldhüter"],
    "dorf": ["Glöckner", "Wirtin vom Krug", "Dorfschmied", "Fährmann", "Nachtwächter", "Küster"],
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return json.loads(r.read())


def to_m(lat0, lat, lon, lon0):
    return (lon - lon0) * 111_320 * math.cos(math.radians(lat0)), (lat - lat0) * 110_540


def from_m(lat0, lon0, x, y):
    return lat0 + y / 110_540, lon0 + x / (111_320 * math.cos(math.radians(lat0)))


def outer_ring(geo):
    if geo["type"] == "Polygon":
        return geo["coordinates"][0]
    if geo["type"] == "MultiPolygon":
        return max((p[0] for p in geo["coordinates"]), key=len)
    return None


def inside(pt, ring):
    x, y, c = pt[0], pt[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def waypoints(spec):
    key, _, _, pattern, where, rad_km, _ = spec
    rng = random.Random(key)
    if pattern == "line":
        return [(float(PLACES[n]["lat"]), float(PLACES[n]["lon"])) for n in where.split("|")]
    p = PLACES[where]
    lat0, lon0 = float(p["lat"]), float(p["lon"])
    ring = outer_ring(p["geojson"])
    if pattern == "lake" and ring:
        cx = sum(q[0] for q in ring) / len(ring); cy = sum(q[1] for q in ring) / len(ring)
        pts = []
        for a in range(0, 360, 60):
            # Uferpunkt in Richtung a, dann um rad_km nach außen geschoben
            ang = math.radians(a + rng.uniform(-10, 10))
            best = max(ring, key=lambda q: (q[0] - cx) * math.sin(ang) * math.cos(math.radians(cy)) + (q[1] - cy) * math.cos(ang))
            x, y = to_m(cy, best[1], best[0], cx)
            r = math.hypot(x, y) or 1
            x, y = x / r * (r + rad_km * 1000), y / r * (r + rad_km * 1000)
            pts.append(from_m(cy, cx, x, y))
        return pts + pts[:1]
    if pattern == "area" and ring:
        cx = sum(q[0] for q in ring) / len(ring); cy = sum(q[1] for q in ring) / len(ring)
        lat0, lon0 = cy, cx
        pts, start = [], rng.uniform(0, 72)
        for k in range(5):
            ang = math.radians(start + k * 72)
            for shrink in (1.0, 0.75, 0.5, 0.3):
                la, lo = from_m(lat0, lon0, math.sin(ang) * rad_km * 1000 * shrink, math.cos(ang) * rad_km * 1000 * shrink)
                if inside((lo, la), ring):
                    break
            pts.append((la, lo))
        return pts + pts[:1]
    # village / Punkt: Runde um den Ortskern
    pts, start = [], rng.uniform(0, 90)
    for k in range(4):
        ang = math.radians(start + k * 90)
        pts.append(from_m(lat0, lon0, math.sin(ang) * rad_km * 1000, math.cos(ang) * rad_km * 1000))
    return pts + pts[:1]


cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def route(pts):
    lonlats = "|".join(f"{lo:.5f},{la:.5f}" for la, lo in pts)
    if lonlats in cache:
        return cache[lonlats]
    q = urllib.parse.urlencode({"lonlats": lonlats, "profile": "hiking-mountain", "alternativeidx": 0, "format": "geojson"})
    data = get(f"https://brouter.de/brouter?{q}")
    coords = [(c[1], c[0]) for c in data["features"][0]["geometry"]["coordinates"]]
    cache[lonlats] = coords
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    time.sleep(4.0)
    return coords


def resample(coords, step=30.0):
    lat0, lon0 = coords[0]
    m = [to_m(lat0, la, lo, lon0) for la, lo in coords]
    out, carry, total = [coords[0]], 0.0, 0.0
    for (x1, y1), (x2, y2) in zip(m, m[1:]):
        d = math.hypot(x2 - x1, y2 - y1)
        total += d
        pos = step - carry
        while pos <= d:
            t = pos / d
            out.append(from_m(lat0, lon0, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
            pos += step
        carry = (carry + d) % step if d else carry
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out, total


def spur_ratio(pts):
    """Anteil Hin-und-zurück-Stücke: Punkte, die einen früheren (nicht benachbarten) Punkt fast treffen."""
    lat0, lon0 = pts[0]
    m = [to_m(lat0, la, lo, lon0) for la, lo in pts]
    hits = 0
    for i, (x, y) in enumerate(m):
        if any(math.hypot(x - a, y - b) < 15 for a, b in m[: max(0, i - 8)]):
            hits += 1
    return hits / len(m)


dungeons = []
only = set(sys.argv[1:])
for spec in SPECS:
    key, name, kind, pattern, where, rad_km, desc = spec
    if only and key not in only:
        continue
    try:
        coords = route(waypoints(spec))
    except Exception as e:  # noqa: BLE001
        print("ERR", key, e)
        continue
    pts, length = resample(coords)
    nseg = 2 if length < 3500 else 3 if length < 7000 else 4
    per = len(pts) // nseg
    names = random.Random(key + ":boss").sample(BOSSES[kind], nseg)
    segs = []
    for i in range(nseg):
        part = pts[i * per: (i + 1) * per + 1] if i < nseg - 1 else pts[i * per:]
        segs.append({"boss": names[i], "points": [[round(la, 5), round(lo, 5)] for la, lo in part]})
    dungeons.append({"key": key, "name": name, "type": kind, "desc": desc, "length_m": round(length), "segments": segs})
    print(f"{key:20s} {kind:6s} {length / 1000:5.1f} km  {nseg} Abschn.  Spur {spur_ratio(pts):.0%}")

if not only:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "© OpenStreetMap-Mitwirkende (ODbL), Routen via BRouter", "dungeons": dungeons},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("geschrieben:", OUT, OUT.stat().st_size // 1024, "KB")
