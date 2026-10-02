import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "raum"
TABELLE   = "kreisstand_crosswalk"
VIEW      = "kreisstand_stichtag_crosswalk"
ROH       = "roh_crosswalk.cty_crosswalk"
STAND     = "raum.kreisstand"

ZIELJAHR = 2021

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kreisstand-crosswalk")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;

CREATE TABLE {DB_SCHEMA}.{TABELLE} (
    stichtag DATE     NOT NULL,
    kreis    CHAR(5)  NOT NULL,
    kreis_21 CHAR(5),
    jahrgang SMALLINT,
    pop_cw   DOUBLE PRECISION,
    area_cw  DOUBLE PRECISION,
    emp_cw   DOUBLE PRECISION,

    status   TEXT     NOT NULL
);
CREATE UNIQUE INDEX {TABELLE}_pk
    ON {DB_SCHEMA}.{TABELLE} (stichtag, kreis, coalesce(kreis_21, ''));
CREATE INDEX {TABELLE}_ziel   ON {DB_SCHEMA}.{TABELLE} (kreis_21);
CREATE INDEX {TABELLE}_status ON {DB_SCHEMA}.{TABELLE} (status);
"""


DDL_VIEW = f"""
DROP VIEW IF EXISTS {DB_SCHEMA}.{VIEW};
CREATE VIEW {DB_SCHEMA}.{VIEW} AS
SELECT s.stichtag, s.ags AS kreis, s.quelle_stand,
       c.kreis_21, c.jahrgang, c.pop_cw, c.area_cw, c.emp_cw, c.status
FROM {DB_SCHEMA}.kreisstand_stichtag s
LEFT JOIN {DB_SCHEMA}.{TABELLE} c
       ON c.stichtag = s.quelle_stand AND trim(c.kreis) = trim(s.ags);
"""


def aufbau():
    run_sql(f"""
    TRUNCATE {DB_SCHEMA}.{TABELLE};

    WITH cw AS (
        SELECT lpad(trim(county_code), 5, '0')    AS kreis,
               lpad(trim(county_code_21), 5, '0') AS kreis_21,
               trim(year)::smallint               AS jahrgang,
               nullif(trim(pop_cw),  '')::double precision AS pop_cw,
               nullif(trim(area_cw), '')::double precision AS area_cw,
               nullif(trim(emp_cw),  '')::double precision AS emp_cw
        FROM {ROH}
        WHERE trim(county_code)    ~ '^[0-9]{{4,5}}$'
          AND trim(county_code_21) ~ '^[0-9]{{4,5}}$'
          AND trim(year)           ~ '^[0-9]{{4}}$'
    )
    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (stichtag, kreis, kreis_21, jahrgang, pop_cw, area_cw, emp_cw, status)
    SELECT k.stichtag, trim(k.ags),
           CASE WHEN extract(year FROM k.stichtag) = {ZIELJAHR} THEN trim(k.ags)
                ELSE cw.kreis_21 END,
           CASE WHEN extract(year FROM k.stichtag) = {ZIELJAHR} THEN NULL
                ELSE cw.jahrgang END,
           CASE WHEN extract(year FROM k.stichtag) = {ZIELJAHR} THEN 1
                ELSE cw.pop_cw END,
           CASE WHEN extract(year FROM k.stichtag) = {ZIELJAHR} THEN 1
                ELSE cw.area_cw END,
           CASE WHEN extract(year FROM k.stichtag) = {ZIELJAHR} THEN NULL
                ELSE cw.emp_cw END,
           CASE WHEN extract(year FROM k.stichtag) = {ZIELJAHR} THEN 'zielstand'
                WHEN cw.kreis_21 IS NULL                        THEN 'ohne_eintrag'
                ELSE 'umsteigeschluessel' END
    FROM {STAND} k
    LEFT JOIN cw
           ON cw.kreis = trim(k.ags)
          AND cw.jahrgang = extract(year FROM k.stichtag)::smallint
    ON CONFLICT DO NOTHING;
    """, "aufbau kreisstand_crosswalk")
    run_sql(DDL_VIEW, "view kreisstand_stichtag_crosswalk")


def pruefe():
    log.info("--- Zuordnung je Jahresstand ---")
    for zeile in query(f"""
        SELECT stichtag, count(DISTINCT kreis) AS kreise,
               count(*) FILTER (WHERE status = 'umsteigeschluessel') AS zeilen_cw,
               count(DISTINCT kreis) FILTER (WHERE status = 'ohne_eintrag') AS ohne_eintrag,
               count(DISTINCT kreis) FILTER (WHERE trim(kreis) <> trim(kreis_21)) AS wechselt
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Kreise, %s Schluesselzeilen, %s ohne Eintrag, " "%s mit anderem Ziel", *zeile)

    log.info("--- Kreise mit mehr als einem Ziel (erwartet: keine) ---")
    for zeile in query(f"""
        SELECT stichtag, count(*) FROM (
            SELECT stichtag, kreis FROM {DB_SCHEMA}.{TABELLE}
            WHERE status = 'umsteigeschluessel'
            GROUP BY 1, 2 HAVING count(*) > 1
        ) x GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s", *zeile)

    log.info("--- Kreise ohne Eintrag ---")
    for zeile in query(f"""
        SELECT stichtag, kreis FROM {DB_SCHEMA}.{TABELLE}
        WHERE status = 'ohne_eintrag' ORDER BY 1, 2 LIMIT 20;
    """):
        log.info("  %s  %s", *zeile)

    log.info("--- Stichtagsstaende ueber die View ---")
    for zeile in query(f"""
        SELECT stichtag, count(*), count(*) FILTER (WHERE kreis_21 IS NULL)
        FROM {DB_SCHEMA}.{VIEW} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Zeilen, %s ohne Ziel", *zeile)

    log.info("--- Die Schluesselwechsel im Zeitraum ---")
    for zeile in query(f"""
        SELECT stichtag, kreis, kreis_21 FROM {DB_SCHEMA}.{TABELLE}
        WHERE trim(kreis) <> trim(kreis_21)
          AND stichtag IN (DATE '2013-12-31', DATE '2017-12-31')
        ORDER BY 1, 2;
    """):
        log.info("  %s  %s -> %s", *zeile)


def main():
    if "--neu" in sys.argv:
        run_sql(DDL, "ddl kreisstand_crosswalk")
    aufbau()
    pruefe()


if __name__ == "__main__":
    main()
