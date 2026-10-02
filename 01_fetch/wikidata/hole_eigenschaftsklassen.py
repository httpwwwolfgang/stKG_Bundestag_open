import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import query

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

SPARQL = "https://query.wikidata.org/sparql"
import zwischenstand


LIEFERUNG = "wikidata_eigenschaftsklassen"
AUSGABE = zwischenstand.fuer(__file__)
BLOCK = 50
PAUSE = 4

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("sKG-bundestag/1.0 (Masterarbeit, raeumlicher Knowledge " "Graph zum Bundestag)"),
    "Accept": "application/sparql-results+json",
})

ABFRAGE = """
SELECT ?p ?pLabel ?pDescription ?art ?artLabel ?gegenstand ?gegenstandLabel
       ?gegenstandArt ?gegenstandArtLabel ?formatUrl
WHERE {
  VALUES ?p { %s }
  OPTIONAL { ?p wdt:P31 ?art . }
  OPTIONAL { ?p wdt:P1630 ?formatUrl . }
  OPTIONAL {
    ?p wdt:P1629 ?gegenstand .
    OPTIONAL { ?gegenstand wdt:P31 ?gegenstandArt . }
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". }
}
"""


def frage(werte):
    for versuch in range(6):
        try:
            r = SESSION.post(SPARQL, data={"query": ABFRAGE % werte},
                             timeout=300)
            r.raise_for_status()
            return r.json()["results"]["bindings"]
        except (requests.RequestException, ValueError) as e:
            wart = 8 * (versuch + 1)
            log.warning("   Abfrage fehlgeschlagen (%s), warte %ds",
                        str(e)[:70], wart)
            time.sleep(wart)
    raise SystemExit("Query Service antwortet nicht.")


def eigenschaften():
    zeilen = query("SELECT p_nummer, label, typ " "FROM politiker_innen.wikidata_eigenschaft " "ORDER BY p_nummer;")
    return [(str(a).strip(), str(b).strip(), str(c).strip())
            for a, b, c in zeilen]


def wert(b, name):
    x = b.get(name)
    return x["value"] if x else None


def kuerze(iri):
    return iri.rsplit("/", 1)[-1] if iri else None


def main():
    liste = eigenschaften()
    log.info("%d Eigenschaften aus wikidata_eigenschaft", len(liste))

    ergebnis = {p: {"label_db": lab, "typ_db": typ,
                    "art": [], "gegenstand": [], "gegenstand_art": [],
                    "format_url": [], "label_wd": None, "beschreibung": None}
                for p, lab, typ in liste}

    pnummern = [p for p, _, _ in liste]
    bloecke = [pnummern[i:i + BLOCK] for i in range(0, len(pnummern), BLOCK)]
    log.info("%d Bloecke zu %d", len(bloecke), BLOCK)

    for i, block in enumerate(bloecke, 1):
        werte = " ".join("wd:%s" % p for p in block)
        log.info("  Block %d/%d ...", i, len(bloecke))
        for b in frage(werte):
            p = kuerze(wert(b, "p"))
            if p not in ergebnis:
                continue
            e = ergebnis[p]
            e["label_wd"] = e["label_wd"] or wert(b, "pLabel")
            e["beschreibung"] = e["beschreibung"] or wert(b, "pDescription")
            for feld, iri_feld, label_feld in (
                    ("art", "art", "artLabel"),
                    ("gegenstand", "gegenstand", "gegenstandLabel"),
                    ("gegenstand_art", "gegenstandArt", "gegenstandArtLabel")):
                q = kuerze(wert(b, iri_feld))
                if q:
                    eintrag = {"qid": q, "label": wert(b, label_feld)}
                    if eintrag not in e[feld]:
                        e[feld].append(eintrag)
            f = wert(b, "formatUrl")
            if f and f not in e["format_url"]:
                e["format_url"].append(f)
        if i < len(bloecke):
            time.sleep(PAUSE)

    AUSGABE.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    ziel = AUSGABE / ("wikidata_eigenschaftsklassen_%s.json" % stempel)
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump({"abgerufen_am": stempel, "quelle": SPARQL,
                   "eigenschaften": ergebnis}, f, ensure_ascii=False, indent=1)

    ohne_art = sum(1 for e in ergebnis.values() if not e["art"])
    ohne_gegenstand = sum(1 for e in ergebnis.values() if not e["gegenstand"])
    log.info("")
    log.info("geschrieben: %s", ziel)
    log.info("  %d Eigenschaften ohne P31 (ist ein)", ohne_art)
    log.info("  %d Eigenschaften ohne P1629 (Gegenstand)", ohne_gegenstand)


if __name__ == "__main__":
    main()
