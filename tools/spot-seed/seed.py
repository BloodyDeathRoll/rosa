#!/usr/bin/env python3
"""Rosa spot-seed pipeline:  GENERATE (coastline) -> PRUNE (bathy) -> VALIDATE (OSM).

Not a scraper of a spot-list (all such lists are tiny-open or proprietary). It
generates the candidate-break universe from the coast itself, prunes with seabed
physics, then confirms + names candidates against OSM surf features. Comprehensive
by construction; OSM is used only to CONFIRM/name (never to reject - its absence
is not evidence of absence).

Output tiers:
  A  generated + an OSM surf feature nearby   -> confirmed + named
  A- generated + a named beach nearby         -> confirmed, weak name
  B  generated, passed the gates, no OSM      -> plausible, unnamed (needs sat-verify)

Stages cache to work/<region>/ so a flaky Overpass or the OpenTopoData daily quota
never costs you finished work. Re-run resumes; --fresh <stage> forces a refetch.

Usage:
  python tools/spot-seed/seed.py sri-lanka
  python tools/spot-seed/seed.py sri-lanka --spacing 400 --fresh beacons
"""

from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
import urllib.parse
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coast_generate import bearing, hav_m
from bathy_gate import destination, gebco_elevations, classify, XSECT_KM, SHELF_MIN_KM
from osm_seed import BIZ_NAME_RE  # school/shop/rental/... - exclude from surf naming

# stopwords stripped before name-matching: surf vocabulary + PT/ES/generic geo words that
# would otherwise become match-everything tokens ("Praia", "Playa", "de", ...)
_STOP = re.compile(
    r"\b(surf|spot|point|beach|bay|reef|the|praia|playa|plage|de|da|do|dos|das|"
    r"del|el|la|los|las|do?s?|norte|sul|north|south|left|right|main)\b",
    re.I,
)


def norm_name(s):
    """lowercase, drop surf-spot stopwords + punctuation -> comparable token string."""
    s = _STOP.sub(" ", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(name):
    n = norm_name(name).replace(" ", "-")
    return re.sub(r"-+", "-", n).strip("-") or "spot"


ROOT = Path(__file__).resolve().parents[2]
SPOTS = ROOT / "data" / "spots"
WORK = Path(__file__).resolve().parent / "work"
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# surf-coast bbox per region (S, W, N, E). Sri Lanka = SW+S+E surf coast (skips the
# non-surf northern lagoons); others cover the mapped coast.
REGIONS = {
    "new-zealand": (-47.30, 166.35, -34.40, 178.60),
    "sri-lanka": (5.85, 79.60, 7.05, 81.95),
    "israel": (31.40, 34.20, 33.25, 35.20),
    "japan": (30.0, 129.0, 41.6, 142.2),
    "portugal": (36.90, -9.60, 42.20, -6.90),
    "costa-rica": (8.00, -85.95, 11.30, -82.50),
    "nicaragua": (10.70, -87.75, 15.05, -83.10),
    "philippines": (4.50, 116.90, 21.20, 126.70),
    "el-salvador": (13.10, -90.20, 13.65, -87.65),
    "mexico": (14.30, -118.60, 32.80, -91.90),
    # the whole Pacific coast, Imperial Beach to the Oregon line; the Channel Islands
    # fall inside it and are surfed, so they stay
    "california": (32.50, -124.60, 42.05, -117.05),
    # the open Pacific coast only - the Columbia mouth is shared, Puget Sound is excluded
    "oregon": (41.95, -124.70, 46.35, -123.30),
    # outer coast from the Columbia to Cape Flattery plus the Strait of Juan de Fuca as far
    # as Port Angeles (Crescent Bay / Salt Creek are surfed); Puget Sound is excluded
    "washington": (46.20, -124.90, 48.45, -123.40),
    # the Atlantic coast only, Cap Spartel down through Western Sahara to Dakhla; the
    # Mediterranean side is barely surfed and would drag in 400 km of flat coastline
    "morocco": (20.70, -17.40, 36.00, -5.30),
    # the whole Angolan coast incl. the Cabinda exclave - one open west-facing shore
    "angola": (-17.30, 11.40, -4.30, 13.90),
    # the whole Pacific coast, Tumbes to Tacna - Peru has no other shore
    "peru": (-18.40, -81.40, -3.35, -70.20),
    # both coasts: the Pacific (Santa Catalina, Venao) and the Caribbean (Bocas del Toro)
    "panama": (7.10, -83.10, 9.70, -77.10),
    # every atoll, Haa Alif in the north down to Addu; the chain is only ~130 km wide
    # so one box is the whole country
    "maldives": (-0.80, 72.50, 7.20, 73.85),
    # Sydney metro surf coast: Palm Beach down through the Northern Beaches, the eastern
    # suburbs and Cronulla to Garie in the Royal National Park; Sydney Harbour is inside
    # the box but bathy-prunes itself (enclosed water)
    "sydney": (-34.25, 150.80, -33.55, 151.40),
    # the far-north NSW surf coast around Byron Bay: Tweed Heads (the QLD line) down
    # through Cabarita, Brunswick Heads, Byron and Lennox Head to Ballina
    "byron-bay": (-28.95, 153.30, -28.15, 153.70),
    # the surfed islands only: the Society group (Tahiti, Moorea, Huahine, Raiatea,
    # Bora Bora) plus Rangiroa/Tikehau in the western Tuamotus; Marquesas and Australs
    # are barely surfed and would triple the box
    "french-polynesia": (-18.20, -152.10, -14.80, -147.50),
    # the surfed zone only: SW Viti Levu / Mamanucas, the Coral Coast, Beqa lagoon and
    # Kadavu - all west of 179 E, so the box never touches the antimeridian (the Lau
    # group would, and is not surfed enough to seed)
    "fiji": (-19.30, 176.70, -16.00, 179.00),
    # the three surfed islands - Kauai, Oahu and Maui (Molokai and Lanai fall inside the
    # box and are barely surfed); the Big Island is left out, it would add 2 deg of
    # mostly cliff coast for a handful of Hilo/Kona breaks
    "hawaii": (20.50, -159.85, 22.30, -155.90),
    # Perth metro surf coast: Mandurah up through Cottesloe, Scarborough/Trigg and the
    # northern beaches to Two Rocks, plus Rottnest Island offshore
    "perth": (-32.65, 115.40, -31.40, 115.85),
    # the Capes: Cape Naturaliste (Yallingup, Injidup) down through Gracetown and the
    # Margaret River mouth to Cape Leeuwin; Geographe Bay's sheltered east side is inside
    # the box but bathy-prunes itself
    "margaret-river": (-34.40, 114.90, -33.50, 115.25),
    # Bali plus Nusa Lembongan / Ceningan / Penida; the west edge stays east of Java's
    # tip (G-Land is a Java region) and the east edge short of Lombok
    "bali": (-8.90, 114.45, -8.05, 115.75),
    # Lombok: Desert Point on the SW tip, the whole south coast (Selong Belanak, Mawi,
    # Kuta, Gerupuk, Ekas) and the Senggigi west coast; the Gilis are inside and flat
    "lombok": (-9.15, 115.80, -8.20, 116.80),
    # Sumbawa's south and west coasts only: Sekongkang/Maluk (Scar Reef, Supersuck,
    # Yoyo's) in the west and Hu'u (Lakey Peak) in the south; the north coast is not
    # surfed and is left out
    "sumbawa": (-9.15, 116.70, -8.55, 118.65),
    # Java's south coast only, in two boxes (the north coast is unsurfed). East: Pacitan
    # (Watu Karung, Srau) through Malang's south coast and Red Island to G-Land at the
    # Blambangan tip
    "east-java": (-8.85, 110.95, -7.95, 114.45),
    # West: Sawarna and Pelabuhan Ratu / Cimaja, Ujung Genteng, then Batu Karas and
    # Pangandaran; the Bogor/Jakarta north stays out
    "west-java": (-7.85, 106.25, -6.90, 108.70),
    # Gold Coast: the QLD line at Coolangatta/Snapper up through Kirra, Currumbin, Burleigh
    # and Surfers to The Spit and South Stradbroke; Byron's box already holds Tweed Heads
    "gold-coast": (-28.18, 153.35, -27.80, 153.60),
    # Sunshine Coast: Caloundra up through Alexandra Headland, Coolum and Peregian to
    # Noosa's points
    "sunshine-coast": (-26.85, 152.95, -26.35, 153.20),
    # Victoria's Bass Strait surf: the Surf Coast from Lorne through Bells and Torquay,
    # the Mornington Peninsula back beaches and Phillip Island; Port Phillip Bay is inside
    # the box but bathy-prunes itself (enclosed water)
    "victoria": (-38.75, 143.85, -38.15, 145.45),
    # South Australia's surfed peninsulas: the Fleurieu (Middleton, Waitpinga, Parsons) and
    # the Yorke's southern foot (Pondalowie, Chinamans, Berry Bay); Kangaroo Island's north
    # coast is inside and flat, Cactus on the Eyre is its own region later
    "south-australia": (-35.70, 136.85, -34.85, 138.80),
    # Tasmania's east and south coasts: St Helens down through Bicheno, the Tasman Peninsula
    # (Shipstern, Eaglehawk Neck), Clifton and Bruny; Marrawah in the NW is left for later
    "tasmania": (-43.65, 146.80, -40.80, 148.40),
    # WA's Coral Coast north of Perth: Geraldton, Kalbarri, then Red Bluff and Gnaraloo;
    # 600 km of mostly empty coast, the box is what keeps the candidate count sane
    "wa-north": (-29.20, 113.30, -23.70, 114.90),
    # the Mentawai chain, Siberut down to South Pagai; the Sumatran mainland stays east of
    # the box (Padang is at 100.35, the chain's east edge is ~100.5)
    "mentawai": (-3.30, 98.60, -0.85, 100.55),
    # Japan's southern islands, north half: Tanegashima and Yakushima (just south of the
    # japan box's 30.0 edge), Amami Oshima, Tokunoshima and Okinoerabu
    "tanegashima-amami": (27.0, 128.3, 30.9, 131.2),
    # south half: Okinawa main island and the Keramas, Miyako and the Yaeyamas (Ishigaki,
    # Iriomote); Daito and Yonaguni are out
    "okinawa": (24.0, 122.9, 27.0, 128.5),
    # Hokkaido, north of the japan box's 41.6 edge: Hakodate, the Tomakomai-Muroran
    # Pacific beaches, Hidaka and Tokachi, the Otaru-Ishikari Sea of Japan coast
    "hokkaido": (41.40, 139.30, 45.60, 146.00),
    # the WA west-coast gaps, closed 2026-09-03: Two Rocks up through Lancelin, Cervantes,
    # Jurien Bay and Green Head to Dongara (the perth box ends at -31.40, wa-north starts
    # at -29.20)
    "wa-midwest": (-31.40, 114.80, -29.20, 115.45),
    # Mandurah down to Cape Naturaliste: Myalup, Binningup, Bunbury's back beach; Geographe
    # Bay is inside and sheltered (the perth box ends at -32.65, margaret-river starts at -33.50)
    "bunbury": (-33.55, 115.35, -32.65, 115.80),
    # north of Gnaraloo: Coral Bay to Exmouth and the Ningaloo reef breaks around the North
    # West Cape (wa-north ends at -23.70)
    "exmouth": (-23.70, 113.60, -21.75, 114.35),
    # WA's south coast: Augusta (east of the margaret-river box) through Windy Harbour,
    # Walpole, Denmark and Albany to Bremer Bay
    "wa-south": (-35.20, 115.25, -34.20, 119.50),
    # Esperance and the Cape Le Grand beaches; the Recherche islands are inside and flat
    "esperance": (-34.10, 121.40, -33.60, 122.60),
    # UK: Cornwall and Devon, both coasts (Sennen and Porthleven in the far west, Newquay,
    # Bude, then Croyde / Saunton / Woolacombe on the north Devon coast and Bantham in
    # the south); the Bristol Channel side of Somerset is out
    "cornwall-devon": (49.95, -5.75, 51.25, -3.85),
    # Wales: the Gower (Llangennith, Rhossili) and Pembrokeshire (Freshwater West,
    # Manorbier, Newgale); Cardigan Bay is out
    "wales": (51.55, -5.35, 51.80, -3.95),
    # the north Scottish coast around Thurso (Thurso East, Brims Ness, Melvich, Torrisdale)
    "north-scotland": (58.45, -4.45, 58.70, -3.05),
    # the north-east English coast from Tynemouth down through Saltburn and Whitby to
    # Scarborough and Cayton Bay
    "north-east-england": (54.20, -1.65, 55.10, -0.30),
    # France, the Landes / Basque coast: Anglet and Biarritz up through Hossegor and
    # Capbreton, Mimizan and Biscarrosse to Lacanau
    "landes": (43.35, -1.85, 45.10, -1.05),
    # Brittany's Atlantic tip: La Torche and the Pays Bigouden, Crozon, Quiberon
    "brittany": (47.45, -4.85, 48.75, -3.00),
    # Senegal: the Dakar peninsula (Ngor, Ouakam, the Almadies reefs, Yoff, Virage),
    # the Petite Cote south to Toubab Dialaw and Somone, and Cap Skirring in Casamance
    "senegal": (12.25, -17.60, 14.90, -16.65),
    # Cape Verde's surfed islands: Sal and Boa Vista in the east, Sao Vicente in the
    # north-west; Santiago's south coast is barely surfed and is left out
    "cape-verde": (15.95, -25.10, 16.95, -22.65),
    # Ghana's west coast (Busua, Dixcove) east through Cape Coast to Accra and Kokrobite.
    # Togo is NOT in here: it needs its own Geofabrik extract, and Lome fell out of the
    # 2026-09-03 pass with "no coastline candidate within reach" because only ghana.pbf
    # was linked. Seed it as its own region when someone wants Lome.
    "ghana": (4.65, -2.65, 6.30, 0.20),
    # South Africa's Indian Ocean coast: Jeffreys Bay and Cape St Francis in the Eastern
    # Cape, then the KwaZulu-Natal points from Scottburgh through Durban to Ballito.
    # The Cape Peninsula and the west coast are their own region later.
    "south-africa-east": (-34.30, 24.60, -29.30, 31.40),
    # South Africa's Atlantic and southern Cape: the Garden Route (Mossel Bay, Victoria
    # Bay, Stilbaai) west of Cape St Francis, Agulhas, the Overberg, the Cape Peninsula,
    # then the west coast (Elands Bay, Lamberts Bay) north to the Orange River border.
    # Its E edge is south-africa-east's W edge, so no break is offered twice.
    "south-africa-west": (-34.90, 16.40, -28.62, 24.60),
    # Namibia's whole coast, Orange River to the Kunene: Luderitz, the Walvis Bay /
    # Swakopmund / Skeleton Bay stretch, Henties Bay and the Skeleton Coast. Its N edge is
    # angola's S edge.
    "namibia": (-28.62, 11.70, -17.30, 15.40),
    # Mozambique's surfed south: Ponta do Ouro and Ponta Malongane on the border, then
    # Tofo and Tofinho up at Inhambane
    "mozambique": (-27.00, 32.60, -10.40, 40.90),
    # Kenya's Diani coast and Tanzania's Zanzibar: reef and lagoon breaks on the
    # monsoon swell. Two countries, but ONE box needs ONE extract - kenya.pbf covers
    # Diani; Zanzibar is in tanzania.pbf and gets its own region below.
    "kenya": (-4.75, 39.10, -3.90, 39.90),
    # Zanzibar's east coast: Paje, Jambiani, Dongwe
    "zanzibar": (-6.60, 39.30, -5.70, 39.65),
    # Madagascar: the east coast faces open Indian Ocean swell; the south tip
    # catches Southern Ocean groundswell. West coast is sheltered by Mozambique Channel.
    "madagascar": (-25.70, 43.10, -12.00, 50.60),
    # Mauritius: small volcanic island fully exposed to Indian Ocean + S.O. swell
    "mauritius": (-20.60, 57.25, -19.95, 57.85),
    # ---- the US east coast. Every box is Atlantic-facing only; bays, sounds and the
    # Gulf side are excluded, and each box is scoped to ONE state extract.
    # New York's ocean beaches: Rockaway and Long Beach west, the Fire Island barrier,
    # then the Hamptons out to Montauk. Long Island Sound is north of the box and is not
    # surfed; NYC's harbour is west of it.
    "long-island": (40.53, -74.05, 41.10, -71.83),
    # the whole Jersey Shore, Sandy Hook to Cape May. Delaware Bay is west of the box.
    "new-jersey": (38.90, -75.00, 40.50, -73.90),
    # North Carolina's barrier islands: Nags Head and Cape Hatteras out to Ocracoke, plus
    # Wrightsville in the south. Pamlico and Albemarle Sounds fall inside the box's
    # rectangle but carry no ocean swell - the bathy gate drops them.
    "outer-banks": (33.70, -78.10, 36.60, -75.40),
    # Florida's Space Coast: Sebastian Inlet, Melbourne, Cocoa Beach, Playalinda and New
    # Smyrna. The box stops short of the Gulf side; Florida's south-east and north-east
    # are their own regions later.
    "florida-space-coast": (27.30, -80.95, 29.30, -80.30),
    # Rhode Island's ocean shore: Narragansett and Point Judith, Matunuck and the south
    # county beaches, and Newport's Atlantic side. Narragansett Bay is inside the
    # rectangle and carries no swell.
    "rhode-island": (41.13, -71.90, 41.55, -71.10),
    # ---- Spain. One box per autonomous community, each on its own Geofabrik extract
    # (europe/spain/<community>); the Mediterranean coast is barely surfed and is left out.
    # The Basque coast from Hondarribia west past Zarautz, Mundaka and Sopelana to Muskiz.
    # Its east edge overlaps the landes box by 0.07 deg at Hendaye - a hit there is France's.
    "basque-country": (43.28, -3.20, 43.48, -1.78),
    # Cantabria: Laredo and Berria, Somo, Santander, Liencres, Los Locos, San Vicente
    "cantabria": (43.30, -4.55, 43.52, -3.15),
    # Asturias: Llanes and Ribadesella west through Rodiles, Gijon, Salinas to Tapia
    "asturias": (43.35, -7.10, 43.70, -4.50),
    # Galicia: the north coast (Ferrol's Pantin and Doninos, Valdovino) and the west
    # (Razo, the Costa da Morte, the Rias Baixas beaches down to A Guarda)
    "galicia": (41.85, -9.35, 43.82, -7.00),
    # Cadiz: the Atlantic side of Andalucia, Chipiona and El Palmar down to Los Canos and
    # Tarifa. The andalucia extract also holds the Mediterranean coast, which is outside
    # this box.
    "cadiz": (35.95, -6.45, 36.85, -5.50),
    # the Canary Islands, all seven (africa/canary-islands - NOT europe/spain/canarias,
    # which 404s to a 9 KB HTML page)
    "canary-islands": (27.60, -18.20, 29.45, -13.30),
    # Cyprus, the whole island: Paphos and the west coast, Limassol, Larnaca and Ayia Napa
    "cyprus": (34.55, 32.25, 35.72, 34.62),
    # Sicily, the whole island plus the Egadi (europe/italy/isole - the extract also holds
    # Sardinia, which is outside this box). Lampedusa and Pantelleria are not seeded.
    "sicily": (36.60, 12.25, 38.35, 15.70),
    # ---- northern Europe (2026-09-29). Scotland on europe/united-kingdom/scotland; the
    # North Sea / Baltic countries on their own country extracts.
    # Scotland's Atlantic side: Kintyre (Machrihanish, Westport), Islay, Tiree, the Outer
    # Hebrides (Lewis, Harris) and the north-west mainland to Durness. The north coast from
    # Farr east is north-scotland's.
    "scotland-west": (55.25, -7.70, 58.65, -4.50),
    # Scotland's North Sea side: the Moray coast (Sandend, Lossiemouth), Fraserburgh,
    # Aberdeen, Lunan Bay, Fife (St Andrews) and East Lothian (Belhaven, Pease Bay)
    "scotland-east": (55.85, -3.60, 57.75, -1.75),
    # Norway's south-west: Lista and Jaeren (Borestranda, Brusand, Point Perfect) north to
    # Stad (Hoddevik, Ervik). Lofoten is its own box.
    "norway-south": (57.95, 4.80, 62.30, 7.20),
    # Lofoten: Unstad, Flakstad, Skagsanden
    "lofoten": (67.85, 12.90, 68.45, 14.50),
    # Denmark: the North Sea coast of Jutland (Klitmoller "Cold Hawaii", Hanstholm, Hvide
    # Sande, Lokken, Skagen) and north Zealand's Kattegat shore (Hornbaek)
    "denmark": (55.00, 7.95, 57.80, 12.70),
    # the Dutch coast: Zeeland (Domburg, Westkapelle) north through Scheveningen,
    # Zandvoort and Wijk aan Zee to the Wadden islands
    "netherlands": (51.35, 3.35, 53.55, 7.00),
    # Germany's two coasts on a merged extract (schleswig-holstein + niedersachsen +
    # mecklenburg-vorpommern = data/osm/germany-coast.osm.pbf): the North Sea (Sylt,
    # St Peter-Ording, Norderney) and the Baltic (Fehmarn, Weissenhaus, Warnemuende, Ruegen)
    "germany": (53.40, 6.60, 55.10, 14.50),
    # Sweden: the Halland / Kattegat west coast (Apelviken, Tylosand), Skane (Molle) and
    # the Baltic east coast (Toro)
    "sweden": (55.30, 11.10, 59.00, 18.50),
    # Algeria's whole Mediterranean coast, the Moroccan border to Tunisia: Oran and
    # Mostaganem in the west, the Algiers / Tipaza beaches, Bejaia, Jijel, Skikda, Annaba
    "algeria": (35.05, -2.25, 37.15, 8.65),
    # ---- Brazil. One box per surfed state, on three Geofabrik extracts
    # (south-america/brazil/{sul,sudeste,nordeste}). Alagoas, Sergipe, Paraiba, Piaui and
    # the Amazon coast are not seeded.
    # Rio Grande do Sul: the straight open beach from Torres south to Cidreira
    "rio-grande-do-sul": (-30.40, -50.60, -29.20, -49.60),
    # Santa Catarina: Laguna, Imbituba and Garopaba, Florianopolis, Balneario Camboriu,
    # Sao Francisco do Sul
    "santa-catarina": (-28.95, -49.10, -26.00, -48.30),
    # Parana's short coast: Pontal do Parana, Matinhos, Ilha do Mel
    "parana": (-25.95, -48.70, -25.25, -48.05),
    # Sao Paulo: the south-facing coast from Guaruja through Maresias to Ubatuba
    "sao-paulo": (-25.30, -48.10, -23.30, -44.70),
    # Rio de Janeiro: Paraty and Rio city east through Saquarema, Arraial do Cabo, Buzios
    "rio-de-janeiro": (-23.40, -44.75, -21.30, -40.95),
    # Espirito Santo: Guarapari, Vila Velha, Vitoria, Regencia
    "espirito-santo": (-21.35, -41.05, -18.30, -39.60),
    # Bahia: Itacare and the cacao coast, Salvador, Praia do Forte north to Mangue Seco
    "bahia": (-18.40, -40.00, -11.40, -37.30),
    # Pernambuco's mainland: Recife and Porto de Galinhas / Maracaipe
    "pernambuco": (-9.45, -35.30, -7.50, -34.75),
    # Fernando de Noronha, 350 km offshore - its own box so Pernambuco's is not the ocean
    "fernando-de-noronha": (-3.90, -32.50, -3.80, -32.35),
    # Rio Grande do Norte: Pipa and Natal, then the north-facing coast west to Tibau
    "rio-grande-do-norte": (-6.50, -38.00, -4.80, -34.95),
    # Ceara: Fortaleza, Paracuru, Taiba and Jericoacoara on the north-facing trade coast
    "ceara": (-4.90, -41.40, -2.70, -37.20),
    # the Brazilian north-east gaps closed 2026-09-16, all three on the nordeste extract
    # Paraiba: Joao Pessoa's city beaches (Cabo Branco, Bessa) and Tambaba south of it.
    # The N edge is the Rio Guaju, the PB/RN border - at -6.00 the box overran into Rio
    # Grande do Norte and re-offered Baia Formosa's already-seeded pontal as NEW (2026-09-16)
    "paraiba": (-7.95, -35.15, -6.47, -34.60),
    # Alagoas: Maceio, Praia do Frances and Barra de Sao Miguel
    "alagoas": (-10.55, -36.40, -8.80, -35.10),
    # Sergipe: Aracaju's beaches and the Atalaia / Mosqueiro coast
    "sergipe": (-11.60, -37.60, -10.00, -36.35),
    # ---- the Pacific coast of South America south of Peru. Chile is 4,000 km of one
    # west-facing coastline, so it is three boxes on one `south-america/chile` extract;
    # the Southern Ocean groundswell is the same everywhere, the wind and the shelf are not
    # Chile north: Arica, Iquique and Antofagasta on the desert coast
    "chile-north": (-27.00, -71.70, -18.30, -69.80),
    # Chile central: Coquimbo and La Serena through Valparaiso / Ritoque and Pichilemu
    # (Punta de Lobos) down to Constitucion
    "chile-central": (-35.50, -72.60, -27.00, -70.30),
    # Chile south: Cobquecura and Buchupureo, the Concepcion beaches, Arauco and Lebu
    "chile-south": (-42.00, -75.00, -35.50, -72.20),
    # Ecuador's mainland coast: Montanita and Ayampe in the south, Manta, Canoa and
    # Mompiche north; the Galapagos are 900 km offshore and not seeded
    "ecuador": (-3.50, -81.20, 1.60, -79.40),
    # ---- the south-west Atlantic. Uruguay and Argentina face E-SE into the same swell
    # Uruguay: Montevideo east through Punta del Este, La Paloma and Punta del Diablo
    "uruguay": (-35.10, -56.60, -33.60, -53.10),
    # Argentina's Buenos Aires coast: Mar del Plata, Miramar, Necochea and Claromeco.
    # N edge moved -36.90 -> -36.60 on 2026-09-16: Mar de Ajo and Punta Medanos are
    # surfed and sat just outside the first box
    "mar-del-plata": (-39.10, -61.50, -36.60, -56.60),
    # Argentine Patagonia: El Condor and Las Grutas on the Rio Negro coast, then Playa
    # Union / Rawson and Rada Tilly in Chubut - the box spans both provinces, which is
    # why the region is not called "chubut" (2026-09-16: 9 of its 16 spots are Rio Negro)
    "patagonia-argentina": (-46.00, -68.00, -40.50, -62.00),
    # ---- Melanesia, seeded 2026-09-21. PNG's surf zone is two clusters ~1,300 km apart
    # on the same north coast (permit-limited Kavieng/New Ireland, and Vanimo/West Sepik
    # near the Indonesian border) - too far apart for one box without swallowing most of
    # the Bismarck Sea, so each gets its own region key; both emit into papua-new-guinea.yaml
    "papua-new-guinea-kavieng": (-3.20, 150.60, -2.30, 151.00),
    "papua-new-guinea-vanimo": (-3.20, 141.00, -2.40, 142.00),
    # Vanuatu: Efate (Port Vila - Pango Point, Breakas, Erakor, Eratap) and Tanna
    # (Lenakel, Port Resolution); Santo, Malekula and the Banks/Torres group are not surfed
    "vanuatu": (-19.70, 168.20, -17.50, 169.00),
    # Solomon Islands' Western Province only: Gizo/Ghizo (Titiana, Naru, Paelonge) to
    # Munda/New Georgia (Skull Island, VonaVona Lagoon); Guadalcanal/Honiara and the
    # eastern provinces are not a known surf zone
    "solomon-islands": (-8.60, 156.80, -7.80, 158.00),
    # New Caledonia: the Noumea lagoon (Dumbea Pass, Ouano, Gouaro) plus the Isle of Pines;
    # the long northern two-thirds of Grande Terre is left out
    "new-caledonia": (-22.80, 166.20, -21.90, 167.60),
    # Samoa: Upolu (Apia, Boulders, Salani, Tiavea) and Savai'i (Aganoa, Manase, Lano,
    # Fagamalo, Satuiatua) - both islands, Apia to Salelologa
    "samoa": (-14.10, -172.85, -13.40, -171.35),
    # Cook Islands: Rarotonga only - Aitutaki's reef is a closeout/kitesurf destination,
    # no named surf break in any guide, so it is not scoped
    "cook-islands": (-21.30, -159.85, -21.15, -159.70),
}


def overpass(q, tag):
    data = urllib.parse.urlencode({"data": q}).encode()
    for rnd in range(3):
        for ep in OVERPASS:
            try:
                req = urllib.request.Request(
                    ep, data=data, headers={"User-Agent": "rosa-spot-seed/0.2"}
                )
                with urllib.request.urlopen(req, timeout=180) as r:
                    return json.load(r).get("elements", [])
            except Exception as ex:
                print(f"  [{tag}] {ep.split('//')[1].split('/')[0]} failed: {ex}", file=sys.stderr)
                time.sleep(3)
        time.sleep(10 * (rnd + 1))
    raise RuntimeError(f"overpass failed for {tag} on all mirrors")


def cache_path(region, name):
    d = WORK / region
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{name}.json"


def cached(region, name, fresh_set, producer):
    p = cache_path(region, name)
    if p.exists() and name not in fresh_set:
        return json.load(open(p))
    val = producer()
    json.dump(val, open(p, "w"))
    return val


def load_existing(region):
    text = (SPOTS / f"{region}.yaml").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"\bid:\s*([a-z0-9-]+)", text):
        seg = text[m.start() : m.start() + 400]
        la = re.search(r"\blat:\s*(-?[0-9.]+)", seg)
        lo = re.search(r"\blon:\s*(-?[0-9.]+)", seg)
        nm = re.search(r'\bname:\s*"([^"]+)"', seg)
        if la and lo:
            out.append(
                {
                    "id": m.group(1),
                    "name": nm.group(1) if nm else m.group(1),
                    "lat": float(la.group(1)),
                    "lon": float(lo.group(1)),
                }
            )
    return out


def fetch_coastline(bbox):
    s, w, n, e = bbox
    return overpass(
        f'[out:json][timeout:180];way["natural"="coastline"]({s},{w},{n},{e});out geom;',
        "coastline",
    )


def generate(ways, spacing, cluster):
    raw = []
    for wy in ways:
        pts = [(g["lat"], g["lon"]) for g in wy.get("geometry", [])]
        acc = spacing
        for i in range(1, len(pts)):
            a, b = pts[i - 1], pts[i]
            acc += hav_m(*a, *b)
            if acc >= spacing:
                acc = 0.0
                seaward = (bearing(*a, *b) + 90) % 360  # OSM: water on the right of way dir
                raw.append(
                    {
                        "lat": round(b[0], 6),
                        "lon": round(b[1], 6),
                        "seaward": round(seaward),
                        "offshore_direction": round((seaward + 180) % 360),
                    }
                )
    # O(n) spatial-grid clustering (an O(n^2) all-pairs check chokes on the 100k-way
    # coastlines of Japan/Philippines). Bucket into ~cluster-sized cells; a point is kept
    # only if no already-kept point in its own or the 8 neighbouring cells is within cluster m.
    cell = max(cluster, 1.0) / 111000.0  # deg (lat; conservative for lon)
    grid, clustered = {}, []
    for p in sorted(raw, key=lambda p: (p["lat"], p["lon"])):
        gi, gj = int(p["lat"] / cell), int(p["lon"] / cell)
        near = (
            c for di in (-1, 0, 1) for dj in (-1, 0, 1) for c in grid.get((gi + di, gj + dj), ())
        )
        if all(hav_m(p["lat"], p["lon"], c["lat"], c["lon"]) > cluster for c in near):
            clustered.append(p)
            grid.setdefault((gi, gj), []).append(p)
    return clustered


def bathy_prune(cands, elev_fn):
    pts = []
    for c in cands:
        pts += [destination(c["lat"], c["lon"], c["seaward"], d) for d in XSECT_KM]
    elev = elev_fn(pts)
    kept, dropped = [], 0
    for i, c in enumerate(cands):
        ev = elev[i * len(XSECT_KM) : (i + 1) * len(XSECT_KM)]
        shelf = [ev[j] for j, d in enumerate(XSECT_KM) if d >= SHELF_MIN_KM]
        ok, _ = classify(shelf)
        if ok:
            kept.append(c)
        else:
            dropped += 1
    return {"kept": kept, "dropped": dropped}


def fetch_beacons(bbox):
    s, w, n, e = bbox
    q = (
        f"[out:json][timeout:120];("
        f'node["sport"="surfing"]({s},{w},{n},{e});'
        f'way["sport"="surfing"]({s},{w},{n},{e});'
        f'node["natural"="beach"]({s},{w},{n},{e});'
        f'way["natural"="beach"]({s},{w},{n},{e});'
        f");out center tags;"
    )
    out = []
    for el in overpass(q, "beacons"):
        t = el.get("tags", {})
        nm = t.get("name:en") or t.get("name")
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None:
            continue
        is_surf = t.get("sport") == "surfing" or (nm and "surf" in nm.lower())
        # a surf SCHOOL/SHOP marks a break but is a bad spot NAME - exclude from naming
        if nm and BIZ_NAME_RE.search(nm):
            is_surf = False
        out.append({"name": nm, "lat": lat, "lon": lon, "surf": bool(is_surf)})
    return out


def tier(kept, beacons, name_match):
    surf = [b for b in beacons if b["surf"] and b["name"]]
    beach = [b for b in beacons if not b["surf"] and b["name"]]
    A, Ab, B = [], [], []
    for c in kept:
        ds = [(hav_m(c["lat"], c["lon"], b["lat"], b["lon"]), b) for b in surf]
        db = [(hav_m(c["lat"], c["lon"], b["lat"], b["lon"]), b) for b in beach]
        ds.sort(key=lambda x: x[0])
        db.sort(key=lambda x: x[0])
        if ds and ds[0][0] <= name_match:
            A.append({**c, "osm_name": ds[0][1]["name"], "osm_m": round(ds[0][0])})
        elif db and db[0][0] <= name_match:
            Ab.append({**c, "osm_name": db[0][1]["name"], "osm_m": round(db[0][0])})
        else:
            B.append(c)
    return A, Ab, B


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region", choices=list(REGIONS))
    ap.add_argument("--spacing", type=float, default=400)
    ap.add_argument("--cluster", type=float, default=400)
    ap.add_argument("--name-match", type=float, default=450)
    ap.add_argument(
        "--bathy",
        choices=["auto", "local", "api"],
        default="auto",
        help="seabed source: local GEBCO grid, OpenTopoData API, or auto (local if present)",
    )
    ap.add_argument(
        "--osm",
        choices=["auto", "local", "api"],
        default="auto",
        help="OSM source: local Geofabrik .osm.pbf, Overpass API, or auto (local if present)",
    )
    ap.add_argument(
        "--fresh", nargs="*", default=[], help="stages to refetch: coastline generate bathy beacons"
    )
    a = ap.parse_args()
    bbox = REGIONS[a.region]
    fresh = set(a.fresh)

    grid = Path(__file__).resolve().parents[2] / "data" / "bathy" / "GEBCO_2024.nc"
    if a.bathy == "local" or (a.bathy == "auto" and grid.exists()):
        from local_bathy import LocalGebco

        elev_fn = LocalGebco().elevations
        bsrc = "local GEBCO_2024 grid (offline, uncapped)"
    else:
        elev_fn = gebco_elevations
        bsrc = "OpenTopoData API (1000/day cap)"

    pbf = Path(__file__).resolve().parents[2] / "data" / "osm" / f"{a.region}.osm.pbf"
    use_local_osm = a.osm == "local" or (a.osm == "auto" and pbf.exists())
    osrc = "local Geofabrik extract (offline)" if use_local_osm else "Overpass API"
    _osm = {}

    def _local_osm():
        if not _osm:
            from osm_local import extract_region

            _osm["coast"], _osm["beacons"] = extract_region(pbf)
        return _osm["coast"], _osm["beacons"]

    def get_coastline():
        if use_local_osm:
            coast, _b = _local_osm()
            return [{"geometry": [{"lat": la, "lon": lo} for la, lo in w]} for w in coast]
        return fetch_coastline(bbox)

    def get_beacons():
        if use_local_osm:
            _c, beacons = _local_osm()
            s, w, n, e = bbox
            return [b for b in beacons if s <= b["lat"] <= n and w <= b["lon"] <= e]
        return fetch_beacons(bbox)

    ways = cached(a.region, "coastline", fresh, get_coastline)
    print(f"1) coastline ({osrc}): {len(ways)} ways", file=sys.stderr)
    cands = cached(
        a.region,
        "candidates",
        fresh | ({"generate"} if fresh else set()),
        lambda: generate(ways, a.spacing, a.cluster),
    )
    if use_local_osm:  # local coastline is whole-country - scope to the region's surf bbox
        s, w, n, e = bbox
        cands = [c for c in cands if s <= c["lat"] <= n and w <= c["lon"] <= e]
    print(f"2) generate: {len(cands)} candidates @ {a.spacing:.0f} m", file=sys.stderr)
    bathy = cached(a.region, "bathy", fresh, lambda: bathy_prune(cands, elev_fn))
    kept = bathy["kept"]
    print(
        f"3) bathy prune ({bsrc}): {len(cands)} -> {len(kept)} (dropped {bathy['dropped']})",
        file=sys.stderr,
    )
    beacons = cached(a.region, "beacons", fresh, get_beacons)
    nsurf = sum(1 for b in beacons if b["surf"] and b["name"])
    print(f"4) OSM beacons: {len(beacons)} ({nsurf} named surf features)", file=sys.stderr)

    A, Ab, B = tier(kept, beacons, a.name_match)
    existing = load_existing(a.region)
    ex_tokens = []
    for e in existing:
        toks = set(norm_name(e["name"]).split()) | set(e["id"].split("-"))
        ex_tokens.append({**e, "tokens": {t for t in toks if len(t) > 2}})

    # one candidate per OSM name (nearest), then classify HAVE vs NEW (name-aware)
    byname = {}
    for c in A:
        if c["osm_name"] not in byname or c["osm_m"] < byname[c["osm_name"]]["osm_m"]:
            byname[c["osm_name"]] = c
    have, corrections, new = [], [], []
    for c in sorted(byname.values(), key=lambda c: (c["lat"], c["lon"])):
        toks = {t for t in norm_name(c["osm_name"]).split() if len(t) > 2}
        # a brand-new region has no existing pins: every Tier-A candidate is NEW by
        # construction, so stand in an infinite nearest-distance rather than min() on []
        near = (
            min(existing, key=lambda e: hav_m(c["lat"], c["lon"], e["lat"], e["lon"]))
            if existing
            else None
        )
        dm = round(hav_m(c["lat"], c["lon"], near["lat"], near["lon"])) if near else 10**9
        name_hit = next((e for e in ex_tokens if toks & e["tokens"]), None)
        if name_hit and dm <= 5000:  # same name AND within 5 km -> our pin, plausibly off
            (corrections if dm > 600 else have).append((c, name_hit["id"], dm))
        elif dm <= 400:  # unnamed-match: same spot, different label
            have.append((c, near["id"], dm))
        else:  # distinct spot (a far coincidental name-match is NEW)
            new.append((c, dm))

    # dedup NEW by slug, build ready-to-add records with derived offshore_point + coast
    taken = {e["id"] for e in existing}
    records, seen_slug = [], set()
    for c, dm in sorted(new, key=lambda x: -x[0]["lat"]):
        sid = slug(c["osm_name"])
        if sid in seen_slug:
            continue
        seen_slug.add(sid)
        base = sid
        k = 2
        while sid in taken:
            sid = f"{base}-{k}"
            k += 1
        taken.add(sid)
        # The deep-water sample is a DISTANCE along this spot's own seaward normal, not an
        # absolute point: emit_spots.py writes it as offshore_km so it follows the pin.
        records.append(
            {
                "id": sid,
                "name": c["osm_name"],
                "lat": round(c["lat"], 4),
                "lon": round(c["lon"], 4),
                "offshore_direction": c["offshore_direction"],
                "seaward": (c["offshore_direction"] + 180) % 360,
                "offshore_km": 5.0,
            }
        )

    print(f"\n=== {a.region}: proper review ===")
    print(f"coastline candidates (bathy-passed) : {len(kept)}")
    print(f"OSM-named surf spots (Tier A)        : {len(byname)}")
    print(f"  already in DB (name/<400 m)        : {len(have)}")
    print(f"  pin CORRECTIONS (same name, >600 m): {len(corrections)}")
    print(f"  NEW distinct spots                 : {len(records)}")
    print(f"Tier A- (named beach only)           : {len(Ab)}")
    print(f"Tier B (plausible, unnamed)          : {len(B)}")
    print(f"our DB has                           : {len(existing)} spots\n")
    if corrections:
        print("--- PIN CORRECTIONS (we have these, OSM says our pin is off) ---")
        for c, eid, dm in corrections:
            print(
                f'  {eid:20} our pin is {dm} m from OSM "{c["osm_name"]}" @ {c["lat"]:.5f},{c["lon"]:.5f}'
            )
    print("\n--- NEW spots to add ---")
    for r in records:
        print(
            f"  {r['id']:22} {r['lat']:.4f},{r['lon']:.4f}  offdir {r['offshore_direction']:>3}°  "
            f'seaward {r["seaward"]:>3}°  "{r["name"]}"'
        )

    json.dump(
        {
            "new": records,
            "corrections": [{"id": e, "m": dm, "osm": c["osm_name"]} for c, e, dm in corrections],
        },
        open(cache_path(a.region, "result"), "w"),
        indent=1,
        ensure_ascii=False,
    )
    print(f"\nresult -> {cache_path(a.region, 'result')}")


if __name__ == "__main__":
    main()
