import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query


import lieferung
LIEFERUNG = "wahlkreisebene_amtlich"

DB_SCHEMA = "wahlergebnisse"
T_ERG     = "wahlkreis_ergebnis"
T_KENN    = "wahlkreis_kennzahl"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wahlkreisergebnisse")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_ERG} (
    wahljahr  SMALLINT NOT NULL,
    wkr_nr    SMALLINT NOT NULL,
    stimme    TEXT     NOT NULL,
    partei    TEXT     NOT NULL,
    stimmen   BIGINT   NOT NULL,
    PRIMARY KEY (wahljahr, wkr_nr, stimme, partei)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_KENN} (
    wahljahr  SMALLINT NOT NULL,
    wkr_nr    SMALLINT NOT NULL,
    merkmal   TEXT     NOT NULL,
    wert      BIGINT,
    PRIMARY KEY (wahljahr, wkr_nr, merkmal)
);

CREATE INDEX IF NOT EXISTS {T_ERG}_wkr  ON {DB_SCHEMA}.{T_ERG} (wahljahr, wkr_nr);
CREATE INDEX IF NOT EXISTS {T_KENN}_wkr ON {DB_SCHEMA}.{T_KENN} (wahljahr, wkr_nr);
"""


SQL_ERGEBNIS = f"""
TRUNCATE {DB_SCHEMA}.{T_ERG};

INSERT INTO {DB_SCHEMA}.{T_ERG} (wahljahr, wkr_nr, stimme, partei, stimmen)
SELECT wahljahr, wkr_nr, stimme, partei, sum(stimmen)
FROM {DB_SCHEMA}.wahlbezirksergebnis
GROUP BY 1, 2, 3, 4;
"""


SQL_KENNZAHL = f"""
TRUNCATE {DB_SCHEMA}.{T_KENN};

INSERT INTO {DB_SCHEMA}.{T_KENN} (wahljahr, wkr_nr, merkmal, wert)
SELECT wahljahr, wkr_nr, merkmal, wert FROM (
    SELECT w.wahljahr, w.wkr_nr,
           sum(w.wahlberechtigte)  AS wahlberechtigte,
           sum(w.waehlende)        AS waehlende,
           sum(w.gueltig_erst)     AS gueltig_erst,
           sum(w.gueltig_zweit)    AS gueltig_zweit,
           sum(w.ungueltig_erst)   AS ungueltig_erst,
           sum(w.ungueltig_zweit)  AS ungueltig_zweit,
           count(*)                AS wahlbezirke
    FROM {DB_SCHEMA}.wahlbezirk w
    GROUP BY 1, 2
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
        SELECT wahljahr, count(DISTINCT wkr_nr) AS wahlkreise, count(*) AS zeilen
        FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Wahlkreise, %s Ergebniszeilen", *zeile)

    log.info("--- Gegenprobe 1: gegen GERDA, das bisher diese Ebene trug ---")
    for zeile in query(f"""
        SELECT e.wahljahr,
               to_char(sum(e.stimmen), 'FM999G999G999')  AS wir,
               to_char(g.summe, 'FM999G999G999')          AS gerda,
               sum(e.stimmen) - g.summe                   AS differenz
        FROM {DB_SCHEMA}.{T_ERG} e
        JOIN (SELECT wahljahr, sum(stimmen) AS summe
              FROM gerda.wahlergebnis_gerda_wahlkreis
              WHERE stimme = 'zweitstimme' GROUP BY 1) g USING (wahljahr)
        WHERE e.stimme = 'zweitstimme'
        GROUP BY e.wahljahr, g.summe ORDER BY 1;
    """):
        log.info("  %s: Zweitstimmen %s gegen %s, Differenz %s", *zeile)

    log.info("--- Gegenprobe 2: derselbe Wahlkreis ueber die Raumzuordnung ---")
    log.info("  (kleinst_100_geteilt fuer die geteilten Staedte, sonst ueber " "gemeinde_wahlkreis)")
    for zeile in query(f"""
        WITH ueber_raum AS (

            SELECT t.wahljahr, t.wkr_nr, sum(g.stimmen) AS stimmen
            FROM {DB_SCHEMA}.kleinst_100_geteilt_ergebnis g
            JOIN raum.kleinst_100_geteilt t
              ON (t.wahljahr, t.einheit_id) = (g.wahljahr, g.einheit_id)
            WHERE g.stimme = 'zweitstimme'
            GROUP BY 1, 2
            UNION ALL

            SELECT m.wahljahr, m.wkr_nr, sum(a.stimmen)
            FROM {DB_SCHEMA}.kleinst_100_amtlich_ergebnis a
            JOIN (SELECT DISTINCT wahljahr, einheit_id, wkr_nr
                  FROM raum.gemeinde_kleinst_100 WHERE bestand = 'amtlich') m
              ON (m.wahljahr, m.einheit_id) = (a.wahljahr, a.einheit_id)
            WHERE a.stimme = 'zweitstimme'
            GROUP BY 1, 2
        )
        SELECT d.wahljahr,
               to_char(sum(d.direkt), 'FM999G999G999')  AS direkt,
               to_char(sum(d.raum), 'FM999G999G999')    AS ueber_raum,
               sum(d.direkt) - sum(d.raum)              AS differenz
        FROM (
            SELECT e.wahljahr, e.wkr_nr, sum(e.stimmen) AS direkt,
                   coalesce((SELECT sum(r.stimmen) FROM ueber_raum r
                             WHERE (r.wahljahr, r.wkr_nr) = (e.wahljahr, e.wkr_nr)), 0)
                   AS raum
            FROM {DB_SCHEMA}.{T_ERG} e
            WHERE e.stimme = 'zweitstimme'
            GROUP BY 1, 2
        ) d
        GROUP BY d.wahljahr ORDER BY 1;
    """):
        log.info("  %s: direkt %s, ueber Raum %s, Differenz %s", *zeile)

    log.info("--- Hat jeder Wahlkreis des Raums ein Ergebnis? ---")
    for zeile in query(f"""
        SELECT w.wahljahr, count(*) AS im_raum,
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM {DB_SCHEMA}.{T_ERG} e
                   WHERE (e.wahljahr, e.wkr_nr) = (w.wahljahr, w.wkr_nr))) AS mit_ergebnis
        FROM raum.wahlkreis w GROUP BY 1 ORDER BY 1;
    """):
        jahr, raum, erg = zeile
        marke = "ok" if raum == erg else f"FEHLEN {int(raum) - int(erg)}"
        log.info("  %s: %s Wahlkreise im Raum, %s mit Ergebnis  %s", jahr, raum, erg, marke)


def main():
    lieferung.merke(LIEFERUNG)
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{T_ERG} CASCADE;"
                f"DROP TABLE IF EXISTS {DB_SCHEMA}.{T_KENN} CASCADE;",
                "tabellen verwerfen")
        log.warning("Tabellen %s und %s verworfen.", T_ERG, T_KENN)

    if not query(f"SELECT 1 FROM {DB_SCHEMA}.wahlbezirk LIMIT 1;"):
        raise SystemExit(f"{DB_SCHEMA}.wahlbezirk ist leer - erst load_wahlbezirke.py")

    run_sql(DDL, "ddl")
    run_sql(SQL_ERGEBNIS, T_ERG)
    run_sql(SQL_KENNZAHL, T_KENN)
    report()


if __name__ == "__main__":
    main()
