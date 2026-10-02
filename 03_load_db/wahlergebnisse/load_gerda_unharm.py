import csv
import sys
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

DB_SCHEMA   = "gerda"
META_SCHEMA = "meta"
T_EINHEIT   = "gemeinde_gerda_unharm"
T_ERG       = "gemeinde_gerda_unharm_ergebnis"

DATEI = (Path(__file__).resolve().parents[4] / "Daten" / "wahlergebnisse"
         / "GERDA" / "federal_muni_unharm.txt")

JAHRE = (2013, 2017, 2021)


KOPFSPALTEN = 28

BERECHNET = ("cdu_csu", "far_right", "far_left", "far_left_w_linke",
             "flag_naive_turnout_above_1")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gerda-unharm")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {META_SCHEMA};
CREATE TABLE IF NOT EXISTS {META_SCHEMA}.datenlieferung (
    lieferung_id TEXT PRIMARY KEY,
    bezeichnung  TEXT NOT NULL,
    herausgeber  TEXT NOT NULL,
    datei        TEXT,
    gebietsstand DATE,
    lizenz       TEXT,
    wahljahr     SMALLINT
);
ALTER TABLE {META_SCHEMA}.datenlieferung
    ADD COLUMN IF NOT EXISTS art   TEXT NOT NULL DEFAULT 'amtlich',
    ADD COLUMN IF NOT EXISTS basis TEXT[];

DROP TABLE IF EXISTS {DB_SCHEMA}.{T_ERG}     CASCADE;
DROP TABLE IF EXISTS {DB_SCHEMA}.{T_EINHEIT} CASCADE;

CREATE TABLE {DB_SCHEMA}.{T_EINHEIT} (
    wahljahr              SMALLINT NOT NULL,
    ags                   CHAR(8)  NOT NULL,
    gemeindename          TEXT,



    kreis                 TEXT,
    land                  CHAR(2),


    wahlberechtigte_orig  INTEGER,
    wahlberechtigte       INTEGER,
    waehlende_orig        INTEGER,
    waehlende             INTEGER,
    gueltige              INTEGER,
    ungueltige            INTEGER,
    wb_ohne_sperrvermerk  INTEGER,
    wb_mit_sperrvermerk   INTEGER,
    wb_par25              INTEGER,
    waehlende_wahlschein  INTEGER,


    unique_mailin         SMALLINT,
    unique_multi_mailin   SMALLINT,
    einwohner             INTEGER,
    flaeche               DOUBLE PRECISION,

    pop_weight            DOUBLE PRECISION,
    area_weight           DOUBLE PRECISION,
    voters_weight         DOUBLE PRECISION,
    blocked_weight        DOUBLE PRECISION,
    turnout               DOUBLE PRECISION,
    turnout_ohne_briefwahl DOUBLE PRECISION,

    cdu_csu               DOUBLE PRECISION,
    far_right             DOUBLE PRECISION,
    far_left              DOUBLE PRECISION,
    far_left_w_linke      DOUBLE PRECISION,
    flag_turnout_ueber_1  SMALLINT,
    lieferung_id          TEXT,
    PRIMARY KEY (wahljahr, ags),
    FOREIGN KEY (lieferung_id)
        REFERENCES {META_SCHEMA}.datenlieferung (lieferung_id)
);
CREATE INDEX {T_EINHEIT}_ags ON {DB_SCHEMA}.{T_EINHEIT} (ags);

CREATE TABLE {DB_SCHEMA}.{T_ERG} (
    wahljahr SMALLINT NOT NULL,
    ags      CHAR(8)  NOT NULL,
    partei   TEXT     NOT NULL,

    anteil   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (wahljahr, ags, partei),
    FOREIGN KEY (wahljahr, ags)
        REFERENCES {DB_SCHEMA}.{T_EINHEIT} (wahljahr, ags) ON DELETE CASCADE
);
CREATE INDEX {T_ERG}_partei ON {DB_SCHEMA}.{T_ERG} (wahljahr, partei);
"""


def merke_lieferung():
    run_sql(f"""
    INSERT INTO {META_SCHEMA}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, datei, lizenz, art)
    VALUES ('gerda_federal_muni_unharm',
            'GERDA federal_muni_unharm, Gemeindeebene mit verteilter Briefwahl',
            'Heddesheimer, Hilbig, Sichart & Wiedemann (2025), doi:10.1038/s41597-025-04811-5',
            '{DATEI.name}', 'CC-BY-4.0', 'amtlich')
    ON CONFLICT (lieferung_id) DO UPDATE SET bezeichnung = EXCLUDED.bezeichnung;
    """, "lieferung gerda_unharm")


def staging():
    if not DATEI.exists():
        raise SystemExit(f"Datei fehlt: {DATEI}")

    with DATEI.open(encoding="utf-8", newline="") as fh:
        kopf = next(csv.reader(fh))
    log.info("%d Spalten in %s", len(kopf), DATEI.name)

    tmp_csv = Path(tempfile.gettempdir()) / "gerda_unharm.csv"
    zeilen = 0
    with DATEI.open(encoding="utf-8", newline="") as fh, \
         tmp_csv.open("w", encoding="utf-8", newline="") as out:
        leser, schreiber = csv.reader(fh), csv.writer(out)
        schreiber.writerow(next(leser))
        for z in leser:
            if z and z[1].isdigit() and int(z[1]) in JAHRE:
                schreiber.writerow(z)
                zeilen += 1
    log.info("%d Zeilen fuer %s aufbereitet", zeilen, ", ".join(map(str, JAHRE)))

    tab = f"{DB_SCHEMA}.stg_gerda_unharm"
    namen = [f"c{i:03d}" for i in range(len(kopf))]
    sql = Path(tempfile.gettempdir()) / "gerda_unharm.sql"
    sql.write_text(
        f"DROP TABLE IF EXISTS {tab};\n"
        f"CREATE TABLE {tab} (\n    "
        + ",\n    ".join(f"{n} TEXT" for n in namen) + "\n);\n"
        f"\\copy {tab} FROM '{tmp_csv.as_posix()}' "
        f"WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');\n",
        encoding="utf-8")
    run_sql_file(sql, label="staging gerda_unharm")
    sql.unlink(missing_ok=True)
    tmp_csv.unlink(missing_ok=True)
    return tab, kopf, namen


def zahl(spalte, typ="int"):
    if typ == "int":
        return f"(CASE WHEN {spalte} ~ '^-?[0-9]+$' THEN {spalte}::int END)"
    return (f"(CASE WHEN {spalte} ~ '^-?[0-9]+([.][0-9]+)?([eE]-?[0-9]+)?$' "
            f"THEN {spalte}::double precision END)")


def verteile(tab, kopf, namen):
    idx = {n: namen[i] for i, n in enumerate(kopf)}
    i = lambda n: zahl(idx[n], "int")
    d = lambda n: zahl(idx[n], "float")

    run_sql(f"""
    INSERT INTO {DB_SCHEMA}.{T_EINHEIT}
        (wahljahr, ags, gemeindename, kreis, land,
         wahlberechtigte_orig, wahlberechtigte, waehlende_orig, waehlende,
         gueltige, ungueltige, wb_ohne_sperrvermerk, wb_mit_sperrvermerk,
         wb_par25, waehlende_wahlschein, unique_mailin, unique_multi_mailin,
         einwohner, flaeche, pop_weight, area_weight, voters_weight,
         blocked_weight, turnout, turnout_ohne_briefwahl,
         cdu_csu, far_right, far_left, far_left_w_linke, flag_turnout_ueber_1,
         lieferung_id)
    SELECT {idx['election_year']}::int, {idx['ags']}, {idx['ags_name']},
           {idx['county']}, {idx['state']},
           {i('eligible_voters_orig')}, {i('eligible_voters')},
           {i('number_voters_orig')}, {i('number_voters')},
           {i('valid_votes')}, {i('invalid_votes')},
           {i('voters_wo_blockingnotice')}, {i('voters_blockingnotice')},
           {i('voters_par25_2')}, {i('voters_w_ballot')},
           {i('unique_mailin')}, {i('unique_multi_mailin')},
           {i('pop')}, {d('area')},
           {d('pop_weight')}, {d('area_weight')}, {d('voters_weight')},
           {d('blocked_weight')}, {d('turnout')}, {d('turnout_wo_mailin')},
           {d('cdu_csu')}, {d('far_right')}, {d('far_left')},
           {d('far_left_w_linke')}, {i('flag_naive_turnout_above_1')},
           'gerda_federal_muni_unharm'
    FROM {tab}
    WHERE {idx['ags']} ~ '^[0-9]{{8}}$'
    ON CONFLICT DO NOTHING;
    """, "einheiten gerda_unharm")

    parteien = [n for n in kopf[KOPFSPALTEN:] if n not in BERECHNET]
    log.info("%d Parteispalten", len(parteien))
    teile = [
        f"SELECT {idx['election_year']}::int, {idx['ags']}, '{p}', "
        f"{zahl(idx[p], 'float')}\nFROM {tab} "
        f"WHERE {idx['ags']} ~ '^[0-9]{{8}}$' AND {zahl(idx[p], 'float')} IS NOT NULL"
        for p in parteien]

    sql = Path(tempfile.gettempdir()) / "gerda_unharm_erg.sql"
    sql.write_text(
        "SET client_encoding TO 'UTF8';\n"
        f"INSERT INTO {DB_SCHEMA}.{T_ERG} (wahljahr, ags, partei, anteil)\n"
        + "\nUNION ALL\n".join(teile) + "\nON CONFLICT DO NOTHING;\n",
        encoding="utf-8")
    run_sql_file(sql, label="ergebnisse gerda_unharm")
    sql.unlink(missing_ok=True)
    run_sql(f"DROP TABLE IF EXISTS {tab};", "staging weg")


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, T_EINHEIT)
    log.info("%-6s %10s %14s %14s", "Jahr", "Gemeinden", "Wahlberecht.", "Waehlende")
    for zeile in query(f"""
        SELECT wahljahr, count(*),
               to_char(sum(wahlberechtigte_orig), 'FM999G999G999'),
               to_char(sum(waehlende), 'FM999G999G999')
        FROM {DB_SCHEMA}.{T_EINHEIT} GROUP BY 1 ORDER BY 1;
    """):
        log.info("%-6s %10s %14s %14s", *zeile)

    log.info("--- Vergleich der beiden Gemeindeebenen ---")
    for zeile in query(f"""
        SELECT a.wahljahr, a.einheiten AS amtlich, g.gemeinden AS gerda,
               g.gemeinden - a.einheiten AS mehr_bei_gerda
        FROM (SELECT wahljahr, count(*) AS einheiten
              FROM wahlergebnisse.kleinst_100_amtlich GROUP BY 1) a
        JOIN (SELECT wahljahr, count(*) AS gemeinden
              FROM {DB_SCHEMA}.{T_EINHEIT} GROUP BY 1) g USING (wahljahr)
        ORDER BY 1;
    """):
        log.info("  %s: amtliche Ebene %s Einheiten, GERDA %s Gemeinden " "(%s mehr, weil die Briefwahl verteilt ist)", *zeile)

    log.info("--- Gegenprobe: Zweitstimmen aus Anteil x Waehlende ---")
    for zeile in query(f"""
        SELECT e.wahljahr,
               to_char(round(sum(r.anteil * e.waehlende)), 'FM999G999G999') AS zurueck,
               to_char(w.summe, 'FM999G999G999')                            AS wahlkreisebene,
               to_char(round(sum(r.anteil * e.waehlende)) - w.summe,
                       'FM999G999G999')                                     AS differenz
        FROM {DB_SCHEMA}.{T_ERG} r
        JOIN {DB_SCHEMA}.{T_EINHEIT} e USING (wahljahr, ags)
        JOIN (SELECT wahljahr, sum(stimmen) AS summe
              FROM {DB_SCHEMA}.wahlergebnis_gerda_wahlkreis
              WHERE stimme = 'zweitstimme' GROUP BY 1) w USING (wahljahr)
        GROUP BY e.wahljahr, w.summe ORDER BY 1;
    """):
        log.info("  %s: zurueckgerechnet %s, Wahlkreisebene %s, Differenz %s",
                 *zeile)

    log.info("--- unique_mailin: 2013 gegen 2017 (erwartet: identisch, Bug B2) ---")
    for zeile in query(f"""
        SELECT count(*) AS gemeinden,
               count(*) FILTER (WHERE a.unique_mailin = b.unique_mailin) AS gleich,
               round(100.0 * count(*) FILTER (WHERE a.unique_mailin = b.unique_mailin)
                     / nullif(count(*), 0), 1) AS prozent
        FROM {DB_SCHEMA}.{T_EINHEIT} a
        JOIN {DB_SCHEMA}.{T_EINHEIT} b ON b.ags = a.ags
        WHERE a.wahljahr = 2013 AND b.wahljahr = 2017;
    """):
        log.info("  2013/2017: %s Gemeinden, %s gleich (%s %%)", *zeile)
    for zeile in query(f"""
        SELECT count(*) AS gemeinden,
               count(*) FILTER (WHERE a.unique_mailin = b.unique_mailin) AS gleich,
               round(100.0 * count(*) FILTER (WHERE a.unique_mailin = b.unique_mailin)
                     / nullif(count(*), 0), 1) AS prozent
        FROM {DB_SCHEMA}.{T_EINHEIT} a
        JOIN {DB_SCHEMA}.{T_EINHEIT} b ON b.ags = a.ags
        WHERE a.wahljahr = 2017 AND b.wahljahr = 2021;
    """):
        log.info("  2017/2021: %s Gemeinden, %s gleich (%s %%)", *zeile)


def main():
    run_sql(DDL, "ddl")
    merke_lieferung()
    tab, kopf, namen = staging()
    verteile(tab, kopf, namen)
    report()


if __name__ == "__main__":
    main()
