import sys

import psycopg2

sys.path.insert(0, ".")
from abgeordnetenwatch import (DB_DSN, DB_SCHEMA, RateLimiter,
                               AbgeordnetenwatchAPI, START_CALLS_PER_MIN,
                               upsert_raw, load_clean_politicians,
                               load_clean_constituencies, setup_db)


FEHLENDE_WAHLKREISE = [6418, 3782, 6202]


def spalten_nachziehen(conn):
    print("1) Personen-Identifikatoren in den Clean-Layer nachziehen")
    setup_db(conn)
    load_clean_politicians(conn)
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*), count(qid_wikidata),
                              count(ext_id_bundestagsverwaltung)
                       FROM politician;""")
        n, q, e = cur.fetchone()
    print(f"   {n} Personen: {q} mit Wikidata-Id ({100.0*q/n:.1f} %), "
          f"{e} mit Id der Bundestagsverwaltung ({100.0*e/n:.1f} %)")
    return e


def reste_loeschen(conn):
    print("\n2) Wahlkreis-Reste des Testlaufs entfernen")
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM raw_constituencies
                       WHERE abgefragt_periode IS NULL;""")
        n = cur.fetchone()[0]
        if not n:
            print("   nichts zu loeschen")
            return 0
        cur.execute("""SELECT label FROM raw_constituencies
                       WHERE abgefragt_periode IS NULL ORDER BY id LIMIT 3;""")
        for (lab,) in cur.fetchall():
            print(f"   Beispiel: {lab}")


        cur.execute("""SELECT count(*) FROM raw_constituencies
                       WHERE abgefragt_periode IS NULL
                         AND label NOT LIKE '%%2025%%';""")
        fremd = cur.fetchone()[0]
        if fremd:
            print(f"   ABBRUCH: {fremd} der {n} Zeilen tragen kein Bezugsjahr "
                  f"2025 im Label - das waeren keine Testreste. Nichts geloescht.")
            return 0
        cur.execute("""DELETE FROM raw_constituencies
                       WHERE abgefragt_periode IS NULL;""")
        geloescht = cur.rowcount
        cur.execute("DELETE FROM constituency WHERE parliament_period_id IS NULL;")
        clean = cur.rowcount
    conn.commit()
    print(f"   {geloescht} Zeilen aus raw_constituencies, {clean} aus constituency")
    return geloescht


def wahlkreise_nachladen(conn, api):
    print("\n3) Drei einzeln referenzierte Wahlkreise nachladen")
    geholt = 0
    for wk_id in FEHLENDE_WAHLKREISE:
        try:
            payload = api._get(f"constituencies/{wk_id}", {})
        except Exception as e:
            print(f"   {wk_id}: nicht abrufbar ({e})")
            continue
        d = payload.get("data") or {}
        if not d.get("id"):
            print(f"   {wk_id}: keine Daten zurueckgekommen")
            continue


        upsert_raw(conn, "raw_constituencies", [d])
        print(f"   {wk_id}: {d.get('label')}")
        geholt += 1
    return geholt


def kontrolle(conn):
    print("\n4) Kontrolle: zeigen noch Mandate auf fehlende Wahlkreise?")
    with conn.cursor() as cur:
        cur.execute("""SELECT count(*) FROM candidacy_mandate cm
                       WHERE cm.constituency_id IS NOT NULL
                         AND NOT EXISTS (SELECT 1 FROM constituency c
                                         WHERE c.aw_id = cm.constituency_id);""")
        print("   tote Verweise im Clean-Layer:", cur.fetchone()[0])
        cur.execute("""SELECT parliament_period_id, parliament_period_label,
                              count(*) FROM constituency
                       GROUP BY 1,2 ORDER BY 1 NULLS LAST;""")
        print("   constituency je Wahlperiode:")
        for r in cur.fetchall():
            print(f"     {str(r[0]):>6}  {str(r[1]):<26} {r[2]:>5}")


def main():
    conn = psycopg2.connect(DB_DSN)
    api = AbgeordnetenwatchAPI(RateLimiter(START_CALLS_PER_MIN))
    try:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')
        spalten_nachziehen(conn)
        reste_loeschen(conn)
        wahlkreise_nachladen(conn, api)
        load_clean_constituencies(conn)
        kontrolle(conn)
        print("\nFertig.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
