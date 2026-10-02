import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "gerda"
T_EINHEIT = "kleinst_100_einheit"
T_ERG     = "kleinst_100_einheit_ergebnis"

JAHRE = [2013, 2017, 2021]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("auswertungseinheit")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_EINHEIT} (
    wahljahr    SMALLINT NOT NULL,
    einheit_id  TEXT     NOT NULL,
    typ         TEXT     NOT NULL
                CHECK (typ IN ('gemeinde', 'briefwahlverbund', 'grossstadt_wahlkreis')),
    bezeichnung TEXT,
    gemeinden   INTEGER,
    herkunft    TEXT     NOT NULL,
    geom        geometry(MultiPolygon, 25832),
    PRIMARY KEY (wahljahr, einheit_id)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_ERG} (
    wahljahr   SMALLINT NOT NULL,
    einheit_id TEXT     NOT NULL,
    partei     TEXT     NOT NULL,
    stimmen    INTEGER,
    PRIMARY KEY (wahljahr, einheit_id, partei),
    FOREIGN KEY (wahljahr, einheit_id)
        REFERENCES {DB_SCHEMA}.{T_EINHEIT} (wahljahr, einheit_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS {T_EINHEIT}_gix ON {DB_SCHEMA}.{T_EINHEIT} USING GIST (geom);
CREATE INDEX IF NOT EXISTS {T_EINHEIT}_typ ON {DB_SCHEMA}.{T_EINHEIT} (wahljahr, typ);
"""


def lade(jahr):
    run_sql(f"""
    DELETE FROM {DB_SCHEMA}.{T_EINHEIT} WHERE wahljahr = {jahr};


    CREATE TEMP TABLE geteilt AS
        SELECT ags FROM raum.gemeinde_wahlkreis_wahltag
        WHERE wahljahr = {jahr} GROUP BY ags HAVING count(DISTINCT wkr_nr) > 1;


    CREATE TEMP TABLE fremd AS
        SELECT gw.wkr_nr, gw.ags
        FROM raum.gemeinde_wahlkreis_wahltag gw
        WHERE gw.wahljahr = {jahr}
          AND gw.wkr_nr IN (SELECT DISTINCT wkr_nr FROM raum.gemeinde_wahlkreis_wahltag
                            WHERE wahljahr = {jahr} AND ags IN (SELECT ags FROM geteilt))
          AND gw.ags NOT IN (SELECT ags FROM geteilt);



    CREATE TEMP TABLE stadt_wkr AS
        SELECT DISTINCT gw.wkr_nr
        FROM raum.gemeinde_wahlkreis_wahltag gw
        WHERE gw.wahljahr = {jahr} AND gw.ags IN (SELECT ags FROM geteilt)
          AND NOT EXISTS (
              SELECT 1 FROM fremd f
              WHERE f.wkr_nr = gw.wkr_nr
                AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.briefwahl_gemeinde b
                                WHERE b.wahljahr = {jahr} AND b.ags = f.ags
                                  AND b.briefwahl = 'eigen'));



    CREATE TEMP TABLE geteilt_offen AS
        SELECT g.ags FROM geteilt g
        WHERE NOT EXISTS (SELECT 1 FROM raum.gemeinde_wahlkreis_wahltag gw
                          JOIN stadt_wkr s ON s.wkr_nr = gw.wkr_nr
                          WHERE gw.wahljahr = {jahr} AND gw.ags = g.ags);


    INSERT INTO {DB_SCHEMA}.{T_EINHEIT}
        (wahljahr, einheit_id, typ, bezeichnung, gemeinden, herkunft, geom)
    SELECT {jahr}, 'G' || b.ags, 'gemeinde', b.gemeinde, 1,
           CASE WHEN b.ags IN (SELECT ags FROM geteilt_offen)
                THEN 'Gemeinde mit eigenem Briefwahlbezirk, Wahlkreise nicht trennbar'
                ELSE 'Gemeinde mit eigenem Briefwahlbezirk' END,
           b.geom
    FROM {DB_SCHEMA}.briefwahl_gemeinde b
    WHERE b.wahljahr = {jahr} AND b.briefwahl = 'eigen'
      AND (b.ags NOT IN (SELECT ags FROM geteilt)
           OR b.ags IN (SELECT ags FROM geteilt_offen));


    INSERT INTO {DB_SCHEMA}.{T_EINHEIT}
        (wahljahr, einheit_id, typ, bezeichnung, gemeinden, herkunft, geom)
    SELECT {jahr}, 'V' || v.verbund_id, 'briefwahlverbund',






           coalesce((SELECT string_agg(DISTINCT s.gemeindename, ' / ')
                     FROM wahlergebnisse.briefwahlbezirk s
                     WHERE s.wahljahr = {jahr} AND s.sammelposten
                       AND s.kreis = split_part(v.verbund_id, '-', 1)
                       AND s.bwbez = lpad(split_part(v.verbund_id, '-', 2), 2, '0')),
                    'Briefwahlverbund ' || v.verbund_id),
           v.gemeinden,
           'Urnenwahl der Mitglieder und Briefwahl des Sammelpostens', v.geom
    FROM {DB_SCHEMA}.briefwahl_verbund v
    WHERE v.wahljahr = {jahr};


    INSERT INTO {DB_SCHEMA}.{T_EINHEIT}
        (wahljahr, einheit_id, typ, bezeichnung, gemeinden, herkunft, geom)
    SELECT {jahr}, 'W' || lpad(w.wkr_nr::text, 3, '0'), 'grossstadt_wahlkreis',
           w.wkr_name,
           (SELECT count(*) FROM raum.gemeinde_wahlkreis_wahltag x
             WHERE x.wahljahr = {jahr} AND x.wkr_nr = w.wkr_nr),
           CASE WHEN EXISTS (SELECT 1 FROM fremd f WHERE f.wkr_nr = w.wkr_nr)
                THEN 'Wahlkreisergebnis abzueglich der Fremdgemeinden'
                ELSE 'Wahlkreisergebnis unveraendert' END,

           CASE WHEN EXISTS (SELECT 1 FROM fremd f WHERE f.wkr_nr = w.wkr_nr)
                THEN (SELECT ST_Multi(ST_CollectionExtract(ST_MakeValid(
                        ST_Intersection(w.geom, ST_Union(s.geom))), 3))
                      FROM raum.gemeindestand_stichtag s
                      JOIN zeit.stichtag t ON t.art = 'wahltag'
                       AND t.bezug = 'Wahl {jahr}' AND s.stichtag = t.datum
                      JOIN raum.gemeinde_wahlkreis_wahltag gw
                        ON gw.wahljahr = {jahr} AND gw.ags = s.ags
                       AND gw.wkr_nr = w.wkr_nr
                      WHERE s.ags IN (SELECT ags FROM geteilt))
                ELSE w.geom END
    FROM raum.wahlkreis w
    WHERE w.wahljahr = {jahr} AND w.wkr_nr IN (SELECT wkr_nr FROM stadt_wkr);









    UPDATE {DB_SCHEMA}.{T_EINHEIT} e
    SET geom      = ST_Multi(ST_Union(e.geom, z.geom)),
        gemeinden = e.gemeinden + z.n
    FROM (
        SELECT CASE WHEN bg.briefwahl = 'eigen' THEN 'G' || bg.ags
                    ELSE 'V' || bg.verbund_id END AS einheit_id,
               ST_Union(s.geom) AS geom, count(*) AS n
        FROM raum.gemeinde_aufnahme a
        JOIN {DB_SCHEMA}.briefwahl_gemeinde bg
          ON bg.wahljahr = a.wahljahr AND bg.ags = a.ags_aufnehmend
        JOIN zeit.stichtag zt
          ON zt.art = 'wahltag' AND zt.bezug = 'Wahl {jahr}'
        JOIN raum.gemeindestand_stichtag s
          ON s.stichtag = zt.datum AND s.ags = a.ags
        WHERE a.wahljahr = {jahr}
        GROUP BY 1
    ) z
    WHERE e.wahljahr = {jahr} AND e.einheit_id = z.einheit_id;



    INSERT INTO {DB_SCHEMA}.{T_ERG} (wahljahr, einheit_id, partei, stimmen)
    SELECT {jahr}, 'G' || g.ags, g.partei, sum(g.stimmen)
    FROM {DB_SCHEMA}.gemeindeergebnis_gerda g
    JOIN {DB_SCHEMA}.briefwahl_gemeinde b
      ON (b.wahljahr, b.ags, b.bwbez) = (g.wahljahr, g.ags, g.bwbez)
     AND b.briefwahl = 'eigen'
    WHERE g.wahljahr = {jahr}
      AND EXISTS (SELECT 1 FROM {DB_SCHEMA}.{T_EINHEIT} e
                  WHERE e.wahljahr = {jahr} AND e.einheit_id = 'G' || g.ags)
    GROUP BY g.ags, g.partei;



    INSERT INTO {DB_SCHEMA}.{T_ERG} (wahljahr, einheit_id, partei, stimmen)
    SELECT {jahr}, 'V' || v.verbund_id, g.partei, sum(g.stimmen)
    FROM {DB_SCHEMA}.briefwahl_verbund v
    JOIN {DB_SCHEMA}.gemeindeeinheit_gerda m
      ON m.wahljahr = {jahr} AND m.kreis = v.kreis AND m.bwbez = v.bwbez
    JOIN {DB_SCHEMA}.gemeindeergebnis_gerda g
      ON (g.wahljahr, g.ags, g.bwbez) = (m.wahljahr, m.ags, m.bwbez)
    WHERE v.wahljahr = {jahr}
    GROUP BY v.verbund_id, g.partei;




    INSERT INTO {DB_SCHEMA}.{T_ERG} (wahljahr, einheit_id, partei, stimmen)
    SELECT {jahr}, 'W' || lpad(e.wkr_nr::text, 3, '0'), e.partei,
           e.stimmen - coalesce((
               SELECT sum(g.stimmen)
               FROM fremd f
               JOIN {DB_SCHEMA}.briefwahl_gemeinde b
                 ON b.wahljahr = {jahr} AND b.ags = f.ags AND b.briefwahl = 'eigen'
               JOIN {DB_SCHEMA}.gemeindeergebnis_gerda g
                 ON (g.wahljahr, g.ags, g.bwbez) = (b.wahljahr, b.ags, b.bwbez)
                AND g.partei = e.partei
               WHERE f.wkr_nr = e.wkr_nr), 0)
    FROM {DB_SCHEMA}.wahlergebnis_gerda_wahlkreis e
    WHERE e.wahljahr = {jahr} AND e.stimme = 'zweitstimme'
      AND e.wkr_nr IN (SELECT wkr_nr FROM stadt_wkr);

    DROP TABLE geteilt; DROP TABLE fremd; DROP TABLE stadt_wkr;
    DROP TABLE geteilt_offen;
    """, f"kleinst_100_einheit {jahr}")


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, T_EINHEIT)
    log.info("%-6s %-22s %10s %10s", "Jahr", "Typ", "Einheiten", "Gemeinden")
    for zeile in query(f"""
        SELECT wahljahr, typ, count(*), sum(gemeinden)
        FROM {DB_SCHEMA}.{T_EINHEIT} GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("%-6s %-22s %10s %10s", *zeile)

    log.info("--- Einheiten ohne Ergebnis ---")
    for zeile in query(f"""
        SELECT e.wahljahr, e.typ, count(*)
        FROM {DB_SCHEMA}.{T_EINHEIT} e
        WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{T_ERG} r
                          WHERE (r.wahljahr, r.einheit_id) = (e.wahljahr, e.einheit_id))
        GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  %s %s: %s", *zeile)

    log.info("--- Gegenprobe: Zweitstimmen gegen die Wahlkreisebene ---")
    for zeile in query(f"""
        SELECT a.wahljahr,
               to_char(a.summe, 'FM999G999G999'), to_char(w.summe, 'FM999G999G999'),
               to_char(a.summe - w.summe, 'FM999G999G999')
        FROM (SELECT wahljahr, sum(stimmen) AS summe FROM {DB_SCHEMA}.{T_ERG}
              GROUP BY 1) a
        JOIN (SELECT wahljahr, sum(stimmen) AS summe
              FROM {DB_SCHEMA}.wahlergebnis_gerda_wahlkreis
              WHERE stimme = 'zweitstimme' GROUP BY 1) w USING (wahljahr)
        ORDER BY 1;
    """):
        log.info("  %s: Einheiten %s, Wahlkreise %s, Differenz %s", *zeile)

    log.info("--- Ueberdeckung: Gemeinden je Wahljahr ---")
    for zeile in query(f"""
        SELECT wahljahr, to_char(sum(gemeinden), 'FM999G999')
        FROM {DB_SCHEMA}.{T_EINHEIT} WHERE typ <> 'grossstadt_wahlkreis'
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden in Gemeinde- und Verbundeinheiten", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        for t in (T_ERG, T_EINHEIT):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;", f"drop {t}")
        log.warning("Tabellen verworfen.")

    run_sql(DDL, "ddl")
    for jahr in JAHRE:
        log.info("Wahljahr %s", jahr)
        lade(jahr)
    report()


if __name__ == "__main__":
    main()
