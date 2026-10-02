import logging
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query


import lieferung
LIEFERUNG = "bt_mdb_stammdaten"

SCHEMA = "roh_bundestag"


XML_PFAD = (Path(__file__).resolve().parents[4] / "Daten" / "politiker_innen"
            / "MdB-Stammdaten (2)" / "MDB_STAMMDATEN.XML")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mdb-stammdaten")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {SCHEMA};

CREATE TABLE IF NOT EXISTS {SCHEMA}.stammdaten_mdb (
    id                            TEXT PRIMARY KEY,
    geburtsdatum                  DATE,
    geburtsort                    TEXT,
    geburtsland                   TEXT,
    sterbedatum                   DATE,
    geschlecht                    TEXT,
    familienstand                 TEXT,
    religion                      TEXT,
    beruf                         TEXT,
    partei_kurz                   TEXT,
    vita_kurz                     TEXT,
    veroeffentlichungspflichtiges TEXT
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.stammdaten_mdb_name (
    id            TEXT NOT NULL,
    lfd           SMALLINT NOT NULL,
    nachname      TEXT,
    vorname       TEXT,
    ortszusatz    TEXT,
    adel          TEXT,
    praefix       TEXT,
    anrede_titel  TEXT,
    akad_titel    TEXT,
    historie_von  DATE,
    historie_bis  DATE,
    PRIMARY KEY (id, lfd)
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.stammdaten_mdb_wahlperiode (
    id           TEXT NOT NULL,
    wp           SMALLINT NOT NULL,
    mdbwp_von    DATE,
    mdbwp_bis    DATE,
    wkr_nummer   SMALLINT,
    wkr_name     TEXT,
    wkr_land     TEXT,
    liste        TEXT,
    mandatsart   TEXT,
    PRIMARY KEY (id, wp)
);

CREATE TABLE IF NOT EXISTS {SCHEMA}.stammdaten_mdb_institution (
    id           TEXT NOT NULL,
    wp           SMALLINT NOT NULL,
    lfd          SMALLINT NOT NULL,
    insart_lang  TEXT,
    ins_lang     TEXT,
    mdbins_von   DATE,
    mdbins_bis   DATE,
    fkt_lang     TEXT,
    fktins_von   DATE,
    fktins_bis   DATE,
    PRIMARY KEY (id, wp, lfd)
);

CREATE INDEX IF NOT EXISTS idx_mdb_wp_wkr
    ON {SCHEMA}.stammdaten_mdb_wahlperiode (wp, wkr_nummer);
CREATE INDEX IF NOT EXISTS idx_mdb_wp_mandatsart
    ON {SCHEMA}.stammdaten_mdb_wahlperiode (mandatsart);
"""


def txt(element, name):
    if element is None:
        return None
    wert = element.findtext(name)
    if wert is None:
        return None
    wert = wert.strip()
    return wert or None


def datum(wert, wo):
    if not wert:
        return None
    teile = wert.split(".")
    if len(teile) != 3 or not all(t.isdigit() for t in teile):
        raise SystemExit(f"Unlesbares Datum '{wert}' bei {wo} - Lauf abgebrochen.")
    tag, monat, jahr = teile
    return f"{jahr}-{monat}-{tag}"


def sql_wert(wert):
    if wert is None:
        return "NULL"
    return "'" + str(wert).replace("'", "''") + "'"


def lies_xml(pfad):
    baum = ET.parse(pfad)
    wurzel = baum.getroot()
    log.info("VERSION der Lieferung: %s", wurzel.findtext("VERSION"))

    mdb, namen, perioden, institutionen = [], [], [], []
    for m in wurzel.iter("MDB"):
        mdb_id = (m.findtext("ID") or "").strip()
        if not mdb_id:
            raise SystemExit("MDB ohne ID gefunden - Lauf abgebrochen.")
        bio = m.find("BIOGRAFISCHE_ANGABEN")
        mdb.append((
            mdb_id,
            datum(txt(bio, "GEBURTSDATUM"), f"MDB {mdb_id} GEBURTSDATUM"),
            txt(bio, "GEBURTSORT"), txt(bio, "GEBURTSLAND"),
            datum(txt(bio, "STERBEDATUM"), f"MDB {mdb_id} STERBEDATUM"),
            txt(bio, "GESCHLECHT"), txt(bio, "FAMILIENSTAND"),
            txt(bio, "RELIGION"), txt(bio, "BERUF"), txt(bio, "PARTEI_KURZ"),
            txt(bio, "VITA_KURZ"), txt(bio, "VEROEFFENTLICHUNGSPFLICHTIGES"),
        ))

        for lfd, n in enumerate(m.iter("NAME"), 1):
            namen.append((
                mdb_id, lfd, txt(n, "NACHNAME"), txt(n, "VORNAME"),
                txt(n, "ORTSZUSATZ"), txt(n, "ADEL"), txt(n, "PRAEFIX"),
                txt(n, "ANREDE_TITEL"), txt(n, "AKAD_TITEL"),
                datum(txt(n, "HISTORIE_VON"), f"MDB {mdb_id} HISTORIE_VON"),
                datum(txt(n, "HISTORIE_BIS"), f"MDB {mdb_id} HISTORIE_BIS"),
            ))

        for w in m.iter("WAHLPERIODE"):
            wp = txt(w, "WP")
            perioden.append((
                mdb_id, wp,
                datum(txt(w, "MDBWP_VON"), f"MDB {mdb_id} WP {wp} MDBWP_VON"),
                datum(txt(w, "MDBWP_BIS"), f"MDB {mdb_id} WP {wp} MDBWP_BIS"),
                txt(w, "WKR_NUMMER"), txt(w, "WKR_NAME"), txt(w, "WKR_LAND"),
                txt(w, "LISTE"), txt(w, "MANDATSART"),
            ))
            for lfd, i in enumerate(w.iter("INSTITUTION"), 1):
                institutionen.append((
                    mdb_id, wp, lfd, txt(i, "INSART_LANG"), txt(i, "INS_LANG"),
                    datum(txt(i, "MDBINS_VON"), f"MDB {mdb_id} MDBINS_VON"),
                    datum(txt(i, "MDBINS_BIS"), f"MDB {mdb_id} MDBINS_BIS"),
                    txt(i, "FKT_LANG"),
                    datum(txt(i, "FKTINS_VON"), f"MDB {mdb_id} FKTINS_VON"),
                    datum(txt(i, "FKTINS_BIS"), f"MDB {mdb_id} FKTINS_BIS"),
                ))
    return mdb, namen, perioden, institutionen


def schreibe_insert(datei, tabelle, spalten, zeilen, schluessel):
    if not zeilen:
        return
    setzen = ",\n    ".join(f"{s} = EXCLUDED.{s}"
                            for s in spalten if s not in schluessel)
    datei.write(f"INSERT INTO {SCHEMA}.{tabelle} ({', '.join(spalten)}) VALUES\n")
    datei.write(",\n".join("(" + ", ".join(sql_wert(w) for w in z) + ")"
                           for z in zeilen))
    datei.write(f"\nON CONFLICT ({', '.join(schluessel)}) DO UPDATE SET\n    "
                f"{setzen};\n\n")


def main():
    lieferung.merke(LIEFERUNG)
    if not XML_PFAD.exists():
        raise SystemExit(f"Datei nicht gefunden: {XML_PFAD}")
    log.info("Lese %s", XML_PFAD)

    mdb, namen, perioden, institutionen = lies_xml(XML_PFAD)
    log.info("Gelesen: %d Abgeordnete, %d Namensfassungen, %d Wahlperioden, " "%d Institutionen", len(mdb), len(namen), len(perioden),
             len(institutionen))

    run_sql(DDL, "roh_bundestag anlegen")

    tmp = Path(tempfile.gettempdir()) / "mdb_stammdaten.sql"
    with tmp.open("w", encoding="utf-8") as f:
        schreibe_insert(f, "stammdaten_mdb",
                        ["id", "geburtsdatum", "geburtsort", "geburtsland",
                         "sterbedatum", "geschlecht", "familienstand",
                         "religion", "beruf", "partei_kurz", "vita_kurz",
                         "veroeffentlichungspflichtiges"], mdb, ["id"])
        schreibe_insert(f, "stammdaten_mdb_name",
                        ["id", "lfd", "nachname", "vorname", "ortszusatz",
                         "adel", "praefix", "anrede_titel", "akad_titel",
                         "historie_von", "historie_bis"], namen, ["id", "lfd"])
        schreibe_insert(f, "stammdaten_mdb_wahlperiode",
                        ["id", "wp", "mdbwp_von", "mdbwp_bis", "wkr_nummer",
                         "wkr_name", "wkr_land", "liste", "mandatsart"],
                        perioden, ["id", "wp"])
        schreibe_insert(f, "stammdaten_mdb_institution",
                        ["id", "wp", "lfd", "insart_lang", "ins_lang",
                         "mdbins_von", "mdbins_bis", "fkt_lang", "fktins_von",
                         "fktins_bis"], institutionen, ["id", "wp", "lfd"])
    log.info("SQL geschrieben: %s (%.1f MB)", tmp, tmp.stat().st_size / 1e6)

    run_sql_file(tmp, "mdb-stammdaten")
    bericht()


def bericht():
    print("\nZeilen je Tabelle:")
    for t in ("stammdaten_mdb", "stammdaten_mdb_name",
              "stammdaten_mdb_wahlperiode", "stammdaten_mdb_institution"):
        n = query(f"SELECT count(*) FROM {SCHEMA}.{t};")[0][0]
        print(f"   {t:<32} {n:>7}")

    print("\nWahlperioden 18 bis 20 - Wahlkreisabdeckung:")
    zeilen = query(f"""
        SELECT wp, count(*),
               count(wkr_nummer),
               count(*) FILTER (WHERE mandatsart = 'Direktwahl'),
               count(*) FILTER (WHERE mandatsart = 'Direktwahl'
                                  AND wkr_nummer IS NOT NULL)
          FROM {SCHEMA}.stammdaten_mdb_wahlperiode
         WHERE wp IN (18, 19, 20) GROUP BY wp ORDER BY wp;""")
    print(f"   {'WP':<5}{'Eintraege':>10}{'mit WK-Nr':>11}"
          f"{'Direktwahl':>12}{'davon mit Nr':>14}")
    for wp, ges, mit_nr, direkt, direkt_nr in zeilen:
        print(f"   {wp:<5}{ges:>10}{mit_nr:>11}{direkt:>12}{direkt_nr:>14}")

    print("\n   Erwartet: 'Direktwahl' und 'davon mit Nr' sind je 299 und gleich.")
    print("   Weicht das ab, stimmt die Annahme nicht, auf der Eingriff E1 " "beruht.")


if __name__ == "__main__":
    main()
