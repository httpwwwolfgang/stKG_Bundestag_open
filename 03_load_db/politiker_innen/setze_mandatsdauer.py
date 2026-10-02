import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

AW = "politiker_innen"
ROH = "roh_bundestag"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("mandatsdauer")


WP = "CASE substring(m.parliament_period_label from '[0-9]{4}')::int " \
     "WHEN 2013 THEN 18 WHEN 2017 THEN 19 WHEN 2021 THEN 20 END"

DDL = f"""
SET client_min_messages TO WARNING;

ALTER TABLE {AW}.candidacy_mandate
    ADD COLUMN IF NOT EXISTS beginn_amtlich  date,
    ADD COLUMN IF NOT EXISTS ende_amtlich    date,
    ADD COLUMN IF NOT EXISTS beginn          date,
    ADD COLUMN IF NOT EXISTS beginn_herkunft text,
    ADD COLUMN IF NOT EXISTS ende            date,
    ADD COLUMN IF NOT EXISTS ende_herkunft   text;

UPDATE {AW}.candidacy_mandate m
   SET beginn_amtlich = w.mdbwp_von,
       ende_amtlich   = w.mdbwp_bis
  FROM {AW}.mdb_zu_aw z
  JOIN {ROH}.stammdaten_mdb_wahlperiode w ON w.id = z.mdb_id
 WHERE z.aw_id = m.politician_id
   AND m.type  = 'mandate'
   AND w.wp    = {WP};

UPDATE {AW}.candidacy_mandate m
   SET beginn = coalesce(m.beginn_amtlich, m.start_date),
       ende   = coalesce(m.ende_amtlich,   m.end_date),
       beginn_herkunft = CASE
           WHEN m.beginn_amtlich IS NOT NULL THEN 'bt_mdb_stammdaten'
           WHEN m.start_date     IS NOT NULL THEN 'aw_api_v2'
           ELSE 'unbestimmt' END,
       ende_herkunft = CASE
           WHEN m.ende_amtlich IS NOT NULL THEN 'bt_mdb_stammdaten'
           WHEN m.end_date     IS NOT NULL THEN 'aw_api_v2'
           ELSE 'unbestimmt' END
 WHERE m.type = 'mandate';

UPDATE {AW}.candidacy_mandate m
   SET beginn_herkunft = 'ergaenzt', ende_herkunft = 'ergaenzt'
  FROM {AW}.nachfolge n
 WHERE n.quelle = 'ergaenzt'
   AND n.vorgaenger_aw_id = m.politician_id
   AND m.type = 'mandate'
   AND m.beginn_amtlich IS NULL
   AND m.beginn IS NOT NULL;

CREATE INDEX IF NOT EXISTS candidacy_mandate_dauer_idx
    ON {AW}.candidacy_mandate (beginn, ende);

COMMENT ON COLUMN {AW}.candidacy_mandate.beginn_amtlich IS
 'mdbwp_von aus roh_bundestag.stammdaten_mdb_wahlperiode, Lieferung '
 'bt_mdb_stammdaten (Deutscher Bundestag, MdB-XML). Unveraendert uebernommen, '
 'angeschlossen ueber mdb_zu_aw statt ueber Namen.';
COMMENT ON COLUMN {AW}.candidacy_mandate.ende_amtlich IS
 'mdbwp_bis aus derselben Lieferung. ACHTUNG: der Bundestag traegt den letzten '
 'Tag MIT Mandat ein, abgeordnetenwatch in end_date den ersten Tag OHNE - '
 'daher 25 Abweichungen von genau einem Tag. Kein Fehler, sondern zwei '
 'Bedeutungen.';
COMMENT ON COLUMN {AW}.candidacy_mandate.beginn IS
 'Geltender Mandatsbeginn. Vorrang: amtlich (bt_mdb_stammdaten) vor geliefert '
 '(aw_api_v2). start_date bleibt daneben unveraendert stehen.';
COMMENT ON COLUMN {AW}.candidacy_mandate.ende IS
 'Geltendes Mandatsende, gleiche Vorrangregel wie beginn.';
COMMENT ON COLUMN {AW}.candidacy_mandate.beginn_herkunft IS
 'Welche LIEFERUNG den geltenden Wert gestellt hat, als lieferung_id aus '
 'meta.datenlieferung: bt_mdb_stammdaten (MdB-XML, amtlich) oder aw_api_v2 '
 '(abgeordnetenwatch). Dazu ergaenzt (eigene Entscheidung aus einer '
 'Korrektur-CSV) und unbestimmt (keine Quelle nennt ein Datum).';
COMMENT ON COLUMN {AW}.candidacy_mandate.ende_herkunft IS
 'Wie beginn_herkunft, fuer das Mandatsende.';
"""


def main():
    run_sql(DDL, "mandatsdauer")

    log.info("--- Vorher und nachher ---")
    for zeile in query(f"""
            SELECT parliament_period_label, count(*)::text,
                   count(start_date)::text, count(beginn)::text,
                   count(end_date)::text, count(ende)::text
              FROM {AW}.candidacy_mandate WHERE type = 'mandate'
             GROUP BY 1 ORDER BY 1;"""):
        log.info("   %-24s %s Mandate | Beginn %s -> %s | Ende %s -> %s",
                 zeile[0], zeile[1], zeile[2], zeile[3], zeile[4], zeile[5])

    log.info("--- Welche Lieferung stellt den geltenden Wert? ---")
    for h, b, e in query(f"""
            SELECT h, count(*) FILTER (WHERE art = 'beginn')::text,
                   count(*) FILTER (WHERE art = 'ende')::text
              FROM (SELECT beginn_herkunft AS h, 'beginn' AS art
                      FROM {AW}.candidacy_mandate WHERE type = 'mandate'
                    UNION ALL
                    SELECT ende_herkunft, 'ende'
                      FROM {AW}.candidacy_mandate WHERE type = 'mandate') x
             GROUP BY 1 ORDER BY 2 DESC;"""):
        log.info("   %-22s Beginn %6s   Ende %6s", h, b, e)

    log.info("--- Wo beide Lieferungen ein Ende nennen: Abweichung in Tagen ---")
    for tage, n in query(f"""
            SELECT (ende_amtlich - end_date)::text, count(*)::text
              FROM {AW}.candidacy_mandate
             WHERE type = 'mandate' AND end_date IS NOT NULL
               AND ende_amtlich IS NOT NULL
             GROUP BY 1 ORDER BY 1::int;"""):
        marke = "  (aw nennt den ersten Tag OHNE Mandat)" if tage == "-1" else ""
        log.info("   %+5s Tage: %4s%s", tage, n, marke)

    log.info("--- Die Widersprueche, die das nicht erklaert ---")
    for zeile in query(f"""
            SELECT politician_label, parliament_period_label,
                   end_date::text, ende_amtlich::text,
                   (ende_amtlich - end_date)::text
              FROM {AW}.candidacy_mandate
             WHERE type = 'mandate' AND end_date IS NOT NULL
               AND ende_amtlich IS NOT NULL
               AND ende_amtlich - end_date NOT IN (0, -1)
             ORDER BY abs(ende_amtlich - end_date) DESC;"""):
        log.info("   %-28s %s  aw %s | Bundestag %s (%s Tage)",
                 zeile[0][:26], zeile[1][-11:], zeile[2], zeile[3], zeile[4])

    log.info("--- Gegenprobe: Mandate ohne jedes Datum ---")
    for ohne, gesamt in query(f"""
            SELECT count(*) FILTER (WHERE beginn IS NULL OR ende IS NULL)::text,
                   count(*)::text
              FROM {AW}.candidacy_mandate WHERE type = 'mandate';"""):
        log.info("   %s von %s (erwartet 0)", ohne, gesamt)

    log.info("--- Und was daraus jetzt geht: Mandatsdauer in Tagen ---")
    for zeile in query(f"""
            SELECT parliament_period_label,
                   min(ende - beginn)::text, round(avg(ende - beginn))::text,
                   max(ende - beginn)::text
              FROM {AW}.candidacy_mandate WHERE type = 'mandate'
               AND beginn IS NOT NULL AND ende IS NOT NULL
             GROUP BY 1 ORDER BY 1;"""):
        log.info("   %-24s kuerzestes %s, Mittel %s, laengstes %s Tage", *zeile)


if __name__ == "__main__":
    main()
