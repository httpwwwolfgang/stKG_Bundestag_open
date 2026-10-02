import re
import sys
import logging
import tempfile
from pathlib import Path
from datetime import datetime, date

from openpyxl import load_workbook


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query


import lieferung
LIEFERUNG = "destatis_gebietsaenderungen"


DB_SCHEMA = "roh_gemeinden"
TABELLE   = "stg_gebietsaenderung"

QUELL_DIR = (Path(__file__).resolve().parents[4]
             / "Daten" / "Gemeinde_Gebietsänderungen")


KOPF_SUCHE_BIS = 15


SPALTEN = [
    ("kennziffer",        None),
    ("regionaleinheit",   None),
    ("rs_alt",            "regionalschl"),
    ("ags_alt",           "gemeinde"),
    ("name_alt",          "name"),
    ("aenderungsart",     "nderungs"),
    ("flaeche_qm",        "che"),
    ("einwohner",         "einwohner"),
    ("rs_neu",            "regionalschl"),
    ("ags_neu",           "gemeinde"),
    ("name_neu",          "name"),
    ("datum_juristisch",  "juristisch"),
    ("datum_statistisch", "statistisch"),
]

KENNZIFFER = re.compile(r"^\d{2}/\d{4}/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gebietsaend")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    jahrgang          SMALLINT NOT NULL,
    zeile             INTEGER  NOT NULL,
    kennziffer        TEXT,
    regionaleinheit   TEXT,
    rs_alt            TEXT,
    ags_alt           TEXT,
    name_alt          TEXT,
    aenderungsart     TEXT,
    flaeche_qm        TEXT,
    einwohner         TEXT,
    rs_neu            TEXT,
    ags_neu           TEXT,
    name_neu          TEXT,
    datum_juristisch  TEXT,
    datum_statistisch TEXT,
    PRIMARY KEY (jahrgang, zeile)
);
CREATE INDEX IF NOT EXISTS idx_gebaend_alt ON {DB_SCHEMA}.{TABELLE} (ags_alt);
CREATE INDEX IF NOT EXISTS idx_gebaend_neu ON {DB_SCHEMA}.{TABELLE} (ags_neu);
"""


def _lit(text):
    return "NULL" if text in (None, "") else "'" + text.replace("'", "''") + "'"


def zelle(wert):
    if wert is None:
        return None
    if isinstance(wert, datetime):
        return wert.strftime("%d.%m.%Y")
    if isinstance(wert, date):
        return wert.strftime("%d.%m.%Y")
    if isinstance(wert, float) and wert.is_integer():
        return str(int(wert))
    text = str(wert).strip()
    return text or None


def finde_kopf(ws, datei):
    for nr, row in enumerate(ws.iter_rows(max_row=KOPF_SUCHE_BIS,
                                          max_col=len(SPALTEN),
                                          values_only=True), start=1):
        kopf = [(zelle(c) or "").lower().replace("\n", " ") for c in row]
        kopf += [""] * (len(SPALTEN) - len(kopf))
        if not ("einwohner" in kopf and any("regionalschl" in k for k in kopf)):
            continue
        fehler = [f"Spalte {i + 1} ({name}): erwartet '{teil}' in {kopf[i]!r}"
                  for i, (name, teil) in enumerate(SPALTEN)
                  if teil is not None and teil.lower() not in kopf[i]]
        if fehler:
            raise SystemExit(f"Unerwarteter Spaltenkopf in {datei} (Zeile {nr}):\n  "
                             + "\n  ".join(fehler))
        return nr
    raise SystemExit(f"Kein Spaltenkopf in den ersten {KOPF_SUCHE_BIS} Zeilen "
                     f"von {datei} gefunden.")


def lies_datei(pfad):
    wb = load_workbook(pfad, read_only=True, data_only=True)
    blaetter = [b for b in wb.sheetnames if "deckblatt" not in b.lower()]
    if len(blaetter) != 1:
        raise SystemExit(f"{pfad.name}: erwartet genau ein Datenblatt, "
                         f"gefunden {wb.sheetnames}")
    ws = wb[blaetter[0]]
    kopfzeile = finde_kopf(ws, pfad.name)

    zeilen, verworfen = [], []
    for nr, row in enumerate(ws.iter_rows(max_col=len(SPALTEN), values_only=True), start=1):
        if nr <= kopfzeile:
            continue
        werte = [zelle(c) for c in row]
        werte += [None] * (len(SPALTEN) - len(werte))
        kennziffer, einheit = werte[0], werte[1]
        if (kennziffer and KENNZIFFER.match(kennziffer)) or einheit:
            zeilen.append((nr, werte))
        elif any(w is not None for w in werte):
            verworfen.append((nr, kennziffer or ""))
    wb.close()
    return zeilen, verworfen


def lade(jahr, pfad):
    zeilen, verworfen = lies_datei(pfad)
    werte = ",\n".join(
        "(" + str(jahr) + ", " + str(nr) + ", "
        + ", ".join(_lit(w) for w in w_) + ")"
        for nr, w_ in zeilen)
    sql = (f"DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE jahrgang = {jahr};\n"
           f"INSERT INTO {DB_SCHEMA}.{TABELLE} (jahrgang, zeile, "
           + ", ".join(n for n, _ in SPALTEN) + ")\nVALUES\n" + werte + ";\n")

    tmp = Path(tempfile.gettempdir()) / f"gebietsaenderung_{jahr}.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, label=f"gebietsaenderung {jahr}")
    tmp.unlink(missing_ok=True)

    log.info("[%s] %d Datenzeilen, %d Nicht-Datenzeilen uebersprungen (Legende, " "Copyright, Leerzeilen)", jahr, len(zeilen), len(verworfen))


def report(jahre):
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    log.info("%-6s %-8s %-12s %-12s %s", "Jahr", "Zeilen", "Gemeinden", "Verbaende", "Arten")
    for jahr in jahre:
        zeilen, gem, verb, arten = query(f"""
            SELECT count(*),
                   count(*) FILTER (WHERE regionaleinheit = 'Gemeinde'),
                   count(*) FILTER (WHERE regionaleinheit = 'Gemeindeverband'),
                   string_agg(DISTINCT aenderungsart, ',' ORDER BY aenderungsart)
            FROM {DB_SCHEMA}.{TABELLE} WHERE jahrgang = {jahr};
        """)[0]
        log.info("%-6s %-8s %-12s %-12s %s", jahr, zeilen, gem, verb, arten)


    sonst = query(f"""
        SELECT regionaleinheit, count(*) FROM {DB_SCHEMA}.{TABELLE}
        WHERE regionaleinheit NOT IN ('Gemeinde', 'Gemeindeverband')
        GROUP BY 1 ORDER BY 2 DESC;
    """)
    if sonst:
        log.warning("weitere Regionaleinheiten: %s",
                    ", ".join(f"{b}: {n}" for b, n in sonst))


    vorhanden = [int(j) for (j,) in query(
        f"SELECT DISTINCT jahrgang FROM {DB_SCHEMA}.{TABELLE} ORDER BY 1;")]
    if vorhanden:
        fehlend = [j for j in range(min(vorhanden), max(vorhanden) + 1)
                   if j not in vorhanden]
        if fehlend:
            log.warning("Fehlende Jahrgaenge zwischen %s und %s: %s - die " "Fortschreibung ist dort unterbrochen",
                        min(vorhanden), max(vorhanden), fehlend)


def main():
    lieferung.merke(LIEFERUNG)
    argumente = sys.argv[1:]
    if "--neu" in argumente:
        argumente.remove("--neu")
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE};", "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    dateien = {int(p.stem): p for p in sorted(QUELL_DIR.glob("*.xlsx"))
               if p.stem.isdigit()}
    if not dateien:
        raise SystemExit(f"Keine Jahresdateien in {QUELL_DIR}")

    jahre = [int(a) for a in argumente] or sorted(dateien)
    unbekannt = [j for j in jahre if j not in dateien]
    if unbekannt:
        raise SystemExit(f"Keine Datei fuer {unbekannt}. Vorhanden: {sorted(dateien)}")

    run_sql(DDL, "ddl")
    for jahr in jahre:
        log.info("[%s] lese %s", jahr, dateien[jahr].name)
        lade(jahr, dateien[jahr])
    report(jahre)


if __name__ == "__main__":
    main()
