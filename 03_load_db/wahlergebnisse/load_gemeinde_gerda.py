import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "raum"
TABELLE   = "gemeinde_gerda"


VARIANTEN = [
    ("unharm",  "gerda.gemeinde_gerda_unharm",  None),
    ("harm_21", "gerda.gemeinde_gerda_harm21",  2021),
    ("raw",     "gerda.gemeindeeinheit_gerda",  None),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemeinde-gerda")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    wahljahr  SMALLINT NOT NULL,
    variante  TEXT     NOT NULL,
    gerda_ags CHAR(8)  NOT NULL,
    ags       CHAR(8),

    herkunft  TEXT     NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS {TABELLE}_pk
    ON {DB_SCHEMA}.{TABELLE} (wahljahr, variante, gerda_ags, coalesce(ags, ''));

CREATE INDEX IF NOT EXISTS {TABELLE}_ags
    ON {DB_SCHEMA}.{TABELLE} (wahljahr, ags);
CREATE INDEX IF NOT EXISTS {TABELLE}_gerda
    ON {DB_SCHEMA}.{TABELLE} (wahljahr, variante, gerda_ags);

COMMENT ON TABLE {DB_SCHEMA}.{TABELLE} IS
  'Bindet GERDA-Schluessel an Gemeinden des Wahltagsstands. Eine Zeile je '
  'Paar - ein GERDA-Objekt kann mehrere Gemeinden treffen (Langelsheim 2021) '
  'oder keine (Briefwahl-Sammelposten).';
"""


def lade(variante, quelle, bezugsjahr=None):
    bezug = (f"zt.bezug = 'Wahl {bezugsjahr}'" if bezugsjahr
             else "zt.bezug = 'Wahl ' || g.wahljahr::text")


    a_jahr = str(bezugsjahr) if bezugsjahr else "g.wahljahr" 
    run_sql(f"""
    DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE variante = '{variante}';



    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (wahljahr, variante, gerda_ags, ags, herkunft)
    SELECT DISTINCT g.wahljahr, '{variante}', g.ags, NULL, 'ohne_gebiet'
    FROM {quelle} g
    WHERE raum.ist_sammelposten(g.ags)
    ON CONFLICT DO NOTHING;




    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (wahljahr, variante, gerda_ags, ags, herkunft)
    SELECT DISTINCT g.wahljahr, '{variante}', g.ags, a.ags, 'aufgeteilt'
    FROM {quelle} g
    JOIN zeit.stichtag zt
      ON zt.art = 'wahltag' AND {bezug}
    JOIN {DB_SCHEMA}.gemeinde_aufnahme a
      ON a.wahljahr = {a_jahr} AND a.ags_aufnehmend = g.ags
    WHERE NOT raum.ist_sammelposten(g.ags)


      AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeindestand_stichtag s
                      WHERE s.stichtag = zt.datum
                        AND s.ags = raum.gemeinde_ags(g.ags))
    ON CONFLICT DO NOTHING;


    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (wahljahr, variante, gerda_ags, ags, herkunft)
    SELECT DISTINCT g.wahljahr, '{variante}', g.ags, raum.gemeinde_ags(g.ags),
           CASE WHEN g.ags = raum.gemeinde_ags(g.ags) THEN 'identisch'
                ELSE 'gehoben' END
    FROM {quelle} g
    JOIN zeit.stichtag zt
      ON zt.art = 'wahltag' AND {bezug}
    JOIN {DB_SCHEMA}.gemeindestand_stichtag s
      ON s.stichtag = zt.datum AND s.ags = raum.gemeinde_ags(g.ags)
    WHERE NOT raum.ist_sammelposten(g.ags)
    ON CONFLICT DO NOTHING;
    """, f"gemeinde_gerda {variante}")


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT variante, wahljahr, herkunft, count(*) AS zeilen,
               count(DISTINCT gerda_ags) AS objekte
        FROM {DB_SCHEMA}.{TABELLE}
        GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC;
    """):
        log.info("  %-8s %s %-12s %6s Zeilen, %6s GERDA-Objekte", *zeile)

    log.info("--- Trifft jedes GERDA-Objekt ein Ziel? ---")
    for zeile in query(f"""
        SELECT variante, wahljahr,
               count(DISTINCT gerda_ags) AS objekte,
               count(DISTINCT gerda_ags) FILTER (WHERE ags IS NULL) AS ohne_ziel
        FROM {DB_SCHEMA}.{TABELLE}
        GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        variante, jahr, objekte, ohne = zeile
        log.info("  %-8s %s: %6s Objekte, %s ohne Ziel (Sammelposten)",
                 variante, jahr, objekte, ohne)


    log.info("--- Fehlt ein Schluessel der Quelle? ---")
    for variante, quelle, _ in VARIANTEN:
        for zeile in query(f"""
            SELECT g.wahljahr, count(DISTINCT g.ags)
            FROM {quelle} g
            WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} z
                              WHERE z.wahljahr = g.wahljahr
                                AND z.variante = '{variante}'
                                AND z.gerda_ags = g.ags)
            GROUP BY 1 ORDER BY 1;
        """):
            log.warning("  %-8s %s: %s Schluessel NICHT gebunden",
                        variante, *zeile)
    log.info("  (keine Zeile darueber = jeder Schluessel ist gebunden)")

    log.info("--- Die Sonderfaelle im Klartext ---")
    for zeile in query(f"""
        SELECT variante, wahljahr, gerda_ags, coalesce(ags, '-'), herkunft
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE herkunft IN ('gehoben', 'aufgeteilt')
        ORDER BY wahljahr, gerda_ags, variante LIMIT 25;
    """):
        log.info("  %-8s %s  %s -> %s  (%s)", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    run_sql(DDL, "ddl")
    for variante, quelle, bezugsjahr in VARIANTEN:
        log.info("%s aus %s (Gebietsstand: %s) ...", variante, quelle,
                 bezugsjahr or "Wahltag des Jahres")
        lade(variante, quelle, bezugsjahr)
    report()


if __name__ == "__main__":
    main()
