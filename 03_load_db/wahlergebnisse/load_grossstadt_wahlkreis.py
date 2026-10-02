import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA   = "wahlergebnisse"
RAUM_SCHEMA = "raum"
META_SCHEMA = "meta"
T_EINHEIT  = "kleinst_100_geteilt"
T_ERG      = "kleinst_100_geteilt_ergebnis"
T_KENNZAHL = "kleinst_100_geteilt_kennzahl"

JAHRE = [2013, 2017, 2021]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grossstadt")


LIEFERUNG = f"""
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
"""


def merke_lieferung(jahr):
    run_sql(f"""
    INSERT INTO {META_SCHEMA}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, lizenz, wahljahr, art, basis)
    VALUES ('grossstadt_wkr_{jahr}',
            'Geteilte Gemeinden je Wahlkreis {jahr}',
            'eigene Ableitung (kein Herausgeber)',
            'dl-de/by-2-0 (Basis Bundeswahlleiterin)', {jahr}, 'abgeleitet',
            ARRAY['bwl_wahlbezirke_{jahr}']::text[])
    ON CONFLICT (lieferung_id) DO UPDATE SET
        bezeichnung = EXCLUDED.bezeichnung, basis = EXCLUDED.basis;
    """, f"lieferung grossstadt_wkr_{jahr}")


SQL = f"""
DROP TABLE IF EXISTS {DB_SCHEMA}.{T_ERG}      CASCADE;
DROP TABLE IF EXISTS {DB_SCHEMA}.{T_KENNZAHL} CASCADE;
DROP TABLE IF EXISTS {RAUM_SCHEMA}.{T_EINHEIT} CASCADE;

CREATE TABLE {RAUM_SCHEMA}.{T_EINHEIT} AS
WITH bezirk AS (

    SELECT w.*,
           raum.gemeinde_ags(w.ags) AS gem_ags
    FROM {DB_SCHEMA}.wahlbezirk w
),
geteilt AS (
    SELECT wahljahr, gem_ags, wkr_nr,
           row_number() OVER (PARTITION BY wahljahr, gem_ags
                              ORDER BY wkr_nr)                  AS teilnummer,
           count(*)    OVER (PARTITION BY wahljahr, gem_ags)    AS teile
    FROM (SELECT DISTINCT wahljahr, gem_ags, wkr_nr FROM bezirk) d
),
stadt AS (





    SELECT * FROM geteilt
    WHERE teile > 1 AND NOT raum.ist_sammelposten(gem_ags)
),
flaeche AS (
    SELECT DISTINCT s.wahljahr, s.gem_ags, g.geom, g.gen
    FROM stadt s
    JOIN zeit.stichtag zt
      ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || s.wahljahr::text
    JOIN raum.gemeindestand_stichtag g
      ON g.stichtag = zt.datum AND g.ags = s.gem_ags
),
messer AS (
    SELECT f.wahljahr, f.gem_ags, f.geom,
           ST_Union(ST_Boundary(w.geom)) AS linie
    FROM flaeche f
    JOIN stadt s ON (s.wahljahr, s.gem_ags) = (f.wahljahr, f.gem_ags)
    JOIN raum.wahlkreis w
      ON (w.wahljahr, w.wkr_nr) = (s.wahljahr, s.wkr_nr)
    GROUP BY f.wahljahr, f.gem_ags, f.geom
),
stueck AS (
    SELECT m.wahljahr, m.gem_ags,
           (ST_Dump(ST_Split(m.geom, m.linie))).geom AS teilstueck
    FROM messer m
),
zerlegt AS (
    SELECT st.wahljahr, st.gem_ags, w.wkr_nr,
           ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(st.teilstueck)), 3))
               ::geometry(MultiPolygon, 25832) AS geom
    FROM stueck st
    CROSS JOIN LATERAL (
        SELECT s2.wkr_nr
        FROM stadt s2
        JOIN raum.wahlkreis w2
          ON (w2.wahljahr, w2.wkr_nr) = (s2.wahljahr, s2.wkr_nr)
        WHERE (s2.wahljahr, s2.gem_ags) = (st.wahljahr, st.gem_ags)
        ORDER BY ST_Area(ST_Intersection(w2.geom, st.teilstueck)) DESC,
                 ST_Distance(w2.geom, st.teilstueck)
        LIMIT 1) w
    GROUP BY st.wahljahr, st.gem_ags, w.wkr_nr
)
SELECT b.gem_ags || '-' || lpad(s.teilnummer::text, 2, '0')   AS einheit_id,
       b.wahljahr, b.gem_ags AS ags, s.teilnummer, b.wkr_nr,
       max(w.wkr_name)                                        AS wkr_name,


       CASE left(b.gem_ags, 2) WHEN '11' THEN 'Berlin, Stadt'
                               WHEN '02' THEN 'Hamburg, Freie und Hansestadt'
                               ELSE coalesce(max(fl.gen),
                                             max(b.gemeindename)) END AS gemeindename,
       s.teile                                                AS teile_gesamt,
       'grossstadt_wkr_' || b.wahljahr                        AS lieferung_id,
       ST_Area(z.geom) / 1e6                                  AS flaeche_km2,
       z.geom
FROM bezirk b
JOIN stadt s
  ON (s.wahljahr, s.gem_ags, s.wkr_nr) = (b.wahljahr, b.gem_ags, b.wkr_nr)
JOIN raum.wahlkreis w ON (w.wahljahr, w.wkr_nr) = (b.wahljahr, b.wkr_nr)
LEFT JOIN zerlegt z
  ON (z.wahljahr, z.gem_ags, z.wkr_nr) = (b.wahljahr, b.gem_ags, b.wkr_nr)
LEFT JOIN flaeche fl
  ON (fl.wahljahr, fl.gem_ags) = (b.wahljahr, b.gem_ags)
GROUP BY b.wahljahr, b.gem_ags, b.wkr_nr, s.teilnummer, s.teile, z.geom;

ALTER TABLE {RAUM_SCHEMA}.{T_EINHEIT} ADD PRIMARY KEY (wahljahr, einheit_id);
CREATE INDEX {T_EINHEIT}_gix ON {RAUM_SCHEMA}.{T_EINHEIT} USING GIST (geom);
CREATE INDEX {T_EINHEIT}_ags ON {RAUM_SCHEMA}.{T_EINHEIT} (wahljahr, ags);

CREATE TABLE {DB_SCHEMA}.{T_KENNZAHL} AS
WITH bezirk AS (
    SELECT w.*,
           raum.gemeinde_ags(w.ags) AS gem_ags
    FROM {DB_SCHEMA}.wahlbezirk w
),
summe AS (
    SELECT e.wahljahr, e.einheit_id,
           count(*)                                   AS bezirke,







           count(*) FILTER (WHERE b.bezirksart = '0') AS urnenbezirke,
           count(*) FILTER (WHERE b.bezirksart = '5') AS briefbezirke,
           count(*) FILTER (WHERE b.abgebend)         AS abgebende_bezirke,
           sum(b.wahlberechtigte)                     AS wahlberechtigte,
           sum(b.waehlende)                           AS waehlende,
           sum(b.waehlende_wahlschein)                AS waehlende_wahlschein,
           sum(b.gueltig_erst)                        AS gueltig_erst,
           sum(b.gueltig_zweit)                       AS gueltig_zweit,
           sum(b.ungueltig_erst)                      AS ungueltig_erst,
           sum(b.ungueltig_zweit)                     AS ungueltig_zweit
    FROM {RAUM_SCHEMA}.{T_EINHEIT} e
    JOIN bezirk b ON (b.wahljahr, b.gem_ags, b.wkr_nr)
                   = (e.wahljahr, e.ags, e.wkr_nr)
    GROUP BY 1, 2
)
SELECT s.wahljahr, s.einheit_id, m.merkmal, m.wert,
       'grossstadt_wkr_' || s.wahljahr AS lieferung_id
FROM summe s
CROSS JOIN LATERAL (VALUES
    ('bezirke',              s.bezirke),
    ('urnenbezirke',         s.urnenbezirke),
    ('briefbezirke',         s.briefbezirke),
    ('abgebende_bezirke',    s.abgebende_bezirke),
    ('wahlberechtigte',      s.wahlberechtigte),
    ('waehlende',            s.waehlende),
    ('waehlende_wahlschein', s.waehlende_wahlschein),
    ('gueltig_erst',         s.gueltig_erst),
    ('gueltig_zweit',        s.gueltig_zweit),
    ('ungueltig_erst',       s.ungueltig_erst),
    ('ungueltig_zweit',      s.ungueltig_zweit)
) AS m(merkmal, wert)
WHERE m.wert IS NOT NULL;

ALTER TABLE {DB_SCHEMA}.{T_KENNZAHL} ADD PRIMARY KEY (wahljahr, einheit_id, merkmal);
CREATE INDEX {T_KENNZAHL}_merkmal
    ON {DB_SCHEMA}.{T_KENNZAHL} (wahljahr, merkmal);

CREATE TABLE {DB_SCHEMA}.{T_ERG} AS
SELECT e.wahljahr, e.einheit_id, e.ags, e.wkr_nr,
       r.stimme, r.partei, sum(r.stimmen) AS stimmen
FROM {DB_SCHEMA}.wahlbezirksergebnis r
JOIN {RAUM_SCHEMA}.{T_EINHEIT} e
  ON e.wahljahr = r.wahljahr AND e.wkr_nr = r.wkr_nr
 AND e.ags = raum.gemeinde_ags(r.ags)
GROUP BY 1, 2, 3, 4, 5, 6;

ALTER TABLE {DB_SCHEMA}.{T_ERG} ADD PRIMARY KEY (wahljahr, einheit_id, stimme, partei);
"""


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, T_EINHEIT)
    log.info("%-6s %10s %10s %14s", "Jahr", "Einheiten", "Gemeinden", "Wahlberecht.")
    for zeile in query(f"""
        SELECT e.wahljahr, count(*), count(DISTINCT e.ags),
               to_char(sum(k.wert), 'FM999G999G999')
        FROM {RAUM_SCHEMA}.{T_EINHEIT} e
        LEFT JOIN {DB_SCHEMA}.{T_KENNZAHL} k
          ON (k.wahljahr, k.einheit_id) = (e.wahljahr, e.einheit_id)
         AND k.merkmal = 'wahlberechtigte'
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("%-6s %10s %10s %14s", *zeile)

    log.info("--- Teile je Gemeinde ---")
    for zeile in query(f"""
        SELECT wahljahr, ags, max(gemeindename), count(*),
               string_agg(teilnummer || '->WK' || wkr_nr, ', ' ORDER BY teilnummer)
        FROM {RAUM_SCHEMA}.{T_EINHEIT}
        GROUP BY wahljahr, ags ORDER BY 1, 4 DESC, 2;
    """):
        log.info("  %s %s %-26s %s: %s", *zeile)

    log.info("--- Flaeche: ergeben die Teile die Gemeinde? ---")
    zeilen = query(f"""
        SELECT e.wahljahr, e.ags, round(sum(e.flaeche_km2)::numeric, 2),
               round(max(ST_Area(s.geom) / 1e6)::numeric, 2)
        FROM {RAUM_SCHEMA}.{T_EINHEIT} e
        JOIN zeit.stichtag zt
          ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || e.wahljahr::text
        JOIN raum.gemeindestand_stichtag s
          ON s.stichtag = zt.datum AND s.ags = e.ags
        GROUP BY e.wahljahr, e.ags
        HAVING abs(sum(e.flaeche_km2) - max(ST_Area(s.geom) / 1e6)) > 0.5
        ORDER BY 1, 2;
    """)
    if not zeilen:
        log.info("  alle vollstaendig (Abweichung < 0,5 km2)")
    for jahr, ags, teile, gesamt in zeilen:
        log.warning("  %s %s: Teile %s km2, Gemeinde %s km2", jahr, ags, teile, gesamt)

    log.info("--- Gegenprobe: Anteile ergeben das Wahlkreisergebnis? ---")
    for zeile in query(f"""
        SELECT g.wahljahr, g.stimme, count(*) AS wahlkreise,
               count(*) FILTER (WHERE g.summe <> w.summe) AS abweichend
        FROM (SELECT wahljahr, wkr_nr, stimme, sum(stimmen) AS summe
              FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1, 2, 3) g
        JOIN (SELECT wahljahr, wkr_nr, stimme, sum(stimmen) AS summe
              FROM {DB_SCHEMA}.wahlbezirksergebnis GROUP BY 1, 2, 3) w
          USING (wahljahr, wkr_nr, stimme)
        GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  %s %s: %s Wahlkreise, davon abweichend %s " "(Abweichung erwartet, wo Fremdgemeinden im Wahlkreis liegen)", *zeile)


def main():
    if "--neu" in sys.argv[1:]:


        for s, t in ((DB_SCHEMA, T_ERG), (DB_SCHEMA, T_KENNZAHL),
                     (RAUM_SCHEMA, T_EINHEIT)):
            run_sql(f"DROP TABLE IF EXISTS {s}.{t} CASCADE;",
                    f"drop {t}")
        log.warning("Sichten verworfen.")

    run_sql(LIEFERUNG, "lieferung-ddl")
    for jahr in JAHRE:
        merke_lieferung(jahr)
    run_sql(SQL, "kleinst_100_geteilt")
    report()


if __name__ == "__main__":
    main()
