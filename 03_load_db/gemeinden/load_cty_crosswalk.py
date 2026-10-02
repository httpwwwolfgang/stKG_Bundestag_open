import sys
import csv
import logging
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

DB_SCHEMA   = "roh_crosswalk"
META_SCHEMA = "meta"
TABELLE     = "cty_crosswalk"

DATEI = (Path(__file__).resolve().parents[4] / "Daten" / "wahlergebnisse"
         / "GERDA" / "cty_crosswalks.txt")

SPALTEN = ["county_code", "county_name", "year", "area_cw", "pop_cw", "area",
           "population", "county_code_21", "county_name_21", "emp_cw", "employees"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("roh-cty-crosswalk")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;

CREATE TABLE {DB_SCHEMA}.{TABELLE} (
    county_code    TEXT,
    county_name    TEXT,
    year           TEXT,
    area_cw        TEXT,
    pop_cw         TEXT,
    area           TEXT,
    population     TEXT,
    county_code_21 TEXT,
    county_name_21 TEXT,
    emp_cw         TEXT,
    employees      TEXT,
    lieferung_id   TEXT
);
CREATE INDEX {TABELLE}_code_jahr ON {DB_SCHEMA}.{TABELLE} (county_code, year);
CREATE INDEX {TABELLE}_ziel      ON {DB_SCHEMA}.{TABELLE} (county_code_21);
"""


def merke_lieferung():
    run_sql(f"""
    INSERT INTO {META_SCHEMA}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, datei, gebietsstand, lizenz, art)
    VALUES ('bbsr_cty_crosswalk',
            'BBSR-Umsteigeschluessel Kreise auf Gebietsstand 2021',
            'BBSR, verteilt ueber GERDA (Heddesheimer u.a. 2025, doi:10.1038/s41597-025-04811-5)',
            '{DATEI.name}', DATE '2021-12-31', 'CC-BY-4.0', 'amtlich')
    ON CONFLICT (lieferung_id) DO UPDATE SET bezeichnung = EXCLUDED.bezeichnung;
    """, "lieferung bbsr_cty_crosswalk")


def laden():
    if not DATEI.exists():
        raise SystemExit(f"Datei fehlt: {DATEI}")
    with DATEI.open(encoding="utf-8", newline="") as fh:
        kopf = next(csv.reader(fh))
    if kopf != SPALTEN:
        raise SystemExit(f"Unerwarteter Spaltenkopf: {kopf}")
    log.info("Spaltenkopf wie erwartet (%d Spalten)", len(kopf))

    sql = Path(tempfile.gettempdir()) / "roh_cty_crosswalk.sql"
    sql.write_text(
        f"TRUNCATE {DB_SCHEMA}.{TABELLE};\n"
        f"\\copy {DB_SCHEMA}.{TABELLE} ({', '.join(SPALTEN)}) "
        f"FROM '{DATEI.as_posix()}' "
        f"WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');\n"
        f"UPDATE {DB_SCHEMA}.{TABELLE} SET lieferung_id = 'bbsr_cty_crosswalk';\n",
        encoding="utf-8")
    run_sql_file(sql, label="copy roh_cty_crosswalk")
    sql.unlink(missing_ok=True)


def pruefe():
    log.info("--- Umfang ---")
    for zeile in query(f"""
        SELECT min(year), max(year), count(*), count(DISTINCT year),
               count(DISTINCT county_code_21)
        FROM {DB_SCHEMA}.{TABELLE};
    """):
        log.info("  Jahrgaenge %s bis %s, %s Zeilen, %s Jahrgaenge, " "%s verschiedene Ziele im Stand 2021", *zeile)

    log.info("--- Schluessellaengen ---")
    for zeile in query(f"""
        SELECT length(trim(county_code)), length(trim(county_code_21)), count(*)
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  Quelle %s Stellen, Ziel %s Stellen: %s Zeilen", *zeile)

    log.info("--- Gewichtssummen je Kreis und Jahrgang ---")
    for zeile in query(f"""
        WITH s AS (
            SELECT year, county_code,
                   sum(pop_cw::double precision)  AS summe_pop,
                   sum(area_cw::double precision) AS summe_area
            FROM {DB_SCHEMA}.{TABELLE}
            WHERE pop_cw <> '' AND area_cw <> '' GROUP BY 1, 2
        )
        SELECT count(*) FILTER (WHERE abs(summe_area - 1) > 0.01),
               count(*) FILTER (WHERE abs(summe_pop  - 1) > 0.01)
        FROM s;
    """):
        log.info("  Flaechengewicht != 1: %s | Bevoelkerungsgewicht != 1: %s", *zeile)


def main():
    if "--neu" in sys.argv:
        run_sql(DDL, "ddl roh cty_crosswalk")
    merke_lieferung()
    laden()
    pruefe()


if __name__ == "__main__":
    main()
