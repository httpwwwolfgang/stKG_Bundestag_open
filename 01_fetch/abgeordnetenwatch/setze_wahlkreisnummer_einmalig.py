import sys

import psycopg2

sys.path.insert(0, ".")
from abgeordnetenwatch import (DB_DSN, DB_SCHEMA, MANDATE_DDL,
                               setze_wahlkreisnummer, pruefe_wahlkreisnummer)


def main():
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')
            cur.execute(MANDATE_DDL)
        conn.commit()
        print("Spalten angelegt bzw. vorhanden.\n")

        setze_wahlkreisnummer(conn)
        pruefe_wahlkreisnummer(conn)

        with conn.cursor() as cur:
            cur.execute("""SELECT parliament_period_label, wkr_herkunft, count(*)
                             FROM candidacy_mandate
                            WHERE type='mandate'
                            GROUP BY 1,2 ORDER BY 1,2;""")
            print("\n  Mandate je Wahlperiode und Herkunft:")
            for lab, herkunft, n in cur.fetchall():
                print(f"    {str(lab):<24} {str(herkunft):<12} {n:>5}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
