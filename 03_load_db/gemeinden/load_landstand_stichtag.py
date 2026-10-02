import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA   = "raum"
STAND       = "landstand"
TABELLE     = "landstand_stichtag"
TARGET_SRID = 25832


LANDFILTER = {
    "2012-01-01": "07",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("landstand-stichtag")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    stichtag     DATE     NOT NULL,
    ags          CHAR(2)  NOT NULL,
    gen          TEXT,
    bez          TEXT,
    ars          TEXT,
    ewz          INTEGER,
    flaeche_km2  DOUBLE PRECISION,
    quelle_stand DATE     NOT NULL,
    geom         geometry(MultiPolygon, {TARGET_SRID}) NOT NULL,
    PRIMARY KEY (stichtag, ags)
);

CREATE INDEX IF NOT EXISTS {TABELLE}_geom_idx
    ON {DB_SCHEMA}.{TABELLE} USING GIST (geom);

COMMENT ON TABLE {DB_SCHEMA}.{TABELLE} IS
  'Bundeslaender je Stichtag. quelle_stand haelt fest, aus welchem Jahrgang '
  'die Zeile stammt - auf dieser Ebene immer der letzte vor dem Stichtag, '
  'weil sich Laendergrenzen nicht aendern.';
"""


SQL = f"""
TRUNCATE {DB_SCHEMA}.{TABELLE};

INSERT INTO {DB_SCHEMA}.{TABELLE}
    (stichtag, ags, gen, bez, ars, ewz, flaeche_km2, quelle_stand, geom)
SELECT t.datum, s.ags, s.gen, s.bez, s.ars, s.ewz, s.flaeche_km2,
       s.stichtag, s.geom
FROM (SELECT DISTINCT datum FROM zeit.stichtag) t
JOIN {DB_SCHEMA}.{STAND} s ON s.stichtag = DATE '2021-12-31'
WHERE NOT EXISTS (SELECT 1 FROM (VALUES {{landfilter}}) AS f(datum, land)
                  WHERE f.datum = t.datum AND f.land <> s.ags);
"""


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT s.stichtag::text,
               string_agg(DISTINCT t.art, ' / ' ORDER BY t.art) AS art,
               count(DISTINCT s.ags) AS laender,
               max(s.quelle_stand)::text AS aus_jahrgang
        FROM {DB_SCHEMA}.{TABELLE} s
        JOIN zeit.stichtag t ON t.datum = s.stichtag
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s  %-42s %s Laender, Jahrgang %s", *zeile)

    log.info("--- Stichtage ohne Landesstand ---")
    fehlend = query(f"""
        SELECT t.datum::text, t.art, t.bezug
        FROM zeit.stichtag t
        WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} s
                          WHERE s.stichtag = t.datum)
        ORDER BY 1;
    """)
    if fehlend:
        for zeile in fehlend:
            log.warning("  %s %s %s - kein Jahrgang davor", *zeile)
    else:
        log.info("  keine - jeder Stichtag hat seine sechzehn")


    log.info("--- Gegenprobe gegen gemeindestand_stichtag ---")
    for zeile in query(f"""
        SELECT l.stichtag::text, l.n AS laender, g.n AS aus_gemeinden
        FROM (SELECT stichtag, count(*) AS n
              FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1) l
        JOIN (SELECT stichtag, count(DISTINCT left(ags, 2)) AS n
              FROM {DB_SCHEMA}.gemeindestand_stichtag GROUP BY 1) g
          USING (stichtag)
        ORDER BY 1;
    """):
        stichtag, laender, gem = zeile
        marke = "deckt sich" if laender == gem else "ABWEICHUNG"
        log.info("  %s: %s Laender, %s aus Gemeinden - %s",
                 stichtag, laender, gem, marke)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    if not query(f"SELECT 1 FROM {DB_SCHEMA}.{STAND} LIMIT 1;"):
        raise SystemExit(f"{DB_SCHEMA}.{STAND} ist leer - erst load_landstaende.py")

    run_sql(DDL, "ddl")
    werte = ", ".join(f"(DATE '{d}', '{l}')" for d, l in LANDFILTER.items())
    run_sql(SQL.replace("{landfilter}", werte), TABELLE)
    report()


if __name__ == "__main__":
    main()
