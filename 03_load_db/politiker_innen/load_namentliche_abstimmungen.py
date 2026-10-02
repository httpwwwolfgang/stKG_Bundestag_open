import glob
import json
import logging
import sys
import tempfile
from pathlib import Path

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "politiker_innen"
          / "bundestag_namentliche_abstimmungen")
from zugang import dsn
DSN = dsn()
AW = "politiker_innen"
LIEFERUNG = "bt_namentliche_abstimmungen"

STIMMSPALTEN = (("ja", "ja"), ("nein", "nein"), ("Enthaltung", "enthaltung"),
                ("ungültig", "ungueltig"), ("nichtabgegeben", "nicht_abgegeben"))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("namentliche-laden")


DDL = f"""
SET client_min_messages TO WARNING;
DROP TABLE IF EXISTS {AW}.stimme_bt;
DROP TABLE IF EXISTS {AW}.abstimmung_bt;

CREATE TABLE {AW}.abstimmung_bt (
    datei        TEXT PRIMARY KEY,
    wahlperiode  SMALLINT NOT NULL,
    sitzung      SMALLINT NOT NULL,
    abstimmung   SMALLINT NOT NULL,
    datum        DATE     NOT NULL,
    titel        TEXT,
    sha256       TEXT
);
CREATE INDEX ON {AW}.abstimmung_bt (datum);
CREATE INDEX ON {AW}.abstimmung_bt (wahlperiode, sitzung, abstimmung);

CREATE TABLE {AW}.stimme_bt (
    datei        TEXT NOT NULL REFERENCES {AW}.abstimmung_bt (datei),
    wahlperiode  SMALLINT NOT NULL,
    mdb_id       TEXT,
    mandat_id    INTEGER,
    nachname     TEXT NOT NULL,
    vorname      TEXT NOT NULL,
    fraktion_roh TEXT,
    stimme       TEXT NOT NULL,
    bemerkung    TEXT,
    PRIMARY KEY (datei, nachname, vorname)
);
CREATE INDEX ON {AW}.stimme_bt (mandat_id);
CREATE INDEX ON {AW}.stimme_bt (mdb_id);

COMMENT ON TABLE {AW}.abstimmung_bt IS
 'Namentliche Abstimmungen des Bundestages, Lieferung bt_namentliche_'
 'abstimmungen. 642 fuer die Wahlperioden 18 bis 20 - gegenueber 459 bei '
 'abgeordnetenwatch, das nur einen Teil fuehrt. Schluessel ist die DATEI: '
 '(wahlperiode, sitzung, abstimmung) ist NICHT eindeutig, siehe Kommentar an '
 'der Spalte abstimmung.';
COMMENT ON COLUMN {AW}.abstimmung_bt.abstimmung IS
 'Abstimmungsnummer der Sitzung, wie geliefert - NICHT eindeutig. Am '
 '30.01.2025 tragen zwei verschiedene Abstimmungen (Eunavfor Aspides und '
 'Unmiss) beide Sitzung 210, Abstimmung 2. Als Schluessel unbrauchbar, als '
 'gelieferte Angabe behalten.';
COMMENT ON TABLE {AW}.stimme_bt IS
 'Das Stimmverhalten aller Mitglieder je namentlicher Abstimmung, 443.382 '
 'Zeilen. Die Person ist ueber mdb_namensalias an die MdB-Nummer und ueber '
 'mdb_zu_aw an das Mandat gebunden - der Namensabgleich ist dort geloest, '
 'nicht hier.';
COMMENT ON COLUMN {AW}.stimme_bt.stimme IS
 'ja | nein | enthaltung | ungueltig | nicht_abgegeben. In der Lieferung sind '
 'das fuenf 0/1-Spalten; geprueft ist, dass jede Zeile genau eine 1 traegt.';
COMMENT ON COLUMN {AW}.stimme_bt.fraktion_roh IS
 'Fraktionsbezeichnung, wie die Datei sie schreibt - uneinheitlich '
 '(DIE LINKE. / Die Linke / DIE LINKE, BUE90/GR). Unveraendert uebernommen; '
 'fuer die belastbare Zugehoerigkeit fraktion_mitgliedschaft nehmen.';
COMMENT ON COLUMN {AW}.stimme_bt.mandat_id IS
 'Das Mandat in candidacy_mandate, ueber mdb_zu_aw. NULL, wo die Person in '
 'dieser Wahlperiode kein Mandat im Bestand hat.';
"""


def main():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


    with conn.cursor() as cur:
        cur.execute(f"""SELECT such_nachname, such_vorname, such_ortszusatz, mdb_id
                          FROM {AW}.mdb_namensalias;""")
        alias = {}
        for sn, sv, so, mdb in cur.fetchall():
            alias.setdefault((sn, sv), set()).add(mdb)
            alias.setdefault((sn, sv, so), set()).add(mdb)
        cur.execute(f"""
            SELECT z.mdb_id,
                   CASE substring(m.parliament_period_label from '[0-9]{{4}}')::int
                        WHEN 2013 THEN 18 WHEN 2017 THEN 19 WHEN 2021 THEN 20 END,
                   m.aw_id
              FROM {AW}.mdb_zu_aw z
              JOIN {AW}.candidacy_mandate m ON m.politician_id = z.aw_id
             WHERE m.type = 'mandate';""")
        mandate = {(mdb, wp): aw for mdb, wp, aw in cur.fetchall() if wp}
    log.info("%d Aliasschluessel, %d Mandate ueber die MdB-Nummer erreichbar",
             len(alias), len(mandate))

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from baue_namensalias import schluessel, zerlege


    aus_protokoll = {}
    protokoll = QUELLE / "abruf.json"
    if protokoll.exists():
        for eintrag in json.loads(protokoll.read_text(encoding="utf-8")).values():
            aus_protokoll[eintrag["datei"]] = (eintrag.get("titel") or None,
                                               eintrag.get("sha256"))
    log.info("%d Titel und Pruefsummen aus abruf.json", len(aus_protokoll))

    dateien = sorted(glob.glob(str(QUELLE / "*.xls*")))
    log.info("%d Dateien werden geladen ...", len(dateien))

    abst, stimmen, ohne_person, ohne_mandat = [], [], 0, 0
    for i, f in enumerate(dateien, 1):
        df = pd.read_excel(f)
        wp = int(df["Wahlperiode"].iloc[0])
        name = Path(f).name
        titel, sha = aus_protokoll.get(name, (None, None))
        abst.append((name, wp, int(df["Sitzungnr"].iloc[0]),
                     int(df["Abstimmnr"].iloc[0]), name[:10], titel, sha))

        for _, r in df.iterrows():
            wert = None
            for sp, bez in STIMMSPALTEN:
                if sp in df.columns and r.get(sp) == 1:
                    wert = bez
                    break
            if wert is None:
                continue

            basis, zusatz = zerlege(r["Name"])
            sv = schluessel(r["Vorname"])
            kand = alias.get((basis, sv, zusatz)) or alias.get((basis, sv)) or set()
            mdb = next(iter(kand)) if len(kand) == 1 else None
            if mdb is None:
                ohne_person += 1
            mandat = mandate.get((mdb, wp)) if mdb else None
            if mdb and mandat is None:
                ohne_mandat += 1

            stimmen.append((name, wp, mdb, mandat, str(r["Name"]),
                            str(r["Vorname"]),
                            None if pd.isna(r.get("Fraktion/Gruppe")) else str(r["Fraktion/Gruppe"]),
                            wert,
                            None if pd.isna(r.get("Bemerkung")) else str(r.get("Bemerkung"))))
        if i % 200 == 0:
            log.info("   %d/%d Dateien, %d Stimmzeilen", i, len(dateien), len(stimmen))

    with conn.cursor() as cur:
        execute_values(cur, f"""INSERT INTO {AW}.abstimmung_bt
            (datei, wahlperiode, sitzung, abstimmung, datum, titel, sha256)
            VALUES %s""", abst)
        execute_values(cur, f"""INSERT INTO {AW}.stimme_bt
            (datei, wahlperiode, mdb_id, mandat_id, nachname, vorname,
             fraktion_roh, stimme, bemerkung) VALUES %s""",
            stimmen, page_size=5000)
    conn.commit()

    log.info("--- Was geladen wurde ---")
    with conn.cursor() as cur:
        cur.execute(f"""SELECT wahlperiode, count(*) FROM {AW}.abstimmung_bt
                        GROUP BY 1 ORDER BY 1;""")
        for wp, n in cur.fetchall():
            log.info("   WP %d: %3d Abstimmungen", wp, n)
        cur.execute(f"""SELECT wahlperiode, count(*), count(mdb_id),
                               count(mandat_id) FROM {AW}.stimme_bt
                        GROUP BY 1 ORDER BY 1;""")
        for wp, n, mit_mdb, mit_mandat in cur.fetchall():
            log.info("   WP %d: %7d Stimmen, %7d mit MdB-Nummer, %7d mit Mandat",
                     wp, n, mit_mdb, mit_mandat)
        cur.execute(f"SELECT stimme, count(*) FROM {AW}.stimme_bt GROUP BY 1 ORDER BY 2 DESC;")
        for s, n in cur.fetchall():
            log.info("   %-16s %7d", s, n)

        log.info("--- Gegenprobe: Stimmen je Abstimmung ---")
        cur.execute(f"""
            SELECT a.wahlperiode, count(*)::text, min(x.n)::text, max(x.n)::text
              FROM {AW}.abstimmung_bt a
              JOIN (SELECT datei, count(*) AS n FROM {AW}.stimme_bt
                     GROUP BY 1) x ON x.datei = a.datei
             GROUP BY 1 ORDER BY 1;""")
        for wp, n, mi, ma in cur.fetchall():
            log.info("   WP %s: %s Abstimmungen, %s bis %s Stimmen je Abstimmung",
                     wp, n, mi, ma)

        log.info("--- Die doppelt vergebene Nummer ---")
        cur.execute(f"""
            SELECT wahlperiode, sitzung, abstimmung, count(*), string_agg(titel, ' | ')
              FROM {AW}.abstimmung_bt GROUP BY 1,2,3 HAVING count(*) > 1;""")
        for wp, s, a2, n, titel in cur.fetchall():
            log.info("   WP%d Sitzung %d Abstimmung %d: %d Eintraege - %s",
                     wp, s, a2, n, str(titel)[:70])

    log.info("   ohne MdB-Nummer: %d, mit Nummer aber ohne Mandat: %d",
             ohne_person, ohne_mandat)
    conn.close()


if __name__ == "__main__":
    main()
