import sys
import csv
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import DB_SCHEMA as WK_SCHEMA, run_sql, run_sql_file, query


import lieferung
LIEFERUNG = "gerda_federal_wkr_unharm"


DB_SCHEMA = "wahlergebnisse"
GERDA_SCHEMA = "gerda"


T_WAHL     = "wahl"
T_ERGEBNIS = "wahlergebnis_gerda_wahlkreis"
T_KENNZAHL = "wahlkennzahl_gerda_wahlkreis"
T_DIREKT   = "direktmandat_gerda_wahlkreis"


QUELL_DIR = (Path(__file__).resolve().parents[4]
             / "Daten" / "Wahlergebnisse" / "GERDA")

DATEI_LONG = QUELL_DIR / "federal_wkr_unharm_long.txt"
DATEI_WIDE = QUELL_DIR / "federal_wkr_unharm.txt"

JAHRE = [2013, 2017, 2021]


KOPF_LONG = [
    "election_year", "election_date", "wkr_nr", "wkr_name", "state", "state_name",
    "stimme", "party", "votes", "vote_share",
    "eligible_voters", "number_voters", "valid_votes", "invalid_votes", "turnout",
]


SPALTEN_WIDE = ["election_year", "wkr_nr", "stimme", "elected_party"]


KENNZAHLEN = {
    "eligible_voters": "wahlberechtigte",
    "number_voters":   "waehlende",
    "valid_votes":     "gueltige_stimmen",
    "invalid_votes":   "ungueltige_stimmen",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wahlergebnisse")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_WAHL} (
    wahljahr SMALLINT PRIMARY KEY,
    wahltag  DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS {GERDA_SCHEMA}.{T_ERGEBNIS} (
    wahljahr SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.{T_WAHL} (wahljahr),
    wkr_nr   SMALLINT NOT NULL,
    stimme   TEXT     NOT NULL CHECK (stimme IN ('erststimme', 'zweitstimme')),
    partei   TEXT     NOT NULL,
    stimmen  INTEGER,
    PRIMARY KEY (wahljahr, wkr_nr, stimme, partei),
    FOREIGN KEY (wahljahr, wkr_nr)
        REFERENCES {WK_SCHEMA}.wahlkreis (wahljahr, wkr_nr)
);

CREATE TABLE IF NOT EXISTS {GERDA_SCHEMA}.{T_KENNZAHL} (
    wahljahr SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.{T_WAHL} (wahljahr),
    wkr_nr   SMALLINT NOT NULL,
    stimme   TEXT     NOT NULL CHECK (stimme IN ('erststimme', 'zweitstimme')),
    merkmal  TEXT     NOT NULL,
    wert     INTEGER,
    PRIMARY KEY (wahljahr, wkr_nr, stimme, merkmal),
    FOREIGN KEY (wahljahr, wkr_nr)
        REFERENCES {WK_SCHEMA}.wahlkreis (wahljahr, wkr_nr)
);

CREATE TABLE IF NOT EXISTS {GERDA_SCHEMA}.{T_DIREKT} (
    wahljahr SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.{T_WAHL} (wahljahr),
    wkr_nr   SMALLINT NOT NULL,
    partei   TEXT,
    PRIMARY KEY (wahljahr, wkr_nr),
    FOREIGN KEY (wahljahr, wkr_nr)
        REFERENCES {WK_SCHEMA}.wahlkreis (wahljahr, wkr_nr)
);
"""


def lies(pfad, jahre, erwarteter_kopf=None, benoetigt=None):
    if not pfad.exists():
        raise SystemExit(f"Datei fehlt: {pfad}")

    try:
        with pfad.open("r", encoding="utf-8", newline="") as f:
            leser = csv.DictReader(f)
            kopf = leser.fieldnames
            if erwarteter_kopf and kopf != erwarteter_kopf:
                raise SystemExit(
                    f"{pfad.name}: unerwarteter Spaltenkopf.\n"
                    f"  erwartet: {erwarteter_kopf}\n"
                    f"  gelesen : {kopf}"
                )
            if benoetigt:
                fehlend = [s for s in benoetigt if s not in kopf]
                if fehlend:
                    raise SystemExit(f"{pfad.name}: Spalten fehlen: {fehlend}")

            gesucht = {str(j) for j in jahre}
            zeilen = [z for z in leser if z["election_year"] in gesucht]
    except UnicodeDecodeError as fehler:
        raise SystemExit(f"{pfad.name}: kein UTF-8 ({fehler})")

    gefunden = sorted({int(z["election_year"]) for z in zeilen})
    if gefunden != sorted(jahre):
        raise SystemExit(f"{pfad.name}: erwartet {sorted(jahre)}, gefunden {gefunden}")

    log.info("%s: %d Zeilen fuer %s", pfad.name, len(zeilen), gefunden)
    return zeilen


def gebietsstaende():
    zeilen = query(f"SELECT DISTINCT wahljahr FROM {WK_SCHEMA}.wahlkreis ORDER BY 1;")
    return [int(z[0]) for z in zeilen]


def zahl(wert):
    return "NULL" if wert in ("", None, "NA") else str(int(float(wert)))


def text(wert):
    return "NULL" if wert in ("", None, "NA") else "'" + wert.replace("'", "''") + "'"


def schreibe(tabelle, spalten, saetze, label):
    if not saetze:
        log.warning("%s: nichts zu schreiben", tabelle)
        return
    sql = (f"INSERT INTO {DB_SCHEMA}.{tabelle} ({', '.join(spalten)})\nVALUES\n"
           + ",\n".join("(" + ", ".join(str(w) for w in s) + ")" for s in saetze) + ";\n")
    tmp = Path(tempfile.gettempdir()) / f"wahlergebnisse_{tabelle}.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, label=label)
    tmp.unlink(missing_ok=True)
    log.info("%s: %d Zeilen", tabelle, len(saetze))


def lade(zeilen_long, zeilen_wide, jahre):
    liste = ", ".join(str(j) for j in jahre)
    run_sql(f"""
        DELETE FROM {GERDA_SCHEMA}.{T_ERGEBNIS} WHERE wahljahr IN ({liste});
        DELETE FROM {GERDA_SCHEMA}.{T_KENNZAHL} WHERE wahljahr IN ({liste});
        DELETE FROM {GERDA_SCHEMA}.{T_DIREKT}   WHERE wahljahr IN ({liste});
        DELETE FROM {DB_SCHEMA}.{T_WAHL}     WHERE wahljahr IN ({liste});
    """, "vorherigen Stand entfernen")


    tage = {}
    for z in zeilen_long:
        tage.setdefault(z["election_year"], set()).add(z["election_date"])
    for jahr, gefunden in sorted(tage.items()):
        if len(gefunden) > 1:
            raise SystemExit(f"{jahr}: mehrere Wahltage {sorted(gefunden)}")
    schreibe(T_WAHL, ["wahljahr", "wahltag"],
             [(jahr, text(next(iter(d)))) for jahr, d in sorted(tage.items())],
             "wahl")

    schreibe(
        T_ERGEBNIS, ["wahljahr", "wkr_nr", "stimme", "partei", "stimmen"],
        [(z["election_year"], z["wkr_nr"], text(z["stimme"]), text(z["party"]),
          zahl(z["votes"])) for z in zeilen_long],
        "wahlergebnis",
    )


    kennzahlen = {}
    for z in zeilen_long:
        for spalte, merkmal in KENNZAHLEN.items():
            schluessel = (z["election_year"], z["wkr_nr"], z["stimme"], merkmal)
            vorher = kennzahlen.setdefault(schluessel, z[spalte])
            if vorher != z[spalte]:
                raise SystemExit(
                    f"{schluessel}: {merkmal} uneinheitlich ({vorher} / {z[spalte]})")
    schreibe(
        T_KENNZAHL, ["wahljahr", "wkr_nr", "stimme", "merkmal", "wert"],
        [(jahr, wkr, text(stimme), text(merkmal), zahl(wert))
         for (jahr, wkr, stimme, merkmal), wert in sorted(kennzahlen.items())],
        "wahlkennzahl",
    )

    schreibe(
        T_DIREKT, ["wahljahr", "wkr_nr", "partei"],
        [(z["election_year"], z["wkr_nr"], text(z["elected_party"]))
         for z in zeilen_wide if z["stimme"] == "erststimme"],
        "direktmandat",
    )


def report(jahre):
    log.info("--- %s ---", DB_SCHEMA)
    log.info("%-6s %-12s %-11s %-9s %-11s %s",
             "Jahr", "Wahltag", "Wahlkreise", "Parteien", "Ergebnisse", "Kennzahlen")
    for jahr in jahre:
        zeilen = query(f"""
            SELECT (SELECT wahltag FROM {DB_SCHEMA}.{T_WAHL} WHERE wahljahr={jahr}),
                   (SELECT count(DISTINCT wkr_nr) FROM {GERDA_SCHEMA}.{T_ERGEBNIS} WHERE wahljahr={jahr}),
                   (SELECT count(DISTINCT partei) FROM {GERDA_SCHEMA}.{T_ERGEBNIS} WHERE wahljahr={jahr}),
                   (SELECT count(*) FROM {GERDA_SCHEMA}.{T_ERGEBNIS} WHERE wahljahr={jahr}),
                   (SELECT count(*) FROM {GERDA_SCHEMA}.{T_KENNZAHL} WHERE wahljahr={jahr});
        """)
        if zeilen:
            log.info("%-6s %-12s %-11s %-9s %-11s %s", jahr, *zeilen[0])


    abweichend = query(f"""
        SELECT count(*), coalesce(max(abs(summe - gueltig)), 0) FROM (
            SELECT sum(e.stimmen) AS summe, max(k.wert) AS gueltig
            FROM {GERDA_SCHEMA}.{T_ERGEBNIS} e
            JOIN {GERDA_SCHEMA}.{T_KENNZAHL} k
              ON (k.wahljahr, k.wkr_nr, k.stimme) = (e.wahljahr, e.wkr_nr, e.stimme)
             AND k.merkmal = 'gueltige_stimmen'
            GROUP BY e.wahljahr, e.wkr_nr, e.stimme
            HAVING sum(e.stimmen) <> max(k.wert)
        ) t;
    """)
    if abweichend:
        log.info("Summenabweichung Parteistimmen/gueltige Stimmen: %s Faelle, " "groesste Abweichung %s", *abweichend[0])


def main():
    lieferung.merke(LIEFERUNG)
    argumente = sys.argv[1:]
    if "--neu" in argumente:
        argumente.remove("--neu")
        run_sql(f'DROP SCHEMA IF EXISTS "{DB_SCHEMA}" CASCADE;', "schema verwerfen")
        log.warning("Schema %s verworfen.", DB_SCHEMA)

    jahre = [int(a) for a in argumente] or JAHRE
    unbekannt = [j for j in jahre if j not in JAHRE]
    if unbekannt:
        raise SystemExit(f"Nicht vorgesehen: {unbekannt}. Moeglich: {JAHRE}")

    run_sql(DDL, "ddl")

    ohne_stand = [j for j in jahre if j not in gebietsstaende()]
    if ohne_stand:
        raise SystemExit(
            f"Kein Wahlkreis-Gebietsstand fuer {ohne_stand} - erst lib/db.py")

    zeilen_long = lies(DATEI_LONG, jahre, erwarteter_kopf=KOPF_LONG)
    zeilen_wide = lies(DATEI_WIDE, jahre, benoetigt=SPALTEN_WIDE)

    lade(zeilen_long, zeilen_wide, jahre)
    report(jahre)


if __name__ == "__main__":
    main()
