import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("sidejob-mandat")


DDL = f"""
DROP TABLE IF EXISTS {AW}.sidejob_mandat;

CREATE TABLE {AW}.sidejob_mandat AS
SELECT (r.data->>'id')::int          AS sidejob_id,
       (m->>'id')::int               AS mandat_id,
       min(ord)::smallint            AS lfd,
       count(*)::smallint            AS nennungen,
       EXISTS (SELECT 1 FROM {AW}.candidacy_mandate cm
                WHERE cm.aw_id = (m->>'id')::int
                  AND cm.type = 'mandate')  AS mandat_im_bestand
  FROM {AW}.raw_sidejobs r,
       jsonb_array_elements(r.data->'mandates') WITH ORDINALITY AS t(m, ord)
 GROUP BY 1, 2, 5;

ALTER TABLE {AW}.sidejob_mandat ADD PRIMARY KEY (sidejob_id, mandat_id);
CREATE INDEX ON {AW}.sidejob_mandat (mandat_id);

COMMENT ON TABLE {AW}.sidejob_mandat IS
 'Kante Mandat -> Nebentaetigkeit, n:m. Loest die gelieferte Liste '
 'raw_sidejobs.data->mandates auf, von der sidejob.mandate_id nur das erste '
 'Element traegt. 20.293 Verknuepfungen bei 16.189 Nebentaetigkeiten. '
 'Der Anker ist das MANDAT, nicht die Person: 2.127 Nebentaetigkeiten spannen '
 'ueber mehrere Wahlperioden, und an der Person haengend ginge die Zeitachse '
 'verloren. Die Person ist ueber mandat -> politician_id ableitbar. '
 'Siehe .';
COMMENT ON COLUMN {AW}.sidejob_mandat.lfd IS
 'Position in der gelieferten Liste. lfd = 1 ist der Wert, den '
 'sidejob.mandate_id traegt - die Reihenfolge stammt vom Herausgeber und hat '
 'keine inhaltliche Bedeutung.';
COMMENT ON COLUMN {AW}.sidejob_mandat.nennungen IS
 'Wie oft das Mandat in der gelieferten Liste steht. Normalerweise 1; bei '
 'fuenf Nebentaetigkeiten steht dasselbe Mandat ZWEIMAL identisch drin - eine '
 'Dopplung der Lieferung, kein Sachverhalt. Sie sind hier zu einer Kante '
 'zusammengefasst und an nennungen = 2 erkennbar.';
COMMENT ON COLUMN {AW}.sidejob_mandat.mandat_im_bestand IS
 'FALSE, wenn das Mandat ausserhalb der drei geladenen Legislaturen liegt. '
 '1.518 von 20.293 Verknuepfungen. Die Zeile bleibt stehen, damit die '
 'Lieferung vollstaendig abgebildet ist.';
"""


def main():
    run_sql(DDL, "sidejob_mandat")

    log.info("--- Was entstanden ist ---")
    for gesamt, im_bestand, sidejobs, mandate in query(f"""
            SELECT count(*)::text,
                   count(*) FILTER (WHERE mandat_im_bestand)::text,
                   count(DISTINCT sidejob_id)::text,
                   count(DISTINCT mandat_id) FILTER (WHERE mandat_im_bestand)::text
              FROM {AW}.sidejob_mandat;"""):
        log.info("   %s Kanten, davon %s auf ein Mandat im Bestand", gesamt, im_bestand)
        log.info("   %s Nebentaetigkeiten, %s verschiedene Mandate", sidejobs, mandate)

    log.info("--- Doppelt genannte Mandate in der Lieferung ---")
    for zeile in query(f"""
            SELECT sm.sidejob_id::text, j.label, m.politician_label, sm.nennungen::text
              FROM {AW}.sidejob_mandat sm
              JOIN {AW}.sidejob j ON j.aw_id = sm.sidejob_id
              LEFT JOIN {AW}.candidacy_mandate m ON m.aw_id = sm.mandat_id
             WHERE sm.nennungen > 1 ORDER BY sm.sidejob_id;"""):
        log.info("   sidejob %-7s %-20s %sx  %s", zeile[0], zeile[2][:20],
                 zeile[3], zeile[1][:40])

    log.info("--- Wie viele Mandate je Nebentaetigkeit? ---")
    for anzahl, n in query(f"""
            SELECT anzahl::text, count(*)::text FROM (
                SELECT sidejob_id, count(*) AS anzahl
                  FROM {AW}.sidejob_mandat GROUP BY 1) x
             GROUP BY 1 ORDER BY 1;"""):
        log.info("   an %s Mandat(en): %s", anzahl, n)

    log.info("--- Was der alte Weg unterschlagen hat ---")
    for alt, neu in query(f"""
            SELECT (SELECT count(*)::text FROM {AW}.sidejob),
                   (SELECT count(*)::text FROM {AW}.sidejob_mandat);"""):
        log.info("   sidejob.mandate_id: %s Verknuepfungen", alt)
        log.info("   sidejob_mandat:     %s Verknuepfungen", neu)

    log.info("--- Gegenprobe: Martin Burkert im Eisenbahninfrastrukturbeirat ---")
    for zeile in query(f"""
            SELECT j.label, m.politician_label, m.parliament_period_label, sm.lfd::text
              FROM {AW}.sidejob_mandat sm
              JOIN {AW}.sidejob j ON j.aw_id = sm.sidejob_id
              JOIN {AW}.candidacy_mandate m ON m.aw_id = sm.mandat_id
             WHERE j.aw_id = 4714 ORDER BY sm.lfd;"""):
        log.info("   %s | %s | %s | lfd %s", zeile[0][:40], zeile[1], zeile[2], zeile[3])

    log.info("--- Wer hat die meisten Nebentaetigkeiten je Wahlperiode? ---")
    for name, periode, n in query(f"""
            SELECT m.politician_label, m.parliament_period_label, count(*)::text
              FROM {AW}.sidejob_mandat sm
              JOIN {AW}.candidacy_mandate m ON m.aw_id = sm.mandat_id
             WHERE sm.mandat_im_bestand AND m.type = 'mandate'
             GROUP BY 1, 2 ORDER BY count(*) DESC LIMIT 5;"""):
        log.info("   %-26s %-24s %s", name[:25], periode, n)


if __name__ == "__main__":
    main()
