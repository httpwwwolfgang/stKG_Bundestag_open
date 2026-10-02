import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand

ZIEL = zwischenstand.fuer(__file__)
from zugang import dsn
DSN = dsn()
SPARQL = "https://query.wikidata.org/sparql"
BLOCK = 50
PAUSE = 4.0

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("wikidata-geburtsorte")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("sKG-bundestag/1.0 (Masterarbeit, raeumlicher Knowledge Graph " "zum Bundestag; KONTAKT_EMAIL)"),
    "Accept": "application/sparql-results+json",
})

ABFRAGE = """
SELECT ?person ?ort ?ortLabel ?koord ?landLabel ?einheitLabel WHERE {
  VALUES ?person { %s }
  ?person wdt:P19 ?ort .
  OPTIONAL { ?ort wdt:P625 ?koord }
  OPTIONAL { ?ort wdt:P17 ?land }
  OPTIONAL { ?ort wdt:P131 ?einheit }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". }
}
"""


def frage(personen):
    for versuch in range(6):
        try:
            r = SESSION.post(SPARQL, data={"query": ABFRAGE % personen}, timeout=300)
            r.raise_for_status()
            return r.json()["results"]["bindings"]
        except (requests.RequestException, ValueError) as e:
            wart = 8 * (versuch + 1)
            log.warning("   Abfrage fehlgeschlagen (%s), warte %ds", str(e)[:70], wart)
            time.sleep(wart)
    raise SystemExit("Query Service antwortet nicht.")


def main():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT p.qid_wikidata, p.aw_id
                         FROM politiker_innen.politician p
                        WHERE p.aw_id IN (SELECT politician_id FROM politiker_innen.mandat)
                          AND p.qid_wikidata IS NOT NULL ORDER BY 1;""")
        nach_qid = dict(cur.fetchall())
    conn.close()
    log.info("%d Personen mit Mandat und Q-Nummer", len(nach_qid))

    qids = list(nach_qid)
    bloecke = [qids[i:i + BLOCK] for i in range(0, len(qids), BLOCK)]
    log.info("--- %d Abfragen zu je %d Personen ---", len(bloecke), BLOCK)

    orte = defaultdict(lambda: {"ort_qid": None, "ort": None, "koordinaten": set(),
                                "land": None, "einheit": None})
    for i, b in enumerate(bloecke, 1):
        for z in frage(" ".join(f"wd:{q}" for q in b)):
            q = z["person"]["value"].rsplit("/", 1)[-1]
            e = orte[q]
            e["ort_qid"] = z["ort"]["value"].rsplit("/", 1)[-1]
            e["ort"] = z.get("ortLabel", {}).get("value")
            if "koord" in z:
                e["koordinaten"].add(z["koord"]["value"])
            e["land"] = z.get("landLabel", {}).get("value") or e["land"]
            e["einheit"] = z.get("einheitLabel", {}).get("value") or e["einheit"]
        if i % 5 == 0 or i == len(bloecke):
            log.info("   %d/%d Bloecke, %d Personen mit Geburtsort",
                     i, len(bloecke), len(orte))
        if i < len(bloecke):
            time.sleep(PAUSE)

    ZIEL.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    ziel = ZIEL / f"wikidata_geburtsorte_{stempel}.json"
    ziel.write_text(json.dumps({
        "abgerufen_am": stempel, "quelle": SPARQL,
        "personen": {q: {"aw_id": nach_qid[q], **{k: (sorted(v) if isinstance(v, set) else v)
                                                  for k, v in e.items()}}
                     for q, e in orte.items()},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("   geschrieben: %s", ziel)

    mit_koord = sum(1 for e in orte.values() if e["koordinaten"])
    mehrfach = sum(1 for e in orte.values() if len(e["koordinaten"]) > 1)
    log.info("--- Was geholt wurde ---")
    log.info("   %d von %d Personen mit Geburtsort", len(orte), len(nach_qid))
    log.info("   %d davon mit Koordinate (%.1f %%), %d mit mehr als einer",
             mit_koord, 100 * mit_koord / max(len(orte), 1), mehrfach)
    laender = defaultdict(int)
    for e in orte.values():
        laender[e["land"] or "(ohne)"] += 1
    log.info("   Laender: %s", dict(sorted(laender.items(), key=lambda x: -x[1])[:8]))
    ohne = set(nach_qid) - set(orte)
    if ohne:
        log.warning("   %d Personen ohne P19 in Wikidata", len(ohne))


if __name__ == "__main__":
    main()
