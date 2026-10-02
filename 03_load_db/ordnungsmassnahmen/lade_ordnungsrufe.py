import csv
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import run_sql, query, _psql_args, _pg_env

SCHEMA = "parlamentsarbeit"
HIER = Path(__file__).resolve().parent
QUELLE = (HIER.parents[1] / "02_clean" / "ordnungsmassnahmen"
          / "export" / "ordnungsruf.csv")

SPALTEN = ["ordnungsruf_id", "position_id", "vorgang_id", "wahlperiode", "datum", "protokoll",
           "seite", "anzahl_rufe", "empfaenger_anzahl", "empfaenger_name",
           "empfaenger_fraktion", "empfaenger_fraktion_id", "fraktion_herkunft", "empfaenger_person", "empfaenger_status",
           "erteilt_von_person_id", "erteilt_von", "titel", "quelle"]

DDL = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA}.ordnungsruf (
    ordnungsruf_id        text PRIMARY KEY,
    position_id           text,
    vorgang_id            text,
    wahlperiode           integer,
    datum                 date,
    protokoll             text,
    seite                 integer,
    anzahl_rufe           integer,
    empfaenger_anzahl     integer,
    empfaenger_name       text,
    empfaenger_fraktion   text,
    empfaenger_fraktion_id text,
    fraktion_herkunft     text,
    empfaenger_person     text,
    empfaenger_status     text,
    erteilt_von_person_id text,
    erteilt_von           text,
    titel                 text,
    quelle                text
);
CREATE INDEX IF NOT EXISTS or_person_idx
    ON {SCHEMA}.ordnungsruf (empfaenger_person);
CREATE INDEX IF NOT EXISTS or_protokoll_idx
    ON {SCHEMA}.ordnungsruf (protokoll, seite);
"""


def main():
    if not QUELLE.exists():
        raise SystemExit(f"Fehlt: {QUELLE}")
    d = pd.read_csv(QUELLE, dtype=str, keep_default_na=False)
    fehlend = [s for s in SPALTEN if s not in d.columns]
    if fehlend:
        raise SystemExit(f"Spalten fehlen: {fehlend}")
    d = d[SPALTEN].replace("", None)

    print(f"Quelle: {QUELLE.name} — {len(d)} Zeilen")
    run_sql(DDL, "ordnungsruf")
    run_sql(f"TRUNCATE {SCHEMA}.ordnungsruf;", "ordnungsruf")

    tmp = HIER / "ordnungsruf.tsv"
    d.to_csv(tmp, index=False, sep="\t", na_rep="",
             quoting=csv.QUOTE_MINIMAL, encoding="utf-8")
    befehl = (fr"\copy {SCHEMA}.ordnungsruf ({', '.join(SPALTEN)}) "
              fr"FROM '{tmp.as_posix()}' WITH (FORMAT csv, HEADER true, "
              fr"DELIMITER E'\t')")
    proc = subprocess.run(_psql_args() + ["-c", befehl], env=_pg_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"Laden fehlgeschlagen:\n{proc.stderr}")

    n = int(query(f"SELECT count(*) FROM {SCHEMA}.ordnungsruf;")[0][0])
    print(f"geladen: {n} Zeilen (erwartet {len(d)})")
    print("\nOrdnungsrufe je Wahlperiode:")
    for z in query(f"SELECT wahlperiode, count(*), sum(anzahl_rufe) "
                   f"FROM {SCHEMA}.ordnungsruf GROUP BY 1 ORDER BY 1;"):
        print(f"  WP {z[0]}: {z[1]} Positionen, {z[2]} Rufe")
    print("\nMit Empfaenger aufgeloest: "
          f"{query(f'''SELECT count(*) FROM {SCHEMA}.ordnungsruf '''
                   f'''WHERE empfaenger_person IS NOT NULL;''')[0][0]} von {n}")
    print("\nBeispielzeilen:")
    for z in query(f"SELECT datum, protokoll, seite, empfaenger_name, "
                   f"empfaenger_fraktion, left(erteilt_von,34) "
                   f"FROM {SCHEMA}.ordnungsruf "
                   f"WHERE empfaenger_person IS NOT NULL "
                   f"ORDER BY datum LIMIT 5;"):
        print(" ", z)


if __name__ == "__main__":
    main()
