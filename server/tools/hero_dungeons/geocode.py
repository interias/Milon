"""Geocode candidate landmarks around Wesel (public places only) and cache results."""
import json, math, pathlib, time, urllib.parse, urllib.request

OUT = pathlib.Path(__file__).with_name("places.json")
UA = {"User-Agent": "milon-hero-research/1.0 (personal fitness project)"}
CENTER = (51.658, 6.618)  # Wesel Innenstadt
NAMES = [
    "Auesee, Wesel", "Schwarzes Wasser, Wesel", "Diersfordter Wald", "Schloss Diersfordt", "Bislicher Insel",
    "Tenderingssee, Hünxe", "Xantener Südsee", "Xantener Nordsee", "Lippemündung, Wesel", "Zitadelle Wesel",
    "Fort Blücher, Wesel", "Dämmerwald, Schermbeck", "Hünxer Wald", "Üfter Mark", "Die Leucht, Alpen",
    "Hees, Xanten", "Drevenacker Dünen", "Gartroper Busch", "Bislich", "Flüren", "Büderich, Wesel", "Diersfordt",
    "Obrighoven", "Drevenack", "Ginderich", "Wardt, Xanten", "Marienthal, Hamminkeln", "Ringenberg, Hamminkeln",
    "Dingden", "Brünen", "Gahlen", "Krudenburg", "Archäologischer Park Xanten", "Schloss Ringenberg",
    "Haus Gartrop", "Rheinpromenade Wesel", "Blumenkamp, Wesel", "Lippeaue, Wesel", "Diersfordter Heide",
    "Hagener Meer", "Rhein, Rees", "Isselburg", "Hohe Mark, Haltern", "Kirchhellener Heide", "Schwarzer Graben",
    "Lauerhaas, Wesel", "Momm-Niederung", "Rheinberg Altstadt", "Annaberg, Rheinberg", "Bönninghardt",
    "Bergerfurth, Wesel", "Feldmark, Wesel", "Hamminkeln", "Mehrhoog", "Loikum", "Haldern", "Rees",
]


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read())


cache = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
for name in NAMES:
    if name in cache:
        continue
    q = urllib.parse.urlencode({"q": name, "format": "json", "limit": 1, "polygon_geojson": 1, "countrycodes": "de",
                                "viewbox": "6.1,51.95,7.1,51.38", "bounded": 1})
    try:
        res = get(f"https://nominatim.openstreetmap.org/search?{q}")
    except Exception as e:  # noqa: BLE001
        res = []
        print("ERR", name, e)
    cache[name] = res[0] if res else None
    time.sleep(1.1)
OUT.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
for name, r in cache.items():
    if not r:
        print(f"{name:32s} --")
        continue
    lat, lon = float(r["lat"]), float(r["lon"])
    d = math.hypot((lon - CENTER[1]) * 69.2, (lat - CENTER[0]) * 110.5)
    bb = r["boundingbox"]
    size = math.hypot((float(bb[3]) - float(bb[2])) * 69.2, (float(bb[1]) - float(bb[0])) * 110.5)
    print(f"{name:32s} {r['class']:9s} {r['type']:14s} {d:5.1f} km  bbox {size:5.2f} km  {r['geojson']['type']}")
