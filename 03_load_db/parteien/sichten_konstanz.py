import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "parteien"
GERDA_SCHEMA = "gerda_seit_1990"
CROSSWALK = "roh_crosswalk.ags_crosswalk"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("konstanz")


DDL = f"""
DROP MATERIALIZED VIEW IF EXISTS {DB_SCHEMA}.gemeinde_konstanz      CASCADE;
DROP MATERIALIZED VIEW IF EXISTS {DB_SCHEMA}.gemeinde_konstanz_paar CASCADE;

CREATE MATERIALIZED VIEW {DB_SCHEMA}.gemeinde_konstanz_paar AS
WITH paare AS (
    SELECT wahljahr AS von,
           lead(wahljahr) OVER (ORDER BY wahljahr) AS bis
    FROM (SELECT DISTINCT wahljahr FROM {GERDA_SCHEMA}.gemeinde_harm21) j
),
p AS (SELECT von, bis FROM paare WHERE bis IS NOT NULL),

ped AS (
    SELECT von, bis, ags,


           round((50.0 * sum(abs(a_von - a_bis)))::numeric, 4) AS pedersen
    FROM (
        SELECT p.von, p.bis, e.ags, e.partei,
               coalesce(sum(e.anteil) FILTER (WHERE e.wahljahr = p.von), 0) AS a_von,
               coalesce(sum(e.anteil) FILTER (WHERE e.wahljahr = p.bis), 0) AS a_bis
        FROM p
        JOIN {GERDA_SCHEMA}.gemeinde_harm21_ergebnis e
          ON e.wahljahr IN (p.von, p.bis)
        GROUP BY 1, 2, 3, 4
    ) t
    GROUP BY 1, 2, 3
),

schritte AS (
    SELECT p.von, p.bis, k.ags, k.rile, k.wahljahr, k.anteil_normiert
    FROM p
    JOIN {DB_SCHEMA}.gemeinde_score_kurve k ON k.wahljahr IN (p.von, p.bis)
),
kumuliert AS (
    SELECT von, bis, ags, rile,
           coalesce(sum(anteil_normiert) FILTER (WHERE wahljahr = von)
                    OVER w, 0) AS f_von,
           coalesce(sum(anteil_normiert) FILTER (WHERE wahljahr = bis)
                    OVER w, 0) AS f_bis,
           lead(rile) OVER (PARTITION BY von, bis, ags ORDER BY rile)
             - rile      AS breite
    FROM schritte
    WINDOW w AS (PARTITION BY von, bis, ags ORDER BY rile
                 ROWS UNBOUNDED PRECEDING)
),
wass AS (
    SELECT von, bis, ags,
           round((sum(abs(f_von - f_bis) * breite) / 100.0)::numeric, 4)
               AS achsenverschiebung
    FROM kumuliert
    WHERE breite IS NOT NULL
    GROUP BY 1, 2, 3
),

harm AS (
    SELECT ags_21 AS ags, year::int AS wahljahr,
           count(*)                                        AS quellen,
           count(*) FILTER (WHERE pop_cw::double precision < 1)
                                                           AS quellen_geteilt
    FROM {CROSSWALK}
    WHERE pop_cw ~ '^[0-9.]+$'
    GROUP BY 1, 2
)
SELECT ped.von                       AS wahljahr_von,
       ped.bis                       AS wahljahr_bis,
       ped.ags,
       ped.pedersen,
       w.achsenverschiebung,
       round((pb.median_rile - pv.median_rile)::numeric, 3)
                                     AS delta_median_rile,
       pv.median_partei              AS median_partei_von,
       pb.median_partei              AS median_partei_bis,
       pv.staerkste_partei           AS staerkste_von,
       pb.staerkste_partei           AS staerkste_bis,
       pv.abdeckung                  AS abdeckung_von,
       pb.abdeckung                  AS abdeckung_bis,

       coalesce(hv.quellen_geteilt, 0) AS quellen_geteilt_von,
       coalesce(hb.quellen_geteilt, 0) AS quellen_geteilt_bis,

       round((100.0 * percent_rank() OVER (PARTITION BY ped.von, ped.bis
                                           ORDER BY ped.pedersen))::numeric, 1)
                                     AS pedersen_perzentil,
       round((100.0 * percent_rank() OVER (PARTITION BY ped.von, ped.bis
                                           ORDER BY w.achsenverschiebung))::numeric, 1)
                                     AS achse_perzentil
FROM ped
JOIN wass w   ON w.von = ped.von AND w.bis = ped.bis AND w.ags = ped.ags
JOIN {DB_SCHEMA}.gemeinde_score_profil pv
              ON pv.ags = ped.ags AND pv.wahljahr = ped.von
JOIN {DB_SCHEMA}.gemeinde_score_profil pb
              ON pb.ags = ped.ags AND pb.wahljahr = ped.bis
LEFT JOIN harm hv ON hv.ags = ped.ags AND hv.wahljahr = ped.von
LEFT JOIN harm hb ON hb.ags = ped.ags AND hb.wahljahr = ped.bis;

CREATE UNIQUE INDEX gemeinde_konstanz_paar_pk
    ON {DB_SCHEMA}.gemeinde_konstanz_paar (wahljahr_von, wahljahr_bis, ags);

CREATE MATERIALIZED VIEW {DB_SCHEMA}.gemeinde_konstanz AS
WITH agg AS (
SELECT k.ags,
       max(p.gemeindename)                          AS gemeindename,
       max(p.land)                                  AS land,
       count(*)                                     AS n_paare,
       round(avg(k.pedersen), 3)                    AS pedersen_mittel,
       round(avg(k.achsenverschiebung), 3)          AS achse_mittel,
       round(avg(k.pedersen_perzentil), 1)          AS pedersen_perzentil_mittel,
       round(avg(k.achse_perzentil), 1)             AS achse_perzentil_mittel,

       round(stddev_samp(p.median_rile)::numeric, 3) AS median_rile_streuung,
       round(min(p.median_rile)::numeric, 3)         AS median_rile_min,
       round(max(p.median_rile)::numeric, 3)         AS median_rile_max,
       round(min(k.abdeckung_von), 2)                AS abdeckung_min,
       sum(k.quellen_geteilt_von)                    AS quellen_geteilt_gesamt
FROM {DB_SCHEMA}.gemeinde_konstanz_paar k
JOIN {DB_SCHEMA}.gemeinde_score_profil p
     ON p.ags = k.ags AND p.wahljahr = k.wahljahr_von
GROUP BY 1
)
SELECT a.*, g.geom
FROM agg a
LEFT JOIN raum.gemeindestand g
     ON g.ags = a.ags AND g.stichtag = DATE '2021-12-31';

CREATE UNIQUE INDEX gemeinde_konstanz_pk ON {DB_SCHEMA}.gemeinde_konstanz (ags);
CREATE INDEX gemeinde_konstanz_geom ON {DB_SCHEMA}.gemeinde_konstanz USING GIST (geom);
"""


def pruefe():
    log.info("--- Umfang ---")
    for z in query(f"""
        SELECT (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_konstanz_paar),
               (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_konstanz),
               (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_konstanz WHERE geom IS NULL);
    """):
        log.info("  %s Paarzeilen, %s Gemeinden, ohne Geometrie %s", *z)

    log.info("--- Je Wahlpaar: wieviel wechselte, wieviel wanderte? ---")
    for z in query(f"""
        SELECT wahljahr_von, wahljahr_bis, count(*),
               round(avg(pedersen), 2), round(avg(achsenverschiebung), 2),
               round(avg(abdeckung_bis), 1)
        FROM {DB_SCHEMA}.gemeinde_konstanz_paar
        GROUP BY 1, 2 ORDER BY 1;
    """):
        log.info("  %s->%s: %s Gemeinden | Pedersen %s %% | Achse %s Punkte " "| Abdeckung %s %%", *z)

    log.info("--- Wieviele Gemeinden sind exakt aufsummiert statt geteilt? ---")
    for z in query(f"""
        SELECT count(*) FILTER (WHERE quellen_geteilt_gesamt = 0), count(*)
        FROM {DB_SCHEMA}.gemeinde_konstanz;
    """):
        log.info("  %s von %s Gemeinden ohne einen einzigen geteilten " "Quellwert - dort ist die Konstanz keine Folge der " "Umrechnung", *z)

    log.info("--- Die vier Felder, Paar 1998->2002 (Median als Trenner) ---")
    for z in query(f"""
        WITH m AS (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY pedersen) AS mp,
                          percentile_cont(0.5) WITHIN GROUP (ORDER BY achsenverschiebung) AS ma
                   FROM {DB_SCHEMA}.gemeinde_konstanz_paar
                   WHERE wahljahr_von = 1998)
        SELECT CASE WHEN pedersen >= mp THEN 'Partei wechselt' ELSE 'Partei bleibt' END,
               CASE WHEN achsenverschiebung >= ma THEN 'Achse wandert' ELSE 'Achse bleibt' END,
               count(*)
        FROM {DB_SCHEMA}.gemeinde_konstanz_paar, m
        WHERE wahljahr_von = 1998
        GROUP BY 1, 2 ORDER BY 3 DESC;
    """):
        log.info("  %-16s + %-14s %s Gemeinden", *z)

    log.info("--- Koeln ueber die Paare ---")
    for z in query(f"""
        SELECT wahljahr_von, wahljahr_bis, pedersen, achsenverschiebung,
               delta_median_rile, staerkste_von, staerkste_bis
        FROM {DB_SCHEMA}.gemeinde_konstanz_paar
        WHERE ags = '05315000' ORDER BY wahljahr_von;
    """):
        log.info("  %s->%s Pedersen %6s | Achse %6s | dMedian %7s | %s -> %s",
                 *z)


def main():
    run_sql(DDL, "sichten konstanz")
    pruefe()


if __name__ == "__main__":
    main()
