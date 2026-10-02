import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA = "meta"
TABELLE   = "gebietsbezug"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gebietsbezug")


BEZUEGE = [

    ("raum.gemeindestand", None, "flaeche", "jahresstand", "abweichend",
     "VG250-Jahresstaende zum 31.12., zwoelf Staende 2010-2021. Grundlage " "aller abgeleiteten Flaechen."),
    ("raum.kreisstand", None, "flaeche", "jahresstand", "abweichend",
     "VG250-Kreisebene zum 31.12., dieselben zwoelf Staende. Der Bezug zum " "Wahltag steht in kreisstand_stichtag."),
    ("raum.kreisstand_stichtag", None, "flaeche", "mehrere", "exakt",
     "Kreise je Stichtag, aus dem Jahrgang, der am Stichtag galt. " "quelle_stand haelt ihn je Zeile fest."),
    ("raum.landstand", None, "flaeche", "einheitlich", "bewusst_abweichend",
     "VG250-Landesebene, EIN Stand: 31.12.2021. Auf dieser Ebene gibt es null " "Gebietsuebergaenge und in zwoelf Jahrgaengen dieselben 16 Schluessel; " "was sich unterscheidet, ist Vermessung."),
    ("raum.landstand_stichtag", None, "flaeche", "einheitlich", "bewusst_abweichend",
     "Jeder Stichtag traegt die Geometrie vom 31.12.2021, auch die Wahltage " "2013 und 2017. Begruendet: auf Landesebene gibt es null Uebergaenge, " "dieselben 16 Schluessel und Namen in allen zwoelf Jahrgaengen. Was sich " "unterscheidet, ist Vermessung - Berlin 2013 gegen 2021 um 0,024 % der " "Flaeche. Eine Geometrie je Land heisst: Zeitvergleiche zeigen " "Unterschiede in den Zahlen, nicht im Umriss."),
    ("raum.gemeinde_land", None, "zuordnung", "wahltag", "exakt",
     "Gemeinde -> Land je Wahl, aus den Stellen 1-2 des AGS. Keine Gemeinde " "liegt in zwei Laendern."),
    ("raum.kreis_land", None, "zuordnung", "wahltag", "exakt",
     "Kreis -> Land je Wahl, aus den Stellen 1-2 des Kreisschluessels."),
    ("raum.wahlkreis_land", None, "zuordnung", "wahltag", "exakt",
     "Wahlkreis -> Land je Wahl. Ein Wahlkreis darf keine Landesgrenze " "ueberschreiten (Par. 3 Abs. 1 Nr. 1 BWahlG); geprueft an den Gemeinden, " "299 von 299 in genau einem Land."),
    ("raum.gemeindestand_stichtag", None, "flaeche", "mehrere", "exakt",
     "Zu jedem Stichtag aus zeit.stichtag gebildet, darunter die drei " "Wahltage. Hieraus beziehen alle Ergebnis-Layer ihre Flaeche."),
    ("raum.gebietsuebergang", None, "zuordnung", "jahresstand", "abweichend",
     "Uebergaenge zwischen den Jahresstaenden, datiert nach dem juristischen " "Wirksamkeitsdatum der Quelle - kein eigener Gebietsstand."),


    ("raum.wahlkreis", 2013, "flaeche", "gebietsstand_wahlkreise",
     "abweichend",
     "Zuschnitt nach dem Stand 30.09.2011 (Rheinland-Pfalz 01.01.2012), also " "fast zwei Jahre vor der Wahl. Geometrie ist VG1000, nicht VG250 - " "."),
    ("raum.wahlkreis", 2017, "flaeche", "gebietsstand_wahlkreise",
     "abweichend", "Zuschnitt nach dem Stand 29.02.2016."),
    ("raum.wahlkreis", 2021, "flaeche", "gebietsstand_wahlkreise",
     "abweichend", "Zuschnitt nach dem Stand 15.04.2020."),
    ("raum.wahlkreisuebergang", None, "zuordnung",
     "gebietsstand_zuordnungsliste", "abweichend",
     "Mengenvergleich der Gemeinden zwischen den Staenden der " "Zuordnungslisten, nicht zwischen den Wahltagen."),


    ("archiv.gemeinde_wahlkreis", 2013, "zuordnung",
     "gebietsstand_zuordnungsliste", "abweichend",
     "Aus GV100AD zum 31.12.2013, also NACH dem Wahltag. Eine Zuordnungsliste " "der Bundeswahlleiterin gibt es fuer 2013 nicht."),
    ("archiv.gemeinde_wahlkreis", 2017, "zuordnung",
     "gebietsstand_zuordnungsliste", "abweichend",
     "Amtliche Zuordnungsliste zum 28.02.2017, sieben Monate vor der Wahl."),
    ("archiv.gemeinde_wahlkreis", 2021, "zuordnung",
     "gebietsstand_zuordnungsliste", "abweichend",
     "Amtliche Zuordnungsliste zum 15.04.2020, siebzehn Monate vor der Wahl."),
    ("raum.gemeindefreies_gebiet", None, "flaeche", "mehrere", "exakt",
     "Sicht auf gemeindestand_stichtag, traegt deshalb dessen Stand je " "Stichtag. Die angehaengte Spalte wkr_nr stammt dagegen aus der " "Zuordnungsliste und hat deren abweichenden Gebietsstand - fuer " "unbewohnte Gebiete folgenlos, sie liefern keine Stimmen."),
    ("raum.gemeinde_wahlkreis_wahltag", None, "zuordnung", "wahltag", "exakt",
     "Wer tatsaechlich wo gewaehlt hat, im Gebietsstand des Wahltags. Zu 97 % " "direkt aus den Wahlbezirken, wo Gemeinde und Wahlkreis in derselben " "Zeile stehen. Die Spalte herkunft haelt je Zeile fest, woher sie stammt; " "nur die gemeindefreien Gebiete brauchen die Zuordnungsliste."),
    ]


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    objekt        TEXT     NOT NULL,
    wahljahr      SMALLINT,
    rolle         TEXT     NOT NULL,
    stichtag_art  TEXT     NOT NULL,
    stichtag      DATE,
    passung       TEXT     NOT NULL,
    bemerkung     TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS {TABELLE}_key
    ON {DB_SCHEMA}.{TABELLE} (objekt, coalesce(wahljahr, 0), rolle);
"""


def literal(wert):
    if wert is None:
        return "NULL"
    if isinstance(wert, int):
        return str(wert)
    return "'" + wert.replace("'", "''") + "'"


def lade():
    zeilen = []
    for objekt, jahr, rolle, art, passung, bemerkung in BEZUEGE:
        zeilen.append("(" + ", ".join([
            literal(objekt), literal(jahr), literal(rolle), literal(art),
            literal(passung), literal(bemerkung)]) + ")")

    run_sql(f"""
        TRUNCATE {DB_SCHEMA}.{TABELLE};

        INSERT INTO {DB_SCHEMA}.{TABELLE}
            (objekt, wahljahr, rolle, stichtag_art, passung, bemerkung)
        VALUES {", ".join(zeilen)};







        UPDATE {DB_SCHEMA}.{TABELLE} b
        SET stichtag = s.datum
        FROM (SELECT DISTINCT ON (art, bezug) art, bezug, datum
              FROM zeit.stichtag ORDER BY art, bezug, datum) s
        WHERE s.art = b.stichtag_art
          AND s.bezug = 'Wahl ' || b.wahljahr::text
          AND b.wahljahr IS NOT NULL;
    """, "gebietsbezug")


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT passung, count(*) FROM {DB_SCHEMA}.{TABELLE}
        GROUP BY 1 ORDER BY 2 DESC;
    """):
        log.info("  %-12s %s", *zeile)

    log.info("--- Objekte mit MEHREREN Gebietsstaenden (die heiklen) ---")
    for zeile in query(f"""
        SELECT objekt, string_agg(DISTINCT rolle || ':' || stichtag_art, ', ')
        FROM {DB_SCHEMA}.{TABELLE}
        GROUP BY objekt
        HAVING count(DISTINCT stichtag_art) > 1
        ORDER BY objekt;
    """):
        log.info("  %-42s %s", *zeile)

    log.info("--- Was NICHT am Wahltag haengt ---")
    for zeile in query(f"""
        SELECT objekt, coalesce(wahljahr::text, 'alle'), rolle, stichtag_art,
               coalesce(stichtag::text, '-')
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE passung <> 'exakt' ORDER BY objekt, wahljahr;
    """):
        log.info("  %-38s %-5s %-13s %-28s %s", *zeile)


def pruefe():
    fehlend = query(f"""
        SELECT n.nspname || '.' || c.relname AS objekt
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname IN ('gemeinden', 'wahlkreise', 'wahlergebnisse', 'gerda')
          AND c.relkind IN ('r', 'm')
          AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} b
                          WHERE b.objekt = n.nspname || '.' || c.relname)
        ORDER BY 1;
    """)
    if fehlend:
        log.warning("%s Objekte ohne Gebietsbezug:", len(fehlend))
        for (objekt,) in fehlend:
            log.warning("    %s", objekt)
    else:
        log.info("Alle Objekte haben einen Gebietsbezug.")


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;",
                "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    run_sql(DDL, "ddl")
    lade()
    report()
    pruefe()


if __name__ == "__main__":
    main()
