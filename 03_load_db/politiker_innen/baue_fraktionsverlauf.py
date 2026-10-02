import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql_file, query

AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("fraktionsverlauf")


SQL = f"""
SET client_min_messages TO WARNING;
CREATE EXTENSION IF NOT EXISTS btree_gist;

DROP TABLE IF EXISTS {AW}.fraktion_funktion;
DROP TABLE IF EXISTS {AW}.fraktion_mitgliedschaft;

CREATE TEMP TABLE roh AS
SELECT m.aw_id                       AS mandat_id,
       f.mdb_id, f.wp, f.lfd, f.fraktion, f.von, f.bis,
       f.funktion, f.funktion_von, f.funktion_bis,
       m.beginn, m.ende
  FROM {AW}.fraktionszugehoerigkeit f
  JOIN {AW}.mdb_zu_aw z ON z.mdb_id = f.mdb_id
  JOIN {AW}.mandat m ON m.politician_id = z.aw_id
   AND substring(m.legislatur from '[0-9]{{4}}')::int
       = CASE f.wp WHEN 18 THEN 2013 WHEN 19 THEN 2017 WHEN 20 THEN 2021 END;

CREATE TEMP TABLE zug AS
SELECT mandat_id, fraktion, von, min(bis) AS bis, min(beginn) AS beginn,
       min(ende) AS ende, count(*) AS xml_zeilen
  FROM roh GROUP BY mandat_id, fraktion, von;

CREATE TABLE {AW}.fraktion_mitgliedschaft AS
SELECT mandat_id,
       (row_number() OVER (PARTITION BY mandat_id ORDER BY von))::smallint AS lfd,
       fraktion,
       von,
       bis AS bis_geliefert,
       daterange(von,
                 coalesce(lead(von) OVER (PARTITION BY mandat_id ORDER BY von),
                          ende + 1),
                 '[)') AS zeitraum,
       xml_zeilen
  FROM zug;

ALTER TABLE {AW}.fraktion_mitgliedschaft ADD PRIMARY KEY (mandat_id, lfd);
ALTER TABLE {AW}.fraktion_mitgliedschaft
    ADD CONSTRAINT fraktion_mitgliedschaft_ohne_ueberlappung
    EXCLUDE USING gist (mandat_id WITH =, zeitraum WITH &&);
CREATE INDEX ON {AW}.fraktion_mitgliedschaft USING gist (zeitraum);
CREATE INDEX ON {AW}.fraktion_mitgliedschaft (fraktion);

CREATE TABLE {AW}.fraktion_funktion AS
SELECT mandat_id,
       (row_number() OVER (PARTITION BY mandat_id ORDER BY funktion_von, funktion))::smallint AS lfd,
       fraktion, funktion,
       funktion_von AS von,
       funktion_bis AS bis_geliefert,
       daterange(funktion_von, coalesce(funktion_bis + 1, ende + 1), '[)') AS zeitraum
  FROM roh
 WHERE funktion IS NOT NULL AND funktion_von IS NOT NULL;

ALTER TABLE {AW}.fraktion_funktion ADD PRIMARY KEY (mandat_id, lfd);
CREATE INDEX ON {AW}.fraktion_funktion USING gist (zeitraum);

COMMENT ON TABLE {AW}.fraktion_mitgliedschaft IS
 'Fraktionszugehoerigkeit als lueckenloser Zeitverlauf je Mandat. Quelle: '
 'MdB-XML (Lieferung bt_mdb_stammdaten) ueber fraktionszugehoerigkeit, '
 'angeschlossen ueber mdb_zu_aw. Der Anker ist das MANDAT, nicht die Person '
 '( G2). Im Knowledge Graph wird daraus ein eigener '
 'Knoten: eine reifizierte Beziehung Mandat -> Fraktion mit Zeitraum.';
COMMENT ON COLUMN {AW}.fraktion_mitgliedschaft.zeitraum IS
 'Halboffen [von, bis). Gebildet aus dem VON der naechsten Zeile, NICHT aus '
 'dem gelieferten bis: dessen Konvention wechselt (48-mal ist bis der letzte '
 'Tag MIT, 49-mal der erste Tag OHNE, teils bei derselben Person). Die letzte '
 'Zeile endet am Mandatsende + 1. Ueberlappungsfreiheit ist per '
 'EXCLUDE-Constraint erzwungen, nicht behauptet.';
COMMENT ON COLUMN {AW}.fraktion_mitgliedschaft.bis_geliefert IS
 'Der gelieferte bis-Wert, unveraendert. An den 49 Uebergangstagen weicht er '
 'um einen Tag von der Obergrenze in zeitraum ab - absichtlich sichtbar '
 'gelassen. NULL heisst: das XML nennt kein Ende, der Zeitraum laeuft bis zum '
 'Mandatsende.';
COMMENT ON COLUMN {AW}.fraktion_mitgliedschaft.xml_zeilen IS
 'Wie viele XML-Zeilen zu dieser einen Zugehoerigkeit zusammengefasst wurden. '
 '2 bedeutet: die Person hatte in diesem Zeitraum zwei Funktionen in der '
 'Fraktion, und das XML wiederholt die Zugehoerigkeit je Funktion. Zwoelf '
 'solche Faelle - Fraktionsvorsitzende und Geschaeftsfuehrer.';
COMMENT ON COLUMN {AW}.fraktion_mitgliedschaft.fraktion IS
 'Klartext des MdB-XML ("Fraktion DIE LINKE."). NICHT gemappt auf '
 'politiker_innen.fraktion, deren Labels anders lauten.';
COMMENT ON TABLE {AW}.fraktion_funktion IS
 'Funktionen innerhalb der Fraktion - Vorsitz, Parlamentarische '
 'Geschaeftsfuehrung, Justiziariat - mit eigenem Zeitraum. Im XML steckten sie '
 'in derselben Zeile wie die Zugehoerigkeit und liessen sie doppelt erscheinen.';
"""


def main():
    tmp = Path(tempfile.gettempdir()) / "fraktionsverlauf.sql"
    tmp.write_text(SQL, encoding="utf-8")
    run_sql_file(tmp, "fraktionsverlauf")
    tmp.unlink(missing_ok=True)

    log.info("--- Was entstanden ist ---")
    for zeilen, mandate, doppelt in query(f"""
            SELECT count(*)::text, count(DISTINCT mandat_id)::text,
                   count(*) FILTER (WHERE xml_zeilen > 1)::text
              FROM {AW}.fraktion_mitgliedschaft;"""):
        log.info("   fraktion_mitgliedschaft: %s Zeilen, %s Mandate, " "%s aus zwei XML-Zeilen zusammengefasst", zeilen, mandate, doppelt)
    for zeilen, mandate in query(f"""
            SELECT count(*)::text, count(DISTINCT mandat_id)::text
              FROM {AW}.fraktion_funktion;"""):
        log.info("   fraktion_funktion:       %s Zeilen, %s Mandate", zeilen, mandate)

    log.info("--- Deckt der Verlauf das ganze Mandat ab? ---")
    for legislatur, mandate, mit, luecke in query(f"""
            SELECT m.legislatur, count(*)::text,
                   count(*) FILTER (WHERE v.mandat_id IS NOT NULL)::text,
                   count(*) FILTER (WHERE v.mandat_id IS NOT NULL
                       AND NOT v.abdeckung @> daterange(m.beginn, m.ende + 1, '[)'))::text
              FROM {AW}.mandat m
              LEFT JOIN (SELECT mandat_id, range_agg(zeitraum) AS abdeckung
                           FROM {AW}.fraktion_mitgliedschaft GROUP BY 1) v
                     ON v.mandat_id = m.aw_id
             GROUP BY 1 ORDER BY 1;"""):
        log.info("   %-24s %s Mandate, %s mit Verlauf, %s unvollstaendig abgedeckt",
                 legislatur, mandate, mit, luecke)

    log.info("--- Wie viele Wechsel? ---")
    for n, anzahl in query(f"""
            SELECT n::text, count(*)::text FROM (
                SELECT mandat_id, count(*) AS n
                  FROM {AW}.fraktion_mitgliedschaft GROUP BY 1) x
             GROUP BY 1 ORDER BY 1;"""):
        log.info("   %s Zugehoerigkeit(en): %s Mandate", n, anzahl)


    log.info("--- Gegenprobe: eine Fraktion je Zeitraum? ---")
    for abschnitte, eindeutig in query(f"""
            SELECT count(*)::text,
                   count(*) FILTER (WHERE n = 1)::text FROM (
                SELECT v.mandat_id, v.lfd,
                       count(DISTINCT split_part(s.fraktion, ' (', 1)) AS n
                  FROM {AW}.fraktion_mitgliedschaft v
                  JOIN {AW}.stimme s ON s.mandat_id = v.mandat_id
                  JOIN {AW}.abstimmung a ON a.aw_id = s.abstimmung_id
                   AND v.zeitraum @> a.datum
                 GROUP BY 1, 2) x;"""):
        log.info("   %s Zeitraeume mit Stimmen, %s davon mit genau EINER " "Fraktion laut stimme.fraktion", abschnitte, eindeutig)

    log.info("--- Stimmabgaben ausserhalb jeder Mandatsdauer ---")
    for zeile in query(f"""
            SELECT m.politician_label, a.datum::text, m.ende::text,
                   (a.datum - m.ende)::text, s.stimme
              FROM {AW}.stimme s
              JOIN {AW}.abstimmung a ON a.aw_id = s.abstimmung_id
              JOIN {AW}.mandat m ON m.aw_id = s.mandat_id
             WHERE NOT EXISTS (SELECT 1 FROM {AW}.fraktion_mitgliedschaft v
                                WHERE v.mandat_id = s.mandat_id
                                  AND v.zeitraum @> a.datum)
             ORDER BY 1, 2;"""):
        log.info("   %-24s stimmte %s, Mandat endete %s (%s Tage) - %s",
                 zeile[0][:22], zeile[1], zeile[2], zeile[3], zeile[4])

    log.info("--- Und was mandat.fraction_label verschweigt ---")
    for zeile in query(f"""
            SELECT m.politician_label, m.legislatur, m.fraction_label,
                   string_agg(v.fraktion || ' ' || lower(v.zeitraum)::text,
                              ' | ' ORDER BY v.lfd)
              FROM {AW}.fraktion_mitgliedschaft v
              JOIN {AW}.mandat m ON m.aw_id = v.mandat_id
             WHERE v.mandat_id IN (SELECT mandat_id FROM {AW}.fraktion_mitgliedschaft
                                    GROUP BY 1 HAVING count(*) > 2)
             GROUP BY 1, 2, 3 ORDER BY 1 LIMIT 3;"""):
        log.info("   %s (%s)", zeile[0], zeile[1][-11:])
        log.info("      mandat sagt: %s", zeile[2][:52])
        log.info("      Verlauf:     %s", zeile[3][:110])


if __name__ == "__main__":
    main()
