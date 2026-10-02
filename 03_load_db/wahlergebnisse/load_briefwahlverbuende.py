import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "gerda"
T_GEM     = "briefwahl_gemeinde"
T_VERBUND = "briefwahl_verbund"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("briefwahl")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_GEM} (
    wahljahr        SMALLINT NOT NULL,
    ags             CHAR(8)  NOT NULL,
    gemeinde        TEXT,
    kreis           TEXT,
    bwbez           TEXT,
    verbund_id      TEXT,
    briefwahl       TEXT     NOT NULL,
    wahlberechtigte INTEGER,
    geom            geometry(MultiPolygon, 25832) NOT NULL,



    PRIMARY KEY (wahljahr, ags, bwbez)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_VERBUND} (
    wahljahr        SMALLINT NOT NULL,
    verbund_id      TEXT     NOT NULL,
    kreis           TEXT,
    bwbez           TEXT,
    gemeinden       INTEGER,
    wahlberechtigte INTEGER,
    geom            geometry(MultiPolygon, 25832) NOT NULL,
    PRIMARY KEY (wahljahr, verbund_id)
);

CREATE INDEX IF NOT EXISTS {T_GEM}_gix ON {DB_SCHEMA}.{T_GEM} USING GIST (geom);
CREATE INDEX IF NOT EXISTS {T_VERBUND}_gix ON {DB_SCHEMA}.{T_VERBUND} USING GIST (geom);
CREATE INDEX IF NOT EXISTS {T_GEM}_verbund ON {DB_SCHEMA}.{T_GEM} (wahljahr, verbund_id);
"""


UEBERNAHME = f"""
TRUNCATE {DB_SCHEMA}.{T_GEM};
TRUNCATE {DB_SCHEMA}.{T_VERBUND};

INSERT INTO {DB_SCHEMA}.{T_GEM}
    (wahljahr, ags, gemeinde, kreis, bwbez, verbund_id, briefwahl,
     wahlberechtigte, geom)
SELECT DISTINCT ON (e.wahljahr, e.ags_gem, e.bwbez)
       e.wahljahr, e.ags_gem, s.gen, e.kreis, e.bwbez,
       CASE WHEN e.im_verbund THEN e.kreis || '-' || e.bwbez END,
       CASE WHEN e.im_verbund THEN 'verbund' ELSE 'eigen' END,
       e.wahlberechtigte,
       s.geom
FROM (
    SELECT g.wahljahr, g.kreis,



           CASE WHEN left(g.ags, 2) IN ('11', '02') THEN '00'
                ELSE g.bwbez END AS bwbez,




           raum.gemeinde_ags(g.ags) AS ags_gem,




           EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeindeeinheit_gerda v
                   WHERE v.einheitstyp = 'briefwahlverbund'
                     AND v.wahljahr = g.wahljahr
                     AND v.kreis = g.kreis AND v.bwbez = g.bwbez) AS im_verbund,





           CASE WHEN left(g.ags, 2) IN ('11', '02')
                THEN (SELECT sum(k.wert)
                        FROM {DB_SCHEMA}.wahlkennzahl_gerda_wahlkreis k
                        JOIN raum.wahlkreis w
                          ON (w.wahljahr, w.wkr_nr) = (k.wahljahr, k.wkr_nr)
                       WHERE k.wahljahr = g.wahljahr
                         AND k.stimme = 'zweitstimme'
                         AND k.merkmal = 'wahlberechtigte'
                         AND w.land_name = CASE left(g.ags, 2)
                                             WHEN '11' THEN 'Berlin'
                                             ELSE 'Hamburg' END)
                ELSE (SELECT k.wert FROM {DB_SCHEMA}.gemeindekennzahl_gerda k
                      WHERE (k.wahljahr, k.ags, k.bwbez) = (g.wahljahr, g.ags, g.bwbez)
                        AND k.merkmal = 'wahlberechtigte') END AS wahlberechtigte
    FROM {DB_SCHEMA}.gemeindeeinheit_gerda g
    WHERE g.einheitstyp = 'gemeinde'
) e
JOIN zeit.stichtag t
  ON t.art = 'wahltag' AND t.bezug = 'Wahl ' || e.wahljahr::text
JOIN raum.gemeindestand_stichtag s
  ON s.stichtag = t.datum AND s.ags = e.ags_gem
ORDER BY e.wahljahr, e.ags_gem, e.bwbez, e.wahlberechtigte DESC NULLS LAST;

INSERT INTO {DB_SCHEMA}.{T_VERBUND}
    (wahljahr, verbund_id, kreis, bwbez, gemeinden, wahlberechtigte, geom)
SELECT wahljahr, verbund_id, max(kreis), max(bwbez),
       count(*), sum(wahlberechtigte),
       ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(geom)), 3))
FROM {DB_SCHEMA}.{T_GEM}
WHERE verbund_id IS NOT NULL
GROUP BY wahljahr, verbund_id;
"""


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, T_GEM)
    log.info("%-6s %-12s %9s %14s", "Jahr", "Briefwahl", "Gemeinden", "Wahlberechtigte")
    for zeile in query(f"""
        SELECT wahljahr, briefwahl, count(*), to_char(sum(wahlberechtigte), 'FM999G999G999')
        FROM {DB_SCHEMA}.{T_GEM} GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("%-6s %-12s %9s %14s", *(f or "" for f in zeile))

    log.info("--- %s.%s ---", DB_SCHEMA, T_VERBUND)
    for zeile in query(f"""
        SELECT wahljahr, count(*), min(gemeinden), round(avg(gemeinden), 1), max(gemeinden)
        FROM {DB_SCHEMA}.{T_VERBUND} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Verbuende, %s bis %s Gemeinden (Mittel %s)",
                 zeile[0], zeile[1], zeile[2], zeile[4], zeile[3])


    log.info("--- ohne Geometrie, nicht uebernommen ---")
    for zeile in query(f"""
        SELECT e.wahljahr, count(*), count(DISTINCT left(e.ags, 2))
        FROM {DB_SCHEMA}.gemeindeeinheit_gerda e
        WHERE e.einheitstyp = 'gemeinde'
          AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{T_GEM} g
                          WHERE (g.wahljahr, g.ags) = (e.wahljahr, e.ags))
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Einheiten aus %s Laendern", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        for t in (T_GEM, T_VERBUND):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;", f"drop {t}")
        log.warning("Tabellen verworfen.")

    run_sql(DDL, "ddl")
    run_sql(UEBERNAHME, "briefwahlverbuende")
    report()


if __name__ == "__main__":
    main()
