import csv
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

AW = "politiker_innen"
KORREKTUREN = (Path(__file__).resolve().parents[2] / "01_fetch"
               / "abgeordnetenwatch" / "korrekturen_kandidatur.csv")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("kandidaturen")


def lies_korrekturen():
    if not KORREKTUREN.exists():
        raise SystemExit(f"Korrekturtabelle fehlt: {KORREKTUREN}")
    with KORREKTUREN.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def main():
    zeilen = lies_korrekturen()
    loeschen = [int(z["eintrag_id"]) for z in zeilen if z["aktion"] == "loeschen"]
    setzen = [z for z in zeilen if z["aktion"] == "setzen"]

    log.info("%d Entscheidungen aus %s", len(zeilen), KORREKTUREN.name)
    for z in zeilen:
        if z["aktion"] == "loeschen":


            log.info("   %s  %-16s LOESCHEN - %s", z["eintrag_id"], z["person"],
                     z["grundlage"][:70].replace("\n", " "))
        else:
            neu = z["wert_korrigiert"] or "NULL"
            log.info("   %s  %-16s %s: %s -> %s", z["eintrag_id"], z["person"],
                     z["feld"], z["wert_geliefert"], neu)

    log.info("--- Vorher ---")
    for zeile in query(f"""
            SELECT aw_id, politician_label, coalesce(wkr_nr::text,'NULL'),
                   coalesce(liste_id::text,'NULL')
              FROM {AW}.candidacy_mandate
             WHERE aw_id IN ({','.join(str(x) for x in loeschen + [int(z['eintrag_id']) for z in setzen])})
             ORDER BY aw_id;"""):
        log.info("   %s %-18s wkr_nr=%-6s liste_id=%s", *zeile)

    run_sql(f"""ALTER TABLE {AW}.candidacy_mandate
                    ADD COLUMN IF NOT EXISTS listenplatz_herkunft TEXT,
                    ADD COLUMN IF NOT EXISTS partei_herkunft TEXT;
                COMMENT ON COLUMN {AW}.candidacy_mandate.listenplatz_herkunft IS
                 'korrigiert = der gelieferte Listenplatz stammte nachweislich '
                 'aus einer anderen Wahl; der richtige steht in keiner geladenen '
                 'Lieferung, sondern in einer benannten externen Quelle. '
                 'NULL = geliefert, unveraendert.';""",
            "Herkunftsspalte Listenplatz")

    tmp = Path(tempfile.gettempdir()) / "kandidaturen_bereinigen.sql"
    with tmp.open("w", encoding="utf-8") as f:

        f.write(f"DELETE FROM {AW}.candidacy_mandate WHERE aw_id IN "
                f"({', '.join(str(x) for x in loeschen)});\n")
        for z in setzen:
            wert = z["wert_korrigiert"].strip()
            if z["feld"] == "constituency":
                f.write(f"UPDATE {AW}.candidacy_mandate SET wkr_nr = "
                        f"{wert if wert else 'NULL'}, wkr_herkunft = 'korrigiert' "
                        f"WHERE aw_id = {int(z['eintrag_id'])};\n")
            elif z["feld"] == "listenplatz":


                f.write(f"UPDATE {AW}.candidacy_mandate SET list_position = "
                        f"{wert if wert else 'NULL'}, "
                        f"listenplatz_herkunft = 'korrigiert' "
                        f"WHERE aw_id = {int(z['eintrag_id'])};\n")
            elif z["feld"] == "partei":


                f.write(f"UPDATE {AW}.candidacy_mandate SET party_label = "
                        f"'{wert.replace(chr(39), chr(39)*2)}', party_id = NULL, "
                        f"partei_herkunft = 'korrigiert' "
                        f"WHERE aw_id = {int(z['eintrag_id'])};\n")
            elif z["feld"] == "liste":
                f.write(f"UPDATE {AW}.candidacy_mandate SET liste_id = "
                        f"{wert if wert else 'NULL'}, liste_herkunft = 'korrigiert' "
                        f"WHERE aw_id = {int(z['eintrag_id'])};\n")
    run_sql_file(tmp, "kandidaturen bereinigen")

    log.info("--- Nachher ---")
    for zeile in query(f"""
            SELECT m.aw_id, m.politician_label, coalesce(m.wkr_nr::text,'NULL'),
                   coalesce(m.wkr_herkunft,'-'), coalesce(m.liste_id::text,'NULL'),
                   coalesce(l.name || ' (' || l.wahl || ')', '-'),
                   coalesce(m.liste_herkunft,'-')
              FROM {AW}.candidacy_mandate m
              LEFT JOIN {AW}.landesliste l ON l.aw_id = m.liste_id
             WHERE m.aw_id IN (28411, 9127) ORDER BY m.aw_id;"""):
        log.info("   %s %-18s wkr_nr=%-6s (%s)", zeile[0], zeile[1], zeile[2], zeile[3])
        log.info("        liste_id=%-6s %s (%s)", zeile[4], zeile[5], zeile[6])

    log.info("--- Sind die Duplikate weg? ---")
    for zeile in query(f"""
            SELECT aw_id, politician_label FROM {AW}.candidacy_mandate
             WHERE aw_id IN ({', '.join(str(x) for x in loeschen)});"""):
        log.info("   NOCH DA: %s %s", *zeile)
    log.info("   in der Rohschicht erhalten: %s Zeilen", query(
        f"""SELECT count(*)::text FROM {AW}.raw_candidacies_mandates
             WHERE id IN ({', '.join(str(x) for x in loeschen)});""")[0][0])

    log.info("--- Gibt es noch doppelte Kandidaturen? ---")
    doppelt = query(f"""
        SELECT politician_label, parliament_period_label, count(*)::text
          FROM {AW}.candidacy_mandate WHERE type = 'candidacy'
         GROUP BY politician_id, 1, 2 HAVING count(*) > 1;""")
    log.info("   %s", doppelt if doppelt else "keine")

    log.info("--- Zeigen jetzt alle Kandidaturen auf Objekte ihrer eigenen Wahl? ---")
    for wahl, listenwahl, n in query(f"""
            SELECT m.parliament_period_label, l.wahl, count(*)::text
              FROM {AW}.candidacy_mandate m JOIN {AW}.landesliste l ON l.aw_id = m.liste_id
             WHERE m.type = 'candidacy' GROUP BY 1,2 ORDER BY 1;"""):
        marke = "OK" if wahl == listenwahl else "<-- PASST NICHT"
        log.info("   %-22s -> Liste aus %-22s %5s  %s", wahl, listenwahl, n, marke)

    log.info("--- Und die Gesamtzahl ---")
    for art, n in query(f"""SELECT type, count(*)::text FROM {AW}.candidacy_mandate
                             GROUP BY 1 ORDER BY 1;"""):
        log.info("   %-11s %s", art, n)


if __name__ == "__main__":
    main()
