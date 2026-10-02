import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "parteien"
GERDA_SCHEMA = "gerda_seit_1990"
GEOM_STICHTAG = "2021-12-31"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("score-gemeinde")


DDL = f"""
DROP MATERIALIZED VIEW IF EXISTS {DB_SCHEMA}.gemeinde_score_profil CASCADE;
DROP MATERIALIZED VIEW IF EXISTS {DB_SCHEMA}.gemeinde_score_kurve  CASCADE;

CREATE MATERIALIZED VIEW {DB_SCHEMA}.gemeinde_score_kurve AS
WITH erfasst AS (
    SELECT wahljahr, ags, partei, manifesto_partei, rile, anteil,
           sum(anteil) OVER (PARTITION BY wahljahr, ags) AS abdeckung
    FROM {DB_SCHEMA}.gemeinde_partei
    WHERE hat_score AND anteil IS NOT NULL
)
SELECT wahljahr, ags, partei, manifesto_partei, rile,
       anteil,
       abdeckung,
       round((100.0 * anteil / nullif(abdeckung, 0))::numeric, 4)
           AS anteil_normiert,
       round((100.0 * sum(anteil) OVER (PARTITION BY wahljahr, ags
                                        ORDER BY rile, partei
                                        ROWS UNBOUNDED PRECEDING)
              / nullif(abdeckung, 0))::numeric, 4)
           AS anteil_kumuliert
FROM erfasst;
CREATE UNIQUE INDEX gemeinde_score_kurve_pk
    ON {DB_SCHEMA}.gemeinde_score_kurve (wahljahr, ags, partei);
CREATE INDEX gemeinde_score_kurve_ags
    ON {DB_SCHEMA}.gemeinde_score_kurve (ags, wahljahr);

CREATE MATERIALIZED VIEW {DB_SCHEMA}.gemeinde_score_profil AS
WITH basis AS (
    SELECT wahljahr, ags,
           round((100.0 * max(abdeckung))::numeric, 2)        AS abdeckung,
           round(sum(anteil_normiert) FILTER (WHERE rile < 0), 2)
                                                              AS anteil_links,
           round(sum(anteil_normiert) FILTER (WHERE rile >= 0), 2)
                                                              AS anteil_rechts,


           (array_agg(rile ORDER BY rile, partei)
            FILTER (WHERE anteil_kumuliert >= 50))[1]         AS median_rile,
           (array_agg(manifesto_partei ORDER BY rile, partei)
            FILTER (WHERE anteil_kumuliert >= 50))[1]         AS median_partei,

           (array_agg(manifesto_partei ORDER BY anteil DESC))[1]
                                                              AS staerkste_partei,
           (array_agg(rile ORDER BY anteil DESC))[1]          AS staerkste_rile
    FROM {DB_SCHEMA}.gemeinde_score_kurve
    GROUP BY 1, 2
)
SELECT b.*, e.gemeindename, e.land, g.geom
FROM basis b
JOIN {GERDA_SCHEMA}.gemeinde_harm21 e
  ON e.ags = b.ags AND e.wahljahr = b.wahljahr
LEFT JOIN raum.gemeindestand g
  ON g.ags = b.ags AND g.stichtag = DATE '{GEOM_STICHTAG}';
CREATE UNIQUE INDEX gemeinde_score_profil_pk
    ON {DB_SCHEMA}.gemeinde_score_profil (wahljahr, ags);
CREATE INDEX gemeinde_score_profil_geom
    ON {DB_SCHEMA}.gemeinde_score_profil USING GIST (geom);
"""


def pruefe():
    log.info("--- Umfang ---")
    for z in query(f"""
        SELECT (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_score_kurve),
               (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_score_profil),
               (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_score_profil
                 WHERE geom IS NULL);
    """):
        log.info("  Kurve %s Zeilen, Profil %s Zeilen, davon ohne Geometrie %s",
                 *z)

    log.info("--- Kumuliert die Kurve je Gemeinde auf 100 Prozent? ---")
    for z in query(f"""
        SELECT count(*), round(min(m), 2), round(max(m), 2)
        FROM (SELECT wahljahr, ags, max(anteil_kumuliert) AS m
              FROM {DB_SCHEMA}.gemeinde_score_kurve GROUP BY 1, 2) x;
    """):
        log.info("  %s Gemeinde-Wahl-Paare, Endwert zwischen %s und %s", *z)

    log.info("--- Anteil links von rile 0, je Wahl (Mittel ueber Gemeinden) ---")
    for z in query(f"""
        SELECT wahljahr, count(*),
               round(avg(anteil_links), 2), round(min(anteil_links), 2),
               round(max(anteil_links), 2), round(avg(abdeckung), 2)
        FROM {DB_SCHEMA}.gemeinde_score_profil
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden, links im Mittel %s %% (von %s bis %s), " "Abdeckung %s %%", *z)

    log.info("--- Beispiel: die Kurve fuer Koeln 2021 ---")
    for z in query(f"""
        SELECT manifesto_partei, rile, round(anteil_normiert, 2),
               round(anteil_kumuliert, 2)
        FROM {DB_SCHEMA}.gemeinde_score_kurve
        WHERE ags = '05315000' AND wahljahr = 2021
        ORDER BY rile;
    """):
        log.info("  %-10s rile %8s  Anteil %6s %%  kumuliert %6s %%", *z)

    log.info("--- Median-Score einer Gemeinde ueber die Zeit: Koeln ---")
    for z in query(f"""
        SELECT wahljahr, median_partei, median_rile,
               staerkste_partei, round(anteil_links, 1)
        FROM {DB_SCHEMA}.gemeinde_score_profil
        WHERE ags = '05315000' ORDER BY wahljahr;
    """):
        log.info("  %s: Median bei %-10s rile %8s | staerkste %-10s | " "links %s %%", *z)


def main():
    run_sql(DDL, "sichten score je gemeinde")
    pruefe()


if __name__ == "__main__":
    main()
