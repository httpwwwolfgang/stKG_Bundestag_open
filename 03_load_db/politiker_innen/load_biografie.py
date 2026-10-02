import logging
import sys

import psycopg2
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dsn

DSN = dsn()
AW = "politiker_innen"
LIEFERUNG = "bt_mdb_stammdaten"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("biografie")

TEXTFELDER = ("geburtsort", "geburtsland", "geschlecht", "familienstand",
              "religion", "beruf", "vita_kurz")

DDL = f"""
SET client_min_messages TO WARNING;
DROP TABLE IF EXISTS {AW}.biografie_bt;

CREATE TABLE {AW}.biografie_bt (
    aw_id         INTEGER PRIMARY KEY,
    mdb_id        TEXT NOT NULL,
    geburtsdatum  DATE,
    sterbedatum   DATE,
    geburtsort    TEXT NOT NULL DEFAULT 'unbekannt',
    geburtsland   TEXT NOT NULL DEFAULT 'unbekannt',
    geschlecht    TEXT NOT NULL DEFAULT 'unbekannt',
    familienstand TEXT NOT NULL DEFAULT 'unbekannt',
    religion      TEXT NOT NULL DEFAULT 'unbekannt',
    beruf         TEXT NOT NULL DEFAULT 'unbekannt',
    vita_kurz     TEXT NOT NULL DEFAULT 'unbekannt',
    herkunft      TEXT NOT NULL DEFAULT '{LIEFERUNG}'
);
CREATE INDEX ON {AW}.biografie_bt (mdb_id);
CREATE INDEX ON {AW}.biografie_bt (geburtsort);

INSERT INTO {AW}.biografie_bt
    (aw_id, mdb_id, geburtsdatum, sterbedatum, geburtsort, geburtsland,
     geschlecht, familienstand, religion, beruf, vita_kurz)
SELECT z.aw_id, z.mdb_id, s.geburtsdatum, s.sterbedatum,
       coalesce(nullif(s.geburtsort, ''),    'unbekannt'),
       coalesce(nullif(s.geburtsland, ''),   'unbekannt'),
       coalesce(nullif(s.geschlecht, ''),    'unbekannt'),
       coalesce(nullif(s.familienstand, ''), 'unbekannt'),
       coalesce(nullif(s.religion, ''),      'unbekannt'),
       coalesce(nullif(s.beruf, ''),         'unbekannt'),
       coalesce(nullif(s.vita_kurz, ''),     'unbekannt')
  FROM {AW}.mdb_zu_aw z
  JOIN roh_bundestag.stammdaten_mdb s ON s.id = z.mdb_id
 WHERE z.aw_id IN (SELECT politician_id FROM {AW}.mandat);

COMMENT ON TABLE {AW}.biografie_bt IS
 'Biografischer Block der MdB-Stammdaten (Lieferung {LIEFERUNG}) fuer die '
 'Personen mit Mandat. Verbunden ueber mdb_zu_aw, NICHT ueber '
 'politician.ext_id_bundestagsverwaltung - dort steht bei neun Gewaehlten '
 'keine Bundestagsnummer.';
COMMENT ON COLUMN {AW}.biografie_bt.geburtsdatum IS
 'Tagesgenau und lueckenlos. Abgeordnetenwatch liefert nur das Geburtsjahr und '
 'das zu 97,8 % - fuer alles, was aufs Datum ankommt, gilt diese Spalte.';
COMMENT ON COLUMN {AW}.biografie_bt.geburtsort IS
 'Amtliche Schreibweise, Text mit historischem Kontext: "Quedlinburg / Bezirk '
 'Halle" nennt die DDR-Gliederung, nicht den heutigen Kreis. KEIN '
 'Ortsschluessel - die Koordinate kommt aus Wikidata, dieser Text ist die '
 'Gegenprobe dazu.';
COMMENT ON COLUMN {AW}.biografie_bt.geburtsland IS
 'ALS MERKMAL UNBRAUCHBAR: 829 ohne Angabe, 387 "Deutschland", 46 ein anderes '
 'Land. `unbekannt` heisst hier NICHT Deutschland - sonst waeren es 1.216 '
 'Deutsche. Uebernommen, aber nicht auszuwerten.';
"""


def main():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()

    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {AW}.biografie_bt;")
        n = cur.fetchone()[0]
        cur.execute(f"SELECT count(DISTINCT politician_id) FROM {AW}.mandat;")
        soll = cur.fetchone()[0]
        log.info("--- %d von %d Personen mit Mandat haben einen biografischen Satz ---",
                 n, soll)

        log.info("--- Wie gut gefuellt ---")
        cur.execute(f"""SELECT count(geburtsdatum), count(sterbedatum) FROM {AW}.biografie_bt;""")
        gd, sd = cur.fetchone()
        log.info("   %-16s %5d von %d  (%.1f %%)", "geburtsdatum", gd, n, 100 * gd / n)
        log.info("   %-16s %5d von %d  (%.1f %%)", "sterbedatum", sd, n, 100 * sd / n)
        for sp in TEXTFELDER:
            cur.execute(f"""SELECT count(*) FROM {AW}.biografie_bt
                             WHERE {sp} <> 'unbekannt';""")
            k = cur.fetchone()[0]
            log.info("   %-16s %5d von %d  (%.1f %%)", sp, k, n, 100 * k / n)

        cur.execute(f"""SELECT p.aw_id, p.first_name || ' ' || p.last_name
                          FROM {AW}.politician p
                         WHERE p.aw_id IN (SELECT politician_id FROM {AW}.mandat)
                           AND p.aw_id NOT IN (SELECT aw_id FROM {AW}.biografie_bt);""")
        fehlt = cur.fetchall()
        if fehlt:
            log.warning("--- %d ohne Satz in den Stammdaten ---", len(fehlt))
            for r in fehlt:
                log.warning("      %s  %s", r[0], r[1])

        log.info("--- Gegenprobe gegen abgeordnetenwatch: dasselbe Geburtsjahr? ---")
        cur.execute(f"""
            SELECT count(*) FILTER (WHERE p.year_of_birth IS NOT NULL),
                   count(*) FILTER (WHERE p.year_of_birth
                                          = extract(year FROM b.geburtsdatum)),
                   count(*) FILTER (WHERE p.year_of_birth IS NOT NULL
                                      AND p.year_of_birth
                                          <> extract(year FROM b.geburtsdatum))
              FROM {AW}.biografie_bt b JOIN {AW}.politician p ON p.aw_id = b.aw_id;""")
        hat, gleich, anders = cur.fetchone()
        log.info("   %d mit Jahr bei abgeordnetenwatch, %d gleich, %d verschieden",
                 hat, gleich, anders)
        if anders:
            cur.execute(f"""
                SELECT p.first_name || ' ' || p.last_name, p.year_of_birth,
                       b.geburtsdatum
                  FROM {AW}.biografie_bt b JOIN {AW}.politician p ON p.aw_id = b.aw_id
                 WHERE p.year_of_birth IS NOT NULL
                   AND p.year_of_birth <> extract(year FROM b.geburtsdatum);""")
            for r in cur.fetchall():
                log.warning("      %-28s aw %s, amtlich %s", r[0][:26], r[1], r[2])

        log.info("--- Die haeufigsten Geburtsorte ---")
        cur.execute(f"""SELECT geburtsort, count(*) FROM {AW}.biografie_bt
                         WHERE geburtsort <> 'unbekannt'
                         GROUP BY 1 ORDER BY 2 DESC LIMIT 8;""")
        for ort, k in cur.fetchall():
            log.info("   %-40s %3d", ort[:38], k)
    conn.close()


if __name__ == "__main__":
    main()
