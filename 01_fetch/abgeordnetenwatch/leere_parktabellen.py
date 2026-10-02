import sys

import psycopg2

sys.path.insert(0, ".")
from abgeordnetenwatch import DB_DSN, DB_SCHEMA, PARK_TABLES


def main():
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')

            for t in PARK_TABLES.values():
                cur.execute(f"SELECT count(*) FROM {t};")
                print(f"   {t:<32} {cur.fetchone()[0]:>7} Zeilen")

            print("\nPruefung 1: geparkte Person von einem Mandat gebraucht UND" " nicht im Bestand?")
            cur.execute("""
                SELECT count(*) FROM raw_politicians_non_bundestag p
                WHERE EXISTS (SELECT 1 FROM raw_candidacies_mandates m
                              WHERE (m.data -> 'politician' ->> 'id')::int = p.id)
                  AND NOT EXISTS (SELECT 1 FROM raw_politicians r WHERE r.id = p.id);""")
            n_pol = cur.fetchone()[0]
            print(f"   {n_pol}")

            print("Pruefung 2: geparkte Nebentaetigkeit an einem Mandat UND" " nicht im Bestand?")
            cur.execute("""
                SELECT count(*) FROM raw_sidejobs_non_bundestag s
                WHERE EXISTS (
                        SELECT 1 FROM jsonb_array_elements(s.data -> 'mandates') m
                        JOIN raw_candidacies_mandates k ON k.id = (m ->> 'id')::int)
                  AND NOT EXISTS (SELECT 1 FROM raw_sidejobs r WHERE r.id = s.id);""")
            n_sj = cur.fetchone()[0]
            print(f"   {n_sj}")

            print("Pruefung 3: zeigt im Clean-Layer noch etwas ins Leere?")
            cur.execute("""
                SELECT count(*) FROM candidacy_mandate cm
                WHERE cm.politician_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM politician p WHERE p.aw_id = cm.politician_id);""")
            n_ref = cur.fetchone()[0]
            print(f"   {n_ref}")

            if n_pol or n_sj or n_ref:
                print("\nABBRUCH: es wird noch etwas gebraucht. Nichts geaendert.")
                conn.rollback()
                return

            for t in PARK_TABLES.values():
                cur.execute(f"TRUNCATE {t};")
            conn.commit()

            print("\nGeleert. Kontrolle:")
            for t in PARK_TABLES.values():
                cur.execute(f"SELECT count(*) FROM {t};")
                print(f"   {t:<32} {cur.fetchone()[0]:>7} Zeilen")
            print("\nAb jetzt gilt: eine gefuellte Park-Tabelle ist ein Befund.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
