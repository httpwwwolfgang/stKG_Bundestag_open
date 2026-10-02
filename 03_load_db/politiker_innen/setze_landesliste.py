import csv
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

AW = "politiker_innen"
ROH = "roh_bundestag"
KORREKTUREN = (Path(__file__).resolve().parents[2] / "01_fetch"
               / "abgeordnetenwatch" / "korrekturen_landesliste.csv")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("landesliste")


DDL = f"""
ALTER TABLE {AW}.candidacy_mandate
    ADD COLUMN IF NOT EXISTS liste_id       INTEGER,
    ADD COLUMN IF NOT EXISTS liste_herkunft TEXT;

COMMENT ON COLUMN {AW}.candidacy_mandate.liste_id IS
 'Die zu verwendende Landesliste. electoral_list_id bleibt daneben als '
 'gelieferter Wert stehen. Woher liste_id stammt, sagt liste_herkunft.';
COMMENT ON COLUMN {AW}.candidacy_mandate.liste_herkunft IS
 'Vier Werte, in dieser Vorrangfolge. '
 'korrigiert = Einzelentscheidung mit Beleg in korrekturen_landesliste.csv '
 '(zwei Mandate, deren Verweis auf die Liste einer fremden Wahl zeigt). '
 'geliefert = electoral_list_id von abgeordnetenwatch. '
 'amtlich_ergaenzt = aus dem MdB-XML (Lieferung bt_mdb_stammdaten), das je '
 'Mandat das Bundeslandkuerzel der Liste fuehrt. ACHTUNG: bei KANDIDATUREN '
 'steht der Wert nicht in der Lieferung selbst - das XML kennt keine '
 'Kandidaturen. Er kommt vom Mandat DERSELBEN Person in DERSELBEN '
 'Wahlperiode: wer ueber die Liste eines Bundeslandes einzog, stand auch auf '
 'ihr. Gegengeprueft gegen den zweiten Weg (Bundesland des Wahlkreises): 429 '
 'von 429 treffen dieselbe Liste. '
 'abgeleitet = aus dem Bundesland des Wahlkreises, in dem die Person antrat. '
 'Das Listenobjekt gibt es je Bundesland und Wahl genau einmal '
 '. NUR wo ein Listenplatz dasteht - er ist der Beleg, '
 'dass die Person auf einer Liste stand; ohne ihn wuerde eine Listenkandidatur '
 'erfunden. '
 'NULL = kein Verweis, und keiner der Wege greift.';
"""


def sql_wert(wert):
    if wert is None or wert == "":
        return "NULL"
    return "'" + str(wert).replace("'", "''") + "'"


def lies_korrekturen():
    if not KORREKTUREN.exists():
        raise SystemExit(f"Korrekturtabelle fehlt: {KORREKTUREN}")
    with KORREKTUREN.open(encoding="utf-8", newline="") as f:
        return [{"aw_id": int(z["eintrag_id"]),
                 "person": z["person"],
                 "alt": int(z["wert_geliefert"]),
                 "neu": int(z["wert_korrigiert"]),
                 "geprueft_am": z["geprueft_am"]}
                for z in csv.DictReader(f, delimiter=";")]


def main():
    korrekturen = lies_korrekturen()
    log.info("%d Einzelkorrekturen aus %s", len(korrekturen), KORREKTUREN.name)
    for k in korrekturen:
        log.info("   %s  %-22s Liste %s -> %s  (geprueft %s)",
                 k["aw_id"], k["person"], k["alt"], k["neu"], k["geprueft_am"])

    run_sql(DDL, "Spalten anlegen")

    tmp = Path(tempfile.gettempdir()) / "korrekturen_landesliste.sql"
    with tmp.open("w", encoding="utf-8") as f:
        f.write(f"DROP TABLE IF EXISTS {AW}.korrektur_landesliste;\n")
        f.write(f"""CREATE TABLE {AW}.korrektur_landesliste (
                       aw_id INTEGER PRIMARY KEY, wert INTEGER, geprueft_am DATE);\n""")
        f.write(f"INSERT INTO {AW}.korrektur_landesliste (aw_id, wert, geprueft_am) VALUES\n")
        f.write(",\n".join(f"({k['aw_id']}, {k['neu']}, {sql_wert(k['geprueft_am'])})"
                           for k in korrekturen) + ";\n")
        f.write(f"""
DROP TABLE IF EXISTS {AW}.liste_je_land;
CREATE TABLE {AW}.liste_je_land AS
SELECT l.wahl_id,
       replace(replace(l.name, 'Landesliste ', ''),
               'Mecklenburg Vorpommern', 'Mecklenburg-Vorpommern') AS land_name,
       l.aw_id AS liste_id
  FROM {AW}.landesliste l;
ALTER TABLE {AW}.liste_je_land ADD PRIMARY KEY (wahl_id, land_name);

DROP TABLE IF EXISTS {AW}.land_kuerzel;
CREATE TABLE {AW}.land_kuerzel (kuerzel TEXT PRIMARY KEY, land_name TEXT NOT NULL);
INSERT INTO {AW}.land_kuerzel VALUES
 ('BW','Baden-Württemberg'),('BY','Bayern'),('BE','Berlin'),('BB','Brandenburg'),
 ('HB','Bremen'),('HH','Hamburg'),('HE','Hessen'),('MV','Mecklenburg-Vorpommern'),
 ('NI','Niedersachsen'),('NW','Nordrhein-Westfalen'),('RP','Rheinland-Pfalz'),
 ('SL','Saarland'),('SN','Sachsen'),('ST','Sachsen-Anhalt'),
 ('SH','Schleswig-Holstein'),('TH','Thüringen');

UPDATE {AW}.candidacy_mandate m
   SET liste_id = coalesce(k.wert, m2.electoral_list_id,
                           amtl.liste_id, abgel.liste_id),
       liste_herkunft = CASE
           WHEN k.aw_id                IS NOT NULL THEN 'korrigiert'
           WHEN m2.electoral_list_id   IS NOT NULL THEN 'geliefert'
           WHEN amtl.liste_id          IS NOT NULL THEN 'amtlich_ergaenzt'
           WHEN abgel.liste_id         IS NOT NULL THEN 'abgeleitet'
           ELSE NULL END
  FROM {AW}.candidacy_mandate m2
  LEFT JOIN {AW}.korrektur_landesliste k ON k.aw_id = m2.aw_id




  LEFT JOIN {AW}.mdb_zu_aw z ON z.aw_id = m2.politician_id
  LEFT JOIN {ROH}.stammdaten_mdb_wahlperiode w
         ON w.id = z.mdb_id
        AND w.wp = CASE substring(m2.parliament_period_label from '[0-9]{{4}}')::int
                     WHEN 2013 THEN 18 WHEN 2017 THEN 19 WHEN 2021 THEN 20 END
  LEFT JOIN {AW}.land_kuerzel lk ON lk.kuerzel = w.liste
  LEFT JOIN {AW}.liste_je_land amtl
         ON amtl.wahl_id = m2.parliament_period_id
        AND amtl.land_name = lk.land_name

  LEFT JOIN raum.wahlkreis_land wl
         ON m2.list_position IS NOT NULL
        AND wl.wkr_nr = m2.wkr_nr
        AND wl.wahljahr = substring(m2.parliament_period_label from '[0-9]{{4}}')::int
  LEFT JOIN {AW}.liste_je_land abgel
         ON abgel.wahl_id = m2.parliament_period_id
        AND abgel.land_name = wl.land_name
 WHERE m.aw_id = m2.aw_id;
""")
    run_sql_file(tmp, "landesliste")

    log.info("--- Ergebnis ---")
    for art, herkunft, n in query(f"""
            SELECT type, coalesce(liste_herkunft, 'kein Verweis'), count(*)
              FROM {AW}.candidacy_mandate GROUP BY 1,2 ORDER BY 1,3 DESC;"""):
        log.info("   %-11s %-16s %s", art, herkunft, n)

    log.info("--- Die zwei Korrekturen, wie sie jetzt dastehen ---")
    for zeile in query(f"""
            SELECT m.aw_id, m.politician_label, m.parliament_period_label,
                   m.electoral_list_id, m.liste_id, l.name, l.wahl, m.liste_herkunft
              FROM {AW}.candidacy_mandate m
              JOIN {AW}.landesliste l ON l.aw_id = m.liste_id
             WHERE m.liste_herkunft = 'korrigiert' ORDER BY m.politician_label;"""):
        log.info("   %s %-20s %s", zeile[0], zeile[1][:20], zeile[2])
        log.info("      geliefert %s  ->  jetzt %s = %s (%s), %s",
                 zeile[3], zeile[4], zeile[5], zeile[6], zeile[7])

    log.info("--- Gegenprobe: zeigen jetzt alle Mandate auf ihre eigene Legislatur? ---")
    for leg, wahl, n in query(f"""
            SELECT m.parliament_period_label, l.wahl, count(*)
              FROM {AW}.candidacy_mandate m JOIN {AW}.landesliste l ON l.aw_id = m.liste_id
             WHERE m.type = 'mandate' GROUP BY 1,2 ORDER BY 1,3 DESC;"""):
        marke = "OK" if leg == wahl else "<-- PASST NICHT"
        log.info("   Mandat %-24s -> Liste aus %-24s %5s  %s", leg, wahl, n, marke)


if __name__ == "__main__":
    main()
