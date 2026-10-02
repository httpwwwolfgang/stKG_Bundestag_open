import csv
import glob
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import run_sql, query, _psql_args, _pg_env

SCHEMA = "politiker_innen"
TABELLE = "wikidata_amt"
QUELLE = (Path(__file__).resolve().parents[2] / "01_fetch" / "wikidata"
          / "export")

DDL = """
    aw_id            integer,
    qid              text,
    amt_qid          text,
    amt              text,
    ressort          text,
    wahlperiode      text,
    von              date,
    von_genauigkeit  text,
    bis              date,
    bis_genauigkeit  text,
    abgerufen_am     text"""


GENAUIGKEIT = {"11": "tag", "10": "monat", "9": "jahr", "8": "jahrzehnt",
               "7": "jahrhundert"}


def datum(wert):
    if not wert:
        return ""
    return str(wert)[:10]


def main():
    treffer = sorted(glob.glob(str(QUELLE / "wikidata_aemter_*.json")))
    if not treffer:
        raise SystemExit("Keine JSON in %s -- erst hole_aemter.py" % QUELLE)
    datei = Path(treffer[-1])
    inhalt = json.loads(datei.read_text(encoding="utf-8"))
    aussagen = inhalt["aussagen"]
    aw_je_qid = inhalt["aw_id_je_qid"]
    print("gelesen: %s  (%d Aussagen, %d Personen, abgerufen %s)"
          % (datei.name, len(aussagen), len(aw_je_qid), inhalt["abgerufen_am"]))

    run_sql("CREATE TABLE IF NOT EXISTS %s.%s (%s);" % (SCHEMA, TABELLE, DDL),
            TABELLE)
    run_sql("TRUNCATE %s.%s;" % (SCHEMA, TABELLE), TABELLE)

    tmp = Path(__file__).resolve().parent / ("%s.tsv" % TABELLE)
    ohne_person = 0
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        schreiber = csv.writer(f, delimiter="\t", quoting=csv.QUOTE_MINIMAL,
                               lineterminator="\n")
        for a in aussagen:
            aw = aw_je_qid.get(a["qid"])
            if aw is None:
                ohne_person += 1
                continue
            schreiber.writerow([
                aw, a["qid"], a.get("amt_qid") or "", a.get("amt") or "",
                a.get("ressort") or "", a.get("wahlperiode") or "",
                datum(a.get("von")),
                GENAUIGKEIT.get(str(a.get("von_prec") or ""), ""),
                datum(a.get("bis")),
                GENAUIGKEIT.get(str(a.get("bis_prec") or ""), ""),
                inhalt["abgerufen_am"]])

    befehl = ("\\copy %s.%s FROM '%s' WITH (FORMAT csv, DELIMITER E'\\t')"
              % (SCHEMA, TABELLE, tmp.as_posix()))
    proc = subprocess.run(_psql_args() + ["-c", befehl], env=_pg_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit("Laden fehlgeschlagen:\n%s" % proc.stderr)
    tmp.unlink(missing_ok=True)

    if ohne_person:
        print("  %d Aussagen ohne Zuordnung zu einer aw-Kennung " "-- nicht geladen" % ohne_person)

    print()
    for frage, sql in (
        ("Zeilen", "SELECT count(*) FROM %s.%s" % (SCHEMA, TABELLE)),
        ("verschiedene Aemter",
         "SELECT count(DISTINCT amt) FROM %s.%s" % (SCHEMA, TABELLE)),
        ("Personen",
         "SELECT count(DISTINCT aw_id) FROM %s.%s" % (SCHEMA, TABELLE)),
        ("mit Beginn",
         "SELECT count(von) FROM %s.%s" % (SCHEMA, TABELLE)),
        ("mit Ende",
         "SELECT count(bis) FROM %s.%s" % (SCHEMA, TABELLE)),
        ("davon Bundestagsmandat",
         "SELECT count(*) FROM %s.%s WHERE amt = " "'Mitglied des Deutschen Bundestages'" % (SCHEMA, TABELLE)),
    ):
        print("  %-28s %8s" % (frage, str(query(sql)[0][0]).strip()))

    print()
    print("  Genauigkeit der Beginndaten:")
    for r in query("SELECT coalesce(von_genauigkeit,'(ohne)'), count(*) " "FROM %s.%s GROUP BY 1 ORDER BY 2 DESC" % (SCHEMA, TABELLE)):
        print("     %-12s %6s" % (str(r[0]).strip(), str(r[1]).strip()))


if __name__ == "__main__":
    main()
