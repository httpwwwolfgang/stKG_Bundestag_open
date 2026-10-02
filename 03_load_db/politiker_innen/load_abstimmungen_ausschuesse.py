import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("abstimmungen")


DDL = f"""
DROP TABLE IF EXISTS {AW}.abstimmung_thema;
DROP TABLE IF EXISTS {AW}.abstimmung_ausschuss;
DROP TABLE IF EXISTS {AW}.abstimmung;
DROP TABLE IF EXISTS {AW}.stimme;
DROP TABLE IF EXISTS {AW}.ausschussmitgliedschaft;
DROP TABLE IF EXISTS {AW}.abstimmung;
DROP TABLE IF EXISTS {AW}.ausschuss;


CREATE TABLE {AW}.ausschuss AS
SELECT (data->>'id')::int                        AS aw_id,
        data->>'label'                           AS titel,
       (data->'field_legislature'->>'id')::int   AS legislatur_id,
        data->'field_legislature'->>'label'      AS legislatur,
        data->>'abgeordnetenwatch_url'           AS url
  FROM {AW}.raw_committees;
ALTER TABLE {AW}.ausschuss ADD PRIMARY KEY (aw_id);

CREATE TABLE {AW}.ausschussmitgliedschaft AS
SELECT (data->>'id')::int                          AS aw_id,
       (data->'candidacy_mandate'->>'id')::int     AS mandat_id,
       (data->'committee'->>'id')::int             AS ausschuss_id,
        data->>'committee_role'                    AS rolle,
        data->>'committee_roles_additional'        AS rolle_zusatz
  FROM {AW}.raw_committee_memberships;
ALTER TABLE {AW}.ausschussmitgliedschaft ADD PRIMARY KEY (aw_id);
CREATE INDEX ON {AW}.ausschussmitgliedschaft (mandat_id);


"""


def main():
    log.info("Lege saubere Tabellen an und fuelle sie aus dem Roh-JSONB")
    run_sql(DDL, "abstimmungen und ausschuesse")

    log.info("--- Was entstanden ist ---")
    for tab, n in query(f"""
            SELECT 'ausschuss',            count(*)::text FROM {AW}.ausschuss
            UNION ALL SELECT 'ausschussmitgliedschaft', count(*)::text FROM {AW}.ausschussmitgliedschaft
;"""):
        log.info("   %-32s %s", tab, n)


if __name__ == "__main__":
    main()
