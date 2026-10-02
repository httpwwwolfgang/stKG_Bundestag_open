import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "raum"
TABELLE   = "gemeindestand_stichtag"
STAND     = "gemeindestand"
UEBERGANG = "gebietsuebergang"


ARTEN = ["wahltag", "gebietsstand_wahlkreise", "gebietsstand_zuordnungsliste"]


LANDFILTER = {
    "2012-01-01": "07",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stand-stichtag")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    stichtag     DATE     NOT NULL,
    ags          CHAR(8)  NOT NULL,
    gen          TEXT,
    bez          TEXT,
    ars          TEXT,
    ewz          INTEGER,
    flaeche_km2  DOUBLE PRECISION,
    quelle_stand DATE     NOT NULL,
    geom         geometry(MultiPolygon, 25832) NOT NULL,
    PRIMARY KEY (stichtag, ags)
);

CREATE INDEX IF NOT EXISTS {TABELLE}_geom_idx
    ON {DB_SCHEMA}.{TABELLE} USING GIST (geom);
"""


def stichtage():
    arten = ", ".join("'" + a + "'" for a in ARTEN)
    return query(f"""
        SELECT t.datum, t.art, coalesce(t.bezug, ''),
               (SELECT max(stichtag) FROM {DB_SCHEMA}.{STAND} s WHERE s.stichtag <  t.datum),
               (SELECT min(stichtag) FROM {DB_SCHEMA}.{STAND} s WHERE s.stichtag >= t.datum)
        FROM zeit.stichtag t
        WHERE t.art IN ({arten})
        ORDER BY t.datum;
    """)


def lade(datum, davor, danach):
    land = LANDFILTER.get(datum)
    filt = f"AND left(ags, 2) = '{land}'" if land else ""

    run_sql(f"""
        DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE stichtag = DATE '{datum}';

        WITH fenster AS (
            SELECT ags_alt, ags_neu FROM {DB_SCHEMA}.{UEBERGANG}
            WHERE wirksam > DATE '{davor}' AND wirksam <= DATE '{datum}'
        ),
        geaendert AS (SELECT DISTINCT ags_neu AS ags FROM fenster),
        beendet   AS (SELECT DISTINCT ags_alt AS ags FROM fenster)
        INSERT INTO {DB_SCHEMA}.{TABELLE}
            (stichtag, ags, gen, bez, ars, ewz, flaeche_km2, quelle_stand, geom)


        SELECT DATE '{datum}', s.ags, s.gen, s.bez, s.ars, s.ewz, s.flaeche_km2,
               s.stichtag, s.geom
        FROM {DB_SCHEMA}.{STAND} s
        WHERE s.stichtag = DATE '{danach}'
          AND s.ags IN (SELECT ags FROM geaendert)
          {filt}

        UNION ALL


        SELECT DATE '{datum}', s.ags, s.gen, s.bez, s.ars, s.ewz, s.flaeche_km2,
               s.stichtag, s.geom
        FROM {DB_SCHEMA}.{STAND} s
        WHERE s.stichtag = DATE '{davor}'
          AND s.ags NOT IN (SELECT ags FROM geaendert)
          AND s.ags NOT IN (SELECT ags FROM beendet)
          {filt};
    """, f"stand {datum}")


def report(zeilen):
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    log.info("%-12s %-26s %-10s %9s %9s %9s",
             "Stichtag", "Art", "Bezug", "gesamt", "aus davor", "aus danach")
    for datum, art, bezug, davor, danach in zeilen:
        z = query(f"""
            SELECT count(*),
                   count(*) FILTER (WHERE quelle_stand = DATE '{davor}'),
                   count(*) FILTER (WHERE quelle_stand = DATE '{danach}')
            FROM {DB_SCHEMA}.{TABELLE} WHERE stichtag = DATE '{datum}';
        """)
        if z:
            log.info("%-12s %-26s %-10s %9s %9s %9s", datum, art, bezug, *z[0])


    log.info("--- Abgleich mit dem Jahrgang davor ---")
    for datum, _, _, davor, _ in zeilen:
        z = query(f"""
            SELECT (SELECT count(*) FROM {DB_SCHEMA}.{TABELLE} WHERE stichtag = DATE '{datum}'),
                   (SELECT count(*) FROM {DB_SCHEMA}.{STAND}   WHERE stichtag = DATE '{davor}');
        """)
        if z and z[0][1] != '0':
            log.info("  %s: %s Gemeinden gegen %s im Stand %s", datum, z[0][0], z[0][1], davor)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    if not query(f"SELECT 1 FROM {DB_SCHEMA}.{UEBERGANG} LIMIT 1;"):
        raise SystemExit(f"{DB_SCHEMA}.{UEBERGANG} ist leer - erst load_gebietsuebergaenge.py")

    run_sql(DDL, "ddl")

    zeilen = stichtage()
    if not zeilen:
        raise SystemExit("Keine Stichtage in zeit.stichtag - erst load_stichtage.py")

    for datum, art, bezug, davor, danach in zeilen:
        if not davor or not danach:
            log.warning("%s (%s): kein Jahrgang %s - uebersprungen",
                        datum, art, "davor" if not davor else "danach")
            continue
        log.info("%s (%s, %s): aus %s und %s", datum, art, bezug, davor, danach)
        lade(datum, davor, danach)

    report([z for z in zeilen if z[3] and z[4]])


if __name__ == "__main__":
    main()
