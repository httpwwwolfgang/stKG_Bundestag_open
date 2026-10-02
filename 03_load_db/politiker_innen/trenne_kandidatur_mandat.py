import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

SCHEMA = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("trennung")


DDL = f"""
DROP VIEW IF EXISTS {SCHEMA}.kandidatur;
DROP VIEW IF EXISTS {SCHEMA}.mandat;

CREATE VIEW {SCHEMA}.kandidatur AS
SELECT m.aw_id,
       m.politician_id,
       m.politician_label,
       m.parliament_period_id    AS wahl_id,
       m.parliament_period_label AS wahl,
       m.party_id,
       m.party_label,
       m.constituency_id,
       m.wkr_nr,
       c.name                    AS wkr_name,
       m.wkr_herkunft,
       m.constituency_result     AS erststimmen_anteil,
       m.constituency_result_count AS erststimmen_zahl,
       m.electoral_list_id,
       m.liste_id,
       m.liste_herkunft,
       m.list_position           AS listenplatz,
       m.mandate_won             AS ergebnis,





       w.aw_id                   AS mandat_id,
       w.mandatsart              AS mandat_mandatsart,
       (w.aw_id IS NOT NULL)     AS gewaehlt,
       m.constituency_periode_passt,
       m.liste_periode_passt,
       m.uri
  FROM {SCHEMA}.candidacy_mandate m
  LEFT JOIN {SCHEMA}.constituency c ON c.aw_id = m.constituency_id
  LEFT JOIN {SCHEMA}.candidacy_mandate w
         ON w.type = 'mandate'
        AND w.politician_id = m.politician_id
        AND substring(w.parliament_period_label from '[0-9]{{4}}')::int
            = substring(m.parliament_period_label from '[0-9]{{4}}')::int
 WHERE m.type = 'candidacy';

CREATE VIEW {SCHEMA}.mandat AS
SELECT m.aw_id,
       m.politician_id,
       m.politician_label,
       m.parliament_period_id    AS legislatur_id,
       m.parliament_period_label AS legislatur,
       m.mandatsart,
       m.mandatsart_herkunft,
       m.wahlkreisbezug,

       m.fraction_id,
       m.fraction_label,
       m.wkr_nr,
       w.wkr_name,
       m.wkr_herkunft,
       m.constituency_result     AS erststimmen_anteil,
       m.constituency_result_count AS erststimmen_zahl,
       m.electoral_list_id,
       m.liste_id,
       m.liste_herkunft,
       m.list_position           AS listenplatz,



       m.beginn,
       m.beginn_herkunft,
       m.ende,
       m.ende_herkunft,
       (m.ende - m.beginn)       AS dauer_tage,
       m.start_date              AS beginn_aw,
       m.end_date                AS ende_aw,
       m.constituency_id,
       m.constituency_periode_passt,
       m.liste_periode_passt,
       m.uri
  FROM {SCHEMA}.candidacy_mandate m
  LEFT JOIN raum.wahlkreis w
         ON w.wkr_nr = m.wkr_nr
        AND w.wahlperiode = CASE m.parliament_period_label
                                WHEN 'Bundestag 2013 - 2017' THEN 18
                                WHEN 'Bundestag 2017 - 2021' THEN 19
                                WHEN 'Bundestag 2021 - 2025' THEN 20 END
 WHERE m.type = 'mandate';

COMMENT ON VIEW {SCHEMA}.kandidatur IS
 'Wer zu einer Bundestagswahl angetreten ist. Sicht auf candidacy_mandate '
 'mit type = candidacy, plus Wahlkreisnummer und -name aus constituency. '
 'Traegt die PARTEI - die Fraktion gibt es erst am Mandat.';
COMMENT ON VIEW {SCHEMA}.mandat IS
 'Wer im Bundestag sass. Sicht auf candidacy_mandate mit type = mandate, '
 'plus Wahlkreisnummer und -name aus constituency. Traegt die FRAKTION - '
 'die Partei steht nur an der Kandidatur derselben Person.';
COMMENT ON COLUMN {SCHEMA}.kandidatur.ergebnis IS
 'Gelieferter Ausgang der Kandidatur (constituency / list / moved_up). '
 'UNVOLLSTAENDIG, aber nie falsch: nur an 1.500 von 8.634 Kandidaturen '
 'gesetzt, und es nennt 718 Wahlkreissieger, obwohl es ueber drei Wahlen 897 '
 'gibt. Wen es als Gewinner ausweist, der hat auch ein Mandat - geprueft, 0 '
 'Widersprueche. Fuer die vollstaendige Antwort mandat_id / gewaehlt nehmen.';
COMMENT ON COLUMN {SCHEMA}.kandidatur.mandat_id IS
 'Das Mandat, zu dem diese Kandidatur gefuehrt hat, oder NULL. Verknuepft '
 'ueber Person und Wahljahr; je Person und Legislatur gibt es genau ein '
 'Mandat (geprueft: 2.181 Paare, keines doppelt). Vollstaendig, wo ergebnis '
 'es nicht ist: 2.102 Kandidaturen fuehrten zu einem Mandat gegen 1.500 '
 'laut ergebnis. Die Differenz zu 2.181 Mandaten sind die 79 ohne Kandidatur '
 '.';
COMMENT ON COLUMN {SCHEMA}.kandidatur.gewaehlt IS
 'TRUE, wenn die Person zu dieser Wahl ein Mandat erhielt - auch wenn sie '
 'erst spaeter nachrueckte. Abgeleitet aus der Mandatstabelle, nicht aus dem '
 'gelieferten ergebnis.';
COMMENT ON COLUMN {SCHEMA}.mandat.fraction_label IS
 'Fraktion waehrend dieser Legislatur - die zeitrichtige Zugehoerigkeit am '
 'Mandat. Eine PARTEI gibt es hier nicht: sie steht an der Kandidatur '
 '(Partei zum Zeitpunkt des Antritts) oder an politician.party_label '
 '(heutige Partei, bei allen 6.906 gefuellt). Beides sind andere Aussagen '
 'als die Fraktion und werden hier NICHT hereingerechnet.';
COMMENT ON COLUMN {SCHEMA}.mandat.erststimmen_anteil IS
 'Erststimmenanteil in Prozent, soweit geliefert. Bei Direktgewaehlten '
 '299/299 (2013-2017), 297/299 (2017-2021), 249/299 (2021-2025) - die '
 'fehlenden 50 sind dieselben wie bei wkr_nr.';
COMMENT ON COLUMN {SCHEMA}.mandat.wkr_nr IS
 'Amtliche Wahlkreisnummer. NULL bei 50 Direktgewaehlten der Legislatur '
 '2021-2025: die Wahlkreise 1 bis 50 sind fuer diese Wahlperiode nicht '
 'geliefert. Ein Direktsieger ohne Wahlkreis ist ein '
 'Lieferfehler, kein Sachverhalt.';
"""


def bericht():
    log.info("--- Kandidaturen ---")
    for wahl, n, personen, mit_wk in query(f"""
            SELECT wahl, count(*), count(DISTINCT politician_id), count(wkr_nr)
              FROM {SCHEMA}.kandidatur GROUP BY 1 ORDER BY 1;"""):
        log.info("   %-24s %6s Kandidaturen, %6s Personen, %6s mit Wahlkreisnummer",
                 wahl, n, personen, mit_wk)

    log.info("--- Mandate ---")
    for leg, n, personen, mit_wk in query(f"""
            SELECT legislatur, count(*), count(DISTINCT politician_id), count(wkr_nr)
              FROM {SCHEMA}.mandat GROUP BY 1 ORDER BY 1;"""):
        log.info("   %-24s %6s Mandate, %6s Personen, %6s mit Wahlkreisnummer",
                 leg, n, personen, mit_wk)

    log.info("--- Mandate je Art, und wie oft die Wahlkreisnummer fehlt ---")
    for leg, art, n, ohne in query(f"""
            SELECT legislatur, coalesce(mandatsart,'(leer)'), count(*),
                   count(*) FILTER (WHERE wkr_nr IS NULL)
              FROM {SCHEMA}.mandat GROUP BY 1,2 ORDER BY 1,2;"""):
        log.info("   %-24s %-14s %5s Mandate, davon %3s ohne Wahlkreisnummer",
                 leg, art, n, ohne)

    log.info("--- Geht die Summe auf? ---")
    for k, m, s, gesamt in query(f"""
            SELECT (SELECT count(*) FROM {SCHEMA}.kandidatur),
                   (SELECT count(*) FROM {SCHEMA}.mandat),
                   (SELECT count(*) FROM {SCHEMA}.kandidatur)
                   + (SELECT count(*) FROM {SCHEMA}.mandat),
                   (SELECT count(*) FROM {SCHEMA}.candidacy_mandate);"""):
        gleich = "ja" if s == gesamt else "NEIN - pruefen"
        log.info("   %s Kandidaturen + %s Mandate = %s, candidacy_mandate hat %s -> %s",
                 k, m, s, gesamt, gleich)

    log.info("--- Die Spalten, die jeweils nur einer Seite gehoeren ---")
    for zeile in query(f"""
            SELECT (SELECT count(party_label) FROM {SCHEMA}.kandidatur),
                   (SELECT count(fraction_label) FROM {SCHEMA}.mandat);"""):
        log.info("   Partei an Kandidaturen: %s   Fraktion an Mandaten: %s", *zeile)
        log.info("   Umgekehrt gibt es beide Spalten in der anderen Sicht nicht.")


def main():
    run_sql(DDL, "kandidatur und mandat trennen")
    bericht()


if __name__ == "__main__":
    main()
