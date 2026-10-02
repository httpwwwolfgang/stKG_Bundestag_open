import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql_file, query

import baue_wk_merkmalsbruecke as bruecke

DB_SCHEMA = "strukturdaten"
HIER = Path(__file__).resolve().parent
import zwischenstand
EXPORT = zwischenstand.fuer(__file__)
BRUECKE_CSV = EXPORT / "wk_merkmalsbruecke.csv"

LIEFERUNG = {
    2013: "bwl_strukturdaten_2013",
    2017: "bwl_strukturdaten_2017",
    2021: "bwl_strukturdaten_2021",
}

HERAUSGEBER = "Die Bundeswahlleiterin"
LIZENZ = "dl-de/by-2-0"

LIMITIERUNG = (
    "Nur fuenf Merkmale sind unterhalb der Gemeindeebene gerechnet: " "Bevoelkerung insgesamt, Bevoelkerung Deutsche, Bevoelkerungsdichte, " "Flaeche und Auslaenderanteil. Alle uebrigen Merkmale sind nicht feiner " "als die Gemeinde; fuer die Wahlkreise, die ganz in einer geteilten Stadt " "liegen, tragen sie den Wert der ganzen Stadt -- Berlins zwoelf " "Wahlkreise fuehren dasselbe Einkommen. Welche Merkmale betroffen sind, " "steht je Merkmal in strukturdaten.wk_indikator.aufloesung."
)

DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.wk_indikator (
    indikator_id  text PRIMARY KEY,
    wahljahr      smallint NOT NULL,
    merkmal       text     NOT NULL,
    bezeichnung   text     NOT NULL,
    stichtag      text,
    masseinheit   text,
    aufloesung    text     NOT NULL,
    lieferung_id  text     NOT NULL
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.wahlkreis_indikator (
    wahljahr      smallint NOT NULL,
    wkr_nr        smallint NOT NULL,
    indikator_id  text     NOT NULL REFERENCES {DB_SCHEMA}.wk_indikator,
    wert          double precision,
    PRIMARY KEY (wahljahr, wkr_nr, indikator_id)
);

CREATE INDEX IF NOT EXISTS wahlkreis_indikator_ind
    ON {DB_SCHEMA}.wahlkreis_indikator (indikator_id);
CREATE INDEX IF NOT EXISTS wk_indikator_merkmal
    ON {DB_SCHEMA}.wk_indikator (merkmal);
"""


def lies_bruecke():
    if not BRUECKE_CSV.exists():
        raise SystemExit(f"fehlt: {BRUECKE_CSV}\n" "Erst baue_wk_merkmalsbruecke.py laufen lassen.")
    with open(BRUECKE_CSV, encoding="utf-8-sig", newline="") as f:
        zeilen = list(csv.DictReader(f, delimiter=";"))
    aus = {}
    for z in zeilen:
        if z["uebernehmen"].strip().lower() != "ja":
            continue
        aus[(int(z["wahljahr"]), z["quellspalte"])] = z
    return aus


def zahl(text):
    t = text.strip()
    if not t or t in {"-", ".", "x"}:
        return None
    try:
        return float(t.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def lies_datei(jahr, merkmale):
    datei = bruecke.DATEIEN[jahr]
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(bruecke.QUELLE / datei, encoding=enc) as f:
                roh = [z.rstrip("\n") for z in f if not z.startswith("#")]
            zeilen = list(csv.reader(roh, delimiter=";"))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"Zeichensatz nicht erkannt: {datei}")

    kopf_nr = next(i for i, z in enumerate(zeilen[:8])
                   if any("Wahlkreis" in c and len(c) > 5 for c in z))
    kopf = [c.strip() for c in zeilen[kopf_nr]]
    i_nr = next(i for i, c in enumerate(kopf) if c.startswith("Wahlkreis-Nr"))


    stellen = [(i, merkmale[(jahr, c)]) for i, c in enumerate(kopf)
               if (jahr, c) in merkmale]

    werte, leer = [], {}
    wahlkreise = 0
    for z in zeilen[kopf_nr + 1:]:
        if len(z) <= i_nr or not z[i_nr].strip().isdigit():
            continue
        nr = int(z[i_nr])
        if not 1 <= nr <= 299:
            continue
        wahlkreise += 1
        for i, m in stellen:
            v = zahl(z[i]) if i < len(z) else None
            werte.append((jahr, nr, m["indikator_id"], v))
            if v is None:
                leer[m["spaltenname_db"]] = leer.get(m["spaltenname_db"], 0) + 1
    return stellen, werte, leer, wahlkreise


def schreibe_csv(pfad, spalten, zeilen):
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(spalten)
        for z in zeilen:
            w.writerow(["" if v is None else v for v in z])


def main():
    EXPORT.mkdir(exist_ok=True)
    merkmale = lies_bruecke()


    for (jahr, quellspalte), m in merkmale.items():
        m["indikator_id"] = f"{jahr}_{m['spaltenname_db']}"

    doppelt = {}
    for m in merkmale.values():
        doppelt.setdefault(m["indikator_id"], 0)
        doppelt[m["indikator_id"]] += 1
    kollision = {k: n for k, n in doppelt.items() if n > 1}
    if kollision:
        raise SystemExit("Zwei Quellspalten derselben Wahl tragen denselben "
                         f"Namen: {kollision}")

    katalog, alle_werte = [], []
    print("=== Gelesen ===")
    for jahr in sorted(bruecke.DATEIEN):
        stellen, werte, leer, n_wkr = lies_datei(jahr, merkmale)
        for _, m in stellen:
            katalog.append((m["indikator_id"], jahr, m["spaltenname_db"],
                            m["quellspalte"], m["stichtag"] or None,
                            m["einheit"] or None, m["aufloesung"],
                            LIEFERUNG[jahr]))
        alle_werte.extend(werte)
        fehlend = sum(1 for w in werte if w[3] is None)
        print(f"  {jahr}: {n_wkr} Wahlkreise, {len(stellen)} Merkmale, "
              f"{len(werte)} Zellen, davon {fehlend} leer")
        for name, n in sorted(leer.items(), key=lambda x: -x[1]):
            print(f"        leer: {name} ({n})")

    kat_csv = EXPORT / "_lade_wk_indikator.csv"
    wert_csv = EXPORT / "_lade_wahlkreis_indikator.csv"
    schreibe_csv(kat_csv, ["indikator_id", "wahljahr", "merkmal", "bezeichnung",
                           "stichtag", "masseinheit", "aufloesung",
                           "lieferung_id"], katalog)
    schreibe_csv(wert_csv, ["wahljahr", "wkr_nr", "indikator_id", "wert"],
                 alle_werte)


    vorhanden = query(f"""
        SELECT count(*) FROM {DB_SCHEMA}.wahlkreis_indikator wi
          JOIN {DB_SCHEMA}.wk_indikator k USING (indikator_id)
         WHERE k.lieferung_id IN ({",".join("'" + v + "'" for v in LIEFERUNG.values())});
        """) if tabelle_da() else [(0,)]
    print(f"\n  Im Bestand aus diesen drei Lieferungen: {vorhanden[0][0]} Zeilen." "  Sie werden ersetzt.")

    liefer_sql = "\n".join(
        f"""INSERT INTO meta.datenlieferung
              (lieferung_id, bezeichnung, herausgeber, datei, lizenz,
               wahljahr, art, limitierungen)
            VALUES ('{LIEFERUNG[j]}',
                    'Strukturdaten der Wahlkreise zur Bundestagswahl {j}',
                    '{HERAUSGEBER}', '{bruecke.DATEIEN[j]}', '{LIZENZ}',
                    {j}, 'amtlich', '{LIMITIERUNG}')
            ON CONFLICT (lieferung_id) DO UPDATE
               SET bezeichnung   = EXCLUDED.bezeichnung,
                   herausgeber   = EXCLUDED.herausgeber,
                   datei         = EXCLUDED.datei,
                   lizenz        = EXCLUDED.lizenz,
                   wahljahr      = EXCLUDED.wahljahr,
                   art           = EXCLUDED.art,
                   limitierungen = EXCLUDED.limitierungen;"""
        for j in sorted(LIEFERUNG))


    kennungen = ",".join("'" + v + "'" for v in LIEFERUNG.values())
    skript = EXPORT / "_lade_wahlkreis_strukturdaten.sql"
    skript.write_text(f"""
BEGIN;
{DDL}
{liefer_sql}

DELETE FROM {DB_SCHEMA}.wahlkreis_indikator wi
      USING {DB_SCHEMA}.wk_indikator k
      WHERE k.indikator_id = wi.indikator_id
        AND k.lieferung_id IN ({kennungen});
DELETE FROM {DB_SCHEMA}.wk_indikator
      WHERE lieferung_id IN ({kennungen});

\\copy {DB_SCHEMA}.wk_indikator FROM '{kat_csv.as_posix()}' CSV HEADER DELIMITER ';'
\\copy {DB_SCHEMA}.wahlkreis_indikator FROM '{wert_csv.as_posix()}' CSV HEADER DELIMITER ';'
COMMIT;
""", encoding="utf-8")
    run_sql_file(skript, "laden")

    bericht()


def tabelle_da():
    return bool(query(f"""SELECT 1 FROM information_schema.tables
        WHERE table_schema = '{DB_SCHEMA}' AND table_name = 'wk_indikator';"""))


def bericht():
    print("\n=== Im Bestand ===")
    for j, n, w, z, f in query(f"""
        SELECT k.wahljahr, count(DISTINCT k.indikator_id),
               count(DISTINCT wi.wkr_nr), count(wi.*),
               count(*) FILTER (WHERE wi.wert IS NULL)
          FROM {DB_SCHEMA}.wk_indikator k
          LEFT JOIN {DB_SCHEMA}.wahlkreis_indikator wi USING (indikator_id)
         GROUP BY 1 ORDER BY 1;"""):
        print(f"  {j}: {n} Merkmale, {w} Wahlkreise, {z} Werte, {f} davon leer")

    drei = query(f"""SELECT count(*) FROM (
          SELECT merkmal FROM {DB_SCHEMA}.wk_indikator
           GROUP BY merkmal HAVING count(DISTINCT wahljahr) = 3) t;""")
    print(f"\n  Merkmale in allen drei Wahlen: {drei[0][0]}")
    print("  -- das ist die Grundlage der gepoolten Auswertung ueber 897 Faelle.")

    unter = query(f"""SELECT count(DISTINCT merkmal) FROM {DB_SCHEMA}.wk_indikator
                       WHERE aufloesung = 'unter_gemeinde';""")
    print(f"  Davon unterhalb der Gemeindeebene gerechnet: {unter[0][0]}")


if __name__ == "__main__":
    main()
