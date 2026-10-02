import sys
import csv
import logging
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

DB_SCHEMA   = "gerda"
META_SCHEMA = "meta"
T_EINHEIT   = "kreis_gerda_harm"
T_ERG       = "kreis_gerda_harm_ergebnis"

DATEI = (Path(__file__).resolve().parents[4] / "Daten" / "wahlergebnisse"
         / "GERDA" / "federal_cty_harm.txt")

JAHRE = (2013, 2017, 2021)


KOPFSPALTEN = 8

NICHT_PARTEI = ("election_date", "area", "population",
                "flag_unsuccessful_naive_merge", "total_votes",
                "cdu_csu", "far_right", "far_left", "far_left_w_linke")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gerda-kreis-harm")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

DROP TABLE IF EXISTS {DB_SCHEMA}.{T_ERG}     CASCADE;
DROP TABLE IF EXISTS {DB_SCHEMA}.{T_EINHEIT} CASCADE;

CREATE TABLE {DB_SCHEMA}.{T_EINHEIT} (
    wahljahr        SMALLINT NOT NULL,

    kreis           CHAR(5)  NOT NULL,
    wahltag         DATE,
    land            CHAR(2),
    wahlberechtigte INTEGER,
    waehlende       INTEGER,
    gueltige        INTEGER,
    ungueltige      INTEGER,
    turnout         DOUBLE PRECISION,

    cdu_csu          DOUBLE PRECISION,
    far_right        DOUBLE PRECISION,
    far_left         DOUBLE PRECISION,
    far_left_w_linke DOUBLE PRECISION,

    stimmen_summe   DOUBLE PRECISION,
    flaeche         DOUBLE PRECISION,
    einwohner       DOUBLE PRECISION,
    lieferung_id    TEXT,
    PRIMARY KEY (wahljahr, kreis),
    FOREIGN KEY (lieferung_id)
        REFERENCES {META_SCHEMA}.datenlieferung (lieferung_id)
);
CREATE INDEX {T_EINHEIT}_kreis ON {DB_SCHEMA}.{T_EINHEIT} (kreis);

CREATE TABLE {DB_SCHEMA}.{T_ERG} (
    wahljahr SMALLINT NOT NULL,
    kreis    CHAR(5)  NOT NULL,
    partei   TEXT     NOT NULL,

    anteil   DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (wahljahr, kreis, partei),
    FOREIGN KEY (wahljahr, kreis)
        REFERENCES {DB_SCHEMA}.{T_EINHEIT} (wahljahr, kreis) ON DELETE CASCADE
);
CREATE INDEX {T_ERG}_partei ON {DB_SCHEMA}.{T_ERG} (wahljahr, partei);
"""


def merke_lieferung():
    run_sql(f"""
    INSERT INTO {META_SCHEMA}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, datei, gebietsstand, lizenz, art)
    VALUES ('gerda_federal_cty_harm',
            'GERDA federal_cty_harm, Kreisebene auf Gebietsstand 2021',
            'Heddesheimer, Hilbig, Sichart & Wiedemann (2025), doi:10.1038/s41597-025-04811-5',
            '{DATEI.name}', DATE '2021-12-31', 'CC-BY-4.0', 'abgeleitet')
    ON CONFLICT (lieferung_id) DO UPDATE SET bezeichnung = EXCLUDED.bezeichnung;
    """, "lieferung gerda_cty_harm")


def staging():
    if not DATEI.exists():
        raise SystemExit(f"Datei fehlt: {DATEI}")
    with DATEI.open(encoding="utf-8", newline="") as fh:
        kopf = next(csv.reader(fh))
    log.info("%d Spalten in %s", len(kopf), DATEI.name)
    ix_jahr = kopf.index("election_year")

    tmp_csv = Path(tempfile.gettempdir()) / "gerda_cty_harm.csv"
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

    tab   = f"{DB_SCHEMA}.stg_gerda_cty_harm"
    namen = [f"c{i:03d}" for i in range(len(kopf))]
    sql   = Path(tempfile.gettempdir()) / "gerda_cty_harm.sql"
    sql.write_text(
        f"DROP TABLE IF EXISTS {tab};\n"
        f"CREATE TABLE {tab} (\n    "
        + ",\n    ".join(f"{n} TEXT" for n in namen) + "\n);\n"
        f"\\copy {tab} FROM '{tmp_csv.as_posix()}' "
        f"WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');\n",
        encoding="utf-8")
    run_sql_file(sql, label="staging gerda_cty_harm")
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
        (wahljahr, kreis, wahltag, land, wahlberechtigte, waehlende,
         gueltige, ungueltige, turnout,
         cdu_csu, far_right, far_left, far_left_w_linke,
         stimmen_summe, flaeche, einwohner, lieferung_id)
    SELECT {idx['election_year']}::int,
           lpad(trim({idx['county_code']}), 5, '0'),
           to_date(nullif(trim({idx['election_date']}), ''), 'YYYY-MM-DD'),
           {idx['state']},
           {i('eligible_voters')}, {i('number_voters')},
           {i('valid_votes')}, {i('invalid_votes')}, {d('turnout')},
           {d('cdu_csu')}, {d('far_right')}, {d('far_left')},
           {d('far_left_w_linke')},
           {d('total_votes')}, {d('area')}, {d('population')},
           'gerda_federal_cty_harm'
    FROM {tab}
    WHERE trim({idx['county_code']}) ~ '^[0-9]{{4,5}}$'
    ON CONFLICT DO NOTHING;
    """, "einheiten gerda_cty_harm")

    parteien = [n for n in kopf[KOPFSPALTEN:] if n not in NICHT_PARTEI]
    log.info("%d Parteispalten", len(parteien))
    teile = [
        f"SELECT {idx['election_year']}::int, "
        f"lpad(trim({idx['county_code']}), 5, '0'), '{p}', {zahl(idx[p], 'float')}\n"
        f"FROM {tab} WHERE trim({idx['county_code']}) ~ '^[0-9]{{4,5}}$' "
        f"AND {zahl(idx[p], 'float')} IS NOT NULL"
        for p in parteien]

    sql = Path(tempfile.gettempdir()) / "gerda_cty_harm_erg.sql"
    sql.write_text(
        "SET client_encoding TO 'UTF8';\n"
        f"INSERT INTO {DB_SCHEMA}.{T_ERG} (wahljahr, kreis, partei, anteil)\n"
        + "\nUNION ALL\n".join(teile) + "\nON CONFLICT DO NOTHING;\n",
        encoding="utf-8")
    run_sql_file(sql, label="ergebnisse gerda_cty_harm")
    sql.unlink(missing_ok=True)
    run_sql(f"DROP TABLE IF EXISTS {tab};", "staging weg")


def pruefe():
    log.info("--- %s.%s ---", DB_SCHEMA, T_EINHEIT)
    for zeile in query(f"""
        SELECT wahljahr, count(*),
               to_char(sum(wahlberechtigte), 'FM999G999G999'),
               to_char(sum(gueltige), 'FM999G999G999')
        FROM {DB_SCHEMA}.{T_EINHEIT} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Kreise, %s Wahlberechtigte, %s gueltige Stimmen", *zeile)

    log.info("--- Anteile je Kreis (Nenner total_votes, erwartet: rund 1) ---")
    for zeile in query(f"""
        SELECT wahljahr, count(*),
               count(*) FILTER (WHERE abs(s - 1) > 0.01) AS abweichend,
               round(max(abs(s - 1))::numeric, 4)
        FROM (SELECT wahljahr, kreis, sum(anteil) AS s
              FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1, 2) x
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Kreise, %s abweichend, groesste Abweichung %s", *zeile)

    log.info("--- Kreise gegen den eigenen Gebietsstand 2021 ---")
    for zeile in query(f"""
        SELECT g.wahljahr, count(*) AS gerda,
               count(*) FILTER (WHERE k.ags IS NULL) AS ohne_gegenstueck
        FROM {DB_SCHEMA}.{T_EINHEIT} g
        LEFT JOIN raum.kreisstand k
               ON k.stichtag = DATE '2021-12-31' AND trim(k.ags) = trim(g.kreis)
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Kreise bei GERDA, %s ohne Gegenstueck im eigenen Stand",
                 *zeile)


def main():
    if "--neu" in sys.argv:
        run_sql(DDL, "ddl gerda_cty_harm")
    merke_lieferung()
    tab, kopf, namen = staging()
    verteile(tab, kopf, namen)
    pruefe()


if __name__ == "__main__":
    main()
