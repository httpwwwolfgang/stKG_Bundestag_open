import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "raum"
TABELLE   = "gemeindestand_crosswalk"
VIEW      = "gemeindestand_stichtag_crosswalk"
ROH       = "roh_crosswalk.ags_crosswalk"
STAND     = "raum.gemeindestand"
STICHTAGSSTAND = "raum.gemeindestand_stichtag"
UEBERGANG      = "raum.gebietsuebergang"


ZIELJAHR  = 2021
ZIELSTAND = "2021-12-31"

WAHLTAG   = "2021-09-26"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemeindestand-crosswalk")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

DROP VIEW  IF EXISTS {DB_SCHEMA}.{VIEW}    CASCADE;
DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;

CREATE TABLE {DB_SCHEMA}.{TABELLE} (
    stichtag DATE     NOT NULL,
    ags      CHAR(8)  NOT NULL,
    ags_21   CHAR(8),
    jahrgang SMALLINT,
    pop_cw   DOUBLE PRECISION,
    area_cw  DOUBLE PRECISION,
    emp_cw   DOUBLE PRECISION,

    status   TEXT     NOT NULL,
    FOREIGN KEY (stichtag, ags) REFERENCES {STAND} (stichtag, ags)
);
CREATE UNIQUE INDEX {TABELLE}_pk
    ON {DB_SCHEMA}.{TABELLE} (stichtag, ags, coalesce(ags_21, ''));
CREATE INDEX {TABELLE}_ziel   ON {DB_SCHEMA}.{TABELLE} (ags_21);
CREATE INDEX {TABELLE}_status ON {DB_SCHEMA}.{TABELLE} (status);
"""


DDL_VIEW = f"""
DROP VIEW IF EXISTS {DB_SCHEMA}.{VIEW};
CREATE VIEW {DB_SCHEMA}.{VIEW} AS
SELECT s.stichtag, s.ags, s.quelle_stand,
       c.ags_21, c.jahrgang, c.pop_cw, c.area_cw, c.emp_cw, c.status
FROM {DB_SCHEMA}.gemeindestand_stichtag s
LEFT JOIN {DB_SCHEMA}.{TABELLE} c
       ON c.stichtag = s.quelle_stand AND c.ags = s.ags;
"""


def aufbau():
    run_sql(f"""
    TRUNCATE {DB_SCHEMA}.{TABELLE};

    WITH cw AS (
        SELECT lpad(trim(ags), 8, '0')    AS ags,
               lpad(trim(ags_21), 8, '0') AS ags_21,
               trim(year)::smallint       AS jahrgang,
               nullif(trim(pop_cw),  '')::double precision AS pop_cw,
               nullif(trim(area_cw), '')::double precision AS area_cw,
               nullif(trim(emp_cw),  '')::double precision AS emp_cw
        FROM {ROH}
        WHERE trim(ags)    ~ '^[0-9]{{7,8}}$'
          AND trim(ags_21) ~ '^[0-9]{{7,8}}$'
          AND trim(year)   ~ '^[0-9]{{4}}$'
    )
    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (stichtag, ags, ags_21, jahrgang, pop_cw, area_cw, emp_cw, status)
    SELECT g.stichtag, g.ags,
           CASE WHEN extract(year FROM g.stichtag) = {ZIELJAHR} THEN g.ags
                ELSE cw.ags_21 END,
           CASE WHEN extract(year FROM g.stichtag) = {ZIELJAHR} THEN NULL
                ELSE cw.jahrgang END,
           CASE WHEN extract(year FROM g.stichtag) = {ZIELJAHR} THEN 1
                ELSE cw.pop_cw END,
           CASE WHEN extract(year FROM g.stichtag) = {ZIELJAHR} THEN 1
                ELSE cw.area_cw END,
           CASE WHEN extract(year FROM g.stichtag) = {ZIELJAHR} THEN NULL
                ELSE cw.emp_cw END,
           CASE WHEN extract(year FROM g.stichtag) = {ZIELJAHR} THEN 'zielstand'
                WHEN cw.ags_21 IS NULL                          THEN 'ohne_eintrag'
                ELSE 'umsteigeschluessel' END
    FROM {STAND} g
    LEFT JOIN cw
           ON cw.ags = g.ags
          AND cw.jahrgang = extract(year FROM g.stichtag)::smallint
    ON CONFLICT DO NOTHING;
    """, "aufbau gemeindestand_crosswalk")
    bayerische_forste()
    run_sql(DDL_VIEW, "view gemeindestand_stichtag_crosswalk")


def bayerische_forste():
    run_sql(f"""
    WITH offen AS (
        SELECT c.stichtag, c.ags
        FROM {DB_SCHEMA}.{TABELLE} c
        WHERE c.status = 'ohne_eintrag'
          AND EXISTS (SELECT 1 FROM {ROH} x
                      WHERE x.year = '2019'
                        AND lpad(trim(x.ags), 8, '0') = trim(c.ags))
          AND NOT EXISTS (
              SELECT 1 FROM {UEBERGANG} g
              WHERE g.ebene = 'Gemeinde'
                AND (trim(g.ags_alt) = trim(c.ags) OR trim(g.ags_neu) = trim(c.ags))
                AND g.wirksam > c.stichtag AND g.wirksam <= DATE '2018-12-31'
                AND NOT (right(trim(g.ags_alt), 3) = '444' AND g.art = 'eingliederung'))
    )
    DELETE FROM {DB_SCHEMA}.{TABELLE} c
    USING offen o WHERE c.stichtag = o.stichtag AND c.ags = o.ags;
    """, "forste: alte Zeilen weg")

    run_sql(f"""
    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (stichtag, ags, ags_21, jahrgang, pop_cw, area_cw, emp_cw, status)
    SELECT g.stichtag, g.ags,
           lpad(trim(x.ags_21), 8, '0'),
           2019,
           nullif(trim(x.pop_cw),  '')::double precision,
           nullif(trim(x.area_cw), '')::double precision,
           nullif(trim(x.emp_cw),  '')::double precision,
           'jahrgang_2019'
    FROM {STAND} g
    JOIN {ROH} x ON x.year = '2019' AND lpad(trim(x.ags), 8, '0') = trim(g.ags)
    WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} c
                      WHERE c.stichtag = g.stichtag AND c.ags = g.ags)
    ON CONFLICT DO NOTHING;
    """, "forste: Jahrgang 2019 uebernehmen")


def pruefe():
    log.info("--- Zuordnung je Jahresstand ---")
    for zeile in query(f"""
        SELECT stichtag,
               count(DISTINCT ags)                                        AS gemeinden,
               count(*) FILTER (WHERE status = 'umsteigeschluessel')       AS zeilen_cw,
               count(DISTINCT ags) FILTER (WHERE status = 'ohne_eintrag')  AS ohne_eintrag,
               count(DISTINCT ags) FILTER (WHERE status = 'zielstand')     AS zielstand
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden, %s Schluesselzeilen, %s ohne Eintrag, " "%s Zielstand", *zeile)

    log.info("--- Gemeinden, die auf mehrere Ziele aufgeteilt werden ---")
    for zeile in query(f"""
        SELECT stichtag, count(*) FROM (
            SELECT stichtag, ags FROM {DB_SCHEMA}.{TABELLE}
            WHERE status = 'umsteigeschluessel'
            GROUP BY 1, 2 HAVING count(*) > 1
        ) x GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden mit mehr als einem Ziel", *zeile)

    log.info("--- Gemeinden ohne Eintrag im Umsteigeschluessel ---")
    for zeile in query(f"""
        SELECT stichtag, ags FROM {DB_SCHEMA}.{TABELLE}
        WHERE status = 'ohne_eintrag' ORDER BY 1, 2 LIMIT 40;
    """):
        log.info("  %s  %s", *zeile)

    log.info("--- Bevoelkerungsgewicht, das nicht auf 1 summiert ---")
    for zeile in query(f"""
        WITH s AS (
            SELECT stichtag, ags, sum(pop_cw) AS summe
            FROM {DB_SCHEMA}.{TABELLE}
            WHERE status = 'umsteigeschluessel'
            GROUP BY 1, 2
        )



        SELECT count(*)                                              AS faelle,
               count(DISTINCT s.ags)                                 AS gemeinden,
               count(*) FILTER (WHERE g.bez = 'Gemeindefreies Gebiet') AS gemeindefrei,
               count(*) FILTER (WHERE g.ags IS NULL)                 AS ohne_kennzeichen
        FROM s
        LEFT JOIN LATERAL (
            SELECT ags, bez FROM raum.gemeindestand
            WHERE ags = s.ags ORDER BY stichtag DESC LIMIT 1
        ) g ON TRUE
        WHERE abs(s.summe - 1) > 0.01;
    """):
        log.info("  %s Faelle bei %s Gemeinden, davon %s als gemeindefrei " "bekannt, %s ohne Kennzeichen im eigenen Bestand", *zeile)

    log.info("--- Stichtagsstaende ueber die View ---")
    for zeile in query(f"""
        SELECT stichtag,
               count(*)                                          AS gemeinden,
               count(*) FILTER (WHERE ags_21 IS NOT NULL)        AS mit_ziel,
               count(*) FILTER (WHERE ags_21 IS NULL)            AS ohne_ziel
        FROM {DB_SCHEMA}.{VIEW} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden, %s mit Ziel 2021, %s ohne", *zeile)


def main():
    if "--neu" in sys.argv:
        run_sql(DDL, "ddl gemeindestand_crosswalk")
    aufbau()
    pruefe()


if __name__ == "__main__":
    main()
