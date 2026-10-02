import sys
import time
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA  = "raum"
ERG_SCHEMA = "wahlergebnisse"
T_GEM_KRS  = "gemeinde_kreis"
T_KRS_WKR  = "kreis_wahlkreis"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kreis-zuordnung")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_GEM_KRS} (
    wahljahr     SMALLINT NOT NULL,
    ags          CHAR(8)  NOT NULL,
    gemeindename TEXT,
    kreis        CHAR(5)  NOT NULL,
    kreisname    TEXT,
    kreisart     TEXT,
    stichtag     DATE     NOT NULL,
    hat_wahlbezirk BOOLEAN,
    PRIMARY KEY (wahljahr, ags)
);

CREATE INDEX IF NOT EXISTS {T_GEM_KRS}_kreis_idx
    ON {DB_SCHEMA}.{T_GEM_KRS} (wahljahr, kreis);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_KRS_WKR} (
    wahljahr        SMALLINT NOT NULL,
    kreis           CHAR(5)  NOT NULL,
    kreisname       TEXT,
    kreisart        TEXT,
    wkr_nr          SMALLINT NOT NULL,
    wkr_name        TEXT,
    gemeinden       INTEGER,
    wahlberechtigte INTEGER,
    kreis_teile     INTEGER,
    wkr_teile       INTEGER,
    flaeche_km2     DOUBLE PRECISION,
    geom            geometry(MultiPolygon, 25832),
    PRIMARY KEY (wahljahr, kreis, wkr_nr)
);

CREATE INDEX IF NOT EXISTS {T_KRS_WKR}_gix
    ON {DB_SCHEMA}.{T_KRS_WKR} USING GIST (geom);

CREATE INDEX IF NOT EXISTS {T_KRS_WKR}_wkr_idx
    ON {DB_SCHEMA}.{T_KRS_WKR} (wahljahr, wkr_nr);
"""


SQL_VORBEREITUNG = f"""
TRUNCATE {DB_SCHEMA}.{T_GEM_KRS};
TRUNCATE {DB_SCHEMA}.{T_KRS_WKR};

DROP TABLE IF EXISTS {DB_SCHEMA}.arbeit_gem;
CREATE UNLOGGED TABLE {DB_SCHEMA}.arbeit_gem AS
SELECT b.wahljahr, b.gem_ags AS ags, b.wkr_nr,
       max(b.gemeindename)     AS gemeindename,
       sum(b.wahlberechtigte)  AS wahlberechtigte
FROM (SELECT w.*,
             raum.gemeinde_ags(w.ags) AS gem_ags
      FROM {ERG_SCHEMA}.wahlbezirk w) b
WHERE NOT raum.ist_sammelposten(b.gem_ags)
GROUP BY 1, 2, 3;

"""

SQL_GEMEINDE_KREIS = f"""
INSERT INTO {DB_SCHEMA}.{T_GEM_KRS}
    (wahljahr, ags, gemeindename, kreis, kreisname, kreisart, stichtag,
     hat_wahlbezirk)
SELECT zt.wahljahr, s.ags, s.gen,
       left(s.ags, 5), k.gen, k.bez, zt.datum,
       EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
               WHERE w.wahljahr = zt.wahljahr
                 AND raum.gemeinde_ags(w.ags) = s.ags)
FROM (SELECT substring(bezug from '[0-9]+')::smallint AS wahljahr, datum
      FROM zeit.stichtag WHERE art = 'wahltag') zt
JOIN {DB_SCHEMA}.gemeindestand_stichtag s ON s.stichtag = zt.datum
LEFT JOIN {DB_SCHEMA}.kreisstand_stichtag k
  ON k.stichtag = zt.datum AND k.ags = left(s.ags, 5)
WHERE s.bez <> 'Gemeindefreies Gebiet'
   OR EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
              WHERE w.wahljahr = zt.wahljahr
                AND raum.gemeinde_ags(w.ags) = s.ags);

"""

SQL_KREIS_WAHLKREIS = f"""
INSERT INTO {DB_SCHEMA}.{T_KRS_WKR}
    (wahljahr, kreis, kreisname, kreisart, wkr_nr, wkr_name,
     gemeinden, wahlberechtigte, kreis_teile, wkr_teile, flaeche_km2, geom)
WITH
gemeindeflaeche AS (

    SELECT g.wahljahr, left(g.ags, 5) AS kreis, g.wkr_nr, s.geom
    FROM (SELECT DISTINCT wahljahr, ags, wkr_nr FROM {DB_SCHEMA}.arbeit_gem) g
    JOIN zeit.stichtag zt
      ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || g.wahljahr::text
    JOIN {DB_SCHEMA}.gemeindestand_stichtag s
      ON s.stichtag = zt.datum AND s.ags = g.ags
    WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.kleinst_100_geteilt t
                      WHERE (t.wahljahr, t.ags) = (g.wahljahr, g.ags))
    UNION ALL

    SELECT t.wahljahr, left(t.ags, 5), t.wkr_nr, t.geom
    FROM {DB_SCHEMA}.kleinst_100_geteilt t
),
kreisteil_flaeche AS (
    SELECT wahljahr, kreis, wkr_nr,
           ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(geom)), 3))
               ::geometry(MultiPolygon, 25832) AS geom
    FROM gemeindeflaeche GROUP BY 1, 2, 3
),
schnitt AS (
    SELECT g.wahljahr, left(g.ags, 5) AS kreis, g.wkr_nr,
           count(*)                  AS gemeinden,
           sum(g.wahlberechtigte)    AS wahlberechtigte
    FROM {DB_SCHEMA}.arbeit_gem g GROUP BY 1, 2, 3
)
SELECT s.wahljahr, s.kreis, max(k.gen), max(k.bez), s.wkr_nr, max(w.wkr_name),
       s.gemeinden, s.wahlberechtigte,
       count(*) OVER (PARTITION BY s.wahljahr, s.kreis)  AS kreis_teile,
       count(*) OVER (PARTITION BY s.wahljahr, s.wkr_nr) AS wkr_teile,
       ST_Area(f.geom) / 1e6                             AS flaeche_km2,
       f.geom
FROM schnitt s
LEFT JOIN kreisteil_flaeche f
       ON (f.wahljahr, f.kreis, f.wkr_nr) = (s.wahljahr, s.kreis, s.wkr_nr)
JOIN zeit.stichtag zt
  ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || s.wahljahr::text
LEFT JOIN {DB_SCHEMA}.kreisstand_stichtag k
  ON k.stichtag = zt.datum AND k.ags = s.kreis
LEFT JOIN {DB_SCHEMA}.wahlkreis w
  ON (w.wahljahr, w.wkr_nr) = (s.wahljahr, s.wkr_nr)
GROUP BY s.wahljahr, s.kreis, s.wkr_nr, s.gemeinden, s.wahlberechtigte, f.geom;

"""

SQL_AUFRAEUMEN = f"""
DROP TABLE {DB_SCHEMA}.arbeit_gem;
"""


BLOECKE = [
    ("Arbeitstabelle aus den Wahlbezirken", SQL_VORBEREITUNG),
    ("Gemeinde -> Kreis",                   SQL_GEMEINDE_KREIS),
    ("Kreis -> Wahlkreis (mit Flaeche)",    SQL_KREIS_WAHLKREIS),
    ("Arbeitstabelle verwerfen",            SQL_AUFRAEUMEN),
]


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, T_GEM_KRS)
    for zeile in query(f"""
        SELECT wahljahr, count(*) AS gemeinden, count(DISTINCT kreis) AS kreise,
               count(*) FILTER (WHERE kreisname IS NULL) AS ohne_kreisname
        FROM {DB_SCHEMA}.{T_GEM_KRS} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden in %s Kreisen, ohne Kreisnamen %s", *zeile)

    log.info("--- %s.%s ---", DB_SCHEMA, T_KRS_WKR)
    for zeile in query(f"""
        SELECT wahljahr, count(*) AS paare,
               count(DISTINCT kreis) AS kreise, count(DISTINCT wkr_nr) AS wahlkreise
        FROM {DB_SCHEMA}.{T_KRS_WKR} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Paare, %s Kreise, %s Wahlkreise", *zeile)

    log.info("--- Wie oft ist es wirklich n:m? ---")
    for zeile in query(f"""
        SELECT wahljahr,
               count(DISTINCT kreis)  FILTER (WHERE kreis_teile > 1) AS kreise_in_mehreren_wkr,
               count(DISTINCT wkr_nr) FILTER (WHERE wkr_teile  > 1) AS wkr_aus_mehreren_kreisen,
               count(DISTINCT kreis)  FILTER (WHERE kreis_teile = 1
                                          AND wkr_teile  = 1)       AS eins_zu_eins
        FROM {DB_SCHEMA}.{T_KRS_WKR} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Kreise in mehreren WK, %s WK aus mehreren Kreisen, " "%s genau 1:1", *zeile)

    log.info("--- Die groessten Kreise nach Zahl der Wahlkreise (2021) ---")
    for zeile in query(f"""
        SELECT kreis, max(kreisname), max(kreisart), count(*) AS wahlkreise,
               to_char(sum(wahlberechtigte), 'FM999G999G999') AS wahlberechtigte
        FROM {DB_SCHEMA}.{T_KRS_WKR} WHERE wahljahr = 2021
        GROUP BY 1 ORDER BY 4 DESC, 1 LIMIT 8;
    """):
        log.info("  %s %-26s %-18s %2s WK, %s Wahlberechtigte", *zeile)

    log.info("--- Flaeche: ergeben die Kreisteile wieder den ganzen Kreis? ---")
    for zeile in query(f"""
        SELECT t.wahljahr, count(*) AS geteilte_kreise,
               count(*) FILTER (WHERE abs(t.summe - k.flaeche_km2) < 0.5) AS stimmig,
               round(max(abs(t.summe - k.flaeche_km2))::numeric, 2) AS max_abweichung_km2
        FROM (SELECT wahljahr, kreis, sum(flaeche_km2) AS summe
              FROM {DB_SCHEMA}.{T_KRS_WKR} WHERE kreis_teile > 1
              GROUP BY 1, 2) t
        JOIN zeit.stichtag zt
          ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || t.wahljahr::text
        JOIN {DB_SCHEMA}.kreisstand_stichtag k
          ON k.stichtag = zt.datum AND k.ags = t.kreis
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s geteilte Kreise, %s stimmig, groesste Abweichung %s km2",
                 *zeile)

    log.info("--- Kreisteile ohne Flaeche ---")
    for zeile in query(f"""
        SELECT wahljahr, count(*) FROM {DB_SCHEMA}.{T_KRS_WKR}
        WHERE geom IS NULL GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s", *zeile)

    log.info("--- Gegenprobe: Wahlberechtigte je Wahl vollstaendig? ---")
    for zeile in query(f"""
        SELECT k.wahljahr,
               to_char(k.summe, 'FM999G999G999') AS ueber_kreise,
               to_char(b.summe, 'FM999G999G999') AS ueber_wahlbezirke,
               k.summe - b.summe AS differenz
        FROM (SELECT wahljahr, sum(wahlberechtigte) AS summe
              FROM {DB_SCHEMA}.{T_KRS_WKR} GROUP BY 1) k
        JOIN (SELECT wahljahr, sum(wahlberechtigte) AS summe
              FROM {ERG_SCHEMA}.wahlbezirk
              WHERE NOT raum.ist_sammelposten(raum.gemeinde_ags(ags))
              GROUP BY 1) b USING (wahljahr)
        ORDER BY 1;
    """):
        log.info("  %s: %s ueber Kreise, %s ueber Wahlbezirke, Differenz %s",
                 *zeile)


def protokoll(pfad=None):
    pfad = pfad or (Path(__file__).resolve().parents[2] / "logs"
                    / "load_kreis_zuordnung.txt")
    pfad.parent.mkdir(exist_ok=True)
    h = logging.FileHandler(pfad, mode="w", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(h)
    log.info("Mitschrift: %s", pfad)
    return pfad


def main():
    protokoll()

    if "--neu" in sys.argv[1:]:
        for t in (T_GEM_KRS, T_KRS_WKR):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;",
                    f"{t} verwerfen")
        log.warning("Tabellen verworfen.")

    run_sql(DDL, "ddl")


    gesamt = time.time()
    for nr, (label, sql) in enumerate(BLOECKE, 1):
        log.info("[%d/%d] %s ...", nr, len(BLOECKE), label)
        t0 = time.time()
        run_sql(sql, label)
        log.info("[%d/%d] %s - fertig nach %.0f s", nr, len(BLOECKE), label,
                 time.time() - t0)
    log.info("Alle Bloecke durch, zusammen %.0f s", time.time() - gesamt)

    report()


if __name__ == "__main__":
    main()
