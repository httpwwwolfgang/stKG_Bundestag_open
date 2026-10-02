import csv
import subprocess
from datetime import datetime
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import run_sql, query, _psql_args, _pg_env

SCHEMA = "parlamentsarbeit"
HIER = Path(__file__).resolve().parent
QUELLE = HIER.parents[1] / "02_clean" / "personen" / "export"


TABELLEN = [
    ("person", "person.csv", """
        person            text PRIMARY KEY,
        nachname          text,
        vorname           text,
        anzeige           text,
        kennungen_anzahl  integer,
        systeme           text,
        nur_eine_quelle   boolean"""),
    ("person_kennung", "person_kennung.csv", """
        person               text,
        system               text,
        kennung              text,
        im_rednerverzeichnis text"""),
    ("person_alias", "person_alias.csv", """
        person       text,
        quelle       text,
        nachname     text,
        vorname      text,
        namenszusatz text,
        titel        text,
        ortszusatz   text"""),
    ("person_rolle", "person_rolle.csv", """
        person             text,
        system             text,
        kennung            text,
        quelle             text,
        art                text,
        wert               text,
        rolle_normalisiert text,
        ebene              text,
        wahlperiode        text,
        wahlperiode_quelle text,
        fraktion           text,
        ressort            text,
        bundesland         text,
        wahlkreis          text,
        belege             integer,
        belege_gesamt      integer,
        belege_zeitraum    text"""),
    ("person_fraktion", "person_fraktion.csv", """
        person             text,
        system             text,
        kennung            text,
        quelle             text,
        fraktion           text,
        wahlperiode        text,
        wahlperiode_quelle text,
        zeitrichtig        boolean,
        belege             integer,
        belege_gesamt      integer,
        belege_zeitraum    text"""),
    ("rolle", "rolle.csv", """
        quelle   text,
        art      text,
        wert     text,
        personen integer,
        zeilen   integer"""),
    ("rollen_normalisierung", "rollen_normalisierung.csv", """
        quelle             text,
        art                text,
        wert               text,
        rolle_normalisiert text,
        ressort            text,
        ressort_herkunft   text,
        ebene              text,
        personen           integer,
        regel              text,
        anmerkung          text"""),
]

INDIZES = f"""
CREATE INDEX IF NOT EXISTS pk_kennung_idx
    ON {SCHEMA}.person_kennung (system, kennung);
CREATE INDEX IF NOT EXISTS pk_person_idx
    ON {SCHEMA}.person_kennung (person);
CREATE INDEX IF NOT EXISTS pr_person_idx
    ON {SCHEMA}.person_rolle (person, wahlperiode);
CREATE INDEX IF NOT EXISTS pr_rolle_idx
    ON {SCHEMA}.person_rolle (rolle_normalisiert);
CREATE INDEX IF NOT EXISTS pf_person_idx
    ON {SCHEMA}.person_fraktion (person, wahlperiode);
CREATE INDEX IF NOT EXISTS pa_nachname_idx
    ON {SCHEMA}.person_alias (nachname);
"""


SICHT = f"""
CREATE OR REPLACE VIEW {SCHEMA}.person_uebersicht AS
SELECT p.person, p.anzeige, p.nachname, p.vorname,
       max(k.kennung) FILTER (WHERE k.system = 'dip') AS dip_person_id,
       max(k.kennung) FILTER (WHERE k.system = 'aw')  AS aw_id,
       string_agg(DISTINCT k.kennung, '; ')
           FILTER (WHERE k.system = 'btv')            AS btv_kennungen,
       bool_or(k.im_rednerverzeichnis = 'True')       AS hat_geredet
FROM {SCHEMA}.person p
LEFT JOIN {SCHEMA}.person_kennung k USING (person)
GROUP BY p.person, p.anzeige, p.nachname, p.vorname;
"""


def lade(tabelle, datei, ddl):
    pfad = QUELLE / datei
    if not pfad.exists():
        raise SystemExit(f"Fehlt: {pfad}")
    d = pd.read_csv(pfad, dtype=str, keep_default_na=False, low_memory=False)
    spalten = [z.strip().split()[0] for z in ddl.strip().split("\n")
               if z.strip()]
    fehlend = [s for s in spalten if s not in d.columns]
    if fehlend:
        raise SystemExit(f"{tabelle}: Spalten fehlen in {datei}: {fehlend}")
    d = d[spalten].replace("", None)

    run_sql(f"CREATE TABLE IF NOT EXISTS {SCHEMA}.{tabelle} ({ddl});", tabelle)
    run_sql(f"TRUNCATE {SCHEMA}.{tabelle} CASCADE;", tabelle)

    tmp = HIER / f"{tabelle}.tsv"
    d.to_csv(tmp, index=False, sep="\t", na_rep="",
             quoting=csv.QUOTE_MINIMAL, encoding="utf-8")
    befehl = (fr"\copy {SCHEMA}.{tabelle} ({', '.join(spalten)}) "
              fr"FROM '{tmp.as_posix()}' WITH (FORMAT csv, HEADER true, "
              fr"DELIMITER E'\t')")
    proc = subprocess.run(_psql_args() + ["-c", befehl], env=_pg_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"{tabelle} laden fehlgeschlagen:\n{proc.stderr}")
    n = int(query(f"SELECT count(*) FROM {SCHEMA}.{tabelle};")[0][0])
    zeichen = "ok " if n == len(d) else "!! "
    print(f"  {zeichen}{n:>8,}  {tabelle:<24} erwartet {len(d):>8,}")
    tmp.unlink(missing_ok=True)
    return n == len(d)


def sichere():
    stempel = datetime.now().strftime("%Y%m%d")
    gesichert = []
    for tabelle, _, _ in TABELLEN:
        da = query("SELECT count(*) FROM information_schema.tables "
                   f"WHERE table_schema='{SCHEMA}' AND table_name='{tabelle}';")
        if not int(str(da[0][0]).strip()):
            continue
        ziel = f"{tabelle}_vor_{stempel}"
        run_sql(f"DROP TABLE IF EXISTS {SCHEMA}.{ziel};", ziel)
        run_sql(f"CREATE TABLE {SCHEMA}.{ziel} AS "
                f"SELECT * FROM {SCHEMA}.{tabelle};", ziel)
        n = int(str(query(f"SELECT count(*) FROM {SCHEMA}.{ziel};")[0][0]).strip())
        gesichert.append((ziel, n))
    if gesichert:
        print("Gesichert:")
        for ziel, n in gesichert:
            print(f"  {n:>8,}  {SCHEMA}.{ziel}")
        print("  Wegwerfen mit: DROP TABLE "
              + ", ".join(f"{SCHEMA}.{z}" for z, _ in gesichert) + ";")
    else:
        print("Nichts zu sichern -- die Tabellen gibt es noch nicht.")
    print()


def main():
    print(f"Quelle: {QUELLE}\n")
    sichere()
    alles_gut = all([lade(t, f, d) for t, f, d in TABELLEN])
    run_sql(INDIZES, "indizes")
    run_sql(SICHT, "person_uebersicht")
    print(f"\n{'Alle Tabellen stimmen.' if alles_gut else 'ABWEICHUNGEN, siehe oben.'}")

    print("\n----- Gegenprobe: die Kette bis zum Wahlkreis -----")
    for frage, sql in (
        ("Personen", f"SELECT count(*) FROM {SCHEMA}.person"),
        ("Kennungen", f"SELECT count(*) FROM {SCHEMA}.person_kennung"),
        ("mit Bundestagsmandat",
         f"SELECT count(DISTINCT person) FROM {SCHEMA}.person_rolle "
         f"WHERE quelle = 'mandat'"),
        ("Drucksachen-Beteiligungen mit Person",
         f"SELECT count(*) FROM {SCHEMA}.drucksache_person dp "
         f"JOIN {SCHEMA}.person_kennung k "
         f"  ON k.system = 'dip' AND k.kennung = dp.person_id"),
        ("Ordnungsrufe mit Person",
         f"SELECT count(*) FROM {SCHEMA}.ordnungsruf o "
         f"JOIN {SCHEMA}.person p ON p.person = o.empfaenger_person"),
    ):
        print(f"  {frage:<38} {int(query(sql + ';')[0][0]):>9,}")


if __name__ == "__main__":
    main()
