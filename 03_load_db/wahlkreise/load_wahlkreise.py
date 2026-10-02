import os
import sys
import subprocess
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import (DB_SCHEMA, ROH_SCHEMA, PG_BIN, WK_DIR, log,
                run_sql, run_sql_file, query,
                shp2pgsql_to_db, dbf_encoding)
import lieferung


LIEFERUNG = "bwl_wahlkreisgeometrie"

DATEN_DIR  = WK_DIR / "WK_Bundeswahlleiterin"
ARCHIV_DIR = WK_DIR / "archiv" / "Bundeswahlleiterin"

TARGET_SRID = 25832


DATASETS = {
    2013: {


        "shp": DATEN_DIR / "btw13_geometrie_wahlkreise_etrs89-vg1000_geo_shp (1)"
                         / "Geometrie_Wahlkreise_18DBT_VG1000.shp",
        "src_srid": 25832,
        "wahlperiode": 18,
        "quelle": "Bundeswahlleiter, Geometrie der Wahlkreise BTW 2013 (VG1000, ETRS89)",
    },
    2017: {
        "shp": DATEN_DIR / "btw17_geometrie_wahlkreise_vg250_shp"
                         / "Geometrie_Wahlkreise_19DBT_VG250.shp",
        "src_srid": 25832,
        "wahlperiode": 19,
        "quelle": "Bundeswahlleiter, Geometrie der Wahlkreise BTW 2017 (VG250)",
    },
    2021: {
        "shp": DATEN_DIR / "btw21_geometrie_wahlkreise_vg250_shp"
                         / "Geometrie_Wahlkreise_20DBT_VG250.shp",
        "src_srid": 25832,
        "wahlperiode": 20,
        "quelle": "Bundeswahlleiter, Geometrie der Wahlkreise BTW 2021 (VG250)",
    },
}


VARIANTEN_2013 = {
    "vg1000": DATASETS[2013]["shp"],
    "stark_generalisiert": ARCHIV_DIR / "btw13_geometrie_wahlkreise_etrs89_geo_shp"
                                      / "Geometrie_Wahlkreise_18DBT.shp",
}


SCHEMA_DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";
CREATE EXTENSION IF NOT EXISTS postgis;
"""


CLEAN_DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.wahlkreis (
    wahljahr     SMALLINT NOT NULL,
    wkr_nr       SMALLINT NOT NULL,
    wkr_name     TEXT     NOT NULL,
    land_nr      SMALLINT,
    land_name    TEXT,
    wahlperiode  SMALLINT,
    flaeche_km2       DOUBLE PRECISION,
    flaeche_km2_utm32 DOUBLE PRECISION,
    quelle       TEXT,
    geom         geometry(MultiPolygon, {TARGET_SRID}) NOT NULL,
    geom_4326    geometry(MultiPolygon, 4326)
                 GENERATED ALWAYS AS (ST_Transform(geom, 4326)) STORED,
    geom_3035    geometry(MultiPolygon, 3035)
                 GENERATED ALWAYS AS (ST_Transform(geom, 3035)) STORED,
    geladen_am   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (wahljahr, wkr_nr)
);
CREATE INDEX IF NOT EXISTS idx_wahlkreis_geom     ON {DB_SCHEMA}.wahlkreis USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_wahlkreis_geom4326 ON {DB_SCHEMA}.wahlkreis USING GIST (geom_4326);
CREATE INDEX IF NOT EXISTS idx_wahlkreis_jahr     ON {DB_SCHEMA}.wahlkreis (wahljahr);
CREATE INDEX IF NOT EXISTS idx_wahlkreis_name     ON {DB_SCHEMA}.wahlkreis (wkr_name);
"""


MIGRATION_DDL = f"""
ALTER TABLE {DB_SCHEMA}.wahlkreis
    ADD COLUMN IF NOT EXISTS flaeche_km2_utm32 DOUBLE PRECISION;
ALTER TABLE {DB_SCHEMA}.wahlkreis
    ADD COLUMN IF NOT EXISTS geom_3035 geometry(MultiPolygon, 3035)
        GENERATED ALWAYS AS (ST_Transform(geom, 3035)) STORED;
CREATE INDEX IF NOT EXISTS idx_wahlkreis_geom3035 ON {DB_SCHEMA}.wahlkreis USING GIST (geom_3035);
"""


def check_extent(jahr, staging):
    xmin, ymin, xmax, ymax = (float(v) for v in query(f"""
        SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e)
        FROM (SELECT ST_Extent(geom) AS e FROM {ROH_SCHEMA}.{staging}) t;
    """)[0])
    plausibel = (250000 < xmin < 950000 and 250000 < xmax < 950000
                 and 5200000 < ymin < 6150000 and 5200000 < ymax < 6150000)
    if not plausibel:
        log.error("[%s] Ausdehnung von %s passt nicht zu EPSG:25832: " "x %.1f..%.1f, y %.1f..%.1f", jahr, staging, xmin, xmax, ymin, ymax)
        log.error("Vermutlich stimmt src_srid nicht mit den Daten ueberein " "(geographische Koordinaten? anderer UTM-Streifen?). Abbruch.")
        raise SystemExit(1)


def _sql_str(value):
    return "'" + str(value).replace("'", "''") + "'"


def build_clean(jahr, cfg, staging):
    sql = f"""
    DELETE FROM {DB_SCHEMA}.wahlkreis WHERE wahljahr = {jahr};

    INSERT INTO {DB_SCHEMA}.wahlkreis
        (wahljahr, wkr_nr, wkr_name, land_nr, land_name, wahlperiode,
         flaeche_km2, flaeche_km2_utm32, quelle, geom)
    SELECT
        {jahr}                                   AS wahljahr,
        s.wkr_nr::SMALLINT                       AS wkr_nr,
        btrim(s.wkr_name)                        AS wkr_name,
        nullif(btrim(s.land_nr), '')::SMALLINT   AS land_nr,
        nullif(btrim(s.land_name), '')           AS land_name,
        {cfg['wahlperiode']}                     AS wahlperiode,
        ST_Area(ST_Transform(g.geom, 3035)) / 1000000.0 AS flaeche_km2,
        ST_Area(g.geom) / 1000000.0              AS flaeche_km2_utm32,
        {_sql_str(cfg['quelle'])}                AS quelle,
        g.geom
    FROM {ROH_SCHEMA}.{staging} s
    CROSS JOIN LATERAL (
        SELECT ST_Multi(
                   ST_CollectionExtract(
                       ST_MakeValid(ST_Transform(s.geom, {TARGET_SRID})), 3)
               )::geometry(MultiPolygon, {TARGET_SRID}) AS geom
    ) g;
    """
    run_sql(sql, label=f"clean {jahr}")


def report():
    rows = query(f"""
        SELECT wahljahr,
               count(*),
               min(wkr_nr), max(wkr_nr),
               count(DISTINCT land_nr),
               round(sum(flaeche_km2)::numeric, 0),
               round(sum(flaeche_km2_utm32)::numeric, 0),
               count(*) FILTER (WHERE NOT ST_IsValid(geom))
        FROM {DB_SCHEMA}.wahlkreis
        GROUP BY wahljahr
        ORDER BY wahljahr;
    """)
    log.info("--- Bestand in %s.wahlkreis ---", DB_SCHEMA)
    log.info("%-6s %-5s %-10s %-8s %-13s %-13s %s",
             "Jahr", "Anz", "WKR-Nr", "Laender", "km2 (3035)", "km2 (25832)", "ungueltig")
    for jahr, anz, nmin, nmax, laender, flaeche, flaeche_utm, invalid in rows:
        log.info("%-6s %-5s %-10s %-8s %-13s %-13s %s",
                 jahr, anz, f"{nmin}-{nmax}", laender, flaeche, flaeche_utm, invalid)
        if anz != "299":
            log.warning("[%s] erwartet 299 Wahlkreise, geladen %s", jahr, anz)
        if invalid != "0":
            log.warning("[%s] %s ungueltige Geometrien trotz ST_MakeValid", jahr, invalid)


    kaputt = query(f"""
        SELECT wahljahr, count(*)
        FROM {DB_SCHEMA}.wahlkreis
        WHERE wkr_name ~ '[\\u0080-\\u009F]'
        GROUP BY wahljahr ORDER BY wahljahr;
    """)
    for jahr, anz in kaputt:
        log.warning("[%s] %s Namen mit Steuerzeichen - falscher Zeichensatz!", jahr, anz)

    probe = query(f"""
        SELECT wahljahr, wkr_nr, wkr_name
        FROM {DB_SCHEMA}.wahlkreis
        WHERE wkr_name !~ '^[\\x20-\\x7E]*$'
        ORDER BY wahljahr, wkr_nr
        LIMIT 3;
    """)
    if probe:
        log.info("Zeichen-Stichprobe (Umlaute und - muessen stimmen): %s",
                 "; ".join(f"{j}/{n} {name}" for j, n, name in probe))
    else:
        log.warning("Keine Namen mit Sonderzeichen gefunden - Encoding pruefen!")


def vergleich_2013():
    for name, shp in VARIANTEN_2013.items():
        if not shp.exists():
            raise SystemExit(f"Shapefile fehlt: {shp}")
        tabelle = f"stg_vergleich_2013_{name}"
        log.info("lade %s -> %s.%s", shp.name, DB_SCHEMA, tabelle)
        shp2pgsql_to_db(shp, tabelle, 25832, dbf_encoding(shp))

    a = f"{DB_SCHEMA}.stg_vergleich_2013_vg1000"
    b = f"{DB_SCHEMA}.stg_vergleich_2013_stark_generalisiert"

    for label, tab in (("VG1000 (geladen)", a), ("Kartenplot-Fassung", b)):
        anz, punkte, flaeche = query(f"""
            SELECT count(*), sum(ST_NPoints(geom)),
                   round((sum(ST_Area(geom)) / 1000000.0)::numeric, 1)
            FROM {tab};
        """)[0]
        log.info("%-20s %s Wahlkreise, %s Stuetzpunkte, %s km2",
                 label, anz, punkte, flaeche)

    hd_mittel, hd_max, hd_wkr, flaechendiff = query(f"""
        WITH d AS (
            SELECT a.wkr_nr,
                   ST_HausdorffDistance(a.geom, b.geom)          AS hd,
                   abs(ST_Area(a.geom) - ST_Area(b.geom))/1000000.0 AS dflaeche
            FROM {a} a JOIN {b} b USING (wkr_nr)
        )
        SELECT round(avg(hd)::numeric, 0),
               round(max(hd)::numeric, 0),
               (SELECT wkr_nr FROM d ORDER BY hd DESC LIMIT 1),
               round(sum(dflaeche)::numeric, 1)
        FROM d;
    """)[0]
    log.info("Grenzabweichung je Wahlkreis: im Mittel %s m, max %s m (WKR %s)",
             hd_mittel, hd_max, hd_wkr)
    log.info("Summe der Flaechendifferenzen: %s km2", flaechendiff)


def main():
    lieferung.merke(LIEFERUNG)
    if "--vergleich" in sys.argv:
        run_sql(SCHEMA_DDL, "schema")
        vergleich_2013()
        return

    jahre = [int(a) for a in sys.argv[1:]] or sorted(DATASETS)
    unbekannt = [j for j in jahre if j not in DATASETS]
    if unbekannt:
        raise SystemExit(f"Unbekannte Jahre: {unbekannt}. Verfuegbar: {sorted(DATASETS)}")
    for jahr in jahre:
        if not DATASETS[jahr]["shp"].exists():
            raise SystemExit(f"Shapefile fehlt: {DATASETS[jahr]['shp']}")

    run_sql(SCHEMA_DDL, "schema")
    run_sql(CLEAN_DDL, "clean-ddl")
    run_sql(MIGRATION_DDL, "migration")
    log.info('Schema "%s" bereit (Ziel-SRID %s).', DB_SCHEMA, TARGET_SRID)

    for jahr in jahre:
        cfg = DATASETS[jahr]
        staging = f"stg_wahlkreis_{jahr}"
        enc = dbf_encoding(cfg["shp"])
        log.info("[%s] lade %s (SRID %s, %s) -> %s.%s",
                 jahr, cfg["shp"].name, cfg["src_srid"], enc, DB_SCHEMA, staging)
        shp2pgsql_to_db(cfg["shp"], staging, cfg["src_srid"], enc,
                        schema=ROH_SCHEMA)
        check_extent(jahr, staging)
        build_clean(jahr, cfg, staging)
        log.info("[%s] fertig.", jahr)

    report()


if __name__ == "__main__":
    main()
