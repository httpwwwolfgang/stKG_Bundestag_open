import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql_file, query

AW = "politiker_innen"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("sidejob-ergaenzungen")


KATEGORIEN = {
    29228: "Funktionen in Unternehmen",
    29229: "Funktionen in Koerperschaften und Anstalten des oeffentlichen Rechts",
    29230: "Funktionen in Vereinen, Verbaenden und Stiftungen",
    29231: "Beteiligung an Kapital- oder Personengesellschaften",
    29232: "Spenden/Zuwendungen fuer politische Taetigkeit",
    29233: "Vereinbarungen ueber kuenftige Taetigkeiten oder Vermoegensvorteile",
    29234: "Berufliche Taetigkeit vor der Mitgliedschaft im Deutschen Bundestag",
    29647: "Entgeltliche Taetigkeiten neben dem Mandat",
}


KEINE_TAETIGKEIT = (29231, 29232, 29233, 29234)


def _kategorie_werte():
    return ",\n           ".join(
        f"({k}, '{v}')" for k, v in sorted(KATEGORIEN.items())
    )


DDL = f"""
SET client_min_messages TO WARNING;

DROP TABLE IF EXISTS {AW}.sidejob_thema;

CREATE TABLE {AW}.sidejob_thema AS
SELECT (r.data->>'id')::int    AS sidejob_id,
       (t->>'id')::int         AS thema_id,
       t->>'label'             AS thema,
       min(ord)::smallint      AS lfd
  FROM {AW}.raw_sidejobs r,
       jsonb_array_elements(
           CASE WHEN jsonb_typeof(r.data->'field_topics') = 'array'
                THEN r.data->'field_topics' ELSE '[]'::jsonb END
       ) WITH ORDINALITY AS x(t, ord)
 GROUP BY 1, 2, 3;

ALTER TABLE {AW}.sidejob_thema ADD PRIMARY KEY (sidejob_id, thema_id);
CREATE INDEX ON {AW}.sidejob_thema (thema_id);

COMMENT ON TABLE {AW}.sidejob_thema IS
 'Kante Nebentaetigkeit -> Sachgebiet, n:m. Loest raw_sidejobs.data->field_topics '
 'auf, das der Clean-Layer gar nicht abgebildet hat. Das Sachgebiet der '
 'TAETIGKEIT, nicht das der Organisation - dafuer gibt es organisation_thema. '
 'Taxonomie ist abgeordnetenwatchs an DIP21 angelehnte Themenliste (raw_topics), '
 'keine amtliche Systematik. Siehe .';
COMMENT ON COLUMN {AW}.sidejob_thema.lfd IS
 'Position in der gelieferten Liste. Reihenfolge stammt vom Herausgeber und hat '
 'keine inhaltliche Bedeutung.';

ALTER TABLE {AW}.sidejob
    ADD COLUMN IF NOT EXISTS kategorie_id           int,
    ADD COLUMN IF NOT EXISTS kategorie              text,
    ADD COLUMN IF NOT EXISTS ist_taetigkeit         boolean,
    ADD COLUMN IF NOT EXISTS job_title_extra        text,
    ADD COLUMN IF NOT EXISTS additional_information text,
    ADD COLUMN IF NOT EXISTS data_change_date       date;

WITH vok(id, bezeichnung) AS (
    VALUES {_kategorie_werte()}
)
UPDATE {AW}.sidejob s
   SET kategorie_id           = (r.data->>'category')::int,
       kategorie              = vok.bezeichnung,
       ist_taetigkeit         = (r.data->>'category')::int
                                NOT IN {KEINE_TAETIGKEIT},
       job_title_extra        = nullif(r.data->>'job_title_extra', ''),
       additional_information = nullif(r.data->>'additional_information', ''),
       data_change_date       = nullif(r.data->>'data_change_date', '')::date
  FROM {AW}.raw_sidejobs r
  LEFT JOIN vok ON vok.id = (r.data->>'category')::int
 WHERE (r.data->>'id')::int = s.aw_id;

CREATE INDEX IF NOT EXISTS sidejob_kategorie_idx ON {AW}.sidejob (kategorie_id);

COMMENT ON COLUMN {AW}.sidejob.kategorie_id IS
 'Kennziffer der Anzeigekategorie nach den Verhaltensregeln des Bundestages. '
 'Acht Werte, 29228 bis 29234 und 29647. Das Vokabular steht NICHT in den '
 'Daten, sondern nur in der API-Dokumentation '
 '(abgeordnetenwatch.de/api/entitaeten/sidejob, abgerufen 27.08.2026) und ist '
 'in load_sidejob_ergaenzungen.py als Konstante hinterlegt.';
COMMENT ON COLUMN {AW}.sidejob.kategorie IS
 'Klartext zu kategorie_id, aus derselben Dokumentation. Umlaute sind '
 'transliteriert (ae/oe/ue), damit die Werte ueber psql ladbar bleiben.';
COMMENT ON COLUMN {AW}.sidejob.ist_taetigkeit IS
 'FALSE fuer die vier Kategorien, die keine Taetigkeit bezeichnen: '
 'Beteiligungen an Gesellschaften (29231), Spenden (29232), Vereinbarungen '
 'ueber kuenftige Taetigkeiten (29233) und Berufe VOR der Mitgliedschaft '
 '(29234). Zusammen 966 der 16.189 Zeilen. Wer Nebentaetigkeiten zaehlt, '
 'filtert darauf - sonst zaehlt er Aktienpakete und frueheres Berufsleben mit.';
COMMENT ON COLUMN {AW}.sidejob.data_change_date IS
 'Wann abgeordnetenwatch den Datensatz zuletzt geaendert hat - NICHT wann die '
 'Taetigkeit stattfand oder angezeigt wurde.';
COMMENT ON COLUMN {AW}.sidejob.income_level IS
 'Stufe der Bundestagsverwaltung, KEIN Betrag. 0 = 1 bis 1.000 EUR, '
 '1 = 1.000 bis 3.500, 2 = 3.500 bis 7.000, 3 = 7.000 bis 15.000, '
 '4 = 15.000 bis 30.000, 5 = 30.000 bis 50.000, 6 = 50.000 bis 75.000, '
 '7 = 75.000 bis 100.000, 8 = 100.000 bis 150.000, 9 = 150.000 bis 250.000, '
 '10 = ab 250.000. Im Bestand kommt 0 nicht vor; bei 8.668 von 16.189 fehlt '
 'die Angabe ganz. Summen lassen sich daraus nicht bilden.';
COMMENT ON COLUMN {AW}.sidejob.job_interval IS
 '0 = einmalig, 1 = monatlich, 2 = jaehrlich. Nur bei 689 von 16.189 gefuellt.';
"""


def main():
    with tempfile.NamedTemporaryFile("w", suffix=".sql", encoding="utf-8",
                                     delete=False) as f:
        f.write(DDL)
        pfad = Path(f.name)
    try:
        run_sql_file(pfad, "sidejob-ergaenzungen")
    finally:
        pfad.unlink(missing_ok=True)

    log.info("--- 1 · Sachgebiete der Taetigkeit (sidejob_thema) ---")
    for kanten, sj, themen in query(f"""
            SELECT count(*)::text, count(DISTINCT sidejob_id)::text,
                   count(DISTINCT thema_id)::text FROM {AW}.sidejob_thema;"""):
        log.info("   %s Kanten, %s Nebentaetigkeiten, %s verschiedene Themen",
                 kanten, sj, themen)
    for ohne, in query(f"""
            SELECT count(*)::text FROM {AW}.sidejob s
             WHERE NOT EXISTS (SELECT 1 FROM {AW}.sidejob_thema t
                                WHERE t.sidejob_id = s.aw_id);"""):
        log.info("   %s Nebentaetigkeiten ohne jedes Sachgebiet", ohne)
    for thema, n in query(f"""
            SELECT thema, count(*)::text FROM {AW}.sidejob_thema
             GROUP BY 1 ORDER BY count(*) DESC LIMIT 8;"""):
        log.info("   %-46s %s", thema[:45], n)

    log.info("--- 2 · Anzeigekategorie nach den Verhaltensregeln ---")
    for kid, kat, taet, n in query(f"""
            SELECT kategorie_id::text, kategorie, ist_taetigkeit::text,
                   count(*)::text FROM {AW}.sidejob
             GROUP BY 1, 2, 3 ORDER BY count(*) DESC;"""):

        mark = "" if taet == "true" else "   <-- keine Taetigkeit"
        log.info("   %s  %-62s %6s%s", kid, kat[:61], n, mark)
    for taet, nicht in query(f"""
            SELECT count(*) FILTER (WHERE ist_taetigkeit)::text,
                   count(*) FILTER (WHERE NOT ist_taetigkeit)::text
              FROM {AW}.sidejob;"""):
        log.info("   Taetigkeiten: %s, keine Taetigkeit: %s", taet, nicht)

    log.info("--- 3 · Wo sitzen die Steuerberater-Mandanten? ---")
    for kat, n in query(f"""
            SELECT kategorie, count(*)::text FROM {AW}.sidejob
             WHERE label ILIKE '%Mandant%' GROUP BY 1 ORDER BY count(*) DESC;"""):
        log.info("   %-62s %s", kat[:61], n)

    log.info("--- 4 · Die drei nachgezogenen Freitextfelder ---")
    for a, b, c in query(f"""
            SELECT count(job_title_extra)::text,
                   count(additional_information)::text,
                   count(data_change_date)::text FROM {AW}.sidejob;"""):
        log.info("   job_title_extra %s, additional_information %s, " "data_change_date %s", a, b, c)

    log.info("--- 5 · Gegenprobe: nichts unbekannt geblieben ---")
    for offen, in query(f"""
            SELECT count(*)::text FROM {AW}.sidejob WHERE kategorie IS NULL;"""):
        log.info("   Zeilen ohne aufgeloeste Kategorie: %s (erwartet 0)", offen)


if __name__ == "__main__":
    main()
