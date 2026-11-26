"""Derive each spot's `town` - the nearest OSM settlement - from the local Geofabrik extracts.

The town is a SEARCH key (docs/SPOT-DB.md): a break is famous under its town's name at least
as often as its own, and until this existed a search for "Puerto Escondido" or "Tel Aviv"
returned nothing. Nearest `place` node within 12 km wins, except that a town or city inside
1.6x the nearest hamlet's distance outranks it - a hamlet named after the break itself
("Punta Roca Surf") is useless as a town. Roughly one spot in twelve still needs a hand
override; those live in tools/spot-seed/town_overrides.json.

Usage: towns.py <spots.json> <out.json>   where spots.json is [{id, name, region, lat, lon}].
"""

import json
import math
import sys

import osmium

PLACES = ("city", "town", "village", "hamlet")
REGION_PBF = {
    "Israel": "israel",
    "Portugal": "portugal",
    "Japan": "japan",
    "Sri Lanka": "sri-lanka",
    "Goa": "goa",
    "Karnataka": "karnataka",
    "Kerala": "kerala",
    "Tamil Nadu": "tamil-nadu",
    "Andhra Pradesh": "andhra-pradesh",
    "Odisha": "odisha",
    "Costa Rica": "costa-rica",
    "Nicaragua": "nicaragua",
    "Philippines": "philippines",
    "California": "california",
    "Oregon": "oregon",
    "Washington": "washington",
    "Mexico": "mexico",
    "El Salvador": "el-salvador",
    "Morocco": "morocco",
    "Angola": "angola",
    "Peru": "peru",
    "Panama": "panama",
    "Colombia Pacific": "colombia-pacific",
    "Colombia Caribbean": "colombia-caribbean",
    "Venezuela": "venezuela",
    "Dominican Republic": "dominican-republic",
    "Barbados": "barbados",
    "Puerto Rico": "puerto-rico",
    "Vancouver Island": "british-columbia",
    "Nova Scotia": "nova-scotia",
    "Liguria": "liguria",
    "Tuscany": "tuscany",
    "Lazio": "lazio",
    "Sardinia": "sardinia",
    "Campania": "campania",
    "Basilicata": "basilicata",
    "Calabria": "calabria",
    "Puglia": "puglia",
    "Dakhla": "dakhla",
    "Tobago": "tobago",
    "British Virgin Islands": "british-virgin-islands",
    "Malaysia": "malaysia",
    "Thailand": "thailand",
    "NSW Mid North Coast": "nsw-mid-north-coast",
    "NSW South Coast": "nsw-south-coast",
    "NSW Central Coast": "nsw-central-coast",
    # seeded 2026-11-12 (web flow): Bermuda has no Geofabrik extract - its towns are hand-set
    "Andaman": "andaman",
    "Antigua": "antigua",
    "Bahamas": "bahamas",
    "Brunei": "brunei",
    "Bulgaria": "bulgaria",
    "Charente Maritime": "charente-maritime",
    "Corsica": "corsica",
    "Curacao": "curacao",
    "Egypt": "egypt",
    "Emilia Romagna": "emilia-romagna",
    "Gironde": "gironde",
    "Greece": "greece",
    "Guadeloupe": "guadeloupe",
    "Cuba": "cuba-latest",
    "Haiti": "haiti-and-domrep-latest",
    "Dominica": "central-america-latest",
    "Saint Lucia": "central-america-latest",
    "Iran": "iran",
    "Jamaica": "jamaica",
    "Languedoc": "languedoc",
    "Lebanon": "lebanon",
    "Loire Atlantique": "loire-atlantique",
    "Maharashtra": "maharashtra",
    "Malta": "malta",
    "Maluku": "maluku",
    "Marche": "marche",
    "Martinique": "martinique",
    "Myanmar": "myanmar",
    "Oman": "oman",
    "Pakistan": "pakistan",
    "Papua": "papua",
    "Provence": "provence",
    "Sabah": "sabah",
    "Saint Barthelemy": "saint-barthelemy",
    "Saint Martin": "saint-martin",
    "Savu": "savu",
    "Timor Leste": "timor-leste",
    "Trinidad": "trinidad",
    "Turkey Black Sea": "turkey-black-sea",
    "Turkey Med": "turkey-med",
    "United Arab Emirates": "united-arab-emirates",
    "Us Virgin Islands": "us-virgin-islands",
    "Vendee": "vendee",
    "Vietnam": "vietnam",
    "Guatemala": "guatemala",
    "Galapagos": "galapagos",
    "Easter Island": "chile-latest",
    "Guam": "american-oceania-latest",
    "Pohnpei": "micronesia-latest",
    "Maldives": "maldives",
    "Sydney": "sydney",
    "Byron Bay": "byron-bay",
    "French Polynesia": "french-polynesia",
    "Fiji": "fiji",
    "Hawaii": "hawaii",
    "Perth": "perth",
    "Margaret River": "margaret-river",
    "Bali": "bali",
    "Lombok": "lombok",
    "Sumbawa": "sumbawa",
    "East Java": "east-java",
    "West Java": "west-java",
    "Sumba": "sumba",
    "Rote": "rote",
    "Gold Coast": "gold-coast",
    "Sunshine Coast": "sunshine-coast",
    "Moreton Bay": "australia",
    "Queensland Central": "australia",
    "Victoria": "victoria",
    "South Australia": "south-australia",
    "Tasmania": "tasmania",
    "WA North": "wa-north",
    "Mentawai": "mentawai",
    "Aceh": "aceh",
    "Simeulue": "simeulue",
    "Nias": "nias",
    "Krui": "krui",
    "Bengkulu": "bengkulu",
    "Tanegashima Amami": "tanegashima-amami",
    "Okinawa": "okinawa",
    "Taiwan": "taiwan",
    "Hokkaido": "hokkaido",
    "WA Midwest": "wa-midwest",
    "Bunbury": "bunbury",
    "Exmouth": "exmouth",
    "WA South": "wa-south",
    "Esperance": "esperance",
    "Cornwall Devon": "cornwall-devon",
    "Wales": "wales",
    "North Scotland": "north-scotland",
    "North East England": "north-east-england",
    "Landes": "landes",
    "Brittany": "brittany",
    "Normandy": "normandy",
    "England South": "england-south",
    "Tonga": "tonga",
    "Faroe Islands": "faroe-islands",
    "Azores": "azores",
    "Senegal": "senegal",
    "Cape Verde": "cape-verde",
    "Ghana": "ghana",
    "South Africa East": "south-africa-east",
    "South Africa West": "south-africa-west",
    "Namibia": "namibia",
    "Mozambique": "mozambique",
    "Kenya": "kenya",
    "New Zealand": "new-zealand",
    "Northland": "new-zealand",
    "Auckland": "new-zealand",
    "Coromandel": "new-zealand",
    "Waikato": "new-zealand",
    "Bay Of Plenty": "new-zealand",
    "Gisborne": "new-zealand",
    "Hawkes Bay": "new-zealand",
    "Taranaki": "new-zealand",
    "Wellington": "new-zealand",
    "South Island": "new-zealand",
    "Zanzibar": "zanzibar",
    "Madagascar": "madagascar",
    "Mauritius": "mauritius",
    "Reunion": "reunion",
    "Liberia": "liberia",
    "Sierra Leone": "sierra-leone-latest",
    "Gambia": "senegal-and-gambia-latest",
    "Ivory Coast": "ivory-coast-latest",
    "Sao Tome": "sao-tome-and-principe-latest",
    "Congo": "congo-brazzaville-latest",
    "Kosrae": "micronesia-latest",
    "Nauru": "nauru-latest",
    "Kiribati": "kiribati-latest",
    "Line Islands": "kiribati-latest",
    "Libya": "libya-latest",
    "San Andres": "colombia-latest",
    "Aruba": "central-america-latest",
    "Cayman Islands": "central-america-latest",
    "Grenada": "central-america-latest",
    "Togo": "togo-latest",
    "Benin": "benin-latest",
    "Cameroon": "cameroon-latest",
    "Gabon": "gabon-latest",
    "Long Island": "long-island",
    "New Jersey": "new-jersey",
    "Outer Banks": "outer-banks",
    "Florida Space Coast": "florida-space-coast",
    "South Florida": "south-florida",
    "Florida Northeast": "florida-northeast",
    "Florida Panhandle": "florida-panhandle",
    "Florida Gulf": "florida-gulf",
    "South Carolina": "south-carolina",
    "Georgia": "georgia",
    "Rhode Island": "rhode-island",
    "Massachusetts": "massachusetts",
    "New Hampshire": "new-hampshire",
    "Maine": "maine",
    "Texas": "texas",
    "Gulf Coast": "alabama-latest",
    "Delmarva": "delaware-latest",
    "Alaska": "alaska-latest",
    "Haida Gwaii": "british-columbia",
    "Virginia": "virginia",
    "Basque Country": "basque-country",
    "Cantabria": "cantabria",
    "Asturias": "asturias",
    "Galicia": "galicia",
    "Cadiz": "cadiz",
    "Canary Islands": "canary-islands",
    "Madeira": "madeira",
    "Cyprus": "cyprus",
    "Sicily": "sicily",
    "Scotland West": "scotland-west",
    "Scotland East": "scotland-east",
    "Norway South": "norway-south",
    "Lofoten": "lofoten",
    "Norway North": "norway-latest",
    "Iceland": "iceland",
    "South Korea": "south-korea",
    "Jeju": "jeju",
    "Samoa": "samoa",
    "New Caledonia": "new-caledonia",
    "Denmark": "denmark",
    "Netherlands": "netherlands",
    "Germany": "germany",
    "Sweden": "sweden",
    "Algeria": "algeria",
    "Rio Grande Do Sul": "rio-grande-do-sul",
    "Santa Catarina": "santa-catarina",
    "Parana": "parana",
    "Sao Paulo": "sao-paulo",
    "Rio De Janeiro": "rio-de-janeiro",
    "Espirito Santo": "espirito-santo",
    "Bahia": "bahia",
    "Pernambuco": "pernambuco",
    "Fernando De Noronha": "fernando-de-noronha",
    "Rio Grande Do Norte": "rio-grande-do-norte",
    "Ceara": "ceara",
    "Maranhao": "brazil-nordeste-latest",
    "Para": "brazil-norte-latest",
    "Hainan": "hainan",
    "Guangdong": "guangdong",
    "Hong Kong": "hong-kong",
    "Fujian": "fujian",
    "Zhejiang": "zhejiang",
    "Shandong": "shandong",
    "Catalonia": "catalonia",
    "Valencia": "valencia",
    "Murcia": "murcia",
    "Andalusia": "andalusia",
    "Balearic Islands": "balearic-islands",
    # gap batch 2026-11-12b (Poland, Lithuania, Latvia, Kamchatka: no local extract yet)
    "Newfoundland": "newfoundland-and-labrador-latest",
    "Gulf of St Lawrence": "quebec-latest",
    "Seychelles": "seychelles-latest",
    "Tanzania": "tanzania-latest",
    "Bangladesh": "bangladesh-latest",
    # gap batch 2026-11-12c (Christmas Island: no local extract)
    "Laayoune": "morocco",
    "Primorye": "far-eastern-fed-district-latest",
    "Sakhalin": "far-eastern-fed-district-latest",
    "Orkney and Shetland": "scotland-latest",
    "Marquesas": "french-polynesia",
    "Estonia": "estonia-latest",
    "Kaliningrad": "kaliningrad-latest",
}


def hav(a, b, c, d):
    R = 6371000
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


class Places(osmium.SimpleHandler):
    def __init__(self, box):
        super().__init__()
        self.hits = []
        self.box = box

    def node(self, n):
        t = n.tags
        p = t.get("place")
        if p not in PLACES:
            return
        nm = t.get("name:en") or t.get("name")
        if not nm:
            return
        la, lo = n.location.lat, n.location.lon
        s, w, nn, e = self.box
        if s <= la <= nn and w <= lo <= e:
            self.hits.append((nm, la, lo, p))


spots = json.load(open(sys.argv[1]))  # [{id, name, region, lat, lon}]
out = {}
for region, stem in REGION_PBF.items():
    rows = [s for s in spots if s["region"] == region]
    if not rows:
        continue
    box = (
        min(s["lat"] for s in rows) - 0.4,
        min(s["lon"] for s in rows) - 0.4,
        max(s["lat"] for s in rows) + 0.4,
        max(s["lon"] for s in rows) + 0.4,
    )
    h = Places(box)
    h.apply_file(f"data/osm/{stem}.osm.pbf")
    rank = {"city": 0, "town": 1, "village": 2, "hamlet": 3}
    for s in rows:
        cands = [(hav(s["lat"], s["lon"], p[1], p[2]), p) for p in h.hits]
        cands = [c for c in cands if c[0] <= 12000]
        if not cands:
            out[s["id"]] = None
            continue
        # nearest wins, but a town/city inside 1.6x the nearest hamlet's distance outranks it
        cands.sort(key=lambda c: c[0])
        best = cands[0]
        for d, p in cands:
            if d <= best[0] * 1.6 and rank[p[3]] < rank[best[1][3]]:
                best = (d, p)
        out[s["id"]] = {"town": best[1][0], "m": round(best[0]), "kind": best[1][3]}
    print(f"{region}: {len(rows)} spots", file=sys.stderr)
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
