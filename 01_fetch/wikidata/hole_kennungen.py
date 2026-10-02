import csv
import glob
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2
import requests

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand
ZIEL = zwischenstand.fuer(__file__)
from zugang import dsn
DSN = dsn()
SPARQL = "https://query.wikidata.org/sparql"
BLOCK = 50
PAUSE = 4.0


TYPEN = {"ExternalId", "Monolingualtext", "Url", "String"}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("wikidata-kennungen")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("sKG-bundestag/1.0 (Masterarbeit, raeumlicher Knowledge Graph " "zum Bundestag; KONTAKT_EMAIL)"),
    "Accept": "application/sparql-results+json",
})

ABFRAGE = """
SELECT ?person ?prop ?wert WHERE {
  VALUES ?person { %s }
  VALUES ?prop { %s }
  ?prop wikibase:directClaim ?p .
  ?person ?p ?wert .
}
"""


def frage(personen, props):
    for versuch in range(6):
        try:
            r = SESSION.post(SPARQL, data={"query": ABFRAGE % (personen, props)},
                             timeout=300)
            r.raise_for_status()
            return r.json()["results"]["bindings"]
        except (requests.RequestException, ValueError) as e:
            wart = 8 * (versuch + 1)
            log.warning("   Abfrage fehlgeschlagen (%s), warte %ds",
                        str(e)[:70], wart)
            time.sleep(wart)
    raise SystemExit("Query Service antwortet nicht.")


def inventar():
    dateien = sorted(glob.glob(str(ZIEL / "wikidata_inventar_*.csv")))
    if not dateien:
        raise SystemExit("Kein Inventar da - erst inventar_gewaehlte.py laufen lassen.")
    with open(dateien[-1], encoding="utf-8", newline="") as f:
        zeilen = [z for z in csv.DictReader(f, delimiter=";") if z["typ"] in TYPEN]
    log.info("Inventar %s: %d Eigenschaften vom Typ %s",
             Path(dateien[-1]).name, len(zeilen), "/".join(sorted(TYPEN)))
    return {z["eigenschaft"]: (z["label"], z["typ"], float(z["anteil_prozent"]))
            for z in zeilen}


def main():
    eig = inventar()
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT p.aw_id, p.qid_wikidata
              FROM politiker_innen.politician p
             WHERE p.aw_id IN (SELECT politician_id FROM politiker_innen.mandat)
               AND p.qid_wikidata IS NOT NULL ORDER BY 2;""")
        paare = cur.fetchall()
    conn.close()
    nach_qid = {q: aw for aw, q in paare}
    log.info("%d Personen mit Mandat und Q-Nummer", len(nach_qid))

    qids = list(nach_qid)
    bloecke = [qids[i:i + BLOCK] for i in range(0, len(qids), BLOCK)]
    pw = " ".join(f"wd:{p}" for p in eig)
    log.info("--- %d Abfragen zu je %d Personen x %d Eigenschaften ---",
             len(bloecke), BLOCK, len(eig))

    werte = defaultdict(lambda: defaultdict(list))
    for i, b in enumerate(bloecke, 1):
        pers = " ".join(f"wd:{q}" for q in b)
        for z in frage(pers, pw):
            q = z["person"]["value"].rsplit("/", 1)[-1]
            p = z["prop"]["value"].rsplit("/", 1)[-1]
            werte[q][p].append(z["wert"]["value"])
        if i % 5 == 0 or i == len(bloecke):
            log.info("   %d/%d Bloecke, %d Personen mit mindestens einem Wert",
                     i, len(bloecke), len(werte))
        if i < len(bloecke):
            time.sleep(PAUSE)

    ZIEL.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    ziel = ZIEL / f"wikidata_kennungen_gewaehlte_{stempel}.json"
    ziel.write_text(json.dumps({
        "abgerufen_am": stempel,
        "quelle": SPARQL,
        "eigenschaften": {p: {"label": l, "typ": t, "abdeckung_prozent": a}
                          for p, (l, t, a) in eig.items()},
        "personen": {q: {"aw_id": nach_qid[q], "werte": dict(v)}
                     for q, v in werte.items()},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("   geschrieben: %s", ziel)

    gesamt = sum(len(w) for v in werte.values() for w in v.values())
    log.info("--- Was geholt wurde ---")
    log.info("   %d Personen, %d Werte, %d verschiedene Eigenschaften belegt",
             len(werte), gesamt, len({p for v in werte.values() for p in v}))
    ohne = set(nach_qid) - set(werte)
    if ohne:
        log.warning("   %d Personen ohne jede Kennung", len(ohne))


    gleich = sum(1 for q, v in werte.items()
                 if str(nach_qid[q]) in v.get("P5355", []))
    log.info("   P5355 gegen unsere aw_id: %d von %d gleich", gleich, len(nach_qid))


if __name__ == "__main__":
    main()
