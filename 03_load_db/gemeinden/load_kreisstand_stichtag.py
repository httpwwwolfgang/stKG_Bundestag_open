import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "raum"
TABELLE   = "kreisstand_stichtag"
STAND     = "kreisstand"
UEBERGANG = "gebietsuebergang"
EBENE     = "Kreis"


ARTEN = ["wahltag", "gebietsstand_wahlkreise", "gebietsstand_zuordnungsliste"]


LANDFILTER = {
    "2012-01-01": "07",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kreisstand-stichtag")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    stichtag     DATE     NOT NULL,
    ags          CHAR(5)  NOT NULL,
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
CREATE INDEX IF NOT EXISTS {TABELLE}_ags_idx
    ON {DB_SCHEMA}.{TABELLE} (ags);
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
            WHERE ebene = '{EBENE}'
              AND wirksam > DATE '{davor}' AND wirksam <= DATE '{datum}'
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
    """, f"kreisstand {datum}")


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT stichtag::text, count(*) AS kreise,
               count(*) FILTER (WHERE quelle_stand > stichtag) AS aus_spaeterem_stand
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Kreise, davon %s aus dem spaeteren Jahrgang", *zeile)


    log.info("--- Gegenprobe gegen gemeindestand_stichtag ---")
    for zeile in query(f"""
        SELECT k.stichtag::text, k.n AS aus_kreisen, g.n AS aus_gemeinden,
               k.n - g.n AS differenz
        FROM (SELECT stichtag, count(*) AS n
              FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1) k
        JOIN (SELECT stichtag, count(DISTINCT left(ags, 5)) AS n
              FROM {DB_SCHEMA}.gemeindestand_stichtag GROUP BY 1) g
          USING (stichtag)
        ORDER BY 1;
    """):
        log.info("  %s: Kreisebene %s, aus Gemeinden %s, Differenz %s", *zeile)


    log.info("--- Kreise, die nicht an allen drei Wahltagen bestanden ---")
    for zeile in query(f"""
        WITH wahltag AS (
            SELECT datum FROM zeit.stichtag WHERE art = 'wahltag'
        )
        SELECT k.ags, max(k.gen) AS gen,
               string_agg(k.stichtag::text, ', ' ORDER BY k.stichtag) AS staende
        FROM {DB_SCHEMA}.{TABELLE} k
        JOIN wahltag w ON w.datum = k.stichtag
        GROUP BY k.ags
        HAVING count(*) < (SELECT count(*) FROM wahltag)
        ORDER BY 1;
    """):
        log.info("  %s %-28s nur %s", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;",
                "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    if not query(f"SELECT 1 FROM {DB_SCHEMA}.{STAND} LIMIT 1;"):
        raise SystemExit(f"{DB_SCHEMA}.{STAND} ist leer - erst load_kreisstaende.py")

    run_sql(DDL, "ddl")

    for datum, art, bezug, davor, danach in stichtage():
        if davor is None or danach is None:
            log.warning("%s (%s): kein Jahresstand %s - uebersprungen",
                        datum, art, "davor" if davor is None else "danach")
            continue
        log.info("%s  %-28s %s", datum, art + (f" / {bezug}" if bezug else ""),
                 f"{davor} -> {danach}")
        lade(datum, davor, danach)

    report()


if __name__ == "__main__":
    main()
