import sys
import csv
import time
import logging
import os
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query


import lieferung
LIEFERUNG = "bbsr_inkar_2024"

DB_SCHEMA = "strukturdaten_roh"
TABELLE   = "inkar"
DATEN     = Path(__file__).resolve().parents[4] / "Daten" / "Strukturdaten"


DATEN_AUSGELAGERT = Path(os.environ.get(
    "INKAR_DATEN", "PFAD_ZU_DATEN"))


def quelldatei(verzeichnis, dateiname):
    for basis in (DATEN, DATEN_AUSGELAGERT):
        p = basis / verzeichnis / dateiname
        if p.exists():
            return p
    return DATEN / verzeichnis / dateiname


AUSGABEN = {
    "inkar_2021": ("inkar_2021", "inkar_2021.csv", "2019-12-31"),
    "inkar_2022": ("inkar_2022", "inkar_2022.csv", "2020-12-31"),
    "inkar_2024": ("inkar_2024", "inkar_2024.csv", "2022-12-31"),
    "inkar_2025": ("inkar_2025", "inkar_2025.csv", "2023-12-31"),
}
STANDARD = ["inkar_2024"]


PFLICHT  = ("Bereich", "ID", "Indikator", "Raumbezug", "Kennziffer",
            "Name", "Zeitbezug", "Wert")
OPTIONAL = ("Kuerzel",)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inkar-roh")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    ausgabe       TEXT    NOT NULL,
    zeile         INTEGER NOT NULL,
    bereich       TEXT,
    id            TEXT,
    kuerzel       TEXT,
    indikator     TEXT,
    raumbezug     TEXT,
    kennziffer    TEXT,
    name          TEXT,
    zeitbezug     TEXT,
    wert          TEXT,
    PRIMARY KEY (ausgabe, zeile)
);

CREATE INDEX IF NOT EXISTS {TABELLE}_zugriff
    ON {DB_SCHEMA}.{TABELLE} (ausgabe, raumbezug, kennziffer);
CREATE INDEX IF NOT EXISTS {TABELLE}_indikator
    ON {DB_SCHEMA}.{TABELLE} (ausgabe, bereich, indikator);

COMMENT ON TABLE {DB_SCHEMA}.{TABELLE} IS
  'INKAR-Gesamtdatei des BBSR, Rohschicht, vollstaendig - alle 45 '
  'Raumbezugsebenen. Darunter Gebietseinheiten (Gemeinden, Kreise, '
  'Arbeitsmarktregionen ...) und Typisierungen (Stadt- und Gemeindetyp, '
  'RegioStaR ...), deren Werte Aggregate je Klasse sind. Alles TEXT, '
  'Dezimalkomma unveraendert. Kennziffern sind nur je raumbezug eindeutig.';
COMMENT ON COLUMN {DB_SCHEMA}.{TABELLE}.ausgabe IS
  'Welche INKAR-Ausgabe. Bestimmt den Gebietsstand: 2022 -> 31.12.2020, '
  '2024 -> 31.12.2022. Werte verschiedener Ausgaben sind nicht ohne weiteres '
  'vergleichbar, weil jede auf ihren eigenen Stand zeitreihenbereinigt ist.';
"""


def lies(ausgabe, pfad, ziel_csv):
    n, raus = 0, 0
    ebenen = {}
    t0 = time.time()
    with pfad.open(encoding="utf-8", errors="replace", newline="") as fh, \
         ziel_csv.open("w", encoding="utf-8", newline="") as out:
        kopf = fh.readline().rstrip("\r\n").split(";")
        fehlt = [s for s in PFLICHT if s not in kopf]
        if fehlt:
            raise SystemExit(f"{pfad.name}: Spalten fehlen: {', '.join(fehlt)}")
        i = {s: kopf.index(s) for s in PFLICHT}
        i.update({s: kopf.index(s) for s in OPTIONAL if s in kopf})
        hoechster = max(i.values())
        schreiber = csv.writer(out)
        for zeile in fh:
            n += 1
            f = zeile.rstrip("\r\n").split(";")
            if len(f) <= hoechster:
                continue
            rb = f[i["Raumbezug"]]
            ebenen[rb] = ebenen.get(rb, 0) + 1
            schreiber.writerow([
                ausgabe, n,
                f[i["Bereich"]], f[i["ID"]],
                f[i["Kuerzel"]] if "Kuerzel" in i else "",
                f[i["Indikator"]], rb, f[i["Kennziffer"]].strip(),
                f[i["Name"]], f[i["Zeitbezug"]].strip(), f[i["Wert"]].strip(),
            ])
            raus += 1
    log.info("  %s: %s Zeilen gelesen, %s uebernommen (%.0f s)",
             ausgabe, f"{n:,}".replace(",", "."),
             f"{raus:,}".replace(",", "."), time.time() - t0)
    log.info("      %d Raumbezugsebenen, die zehn groessten:", len(ebenen))
    for rb, c in sorted(ebenen.items(), key=lambda x: -x[1])[:10]:
        log.info("        %-42s %12s", rb[:42], f"{c:,}".replace(",", "."))
    return raus


def laden(ausgabe):
    verz, datei, stand = AUSGABEN[ausgabe]
    pfad = quelldatei(verz, datei)
    if not pfad.exists():
        raise SystemExit(
            f"{pfad} fehlt. Gesucht wurde in {DATEN / verz} und in "
            f"{DATEN_AUSGELAGERT / verz}. Die INKAR-Gesamtdateien liegen "
            f"seit dem 03.09.2026 extern - ist der Datentraeger "
            f"angeschlossen? Anderer Ort: Umgebungsvariable INKAR_DATEN.")
    log.info("--- %s (Gebietsstand %s), %.1f GB ---",
             ausgabe, stand, pfad.stat().st_size / 1e9)

    tmp = Path(tempfile.gettempdir()) / f"{ausgabe}_roh.csv"
    lies(ausgabe, pfad, tmp)

    sql = Path(tempfile.gettempdir()) / f"{ausgabe}_copy.sql"
    sql.write_text(
        f"DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE ausgabe = '{ausgabe}';\n"
        f"\\copy {DB_SCHEMA}.{TABELLE} "
        f"(ausgabe, zeile, bereich, id, kuerzel, indikator, raumbezug, "
        f"kennziffer, name, zeitbezug, wert) "
        f"FROM '{tmp.as_posix()}' WITH (FORMAT csv, ENCODING 'UTF8');\n",
        encoding="utf-8")
    t0 = time.time()
    run_sql_file(sql, label=f"copy {ausgabe}")
    log.info("  in die Datenbank geschrieben (%.0f s)", time.time() - t0)
    sql.unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for z in query(f"""
        SELECT ausgabe, raumbezug,
               count(*)::text                              AS werte,
               count(DISTINCT kennziffer)::text            AS einheiten,
               count(DISTINCT bereich)::text               AS bereiche,
               count(DISTINCT indikator)::text             AS indikatoren,
               min(nullif(zeitbezug,''))::text || '-' ||
               max(nullif(zeitbezug,''))::text             AS zeitreihe,
               count(*) FILTER (WHERE wert = '')::text     AS leer
        FROM {DB_SCHEMA}.{TABELLE}
        GROUP BY 1, 2 ORDER BY 1, 3::bigint DESC;
    """):
        ausgabe, rb, werte, einh, ber, ind, zr, leer = z
        log.info("  %-12s %-32s %12s Werte, %6s Einheiten, %2s Bereiche, " "%4s Indikatoren, %s, %s leer",
                 ausgabe, rb[:32], werte, einh, ber, ind, zr, leer)


    log.info("--- Ebenen mit uneinheitlicher Schluessellaenge ---")
    auffaellig = query(f"""
        SELECT ausgabe, raumbezug,
               string_agg(DISTINCT length(kennziffer)::text, '/' ORDER BY
                          length(kennziffer)::text) AS laengen,
               count(DISTINCT kennziffer)::text
        FROM {DB_SCHEMA}.{TABELLE}
        GROUP BY 1, 2
        HAVING count(DISTINCT length(kennziffer)) > 1
        ORDER BY 1, 2;
    """)
    if auffaellig:
        for z in auffaellig:
            log.warning("  %-12s %-38s Laengen %s, %s Schluessel", *z)
    else:
        log.info("  keine - jede Ebene fuehrt ein einheitliches Format")


def main():
    lieferung.merke(LIEFERUNG)
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    ausgaben = argumente or STANDARD
    unbekannt = [a for a in ausgaben if a not in AUSGABEN]
    if unbekannt:
        raise SystemExit(f"unbekannte Ausgabe(n): {', '.join(unbekannt)}. "
                         f"Bekannt: {', '.join(sorted(AUSGABEN))}")

    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    run_sql(DDL, "ddl")
    for a in ausgaben:
        laden(a)
    report()


if __name__ == "__main__":
    main()
