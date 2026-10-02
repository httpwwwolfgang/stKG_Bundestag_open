import sys
import csv
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query


import lieferung
LIEFERUNG = "gerda_federal_muni_raw"

DB_SCHEMA = "gerda"
T_EINHEIT  = "gemeindeeinheit_gerda"
T_ERGEBNIS = "gemeindeergebnis_gerda"
T_KENNZAHL = "gemeindekennzahl_gerda"

QUELL_DATEI = (Path(__file__).resolve().parents[4] / "Daten" / "Wahlergebnisse"
               / "GERDA" / "federal_muni_raw.txt")

JAHRE = [2013, 2017, 2021]


METADATEN = [
    "ags", "bwbez", "county", "election_year", "election_date", "state",
    "eligible_voters", "number_voters", "valid_votes", "invalid_votes",
    "voters_wo_blockingnotice", "voters_blockingnotice", "voters_par25_2",
    "voters_w_ballot", "unique_mailin", "joint_mailin",
    "pop", "area", "pop_weight", "area_weight",
]


AGGREGATE = ["cdu_csu", "far_right", "far_left", "far_left_w_linke",
             "gruene_comb", "linke_pds_comb"]


KENNZAHLEN = {
    "eligible_voters":          "wahlberechtigte",
    "number_voters":            "waehlende",
    "valid_votes":              "gueltige_stimmen",
    "invalid_votes":            "ungueltige_stimmen",
    "voters_w_ballot":          "wahlscheininhaber",
    "voters_wo_blockingnotice": "waehlende_ohne_sperrvermerk",
    "voters_blockingnotice":    "waehlende_mit_sperrvermerk",
    "voters_par25_2":           "waehlende_par25_abs2",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemeindeergebnis")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_EINHEIT} (
    wahljahr        SMALLINT NOT NULL REFERENCES wahlergebnisse.wahl (wahljahr),
    ags             CHAR(8)  NOT NULL,
    bwbez           TEXT     NOT NULL DEFAULT '',
    einheitstyp     TEXT     NOT NULL
                    CHECK (einheitstyp IN ('gemeinde', 'briefwahlverbund')),
    briefwahl_eigen BOOLEAN,
    kreis           TEXT,
    land            TEXT,
    PRIMARY KEY (wahljahr, ags, bwbez)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_ERGEBNIS} (
    wahljahr SMALLINT NOT NULL,
    ags      CHAR(8)  NOT NULL,
    bwbez    TEXT     NOT NULL DEFAULT '',
    partei   TEXT     NOT NULL,
    stimmen  INTEGER,
    PRIMARY KEY (wahljahr, ags, bwbez, partei),
    FOREIGN KEY (wahljahr, ags, bwbez)
        REFERENCES {DB_SCHEMA}.{T_EINHEIT} (wahljahr, ags, bwbez) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_KENNZAHL} (
    wahljahr SMALLINT NOT NULL,
    ags      CHAR(8)  NOT NULL,
    bwbez    TEXT     NOT NULL DEFAULT '',
    merkmal  TEXT     NOT NULL,
    wert     INTEGER,
    PRIMARY KEY (wahljahr, ags, bwbez, merkmal),
    FOREIGN KEY (wahljahr, ags, bwbez)
        REFERENCES {DB_SCHEMA}.{T_EINHEIT} (wahljahr, ags, bwbez) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS {T_ERGEBNIS}_partei ON {DB_SCHEMA}.{T_ERGEBNIS} (partei);
CREATE INDEX IF NOT EXISTS {T_EINHEIT}_typ ON {DB_SCHEMA}.{T_EINHEIT} (wahljahr, einheitstyp);
"""


def spalten():
    if not QUELL_DATEI.exists():
        raise SystemExit(f"Datei fehlt: {QUELL_DATEI}")
    with QUELL_DATEI.open("r", encoding="utf-8", newline="") as f:
        kopf = next(csv.reader(f))

    fehlend = [s for s in METADATEN if s not in kopf]
    if fehlend:
        raise SystemExit(f"Erwartete Spalten fehlen: {fehlend}")

    parteien = [s for s in kopf if s not in METADATEN and s not in AGGREGATE]
    log.info("%d Spalten: %d Metadaten, %d Parteien, %d Aggregate (uebergangen)",
             len(kopf), len(METADATEN), len(parteien), len(AGGREGATE))
    return kopf, parteien


def lade(kopf, parteien):
    liste = ", ".join(str(j) for j in JAHRE)
    pfad = str(QUELL_DATEI).replace("\\", "/")
    tmp_spalten = ",\n    ".join(f'"{s}" TEXT' for s in kopf)


    paare = ",\n            ".join(f"('{p}', \"{p}\")" for p in parteien)
    kennzahl_paare = ",\n            ".join(
        f"('{merkmal}', \"{spalte}\")" for spalte, merkmal in KENNZAHLEN.items()
    )

    sql = f"""
CREATE TEMP TABLE roh (
    {tmp_spalten}
);

\\copy roh FROM '{pfad}' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

DELETE FROM {DB_SCHEMA}.{T_EINHEIT} WHERE wahljahr IN ({liste});

INSERT INTO {DB_SCHEMA}.{T_EINHEIT}
    (wahljahr, ags, bwbez, einheitstyp, briefwahl_eigen, kreis, land)
SELECT election_year::SMALLINT,
       left(trim(ags), 8),
       coalesce(trim(bwbez), ''),
       CASE WHEN joint_mailin = '1' THEN 'briefwahlverbund' ELSE 'gemeinde' END,
       nullif(unique_mailin, '')::int = 1,
       nullif(trim(county), ''),
       nullif(trim(state), '')
FROM roh
WHERE election_year::SMALLINT IN ({liste});

INSERT INTO {DB_SCHEMA}.{T_ERGEBNIS} (wahljahr, ags, bwbez, partei, stimmen)
SELECT r.election_year::SMALLINT, left(trim(r.ags), 8),
       coalesce(trim(r.bwbez), ''), p.partei,
       round(p.wert::numeric)::INTEGER
FROM roh r
CROSS JOIN LATERAL (VALUES
            {paare}
       ) AS p(partei, wert)
WHERE r.election_year::SMALLINT IN ({liste})
  AND p.wert IS NOT NULL AND p.wert <> '' AND p.wert <> 'NA';

INSERT INTO {DB_SCHEMA}.{T_KENNZAHL} (wahljahr, ags, bwbez, merkmal, wert)
SELECT r.election_year::SMALLINT, left(trim(r.ags), 8),
       coalesce(trim(r.bwbez), ''), k.merkmal,
       round(k.wert::numeric)::INTEGER
FROM roh r
CROSS JOIN LATERAL (VALUES
            {kennzahl_paare}
       ) AS k(merkmal, wert)
WHERE r.election_year::SMALLINT IN ({liste})
  AND k.wert IS NOT NULL AND k.wert <> '' AND k.wert <> 'NA';

DROP TABLE roh;
"""
    ziel = Path(tempfile.gettempdir()) / "gemeindeergebnisse.sql"
    ziel.write_text(sql, encoding="utf-8")
    run_sql_file(ziel, label="gemeindeergebnisse")
    ziel.unlink(missing_ok=True)


def report():
    log.info("--- %s ---", DB_SCHEMA)
    log.info("%-6s %-18s %9s %9s %12s", "Jahr", "Einheitstyp", "Einheiten",
             "mit eigen", "Ergebnisse")
    for zeile in query(f"""
        SELECT e.wahljahr, e.einheitstyp, count(*),
               count(*) FILTER (WHERE e.briefwahl_eigen),
               (SELECT count(*) FROM {DB_SCHEMA}.{T_ERGEBNIS} g
                 WHERE g.wahljahr = e.wahljahr
                   AND (g.ags, g.bwbez) IN
                       (SELECT x.ags, x.bwbez FROM {DB_SCHEMA}.{T_EINHEIT} x
                         WHERE x.wahljahr = e.wahljahr
                           AND x.einheitstyp = e.einheitstyp))
        FROM {DB_SCHEMA}.{T_EINHEIT} e
        GROUP BY e.wahljahr, e.einheitstyp ORDER BY 1, 2;
    """):
        log.info("%-6s %-18s %9s %9s %12s", *zeile)

    zeilen = query(f"""
        SELECT count(DISTINCT partei) FROM {DB_SCHEMA}.{T_ERGEBNIS};
    """)
    log.info("Verschiedene Parteien insgesamt: %s", zeilen[0][0] if zeilen else "?")


def main():
    lieferung.merke(LIEFERUNG)
    if "--neu" in sys.argv[1:]:
        for t in (T_ERGEBNIS, T_KENNZAHL, T_EINHEIT):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;", f"drop {t}")
        log.warning("Tabellen verworfen.")

    run_sql(DDL, "ddl")
    kopf, parteien = spalten()
    lade(kopf, parteien)
    report()


if __name__ == "__main__":
    main()
