import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA  = "wahlergebnisse"
RAUM_SCHEMA = "raum"
T_EINHEIT = "kleinst_100_amtlich"
T_ERG     = "kleinst_100_amtlich_ergebnis"
T_KENNZAHL = "kleinst_100_amtlich_kennzahl"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemeindeebene")


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
    SELECT wahljahr, gem_ags
    FROM (SELECT DISTINCT wahljahr, gem_ags, wkr_nr FROM bezirk) d
    WHERE NOT raum.ist_sammelposten(gem_ags)
    GROUP BY 1, 2 HAVING count(*) > 1
),
zuordnung AS (
    SELECT b.*,
           (b.bwbez <> '00')                                      AS im_verbund,
           CASE WHEN b.bwbez = '00' THEN b.gem_ags
                ELSE 'V-' || b.kreis || '-' || b.bwbez
                     || '-' || lpad(b.wkr_nr::text, 3, '0') END   AS einheit_id
    FROM bezirk b
    WHERE NOT EXISTS (SELECT 1 FROM geteilt g
                      WHERE (g.wahljahr, g.gem_ags) = (b.wahljahr, b.gem_ags))
),
gemeindeflaeche AS (
    SELECT z.wahljahr, z.gem_ags, coalesce(r.geom, g.geom) AS geom, g.gen
    FROM (SELECT DISTINCT wahljahr, gem_ags FROM zuordnung
          WHERE NOT raum.ist_sammelposten(gem_ags)) z
    JOIN zeit.stichtag zt
      ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || z.wahljahr::text
    JOIN raum.gemeindestand_stichtag g
      ON g.stichtag = zt.datum AND g.ags = z.gem_ags
    LEFT JOIN raum.gemeindestand r
      ON z.wahljahr::text = '2013' AND z.gem_ags = '15085040'
     AND r.stichtag = DATE '2013-12-31' AND r.ags = '15085040'
),
flaeche AS (
    SELECT z.wahljahr, z.einheit_id,
           ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Union(f.geom)), 3))
               ::geometry(MultiPolygon, 25832)                  AS geom,




           (array_agg(f.gen ORDER BY z.wahlberechtigte DESC NULLS LAST,
                             f.gen))[1]                         AS gemeindename,
           string_agg(DISTINCT f.gen, '; ' ORDER BY f.gen)       AS mitglieder_namen,







           count(DISTINCT f.gem_ags)                            AS gemeinden
    FROM (SELECT wahljahr, einheit_id, gem_ags,
                 sum(wahlberechtigte) AS wahlberechtigte
          FROM zuordnung GROUP BY 1, 2, 3) z
    JOIN gemeindeflaeche f
      ON (f.wahljahr, f.gem_ags) = (z.wahljahr, z.gem_ags)
    GROUP BY z.wahljahr, z.einheit_id
)
SELECT z.einheit_id, z.wahljahr,
       CASE WHEN z.im_verbund THEN 'briefwahleinheit' ELSE 'gemeinde' END AS typ,
       max(z.wkr_nr)                                          AS wkr_nr,
       count(DISTINCT z.wkr_nr)                               AS wahlkreise,
       max(z.kreis)                                           AS kreis,
       coalesce(f.gemeinden, 0)                               AS gemeinden,
       coalesce(f.gemeindename,
                max(z.gemeindename) FILTER
                    (WHERE NOT raum.ist_sammelposten(z.gem_ags)))  AS gemeindename,
       f.mitglieder_namen                                     AS mitglieder_namen,
       'bwl_wahlbezirke_' || z.wahljahr                       AS lieferung_id,
       ST_Area(f.geom) / 1e6                                  AS flaeche_km2,
       f.geom
FROM zuordnung z
LEFT JOIN flaeche f ON (f.wahljahr, f.einheit_id) = (z.wahljahr, z.einheit_id)
GROUP BY z.wahljahr, z.einheit_id, z.im_verbund, f.geom,
         f.gemeindename, f.mitglieder_namen, f.gemeinden;

ALTER TABLE {RAUM_SCHEMA}.{T_EINHEIT} ADD PRIMARY KEY (wahljahr, einheit_id);
CREATE INDEX {T_EINHEIT}_gix ON {RAUM_SCHEMA}.{T_EINHEIT} USING GIST (geom);
CREATE INDEX {T_EINHEIT}_wkr ON {RAUM_SCHEMA}.{T_EINHEIT} (wahljahr, wkr_nr);
CREATE INDEX {T_EINHEIT}_typ ON {RAUM_SCHEMA}.{T_EINHEIT} (wahljahr, typ);

UPDATE {RAUM_SCHEMA}.{T_EINHEIT} e
SET geom       = ST_Multi(ST_CollectionExtract(ST_MakeValid(
                     coalesce(ST_Union(e.geom, z.geom), z.geom)),
                     3))::geometry(MultiPolygon, 25832),
    flaeche_km2 = ST_Area(coalesce(ST_Union(e.geom, z.geom), z.geom)) / 1e6,
    gemeinden   = e.gemeinden + z.n,
    mitglieder_namen = coalesce(e.mitglieder_namen || '; ', '') || z.namen
FROM (
    SELECT d.wahljahr, d.einheit_id,
           ST_Union(d.geom)                                   AS geom,
           count(*)                                           AS n,
           string_agg(d.gen, '; ' ORDER BY d.gen)              AS namen
    FROM (
        SELECT DISTINCT a.wahljahr, a.ags,


               CASE WHEN w.bwbez = '00' THEN w.ags
                    ELSE 'V-' || w.kreis || '-' || w.bwbez
                         || '-' || lpad(w.wkr_nr::text, 3, '0') END AS einheit_id,
               g.geom, g.gen
        FROM {RAUM_SCHEMA}.gemeinde_aufnahme a
        JOIN {DB_SCHEMA}.wahlbezirk w
          ON w.wahljahr = a.wahljahr AND w.ags = a.ags_aufnehmend
        JOIN zeit.stichtag zt
          ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || a.wahljahr::text
        JOIN {RAUM_SCHEMA}.gemeindestand_stichtag g
          ON g.stichtag = zt.datum AND g.ags = a.ags
        WHERE NOT a.eigener_bezirk
    ) d
    GROUP BY d.wahljahr, d.einheit_id
) z
WHERE (e.wahljahr, e.einheit_id) = (z.wahljahr, z.einheit_id);

CREATE TABLE {DB_SCHEMA}.{T_KENNZAHL} AS
WITH bezirk AS (
    SELECT w.*,
           raum.gemeinde_ags(w.ags) AS gem_ags
    FROM {DB_SCHEMA}.wahlbezirk w
),
geteilt AS (
    SELECT wahljahr, gem_ags
    FROM (SELECT DISTINCT wahljahr, gem_ags, wkr_nr FROM bezirk) d
    WHERE NOT raum.ist_sammelposten(gem_ags)
    GROUP BY 1, 2 HAVING count(*) > 1
),
zuordnung AS (
    SELECT b.*,
           CASE WHEN b.bwbez = '00' THEN b.gem_ags
                ELSE 'V-' || b.kreis || '-' || b.bwbez
                     || '-' || lpad(b.wkr_nr::text, 3, '0') END AS einheit_id
    FROM bezirk b
    WHERE NOT EXISTS (SELECT 1 FROM geteilt g
                      WHERE (g.wahljahr, g.gem_ags) = (b.wahljahr, b.gem_ags))
),
summe AS (
    SELECT z.wahljahr, z.einheit_id,
           count(*)                                   AS bezirke,
           count(*) FILTER (WHERE z.bezirksart = '0') AS urnenbezirke,
           count(*) FILTER (WHERE z.bezirksart = '5') AS briefbezirke,
           count(*) FILTER (WHERE z.abgebend)         AS abgebende_bezirke,
           sum(z.wahlberechtigte)                     AS wahlberechtigte,
           sum(z.waehlende)                           AS waehlende,
           sum(z.waehlende_wahlschein)                AS waehlende_wahlschein,
           sum(z.gueltig_erst)                        AS gueltig_erst,
           sum(z.gueltig_zweit)                       AS gueltig_zweit,
           sum(z.ungueltig_erst)                      AS ungueltig_erst,
           sum(z.ungueltig_zweit)                     AS ungueltig_zweit
    FROM zuordnung z GROUP BY 1, 2
)
SELECT s.wahljahr, s.einheit_id, m.merkmal, m.wert,
       'bwl_wahlbezirke_' || s.wahljahr AS lieferung_id
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
WITH bezirk AS (
    SELECT w.*,
           raum.gemeinde_ags(w.ags) AS gem_ags
    FROM {DB_SCHEMA}.wahlbezirk w
),
geteilt AS (
    SELECT wahljahr, gem_ags
    FROM (SELECT DISTINCT wahljahr, gem_ags, wkr_nr FROM bezirk) d
    WHERE NOT raum.ist_sammelposten(gem_ags)
    GROUP BY 1, 2 HAVING count(*) > 1
),
zuordnung AS (
    SELECT b.wahljahr, b.wkr_nr, b.ags, b.bezirk_nr, b.bezirksart, b.bwbez,
           b.bezirk_original,
           CASE WHEN b.bwbez = '00' THEN b.gem_ags
                ELSE 'V-' || b.kreis || '-' || b.bwbez
                     || '-' || lpad(b.wkr_nr::text, 3, '0') END AS einheit_id
    FROM bezirk b
    WHERE NOT EXISTS (SELECT 1 FROM geteilt g
                      WHERE (g.wahljahr, g.gem_ags) = (b.wahljahr, b.gem_ags))
)
SELECT z.wahljahr, z.einheit_id, r.stimme, r.partei, sum(r.stimmen) AS stimmen
FROM zuordnung z
JOIN {DB_SCHEMA}.wahlbezirksergebnis r
  ON (r.wahljahr, r.wkr_nr, r.ags, r.bezirk_nr, r.bezirksart, r.bwbez,
      r.bezirk_original)
   = (z.wahljahr, z.wkr_nr, z.ags, z.bezirk_nr, z.bezirksart, z.bwbez,
      z.bezirk_original)
GROUP BY 1, 2, 3, 4;

ALTER TABLE {DB_SCHEMA}.{T_ERG} ADD PRIMARY KEY (wahljahr, einheit_id, stimme, partei);
CREATE INDEX {T_ERG}_partei ON {DB_SCHEMA}.{T_ERG} (wahljahr, partei, stimme);
"""


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, T_EINHEIT)
    log.info("%-6s %-18s %10s %11s %14s", "Jahr", "Typ", "Einheiten",
             "Gemeinden", "Wahlberecht.")
    for zeile in query(f"""
        SELECT e.wahljahr, e.typ, count(*), sum(e.gemeinden),
               to_char(sum(k.wert), 'FM999G999G999')
        FROM {RAUM_SCHEMA}.{T_EINHEIT} e
        LEFT JOIN {DB_SCHEMA}.{T_KENNZAHL} k
          ON (k.wahljahr, k.einheit_id) = (e.wahljahr, e.einheit_id)
         AND k.merkmal = 'wahlberechtigte'
        GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("%-6s %-18s %10s %11s %14s", *zeile)

    log.info("--- Verbuende: wie viele Gemeinden gehen darin auf? ---")
    for zeile in query(f"""
        SELECT wahljahr, count(*) AS verbuende, sum(gemeinden) AS mitglieder,
               round(avg(gemeinden), 1) AS im_schnitt, max(gemeinden) AS groesster
        FROM {RAUM_SCHEMA}.{T_EINHEIT} WHERE typ = 'briefwahleinheit'
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Verbuende mit %s Gemeinden (Schnitt %s, groesster %s)",
                 *zeile)

    log.info("--- Vollstaendigkeit: jeder Wahlbezirk genau einer Einheit? ---")
    for zeile in query(f"""
        SELECT b.wahljahr,
               count(*)                                    AS bezirke,
               count(*) FILTER (WHERE g.gem_ags IS NOT NULL) AS in_grossstadt,
               count(*) FILTER (WHERE g.gem_ags IS NULL)     AS in_gemeindeebene
        FROM (SELECT w.*, raum.gemeinde_ags(w.ags) AS gem_ags
              FROM {DB_SCHEMA}.wahlbezirk w) b
        LEFT JOIN (SELECT DISTINCT wahljahr, ags AS gem_ags
                   FROM {RAUM_SCHEMA}.kleinst_100_geteilt) g
          ON (g.wahljahr, g.gem_ags) = (b.wahljahr, b.gem_ags)
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Bezirke, davon %s in kleinst_100_geteilt, " "%s hier", *zeile)

    log.info("--- Aufwaertskompatibilitaet: beide Bestaende je Wahlkreis ---")
    for zeile in query(f"""
        SELECT a.wahljahr, a.stimme, count(*) AS wahlkreise,
               count(*) FILTER (WHERE a.summe <> w.summe) AS abweichend
        FROM (SELECT e.wahljahr, e.wkr_nr, r.stimme, sum(r.stimmen) AS summe
              FROM (SELECT wahljahr, einheit_id, wkr_nr FROM {RAUM_SCHEMA}.{T_EINHEIT}
                    UNION ALL
                    SELECT wahljahr, einheit_id, wkr_nr
                    FROM {RAUM_SCHEMA}.kleinst_100_geteilt) e
              JOIN (SELECT wahljahr, einheit_id, stimme, stimmen
                    FROM {DB_SCHEMA}.{T_ERG}
                    UNION ALL
                    SELECT wahljahr, einheit_id, stimme, stimmen
                    FROM {DB_SCHEMA}.kleinst_100_geteilt_ergebnis) r
                ON (r.wahljahr, r.einheit_id) = (e.wahljahr, e.einheit_id)
              GROUP BY 1, 2, 3) a
        JOIN (SELECT wahljahr, wkr_nr, stimme, sum(stimmen) AS summe
              FROM {DB_SCHEMA}.wahlbezirksergebnis GROUP BY 1, 2, 3) w
          USING (wahljahr, wkr_nr, stimme)
        GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  %s %s: %s Wahlkreise, davon abweichend %s", *zeile)

    log.info("--- Gegenprobe gegen die Wahlkreisebene (GERDA) ---")
    for zeile in query(f"""
        SELECT a.wahljahr,
               to_char(a.summe, 'FM999G999G999'), to_char(g.summe, 'FM999G999G999'),
               to_char(a.summe - g.summe, 'FM999G999G999')
        FROM (SELECT wahljahr, sum(stimmen) AS summe FROM
                (SELECT wahljahr, stimmen, stimme FROM {DB_SCHEMA}.{T_ERG}
                 UNION ALL
                 SELECT wahljahr, stimmen, stimme
                 FROM {DB_SCHEMA}.kleinst_100_geteilt_ergebnis) x
              WHERE stimme = 'zweitstimme' GROUP BY 1) a
        JOIN (SELECT wahljahr, sum(stimmen) AS summe
              FROM gerda.wahlergebnis_gerda_wahlkreis
              WHERE stimme = 'zweitstimme' GROUP BY 1) g USING (wahljahr)
        ORDER BY 1;
    """):
        log.info("  %s: beide Bestaende %s, GERDA %s, Differenz %s", *zeile)

    log.info("--- Einheiten ohne Geometrie ---")
    for zeile in query(f"""
        SELECT wahljahr, typ, count(*) FROM {RAUM_SCHEMA}.{T_EINHEIT}
        WHERE geom IS NULL GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  %s %s: %s", *zeile)


def main():
    run_sql(SQL, "gemeindeebene amtlich")
    report()


if __name__ == "__main__":
    main()
