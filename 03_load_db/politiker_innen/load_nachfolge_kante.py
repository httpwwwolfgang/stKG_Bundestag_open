import csv
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db import run_sql, run_sql_file, query
from pruefe_nachfolge_zuordnung import lies_stammdaten, treffer


LIEFERUNG = "bt_ausgeschiedene"

ROH = "roh_bundestag"


ERGAENZT = (Path(__file__).resolve().parents[2] / "01_fetch"
            / "bundestag" / "ergaenzte_nachfolge.csv")
ZIEL = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("nachfolge-kante")


DDL = f"""
CREATE TABLE IF NOT EXISTS {ZIEL}.nachfolge (
    wp                    SMALLINT NOT NULL,
    lfd                   SMALLINT NOT NULL,
    quelle                TEXT,
    ausgeschieden_am      DATE,
    eingetreten_am        DATE,
    verstorben            BOOLEAN NOT NULL,
    nachfolger_benannt    BOOLEAN NOT NULL,
    vorgaenger_name       TEXT,
    vorgaenger_mdb_id     TEXT,
    vorgaenger_aw_id      INTEGER,
    vorgaenger_herkunft   TEXT,
    nachfolger_name       TEXT,
    nachfolger_mdb_id     TEXT,
    nachfolger_aw_id      INTEGER,
    nachfolger_herkunft   TEXT,
    PRIMARY KEY (wp, lfd)
);

ALTER TABLE {ZIEL}.nachfolge ADD COLUMN IF NOT EXISTS quelle TEXT;

COMMENT ON COLUMN {ZIEL}.nachfolge.quelle IS
 'bundestag_seite = steht auf "Ausgeschiedene Abgeordnete und deren '
 'Nachfolger". ergaenzt = Vorgang, den die Seite NICHT fuehrt, weil formal '
 'niemand ausgeschieden ist - wer ein Mandat nie annimmt, scheidet nicht aus. '
 'Belegt in 01_fetch/bundestag/ergaenzte_nachfolge.csv.';
COMMENT ON TABLE {ZIEL}.nachfolge IS
 'Wer im Bundestag auf wen nachgerueckt ist. Quelle: roh_bundestag.nachfolge '
 '(Deutscher Bundestag, "Ausgeschiedene Abgeordnete und deren Nachfolger"). '
 'Die Personenschluessel stehen NICHT in der Quelle, sie sind abgeleitet - '
 'siehe *_herkunft.';
COMMENT ON COLUMN {ZIEL}.nachfolge.vorgaenger_herkunft IS
 'Wie der Schluessel bestimmt wurde. name_wp_extid = Name und Wahlperiode '
 'trafen genau eine Person der MdB-Stammdaten, deren MdB-Nummer ueber die '
 'Sicht mdb_zu_aw eine aw_id hat. Diese Sicht statt politician direkt: bei '
 'acht vorzeitig Ausgeschiedenen der 19. Wahlperiode steht in '
 'ext_id_bundestagsverwaltung eine vierstellige Hausnummer statt der '
 'MdB-Nummer, und sie stehen alle auf der '
 'Vorgaengerseite. name_wp = Stammdaten getroffen, aber keine aw_id. '
 'unbestimmt = kein oder mehr als ein Treffer; die ID bleibt NULL.';
COMMENT ON COLUMN {ZIEL}.nachfolge.nachfolger_benannt IS
 'FALSE, wenn die Quelle keinen Nachfolger nennt. Dann sind die '
 'Nachfolgerspalten NULL, ohne dass etwas ungeloest waere.';
"""


def sql_wert(wert):
    if wert is None:
        return "NULL"
    if isinstance(wert, bool):
        return "TRUE" if wert else "FALSE"
    if isinstance(wert, int):
        return str(wert)
    return "'" + str(wert).replace("'", "''") + "'"


def politiker_nach_extid():
    tabelle = {}
    for aw_id, mdb_id in query(f"""
            SELECT aw_id, mdb_id FROM {ZIEL}.mdb_zu_aw;"""):
        tabelle[mdb_id.strip()] = int(aw_id)
    return tabelle


def loese_auf(name, wp, stamm, ext, offen):
    if not name:
        return None, None, None
    kandidaten = treffer(name, stamm.get(wp, []))
    if len(kandidaten) != 1:
        offen.append((wp, name, len(kandidaten)))
        return None, None, "unbestimmt"
    mdb_id = kandidaten[0][0].strip()
    aw_id = ext.get(mdb_id)
    return mdb_id, aw_id, "name_wp_extid" if aw_id else "name_wp"


def lies_ergaenzte():
    if not ERGAENZT.exists():
        return []
    with ERGAENZT.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def main():
    stamm = lies_stammdaten()
    ext = politiker_nach_extid()
    log.info("%d Politiker bei Abgeordnetenwatch tragen eine ext_id.", len(ext))

    quelle = query(f"""
        SELECT wp, lfd, coalesce(ausgeschieden_am::text, ''),
               coalesce(eingetreten_am::text, ''), verstorben,
               nachfolger_benannt, coalesce(vorgaenger_name, ''),
               coalesce(nachfolger_name, '')
          FROM {ROH}.nachfolge ORDER BY wp, lfd;""")

    offen, zeilen = [], []
    for wp, lfd, aus, ein, tot, benannt, v_name, n_name in quelle:
        wp, lfd = int(wp), int(lfd)
        v_mdb, v_aw, v_herkunft = loese_auf(v_name or None, wp, stamm, ext, offen)
        n_mdb, n_aw, n_herkunft = loese_auf(n_name or None, wp, stamm, ext, offen)
        zeilen.append((
            wp, lfd, aus or None, ein or None, tot == "t", benannt == "t",
            v_name or None, v_mdb, v_aw, v_herkunft,
            n_name or None, n_mdb, n_aw, n_herkunft,
            "bundestag_seite",
        ))


    beginn_setzen = []
    for z in lies_ergaenzte():
        wp = int(z["wp"])


        v_mdb = loese_auf(z["vorgaenger_name"], wp, stamm, ext, [])[0]
        n_mdb = loese_auf(z["nachfolger_name"], wp, stamm, ext, [])[0]
        zeilen.append((
            wp, int(z["lfd"]), z["ausgeschieden_am"] or None,
            z["eingetreten_am"] or None, False, True,
            z["vorgaenger_name"], v_mdb, int(z["vorgaenger_aw_id"]), "aus_csv",
            z["nachfolger_name"], n_mdb, int(z["nachfolger_aw_id"]), "aus_csv",
            "ergaenzt",
        ))
        if z["beginn_vorgaenger_setzen"]:
            beginn_setzen.append((int(z["vorgaenger_mandat_id"]),
                                  z["beginn_vorgaenger_setzen"]))
        log.info("Ergaenzt: %s -> %s, %s (Quelle: CSV, nicht Bundestagsseite)",
                 z["vorgaenger_name"], z["nachfolger_name"], z["eingetreten_am"])

    if offen:
        log.warning("%d Nennungen ohne eindeutigen Treffer - bleiben NULL:", len(offen))
        for wp, name, anzahl in offen:
            log.warning("   WP %s %-32s %d Treffer", wp, name, anzahl)

    run_sql(DDL, "politiker_innen.nachfolge anlegen")

    tmp = Path(tempfile.gettempdir()) / "nachfolge_kante.sql"
    spalten = ["wp", "lfd", "ausgeschieden_am", "eingetreten_am", "verstorben",
               "nachfolger_benannt", "vorgaenger_name", "vorgaenger_mdb_id",
               "vorgaenger_aw_id", "vorgaenger_herkunft", "nachfolger_name",
               "nachfolger_mdb_id", "nachfolger_aw_id", "nachfolger_herkunft",
               "quelle"]
    with tmp.open("w", encoding="utf-8") as f:
        setzen = ",\n    ".join(f"{s} = EXCLUDED.{s}" for s in spalten[2:])
        f.write(f"INSERT INTO {ZIEL}.nachfolge ({', '.join(spalten)}) VALUES\n")
        f.write(",\n".join("(" + ", ".join(sql_wert(w) for w in z) + ")"
                           for z in zeilen))
        f.write(f"\nON CONFLICT (wp, lfd) DO UPDATE SET\n    {setzen};\n")
    run_sql_file(tmp, "nachfolge-kante")


    for mandat_id, beginn in beginn_setzen:
        run_sql(f"""UPDATE {ZIEL}.candidacy_mandate
                       SET start_date = DATE '{beginn}'
                     WHERE aw_id = {mandat_id} AND start_date IS NULL;""",
                f"Beginn fuer Mandat {mandat_id}")
        log.info("Mandatsbeginn %s fuer Mandat %s gesetzt - Dauer 0 Tage",
                 beginn, mandat_id)

    log.info("--- Ergebnis ---")
    for wp, n, v_ok, n_ok in query(f"""
            SELECT wp, count(*), count(vorgaenger_aw_id), count(nachfolger_aw_id)
              FROM {ZIEL}.nachfolge GROUP BY wp ORDER BY wp;"""):
        log.info("WP %s: %s Kanten, %s Vorgaenger und %s Nachfolger mit aw_id",
                 wp, n, v_ok, n_ok)

    for herkunft, n in query(f"""
            SELECT herkunft, count(*) FROM (
                SELECT coalesce(vorgaenger_herkunft, 'kein Vorgaenger') AS herkunft
                  FROM {ZIEL}.nachfolge
                UNION ALL
                SELECT coalesce(nachfolger_herkunft, 'kein Nachfolger')
                  FROM {ZIEL}.nachfolge) x
             GROUP BY 1 ORDER BY 2 DESC;"""):
        log.info("   %-22s %s", herkunft, n)

    log.info("Gegenprobe - Markus Uhl und sein Vorgaenger:")
    for zeile in query(f"""
            SELECT wp, lfd, vorgaenger_name, vorgaenger_aw_id, ausgeschieden_am,
                   nachfolger_name, nachfolger_aw_id, eingetreten_am
              FROM {ZIEL}.nachfolge
             WHERE nachfolger_mdb_id IS NOT NULL AND wp = 18 AND lfd = 1;"""):
        log.info("   WP %s Zeile %s: %s (aw %s) raus %s -> %s (aw %s) rein %s",
                 *zeile)


if __name__ == "__main__":
    main()
