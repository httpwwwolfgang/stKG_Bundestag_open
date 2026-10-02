import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import run_sql, query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SCHEMA = "raum"
TABELLE = "gemeinde_wahlkreis_wahltag"
HERKUNFT = "eingriff_vg1000"
WAHLTAG_2013 = "2013-09-22"


FAELLE = [
    ("03457501", "Insel Lütje Hörn", 25),
    ("03151501", "Giebel",           51),
    ("08317971", "Rheinau",          283),
]


def setze():
    werte = ",\n           ".join(
        f"('{ags}', {wkr})" for ags, _, wkr in FAELLE
    )
    run_sql(f"""



    DELETE FROM {SCHEMA}.{TABELLE}
     WHERE wahljahr = 2013
       AND ags IN ({", ".join(f"'{a}'" for a, _, _ in FAELLE)});

    INSERT INTO {SCHEMA}.{TABELLE}
        (wahljahr, wahltag, ags, gemeindename, wkr_nr, anteilig, herkunft,
         unsicher)
    SELECT 2013, DATE '{WAHLTAG_2013}', v.ags, g.gen, v.wkr, false,
           '{HERKUNFT}', false
      FROM (VALUES
           {werte}
           ) AS v(ags, wkr)
      JOIN {SCHEMA}.gemeindestand_stichtag g
        ON g.ags = v.ags AND g.stichtag = DATE '{WAHLTAG_2013}';
    """, "Eingriffe gemeindefrei 2013")


def report():
    log.info("--- die drei gesetzten Zeilen ---")
    for zeile in query(f"""
        SELECT ags, coalesce(gemeindename, '-'), wkr_nr, herkunft
          FROM {SCHEMA}.{TABELLE}
         WHERE wahljahr = 2013 AND herkunft = '{HERKUNFT}'
         ORDER BY ags;
    """):
        log.info("  %s %-24s WK %s  (%s)", *zeile)

    log.info("--- deckt sich die Zuordnung jetzt mit dem Gebietsstand? ---")
    for zeile in query(f"""
        SELECT s.stichtag,
               count(DISTINCT s.ags) AS gebiete,
               count(DISTINCT z.ags) AS zugeordnet
          FROM {SCHEMA}.gemeindestand_stichtag s
          LEFT JOIN {SCHEMA}.{TABELLE} z
                 ON z.ags = s.ags AND z.wahljahr = 2013
         WHERE s.stichtag = DATE '{WAHLTAG_2013}'
         GROUP BY 1;
    """):
        stichtag, gebiete, zugeordnet = zeile
        fehlt = int(gebiete) - int(zugeordnet)
        log.info("  %s: %s Gebiete, %s zugeordnet, %s ohne Zuordnung",
                 stichtag, gebiete, zugeordnet, fehlt)


if __name__ == "__main__":
    setze()
    report()
