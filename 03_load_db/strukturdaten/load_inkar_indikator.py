import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query


LIEFERUNG = "bbsr_inkar_2024"

DB_SCHEMA  = "strukturdaten"
ROH_SCHEMA = "strukturdaten_roh"
AUSGABE    = "inkar_2024"


KONFLIKT = {
    "12073532": "nimmt am 19.04.2022 Berkholz-Meyenburg, Mark Landin und " "Passow auf (+3.663 Einwohner, +108,55 qkm)",
    "09273137": "nimmt am 01.01.2022 den gemeindefreien Hienheimer Forst auf " "(+0 Einwohner, +23,55 qkm)",
    "14523170": "tauscht am 02.09.2022 mit Hirschfeld 14524110 je 0,07 qkm " "(Teilausgliederung in beide Richtungen, 0 Einwohner)",
    "14524110": "tauscht am 02.09.2022 mit Lengenfeld 14523170 je 0,07 qkm " "(Teilausgliederung in beide Richtungen, 0 Einwohner)",
    "07140064": "gibt am 21.11.2022 Flaeche an Roth 07140131 ab " "(Teilausgliederung, 0 Einwohner)",
    "07140131": "nimmt am 21.11.2022 Flaeche von Kastellaun 07140064 auf " "(Teilausgliederung, 0 Einwohner)",
}


AUFGELOEST = ("12073032", "12073386", "12073603")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inkar-indikator")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.indikator (
    indikator_id SMALLINT PRIMARY KEY,
    bereich      TEXT NOT NULL,
    indikator    TEXT NOT NULL,
    UNIQUE (bereich, indikator)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.gemeinde_indikator (
    ags          CHAR(8)  NOT NULL,
    indikator_id SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.indikator,
    jahr         SMALLINT NOT NULL,
    wert         DOUBLE PRECISION,

    ausgabe      SMALLINT NOT NULL,
    PRIMARY KEY (ags, indikator_id, jahr)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.kreis_indikator (
    kreis        CHAR(5)  NOT NULL,
    indikator_id SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.indikator,
    jahr         SMALLINT NOT NULL,
    wert         DOUBLE PRECISION,
    ausgabe      SMALLINT NOT NULL,
    PRIMARY KEY (kreis, indikator_id, jahr)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.gebietskonflikt (
    ags     CHAR(8) PRIMARY KEY,
    ausgabe SMALLINT NOT NULL,
    grund   TEXT NOT NULL
);

COMMENT ON TABLE {DB_SCHEMA}.gemeinde_indikator IS
  'INKAR-Indikatoren je Gemeinde, Ausgabe 2024, Gebietsstand 31.12.2022. '
  'Zeitreihenbereinigt: auch alte Jahrgaenge stehen im Zuschnitt von 2022. '
  'Indikatorname ueber indikator_id, Gebietskonflikte in eigener Tabelle.';
COMMENT ON TABLE {DB_SCHEMA}.gebietskonflikt IS
  'Gemeinden, deren INKAR-Gebiet groesser ist als der GERDA-Zuschnitt vom '
  '31.12.2021. Ihre Werte sind in gemeinde_indikator durchgehend NULL - der '
  'Wert existiert, gilt aber fuer ein anderes Gebiet als die Wahlergebnisse.';
COMMENT ON COLUMN {DB_SCHEMA}.gemeinde_indikator.wert IS
  'NULL heisst entweder: die Quelle fuehrt keinen Wert, oder der Schluessel '
  'steht in gebietskonflikt. Nie 0 als Ersatz.';
"""


INDIZES = f"""
CREATE INDEX IF NOT EXISTS gemeinde_indikator_such
    ON {DB_SCHEMA}.gemeinde_indikator (indikator_id, jahr);
CREATE INDEX IF NOT EXISTS kreis_indikator_such
    ON {DB_SCHEMA}.kreis_indikator (indikator_id, jahr);
"""


def _lit(text):
    return "'" + text.replace("'", "''") + "'"


def sql_stamm():
    werte = ", ".join(f"({_lit(k)}, {AUSGABE[-4:]}, {_lit(v)})"
                      for k, v in KONFLIKT.items())
    return f"""
TRUNCATE {DB_SCHEMA}.gemeinde_indikator, {DB_SCHEMA}.kreis_indikator,
         {DB_SCHEMA}.gebietskonflikt, {DB_SCHEMA}.indikator CASCADE;

INSERT INTO {DB_SCHEMA}.indikator (indikator_id, bereich, indikator)
SELECT row_number() OVER (ORDER BY bereich, indikator)::smallint,
       bereich, indikator
FROM (SELECT DISTINCT bereich, indikator
      FROM {ROH_SCHEMA}.inkar
      WHERE ausgabe = '{AUSGABE}'
        AND raumbezug IN ('Gemeinden', 'Kreise')) d;

INSERT INTO {DB_SCHEMA}.gebietskonflikt (ags, ausgabe, grund)
VALUES {werte};
"""


def sql_flaeche(ebene, tabelle, spalte, stellen, konflikt):
    if stellen == 5:

        schluessel = ("CASE WHEN length(r.kennziffer) > 5 " "THEN left(lpad(r.kennziffer, 8, '0'), 5) " "ELSE lpad(r.kennziffer, 5, '0') END::CHAR(5)")
    else:
        schluessel = "lpad(r.kennziffer, 8, '0')::CHAR(8)"

    wert = "nullif(replace(r.wert, ',', '.'), '')::double precision"
    if konflikt:
        wert = (f"CASE WHEN EXISTS (SELECT 1 FROM {DB_SCHEMA}.gebietskonflikt k "
                f"WHERE k.ags = lpad(r.kennziffer, 8, '0')) THEN NULL "
                f"ELSE {wert} END")
    return f"""
INSERT INTO {DB_SCHEMA}.{tabelle} ({spalte}, indikator_id, jahr, wert, ausgabe)
SELECT {schluessel}, i.indikator_id, r.zeitbezug::smallint, {wert},
       {AUSGABE[-4:]}::smallint
FROM {ROH_SCHEMA}.inkar r
JOIN {DB_SCHEMA}.indikator i
  ON i.bereich = r.bereich AND i.indikator = r.indikator
WHERE r.ausgabe = '{AUSGABE}'
  AND r.raumbezug = '{ebene}'
  AND r.zeitbezug ~ '^[0-9]{{4}}$';
"""


def report():
    log.info("--- %s.indikator ---", DB_SCHEMA)
    for z in query(f"""SELECT count(*)::text, count(DISTINCT bereich)::text
                       FROM {DB_SCHEMA}.indikator;"""):
        log.info("  %s Indikatoren in %s Bereichen", *z)

    for tab, schluessel in (("gemeinde_indikator", "ags"),
                            ("kreis_indikator", "kreis")):
        log.info("--- %s.%s ---", DB_SCHEMA, tab)
        for z in query(f"""
            SELECT count(*)::text, count(DISTINCT {schluessel})::text,
                   count(DISTINCT indikator_id)::text,
                   min(jahr)::text || '-' || max(jahr)::text,
                   count(*) FILTER (WHERE wert IS NULL)::text,
                   pg_size_pretty(pg_total_relation_size('{DB_SCHEMA}.{tab}'))
            FROM {DB_SCHEMA}.{tab};
        """):
            log.info("  %s Zeilen, %s Einheiten, %s Indikatoren, %s, " "%s ohne Wert, %s auf der Platte", *z)
        log.info("  Zeitreihe je Bereich:")
        for z in query(f"""
            SELECT i.bereich, count(DISTINCT t.indikator_id)::text,
                   min(t.jahr)::text || '-' || max(t.jahr)::text,
                   count(*)::text
            FROM {DB_SCHEMA}.{tab} t
            JOIN {DB_SCHEMA}.indikator i USING (indikator_id)
            GROUP BY 1 ORDER BY 1;
        """):
            log.info("    %-40s %4s Indikatoren, %-12s %10s Werte", *z)


    log.info("--- Verworfene Zeitangaben (kein reines Jahr) ---")
    for z in query(f"""
        SELECT raumbezug, count(*)::text,
               string_agg(DISTINCT zeitbezug, ', ' ORDER BY zeitbezug) AS formen
        FROM {ROH_SCHEMA}.inkar
        WHERE ausgabe = '{AUSGABE}' AND raumbezug IN ('Gemeinden','Kreise')
          AND zeitbezug !~ '^[0-9]{{4}}$'
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %-12s %8s Zeilen: %s", z[0], z[1], z[2][:90])
    if not query(f"""SELECT 1 FROM {ROH_SCHEMA}.inkar
                     WHERE ausgabe='{AUSGABE}' AND raumbezug IN ('Gemeinden','Kreise')
                       AND zeitbezug !~ '^[0-9]{{4}}$' LIMIT 1;"""):
        log.info("  keine - jede Zeitangabe ist eine reine Jahreszahl")

    log.info("--- Gebietskonflikte ---")
    for z in query(f"""
        SELECT k.ags, k.grund,
               (SELECT count(*)::text FROM {DB_SCHEMA}.gemeinde_indikator g
                WHERE g.ags = k.ags),
               (SELECT count(*)::text FROM {DB_SCHEMA}.gemeinde_indikator g
                WHERE g.ags = k.ags AND g.wert IS NOT NULL)
        FROM {DB_SCHEMA}.gebietskonflikt k ORDER BY 1;
    """):
        marke = "" if z[3] == "0" else f"  PRUEFEN: {z[3]} Zeilen tragen noch einen Wert"
        log.info("  %s %s", z[0], z[1])
        log.info("      %s Zeilen, alle ohne Wert%s", z[2], marke)


    log.info("--- Gegenprobe gegen gerda.gemeinde_gerda_harm21 ---")
    for z in query(f"""
        SELECT
          (SELECT count(DISTINCT ags)::text FROM gerda.gemeinde_gerda_harm21),
          (SELECT count(DISTINCT ags)::text FROM {DB_SCHEMA}.gemeinde_indikator),
          (SELECT count(*)::text FROM (
             SELECT DISTINCT ags FROM gerda.gemeinde_gerda_harm21) g
           WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeinde_indikator i
                             WHERE i.ags = g.ags)),
          (SELECT count(*)::text FROM (
             SELECT DISTINCT ags FROM {DB_SCHEMA}.gemeinde_indikator) i
           WHERE NOT EXISTS (SELECT 1 FROM gerda.gemeinde_gerda_harm21 g
                             WHERE g.ags = i.ags));
    """):
        log.info("  GERDA %s Gemeinden, INKAR %s Gemeinden", z[0], z[1])
        log.info("  nur in GERDA (ohne Strukturdaten): %s", z[2])
        log.info("  nur in INKAR (ohne Wahlergebnis):  %s", z[3])

    log.info("  die aufgeloesten Gemeinden im Einzelnen:")
    for a in AUFGELOEST:
        z = query(f"""
            SELECT (SELECT count(*)::text FROM {DB_SCHEMA}.gemeinde_indikator
                    WHERE ags = '{a}'),
                   (SELECT max(gemeindename) FROM gerda.gemeinde_gerda_harm21
                    WHERE ags = '{a}'),
                   (SELECT max(name_neu) FROM raum.gebietsuebergang
                    WHERE ebene='Gemeinde' AND ags_alt = '{a}'
                      AND wirksam > DATE '2021-12-31');
        """)[0]
        log.info("    %s %-22s %s INKAR-Zeilen, aufgegangen in %s",
                 a, (z[1] or "")[:22], z[0], z[2] or "?")


def main():
    global AUSGABE
    if "--ausgabe" in sys.argv:
        AUSGABE = sys.argv[sys.argv.index("--ausgabe") + 1]

    if "--neu" in sys.argv[1:]:
        for t in ("gemeinde_indikator", "kreis_indikator"):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;", f"{t} verwerfen")
        log.warning("Tabellen verworfen.")

    if not query(f"""SELECT 1 FROM {ROH_SCHEMA}.inkar
                     WHERE ausgabe = '{AUSGABE}' LIMIT 1;"""):
        raise SystemExit(f"{ROH_SCHEMA}.inkar hat nichts fuer {AUSGABE} - "
                         f"erst load_inkar_roh.py {AUSGABE}")

    run_sql(DDL, "ddl")
    run_sql(sql_stamm(), "indikator + gebietskonflikt")
    run_sql(sql_flaeche("Gemeinden", "gemeinde_indikator", "ags", 8, True),
            "gemeinde_indikator")
    run_sql(sql_flaeche("Kreise", "kreis_indikator", "kreis", 5, False),
            "kreis_indikator")
    run_sql(INDIZES, "indizes")
    report()


if __name__ == "__main__":
    main()
