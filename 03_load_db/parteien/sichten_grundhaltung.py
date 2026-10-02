import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "parteien"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grundhaltung")


DDL = f"""
DROP MATERIALIZED VIEW IF EXISTS {DB_SCHEMA}.gemeinde_grundhaltung CASCADE;

CREATE MATERIALIZED VIEW {DB_SCHEMA}.gemeinde_grundhaltung AS
WITH je_wahl AS (

    SELECT wahljahr, ags, anteil_links, abdeckung, median_rile,
           100.0 * percent_rank() OVER (PARTITION BY wahljahr
                                        ORDER BY anteil_links)
               AS links_perzentil
    FROM {DB_SCHEMA}.gemeinde_score_profil
),
agg AS (
    SELECT ags,
           count(*)                                        AS n_wahlen,
           round(avg(links_perzentil)::numeric, 1)         AS links_perzentil_mittel,
           round(stddev_samp(links_perzentil)::numeric, 1) AS links_perzentil_streuung,
           round(min(links_perzentil)::numeric, 1)         AS links_perzentil_min,
           round(max(links_perzentil)::numeric, 1)         AS links_perzentil_max,
           count(*) FILTER (WHERE links_perzentil >= 50)   AS n_linke_haelfte,

           round(avg(anteil_links), 2)                     AS anteil_links_mittel,
           round(min(abdeckung), 2)                        AS abdeckung_min
    FROM je_wahl
    GROUP BY 1
)
SELECT a.*,
       p.gemeindename, p.land,
       g.geom
FROM agg a
JOIN (SELECT DISTINCT ON (ags) ags, gemeindename, land
      FROM {DB_SCHEMA}.gemeinde_score_profil
      ORDER BY ags, wahljahr DESC) p ON p.ags = a.ags
LEFT JOIN raum.gemeindestand g
       ON g.ags = a.ags AND g.stichtag = DATE '2021-12-31';

CREATE UNIQUE INDEX gemeinde_grundhaltung_pk
    ON {DB_SCHEMA}.gemeinde_grundhaltung (ags);
CREATE INDEX gemeinde_grundhaltung_geom
    ON {DB_SCHEMA}.gemeinde_grundhaltung USING GIST (geom);
"""


def pruefe():
    log.info("--- Umfang ---")
    for z in query(f"""
        SELECT count(*), count(*) FILTER (WHERE geom IS NULL),
               count(*) FILTER (WHERE n_wahlen = 10)
        FROM {DB_SCHEMA}.gemeinde_grundhaltung;
    """):
        log.info("  %s Gemeinden, ohne Geometrie %s, mit allen zehn Wahlen %s",
                 *z)

    log.info("--- Verteilung der Grundhaltung (Perzentile der Kennzahl) ---")
    for z in query(f"""
        SELECT round(percentile_cont(0.05) WITHIN GROUP (ORDER BY links_perzentil_mittel)::numeric,1),
               round(percentile_cont(0.25) WITHIN GROUP (ORDER BY links_perzentil_mittel)::numeric,1),
               round(percentile_cont(0.50) WITHIN GROUP (ORDER BY links_perzentil_mittel)::numeric,1),
               round(percentile_cont(0.75) WITHIN GROUP (ORDER BY links_perzentil_mittel)::numeric,1),
               round(percentile_cont(0.95) WITHIN GROUP (ORDER BY links_perzentil_mittel)::numeric,1)
        FROM {DB_SCHEMA}.gemeinde_grundhaltung;
    """):
        log.info("  links_perzentil_mittel 5/25/50/75/95: %s %s %s %s %s", *z)
    for z in query(f"""
        SELECT round(percentile_cont(0.05) WITHIN GROUP (ORDER BY links_perzentil_streuung)::numeric,1),
               round(percentile_cont(0.50) WITHIN GROUP (ORDER BY links_perzentil_streuung)::numeric,1),
               round(percentile_cont(0.95) WITHIN GROUP (ORDER BY links_perzentil_streuung)::numeric,1)
        FROM {DB_SCHEMA}.gemeinde_grundhaltung;
    """):
        log.info("  links_perzentil_streuung 5/50/95: %s %s %s", *z)

    log.info("--- Wie viele waehlen durchgehend in derselben Haelfte? ---")
    for z in query(f"""
        SELECT n_linke_haelfte, count(*)
        FROM {DB_SCHEMA}.gemeinde_grundhaltung
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  in %2s von zehn Wahlen linke Haelfte: %s Gemeinden", *z)

    log.info("--- Die zehn verlaesslichsten je Richtung ---")
    for richtung, ordnung in (("linkesten", "DESC"), ("rechtesten", "ASC")):
        log.info("  die %s:", richtung)
        for z in query(f"""
            SELECT gemeindename, land, links_perzentil_mittel,
                   links_perzentil_streuung, n_linke_haelfte
            FROM {DB_SCHEMA}.gemeinde_grundhaltung
            WHERE n_wahlen = 10 AND links_perzentil_streuung < 10
            ORDER BY links_perzentil_mittel {ordnung} LIMIT 5;
        """):
            log.info("    %-26s %-3s Mittel %5s Streuung %5s  linke Haelfte " "%s/10", *z)


def main():
    run_sql(DDL, "sicht grundhaltung")
    pruefe()


if __name__ == "__main__":
    main()
