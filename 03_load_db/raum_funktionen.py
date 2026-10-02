import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from db import run_sql, query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("raum-funktionen")


SQL = """
CREATE OR REPLACE FUNCTION raum.ist_sammelposten(p_ags CHAR(8))
RETURNS BOOLEAN
LANGUAGE sql
STABLE
PARALLEL SAFE

AS $$
    SELECT substr(p_ags, 6, 3) ~ '^9'
       AND NOT EXISTS (SELECT 1 FROM raum.gemeindestand g WHERE g.ags = p_ags);
$$;

COMMENT ON FUNCTION raum.ist_sammelposten(CHAR) IS
  'true fuer Briefwahl-Sammelposten (erfundene 9xx-Nummer ohne Gebiet). '
  'Echte gemeindefreie Gebiete mit 9xx-Schluessel liefern false.';


CREATE OR REPLACE FUNCTION raum.gemeinde_ags(p_ags CHAR(8))
RETURNS CHAR(8)
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT (CASE
        WHEN left(p_ags, 2) = '11' THEN '11000000'
        WHEN left(p_ags, 2) = '02' THEN '02000000'
        WHEN p_ags = '15085255'    THEN '15085040'
        ELSE p_ags
    END)::CHAR(8);
$$;

COMMENT ON FUNCTION raum.gemeinde_ags(CHAR) IS
  'Hebt einen Schluessel der Wahlbezirksstatistik auf die Gemeinde des '
  'Gebietsstands: Berliner und Hamburger Bezirke auf ihre Stadt (Bremen '
  'nicht - zwei eigenstaendige Gemeinden), Rieder 2013 auf Ballenstedt. '
  'Abschliessende Aufzaehlung, keine Regel - neue Faelle werden entschieden '
  'und hier ergaenzt.';
"""


def report():
    log.info("--- Funktionen im Schema raum ---")
    for zeile in query("""
        SELECT p.proname, pg_get_function_arguments(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'raum' AND p.proname IN
              ('ist_sammelposten', 'gemeinde_ags')
        ORDER BY 1;
    """):
        log.info("  raum.%s(%s)", *zeile)

    log.info("--- Probe: was hebt gemeinde_ags? ---")
    for zeile in query("""
        SELECT v.ags, raum.gemeinde_ags(v.ags), v.was
        FROM (VALUES ('11103000'::CHAR(8), 'Berlin-Pankow'),
                     ('02000000',          'Hamburg'),
                     ('04011000',          'Bremen - bleibt'),
                     ('15085255',          'Rieder 2013'),
                     ('07131003',          'Altenahr - bleibt')
             ) AS v(ags, was)
        ORDER BY 1;
    """):
        pfeil = "->" if zeile[0] != zeile[1] else " "
        log.info("  %s %s %s   (%s)", zeile[0], pfeil, zeile[1], zeile[2])

    log.info("--- Wie viele Wahlbezirks-Schluessel werden gehoben? ---")
    for zeile in query("""
        SELECT wahljahr, count(DISTINCT ags)
        FROM wahlergebnisse.wahlbezirk
        WHERE raum.gemeinde_ags(ags) <> ags
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Schluessel", *zeile)


def main():
    run_sql(SQL, "raum-funktionen")
    report()


if __name__ == "__main__":
    main()
