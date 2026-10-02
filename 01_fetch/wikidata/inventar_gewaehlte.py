import csv
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
PAUSE = 2.0

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("wikidata-inventar")

SESSION = requests.Session()
SESSION.headers.update({

    "User-Agent": ("sKG-bundestag/1.0 (Masterarbeit, raeumlicher Knowledge Graph " "zum Bundestag; KONTAKT_EMAIL)"),
    "Accept": "application/sparql-results+json",
})


Q_INVENTAR = """
SELECT ?person ?prop (COUNT(?wert) AS ?n) WHERE {
  VALUES ?person { %s }
  ?person ?p ?wert .
  ?prop wikibase:directClaim ?p .
}
GROUP BY ?person ?prop
"""


Q_EIGENSCHAFTEN = """
SELECT ?prop ?propLabel ?typ WHERE {
  VALUES ?prop { %s }
  ?prop wikibase:propertyType ?typ .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". }
}
"""


Q_WERTE = """
SELECT ?person ?prop ?wert WHERE {
  VALUES ?person { %s }
  VALUES ?prop { %s }
  ?prop wikibase:directClaim ?p .
  ?person ?p ?wert .
}
"""


def frage(vorlage, *einsetzungen):
    for versuch in range(5):
        try:
            r = SESSION.post(SPARQL, data={"query": vorlage % einsetzungen},
                             timeout=300)
            r.raise_for_status()
            return r.json()["results"]["bindings"]
        except (requests.RequestException, ValueError) as e:
            wart = 5 * (versuch + 1)
            log.warning("   Abfrage fehlgeschlagen (%s), warte %ds",
                        str(e)[:70], wart)
            time.sleep(wart)
    raise SystemExit("Query Service antwortet nicht.")


def main():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT p.aw_id, p.qid_wikidata, p.ext_id_bundestagsverwaltung,
                   coalesce(p.first_name || ' ', '') || p.last_name
              FROM politiker_innen.politician p
             WHERE p.aw_id IN (SELECT politician_id FROM politiker_innen.mandat)
               AND p.qid_wikidata IS NOT NULL
             ORDER BY 2;""")
        personen = cur.fetchall()
    conn.close()
    nach_qid = {q: (aw, ext, name) for aw, q, ext, name in personen}
    n = len(nach_qid)
    log.info("%d Personen mit Mandat und Wikidata-Q-Nummer", n)

    qids = list(nach_qid)
    bloecke = [qids[i:i + BLOCK] for i in range(0, n, BLOCK)]


    log.info("--- Schritt 1: Inventar, %d Abfragen zu je %d QIDs ---",
             len(bloecke), BLOCK)
    personen_je_prop, werte_je_prop = defaultdict(set), defaultdict(int)
    gefunden = set()
    for i, b in enumerate(bloecke, 1):
        werte = " ".join(f"wd:{q}" for q in b)
        for z in frage(Q_INVENTAR, werte):
            q = z["person"]["value"].rsplit("/", 1)[-1]
            pr = z["prop"]["value"].rsplit("/", 1)[-1]
            gefunden.add(q)
            personen_je_prop[pr].add(q)
            werte_je_prop[pr] += int(z["n"]["value"])
        if i % 5 == 0 or i == len(bloecke):
            log.info("   %d/%d Bloecke, %d Eigenschaften bisher",
                     i, len(bloecke), len(personen_je_prop))
        if i < len(bloecke):
            time.sleep(PAUSE)


    log.info("--- Schritt 2: Beschriftung fuer %d Eigenschaften ---",
             len(personen_je_prop))
    label, typ = {}, {}
    props = sorted(personen_je_prop)
    for i in range(0, len(props), 200):
        werte = " ".join(f"wd:{x}" for x in props[i:i + 200])
        for z in frage(Q_EIGENSCHAFTEN, werte):
            pr = z["prop"]["value"].rsplit("/", 1)[-1]
            label[pr] = z.get("propLabel", {}).get("value", "")
            typ[pr] = z["typ"]["value"].rsplit("#", 1)[-1]
        time.sleep(PAUSE)

    reihen = sorted(personen_je_prop.items(), key=lambda x: -len(x[1]))
    log.info("--- Inventar: %d verschiedene Eigenschaften ---", len(reihen))
    log.info("   %-9s %-40s %-13s %6s %7s", "Nr", "Eigenschaft", "Typ",
             "Pers.", "Werte")
    for pr, pers in reihen[:45]:
        log.info("   %-9s %-40s %-13s %5d %7d  (%.0f %%)", pr,
                 label.get(pr, "")[:38], typ.get(pr, "?")[:11], len(pers),
                 werte_je_prop[pr], 100 * len(pers) / n)

    ZIEL.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    inv = ZIEL / f"wikidata_inventar_{stempel}.csv"
    with inv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["eigenschaft", "label", "typ", "personen",
                    "anteil_prozent", "werte"])
        for pr, pers in reihen:
            w.writerow([pr, label.get(pr, ""), typ.get(pr, ""), len(pers),
                        f"{100*len(pers)/n:.1f}", werte_je_prop[pr]])
    log.info("   Inventar geschrieben: %s", inv)

    fehlend = set(nach_qid) - gefunden
    if fehlend:
        log.warning("--- %d QIDs liefern KEINE einzige Aussage ---", len(fehlend))
        for q in sorted(fehlend)[:20]:
            log.warning("      %s  %s", q, nach_qid[q][2])


    kennungen = [pr for pr, pers in reihen
                 if typ.get(pr) == "ExternalId" and len(pers) >= 0.5 * n]
    log.info("--- Schritt 3: Werte von %d haeufigen Kennungen holen ---",
             len(kennungen))
    if not kennungen:
        log.info("   keine Kennung erreicht 50 %% Abdeckung")
        return
    pw = " ".join(f"wd:{x}" for x in kennungen)
    wd_werte = defaultdict(set)
    for i, b in enumerate(bloecke, 1):
        werte = " ".join(f"wd:{q}" for q in b)
        for z in frage(Q_WERTE, werte, pw):
            q = z["person"]["value"].rsplit("/", 1)[-1]
            pr = z["prop"]["value"].rsplit("/", 1)[-1]
            wd_werte[(q, pr)].add(z["wert"]["value"])
        if i < len(bloecke):
            time.sleep(PAUSE)

    roh = ZIEL / f"wikidata_kennungen_{stempel}.json"
    roh.write_text(json.dumps({f"{q}|{pr}": sorted(v)
                               for (q, pr), v in wd_werte.items()},
                              ensure_ascii=False), encoding="utf-8")
    log.info("   Werte gesichert: %s (%d Paare)", roh, len(wd_werte))

    unsere = {q: ext for q, (aw, ext, name) in nach_qid.items() if ext}
    zaehler = defaultdict(lambda: [0, 0])
    for (q, pr), werte in wd_werte.items():
        if q in unsere:
            zaehler[pr][0] += 1
            if unsere[q] in werte:
                zaehler[pr][1] += 1
    treffer = sorted(((pr, a_, b_) for pr, (a_, b_) in zaehler.items() if b_),
                     key=lambda x: -x[2])
    log.info("--- Gegenprobe: welche Wikidata-Kennung ist unsere " "ext_id_bundestagsverwaltung? ---")
    if not treffer:
        log.info("   keine Eigenschaft stimmt mit unseren Ids ueberein")
    for pr, ges, gleich in treffer[:5]:
        log.info("   %-9s %-38s %d von %d Personen gleich (%.1f %%)",
                 pr, label.get(pr, "")[:36], gleich, ges, 100 * gleich / ges)
    for pr, pers in reihen[:12]:
        if typ.get(pr) == "ExternalId":
            bsp = next((sorted(v)[0] for (q, p2), v in wd_werte.items()
                        if p2 == pr), None)
            if bsp:
                log.info("   Beispielwert %s (%s): %s", pr,
                         label.get(pr, "")[:26], bsp[:50])


if __name__ == "__main__":
    main()
