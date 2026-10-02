import csv
import glob
import json
import logging
import re
import sys
import unicodedata
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

QUELLE = (Path(__file__).resolve().parents[2] / "01_fetch" / "wikidata"
          / "export")
KORREKTUREN = (Path(__file__).resolve().parents[2] / "01_fetch"
               / "wikidata" / "korrekturen_geburtsort.csv")


KORREKTUREN_BERLIN = (Path(__file__).resolve().parents[2] / "01_fetch"
                      / "wikidata" / "korrekturen_geburtsort_berlin.csv")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn
DSN = dsn()
AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("geburtsort")

DDL = f"""
SET client_min_messages TO WARNING;
DROP TABLE IF EXISTS {AW}.geburtsort;

CREATE TABLE {AW}.geburtsort (
    aw_id                 INTEGER PRIMARY KEY,
    qid                   TEXT,
    ort_amtlich           TEXT NOT NULL DEFAULT 'unbekannt',
    ort_wikidata          TEXT NOT NULL DEFAULT 'unbekannt',
    ort_qid               TEXT,
    land                  TEXT NOT NULL DEFAULT 'unbekannt',
    einheit               TEXT NOT NULL DEFAULT 'unbekannt',
    abgleich              TEXT NOT NULL,
    koordinate_mehrdeutig BOOLEAN NOT NULL DEFAULT false,
    genauigkeit           TEXT NOT NULL DEFAULT 'ort',
    nachgetragen_grund    TEXT,
    herkunft_name         TEXT NOT NULL DEFAULT 'bt_mdb_stammdaten',
    herkunft_koordinate   TEXT NOT NULL DEFAULT 'wikidata',
    herkunft_ort          TEXT NOT NULL DEFAULT 'wikidata',
    geom                  geometry(Point, 4326)
);
CREATE INDEX ON {AW}.geburtsort USING gist (geom);
CREATE INDEX ON {AW}.geburtsort (abgleich);

COMMENT ON TABLE {AW}.geburtsort IS
 'Geburtsort je Person mit Mandat: der NAME amtlich aus den MdB-Stammdaten, '
 'die KOORDINATE aus dem Wikidata-Ortsobjekt (P19 -> P625). Zwei Lieferungen '
 'in einer Zeile, jede mit eigener Herkunftsspalte.';
COMMENT ON COLUMN {AW}.geburtsort.abgleich IS
 'Vergleich der beiden Ortsnamen: gleich | enthalten | verschieden | '
 'nur amtlich | nur wikidata | keine Angabe. `verschieden` heisst NICHT '
 'falsch - historische Namen (Breslau/Wroclaw) und Eingemeindungen landen '
 'ebenfalls dort. Es ist eine Aufforderung hinzusehen, kein Urteil.';
COMMENT ON COLUMN {AW}.geburtsort.genauigkeit IS
 'Was der Punkt darstellt. `ort` = das Objekt IST der Geburtsort (1.269). '
 '`uebergeordnet` = die Koordinate stammt vom umgebenden Gebiet, weil das '
 'Ortsobjekt keine hat (1 Fall, Mazgirt). `land` = nur das Land ist verortet, '
 'der Punkt liegt irgendwo darin und ist AUSDRUECKLICH KEIN Geburtsort '
 '(1 Fall, Kasachstan). WER ENTFERNUNGEN RECHNET, MUSS AUF `ort` FILTERN.';
COMMENT ON COLUMN {AW}.geburtsort.herkunft_ort IS
 'Woher das Ortsobjekt in ort_qid stammt. `wikidata` = so geliefert. '
 '`korrigiert` = von uns durch ein genaueres ersetzt, Eingriff E14: 24 '
 'Berliner Geburtsorte, die beide Lieferungen nur als `Berlin` (Q64) '
 'fuehren, auf Ost-Berlin (Q56037) oder West-Berlin (Q56036) gesetzt. '
 'WER OHNE EINGRIFFE RECHNEN WILL, FILTERT AUF `wikidata`.';
COMMENT ON COLUMN {AW}.geburtsort.nachgetragen_grund IS
 'Nur bei den drei nachgetragenen Faellen gefuellt: warum Wikidata keine '
 'Koordinate lieferte und welches Objekt stattdessen benannt wurde. Wortlaut '
 'aus korrekturen_geburtsort.csv.';
COMMENT ON COLUMN {AW}.geburtsort.geom IS
 'Punkt des ORTES, nicht des Geburtshauses, EPSG:4326. Herkunft Wikidata, '
 'also kollaborativ - fuer eine Herkunftskarte belastbar genug, fuer Feineres '
 'nicht.';
COMMENT ON COLUMN {AW}.geburtsort.ort_amtlich IS
 'Amtliche Schreibweise mit historischem Kontext, unveraendert uebernommen: '
 '"Quedlinburg / Bezirk Halle" nennt die DDR-Gliederung.';
"""

UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def norm(s):
    if not s or s == "unbekannt":
        return ""
    s = re.split(r"[/(]", s)[0]
    s = s.lower().translate(UMLAUTE)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]", " ", s).strip()


def vergleich(amtlich, wikidata):
    a, w = norm(amtlich), norm(wikidata)
    if not a and not w:
        return "keine Angabe"
    if not w:
        return "nur amtlich"
    if not a:
        return "nur wikidata"
    if a == w:
        return "gleich"
    if a in w or w in a:
        return "enthalten"
    return "verschieden"


def main():
    dateien = sorted(glob.glob(str(QUELLE / "wikidata_geburtsorte_*.json")))
    if not dateien:
        raise SystemExit("Kein Abzug - erst hole_geburtsorte.py laufen lassen.")
    daten = json.loads(Path(dateien[-1]).read_text(encoding="utf-8"))
    log.info("Abzug %s: %d Personen", Path(dateien[-1]).name, len(daten["personen"]))
    wd = {v["aw_id"]: {**v, "qid": q} for q, v in daten["personen"].items()}


    nach = {}
    if KORREKTUREN.exists():
        with KORREKTUREN.open(encoding="utf-8", newline="") as f:
            for z in csv.DictReader((r for r in f if not r.startswith("#")),
                                    delimiter=";"):
                nach[int(z["aw_id"])] = z
        log.info("   %d nachgetragene Ortsobjekte aus %s",
                 len(nach), KORREKTUREN.name)


    berlin = {}
    if KORREKTUREN_BERLIN.exists():
        with KORREKTUREN_BERLIN.open(encoding="utf-8", newline="") as f:
            for z in csv.DictReader((r for r in f if not r.startswith("#")),
                                    delimiter=";"):
                berlin[int(z["aw_id"])] = z
        log.info("   %d Berliner Sektorkorrekturen aus %s",
                 len(berlin), KORREKTUREN_BERLIN.name)

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(f"""SELECT b.aw_id, b.geburtsort FROM {AW}.biografie_bt b;""")
        amtlich = dict(cur.fetchall())
        cur.execute(f"""SELECT DISTINCT politician_id FROM {AW}.mandat;""")
        alle = [r[0] for r in cur.fetchall()]

    zeilen = []
    for aw_id in alle:
        w = wd.get(aw_id, {})
        koords = w.get("koordinaten") or []

        punkt = koords[0] if koords else None
        zeilen.append((
            aw_id, w.get("qid"),
            amtlich.get(aw_id, "unbekannt"),
            w.get("ort") or "unbekannt", w.get("ort_qid"),
            w.get("land") or "unbekannt", w.get("einheit") or "unbekannt",
            vergleich(amtlich.get(aw_id), w.get("ort")),
            len(koords) > 1, "ort", None, punkt))

    with conn.cursor() as cur:
        cur.execute(DDL)
        execute_values(cur, f"""
            INSERT INTO {AW}.geburtsort
                (aw_id, qid, ort_amtlich, ort_wikidata, ort_qid, land, einheit,
                 abgleich, koordinate_mehrdeutig, genauigkeit,
                 nachgetragen_grund, geom)
            VALUES %s;""", zeilen,
            template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s," "ST_GeomFromText(%s, 4326))")


        for aw_id, z in nach.items():
            cur.execute(f"""UPDATE {AW}.geburtsort
                               SET ort_qid = %s, ort_wikidata = %s,
                                   genauigkeit = %s, nachgetragen_grund = %s,
                                   geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                             WHERE aw_id = %s;""",
                        (z["ort_qid"], z["ort_wikidata"], z["genauigkeit"],
                         z["grundlage"], float(z["laenge"]),
                         float(z["breite"]), aw_id))
            if cur.rowcount != 1:
                log.warning("   Nachtrag ohne Ziel: %s", aw_id)


        for aw_id, z in berlin.items():
            cur.execute(f"""UPDATE {AW}.geburtsort
                               SET ort_qid = %s, ort_wikidata = %s,
                                   koordinate_mehrdeutig = true,
                                   herkunft_ort = 'korrigiert',
                                   nachgetragen_grund = %s,
                                   geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                             WHERE aw_id = %s AND ort_qid = %s;""",
                        (z["ort_qid"], z["ort_wikidata"], z["grundlage"],
                         float(z["laenge"]), float(z["breite"]),
                         aw_id, z["ort_qid_alt"]))
            if cur.rowcount != 1:
                log.warning("   E14 ohne Ziel oder Ausgangswert nicht %s: " "aw_id %s (%s)", z["ort_qid_alt"], aw_id,
                            z.get("name", ""))
    conn.commit()
    log.info("   %d Zeilen geschrieben", len(zeilen))

    with conn.cursor() as cur:
        cur.execute(f"""SELECT abgleich, count(*) FROM {AW}.geburtsort
                         GROUP BY 1 ORDER BY 2 DESC;""")
        log.info("--- Gegenprobe der Ortsnamen ---")
        n = len(zeilen)
        for a, k in cur.fetchall():
            log.info("   %-16s %5d  (%.1f %%)", a, k, 100 * k / n)

        cur.execute(f"""SELECT ort_amtlich, ort_wikidata, land
                          FROM {AW}.geburtsort WHERE abgleich = 'verschieden'
                         ORDER BY 1 LIMIT 20;""")
        versch = cur.fetchall()
        if versch:
            log.warning("--- Die Faelle mit verschiedenen Namen ---")
            for a, w_, l in versch:
                log.warning("   amtlich %-34s wikidata %-28s %s",
                            a[:32], str(w_)[:26], l)

        cur.execute(f"""SELECT count(*) FILTER (WHERE geom IS NOT NULL),
                               count(*) FILTER (WHERE koordinate_mehrdeutig),
                               count(DISTINCT ort_qid)
                          FROM {AW}.geburtsort;""")
        mit, mehr, orte = cur.fetchone()
        log.info("--- Verortung ---")
        log.info("   %d von %d mit Koordinate (%.1f %%), %d Orte, " "%d Ortsobjekte mit mehreren Koordinaten",
                 mit, n, 100 * mit / n, orte, mehr)
        cur.execute(f"""SELECT land, count(*) FROM {AW}.geburtsort
                         WHERE land <> 'unbekannt' GROUP BY 1
                         ORDER BY 2 DESC LIMIT 8;""")
        for l, k in cur.fetchall():
            log.info("   %-40s %4d", l[:38], k)


        cur.execute(f"""
            SELECT count(*) FILTER (WHERE land = 'Deutschland'
                                      AND NOT ST_Within(geom,
                                          ST_MakeEnvelope(5.5, 47.0, 15.5, 55.5, 4326)))
              FROM {AW}.geburtsort WHERE geom IS NOT NULL;""")
        log.info("   %d als deutsch gefuehrte Geburtsorte liegen AUSSERHALB " "des deutschen Umrings", cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
