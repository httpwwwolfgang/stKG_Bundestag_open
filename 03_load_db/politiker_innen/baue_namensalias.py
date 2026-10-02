import csv
import glob
import logging
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "politiker_innen"
          / "bundestag_namentliche_abstimmungen")


KORREKTUREN = (Path(__file__).resolve().parents[2] / "01_fetch"
               / "bundestag" / "korrekturen_namensalias.csv")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn
DSN = dsn()
AW = "politiker_innen"

PRAEFIXE = {"von", "van", "de", "der", "den", "zu", "zur", "vom", "du", "di",
            "graf", "gräfin", "freiherr", "frhr.", "freifrau", "ritter"}


UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("namensalias")


def schluessel(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = re.sub(r"\s+", " ", str(s)).strip().lower().translate(UMLAUTE)
    s = "".join(c for c in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(c))
    return " ".join(t for t in s.split(" ") if t not in PRAEFIXE)


def zerlege(nachname):
    s = str(nachname or "")
    m = re.search(r"\(([^)]*)\)", s)
    return (schluessel(re.sub(r"\([^)]*\)", "", s)),
            schluessel(m.group(1)) if m else "")


DDL = f"""
SET client_min_messages TO WARNING;

DROP TABLE IF EXISTS {AW}.mdb_namensalias;
CREATE TABLE {AW}.mdb_namensalias (
    mdb_id          TEXT NOT NULL,
    such_nachname   TEXT NOT NULL,
    such_vorname    TEXT NOT NULL,
    such_ortszusatz TEXT NOT NULL DEFAULT '',
    nachname        TEXT,
    vorname         TEXT,
    ortszusatz      TEXT,
    lieferung_id    TEXT NOT NULL,
    verfahren       TEXT NOT NULL,
    PRIMARY KEY (mdb_id, such_nachname, such_vorname, such_ortszusatz,
                 lieferung_id)
);
CREATE INDEX ON {AW}.mdb_namensalias (such_nachname, such_vorname);
CREATE INDEX ON {AW}.mdb_namensalias (mdb_id);

COMMENT ON TABLE {AW}.mdb_namensalias IS
 'Jede Schreibweise eines Abgeordnetennamens, die in einer Lieferung vorkommt, '
 'unter der elfstelligen Kennung der Bundestagsverwaltung. Verzeichnis, kein '
 'Eingriff: die Rohtabellen bleiben unveraendert. Anker ist die MdB-Nummer, '
 'weil sie in allen Bundestagslieferungen steht - Stammdaten, namentliche '
 'Abstimmungen, Plenarprotokolle. Zur abgeordnetenwatch-Seite fuehrt '
 'mdb_zu_aw. Siehe 03_load_db/politiker_innen/baue_namensalias.py.';
COMMENT ON COLUMN {AW}.mdb_namensalias.such_nachname IS
 'Vergleichsform: Kleinschreibung, Umlaute als ae/oe/ue/ss, uebrige Diakritika '
 'auf die Grundform, Praefixe (von, de, van) abgeschnitten. Die Abbildung ist '
 'in baue_namensalias.py aufgezaehlt, nicht ueber unaccent.';
COMMENT ON COLUMN {AW}.mdb_namensalias.such_ortszusatz IS
 'Der Zusatz, mit dem der Bundestag Namensgleiche unterscheidet - '
 '"Mueller (Erlangen)". Leer, wo keiner gefuehrt wird.';
COMMENT ON COLUMN {AW}.mdb_namensalias.lieferung_id IS
 'Aus welcher Lieferung diese Schreibweise stammt. bt_mdb_stammdaten = '
 'MdB-XML, bt_namentliche_abstimmungen = die XLSX der namentlichen '
 'Abstimmungen.';
COMMENT ON COLUMN {AW}.mdb_namensalias.verfahren IS
 'Wie die Zuordnung zustande kam. stammdaten = die Lieferung nennt Kennung '
 'und Namen zusammen, also abgelesen statt abgeglichen. schluessel = Nach- '
 'und Vorname treffen genau einen Eintrag der Wahlperiode. ortszusatz = '
 'mehrere Namensgleiche, der Zusatz entschied. rufname = der '
 'Stammdaten-Vorname ist der erste der gelieferten Vornamen.';
"""


def stammdaten(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT w.wp, n.id, n.nachname, n.vorname, n.ortszusatz
              FROM roh_bundestag.stammdaten_mdb_wahlperiode w
              JOIN roh_bundestag.stammdaten_mdb_name n ON n.id = w.id
             WHERE w.wp IN (18, 19, 20);""")
        return cur.fetchall()


def main():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()

    zeilen = stammdaten(conn)
    log.info("%d Namenszeilen der Wahlperioden 18 bis 20", len(zeilen))


    werte, index = [], defaultdict(lambda: defaultdict(dict))
    for wp, mdb_id, nach, vor, ort in zeilen:
        sn, sv, so = schluessel(nach), schluessel(vor), schluessel(ort)
        werte.append((mdb_id, sn, sv, so, nach, vor, ort,
                      "bt_mdb_stammdaten", "stammdaten"))
        index[wp][(sn, sv)][mdb_id] = so


    if KORREKTUREN.exists():
        with KORREKTUREN.open(encoding="utf-8", newline="") as f:
            for z in csv.DictReader(f, delimiter=";"):
                sn, so = zerlege(z["nachname"])
                sv = schluessel(z["vorname"])
                if z["ortszusatz"]:
                    so = schluessel(z["ortszusatz"])
                werte.append((z["mdb_id"], sn, sv, so, z["nachname"],
                              z["vorname"], z["ortszusatz"] or None,
                              z["lieferung_id"], "korrigiert"))
                index[int(z["wp"])][(sn, sv)][z["mdb_id"]] = so
                log.info("   Einzelentscheidung: %s %s -> %s (geprueft %s)",
                         z["nachname"], z["vorname"], z["mdb_id"],
                         z["geprueft_am"])


    dateien = sorted(glob.glob(str(QUELLE / "*.xls*")))
    log.info("%d Abstimmungsdateien werden gelesen ...", len(dateien))
    namen = set()
    for i, f in enumerate(dateien, 1):
        df = pd.read_excel(f, usecols=["Wahlperiode", "Name", "Vorname"])
        namen.update(zip(df["Wahlperiode"], df["Name"], df["Vorname"]))
        if i % 200 == 0:
            log.info("   %d/%d", i, len(dateien))
    log.info("   %d verschiedene Schreibweisen", len(namen))

    zaehler, offen = Counter(), []
    for wp, nach, vor in sorted(namen, key=lambda x: (x[0], str(x[1]), str(x[2]))):
        basis, zusatz = zerlege(nach)
        sv = schluessel(vor)
        kand = dict(index.get(int(wp), {}).get((basis, sv), {}))
        verfahren = "schluessel"

        if len(kand) > 1 and zusatz:
            enger = {k: v for k, v in kand.items() if v == zusatz}
            if enger:
                kand, verfahren = enger, "ortszusatz"

        if not kand and sv:

            erster = sv.split(" ")[0]
            treffer = {k: v for (n2, v2), m in index.get(int(wp), {}).items()
                       if n2 == basis and (v2 == erster or sv.startswith(v2 + " "))
                       for k, v in m.items()}
            if len(treffer) == 1:
                kand, verfahren = treffer, "rufname"

        if len(kand) == 1:
            mdb_id = next(iter(kand))
            zaehler[verfahren] += 1
            werte.append((mdb_id, basis, sv, zusatz, str(nach), str(vor), None,
                          "bt_namentliche_abstimmungen", verfahren))
        else:
            zaehler["offen"] += 1
            offen.append((int(wp), str(nach), str(vor), len(kand)))


    gesehen, sauber = set(), []
    for w in werte:
        k = (w[0], w[1], w[2], w[3], w[7])
        if k not in gesehen:
            gesehen.add(k)
            sauber.append(w)

    with conn.cursor() as cur:
        execute_values(cur, f"""
            INSERT INTO {AW}.mdb_namensalias
                (mdb_id, such_nachname, such_vorname, such_ortszusatz,
                 nachname, vorname, ortszusatz, lieferung_id, verfahren)
            VALUES %s""", sauber)
    conn.commit()

    log.info("--- Wie die Schreibweisen der Abstimmungen zugeordnet wurden ---")
    for k, v in zaehler.most_common():
        log.info("   %-12s %5d", k, v)
    if offen:
        log.info("--- Offen: %d Schreibweisen ---", len(offen))
        for wp, nach, vor, n in offen:
            log.info("   WP %d  %-26s %-24s %d Kandidaten", wp, nach[:24], vor[:22], n)

    log.info("--- Die Tabelle ---")
    with conn.cursor() as cur:
        cur.execute(f"""SELECT lieferung_id, verfahren, count(*)
                          FROM {AW}.mdb_namensalias GROUP BY 1,2 ORDER BY 1,3 DESC;""")
        for lief, verf, n in cur.fetchall():
            log.info("   %-30s %-12s %6d", lief, verf, n)
        cur.execute(f"""SELECT count(*), count(DISTINCT mdb_id) FROM {AW}.mdb_namensalias;""")
        log.info("   %d Aliaszeilen fuer %d Personen", *cur.fetchone())

        log.info("--- Suchschluessel, die auf mehrere Personen zeigen ---")
        cur.execute(f"""
            SELECT such_nachname, such_vorname, such_ortszusatz,
                   count(DISTINCT mdb_id) AS personen,
                   string_agg(DISTINCT mdb_id, ', ') AS ids
              FROM {AW}.mdb_namensalias
             GROUP BY 1,2,3 HAVING count(DISTINCT mdb_id) > 1
             ORDER BY 4 DESC, 1;""")
        z = cur.fetchall()
        log.info("   %d mehrdeutige Schluessel", len(z))
        for sn, sv, so, n, ids in z[:15]:
            log.info("      %-22s %-16s %-14s %d: %s", sn[:20], sv[:14], so[:12], n, ids)

    conn.close()


if __name__ == "__main__":
    main()
