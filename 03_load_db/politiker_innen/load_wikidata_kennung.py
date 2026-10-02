import glob
import json
import logging
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, execute_values

QUELLE = (Path(__file__).resolve().parents[2] / "01_fetch" / "wikidata"
          / "export")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn
DSN = dsn()
AW = "politiker_innen"
LIEFERUNG = "wikidata"


SPALTEN = [
    ("P227", "gnd"), ("P5355", "wd_aw_id"), ("P214", "viaf"),
    ("P10632", "opensanctions"), ("P14716", "openparliamenttv"),
    ("P1713", "bt_biografie"), ("P856", "website"),
]

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("wikidata-laden")

SPALTEN_SQL = ",\n    ".join(
    f"{name:<18} TEXT NOT NULL DEFAULT 'unbekannt'" for _, name in SPALTEN)

DDL = f"""
SET client_min_messages TO WARNING;
DROP TABLE IF EXISTS {AW}.wikidata_kennung;
DROP TABLE IF EXISTS {AW}.wikidata_eigenschaft;

CREATE TABLE {AW}.wikidata_eigenschaft (
    p_nummer          TEXT PRIMARY KEY,
    label             TEXT,
    typ               TEXT,
    abdeckung_prozent NUMERIC(5,1),
    eigene_spalte     TEXT
);

CREATE TABLE {AW}.wikidata_kennung (
    aw_id          INTEGER PRIMARY KEY,
    qid            TEXT NOT NULL,
    {SPALTEN_SQL},
    weitere        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    weitere_anzahl INTEGER NOT NULL DEFAULT 0,
    herkunft       TEXT NOT NULL DEFAULT '{LIEFERUNG}',
    abgerufen_am   TEXT
);
CREATE INDEX ON {AW}.wikidata_kennung (gnd);
CREATE INDEX ON {AW}.wikidata_kennung (qid);
CREATE INDEX ON {AW}.wikidata_kennung USING gin (weitere);

COMMENT ON TABLE {AW}.wikidata_kennung IS
 'Kennungen und Namensangaben der 1.271 Personen mit Mandat, aus Wikidata ueber '
 'die gelieferte Q-Nummer. Die Zuordnung ist beidseitig geprueft: Wikidatas '
 'abgeordnetenwatch-Kennung (P5355) stimmt bei 1.271 von 1.271 mit aw_id '
 'ueberein. Lieferung {LIEFERUNG} - kollaborativ, also Zeiger auf andere '
 'Bestaende, keine Belege.';
COMMENT ON COLUMN {AW}.wikidata_kennung.weitere IS
 'Die 376 Eigenschaften, die weniger als 90 Prozent der Personen haben, als '
 '{{"P-Nummer": ["Wert", ...]}}. Hier steht NUR, was vorhanden ist - anders als '
 'in den sieben Spalten gibt es kein unbekannt. Bedeutung der P-Nummern in '
 'wikidata_eigenschaft.';
COMMENT ON COLUMN {AW}.wikidata_kennung.gnd IS
 'GND-Kennung der Deutschen Nationalbibliothek (P227), oder `unbekannt`. '
 'Mehrere Werte sind mit " | " verbunden - es wird keiner ausgewaehlt.';
COMMENT ON COLUMN {AW}.wikidata_kennung.wd_aw_id IS
 'Was WIKIDATA als abgeordnetenwatch-Kennung fuehrt (P5355). Absichtlich '
 'redundant zu aw_id: die Spalte ist die Gegenprobe der Zuordnung und muss '
 'gleich sein.';
COMMENT ON TABLE {AW}.wikidata_eigenschaft IS
 'Was die P-Nummern in wikidata_kennung.weitere bedeuten - Beschriftung, '
 'Datentyp und wie viel Prozent der 1.271 Personen den Wert haben.';
"""


def neueste():
    d = sorted(glob.glob(str(QUELLE / "wikidata_kennungen_gewaehlte_*.json")))
    if not d:
        raise SystemExit(f"Keine Abzugsdatei in {QUELLE} - erst hole_kennungen.py.")
    return Path(d[-1])


def main():
    datei = neueste()
    daten = json.loads(datei.read_text(encoding="utf-8"))
    eig = daten["eigenschaften"]
    pers = daten["personen"]
    log.info("Abzug %s: %d Personen, %d Eigenschaften",
             datei.name, len(pers), len(eig))

    in_spalte = {p: name for p, name in SPALTEN}
    zeilen, mehrfach, ohne = [], {}, {name: 0 for _, name in SPALTEN}
    weitere_werte = 0
    for qid, satz in pers.items():
        werte = satz["werte"]
        spalten = []
        for p, name in SPALTEN:
            v = werte.get(p, [])
            if not v:
                ohne[name] += 1
                spalten.append("unbekannt")
            else:
                if len(v) > 1:
                    mehrfach[name] = mehrfach.get(name, 0) + 1
                spalten.append(" | ".join(sorted(v)))
        rest = {p: sorted(v) for p, v in werte.items() if p not in in_spalte}
        weitere_werte += sum(len(v) for v in rest.values())
        zeilen.append((satz["aw_id"], qid, *spalten, Json(rest), len(rest),
                       daten["abgerufen_am"]))

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
        execute_values(cur, f"""INSERT INTO {AW}.wikidata_eigenschaft
            (p_nummer, label, typ, abdeckung_prozent, eigene_spalte) VALUES %s;""",
            [(p, m["label"], m["typ"], m["abdeckung_prozent"], in_spalte.get(p))
             for p, m in eig.items()])
        namen = ", ".join(name for _, name in SPALTEN)
        execute_values(cur, f"""INSERT INTO {AW}.wikidata_kennung
            (aw_id, qid, {namen}, weitere, weitere_anzahl, abgerufen_am)
            VALUES %s;""", zeilen)
    conn.commit()
    log.info("   %d Zeilen geschrieben, %d Werte in `weitere`",
             len(zeilen), weitere_werte)

    log.info("--- Die sieben Spalten ---")
    for _, name in SPALTEN:
        n = len(zeilen) - ohne[name]
        log.info("   %-18s %5d belegt, %4d unbekannt   (%.1f %%)%s",
                 name, n, ohne[name], 100 * n / len(zeilen),
                 f"   {mehrfach[name]} mit mehreren Werten" if mehrfach.get(name) else "")

    with conn.cursor() as cur:
        cur.execute(f"""SELECT count(*) FROM {AW}.wikidata_kennung
                         WHERE wd_aw_id <> aw_id::text;""")
        log.info("--- Gegenprobe ---")
        log.info("   %d Zeilen, in denen Wikidatas abgeordnetenwatch-Kennung NICHT " "unserer aw_id entspricht", cur.fetchone()[0])
        cur.execute(f"""SELECT count(*) FROM {AW}.politician
                         WHERE aw_id IN (SELECT politician_id FROM {AW}.mandat)
                           AND aw_id NOT IN (SELECT aw_id FROM {AW}.wikidata_kennung);""")
        log.info("   %d Personen mit Mandat ohne Zeile", cur.fetchone()[0])
        cur.execute(f"""SELECT e.p_nummer, e.label, count(*)
                          FROM {AW}.wikidata_kennung k,
                               LATERAL jsonb_object_keys(k.weitere) AS p
                          JOIN {AW}.wikidata_eigenschaft e ON e.p_nummer = p
                         GROUP BY 1,2 ORDER BY 3 DESC LIMIT 12;""")
        log.info("--- Haeufigstes in `weitere` ---")
        for p, l, n in cur.fetchall():
            log.info("   %-9s %-42s %5d Personen", p, (l or "")[:40], n)
    conn.close()


if __name__ == "__main__":
    main()
