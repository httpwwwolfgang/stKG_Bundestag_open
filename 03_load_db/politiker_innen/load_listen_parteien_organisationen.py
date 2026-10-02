import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("listen")


DDL = f"""
DROP TABLE IF EXISTS {AW}.organisation_thema;
DROP TABLE IF EXISTS {AW}.organisation;
DROP TABLE IF EXISTS {AW}.landesliste;
DROP TABLE IF EXISTS {AW}.partei;
DROP TABLE IF EXISTS {AW}.fraktion;

CREATE TABLE {AW}.landesliste AS
SELECT (data->>'id')::int                              AS aw_id,
        data->>'name'                                  AS name,





        replace(data->>'name', 'Mecklenburg Vorpommern',
                'Mecklenburg-Vorpommern')             AS name_normalisiert,
        data->>'label'                                 AS label,
       (data->'parliament_period'->>'id')::int         AS wahl_id,
        data->'parliament_period'->>'label'            AS wahl
  FROM {AW}.raw_electoral_lists;
ALTER TABLE {AW}.landesliste ADD PRIMARY KEY (aw_id);
CREATE INDEX ON {AW}.landesliste (name_normalisiert);

COMMENT ON COLUMN {AW}.landesliste.name IS
 'Gelieferter Name, unveraendert. Achtung: 17 Schreibweisen fuer 16 '
 'Bundeslaender - aw_id 417 schreibt Mecklenburg Vorpommern ohne '
 'Bindestrich. Wer ueber den Namen gruppiert, bekommt Mecklenburg zweimal.';
COMMENT ON COLUMN {AW}.landesliste.name_normalisiert IS
 'Wie name, nur mit vereinheitlichter Mecklenburg-Schreibweise. Damit sind '
 'es 16 Bundeslaender, und der Vergleich mit raum.wahlkreis_land.land_name '
 'geht auf. Fuer Gruppierungen und Joins diese Spalte nehmen.';

CREATE TABLE {AW}.partei AS
SELECT (data->>'id')::int                              AS aw_id,
        data->>'label'                                 AS label,
        data->>'short_name'                            AS kurzname,
        data->>'full_name'                             AS langname
  FROM {AW}.raw_parties;
ALTER TABLE {AW}.partei ADD PRIMARY KEY (aw_id);

CREATE TABLE {AW}.fraktion AS
SELECT (data->>'id')::int                              AS aw_id,
        data->>'label'                                 AS label,
        data->>'short_name'                            AS kurzname,
        data->>'full_name'                             AS langname,
       (data->'legislature'->>'id')::int               AS legislatur_id,
        data->'legislature'->>'label'                  AS legislatur
  FROM {AW}.raw_fractions;
ALTER TABLE {AW}.fraktion ADD PRIMARY KEY (aw_id);

CREATE TABLE {AW}.organisation AS
SELECT (data->>'id')::int                              AS aw_id,
        data->>'label'                                 AS name,
        data->'field_city'->>'label'                   AS stadt,
        data->'field_country'->>'label'                AS land
  FROM {AW}.raw_sidejob_organizations;
ALTER TABLE {AW}.organisation ADD PRIMARY KEY (aw_id);

CREATE TABLE {AW}.organisation_thema AS
SELECT (o.data->>'id')::int          AS organisation_id,
       (t->>'id')::int               AS thema_id,
        t->>'label'                  AS thema
  FROM {AW}.raw_sidejob_organizations o,
       jsonb_array_elements(CASE WHEN jsonb_typeof(o.data->'field_topics') = 'array'
                               THEN o.data->'field_topics' ELSE '[]'::jsonb END) t;
ALTER TABLE {AW}.organisation_thema ADD PRIMARY KEY (organisation_id, thema_id);

COMMENT ON TABLE {AW}.fraktion IS
 'Fraktionen, je Wahlperiode ein eigenes Objekt mit eigener Id. Wer ueber '
 'Legislaturen hinweg gruppiert, nimmt kurzname - ueber aw_id zerfaellt jede '
 'Fraktion in drei.';
COMMENT ON TABLE {AW}.partei IS
 'Parteien. Nicht mit fraktion verwechseln: die Partei haengt an der '
 'Kandidatur und trennt CDU von CSU, die Fraktion haengt am Mandat und fasst '
 'sie zusammen.';
COMMENT ON TABLE {AW}.organisation IS
 'Auftraggeber der Nebentaetigkeiten. Angeschlossen ueber '
 'sidejob.organization_id.';
COMMENT ON TABLE {AW}.organisation_thema IS
 'Sachgebiete je Organisation - abgeordnetenwatchs eigene Taxonomie, keine '
 'amtliche Branchensystematik. Anhaltspunkt, keine Klassifikation.';
"""


def bericht():
    log.info("--- Was entstanden ist ---")
    for tab, n in query(f"""
            SELECT 'landesliste',        count(*)::text FROM {AW}.landesliste
            UNION ALL SELECT 'partei',   count(*)::text FROM {AW}.partei
            UNION ALL SELECT 'fraktion', count(*)::text FROM {AW}.fraktion
            UNION ALL SELECT 'organisation',       count(*)::text FROM {AW}.organisation
            UNION ALL SELECT 'organisation_thema', count(*)::text FROM {AW}.organisation_thema;"""):
        log.info("   %-22s %s", tab, n)

    log.info("--- Loesen die Verweise jetzt auf? ---")
    for was, gesamt, gefunden in query(f"""
            SELECT 'Mandate -> Landesliste', count(m.electoral_list_id), count(l.aw_id)
              FROM {AW}.candidacy_mandate m
              LEFT JOIN {AW}.landesliste l ON l.aw_id = m.electoral_list_id
             WHERE m.type = 'mandate'
            UNION ALL
            SELECT 'Kandidaturen -> Partei', count(m.party_id), count(p.aw_id)
              FROM {AW}.candidacy_mandate m
              LEFT JOIN {AW}.partei p ON p.aw_id = m.party_id
             WHERE m.type = 'candidacy'
            UNION ALL
            SELECT 'Stimmen -> Fraktion', count(s.fraktion_id), count(f.aw_id)
              FROM {AW}.stimme s LEFT JOIN {AW}.fraktion f ON f.aw_id = s.fraktion_id
            UNION ALL
            SELECT 'Nebentaetigkeit -> Organisation', count(j.organization_id), count(o.aw_id)
              FROM {AW}.sidejob j LEFT JOIN {AW}.organisation o ON o.aw_id = j.organization_id;"""):
        log.info("   %-34s %s Verweise, %s aufgeloest", was, gesamt, gefunden)

    log.info("--- Ueber welche Landeslisten wurde eingezogen? Die groessten ---")
    for name, wahl, n in query(f"""
            SELECT l.name, l.wahl, count(*)::text
              FROM {AW}.candidacy_mandate m JOIN {AW}.landesliste l
                   ON l.aw_id = m.electoral_list_id
             WHERE m.type = 'mandate' GROUP BY 1,2 ORDER BY count(*) DESC LIMIT 6;"""):
        log.info("   %-32s %-24s %s Mandate", name, wahl, n)

    log.info("--- Welche Organisationen zahlen an die meisten Abgeordneten? ---")
    for name, personen, jobs in query(f"""
            SELECT o.name, count(DISTINCT m.politician_id)::text, count(*)::text
              FROM {AW}.sidejob j
              JOIN {AW}.organisation o ON o.aw_id = j.organization_id
              JOIN {AW}.candidacy_mandate m ON m.aw_id = j.mandate_id
             GROUP BY 1 ORDER BY count(DISTINCT m.politician_id) DESC LIMIT 8;"""):
        log.info("   %-46s %s Abgeordnete, %s Nebentaetigkeiten", name[:45], personen, jobs)


def main():
    run_sql(DDL, "listen, parteien, organisationen")
    bericht()


if __name__ == "__main__":
    main()
