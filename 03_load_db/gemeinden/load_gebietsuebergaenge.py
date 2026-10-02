import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "raum"
TABELLE   = "gebietsuebergang"
ROH       = "stg_gebietsaenderung"
STAND     = "gemeindestand"


EBENEN = {
    "Gemeinde": {"quelle": "ags", "laenge": 8, "stand": "gemeindestand"},
    "Kreis":    {"quelle": "rs",  "laenge": 5, "stand": "kreisstand"},
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("uebergaenge")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    jahrgang     SMALLINT NOT NULL,
    zeile        INTEGER  NOT NULL,
    teil         SMALLINT NOT NULL,
    ebene        TEXT     NOT NULL,
    wirksam      DATE     NOT NULL,
    art          TEXT     NOT NULL,
    kontinuitaet TEXT     NOT NULL,
    ags_alt      CHAR(8)  NOT NULL,
    rs_alt       TEXT,
    name_alt     TEXT,
    ags_neu      CHAR(8)  NOT NULL,
    rs_neu       TEXT,
    name_neu     TEXT,
    flaeche_qm   NUMERIC,
    einwohner    INTEGER,
    stand_davor  DATE,
    stand_danach DATE,
    herkunft     TEXT     NOT NULL,
    PRIMARY KEY (jahrgang, zeile, teil)
);

CREATE INDEX IF NOT EXISTS {TABELLE}_alt_idx ON {DB_SCHEMA}.{TABELLE} (ags_alt, wirksam);
CREATE INDEX IF NOT EXISTS {TABELLE}_neu_idx ON {DB_SCHEMA}.{TABELLE} (ags_neu, wirksam);
"""


def uebernahme(ebene):
    cfg   = EBENEN[ebene]
    q     = cfg["quelle"]
    n     = cfg["laenge"]
    stand = cfg["stand"]
    return f"""
DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE ebene = '{ebene}';

INSERT INTO {DB_SCHEMA}.{TABELLE}
    (jahrgang, zeile, teil, ebene, wirksam, art, kontinuitaet,
     ags_alt, rs_alt, name_alt, ags_neu, rs_neu, name_neu, flaeche_qm, einwohner,
     stand_davor, stand_danach, herkunft)
WITH gesplittet AS (
    SELECT r.jahrgang, r.zeile, c.teil::SMALLINT AS teil,
           trim(r.regionaleinheit) AS ebene, trim(c.code) AS code,
           to_date(r.datum_juristisch, 'DD.MM.YYYY') AS wirksam,
           left(trim(r.{q}_alt), {n}) AS ags_alt, nullif(trim(r.rs_alt), '') AS rs_alt,
           trim(r.name_alt) AS name_alt,
           left(trim(r.{q}_neu), {n}) AS ags_neu, nullif(trim(r.rs_neu), '') AS rs_neu,
           trim(r.name_neu) AS name_neu,
           nullif(trim(r.flaeche_qm), '')::NUMERIC AS flaeche_qm,
           nullif(trim(r.einwohner), '')::NUMERIC::INTEGER AS einwohner
    FROM roh_gemeinden.{ROH} r
    CROSS JOIN LATERAL unnest(
        string_to_array(replace(trim(r.aenderungsart), ' ', ''), ',')
    ) WITH ORDINALITY AS c(code, teil)
    WHERE trim(r.regionaleinheit) = '{ebene}'
      AND r.datum_juristisch ~ '^[0-9]{{2}}\\.[0-9]{{2}}\\.[0-9]{{4}}$'
      AND coalesce(trim(r.{q}_alt), '') <> ''
      AND coalesce(trim(r.{q}_neu), '') <> ''
      AND trim(c.code) <> ''
),
umgeben AS (
    SELECT g.*,
           (SELECT max(stichtag) FROM {DB_SCHEMA}.{stand} s WHERE s.stichtag <  g.wirksam) AS stand_davor,
           (SELECT min(stichtag) FROM {DB_SCHEMA}.{stand} s WHERE s.stichtag >= g.wirksam) AS stand_danach
    FROM gesplittet g
),
bewertet AS (
    SELECT u.*,
           CASE WHEN u.code = '1' AND u.stand_davor IS NOT NULL THEN
                EXISTS (SELECT 1 FROM {DB_SCHEMA}.{stand} s
                        WHERE s.ags = u.ags_neu AND s.stichtag = u.stand_davor)
           END AS ziel_bestand_schon
    FROM umgeben u
)
SELECT jahrgang, zeile, teil, ebene, wirksam,
       CASE code
         WHEN '1' THEN CASE ziel_bestand_schon
                         WHEN TRUE  THEN 'eingliederung'
                         WHEN FALSE THEN 'zusammenschluss'
                         ELSE            'aufloesung_unbestimmt' END
         WHEN '2' THEN 'teilausgliederung'
         WHEN '3' THEN 'schluesselaenderung'
         WHEN '4' THEN 'namensaenderung'
         ELSE          'unbekannt_' || code
       END,
       CASE code
         WHEN '1' THEN CASE ziel_bestand_schon
                         WHEN TRUE  THEN 'aufgegangen_in'
                         WHEN FALSE THEN 'hervorgegangen_aus'
                         ELSE            'unbestimmt' END
         WHEN '2' THEN 'flaechenwechsel'
         WHEN '3' THEN 'identisch'
         WHEN '4' THEN 'identisch'
         ELSE          'unbestimmt'
       END,
       ags_alt, rs_alt, name_alt, ags_neu, rs_neu, name_neu, flaeche_qm, einwohner,
       stand_davor, stand_danach,
       CASE WHEN code = '1'
            THEN 'abgeleitet: Ziel im {stand} vor dem Wirksamkeitsdatum vorhanden'
            ELSE 'quelle: Aenderungsart der Destatis-Datei' END
FROM bewertet;
"""


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    log.info("%-8s %-24s %-22s %8s", "Ebene", "Art", "Kontinuitaet", "Zeilen")
    for zeile in query(f"""
        SELECT ebene, art, kontinuitaet, count(*)
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC;
    """):
        log.info("%-8s %-24s %-22s %8s", *zeile)

    for ebene, cfg in EBENEN.items():
        q, stand = cfg["quelle"], cfg["stand"]


        verworfen = query(f"""
            SELECT count(*) FROM roh_gemeinden.{ROH}
            WHERE trim(regionaleinheit) = '{ebene}'
              AND (datum_juristisch !~ '^[0-9]{{2}}\\.[0-9]{{2}}\\.[0-9]{{4}}$'
                   OR coalesce(trim({q}_alt), '') = ''
                   OR coalesce(trim({q}_neu), '') = '');
        """)
        uebernommen = query(f"""
            SELECT count(*) FROM {DB_SCHEMA}.{TABELLE} WHERE ebene = '{ebene}';
        """)
        log.info("%s: %s Zeilen uebernommen, %s ohne Datum oder ohne %s",
                 ebene, uebernommen[0][0] if uebernommen else "?",
                 verworfen[0][0] if verworfen else "?", q)


        fehlend = query(f"""
            SELECT count(*) FROM {DB_SCHEMA}.{TABELLE} u
            WHERE u.ebene = '{ebene}' AND u.stand_danach IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{stand} s
                              WHERE s.ags = u.ags_neu
                                AND s.stichtag = u.stand_danach);
        """)
        log.info("%s: Ziel fehlt im %s danach: %s", ebene, stand,
                 fehlend[0][0] if fehlend else "?")

    log.info("--- Umbenennungen ohne Gebietsaenderung ---")
    for zeile in query(f"""
        SELECT ebene, count(*) FROM {DB_SCHEMA}.{TABELLE}
        WHERE ags_alt = ags_neu AND name_alt IS DISTINCT FROM name_neu
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    run_sql(DDL, "ddl")

    for ebene, cfg in EBENEN.items():
        stand = cfg["stand"]
        if not query(f"SELECT 1 FROM {DB_SCHEMA}.{stand} LIMIT 1;"):
            log.warning("%s.%s ist leer - Ebene %s uebersprungen",
                        DB_SCHEMA, stand, ebene)
            continue
        run_sql(uebernahme(ebene), f"uebergaenge {ebene}")

    report()


if __name__ == "__main__":
    main()
