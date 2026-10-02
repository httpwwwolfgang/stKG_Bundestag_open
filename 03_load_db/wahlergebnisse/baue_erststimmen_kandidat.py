import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql_file, query

WE = "wahlergebnisse"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("erststimmen-kandidat")


SQL = f"""
SET client_min_messages TO WARNING;
DROP VIEW IF EXISTS {WE}.erststimmen_kandidat_klein;
DROP VIEW IF EXISTS {WE}.erststimmen_kandidat;

CREATE VIEW {WE}.erststimmen_kandidat AS
SELECT k.aw_id                AS kandidatur_id,
       k.politician_id,
       k.politician_label,
       k.party_label          AS partei_aw,
       e.partei               AS partei_amtlich,
       mp.partei              AS partei_schluessel,
       e.wahljahr,
       e.wkr_nr,
       k.wkr_name,
       e.stimmen,
       round(100.0 * e.stimmen / sum(e.stimmen) OVER (PARTITION BY e.wahljahr, e.wkr_nr), 1)
                              AS anteil,
       rank() OVER (PARTITION BY e.wahljahr, e.wkr_nr ORDER BY e.stimmen DESC)
                              AS rang,
       k.erststimmen_anteil   AS anteil_aw,
       k.liste_id,
       k.listenplatz,
       k.mandat_id,
       k.gewaehlt
  FROM {WE}.wahlkreis_ergebnis e
  JOIN meta.partei_mapping ma
    ON ma.partei_roh = e.partei AND NOT ma.lieferung_ids @> ARRAY['aw_api_v2']
  JOIN meta.partei_mapping mp
    ON mp.partei = ma.partei AND mp.lieferung_ids @> ARRAY['aw_api_v2']
  JOIN politiker_innen.kandidatur k
    ON k.party_label = mp.partei_roh
   AND k.wkr_nr = e.wkr_nr
   AND substring(k.wahl from '[0-9]{{4}}')::int = e.wahljahr
 WHERE e.stimme = 'erststimme';

CREATE VIEW {WE}.erststimmen_kandidat_klein AS
WITH einheit AS (
    SELECT wahljahr, einheit_id,
           min(wkr_nr)                                AS wkr_nr,
           count(*) FILTER (WHERE rolle = 'gemeinde') AS gemeinden
      FROM raum.gemeinde_kleinst_100 GROUP BY 1, 2
),
ergebnis AS (
    SELECT e.wahljahr, e.einheit_id, ei.wkr_nr, e.partei, e.stimmen,
           'amtlich'::text AS bestand, ei.gemeinden
      FROM {WE}.kleinst_100_amtlich_ergebnis e
      JOIN einheit ei ON ei.wahljahr = e.wahljahr AND ei.einheit_id = e.einheit_id
     WHERE e.stimme = 'erststimme'
    UNION ALL
    SELECT e.wahljahr, e.einheit_id, e.wkr_nr, e.partei, e.stimmen,
           'geteilt'::text, 1
      FROM {WE}.kleinst_100_geteilt_ergebnis e
     WHERE e.stimme = 'erststimme'
)
SELECT k.aw_id AS kandidatur_id, k.politician_id, k.politician_label,
       k.party_label AS partei_aw, r.partei AS partei_amtlich,
       r.wahljahr, r.wkr_nr, r.einheit_id, r.bestand, r.gemeinden,
       r.stimmen, k.mandat_id, k.gewaehlt
  FROM ergebnis r
  JOIN meta.partei_mapping ma
    ON ma.partei_roh = r.partei AND NOT ma.lieferung_ids @> ARRAY['aw_api_v2']
  JOIN meta.partei_mapping mp
    ON mp.partei = ma.partei AND mp.lieferung_ids @> ARRAY['aw_api_v2']
  JOIN politiker_innen.kandidatur k
    ON k.party_label = mp.partei_roh
   AND k.wkr_nr = r.wkr_nr
   AND substring(k.wahl from '[0-9]{{4}}')::int = r.wahljahr;

COMMENT ON VIEW {WE}.erststimmen_kandidat IS
 'Erststimmen je Wahlkreisbewerber und Wahlkreis - die Ebene, auf der die '
 'Frage zuerst gestellt wird. Moeglich, weil je Partei und Wahlkreis genau EIN '
 'Direktkandidat antritt: die Parteistimmen sind die Stimmen dieser Person. '
 'Traegt anteil und rang, also auch den Abstand zum Sieger. Nur Erststimmen - '
 'Zweitstimmen gelten der Partei, nicht der Person.';
COMMENT ON VIEW {WE}.erststimmen_kandidat_klein IS
 'Wie erststimmen_kandidat, aber je kleinster vollstaendiger Einheit. Diese '
 'ist NICHT die Gemeinde: sie buendelt bis zu 71 davon, weil die Briefwahl '
 'gemeinsam ausgezaehlt wird - wie viele, steht in gemeinden. Fuer Karten '
 'unterhalb des Wahlkreises.';
COMMENT ON COLUMN {WE}.erststimmen_kandidat.rang IS
 'Platz im Wahlkreis nach Erststimmen. rang = 1 ist der Direktgewaehlte; '
 'gegengeprueft gegen die Mandatstabelle.';
COMMENT ON COLUMN {WE}.erststimmen_kandidat.anteil IS
 'Anteil an allen Erststimmen des Wahlkreises, aus den amtlichen Zahlen '
 'gerechnet. anteil_aw daneben ist der von abgeordnetenwatch gelieferte Wert.';
"""


def main():
    tmp = Path(tempfile.gettempdir()) / "erststimmen_kandidat.sql"
    tmp.write_text(SQL, encoding="utf-8")
    run_sql_file(tmp, "erststimmen_kandidat")
    tmp.unlink(missing_ok=True)

    log.info("--- Wahlkreisebene ---")
    for jahr, zeilen, kand, stimmen in query(f"""
            SELECT wahljahr::text, count(*)::text,
                   count(DISTINCT kandidatur_id)::text, sum(stimmen)::text
              FROM {WE}.erststimmen_kandidat GROUP BY 1 ORDER BY 1;"""):
        log.info("   %s: %s Zeilen, %s Kandidaten, %s Stimmen zugeordnet",
                 jahr, zeilen, kand, stimmen)

    log.info("--- Deckt rang = 1 die Direktmandate? ---")
    for jahr, erste, gewaehlt in query(f"""
            SELECT wahljahr::text,
                   count(*) FILTER (WHERE rang = 1)::text,
                   count(*) FILTER (WHERE rang = 1 AND gewaehlt)::text
              FROM {WE}.erststimmen_kandidat GROUP BY 1 ORDER BY 1;"""):
        marke = "OK" if erste == gewaehlt else "PRUEFEN"
        log.info("   %s: %s Wahlkreissieger, davon %s mit Mandat  %s",
                 jahr, erste, gewaehlt, marke)

    log.info("--- Wie eng war es? Abstand des Siegers zum Zweiten ---")
    for jahr, knappste, wkr, mittel in query(f"""
            WITH d AS (SELECT wahljahr, wkr_nr,
                              max(anteil) FILTER (WHERE rang = 1)
                            - max(anteil) FILTER (WHERE rang = 2) AS abstand
                         FROM {WE}.erststimmen_kandidat GROUP BY 1, 2)
            SELECT wahljahr::text, min(abstand)::text,
                   (array_agg(wkr_nr ORDER BY abstand))[1]::text,
                   round(avg(abstand), 1)::text
              FROM d GROUP BY 1 ORDER BY 1;"""):
        log.info("   %s: knappster Wahlkreis %s mit %s Prozentpunkten, " "im Mittel %s", jahr, wkr, knappste, mittel)

    log.info("--- Kleinste vollstaendige Einheit ---")
    for jahr, zeilen, kand, einheiten, stimmen in query(f"""
            SELECT wahljahr::text, count(*)::text,
                   count(DISTINCT kandidatur_id)::text,
                   count(DISTINCT einheit_id)::text, sum(stimmen)::text
              FROM {WE}.erststimmen_kandidat_klein GROUP BY 1 ORDER BY 1;"""):
        log.info("   %s: %s Zeilen, %s Kandidaten, %s Einheiten, %s Stimmen",
                 jahr, zeilen, kand, einheiten, stimmen)

    log.info("--- Gegenprobe: Summe der feinen Ebene gegen die Wahlkreisebene ---")
    for jahr, paare, gleich, ab in query(f"""
            WITH f AS (SELECT wahljahr, kandidatur_id, sum(stimmen) AS s
                         FROM {WE}.erststimmen_kandidat_klein GROUP BY 1, 2)
            SELECT f.wahljahr::text, count(*)::text,
                   count(*) FILTER (WHERE f.s = g.stimmen)::text,
                   count(*) FILTER (WHERE f.s <> g.stimmen)::text
              FROM f JOIN {WE}.erststimmen_kandidat g
                ON g.kandidatur_id = f.kandidatur_id AND g.wahljahr = f.wahljahr
             GROUP BY 1 ORDER BY 1;"""):
        marke = "OK" if ab == "0" else "ABWEICHUNG"
        log.info("   %s: %s Kandidaten, %s Summen gleich, %s abweichend  %s",
                 jahr, paare, gleich, ab, marke)

    log.info("--- Wie fein wird es? Gemeinden je Einheit ---")
    for bestand, einheiten, mittel, groesste in query(f"""
            SELECT bestand, count(DISTINCT einheit_id)::text,
                   round(avg(gemeinden), 1)::text, max(gemeinden)::text
              FROM {WE}.erststimmen_kandidat_klein GROUP BY 1 ORDER BY 1;"""):
        log.info("   %-9s %s Einheiten, im Mittel %s Gemeinden, groesste %s",
                 bestand, einheiten, mittel, groesste)

    log.info("--- Probe: Wahlkreis 218 (2021) ---")
    for zeile in query(f"""



            SELECT rang::text AS t_rang, politician_label, partei_aw,
                   stimmen::text AS t_stimmen, anteil::text AS t_anteil,
                   gewaehlt::text AS t_gewaehlt
              FROM {WE}.erststimmen_kandidat
             WHERE wahljahr = 2021 AND wkr_nr = 218
             ORDER BY rang LIMIT 5;"""):
        log.info("   %s. %-24s %-22s %8s Stimmen  %5s %%  Mandat: %s",
                 zeile[0], zeile[1][:22], zeile[2][:20], zeile[3], zeile[4], zeile[5])


if __name__ == "__main__":
    main()
