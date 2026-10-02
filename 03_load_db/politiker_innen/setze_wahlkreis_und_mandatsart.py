import csv
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

AW = "politiker_innen"
ROH = "roh_bundestag"

KORREKTUREN = (Path(__file__).resolve().parents[2] / "01_fetch"
               / "abgeordnetenwatch" / "korrekturen_wahlkreis.csv")


WP = """CASE m.parliament_period_label
            WHEN 'Bundestag 2013 - 2017' THEN 18
            WHEN 'Bundestag 2017 - 2021' THEN 19
            WHEN 'Bundestag 2021 - 2025' THEN 20 END"""

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("wahlkreis")


DDL = f"""
ALTER TABLE {AW}.candidacy_mandate
    ADD COLUMN IF NOT EXISTS wkr_nr_amtlich      SMALLINT,
    ADD COLUMN IF NOT EXISTS wkr_name_amtlich    TEXT,
    ADD COLUMN IF NOT EXISTS mandatsart_amtlich  TEXT,
    ADD COLUMN IF NOT EXISTS wkr_nr              SMALLINT,
    ADD COLUMN IF NOT EXISTS wkr_herkunft        TEXT,
    ADD COLUMN IF NOT EXISTS mandatsart          TEXT,
    ADD COLUMN IF NOT EXISTS mandatsart_herkunft TEXT;

COMMENT ON COLUMN {AW}.candidacy_mandate.wkr_nr_amtlich IS
 'WKR_NUMMER aus MDB_STAMMDATEN.XML, unveraendert. Nur bei Mandaten gefuellt; '
 'die Stammdaten kennen keine Kandidaturen. Kein Eingriff - zweite Quelle '
 'daneben, nichts ersetzt.';
COMMENT ON COLUMN {AW}.candidacy_mandate.mandatsart_amtlich IS
 'MANDATSART aus MDB_STAMMDATEN.XML: Direktwahl oder Landesliste. Im XML zu '
 '100 %% gefuellt (658/750/772 in WP 18/19/20).';
COMMENT ON COLUMN {AW}.candidacy_mandate.wkr_nr IS
 'Der zu verwendende Wahlkreis. Reihenfolge: Korrektur aus '
 'korrekturen_wahlkreis.csv, sonst abgeordnetenwatch, sonst XML. Woher der '
 'Wert stammt, steht in wkr_herkunft - NIE ohne diese Spalte auswerten.';
COMMENT ON COLUMN {AW}.candidacy_mandate.wkr_herkunft IS
 'korrigiert = Einzelentscheidung mit Beleg in korrekturen_wahlkreis.csv. '
 'geliefert = von abgeordnetenwatch. amtlich_ergaenzt = aus dem Bundestags-XML, '
 'weil abgeordnetenwatch keinen Wert hatte. NULL = keine Quelle nennt einen; '
 'bei Listenmandaten ist das der Sachverhalt, keine Luecke.';
ALTER TABLE {AW}.candidacy_mandate
    ADD COLUMN IF NOT EXISTS wahlkreisbezug TEXT GENERATED ALWAYS AS (
        CASE WHEN type <> 'mandate'          THEN NULL
             WHEN mandatsart = 'constituency' THEN 'direktmandat'
             WHEN wkr_nr IS NOT NULL          THEN 'wahlkreiskandidatur'
             WHEN mandatsart IS NOT NULL      THEN 'reine_liste'
             ELSE NULL END) STORED;

COMMENT ON COLUMN {AW}.candidacy_mandate.wahlkreisbezug IS
 'Typologie der Wahlkreisbindung, nur an Mandaten. '
 'direktmandat = hat die relative Mehrheit der Erststimmen gewonnen. '
 'wahlkreiskandidatur = ueber die Landesliste eingezogen, aber in einem '
 'Wahlkreis angetreten und dort unterlegen. reine_liste = in keinem '
 'Wahlkreis angetreten. '
 'Die Unterscheidung ist die zentrale unabhaengige Variable der Frage nach '
 'Wahlkreisbindung: Wer Listenabgeordnete pauschal als wahlkreisfern behandelt, '
 'wirft wahlkreiskandidatur und reine_liste zusammen - und das sind in der '
 'Legislatur 2021-2025 457 gegen 16 Mandate. '
 'GENERATED: rechnet sich aus mandatsart und wkr_nr derselben Zeile.';
COMMENT ON COLUMN {AW}.candidacy_mandate.mandatsart_herkunft IS
 'geliefert = mandate_won von abgeordnetenwatch. amtlich_ergaenzt = aus dem '
 'XML, weil abgeordnetenwatch nichts lieferte (18 Mandate). amtlich_ersetzt = '
 'aus dem XML anstelle des gelieferten moved_up (77 Mandate, Eingriff E1c). '
 'Ein list kann deshalb auch einen Nachruecker meinen - das XML kennt '
 'moved_up nicht; wer das wissen muss, fragt politiker_innen.nachfolge.';
"""


AMTLICH = f"""
UPDATE {AW}.candidacy_mandate m
   SET wkr_nr_amtlich     = s.wkr_nummer,
       wkr_name_amtlich   = s.wkr_name,
       mandatsart_amtlich = s.mandatsart
  FROM {AW}.politician p, {ROH}.stammdaten_mdb_wahlperiode s
 WHERE p.aw_id = m.politician_id
   AND s.id = p.ext_id_bundestagsverwaltung
   AND s.wp = {WP}
   AND m.type = 'mandate';
"""

BERICHT_WAHLKREIS = f"""
SELECT parliament_period_label,
       count(*) FILTER (WHERE wkr_herkunft = 'geliefert'),
       count(*) FILTER (WHERE wkr_herkunft = 'amtlich_ergaenzt'),
       count(*) FILTER (WHERE wkr_herkunft = 'korrigiert'),
       count(*) FILTER (WHERE wkr_herkunft IS NULL)
  FROM {AW}.candidacy_mandate WHERE type = 'mandate'
 GROUP BY 1 ORDER BY 1;
"""


def sql_wert(wert):
    if wert is None or wert == "":
        return "NULL"
    return "'" + str(wert).replace("'", "''") + "'"


def lies_korrekturen():
    if not KORREKTUREN.exists():
        raise SystemExit(f"Korrekturtabelle fehlt: {KORREKTUREN}")
    zeilen = []
    with KORREKTUREN.open(encoding="utf-8", newline="") as f:
        for z in csv.DictReader(f, delimiter=";"):
            wert = (z["wert_korrigiert"] or "").strip()
            zeilen.append({
                "aw_id": int(z["eintrag_id"]),
                "wert": int(wert) if wert else None,
                "person": z["person"],
                "eingriff": z["eingriff"],
                "geprueft_am": z["geprueft_am"],
            })
    return zeilen


def main():
    korrekturen = lies_korrekturen()
    log.info("%d Einzelkorrekturen aus %s", len(korrekturen), KORREKTUREN.name)
    for k in korrekturen:
        log.info("   %s  %-20s -> %s  (%s, geprueft %s)", k["aw_id"],
                 k["person"], k["wert"] if k["wert"] else "NULL",
                 k["eingriff"], k["geprueft_am"])

    run_sql(DDL, "Spalten anlegen")
    log.info("Schritt 1: amtliche Werte danebenstellen (kein Eingriff)")
    run_sql(AMTLICH, "amtliche Werte")


    tmp = Path(tempfile.gettempdir()) / "korrekturen_wahlkreis.sql"
    with tmp.open("w", encoding="utf-8") as f:
        f.write(f"DROP TABLE IF EXISTS {AW}.korrektur_wahlkreis;\n")
        f.write(f"""CREATE TABLE {AW}.korrektur_wahlkreis (
                       aw_id INTEGER PRIMARY KEY, wert SMALLINT,
                       eingriff TEXT, geprueft_am DATE);\n""")
        f.write(f"INSERT INTO {AW}.korrektur_wahlkreis "
                f"(aw_id, wert, eingriff, geprueft_am) VALUES\n")
        f.write(",\n".join(
            f"({k['aw_id']}, {k['wert'] if k['wert'] is not None else 'NULL'}, "
            f"{sql_wert(k['eingriff'])}, {sql_wert(k['geprueft_am'])})"
            for k in korrekturen) + ";\n")

        f.write(f"""
UPDATE {AW}.candidacy_mandate m
   SET wkr_nr = CASE
           WHEN k.aw_id IS NOT NULL THEN k.wert
           WHEN c.number IS NOT NULL THEN c.number
           ELSE m.wkr_nr_amtlich END,
       wkr_herkunft = CASE
           WHEN k.aw_id IS NOT NULL THEN 'korrigiert'
           WHEN c.number IS NOT NULL THEN 'geliefert'
           WHEN m.wkr_nr_amtlich IS NOT NULL THEN 'amtlich_ergaenzt'
           ELSE NULL END
  FROM {AW}.candidacy_mandate m2
  LEFT JOIN {AW}.constituency c ON c.aw_id = m2.constituency_id
  LEFT JOIN {AW}.korrektur_wahlkreis k ON k.aw_id = m2.aw_id
 WHERE m.aw_id = m2.aw_id;

UPDATE {AW}.candidacy_mandate m
   SET mandatsart = CASE
           WHEN m.mandate_won IS NOT NULL
                AND m.mandate_won <> 'moved_up'    THEN m.mandate_won
           WHEN m.mandatsart_amtlich = 'Direktwahl'  THEN 'constituency'
           WHEN m.mandatsart_amtlich = 'Landesliste' THEN 'list'
           ELSE NULL END,
       mandatsart_herkunft = CASE
           WHEN m.mandate_won IS NOT NULL
                AND m.mandate_won <> 'moved_up'    THEN 'geliefert'
           WHEN m.mandate_won = 'moved_up'
                AND m.mandatsart_amtlich IS NOT NULL THEN 'amtlich_ersetzt'
           WHEN m.mandatsart_amtlich IS NOT NULL   THEN 'amtlich_ergaenzt'
           ELSE NULL END;
""")
    log.info("Schritt 2 und 3: Wahlkreis und Mandatsart setzen (E1, E1b, E2, E6)")
    run_sql_file(tmp, "wahlkreis-mandatsart")

    bericht()


def bericht():
    log.info("--- Wahlkreis je Mandat, nach Herkunft ---")
    log.info("   %-24s%12s%18s%12s%10s", "Legislatur", "geliefert",
             "amtlich ergaenzt", "korrigiert", "ohne")
    for r in query(BERICHT_WAHLKREIS):
        log.info("   %-24s%12s%18s%12s%10s", *r)

    log.info("--- Die entscheidende Gegenprobe ---")
    for leg, n, ohne in query(f"""
            SELECT parliament_period_label, count(*),
                   count(*) FILTER (WHERE wkr_nr IS NULL)
              FROM {AW}.candidacy_mandate
             WHERE type='mandate' AND mandatsart='constituency'
             GROUP BY 1 ORDER BY 1;"""):
        marke = "OK" if ohne == "0" else "<-- PRUEFEN"
        log.info("   %-24s %s Direktgewaehlte, davon %s ohne Wahlkreis  %s",
                 leg, n, ohne, marke)

    log.info("--- Mandatsart, nach Herkunft ---")
    for r in query(f"""
            SELECT parliament_period_label,
                   count(*) FILTER (WHERE mandatsart_herkunft='geliefert'),
                   count(*) FILTER (WHERE mandatsart_herkunft='amtlich_ergaenzt'),
                   count(*) FILTER (WHERE mandatsart IS NULL)
              FROM {AW}.candidacy_mandate WHERE type='mandate'
             GROUP BY 1 ORDER BY 1;"""):
        log.info("   %-24s %s geliefert, %s amtlich ergaenzt, %s ohne", *r)

    log.info("--- Wer bleibt ohne Wahlkreis? ---")
    for art, n in query(f"""
            SELECT coalesce(mandatsart,'(ohne Angabe)'), count(*)
              FROM {AW}.candidacy_mandate
             WHERE type='mandate' AND wkr_nr IS NULL
             GROUP BY 1 ORDER BY 2 DESC;"""):
        log.info("   %-18s %s", art, n)

    log.info("--- Alle Korrekturen, wie sie jetzt in der Tabelle stehen ---")
    for r in query(f"""
            SELECT m.aw_id, m.politician_label, m.parliament_period_label,
                   coalesce(m.wkr_nr::text,'NULL'), m.wkr_herkunft,
                   coalesce(m.wkr_nr_amtlich::text,'-')
              FROM {AW}.candidacy_mandate m
              JOIN {AW}.korrektur_wahlkreis k ON k.aw_id = m.aw_id
             ORDER BY m.politician_label;"""):
        log.info("   %s %-20s %-24s wkr_nr=%-6s %-12s (XML sagte %s)", *r)


if __name__ == "__main__":
    main()
