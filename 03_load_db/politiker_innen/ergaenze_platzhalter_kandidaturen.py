import csv
import logging
import sys
from datetime import date
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

QUELLE = (Path(__file__).resolve().parents[2] / "01_fetch"
          / "abgeordnetenwatch" / "platzhalter_kandidatur.csv")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn
DSN = dsn()
AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("platzhalter-kandidatur")


def lies():
    zeilen = []
    with QUELLE.open(encoding="utf-8", newline="") as f:
        for z in csv.DictReader((r for r in f if not r.startswith("#")),
                                delimiter=";"):
            zeilen.append(z)
    return zeilen


def main():
    if not QUELLE.exists():
        raise SystemExit(f"{QUELLE} fehlt.")
    faelle = lies()
    log.info("%d Platzhalter aus %s", len(faelle), QUELLE.name)

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(f"""
            ALTER TABLE {AW}.candidacy_mandate
                ADD COLUMN IF NOT EXISTS platzhalter_grund TEXT;
            COMMENT ON COLUMN {AW}.candidacy_mandate.platzhalter_grund IS
             'Nur bei den Platzhaltern gefuellt (aw_id < 0): warum die Zeile '
             'angelegt wurde, obwohl abgeordnetenwatch sie nicht liefert. '
             'Wortlaut aus platzhalter_kandidatur.csv.';""")

        cur.execute(f"DELETE FROM {AW}.candidacy_mandate WHERE aw_id < 0;")
        weg_k = cur.rowcount
        cur.execute(f"DELETE FROM {AW}.politician WHERE aw_id < 0;")
        weg_p = cur.rowcount
        if weg_k or weg_p:
            log.info("   %d alte Platzhalter-Kandidaturen und %d -Personen entfernt",
                     weg_k, weg_p)


        cur.execute(f"""SELECT parliament_period_id, number, aw_id
                          FROM {AW}.constituency;""")
        wk_obj = {(p, n): a for p, n, a in cur.fetchall()}

        personen, kandidaturen, ohne_objekt = [], [], []
        heute = date.today()
        for z in faelle:
            aw_id = int(z["aw_id"])
            wahl_id, wkr = int(z["wahl_id"]), int(z["wkr_nr"])
            const = wk_obj.get((wahl_id, wkr))
            if const is None:
                ohne_objekt.append((z["name"], z["wahl"], wkr))
            personen.append((aw_id, z["name"], heute))
            kandidaturen.append((aw_id, "candidacy", aw_id, z["name"], wahl_id,
                                 z["wahl"], z["partei"], const, wkr,
                                 "platzhalter", z["grund"], heute))

        execute_values(cur, f"""INSERT INTO {AW}.politician
            (aw_id, last_name, fetched_at) VALUES %s;""", personen)
        execute_values(cur, f"""INSERT INTO {AW}.candidacy_mandate
            (aw_id, type, politician_id, politician_label, parliament_period_id,
             parliament_period_label, party_label, constituency_id, wkr_nr,
             wkr_herkunft, platzhalter_grund, fetched_at) VALUES %s;""",
                       kandidaturen)
    conn.commit()
    log.info("   %d Platzhalter angelegt", len(kandidaturen))
    if ohne_objekt:
        log.warning("   %d ohne Wahlkreisobjekt in constituency - " "constituency_id bleibt leer:", len(ohne_objekt))
        for n, w, k in ohne_objekt:
            log.warning("      %s, %s, WK %d", n, w, k)

    with conn.cursor() as cur:
        cur.execute(f"""SELECT aw_id, politician_label, party_label,
                               parliament_period_label, wkr_nr, constituency_id
                          FROM {AW}.candidacy_mandate WHERE aw_id < 0
                         ORDER BY aw_id DESC;""")
        log.info("--- Angelegt ---")
        for r in cur.fetchall():
            log.info("   %3d  %-26s %-18s %-22s WK %-4d const %s",
                     r[0], r[1], r[2], r[3], r[4], r[5])


        cur.execute("SELECT partei_roh, partei, lieferung_ids FROM meta.partei_mapping;")
        amtlich, aw_labels = {}, {}
        for roh, schl, lief in cur.fetchall():
            if "aw_api_v2" in (lief or []):
                aw_labels.setdefault(schl, set()).add(roh)
            else:
                amtlich[roh] = schl
        cur.execute(f"""SELECT DISTINCT party_label, wkr_nr,
                               substring(parliament_period_label, '[0-9]{{4}}')::int
                          FROM {AW}.candidacy_mandate
                         WHERE type = 'candidacy' AND wkr_nr IS NOT NULL;""")
        haben = set(cur.fetchall())
        cur.execute("""SELECT wahljahr, wkr_nr, partei, stimmen
                         FROM wahlergebnisse.wahlkreis_ergebnis
                        WHERE stimme = 'erststimme' AND stimmen > 0;""")
        soll, offen = 0, []
        for jahr, wkr, partei, stimmen in cur.fetchall():
            schl = amtlich.get(partei)
            if not (schl and aw_labels.get(schl)):
                continue
            soll += 1
            if not any((lab, wkr, jahr) in haben for lab in aw_labels[schl]):
                offen.append((jahr, wkr, partei, stimmen))
        log.info("--- Gegenprobe: Partei tritt an und ist bei abgeordnetenwatch bekannt ---")
        log.info("   %d Faelle, davon %d mit Bewerber im Bestand (%.2f %%)",
                 soll, soll - len(offen), 100 * (soll - len(offen)) / soll)
        if offen:
            log.warning("   %d ohne Bewerber:", len(offen))
            for j_, w, p_, s in sorted(offen):
                log.warning("      %d  WK %3d  %-18s %6d Erststimmen", j_, w, p_, s)
        else:
            log.info("   kein Wahlkreis mehr ohne Bewerber")


        cur.execute(f"""
            SELECT parliament_period_label, wkr_nr, party_label, count(*),
                   string_agg(politician_label, ' | ' ORDER BY politician_label)
              FROM {AW}.candidacy_mandate
             WHERE type = 'candidacy' AND wkr_nr IS NOT NULL
               AND party_label <> 'Einzelbewerbung'
             GROUP BY 1, 2, 3 HAVING count(*) > 1
             ORDER BY 1, 2;""")
        dop = cur.fetchall()
        log.info("--- Doppelbelegungen: zwei Bewerber derselben Partei in einem Wahlkreis ---")
        if not dop:
            log.info("   keine")
        for w, k, pa, n, wer in dop:
            log.warning("   %-22s WK %-4d %-14s %d: %s", w, k, pa, n, wer)
    conn.close()


if __name__ == "__main__":
    main()
