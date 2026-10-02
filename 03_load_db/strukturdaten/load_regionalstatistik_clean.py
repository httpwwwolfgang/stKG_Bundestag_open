import logging
import sys
import pathlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import run_sql, query


LIEFERUNG = "destatis_regionaldatenbank"

ROH_SCHEMA = "strukturdaten_roh"
ROH_TABELLE = "regionalstatistik"
DB_SCHEMA = "strukturdaten"


WAHLEN = {2013: ("2013-09-22", 2012),
          2017: ("2017-09-24", 2016),
          2021: ("2021-09-26", 2020)}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("regionalstatistik_clean")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.regional_indikator (
    indikator_id SMALLINT PRIMARY KEY,
    ebene        TEXT     NOT NULL,
    tabelle      TEXT     NOT NULL,
    indikator    TEXT     NOT NULL,
    masseinheit  TEXT,
    merkmale     JSONB    NOT NULL,
    merkmal_hash TEXT     NOT NULL,
    UNIQUE (tabelle, indikator, merkmal_hash)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.gemeinde_regional (
    ags          CHAR(8)  NOT NULL,
    indikator_id SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.regional_indikator,
    jahr         SMALLINT NOT NULL,
    stichtag     DATE,
    wert         DOUBLE PRECISION,
    PRIMARY KEY (ags, indikator_id, jahr)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.kreis_regional (
    kreis        CHAR(5)  NOT NULL,
    indikator_id SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.regional_indikator,
    jahr         SMALLINT NOT NULL,
    stichtag     DATE,
    wert         DOUBLE PRECISION,
    PRIMARY KEY (kreis, indikator_id, jahr)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.gemeinde_regional_wahltag (
    wahl         SMALLINT NOT NULL,
    ags          CHAR(8)  NOT NULL,
    indikator_id SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.regional_indikator,
    jahr         SMALLINT NOT NULL,
    stichtag     DATE,
    wert         DOUBLE PRECISION NOT NULL,
    herkunft     TEXT     NOT NULL,
    PRIMARY KEY (wahl, ags, indikator_id)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.kreis_regional_wahltag (
    wahl         SMALLINT NOT NULL,
    kreis        CHAR(5)  NOT NULL,
    indikator_id SMALLINT NOT NULL REFERENCES {DB_SCHEMA}.regional_indikator,
    jahr         SMALLINT NOT NULL,
    stichtag     DATE,
    wert         DOUBLE PRECISION NOT NULL,
    herkunft     TEXT     NOT NULL,
    PRIMARY KEY (wahl, kreis, indikator_id)
);
"""


INDIZES = f"""
CREATE INDEX IF NOT EXISTS gemeinde_regional_such
    ON {DB_SCHEMA}.gemeinde_regional (indikator_id, jahr);
CREATE INDEX IF NOT EXISTS kreis_regional_such
    ON {DB_SCHEMA}.kreis_regional (indikator_id, jahr);
CREATE INDEX IF NOT EXISTS gemeinde_regional_wahltag_such
    ON {DB_SCHEMA}.gemeinde_regional_wahltag (wahl, indikator_id);
CREATE INDEX IF NOT EXISTS kreis_regional_wahltag_such
    ON {DB_SCHEMA}.kreis_regional_wahltag (wahl, indikator_id);
"""


def sql_stamm():
    return f"""
INSERT INTO {DB_SCHEMA}.regional_indikator
       (indikator_id, ebene, tabelle, indikator, masseinheit, merkmale, merkmal_hash)
SELECT row_number() OVER (ORDER BY ebene, tabelle, wertname, merkmal_hash)::smallint,
       ebene, tabelle,
       split_part(wertname, '__', 1),
       nullif(split_part(wertname, '__', 2), ''),
       merkmale, merkmal_hash
FROM (SELECT DISTINCT ebene, tabelle, wertname, merkmale, merkmal_hash
      FROM {ROH_SCHEMA}.{ROH_TABELLE}) d;
"""


def leere_wenn_gefuellt(tabellen):
    for t in tabellen:
        n = query(f"SELECT count(*) FROM {DB_SCHEMA}.{t};")[0][0]
        if int(n) > 0:
            run_sql(f"TRUNCATE {DB_SCHEMA}.{t} CASCADE;", f"{t} leeren ({n} Zeilen)")
        else:
            log.info("%s ist leer, kein TRUNCATE noetig", t)


def sql_werte(ebene, tabelle, spalte, stellen):
    schluessel = f"lpad(r.schluessel, {stellen}, '0')::CHAR({stellen})"
    return f"""
INSERT INTO {DB_SCHEMA}.{tabelle} ({spalte}, indikator_id, jahr, stichtag, wert)
SELECT {schluessel}, i.indikator_id, r.jahr, r.stichtag,
       nullif(replace(r.wert, ',', '.'), '')::double precision
FROM {ROH_SCHEMA}.{ROH_TABELLE} r
JOIN {DB_SCHEMA}.regional_indikator i
  ON i.tabelle = r.tabelle AND i.merkmal_hash = r.merkmal_hash
 AND i.indikator = split_part(r.wertname, '__', 1)
WHERE r.ebene = '{ebene}'
  AND length(r.schluessel) = {stellen}
  AND r.wert IS NOT NULL
ON CONFLICT ({spalte}, indikator_id, jahr) DO NOTHING;
"""


def sql_wahltag_gemeinde(wahl, wahltag, vorjahr):
    return f"""
WITH wahltagsgemeinde AS (
    SELECT DISTINCT ags FROM raum.gemeindestand_stichtag
    WHERE stichtag = DATE '{wahltag}'),
geaendert AS (
    SELECT DISTINCT ags FROM (
        SELECT ags_alt AS ags FROM raum.gebietsuebergang
        WHERE ebene = 'Gemeinde'
          AND art IN ('eingliederung', 'zusammenschluss', 'teilausgliederung')
          AND wirksam > DATE '{wahltag}' AND wirksam <= DATE '{wahl}-12-31'
          AND ags_alt IS NOT NULL AND ags_alt <> ags_neu
        UNION ALL
        SELECT ags_neu FROM raum.gebietsuebergang
        WHERE ebene = 'Gemeinde'
          AND art IN ('eingliederung', 'zusammenschluss', 'teilausgliederung')
          AND wirksam > DATE '{wahltag}' AND wirksam <= DATE '{wahl}-12-31'
          AND ags_neu IS NOT NULL AND ags_alt <> ags_neu) x)
INSERT INTO {DB_SCHEMA}.gemeinde_regional_wahltag
       (wahl, ags, indikator_id, jahr, stichtag, wert, herkunft)
SELECT {wahl}, g.ags, g.indikator_id, g.jahr, g.stichtag, g.wert, 'wahljahr'
FROM {DB_SCHEMA}.gemeinde_regional g
JOIN wahltagsgemeinde w ON w.ags = g.ags
WHERE g.jahr = {wahl} AND g.wert IS NOT NULL
  AND g.ags NOT IN (SELECT ags FROM geaendert)

UNION ALL

SELECT {wahl}, g.ags, g.indikator_id, g.jahr, g.stichtag, g.wert,
       'vorjahr_gebietsaenderung'
FROM {DB_SCHEMA}.gemeinde_regional g
JOIN wahltagsgemeinde w ON w.ags = g.ags
WHERE g.jahr = {vorjahr} AND g.wert IS NOT NULL
  AND g.ags IN (SELECT ags FROM geaendert);
"""


def sql_wahltag_kreis(wahl, wahltag):
    return f"""
INSERT INTO {DB_SCHEMA}.kreis_regional_wahltag
       (wahl, kreis, indikator_id, jahr, stichtag, wert, herkunft)
SELECT {wahl}, k.kreis, k.indikator_id, k.jahr, k.stichtag, k.wert, 'wahljahr'
FROM {DB_SCHEMA}.kreis_regional k
WHERE k.jahr = {wahl} AND k.wert IS NOT NULL
  AND EXISTS (SELECT 1 FROM raum.kreisstand_stichtag s
              WHERE s.stichtag = DATE '{wahltag}' AND s.ags = k.kreis);
"""


def pruefe_kreisuebergaenge():
    for wahl, (wahltag, _) in WAHLEN.items():
        z = query(f"""SELECT count(*) FROM raum.gebietsuebergang
                      WHERE ebene = 'Kreis'
                        AND art IN ('eingliederung', 'zusammenschluss')
                        AND wirksam > DATE '{wahltag}'
                        AND wirksam <= DATE '{wahl}-12-31';""")[0][0]
        if int(z) > 0:
            log.warning("Wahl %d: %s Kreisuebergaenge zwischen Wahltag und " "Jahresende - der Kreiszweig kennt dafuer keine Regel, " "die Faelle gehoeren vorgelegt.", wahl, z)
        else:
            log.info("Wahl %d: kein Kreisuebergang zwischen Wahltag und " "Jahresende", wahl)


def report():
    log.info("--- Indikatoren ---")
    for ebene, n in query(f"""SELECT ebene, count(*) FROM {DB_SCHEMA}.regional_indikator
                              GROUP BY ebene ORDER BY ebene;"""):
        log.info("  %-9s %s Indikatoren", ebene, n)

    log.info("--- Clean-Schicht, alle Jahrgaenge ---")
    for t, s in (("gemeinde_regional", "ags"), ("kreis_regional", "kreis")):
        for z in query(f"""SELECT count(*), count(DISTINCT {s}), count(DISTINCT jahr)
                           FROM {DB_SCHEMA}.{t};"""):
            log.info("  %-18s %10s Werte, %6s Einheiten, %s Jahrgaenge", t, *z)

    log.info("--- Wahltagszuschnitt: ist die ZUORDNUNG durch? ---")
    for wahl, (wahltag, vorjahr) in WAHLEN.items():
        for z in query(f"""
            WITH w AS (SELECT DISTINCT ags FROM raum.gemeindestand_stichtag
                       WHERE stichtag = DATE '{wahltag}')
            SELECT (SELECT count(*) FROM w),
                   (SELECT count(*) FROM w WHERE EXISTS (
                       SELECT 1 FROM {DB_SCHEMA}.gemeinde_regional_wahltag t
                       WHERE t.wahl = {wahl} AND t.ags = w.ags)),
                   (SELECT count(*) FROM {DB_SCHEMA}.gemeinde_regional_wahltag
                    WHERE wahl = {wahl} AND herkunft = 'vorjahr_gebietsaenderung'),
                   (SELECT count(DISTINCT ags) FROM {DB_SCHEMA}.gemeinde_regional_wahltag
                    WHERE wahl = {wahl} AND herkunft = 'vorjahr_gebietsaenderung');"""):
            log.info("  Wahl %d: %s Gemeinden am Wahltag, %s davon mit mindestens " "einem Wert | aus dem Vorjahrgang: %s Werte bei %s Gemeinden",
                     wahl, *z)
            fehlend = int(z[0]) - int(z[1])
            if fehlend:
                log.info("           %s Gemeinden ohne jeden Wert - Aufschluesselung:", fehlend)
                for b in query(f"""
                    WITH w AS (SELECT ags, bez FROM raum.gemeindestand_stichtag
                               WHERE stichtag = DATE '{wahltag}')
                    SELECT bez, count(*) FROM w
                    WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeinde_regional_wahltag t
                                      WHERE t.wahl = {wahl} AND t.ags = w.ags)
                    GROUP BY bez ORDER BY 2 DESC;"""):
                    log.info("             %-24s %s", *b)

    log.info("--- Wahltagszuschnitt: fuer wie viele Gemeinden gibt es je " "Indikator einen WERT? ---")
    log.info("    (eine Frage an die Quelle, nicht an die Zuordnung)")
    for wahl in WAHLEN:
        rows = query(f"""
            SELECT i.tabelle, count(DISTINCT t.ags)
            FROM {DB_SCHEMA}.gemeinde_regional_wahltag t
            JOIN {DB_SCHEMA}.regional_indikator i ON i.indikator_id = t.indikator_id
            WHERE t.wahl = {wahl}
            GROUP BY i.tabelle ORDER BY 2;""")
        gesamt = query(f"""SELECT count(*) FROM raum.gemeindestand_stichtag
                           WHERE stichtag = DATE '{WAHLEN[wahl][0]}';""")[0][0]
        log.info("  Wahl %d, von %s Wahltagsgemeinden:", wahl, gesamt)
        for tab, n in rows:
            log.info("    %-17s %6s", tab, n)

    log.info("--- Kreise ---")
    for wahl, (wahltag, _) in WAHLEN.items():
        for z in query(f"""
            SELECT (SELECT count(*) FROM raum.kreisstand_stichtag
                    WHERE stichtag = DATE '{wahltag}'),
                   (SELECT count(DISTINCT kreis) FROM {DB_SCHEMA}.kreis_regional_wahltag
                    WHERE wahl = {wahl});"""):
            log.info("  Wahl %d: %s Kreise am Wahltag, %s davon mit mindestens " "einem Wert", wahl, *z)


WAHLTAGSTABELLEN = ("gemeinde_regional_wahltag", "kreis_regional_wahltag")
WERTTABELLEN = ("gemeinde_regional", "kreis_regional")


def main():
    nur_wahltag = "--nur-wahltag" in sys.argv[1:]

    if "--neu" in sys.argv[1:]:
        for t in WAHLTAGSTABELLEN + WERTTABELLEN + ("regional_indikator",):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;", f"{t} verwerfen")
        log.warning("Alle fuenf Tabellen verworfen.")

    if not query(f"SELECT 1 FROM {ROH_SCHEMA}.{ROH_TABELLE} LIMIT 1;"):
        raise SystemExit(f"{ROH_SCHEMA}.{ROH_TABELLE} ist leer - "
                         f"erst load_regionalstatistik.py")

    run_sql(DDL, "ddl")

    if nur_wahltag:


        if not query(f"SELECT 1 FROM {DB_SCHEMA}.gemeinde_regional LIMIT 1;"):
            raise SystemExit("--nur-wahltag setzt gefuellte Werttabellen voraus; " "gemeinde_regional ist leer. Erst ohne Schalter laufen.")
        log.info("--nur-wahltag: Werttabellen und Indikatoren bleiben unveraendert")
    else:
        leere_wenn_gefuellt(WERTTABELLEN + ("regional_indikator",))
        run_sql(sql_stamm(), "regional_indikator")
        run_sql(sql_werte("gemeinde", "gemeinde_regional", "ags", 8), "gemeinde_regional")
        run_sql(sql_werte("kreis", "kreis_regional", "kreis", 5), "kreis_regional")

    leere_wenn_gefuellt(WAHLTAGSTABELLEN)
    pruefe_kreisuebergaenge()
    for wahl, (wahltag, vorjahr) in WAHLEN.items():
        run_sql(sql_wahltag_gemeinde(wahl, wahltag, vorjahr),
                f"gemeinde_regional_wahltag {wahl}")
        run_sql(sql_wahltag_kreis(wahl, wahltag), f"kreis_regional_wahltag {wahl}")

    run_sql(INDIZES, "indizes")
    report()


if __name__ == "__main__":
    main()
