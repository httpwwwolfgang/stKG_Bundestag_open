import csv
import glob
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import run_sql, query, _psql_args, _pg_env


import lieferung
LIEFERUNG = "wikidata_eigenschaftsklassen"

SCHEMA = "politiker_innen"
TABELLE = "wikidata_eigenschaft_klasse"
QUELLE = (Path(__file__).resolve().parents[2] / "01_fetch" / "wikidata"
          / "export")


NAME = "Q19643892"
KONTO = "Q105388954"
NETZWERK = "Q3220391"


def klasse(e):
    arten = {a["qid"] for a in e["art"]}
    gegenstandsarten = {a["qid"] for a in e["gegenstand_art"]}
    if NAME in arten:
        return "namensvariante"
    if KONTO in arten or NETZWERK in gegenstandsarten:
        return "konto"
    if e["typ_db"] == "Url":
        return "webadresse"
    return "kennung"


def neueste_datei():
    treffer = sorted(glob.glob(str(QUELLE / "wikidata_eigenschaftsklassen_*.json")))
    if not treffer:
        raise SystemExit("Keine JSON in %s -- erst hole_eigenschaftsklassen.py"
                         % QUELLE)
    return Path(treffer[-1])


def main():
    lieferung.merke(LIEFERUNG)
    datei = neueste_datei()
    inhalt = json.loads(datei.read_text(encoding="utf-8"))
    eigenschaften = inhalt["eigenschaften"]
    print("gelesen: %s  (%d Eigenschaften, abgerufen %s)"
          % (datei.name, len(eigenschaften), inhalt["abgerufen_am"]))

    run_sql(f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA}.{TABELLE} (
            p_nummer         text PRIMARY KEY,
            label            text,
            datentyp         text,
            klasse           text,
            gegenstand_qid   text,
            gegenstand_label text,
            art_qids         text,
            art_labels       text,
            format_url       text,
            beschreibung     text,
            abgerufen_am     text
        );""", TABELLE)
    run_sql(f"TRUNCATE {SCHEMA}.{TABELLE};", TABELLE)

    zeilen = []
    for p, e in sorted(eigenschaften.items()):
        gegenstand = e["gegenstand"][0] if e["gegenstand"] else {}
        zeilen.append((
            p, e["label_db"], e["typ_db"], klasse(e),
            gegenstand.get("qid"), gegenstand.get("label"),
            "; ".join(a["qid"] for a in e["art"]),
            "; ".join(str(a["label"]) for a in e["art"]),
            e["format_url"][0] if e["format_url"] else None,
            e["beschreibung"], inhalt["abgerufen_am"]))


    tmp = Path(__file__).resolve().parent / f"{TABELLE}.tsv"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        schreiber = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL,
                               lineterminator="\n")
        for z in zeilen:
            schreiber.writerow(["" if x is None else
                                str(x).replace("\t", " ").replace("\n", " ")
                                for x in z])
    befehl = (f"\\copy {SCHEMA}.{TABELLE} FROM '{tmp.as_posix()}' "
              f"WITH (FORMAT csv, DELIMITER E'\\t')")
    proc = subprocess.run(_psql_args() + ["-c", befehl], env=_pg_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"Laden fehlgeschlagen:\n{proc.stderr}")
    tmp.unlink(missing_ok=True)

    print()
    for r in query(f"SELECT klasse, count(*) FROM {SCHEMA}.{TABELLE} " "GROUP BY klasse ORDER BY count(*) DESC;"):
        print("  %-16s %5s" % (str(r[0]).strip(), str(r[1]).strip()))
    print()
    print("  Konten mit ihrer Plattform:")
    for r in query(f"""SELECT p_nummer, label, coalesce(gegenstand_label,'--')
                         FROM {SCHEMA}.{TABELLE} WHERE klasse='konto'
                        ORDER BY p_nummer;"""):
        print("      %-9s %-40s %s"
              % tuple(str(x).strip()[:40] for x in r))


if __name__ == "__main__":
    main()
