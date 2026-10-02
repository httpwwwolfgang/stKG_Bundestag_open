import csv
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query


LIEFERUNG = "bt_mdb_stammdaten"

AW = "politiker_innen"
ROH = "roh_bundestag"

KORREKTUREN = (Path(__file__).resolve().parents[2] / "01_fetch"
               / "abgeordnetenwatch" / "korrekturen_ext_id.csv")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("biografie")


DDL = f"""
DROP TABLE IF EXISTS {AW}.fraktionszugehoerigkeit;
DROP TABLE IF EXISTS {AW}.biografie;
DROP VIEW IF EXISTS {AW}.mdb_zu_aw;

CREATE VIEW {AW}.mdb_zu_aw AS
SELECT p.ext_id_bundestagsverwaltung AS mdb_id, min(p.aw_id) AS aw_id,
       'geliefert'::text AS herkunft
  FROM {AW}.politician p
 WHERE p.ext_id_bundestagsverwaltung IS NOT NULL
   AND length(p.ext_id_bundestagsverwaltung) = 8
   AND EXISTS (SELECT 1 FROM {AW}.candidacy_mandate m
                WHERE m.politician_id = p.aw_id AND m.type = 'mandate')
 GROUP BY 1
UNION ALL
SELECT k.mdb_id, k.aw_id, 'korrigiert'
  FROM {AW}.korrektur_ext_id k;

COMMENT ON VIEW {AW}.mdb_zu_aw IS
 'Bundestagsnummer -> aw_id, eindeutig. Zwei Besonderheiten: (1) Nur Personen '
 'MIT Bundestagsmandat - die Nummer 11002746 steht bei abgeordnetenwatch an '
 'zwei Menschen, und nur einer sass im Bundestag. (2) Acht Zuordnungen kommen '
 'aus korrekturen_ext_id.csv, weil abgeordnetenwatch dort eine vierstellige '
 'Nummer ins Feld kopiert hat. herkunft unterscheidet beides.';

CREATE TABLE {AW}.biografie AS
SELECT s.id                          AS mdb_id,
       p.aw_id,
       n.vorname,
       n.nachname,
       n.akad_titel,
       n.adel,
       n.praefix,
       n.ortszusatz,
       s.geburtsdatum,
       s.geburtsort,
       s.geburtsland,
       s.sterbedatum,
       s.geschlecht,
       s.familienstand,
       s.religion,
       s.beruf,
       s.partei_kurz,
       s.vita_kurz,
       p.residence                   AS wohnort_aw
  FROM {ROH}.stammdaten_mdb s
  JOIN {ROH}.stammdaten_mdb_name n ON n.id = s.id AND n.lfd = 1
  LEFT JOIN {AW}.mdb_zu_aw z ON z.mdb_id = s.id
  LEFT JOIN {AW}.politician p ON p.aw_id = z.aw_id
 WHERE s.id IN (SELECT id FROM {ROH}.stammdaten_mdb_wahlperiode
                 WHERE wp IN (18, 19, 20));
ALTER TABLE {AW}.biografie ADD PRIMARY KEY (mdb_id);
CREATE INDEX ON {AW}.biografie (aw_id);

CREATE TABLE {AW}.fraktionszugehoerigkeit AS
SELECT i.id                          AS mdb_id,
       p.aw_id,
       i.wp,
       i.lfd,
       i.ins_lang                    AS fraktion,
       i.mdbins_von                  AS von,
       i.mdbins_bis                  AS bis,
       i.fkt_lang                    AS funktion,
       i.fktins_von                  AS funktion_von,
       i.fktins_bis                  AS funktion_bis
  FROM {ROH}.stammdaten_mdb_institution i
  LEFT JOIN {AW}.mdb_zu_aw z ON z.mdb_id = i.id
  LEFT JOIN {AW}.politician p ON p.aw_id = z.aw_id
 WHERE i.insart_lang = 'Fraktion/Gruppe' AND i.wp IN (18, 19, 20);
ALTER TABLE {AW}.fraktionszugehoerigkeit ADD PRIMARY KEY (mdb_id, wp, lfd);
CREATE INDEX ON {AW}.fraktionszugehoerigkeit (aw_id);

COMMENT ON TABLE {AW}.biografie IS
 'Amtliche Personendaten des Bundestages fuer die Abgeordneten der '
 'Wahlperioden 18 bis 20. Angeschlossen ueber ext_id_bundestagsverwaltung. '
 'aw_id ist NULL, wo abgeordnetenwatch eine falsche Nummer fuehrt (L8).';
COMMENT ON COLUMN {AW}.biografie.wohnort_aw IS
 'Wohnort laut abgeordnetenwatch - KEIN amtlicher Wert. Nur bei 389 der 1.271 '
 'Abgeordneten gefuellt, ohne Zeitbezug, Stand des Abrufs. Sagt NICHT, wo '
 'jemand zur Zeit seines Mandats gewohnt hat.';
COMMENT ON TABLE {AW}.fraktionszugehoerigkeit IS
 'Fraktionshistorie mit Datum, aus dem MdB-XML. Mehrere Zeilen je Person und '
 'Wahlperiode bedeuten einen Wechsel - in WP 20 bei 49 von 772 Abgeordneten. '
 'Abgeordnetenwatch fuehrt am Mandat nur eine Fraktion. Die Namen stehen '
 'ausgeschrieben und sind NICHT auf die Kuerzel von abgeordnetenwatch '
 'abgebildet.';
"""


def bericht():
    log.info("--- Was entstanden ist ---")
    for tab, n in query(f"""
            SELECT 'biografie', count(*)::text FROM {AW}.biografie
            UNION ALL SELECT 'fraktionszugehoerigkeit', count(*)::text
              FROM {AW}.fraktionszugehoerigkeit;"""):
        log.info("   %-26s %s", tab, n)

    log.info("--- Wie vollstaendig ist die Biografie? ---")
    for zeile in query(f"""
            SELECT count(*)::text, count(aw_id)::text, count(geburtsdatum)::text,
                   count(geburtsort)::text, count(beruf)::text, count(religion)::text,
                   count(familienstand)::text, count(wohnort_aw)::text
              FROM {AW}.biografie;"""):
        for name, n in zip(["Personen", "mit aw_id", "Geburtsdatum", "Geburtsort",
                            "Beruf", "Religion", "Familienstand",
                            "Wohnort (aw)"], zeile):
            log.info("   %-18s %s", name, n)

    log.info("--- Bleibt noch jemand ohne Anschluss? ---")
    for vor, nach, mdb in query(f"""
            SELECT vorname, nachname, mdb_id FROM {AW}.biografie
             WHERE aw_id IS NULL ORDER BY nachname;"""):
        log.info("   %s %s (%s)", vor, nach, mdb)
    log.info("--- Woher die Zuordnung stammt ---")
    for herkunft, n in query(f"""
            SELECT z.herkunft, count(*)::text FROM {AW}.biografie b
              JOIN {AW}.mdb_zu_aw z ON z.mdb_id = b.mdb_id
             GROUP BY 1 ORDER BY 2 DESC;"""):
        log.info("   %-14s %s", herkunft, n)

    log.info("--- Fraktionswechsel je Wahlperiode ---")
    for wp, personen, mit_wechsel, zeilen in query(f"""
            SELECT wp, count(DISTINCT mdb_id)::text,
                   count(*) FILTER (WHERE n > 1)::text, count(*)::text
              FROM (SELECT wp, mdb_id, count(*) OVER (PARTITION BY wp, mdb_id) AS n
                      FROM {AW}.fraktionszugehoerigkeit) x
             GROUP BY wp ORDER BY wp;"""):
        log.info("   WP %s: %s Personen, %s Zeilen aus Wechseln, %s Zeilen gesamt",
                 wp, personen, mit_wechsel, zeilen)

    log.info("--- Funktionen in der Fraktion ---")
    for funktion, n in query(f"""
            SELECT funktion, count(*)::text FROM {AW}.fraktionszugehoerigkeit
             WHERE funktion IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT 8;"""):
        log.info("   %-44s %s", funktion[:43], n)

    log.info("--- Gegenprobe: Gregor Gysi, Wahlperiode 20 ---")
    for fraktion, von, bis in query(f"""
            SELECT f.fraktion, f.von::text, coalesce(f.bis::text, 'offen')
              FROM {AW}.fraktionszugehoerigkeit f
              JOIN {AW}.biografie b ON b.mdb_id = f.mdb_id
             WHERE b.nachname = 'Gysi' AND f.wp = 20 ORDER BY f.von;"""):
        log.info("   %-48s %s bis %s", fraktion[:47], von, bis)


def lade_korrekturen():
    if not KORREKTUREN.exists():
        raise SystemExit(f"Korrekturtabelle fehlt: {KORREKTUREN}")
    with KORREKTUREN.open(encoding="utf-8", newline="") as f:
        zeilen = list(csv.DictReader(f, delimiter=";"))

    werte = ",\n".join(
        "('{}', {}, '{}', {}, '{}', '{}')".format(
            z["mdb_id"], int(z["aw_id"]), z["person"].replace("'", "''"),
            int(z["geburtsjahr"]), z["wert_geliefert"], z["geprueft_am"])
        for z in zeilen)

    sql = f"""
DROP VIEW IF EXISTS {AW}.mdb_zu_aw;
DROP TABLE IF EXISTS {AW}.korrektur_ext_id;

CREATE TABLE {AW}.korrektur_ext_id (
    mdb_id         TEXT PRIMARY KEY,
    aw_id          INTEGER NOT NULL,
    person         TEXT,
    geburtsjahr    SMALLINT,
    wert_geliefert TEXT,
    geprueft_am    DATE
);

INSERT INTO {AW}.korrektur_ext_id
    (mdb_id, aw_id, person, geburtsjahr, wert_geliefert, geprueft_am) VALUES
{werte};

COMMENT ON TABLE {AW}.korrektur_ext_id IS
 'Acht Zuordnungen Bundestagsnummer -> aw_id, die abgeordnetenwatch nicht '
 'liefert, weil dort eine vierstellige Nummer im Feld steht. '
 'Belegt ueber Nachname, Vorname UND Geburtsjahr. Entscheidungen in '
 '01_fetch/abgeordnetenwatch/korrekturen_ext_id.csv';
"""
    tmp = Path(tempfile.gettempdir()) / "korrekturen_ext_id.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, "korrekturen ext_id")
    log.info("%d Zuordnungen aus %s geladen", len(zeilen), KORREKTUREN.name)
    for z in zeilen:
        log.info("   %-22s aw %-8s ext_id %-8s -> mdb %s  (Jg %s)",
                 z["person"], z["aw_id"], z["wert_geliefert"], z["mdb_id"],
                 z["geburtsjahr"])


def main():
    lade_korrekturen()
    run_sql(DDL, "biografie und fraktionshistorie")
    bericht()


if __name__ == "__main__":
    main()
