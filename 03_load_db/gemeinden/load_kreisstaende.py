import re
import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query, shp2pgsql_to_db, dbf_encoding


LIEFERUNG = "bkg_vg250"

DB_SCHEMA   = "raum"
ROH_SCHEMA  = "roh_gemeinden"
TABELLE     = "kreisstand"
TARGET_SRID = 25832

QUELL_DIR = (Path(__file__).resolve().parents[4]
             / "Daten" / "Gemeinde_Gebietsänderungen" / "Gebietsstände")


SPALTEN = {
    "ags": (["ags"],               True),
    "gen": (["gen"],               True),
    "bez": (["bez", "des"],        True),
    "ars": (["ars", "rs"],         True),
    "ewz": (["ewz"],               False),
    "wsk": (["wsk", "wirksamkei"], False),
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kreisstand")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    stichtag    DATE     NOT NULL,
    ags         CHAR(5)  NOT NULL,
    gen         TEXT,
    bez         TEXT,
    ars         TEXT,
    ewz         INTEGER,
    wirksam_ab  DATE,
    flaeche_km2 DOUBLE PRECISION,
    geom        geometry(MultiPolygon, {TARGET_SRID}) NOT NULL,
    PRIMARY KEY (stichtag, ags)
);

CREATE INDEX IF NOT EXISTS {TABELLE}_geom_idx
    ON {DB_SCHEMA}.{TABELLE} USING GIST (geom);
CREATE INDEX IF NOT EXISTS {TABELLE}_ags_idx
    ON {DB_SCHEMA}.{TABELLE} (ags);
"""


def jahrgaenge():
    gefunden = {}
    for ordner in sorted(QUELL_DIR.iterdir()):
        if not ordner.is_dir():
            continue
        treffer = re.match(r"^(\d{4})_vg250", ordner.name)
        if not treffer:
            continue
        shp = [p for p in ordner.rglob("*.shp") if p.stem.lower() == "vg250_krs"]
        if not shp:
            log.warning("%s: kein vg250_krs.shp gefunden", ordner.name)
            continue
        if len(shp) > 1:
            raise SystemExit(f"{ordner.name}: mehrere Kreis-Shapefiles {shp}")
        gefunden[int(treffer.group(1))] = shp[0]
    return gefunden


def vorhandene_spalten(tabelle):
    zeilen = query(f"""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = '{ROH_SCHEMA}' AND table_name = '{tabelle}';
    """)
    return {z[0] for z in zeilen}


def abbildung(tabelle, jahr):
    da = vorhandene_spalten(tabelle)
    zuordnung, fehlend = {}, []
    for ziel, (aliase, pflicht) in SPALTEN.items():
        treffer = next((a for a in aliase if a in da), None)
        if treffer is None and pflicht:
            fehlend.append(f"{ziel} ({'/'.join(aliase)})")
        zuordnung[ziel] = treffer
    if fehlend:
        raise SystemExit(f"{jahr}: Pflichtspalten fehlen: {fehlend}")
    if "gf" not in da:
        raise SystemExit(f"{jahr}: Spalte gf fehlt - GF-Filter nicht moeglich")
    return zuordnung


def lade(jahr, shp):
    stichtag = f"{jahr}-12-31"
    staging  = f"stg_krs_{jahr}"

    log.info("[%s] %s", jahr, shp.relative_to(QUELL_DIR))
    shp2pgsql_to_db(shp, staging, TARGET_SRID, dbf_encoding(shp), schema=ROH_SCHEMA)

    z = abbildung(staging, jahr)
    log.info("[%s] Spalten: bez=%s ars=%s ewz=%s wsk=%s",
             jahr, z["bez"], z["ars"], z["ewz"] or "-", z["wsk"] or "-")

    ewz = f"max({z['ewz']}::numeric)::INTEGER" if z["ewz"] else "NULL::INTEGER"
    wsk = f"max({z['wsk']})"                   if z["wsk"] else "NULL::DATE"

    run_sql(f"""
        DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE stichtag = DATE '{stichtag}';

        INSERT INTO {DB_SCHEMA}.{TABELLE}
            (stichtag, ags, gen, bez, ars, ewz, wirksam_ab, flaeche_km2, geom)
        SELECT DATE '{stichtag}', ags, gen, bez, ars, ewz, wirksam_ab,
               ST_Area(ST_Transform(geom, 3035)) / 1e6, geom
        FROM (
            SELECT left(trim({z['ags']}), 5)             AS ags,
                   max(trim({z['gen']}))                 AS gen,
                   max(trim({z['bez']}))                 AS bez,
                   max(trim({z['ars']}))                 AS ars,
                   {ewz}                                 AS ewz,
                   {wsk}                                 AS wirksam_ab,
                   ST_Multi(ST_CollectionExtract(
                       ST_MakeValid(ST_Union(geom)), 3)) AS geom
            FROM {ROH_SCHEMA}.{staging}
            WHERE gf::int = 4
            GROUP BY left(trim({z['ags']}), 5)
        ) t;
    """, f"kreisstand {jahr}")


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT stichtag::text, count(*) AS kreise,
               round(sum(flaeche_km2)::numeric)::text AS flaeche_km2
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Kreise, %s km2", *zeile)

    log.info("--- Bezeichnungen ---")
    for zeile in query(f"""
        SELECT bez, count(DISTINCT ags) AS kreise
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 2 DESC;
    """):
        log.info("  %-28s %s", *zeile)


    log.info("--- Gegenprobe: Kreise gegen AGS-Praefixe der Gemeinden ---")
    for zeile in query(f"""
        SELECT k.stichtag::text,
               k.n AS aus_krs, g.n AS aus_gem,
               (SELECT count(*) FROM {DB_SCHEMA}.{TABELLE} x
                 WHERE x.stichtag = k.stichtag
                   AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeindestand y
                                   WHERE y.stichtag = k.stichtag
                                     AND left(y.ags, 5) = x.ags)) AS nur_krs
        FROM (SELECT stichtag, count(*) AS n
              FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1) k
        JOIN (SELECT stichtag, count(DISTINCT left(ags, 5)) AS n
              FROM {DB_SCHEMA}.gemeindestand GROUP BY 1) g USING (stichtag)
        ORDER BY 1;
    """):
        log.info("  %s: KRS %s, aus Gemeinden %s, ohne Gemeinde %s", *zeile)

    log.info("--- Beispiele: Grossstaedte und Landkreise ---")
    for zeile in query(f"""
        SELECT ags, gen, bez, round(flaeche_km2::numeric, 1)::text
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE stichtag = (SELECT max(stichtag) FROM {DB_SCHEMA}.{TABELLE})
          AND ags IN ('05315', '11000', '02000', '07131', '09162', '16064')
        ORDER BY ags;
    """):
        log.info("  %s %-32s %-22s %s km2", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;",
                "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    run_sql(DDL, "ddl")

    jahre = jahrgaenge()
    if not jahre:
        raise SystemExit(f"Keine Jahrgaenge unter {QUELL_DIR}")
    log.info("Gefunden: %s Jahrgaenge (%s)",
             len(jahre), ", ".join(str(j) for j in sorted(jahre)))

    for jahr in sorted(jahre):
        lade(jahr, jahre[jahr])

    report()


if __name__ == "__main__":
    main()
