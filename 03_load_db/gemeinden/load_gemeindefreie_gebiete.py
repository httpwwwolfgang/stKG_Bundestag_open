import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "raum"
SICHT     = "gemeindefreies_gebiet"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemeindefrei")


SQL = f"""
DROP VIEW IF EXISTS {DB_SCHEMA}.{SICHT};

CREATE VIEW {DB_SCHEMA}.{SICHT} AS
SELECT
    g.stichtag,
    g.ags,
    g.gen                                          AS name,
    left(g.ags, 5)                                 AS kreis,
    g.flaeche_km2,



    EXISTS (SELECT 1
            FROM wahlergebnisse.wahlbezirk w
            JOIN zeit.stichtag z
              ON z.art = 'wahltag'
             AND z.datum = g.stichtag
             AND z.bezug = 'Wahl ' || w.wahljahr::text
            WHERE w.ags = g.ags)                   AS bewohnt,





    (SELECT min(gw.wkr_nr)
     FROM {DB_SCHEMA}.gemeinde_wahlkreis_wahltag gw
     JOIN zeit.stichtag z
       ON z.art = 'wahltag'
      AND z.datum = g.stichtag
      AND z.bezug = 'Wahl ' || gw.wahljahr::text
     WHERE gw.ags = g.ags)                         AS wkr_nr,
    g.geom
FROM {DB_SCHEMA}.gemeindestand_stichtag g
WHERE g.bez = 'Gemeindefreies Gebiet';

COMMENT ON VIEW {DB_SCHEMA}.{SICHT} IS
  'Gemeindefreie Gebiete je Stichtag - Forsten, Seen, Truppenuebungsplaetze. '
  'Sicht auf gemeindestand_stichtag, keine eigenen Daten. bewohnt = hat einen '
  'eigenen Wahlbezirk (genau zwei: Lohheide und Osterheide).';
"""


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, SICHT)
    for zeile in query(f"""
        SELECT stichtag::text, count(*) AS gebiete,
               count(*) FILTER (WHERE bewohnt) AS bewohnt,
               count(*) FILTER (WHERE wkr_nr IS NOT NULL) AS mit_wahlkreis,
               round(sum(flaeche_km2)::numeric, 0) AS km2
        FROM {DB_SCHEMA}.{SICHT}
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s  %4s Gebiete, %s bewohnt, %4s mit Wahlkreis, %6s km2", *zeile)

    log.info("--- Die bewohnten ---")
    for zeile in query(f"""
        SELECT DISTINCT ags, name, kreis, round(flaeche_km2::numeric, 1)
        FROM {DB_SCHEMA}.{SICHT} WHERE bewohnt ORDER BY 1;
    """):
        log.info("  %s %-16s Kreis %s  %s km2", *zeile)

    log.info("--- Die groessten (Stand 2021) ---")
    for zeile in query(f"""
        SELECT ags, name, round(flaeche_km2::numeric, 1), coalesce(wkr_nr::text, '-')
        FROM {DB_SCHEMA}.{SICHT}
        WHERE stichtag = DATE '2021-09-26'
        ORDER BY flaeche_km2 DESC LIMIT 5;
    """):
        log.info("  %s %-30s %7s km2  WK %s", *zeile)


def main():
    if not query(f"""SELECT 1 FROM {DB_SCHEMA}.gemeindestand_stichtag LIMIT 1;"""):
        raise SystemExit("gemeindestand_stichtag ist leer")
    run_sql(SQL, SICHT)
    report()


if __name__ == "__main__":
    main()
