import csv
import glob
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

DB_SCHEMA = "parteien"
META_SCHEMA = "meta"

T_KATEGORIE = "manifesto_kategorie"
T_PROGRAMM = "manifesto_programm"
T_ANTEIL = "manifesto_anteil"
T_STG = "stg_manifesto"

DATEN = Path(__file__).resolve().parents[4] / "Daten" / "PArteipositionen"
KATEGORIEN = (Path(__file__).resolve().parents[2] / "02_clean"
              / "export" / "manifesto_kategorien.csv")

LIEFERUNG = "manifesto_mpds_2025a"


RILE_TOLERANZ = 0.05

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("manifesto")


def ddl():
    return f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};
CREATE SCHEMA IF NOT EXISTS {META_SCHEMA};
CREATE TABLE IF NOT EXISTS {META_SCHEMA}.datenlieferung (
    lieferung_id TEXT PRIMARY KEY,
    bezeichnung  TEXT NOT NULL,
    herausgeber  TEXT NOT NULL,
    datei        TEXT,
    gebietsstand DATE,
    lizenz       TEXT,
    wahljahr     SMALLINT
);
ALTER TABLE {META_SCHEMA}.datenlieferung
    ADD COLUMN IF NOT EXISTS art   TEXT NOT NULL DEFAULT 'amtlich',
    ADD COLUMN IF NOT EXISTS basis TEXT[];

DROP TABLE IF EXISTS {DB_SCHEMA}.{T_ANTEIL}    CASCADE;
DROP TABLE IF EXISTS {DB_SCHEMA}.{T_PROGRAMM}  CASCADE;
DROP TABLE IF EXISTS {DB_SCHEMA}.{T_KATEGORIE} CASCADE;
CREATE TABLE {DB_SCHEMA}.{T_KATEGORIE} (
    code            TEXT PRIMARY KEY,

    art             TEXT NOT NULL,
    hauptkategorie  TEXT,
    domaene         SMALLINT,
    domaene_name    TEXT,
    bezeichnung     TEXT NOT NULL,

    rile_seite      TEXT,


    gegenkategorie  TEXT,

    zaehlt_als_uncodiert BOOLEAN NOT NULL
);

CREATE TABLE {DB_SCHEMA}.{T_PROGRAMM} (
    id_perm           TEXT PRIMARY KEY,
    land_code         SMALLINT,
    land              TEXT,
    eu_mitglied       SMALLINT,
    oecd_mitglied     SMALLINT,
    wahltag           DATE,
    wahl_jahrmonat    INTEGER,
    partei_code       TEXT NOT NULL,
    partei_name       TEXT,
    partei_kuerzel    TEXT,
    kandidat          TEXT,

    codierer          TEXT,
    handbuch          SMALLINT,
    codierjahr        SMALLINT,
    reliabilitaet     DOUBLE PRECISION,
    testeditsim       DOUBLE PRECISION,


    stimmenanteil     DOUBLE PRECISION,
    stimmenanteil_geschaetzt DOUBLE PRECISION,
    sitze             INTEGER,
    sitze_gesamt      INTEGER,


    saetze            INTEGER,
    uncodiert         DOUBLE PRECISION,
    programmtyp       SMALLINT,
    datensatzherkunft SMALLINT,
    korpusversion     TEXT,

    rile              DOUBLE PRECISION,
    planeco           DOUBLE PRECISION,
    markeco           DOUBLE PRECISION,
    welfare           DOUBLE PRECISION,
    intpeace          DOUBLE PRECISION,
    datensatzversion  TEXT,
    lieferung_id      TEXT,
    UNIQUE (land_code, partei_code, wahl_jahrmonat),
    FOREIGN KEY (lieferung_id)
        REFERENCES {META_SCHEMA}.datenlieferung (lieferung_id)
);
CREATE INDEX {T_PROGRAMM}_partei ON {DB_SCHEMA}.{T_PROGRAMM} (partei_code);
CREATE INDEX {T_PROGRAMM}_land   ON {DB_SCHEMA}.{T_PROGRAMM} (land_code, wahl_jahrmonat);

CREATE TABLE {DB_SCHEMA}.{T_ANTEIL} (
    id_perm TEXT NOT NULL,
    code    TEXT NOT NULL,



    anteil  DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (id_perm, code),
    FOREIGN KEY (id_perm)
        REFERENCES {DB_SCHEMA}.{T_PROGRAMM} (id_perm) ON DELETE CASCADE,
    FOREIGN KEY (code)
        REFERENCES {DB_SCHEMA}.{T_KATEGORIE} (code)
);
CREATE INDEX {T_ANTEIL}_code ON {DB_SCHEMA}.{T_ANTEIL} (code);
"""


def finde_quelle():
    treffer = sorted(glob.glob(str(DATEN / "MPDataset_*.csv")))
    if len(treffer) != 1:
        raise SystemExit("Erwarte genau eine MPDataset-CSV in %s, gefunden: %s"
                         % (DATEN, treffer))
    return Path(treffer[0])


def lit(wert):
    if wert is None or wert == "":
        return "NULL"
    return "'" + str(wert).replace("'", "''") + "'"


def merke_lieferung(datei):
    run_sql(f"""
    INSERT INTO {META_SCHEMA}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, datei, lizenz, art)
    VALUES ('{LIEFERUNG}',
            'Manifesto Project Dataset MPDS2025a, Programmpositionen von '
            '5.285 Wahlprogrammen aus 67 Laendern, 1920-2025',
            'Lehmann et al. (2025), WZB Berlin / IfDem Goettingen, '
            'doi:10.25522/manifesto.mpds.2025a',
            {lit(datei.name)}, 'siehe Nutzungsbedingungen des Projekts',
            'amtlich')
    ON CONFLICT (lieferung_id) DO UPDATE SET bezeichnung = EXCLUDED.bezeichnung;
    """, "lieferung manifesto")


def lade_stammdaten():
    if not KATEGORIEN.exists():
        raise SystemExit(
            "Kategorienliste fehlt: %s\n" "Erst 'python parse_manifesto_kategorien.py' in 02_clean/ " "laufen lassen." % KATEGORIEN)

    with KATEGORIEN.open(encoding="utf-8", newline="") as fh:
        zeilen = list(csv.DictReader(fh, delimiter=";"))
    if len(zeilen) != 142:
        raise SystemExit("Kategorienliste hat %d Zeilen, erwartet 142"
                         % len(zeilen))

    werte = ",\n        ".join(
        "({}, {}, {}, {}, {}, {}, {}, {}, {})".format(
            lit(z["code"]), lit(z["art"]), lit(z["hauptkategorie"] or None),
            z["domaene"], lit(z["domaene_name"]), lit(z["bezeichnung"]),
            lit(z["rile_seite"] or None), lit(z["gegenkategorie"] or None),
            "TRUE" if z["zaehlt_als_uncodiert"] == "ja" else "FALSE")
        for z in zeilen)
    sql = Path(tempfile.gettempdir()) / f"{T_KATEGORIE}.sql"
    sql.write_text(
        "SET client_encoding TO 'UTF8';\n"
        f"INSERT INTO {DB_SCHEMA}.{T_KATEGORIE} (code, art, hauptkategorie, " "domaene, domaene_name, bezeichnung, rile_seite, gegenkategorie, "
        f"zaehlt_als_uncodiert)\n    VALUES {werte}\n" "ON CONFLICT (code) DO NOTHING;\n", encoding="utf-8")
    run_sql_file(sql, label="kategorien")
    sql.unlink(missing_ok=True)
    return [z["code"] for z in zeilen]


def staging(datei):
    with datei.open(encoding="utf-8", newline="") as fh:
        kopf = next(csv.reader(fh))
    log.info("%d Spalten in %s", len(kopf), datei.name)

    tab = f"{DB_SCHEMA}.{T_STG}"
    namen = [f"c{i:03d}" for i in range(len(kopf))]
    sql = Path(tempfile.gettempdir()) / f"{T_STG}.sql"
    sql.write_text(
        f"DROP TABLE IF EXISTS {tab};\n"
        f"CREATE TABLE {tab} (\n    "
        + ",\n    ".join(f"{n} TEXT" for n in namen) + "\n);\n"
        f"\\copy {tab} FROM '{datei.as_posix()}' "
        f"WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');\n",
        encoding="utf-8")
    run_sql_file(sql, label="staging manifesto")
    sql.unlink(missing_ok=True)
    return tab, kopf, namen


def text(spalte):
    return f"nullif(nullif(trim({spalte}), ''), 'NA')"


def zahl(spalte, typ="int"):
    if typ == "int":
        return f"(CASE WHEN {spalte} ~ '^-?[0-9]+$' THEN {spalte}::int END)"
    return (f"(CASE WHEN {spalte} ~ '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$' "
            f"THEN {spalte}::double precision END)")


def verteile(tab, kopf, namen, codes):
    idx = {n: namen[i] for i, n in enumerate(kopf)}
    i = lambda n: zahl(idx[n], "int")
    d = lambda n: zahl(idx[n], "float")

    run_sql(f"""
    INSERT INTO {DB_SCHEMA}.{T_PROGRAMM}
        (id_perm, land_code, land, eu_mitglied, oecd_mitglied,
         wahltag, wahl_jahrmonat,
         partei_code, partei_name, partei_kuerzel, kandidat,
         codierer, handbuch, codierjahr, reliabilitaet, testeditsim,
         stimmenanteil, stimmenanteil_geschaetzt, sitze, sitze_gesamt,
         saetze, uncodiert, programmtyp, datensatzherkunft, korpusversion,
         rile, planeco, markeco, welfare, intpeace,
         datensatzversion, lieferung_id)
    SELECT {idx['id_perm']},
           {i('country')}, {text(idx['countryname'])},
           {i('eumember')}, {i('oecdmember')},
           to_date(nullif(trim({idx['edate']}), ''), 'DD/MM/YYYY'),
           {i('date')},
           trim({idx['party']}),
           {text(idx['partyname'])},
           {text(idx['partyabbrev'])},
           {text(idx['candidatename'])},
           {text(idx['coderid'])},
           {i('manual')}, {i('coderyear')},
           {d('testresult')}, {d('testeditsim')},
           {d('pervote')}, {d('voteest')}, {i('absseat')}, {i('totseats')},
           {i('total')}, {d('peruncod')},
           {i('progtype')}, {i('datasetorigin')},
           {text(idx['corpusversion'])},
           {d('rile')}, {d('planeco')}, {d('markeco')},
           {d('welfare')}, {d('intpeace')},
           {text(idx['datasetversion'])},
           '{LIEFERUNG}'
    FROM {tab}
    WHERE trim({idx['id_perm']}) <> ''
    ON CONFLICT DO NOTHING;
    """, "programme")


    teile = [
        f"SELECT {idx['id_perm']}, '{c}', {zahl(idx['per' + c], 'float')}\n"
        f"FROM {tab} WHERE trim({idx['id_perm']}) <> '' "
        f"AND {zahl(idx['per' + c], 'float')} IS NOT NULL"
        for c in codes]
    sql = Path(tempfile.gettempdir()) / f"{T_ANTEIL}.sql"
    sql.write_text(
        "SET client_encoding TO 'UTF8';\n"
        f"INSERT INTO {DB_SCHEMA}.{T_ANTEIL} (id_perm, code, anteil)\n"
        + "\nUNION ALL\n".join(teile) + "\nON CONFLICT DO NOTHING;\n",
        encoding="utf-8")
    run_sql_file(sql, label="anteile")
    sql.unlink(missing_ok=True)

    run_sql(f"DROP TABLE IF EXISTS {tab};", "staging weg")


def pruefe():
    log.info("--- Umfang ---")
    for zeile in query(f"""
        SELECT (SELECT count(*) FROM {DB_SCHEMA}.{T_KATEGORIE}),
               (SELECT count(*) FROM {DB_SCHEMA}.{T_PROGRAMM}),
               (SELECT count(*) FROM {DB_SCHEMA}.{T_ANTEIL}),
               (SELECT count(DISTINCT land) FROM {DB_SCHEMA}.{T_PROGRAMM});
    """):
        log.info("  %s Kategorien, %s Programme, %s Anteilszeilen, %s Laender",
                 *zeile)

    log.info("--- NA gegen echte Null: die Unterscheidung muss stehen ---")
    for zeile in query(f"""
        SELECT count(*) FILTER (WHERE anteil = 0),
               count(*) FILTER (WHERE anteil > 0),
               (SELECT count(*) FROM {DB_SCHEMA}.{T_PROGRAMM}) * 142
                 - count(*)
        FROM {DB_SCHEMA}.{T_ANTEIL};
    """):
        log.info("  %s Zeilen mit Wert 0 (erhoben, nichts gesagt), %s mit " "Wert ueber 0, %s Zellen ohne Zeile (nicht erhebbar)", *zeile)

    log.info("--- Deutschland, Wahlen ab 1990 ---")
    for zeile in query(f"""
        SELECT wahl_jahrmonat, count(*),
               round(sum(stimmenanteil)::numeric, 2),
               min(saetze), max(saetze)
        FROM {DB_SCHEMA}.{T_PROGRAMM}
        WHERE land = 'Germany' AND wahl_jahrmonat >= 199000
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Parteien, %s %% der Stimmen, Saetze %s bis %s",
                 *zeile)

    log.info("--- Hauptkategorien ohne Gegenkategorie (nur eine Richtung) ---")
    for zeile in query(f"""
        SELECT count(*) FILTER (WHERE gegenkategorie IS NULL),
               count(*)
        FROM {DB_SCHEMA}.{T_KATEGORIE} WHERE art = 'haupt';
    """):
        log.info("  %s von %s Hauptkategorien - dort ist ein niedriger Wert " "doppeldeutig", *zeile)

    log.info("--- rile nachgerechnet gegen die gelieferte Spalte ---")
    for zeile in query(f"""
        WITH eigen AS (
            SELECT a.id_perm,
                   sum(CASE k.rile_seite WHEN 'rechts' THEN a.anteil
                                         WHEN 'links'  THEN -a.anteil
                                         ELSE 0 END) AS wert
            FROM {DB_SCHEMA}.{T_ANTEIL} a
            JOIN {DB_SCHEMA}.{T_KATEGORIE} k ON k.code = a.code
            WHERE k.art = 'haupt'
            GROUP BY 1)
        SELECT count(*),
               count(*) FILTER (WHERE abs(e.wert - p.rile) >= {RILE_TOLERANZ}),
               round(max(abs(e.wert - p.rile))::numeric, 4),
               count(*) FILTER (WHERE abs(e.wert - p.rile) >= {RILE_TOLERANZ}
                                  AND p.korpusversion IS NOT NULL),
               count(*) FILTER (WHERE abs(e.wert - p.rile) >= {RILE_TOLERANZ}
                                  AND p.land = 'Germany')
        FROM eigen e JOIN {DB_SCHEMA}.{T_PROGRAMM} p USING (id_perm)
        WHERE p.rile IS NOT NULL;
    """):
        log.info("  %s Programme geprueft, %s weichen um %.2f oder mehr ab, " "groesste Abweichung %s",
                 zeile[0], zeile[1], RILE_TOLERANZ, zeile[2])
        log.info("  davon korpusbasiert: %s (erwartet 0), deutsch: %s " "(erwartet 0) - siehe Kopf", zeile[3], zeile[4])

    log.info("--- Woher kommen die Abweichungen? ---")
    for zeile in query(f"""
        WITH eigen AS (
            SELECT a.id_perm,
                   sum(CASE k.rile_seite WHEN 'rechts' THEN a.anteil
                                         WHEN 'links'  THEN -a.anteil
                                         ELSE 0 END) AS wert
            FROM {DB_SCHEMA}.{T_ANTEIL} a
            JOIN {DB_SCHEMA}.{T_KATEGORIE} k ON k.code = a.code
            WHERE k.art = 'haupt'
            GROUP BY 1)
        SELECT p.land, count(*)
        FROM eigen e JOIN {DB_SCHEMA}.{T_PROGRAMM} p USING (id_perm)
        WHERE p.rile IS NOT NULL AND abs(e.wert - p.rile) >= {RILE_TOLERANZ}
        GROUP BY 1 ORDER BY 2 DESC;
    """):
        log.info("  %s: %s Programme", *zeile)


def main():
    datei = finde_quelle()
    if "--neu" in sys.argv:
        run_sql(ddl(), f"ddl {DB_SCHEMA}")
    merke_lieferung(datei)
    codes = lade_stammdaten()
    tab, kopf, namen = staging(datei)
    verteile(tab, kopf, namen, codes)
    pruefe()


if __name__ == "__main__":
    main()
