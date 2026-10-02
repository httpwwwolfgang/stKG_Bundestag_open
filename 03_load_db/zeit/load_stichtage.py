import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "zeit"
TABELLE   = "stichtag"


STICHTAGE = [
    ("2011-09-30", "gebietsstand_wahlkreise",
     "Gebietsstand der Wahlkreisbeschreibung", "Wahl 2013", "Bundeswahlleiterin"),
    ("2012-01-01", "gebietsstand_wahlkreise",
     "Gebietsstand der Wahlkreisbeschreibung, Rheinland-Pfalz",
     "Wahl 2013", "Bundeswahlleiterin; fuer RLP abweichender Stand"),
    ("2013-09-22", "wahltag", "Bundestagswahl 2013",
     "Wahl 2013", "Bundeswahlleiterin; GERDA election_date"),
    ("2013-10-22", "beginn_wahlperiode", "Zusammentritt 18. Bundestag",
     "WP18", "Art. 39 Abs. 2 GG, 30. Tag nach der Wahl"),
    ("2013-12-31", "gebietsstand_zuordnungsliste",
     "Gemeindestand der Zuordnung Gemeinde-Wahlkreis, liegt nach dem Wahltag",
     "Wahl 2013", "Destatis GV100AD_311213; eine Zuordnungsliste der " "Bundeswahlleiterin liegt fuer 2013 nicht vor"),

    ("2016-02-29", "gebietsstand_wahlkreise",
     "Gebietsstand der Wahlkreisbeschreibung", "Wahl 2017", "Bundeswahlleiterin"),
    ("2017-02-28", "gebietsstand_zuordnungsliste",
     "Gemeindestand der amtlichen Zuordnung Gemeinde-Wahlkreis",
     "Wahl 2017", "Bundeswahlleiterin, Datei 20170228_BTW17_WKr_Gemeinden"),
    ("2017-09-24", "wahltag", "Bundestagswahl 2017",
     "Wahl 2017", "Bundeswahlleiterin; GERDA election_date"),
    ("2017-10-24", "ende_wahlperiode", "Ende mit Zusammentritt des 19. Bundestages",
     "WP18", "Art. 39 Abs. 1 Satz 2 GG"),
    ("2017-10-24", "beginn_wahlperiode", "Zusammentritt 19. Bundestag",
     "WP19", "Art. 39 Abs. 2 GG, 30. Tag nach der Wahl"),

    ("2020-04-15", "gebietsstand_wahlkreise",
     "Gebietsstand der Wahlkreisbeschreibung", "Wahl 2021", "Bundeswahlleiterin"),
    ("2020-04-15", "gebietsstand_zuordnungsliste",
     "Gemeindestand der amtlichen Zuordnung Gemeinde-Wahlkreis",
     "Wahl 2021", "Bundeswahlleiterin, Datei 20200415_btw21_wkr_gemeinden"),
    ("2021-09-26", "wahltag", "Bundestagswahl 2021",
     "Wahl 2021", "Bundeswahlleiterin; GERDA election_date"),
    ("2021-10-26", "ende_wahlperiode", "Ende mit Zusammentritt des 20. Bundestages",
     "WP19", "Art. 39 Abs. 1 Satz 2 GG"),
    ("2021-10-26", "beginn_wahlperiode", "Zusammentritt 20. Bundestag",
     "WP20", "Art. 39 Abs. 2 GG, 30. Tag nach der Wahl"),

    ("2025-03-25", "ende_wahlperiode", "Ende mit Zusammentritt des 21. Bundestages",
     "WP20", "Art. 39 Abs. 1 Satz 2 GG"),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("stichtage")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    datum       DATE NOT NULL,
    art         TEXT NOT NULL,
    bezeichnung TEXT NOT NULL,
    bezug       TEXT,
    quelle      TEXT NOT NULL,
    PRIMARY KEY (datum, art, bezeichnung)
);
"""


def literal(wert):
    return "NULL" if wert is None else "'" + wert.replace("'", "''") + "'"


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f'DROP SCHEMA IF EXISTS "{DB_SCHEMA}" CASCADE;', "schema verwerfen")
        log.warning("Schema %s verworfen.", DB_SCHEMA)

    run_sql(DDL, "ddl")

    werte = ",\n".join("(" + ", ".join(literal(f) for f in e) + ")" for e in STICHTAGE)
    run_sql(f"""
        TRUNCATE {DB_SCHEMA}.{TABELLE};
        INSERT INTO {DB_SCHEMA}.{TABELLE} (datum, art, bezeichnung, bezug, quelle)
        VALUES
{werte};
    """, "stichtage")

    log.info("%d Stichtage geschrieben", len(STICHTAGE))
    for zeile in query(f"""
        SELECT to_char(datum, 'DD.MM.YYYY'), art, coalesce(bezug, ''), bezeichnung
        FROM {DB_SCHEMA}.{TABELLE} ORDER BY datum, art;
    """):
        log.info("  %-11s %-24s %-10s %s", *zeile)


if __name__ == "__main__":
    main()
