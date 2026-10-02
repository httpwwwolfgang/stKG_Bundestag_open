import sys
import csv
import logging
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

GERDA_SCHEMA = "gerda"
META_SCHEMA  = "meta"

DATEI = (Path(__file__).resolve().parents[4] / "Daten" / "wahlergebnisse"
         / "GERDA" / "federal_muni_harm_21.txt")

JAHRE_DREI  = (2013, 2017, 2021)
JAHRE_PANEL = (1990, 1994, 1998, 2002, 2005, 2009, 2013, 2017, 2021, 2025)


JAHRE     = JAHRE_DREI
DB_SCHEMA = GERDA_SCHEMA
T_EINHEIT = "gemeinde_gerda_harm21"
T_ERG     = "gemeinde_gerda_harm21_ergebnis"
T_STG     = "stg_gerda_harm21"


def waehle_betriebsart(panel):
    global JAHRE, DB_SCHEMA, T_EINHEIT, T_ERG, T_STG
    if not panel:
        return
    JAHRE     = JAHRE_PANEL
    DB_SCHEMA = "gerda_seit_1990"
    T_EINHEIT = "gemeinde_harm21"
    T_ERG     = "gemeinde_harm21_ergebnis"
    T_STG     = "stg_gemeinde_harm21"


KOPFSPALTEN = 26

NICHT_PARTEI = (
    "cdu_csu", "far_right", "far_left", "far_left_w_linke",
    "flag_naive_turnout_above_1", "flag_unsuccessful_naive_merge",
    "total_votes", "flag_total_votes_incongruent", "total_votes_incogruence",
    "perc_total_votes_incogruence",

    "area_cw", "pop_cw", "ags_21", "area", "population",
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gerda-harm21")


def ddl():
    return f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};
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
    wahljahr               SMALLINT NOT NULL,

    ags                    CHAR(8)  NOT NULL,
    wahltag                DATE,
    gemeindename           TEXT,
    kreis                  TEXT,
    land                   CHAR(2),
    unique_mailin          SMALLINT,
    unique_multi_mailin    SMALLINT,
    wahlberechtigte_orig   INTEGER,
    wahlberechtigte        INTEGER,
    waehlende_orig         INTEGER,
    waehlende              INTEGER,
    gueltige               INTEGER,
    ungueltige             INTEGER,
    wb_ohne_sperrvermerk   INTEGER,
    wb_mit_sperrvermerk    INTEGER,
    wb_par25               INTEGER,
    wb_gesperrt_orig       INTEGER,
    waehlende_wahlschein   INTEGER,
    pop_weight             DOUBLE PRECISION,
    area_weight            DOUBLE PRECISION,
    voters_weight          DOUBLE PRECISION,
    blocked_weight         DOUBLE PRECISION,
    turnout                DOUBLE PRECISION,
    turnout_ohne_briefwahl DOUBLE PRECISION,

    cdu_csu                DOUBLE PRECISION,
    far_right              DOUBLE PRECISION,
    far_left               DOUBLE PRECISION,
    far_left_w_linke       DOUBLE PRECISION,
    flag_turnout_ueber_1   SMALLINT,

    stimmen_summe          DOUBLE PRECISION,
    flag_stimmensumme_abweichend SMALLINT,
    stimmensumme_differenz DOUBLE PRECISION,
    stimmensumme_anteil    DOUBLE PRECISION,
    flaeche                DOUBLE PRECISION,
    einwohner              DOUBLE PRECISION,
    lieferung_id           TEXT,
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
        (lieferung_id, bezeichnung, herausgeber, datei, gebietsstand, lizenz, art)
    VALUES ('gerda_federal_muni_harm_21',
            'GERDA federal_muni_harm_21, Gemeindeebene auf Gebietsstand 2021',
            'Heddesheimer, Hilbig, Sichart & Wiedemann (2025), doi:10.1038/s41597-025-04811-5',
            '{DATEI.name}', DATE '2021-12-31', 'CC-BY-4.0', 'abgeleitet')
    ON CONFLICT (lieferung_id) DO UPDATE SET bezeichnung = EXCLUDED.bezeichnung;
    """, "lieferung gerda_harm21")


def staging():
    if not DATEI.exists():
        raise SystemExit(f"Datei fehlt: {DATEI}")

    with DATEI.open(encoding="utf-8", newline="") as fh:
        kopf = next(csv.reader(fh))
    log.info("%d Spalten in %s", len(kopf), DATEI.name)
    ix_jahr = kopf.index("election_year")

    tmp_csv = Path(tempfile.gettempdir()) / f"{T_STG}.csv"
    zeilen = 0
    with DATEI.open(encoding="utf-8", newline="") as fh, \
         tmp_csv.open("w", encoding="utf-8", newline="") as out:
        leser, schreiber = csv.reader(fh), csv.writer(out)
        schreiber.writerow(next(leser))
        for z in leser:
            if z and z[ix_jahr].isdigit() and int(z[ix_jahr]) in JAHRE:
                schreiber.writerow(z)
                zeilen += 1
    log.info("%d Zeilen fuer %s aufbereitet", zeilen, ", ".join(map(str, JAHRE)))

    tab   = f"{DB_SCHEMA}.{T_STG}"
    namen = [f"c{i:03d}" for i in range(len(kopf))]
    sql   = Path(tempfile.gettempdir()) / f"{T_STG}.sql"
    sql.write_text(
        f"DROP TABLE IF EXISTS {tab};\n"
        f"CREATE TABLE {tab} (\n    "
        + ",\n    ".join(f"{n} TEXT" for n in namen) + "\n);\n"
        f"\\copy {tab} FROM '{tmp_csv.as_posix()}' "
        f"WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');\n",
        encoding="utf-8")
    run_sql_file(sql, label=f"staging {T_STG}")
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
        (wahljahr, ags, wahltag, gemeindename, kreis, land,
         unique_mailin, unique_multi_mailin,
         wahlberechtigte_orig, wahlberechtigte, waehlende_orig, waehlende,
         gueltige, ungueltige, wb_ohne_sperrvermerk, wb_mit_sperrvermerk,
         wb_par25, wb_gesperrt_orig, waehlende_wahlschein,
         pop_weight, area_weight, voters_weight, blocked_weight,
         turnout, turnout_ohne_briefwahl,
         cdu_csu, far_right, far_left, far_left_w_linke,
         flag_turnout_ueber_1,
         stimmen_summe, flag_stimmensumme_abweichend,
         stimmensumme_differenz, stimmensumme_anteil,
         flaeche, einwohner, lieferung_id)
    SELECT {idx['election_year']}::int,
           lpad(trim({idx['ags']}), 8, '0'),
           to_date(nullif(trim({idx['election_date']}), ''), 'YYYY-MM-DD'),
           {idx['ags_name']}, {idx['county']}, {idx['state']},
           {i('unique_mailin')}, {i('unique_multi_mailin')},
           {i('eligible_voters_orig')}, {i('eligible_voters')},
           {i('number_voters_orig')}, {i('number_voters')},
           {i('valid_votes')}, {i('invalid_votes')},
           {i('voters_wo_blockingnotice')}, {i('voters_blockingnotice')},
           {i('voters_par25_2')}, {i('blocked_voters_orig')},
           {i('voters_w_ballot')},
           {d('pop_weight')}, {d('area_weight')}, {d('voters_weight')},
           {d('blocked_weight')}, {d('turnout')}, {d('turnout_wo_mailin')},
           {d('cdu_csu')}, {d('far_right')}, {d('far_left')},
           {d('far_left_w_linke')},
           {i('flag_naive_turnout_above_1')},
           {d('total_votes')}, {i('flag_total_votes_incongruent')},
           {d('total_votes_incogruence')}, {d('perc_total_votes_incogruence')},
           {d('area')}, {d('population')},
           'gerda_federal_muni_harm_21'
    FROM {tab}
    WHERE trim({idx['ags']}) ~ '^[0-9]{{7,8}}$'
    ON CONFLICT DO NOTHING;
    """, "einheiten gerda_harm21")

    parteien = [n for n in kopf[KOPFSPALTEN:] if n not in NICHT_PARTEI]
    log.info("%d Parteispalten", len(parteien))
    teile = [
        f"SELECT {idx['election_year']}::int, lpad(trim({idx['ags']}), 8, '0'), "
        f"'{p}', {zahl(idx[p], 'float')}\nFROM {tab} "
        f"WHERE trim({idx['ags']}) ~ '^[0-9]{{7,8}}$' "
        f"AND {zahl(idx[p], 'float')} IS NOT NULL"
        for p in parteien]

    sql = Path(tempfile.gettempdir()) / f"{T_ERG}.sql"
    sql.write_text(
        "SET client_encoding TO 'UTF8';\n"
        f"INSERT INTO {DB_SCHEMA}.{T_ERG} (wahljahr, ags, partei, anteil)\n"
        + "\nUNION ALL\n".join(teile) + "\nON CONFLICT DO NOTHING;\n",
        encoding="utf-8")
    run_sql_file(sql, label=f"ergebnisse {T_ERG}")
    sql.unlink(missing_ok=True)

    run_sql(f"DROP TABLE IF EXISTS {tab};", "staging weg")


def pruefe():
    log.info("--- %s.%s ---", DB_SCHEMA, T_EINHEIT)
    for zeile in query(f"""
        SELECT wahljahr, count(*),
               to_char(sum(wahlberechtigte_orig), 'FM999G999G999'),
               to_char(sum(gueltige), 'FM999G999G999')
        FROM {DB_SCHEMA}.{T_EINHEIT} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden, %s Wahlberechtigte, %s gueltige Stimmen", *zeile)

    log.info("--- Gemeinden ohne 2021er Zeile (Dreijahresbestand: 146) ---")
    for zeile in query(f"""
        WITH j AS (SELECT ags, array_agg(DISTINCT wahljahr) AS jahre
                   FROM {DB_SCHEMA}.{T_EINHEIT} GROUP BY 1)
        SELECT count(*) FROM j WHERE NOT 2021 = ANY(jahre);
    """):
        log.info("  %s Gemeinden ohne 2021er Zeile", zeile[0])

    if len(JAHRE) > 3:
        log.info("--- Wieviele Gemeinden stehen in ALLEN %d Wahlen? ---", len(JAHRE))
        for zeile in query(f"""
            WITH j AS (SELECT ags, count(DISTINCT wahljahr) AS n
                       FROM {DB_SCHEMA}.{T_EINHEIT} GROUP BY 1)
            SELECT count(*) FILTER (WHERE n = {len(JAHRE)}),
                   count(*),
                   round(100.0 * count(*) FILTER (WHERE n = {len(JAHRE)})
                         / count(*), 2)
            FROM j;
        """):
            log.info("  %s von %s Gemeinden in allen Wahlen (%s %%) - das ist die " "Schnittmenge fuer Zeitvergleiche", *zeile)

        log.info("--- Parteien je Wahljahr ---")
        for zeile in query(f"""
            SELECT wahljahr, count(DISTINCT partei)
            FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1 ORDER BY 1;
        """):
            log.info("  %s: %s Parteien", *zeile)

    log.info("--- 2021 gegen gemeinde_gerda_unharm (erwartet: identische Menge) ---")
    for zeile in query(f"""
        SELECT (SELECT count(*) FROM {DB_SCHEMA}.{T_EINHEIT}         WHERE wahljahr = 2021),
               (SELECT count(*) FROM {GERDA_SCHEMA}.gemeinde_gerda_unharm WHERE wahljahr = 2021),
               (SELECT count(*) FROM {DB_SCHEMA}.{T_EINHEIT} h
                 WHERE h.wahljahr = 2021 AND NOT EXISTS (
                     SELECT 1 FROM {GERDA_SCHEMA}.gemeinde_gerda_unharm u
                     WHERE u.wahljahr = 2021 AND u.ags = h.ags));
    """):
        log.info("  harm21 %s, unharm %s, nur in harm21 %s", *zeile)

    log.info("--- Anteile je Gemeinde (Nenner total_votes, erwartet: rund 1) ---")
    for zeile in query(f"""
        SELECT wahljahr,
               count(*)                                   AS gemeinden,
               count(*) FILTER (WHERE abs(s - 1) > 0.01)  AS abweichend,
               round(max(abs(s - 1))::numeric, 4)         AS groesste_abweichung
        FROM (SELECT wahljahr, ags, sum(anteil) AS s
              FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1, 2) x
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden, %s abweichend, groesste Abweichung %s", *zeile)


def main():
    panel = "--panel" in sys.argv
    waehle_betriebsart(panel)
    log.info("Betriebsart: %s -> %s.%s",
             "panel 1990-2025" if panel else "drei Wahljahre",
             DB_SCHEMA, T_EINHEIT)
    if "--neu" in sys.argv:
        run_sql(ddl(), f"ddl {T_EINHEIT}")
    merke_lieferung()
    tab, kopf, namen = staging()
    verteile(tab, kopf, namen)
    pruefe()


if __name__ == "__main__":
    main()
