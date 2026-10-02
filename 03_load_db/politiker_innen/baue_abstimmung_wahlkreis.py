import logging
import sys
import tempfile
from pathlib import Path

import psycopg2
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn

DSN = dsn()
AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("abstimmung-wahlkreis")


DDL = f"""
SET client_min_messages TO WARNING;
DROP VIEW IF EXISTS {AW}.abstimmung_wahlkreis;
DROP VIEW IF EXISTS {AW}.abstimmung_ohne_wahlkreis;
DROP MATERIALIZED VIEW IF EXISTS {AW}.abstimmung_wahlkreis_stat;

CREATE MATERIALIZED VIEW {AW}.abstimmung_wahlkreis_stat AS
WITH nummer AS (


  SELECT datei, datum, titel,
         dense_rank() OVER (ORDER BY datum, datei) AS abstimmung_nr
    FROM {AW}.abstimmung_bt),
partei AS (

  SELECT m.aw_id AS mandat_id, max(k.party_label) AS partei
    FROM {AW}.candidacy_mandate m
    LEFT JOIN {AW}.candidacy_mandate k
           ON k.type = 'candidacy' AND k.politician_id = m.politician_id
          AND k.parliament_period_label = CASE m.parliament_period_label
                WHEN 'Bundestag 2013 - 2017' THEN 'Bundestag Wahl 2013'
                WHEN 'Bundestag 2017 - 2021' THEN 'Bundestag Wahl 2017'
                WHEN 'Bundestag 2021 - 2025' THEN 'Bundestag Wahl 2021' END
   WHERE m.type = 'mandate'
   GROUP BY m.aw_id),
stimmen AS (


  SELECT s.datei, s.mandat_id, s.stimme, n.datum, n.abstimmung_nr, n.titel,
         f.fraktion
    FROM {AW}.stimme_bt s
    JOIN nummer n ON n.datei = s.datei
    LEFT JOIN {AW}.fraktion_mitgliedschaft f
           ON f.mandat_id = s.mandat_id AND f.zeitraum @> n.datum
   WHERE s.mandat_id IS NOT NULL)
SELECT (s.abstimmung_nr::bigint * 1000) + m.wkr_nr        AS id,
       s.abstimmung_nr,
       s.datei,
       s.titel                                            AS abstimmung,
       s.datum,
       m.parliament_period_label                          AS legislatur,
       w.wahlperiode,
       m.wkr_nr,
       w.wkr_name,
       w.land_name,
       count(*)                                                    AS n_gesamt,
       count(*) FILTER (WHERE s.stimme = 'ja')                     AS n_ja,
       count(*) FILTER (WHERE s.stimme = 'nein')                   AS n_nein,
       count(*) FILTER (WHERE s.stimme = 'enthaltung')             AS n_enthaltung,
       count(*) FILTER (WHERE s.stimme = 'ungueltig')              AS n_ungueltig,
       count(*) FILTER (WHERE s.stimme = 'nicht_abgegeben')        AS n_nicht_abgegeben,
       round(100.0 * count(*) FILTER (WHERE s.stimme = 'ja')
             / nullif(count(*) FILTER (WHERE s.stimme IN
                      ('ja','nein','enthaltung','ungueltig')), 0), 1) AS anteil_ja,
       max(m.politician_label) FILTER (WHERE m.mandatsart = 'constituency') AS direktmandat,
       max(s.fraktion)         FILTER (WHERE m.mandatsart = 'constituency') AS fraktion_direktmandat,
       max(pa.partei)          FILTER (WHERE m.mandatsart = 'constituency') AS partei_direktmandat,
       max(s.stimme)           FILTER (WHERE m.mandatsart = 'constituency') AS stimme_direktmandat,
       max(m.constituency_result) FILTER (WHERE m.mandatsart = 'constituency') AS erststimmen_direktmandat,
       string_agg(DISTINCT s.fraktion, ', ') FILTER (WHERE s.stimme = 'ja')   AS fraktionen_ja,
       string_agg(DISTINCT s.fraktion, ', ') FILTER (WHERE s.stimme = 'nein') AS fraktionen_nein,
       string_agg(DISTINCT s.fraktion, ', ') FILTER (WHERE s.stimme = 'enthaltung') AS fraktionen_enthaltung,
       string_agg(DISTINCT s.fraktion, ', ') FILTER (WHERE s.stimme = 'nicht_abgegeben') AS fraktionen_nicht_abgegeben,
       count(*) FILTER (WHERE m.wahlkreisbezug = 'direktmandat')         AS n_direktmandat,
       count(*) FILTER (WHERE m.wahlkreisbezug = 'wahlkreiskandidatur')  AS n_wahlkreiskandidatur,
       count(*) FILTER (WHERE m.wahlkreisbezug = 'direktmandat'
                          AND s.stimme = 'ja')                          AS n_ja_direktmandat,
       count(*) FILTER (WHERE m.wahlkreisbezug = 'wahlkreiskandidatur'
                          AND s.stimme = 'ja')                          AS n_ja_wahlkreiskandidatur,
       string_agg(m.politician_label || ' [' || coalesce(s.fraktion, '?')
                  || '/' || coalesce(pa.partei, '?') || ', '






                  || CASE WHEN m.mandatsart = 'constituency' THEN 'direkt'
                          WHEN m.mandate_won = 'moved_up' THEN 'nachgerueckt'
                          ELSE 'Liste' END
                  || ']: ' || s.stimme, ' | '
                  ORDER BY m.mandatsart, m.politician_label)            AS wer_wie
  FROM stimmen s
  JOIN {AW}.candidacy_mandate m ON m.aw_id = s.mandat_id AND m.type = 'mandate'
  LEFT JOIN partei pa ON pa.mandat_id = m.aw_id
  JOIN raum.wahlkreis w ON w.wkr_nr = m.wkr_nr
       AND w.wahlperiode = CASE m.parliament_period_label
             WHEN 'Bundestag 2013 - 2017' THEN 18
             WHEN 'Bundestag 2017 - 2021' THEN 19
             WHEN 'Bundestag 2021 - 2025' THEN 20 END
 WHERE m.wkr_nr IS NOT NULL
 GROUP BY s.abstimmung_nr, s.datei, s.titel, s.datum, m.parliament_period_label,
          w.wahlperiode, m.wkr_nr, w.wkr_name, w.land_name;

CREATE UNIQUE INDEX ON {AW}.abstimmung_wahlkreis_stat (id);
CREATE INDEX ON {AW}.abstimmung_wahlkreis_stat (datei);
CREATE INDEX ON {AW}.abstimmung_wahlkreis_stat (wahlperiode, wkr_nr);

CREATE VIEW {AW}.abstimmung_wahlkreis AS
SELECT s.*, w.geom
  FROM {AW}.abstimmung_wahlkreis_stat s
  JOIN raum.wahlkreis w ON w.wkr_nr = s.wkr_nr AND w.wahlperiode = s.wahlperiode;

CREATE VIEW {AW}.abstimmung_ohne_wahlkreis AS
SELECT s.datei, a.titel AS abstimmung, a.datum,
       m.parliament_period_label AS legislatur,
       count(*) AS stimmen_ohne_wahlkreis,
       count(*) FILTER (WHERE s.stimme = 'ja')   AS n_ja,
       count(*) FILTER (WHERE s.stimme = 'nein') AS n_nein
  FROM {AW}.stimme_bt s
  JOIN {AW}.candidacy_mandate m ON m.aw_id = s.mandat_id AND m.type = 'mandate'
  JOIN {AW}.abstimmung_bt a ON a.datei = s.datei
 WHERE m.wkr_nr IS NULL
 GROUP BY 1, 2, 3, 4;

COMMENT ON MATERIALIZED VIEW {AW}.abstimmung_wahlkreis_stat IS
 'Je namentlicher Abstimmung und Wahlkreis aggregiert - fuer QGIS. Seit dem '
 '30.08.2026 auf dem Bundestagsbestand (642 Abstimmungen, 443.382 Stimmen) '
 'statt auf abgeordnetenwatch (459 / 319.903). Gezaehlt werden ALLE an diesem '
 'Wahlkreis verankerten Abgeordneten, nicht nur der Direktgewaehlte.';
COMMENT ON COLUMN {AW}.abstimmung_wahlkreis_stat.abstimmung_nr IS
 'Laufende Nummer 1 bis 642 nach Datum, damit QGIS eine ganze Zahl hat. KEINE '
 'amtliche Kennung - der Schluessel des Bestands ist datei.';
COMMENT ON COLUMN {AW}.abstimmung_wahlkreis_stat.fraktion_direktmandat IS
 'Fraktion ZUM ABSTIMMUNGSTAG, aus fraktion_mitgliedschaft - nicht die '
 'uneinheitliche Schreibweise der Excel und nicht der Endzustand.';
"""


def main():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*), count(DISTINCT datei), count(DISTINCT wkr_nr) "
                    f"FROM {AW}.abstimmung_wahlkreis_stat;")
        n, abst, wkr = cur.fetchone()
        log.info("--- abstimmung_wahlkreis_stat ---")
        log.info("   %d Zeilen, %d Abstimmungen, %d verschiedene Wahlkreisnummern",
                 n, abst, wkr)
        cur.execute(f"""SELECT wahlperiode, count(DISTINCT datei), count(*)
                          FROM {AW}.abstimmung_wahlkreis_stat
                         GROUP BY 1 ORDER BY 1;""")
        for wp, a, z in cur.fetchall():
            log.info("   WP %d: %3d Abstimmungen, %6d Zeilen", wp, a, z)

        cur.execute(f"""SELECT count(*) FROM {AW}.abstimmung_wahlkreis_stat
                         WHERE fraktion_direktmandat IS NULL AND direktmandat IS NOT NULL;""")
        log.info("   %d Zeilen mit Direktmandat, aber ohne Fraktion am Abstimmungstag",
                 cur.fetchone()[0])

        cur.execute(f"""SELECT sum(n_gesamt) FROM {AW}.abstimmung_wahlkreis_stat;""")
        auf_karte = cur.fetchone()[0]
        cur.execute(f"""SELECT count(*) FROM {AW}.stimme_bt WHERE mandat_id IS NOT NULL;""")
        gesamt = cur.fetchone()[0]
        log.info("--- Gegenprobe ---")
        log.info("   %d von %d Stimmen liegen auf der Karte, %d ohne Wahlkreis",
                 auf_karte, gesamt, gesamt - auf_karte)
        cur.execute(f"SELECT count(*) FROM {AW}.abstimmung_wahlkreis;")
        log.info("   Sicht mit Geometrie: %d Zeilen", cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
