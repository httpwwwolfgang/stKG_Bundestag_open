import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "raum"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("land-zuordnung")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.gemeinde_land (
    wahljahr  SMALLINT NOT NULL,
    ags       CHAR(8)  NOT NULL,
    land      CHAR(2)  NOT NULL,
    land_name TEXT,
    PRIMARY KEY (wahljahr, ags)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.kreis_land (
    wahljahr  SMALLINT NOT NULL,
    kreis     CHAR(5)  NOT NULL,
    land      CHAR(2)  NOT NULL,
    land_name TEXT,
    PRIMARY KEY (wahljahr, kreis)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.wahlkreis_land (
    wahljahr  SMALLINT NOT NULL,
    wkr_nr    SMALLINT NOT NULL,
    land      CHAR(2)  NOT NULL,
    land_name TEXT,
    PRIMARY KEY (wahljahr, wkr_nr)
);

CREATE INDEX IF NOT EXISTS gemeinde_land_land ON {DB_SCHEMA}.gemeinde_land (wahljahr, land);
CREATE INDEX IF NOT EXISTS kreis_land_land    ON {DB_SCHEMA}.kreis_land (wahljahr, land);

COMMENT ON TABLE {DB_SCHEMA}.gemeinde_land IS
  'Gemeinde -> Bundesland je Wahl. Der Landesschluessel sind die Stellen 1-2 '
  'des AGS; keine Gemeinde liegt in zwei Laendern.';
COMMENT ON TABLE {DB_SCHEMA}.wahlkreis_land IS
  'Wahlkreis -> Bundesland je Wahl. Ein Wahlkreis darf keine Landesgrenze '
  'ueberschreiten (Par. 3 Abs. 1 Nr. 1 BWahlG) - geprueft, 299 von 299.';
"""


SQL = f"""
TRUNCATE {DB_SCHEMA}.gemeinde_land;
TRUNCATE {DB_SCHEMA}.kreis_land;
TRUNCATE {DB_SCHEMA}.wahlkreis_land;

INSERT INTO {DB_SCHEMA}.gemeinde_land (wahljahr, ags, land, land_name)
SELECT wt.jahr, g.ags, left(g.ags, 2), l.gen
FROM (SELECT substring(bezug from '[0-9]+')::smallint AS jahr, datum
      FROM zeit.stichtag WHERE art = 'wahltag') wt
JOIN {DB_SCHEMA}.gemeindestand_stichtag g ON g.stichtag = wt.datum
LEFT JOIN {DB_SCHEMA}.landstand_stichtag l
  ON l.stichtag = wt.datum AND l.ags = left(g.ags, 2);

INSERT INTO {DB_SCHEMA}.kreis_land (wahljahr, kreis, land, land_name)
SELECT wt.jahr, k.ags, left(k.ags, 2), l.gen
FROM (SELECT substring(bezug from '[0-9]+')::smallint AS jahr, datum
      FROM zeit.stichtag WHERE art = 'wahltag') wt
JOIN {DB_SCHEMA}.kreisstand_stichtag k ON k.stichtag = wt.datum
LEFT JOIN {DB_SCHEMA}.landstand_stichtag l
  ON l.stichtag = wt.datum AND l.ags = left(k.ags, 2);

INSERT INTO {DB_SCHEMA}.wahlkreis_land (wahljahr, wkr_nr, land, land_name)
SELECT w.wahljahr, w.wkr_nr, lpad(w.land_nr::text, 2, '0'), w.land_name
FROM {DB_SCHEMA}.wahlkreis w;
"""


def report():
    for tab, schluessel in (("gemeinde_land", "ags"),
                            ("kreis_land", "kreis"),
                            ("wahlkreis_land", "wkr_nr")):
        log.info("--- %s.%s ---", DB_SCHEMA, tab)
        for zeile in query(f"""
            SELECT wahljahr, count(*) AS zeilen,
                   count(DISTINCT land) AS laender,
                   count(*) FILTER (WHERE land_name IS NULL) AS ohne_name
            FROM {DB_SCHEMA}.{tab} GROUP BY 1 ORDER BY 1;
        """):
            jahr, zeilen, laender, ohne = zeile
            marke = "" if int(ohne) == 0 else f"  {ohne} OHNE LANDESNAME"
            log.info("  %s: %s Zeilen, %s Laender%s", jahr, zeilen, laender, marke)


    log.info("--- Deckt sich die Zuordnung mit dem Gebietsstand? ---")
    for zeile in query(f"""
        WITH wt AS (SELECT substring(bezug from '[0-9]+')::smallint AS jahr, datum
                    FROM zeit.stichtag WHERE art = 'wahltag')
        SELECT wt.jahr,
          (SELECT count(*) FROM {DB_SCHEMA}.gemeindestand_stichtag g
           WHERE g.stichtag = wt.datum)                       AS im_stand,
          (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_land z
           WHERE z.wahljahr = wt.jahr)                        AS zugeordnet,
          (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_land z
           WHERE z.wahljahr = wt.jahr
             AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.landstand_stichtag l
                             WHERE l.stichtag = wt.datum
                               AND l.ags = z.land))           AS land_unbekannt
        FROM wt ORDER BY 1;
    """):
        jahr, stand, zu, unbekannt = zeile
        marke = ("deckt sich" if stand == zu and int(unbekannt) == 0
                 else f"PRUEFEN ({unbekannt} ohne Land)")
        log.info("  %s: %s Gemeinden im Stand, %s zugeordnet - %s",
                 jahr, stand, zu, marke)

    log.info("--- Wahlkreise je Land, Wahl 2021 ---")
    for zeile in query(f"""
        SELECT land, max(land_name), count(*) AS wahlkreise
        FROM {DB_SCHEMA}.wahlkreis_land WHERE wahljahr = 2021
        GROUP BY 1 ORDER BY 3 DESC LIMIT 6;
    """):
        log.info("  %s %-24s %s Wahlkreise", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        for t in ("gemeinde_land", "kreis_land", "wahlkreis_land"):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;", f"{t} verwerfen")
        log.warning("Tabellen verworfen.")

    if not query(f"SELECT 1 FROM {DB_SCHEMA}.landstand_stichtag LIMIT 1;"):
        raise SystemExit("landstand_stichtag ist leer - erst load_landstand_stichtag.py")

    run_sql(DDL, "ddl")
    run_sql(SQL, "land-zuordnung")
    report()


if __name__ == "__main__":
    main()
