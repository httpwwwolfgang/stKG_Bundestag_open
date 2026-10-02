import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "wahlergebnisse"
T_ERG     = "kreis_ergebnis"
T_KENN    = "kreis_kennzahl"


KREIS = """CASE left(w.ags, 2) WHEN '11' THEN '11000'
                              WHEN '02' THEN '02000'
                              ELSE left(w.ags, 5) END"""

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kreisergebnisse")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_ERG} (
    wahljahr  SMALLINT NOT NULL,
    kreis     CHAR(5)  NOT NULL,
    wkr_nr    SMALLINT NOT NULL,
    stimme    TEXT     NOT NULL,
    partei    TEXT     NOT NULL,
    stimmen   BIGINT   NOT NULL,
    PRIMARY KEY (wahljahr, kreis, wkr_nr, stimme, partei)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_KENN} (
    wahljahr  SMALLINT NOT NULL,
    kreis     CHAR(5)  NOT NULL,
    wkr_nr    SMALLINT NOT NULL,
    merkmal   TEXT     NOT NULL,
    wert      BIGINT,
    PRIMARY KEY (wahljahr, kreis, wkr_nr, merkmal)
);

CREATE INDEX IF NOT EXISTS {T_ERG}_kreis  ON {DB_SCHEMA}.{T_ERG} (wahljahr, kreis);
CREATE INDEX IF NOT EXISTS {T_KENN}_kreis ON {DB_SCHEMA}.{T_KENN} (wahljahr, kreis);
"""


SQL_ERGEBNIS = f"""
TRUNCATE {DB_SCHEMA}.{T_ERG};

INSERT INTO {DB_SCHEMA}.{T_ERG} (wahljahr, kreis, wkr_nr, stimme, partei, stimmen)
SELECT e.wahljahr,
       CASE left(e.ags, 2) WHEN '11' THEN '11000'
                           WHEN '02' THEN '02000'
                           ELSE left(e.ags, 5) END AS kreis,
       e.wkr_nr, e.stimme, e.partei, sum(e.stimmen)
FROM {DB_SCHEMA}.wahlbezirksergebnis e
GROUP BY 1, 2, 3, 4, 5;
"""


SQL_KENNZAHL = f"""
TRUNCATE {DB_SCHEMA}.{T_KENN};

INSERT INTO {DB_SCHEMA}.{T_KENN} (wahljahr, kreis, wkr_nr, merkmal, wert)
SELECT wahljahr, kreis, wkr_nr, merkmal, wert FROM (
    SELECT w.wahljahr, {KREIS} AS kreis, w.wkr_nr,
           sum(w.wahlberechtigte)  AS wahlberechtigte,
           sum(w.waehlende)        AS waehlende,
           sum(w.gueltig_erst)     AS gueltig_erst,
           sum(w.gueltig_zweit)    AS gueltig_zweit,
           sum(w.ungueltig_erst)   AS ungueltig_erst,
           sum(w.ungueltig_zweit)  AS ungueltig_zweit,
           count(*)                AS wahlbezirke
    FROM {DB_SCHEMA}.wahlbezirk w
    GROUP BY 1, 2, 3
) s
CROSS JOIN LATERAL (VALUES
    ('wahlberechtigte', s.wahlberechtigte),
    ('waehlende',       s.waehlende),
    ('gueltig_erst',    s.gueltig_erst),
    ('gueltig_zweit',   s.gueltig_zweit),
    ('ungueltig_erst',  s.ungueltig_erst),
    ('ungueltig_zweit', s.ungueltig_zweit),
    ('wahlbezirke',     s.wahlbezirke)
) AS v(merkmal, wert)
WHERE v.wert IS NOT NULL;
"""


def report():
    log.info("--- %s.%s und .%s ---", DB_SCHEMA, T_ERG, T_KENN)
    for zeile in query(f"""
        SELECT wahljahr, count(DISTINCT kreis) AS kreise,
               count(DISTINCT (kreis, wkr_nr)) AS kreisteile, count(*) AS zeilen
        FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Kreise in %s Kreisteilen, %s Ergebniszeilen", *zeile)

    log.info("--- Deckt sich die Kreismenge mit raum.kreisstand_stichtag? ---")
    for zeile in query(f"""
        SELECT z.jahr, z.n_stand, e.n_erg, e.n_erg - z.n_stand AS differenz
        FROM (SELECT substring(s.bezug from '[0-9]+')::int AS jahr, count(*) AS n_stand
              FROM zeit.stichtag s JOIN raum.kreisstand_stichtag k ON k.stichtag = s.datum
              WHERE s.art = 'wahltag' GROUP BY 1) z
        JOIN (SELECT wahljahr, count(DISTINCT kreis) AS n_erg
              FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1) e ON e.wahljahr = z.jahr
        ORDER BY 1;
    """):
        jahr, stand, erg, diff = zeile
        marke = "ok" if int(diff) == 0 else f"ABWEICHUNG {diff}"
        log.info("  %s: Gebietsstand %s, Ergebnisse %s  %s", jahr, stand, erg, marke)

    log.info("--- Gegenprobe: Summe gegen die Wahlbezirksebene ---")
    for zeile in query(f"""
        SELECT k.wahljahr,
               to_char(k.summe, 'FM999G999G999')  AS ueber_kreise,
               to_char(w.summe, 'FM999G999G999')  AS ueber_bezirke,
               k.summe - w.summe                  AS differenz
        FROM (SELECT wahljahr, sum(wert) AS summe FROM {DB_SCHEMA}.{T_KENN}
              WHERE merkmal = 'wahlberechtigte' GROUP BY 1) k
        JOIN (SELECT wahljahr, sum(wahlberechtigte) AS summe
              FROM {DB_SCHEMA}.wahlbezirk GROUP BY 1) w USING (wahljahr)
        ORDER BY 1;
    """):
        log.info("  %s: Wahlberechtigte %s ueber Kreise, %s ueber Bezirke, " "Differenz %s", *zeile)

    log.info("--- Deckt sich die Kreisteilung mit raum.kreis_wahlkreis? ---")
    for zeile in query(f"""
        SELECT e.wahljahr, e.n AS aus_ergebnissen, r.n AS aus_dem_raum,
               e.n - r.n AS differenz
        FROM (SELECT wahljahr, count(DISTINCT (kreis, wkr_nr)) AS n
              FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1) e
        JOIN (SELECT wahljahr, count(*) AS n
              FROM raum.kreis_wahlkreis GROUP BY 1) r USING (wahljahr)
        ORDER BY 1;
    """):
        jahr, erg, raum, diff = zeile
        marke = "ok" if int(diff) == 0 else f"ABWEICHUNG {diff}"
        log.info("  %s: %s Kreisteile aus Ergebnissen, %s aus dem Raum  %s",
                 jahr, erg, raum, marke)

    log.info("--- Die groessten Kreise nach gueltigen Zweitstimmen (2021) ---")
    for zeile in query(f"""
        SELECT e.kreis, coalesce(max(k.gen), '?') AS name,
               to_char(sum(e.stimmen), 'FM999G999G999') AS stimmen
        FROM {DB_SCHEMA}.{T_ERG} e
        LEFT JOIN raum.kreisstand_stichtag k
          ON k.stichtag = DATE '2021-09-26' AND k.ags = e.kreis
        WHERE e.wahljahr = 2021 AND e.stimme = 'zweitstimme'
        GROUP BY e.kreis ORDER BY sum(e.stimmen) DESC LIMIT 5;

    """):
        log.info("  %s %-24s %s", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{T_ERG} CASCADE;"
                f"DROP TABLE IF EXISTS {DB_SCHEMA}.{T_KENN} CASCADE;",
                "tabellen verwerfen")
        log.warning("Tabellen %s und %s verworfen.", T_ERG, T_KENN)

    if not query(f"SELECT 1 FROM {DB_SCHEMA}.wahlbezirk LIMIT 1;"):
        raise SystemExit(f"{DB_SCHEMA}.wahlbezirk ist leer - erst load_wahlbezirke.py")

    run_sql(DDL, "ddl")
    run_sql(SQL_ERGEBNIS, "kreis_ergebnis")
    run_sql(SQL_KENNZAHL, "kreis_kennzahl")
    report()


if __name__ == "__main__":
    main()
