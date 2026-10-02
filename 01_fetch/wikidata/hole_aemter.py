import json
import logging
import sys
import time
from collections import Counter, defaultdict
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
log = logging.getLogger("wikidata-aemter")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("sKG-bundestag/1.0 (Masterarbeit, raeumlicher Knowledge Graph " "zum Bundestag; KONTAKT_EMAIL)"),
    "Accept": "application/sparql-results+json",
})


ABFRAGE = """
SELECT ?person ?amt ?amtLabel ?von ?vonPrec ?bis ?bisPrec ?wp ?wpLabel
       ?ressort ?ressortLabel WHERE {
  VALUES ?person { %s }
  ?person p:P39 ?st .
  ?st ps:P39 ?amt .
  OPTIONAL { ?st pqv:P580 [ wikibase:timeValue ?von ; wikibase:timePrecision ?vonPrec ] }
  OPTIONAL { ?st pqv:P582 [ wikibase:timeValue ?bis ; wikibase:timePrecision ?bisPrec ] }
  OPTIONAL { ?st pq:P2937 ?wp }
  OPTIONAL { ?st pq:P642 ?ressort }
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


def wert(z, k):
    return z.get(k, {}).get("value")


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

    aussagen = []
    for i, b in enumerate(bloecke, 1):
        for z in frage(" ".join(f"wd:{q}" for q in b)):
            aussagen.append({
                "qid": z["person"]["value"].rsplit("/", 1)[-1],
                "amt_qid": z["amt"]["value"].rsplit("/", 1)[-1],
                "amt": wert(z, "amtLabel"),
                "von": wert(z, "von"), "von_prec": wert(z, "vonPrec"),
                "bis": wert(z, "bis"), "bis_prec": wert(z, "bisPrec"),
                "wahlperiode": wert(z, "wpLabel"),
                "ressort": wert(z, "ressortLabel"),
            })
        if i % 5 == 0 or i == len(bloecke):
            log.info("   %d/%d Bloecke, %d Aussagen", i, len(bloecke), len(aussagen))
        if i < len(bloecke):
            time.sleep(PAUSE)

    ZIEL.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    ziel = ZIEL / f"wikidata_aemter_{stempel}.json"
    ziel.write_text(json.dumps({"abgerufen_am": stempel,
                                "aw_id_je_qid": nach_qid,
                                "aussagen": aussagen},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("   geschrieben: %s", ziel)


    n = len(aussagen)
    mit_von = sum(1 for a in aussagen if a["von"])
    mit_bis = sum(1 for a in aussagen if a["bis"])
    beides = sum(1 for a in aussagen if a["von"] and a["bis"])
    nichts = sum(1 for a in aussagen if not a["von"] and not a["bis"])
    mit_wp = sum(1 for a in aussagen if a["wahlperiode"])
    log.info("--- %d Aussagen zu P39 bei %d Personen ---",
             n, len({a["qid"] for a in aussagen}))
    log.info("   mit Beginndatum      %5d  (%.1f %%)", mit_von, 100 * mit_von / n)
    log.info("   mit Enddatum         %5d  (%.1f %%)", mit_bis, 100 * mit_bis / n)
    log.info("   mit beidem           %5d  (%.1f %%)", beides, 100 * beides / n)
    log.info("   ohne jedes Datum     %5d  (%.1f %%)", nichts, 100 * nichts / n)
    log.info("   mit Wahlperiode      %5d  (%.1f %%)", mit_wp, 100 * mit_wp / n)


    genau = Counter(a["von_prec"] for a in aussagen if a["von"])
    log.info("   Genauigkeit des Beginndatums: %s",
             {"Tag" if k == "11" else "Monat" if k == "10" else
              "Jahr" if k == "9" else str(k): v for k, v in genau.most_common()})

    log.info("--- Die haeufigsten Aemter, und wie gut sie datiert sind ---")
    je_amt = defaultdict(lambda: [0, 0, 0])
    for a in aussagen:
        e = je_amt[a["amt"] or a["amt_qid"]]
        e[0] += 1
        e[1] += bool(a["von"])
        e[2] += bool(a["bis"])
    for amt, (ges, v, bi) in sorted(je_amt.items(), key=lambda x: -x[1][0])[:20]:
        log.info("   %-46s %5d  Beginn %3.0f %%  Ende %3.0f %%",
                 str(amt)[:44], ges, 100 * v / ges, 100 * bi / ges)

    log.info("--- Regierungsaemter im engeren Sinn ---")
    muster = ("minister", "kanzler", "staatssekret", "senator", "regierung")
    reg = [a for a in aussagen if a["amt"] and
           any(m in a["amt"].lower() for m in muster)]
    if reg:
        rv = sum(1 for a in reg if a["von"])
        rb = sum(1 for a in reg if a["bis"])
        log.info("   %d Aussagen bei %d Personen, %d mit Beginn (%.0f %%), " "%d mit Ende (%.0f %%)", len(reg), len({a["qid"] for a in reg}),
                 rv, 100 * rv / len(reg), rb, 100 * rb / len(reg))
        for a in reg[:8]:
            log.info("      %-40s %s bis %s   %s", str(a["amt"])[:38],
                     (a["von"] or "?")[:10], (a["bis"] or "?")[:10],
                     a["ressort"] or "")
    else:
        log.info("   keine gefunden")


if __name__ == "__main__":
    main()
