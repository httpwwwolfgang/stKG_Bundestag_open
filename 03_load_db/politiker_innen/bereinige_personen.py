import csv
import logging
import sys
from pathlib import Path

import psycopg2

QUELLE = (Path(__file__).resolve().parents[2] / "01_fetch"
          / "abgeordnetenwatch" / "korrekturen_person.csv")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn
DSN = dsn()
AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("personen-bereinigen")


ERLAUBT = {"year_of_birth": "int", "sex": "text", "education": "text",
           "occupation": "text", "residence": "text"}


def main():
    if not QUELLE.exists():
        raise SystemExit(f"{QUELLE} fehlt.")
    with QUELLE.open(encoding="utf-8", newline="") as f:
        zeilen = [z for z in csv.DictReader((r for r in f if not r.startswith("#")),
                                            delimiter=";")]
    log.info("%d Korrekturen aus %s", len(zeilen), QUELLE.name)

    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        for feld in sorted({z["feld"] for z in zeilen}):
            if feld not in ERLAUBT:
                raise SystemExit(f"Feld '{feld}' steht nicht in der erlaubten Liste.")
            cur.execute(f"""ALTER TABLE {AW}.politician
                            ADD COLUMN IF NOT EXISTS {feld}_herkunft TEXT;""")
            cur.execute(f"""UPDATE {AW}.politician SET {feld}_herkunft = 'geliefert'
                             WHERE {feld} IS NOT NULL AND {feld}_herkunft IS NULL;""")
            cur.execute(f"""COMMENT ON COLUMN {AW}.politician.{feld}_herkunft IS
             'geliefert = Wert von abgeordnetenwatch, korrigiert = '
             'Einzelentscheidung mit Beleg in korrekturen_person.csv. Der '
             'gelieferte Wert steht unveraendert in raw_politicians.';""")

        for z in zeilen:
            aw_id, feld = int(z["aw_id"]), z["feld"]
            cur.execute(f"SELECT {feld}::text FROM {AW}.politician WHERE aw_id = %s;",
                        (aw_id,))
            r = cur.fetchone()
            if r is None:
                log.warning("   %s: keine Person mit dieser aw_id", aw_id)
                continue
            if r[0] != z["wert_geliefert"]:
                log.warning("   %s %s: geliefert steht auf %s, die CSV erwartet %s " "- Begruendung pruefen", aw_id, feld, r[0],
                            z["wert_geliefert"])
            cur.execute(f"""UPDATE {AW}.politician
                               SET {feld} = %s, {feld}_herkunft = 'korrigiert'
                             WHERE aw_id = %s;""", (z["wert_korrigiert"], aw_id))
            log.info("   %s %-16s %s -> %s", aw_id, feld, z["wert_geliefert"],
                     z["wert_korrigiert"])
    conn.commit()

    with conn.cursor() as cur:
        log.info("--- Nachher ---")
        cur.execute(f"""SELECT p.aw_id, p.first_name || ' ' || p.last_name,
                               p.year_of_birth, p.year_of_birth_herkunft,
                               b.geburtsdatum
                          FROM {AW}.politician p
                          LEFT JOIN {AW}.biografie_bt b ON b.aw_id = p.aw_id
                         WHERE p.year_of_birth_herkunft = 'korrigiert'
                         ORDER BY 2;""")
        for r in cur.fetchall():
            log.info("   %-28s %s (%s), amtlich %s", r[1][:26], r[2], r[3], r[4])

        cur.execute(f"""
            SELECT count(*) FROM {AW}.politician p
              JOIN {AW}.biografie_bt b ON b.aw_id = p.aw_id
             WHERE p.year_of_birth IS NOT NULL
               AND p.year_of_birth <> extract(year FROM b.geburtsdatum);""")
        log.info("--- Gegenprobe: %d Personen mit abweichendem Geburtsjahr " "(vorher 2)", cur.fetchone()[0])
        cur.execute(f"""SELECT year_of_birth_herkunft, count(*) FROM {AW}.politician
                         GROUP BY 1 ORDER BY 2 DESC;""")
        for h, n in cur.fetchall():
            log.info("   year_of_birth_herkunft %-12s %5d", str(h), n)
    conn.close()


if __name__ == "__main__":
    main()
