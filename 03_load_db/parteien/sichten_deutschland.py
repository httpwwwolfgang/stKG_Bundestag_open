import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wahlergebnisse"))

from db import run_sql, query
from load_partei_mapping import gerda_spalten

DB_SCHEMA = "parteien"
GERDA_SCHEMA = "gerda_seit_1990"
T_ERGEBNIS = "gemeinde_harm21_ergebnis"

LAND = "Germany"
AB_WAHL = 199000
EU_CODE = 10

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sichten-de")


DDL_ZUORDNUNG = f"""
DROP TABLE IF EXISTS {DB_SCHEMA}.manifesto_gerda CASCADE;
CREATE TABLE {DB_SCHEMA}.manifesto_gerda (
    manifesto_code TEXT     NOT NULL,
    wahl_jahrmonat INTEGER  NOT NULL,
{T_ERGEBNIS}
    gerda_partei   TEXT     NOT NULL,

    verfahren      TEXT     NOT NULL,
    PRIMARY KEY (manifesto_code, wahl_jahrmonat, gerda_partei)
);
"""

DDL_SICHTEN = f"""
DROP VIEW IF EXISTS {DB_SCHEMA}.gemeinde_partei CASCADE;
DROP MATERIALIZED VIEW IF EXISTS {DB_SCHEMA}.de_kategorie CASCADE;
DROP MATERIALIZED VIEW IF EXISTS {DB_SCHEMA}.de_programm  CASCADE;
DROP MATERIALIZED VIEW IF EXISTS {DB_SCHEMA}.eu_referenz  CASCADE;

CREATE MATERIALIZED VIEW {DB_SCHEMA}.eu_referenz AS
SELECT id_perm, land, wahl_jahrmonat, partei_kuerzel, rile
FROM {DB_SCHEMA}.manifesto_programm
WHERE eu_mitglied = {EU_CODE}
  AND wahl_jahrmonat >= {AB_WAHL}
  AND rile IS NOT NULL;

CREATE MATERIALIZED VIEW {DB_SCHEMA}.de_programm AS
SELECT p.wahl_jahrmonat, p.wahltag,
       p.partei_code, p.partei_kuerzel, p.partei_name,
       p.stimmenanteil, p.sitze, p.sitze_gesamt,
       p.saetze, p.uncodiert,
       p.handbuch, p.codierer, p.reliabilitaet,

       p.korpusversion,
       p.rile, p.planeco, p.markeco, p.welfare, p.intpeace,
       (SELECT round((100.0 * count(*) FILTER (WHERE r.rile < p.rile)
                      / count(*))::numeric, 1)
        FROM {DB_SCHEMA}.eu_referenz r)               AS rile_perzentil_eu,
       (SELECT count(*) FROM {DB_SCHEMA}.eu_referenz) AS referenz_programme
FROM {DB_SCHEMA}.manifesto_programm p
WHERE p.land = '{LAND}' AND p.wahl_jahrmonat >= {AB_WAHL};
CREATE UNIQUE INDEX de_programm_pk
    ON {DB_SCHEMA}.de_programm (wahl_jahrmonat, partei_code);

CREATE MATERIALIZED VIEW {DB_SCHEMA}.de_kategorie AS
SELECT p.wahl_jahrmonat, p.partei_code, p.partei_kuerzel,
       k.code, k.bezeichnung, k.domaene, k.domaene_name,
       k.rile_seite,


       k.gegenkategorie,
       a.anteil                                   AS anteil_prozent,
       round((a.anteil * p.saetze / 100.0)::numeric, 0)::int
                                                  AS saetze_rueckgerechnet,
       p.saetze                                   AS saetze_programm
FROM {DB_SCHEMA}.manifesto_programm p
JOIN {DB_SCHEMA}.manifesto_anteil a    ON a.id_perm = p.id_perm
JOIN {DB_SCHEMA}.manifesto_kategorie k ON k.code = a.code
WHERE p.land = '{LAND}' AND p.wahl_jahrmonat >= {AB_WAHL}
  AND k.art = 'haupt';
CREATE UNIQUE INDEX de_kategorie_pk
    ON {DB_SCHEMA}.de_kategorie (wahl_jahrmonat, partei_code, code);

CREATE VIEW {DB_SCHEMA}.gemeinde_partei AS
SELECT e.wahljahr,
       e.ags,
       e.partei,
       e.anteil,
       z.manifesto_code,
       m.partei_kuerzel   AS manifesto_partei,
       m.rile,
       m.saetze           AS manifesto_saetze,
       (m.rile IS NOT NULL) AS hat_score
FROM {GERDA_SCHEMA}.{T_ERGEBNIS} e
LEFT JOIN {DB_SCHEMA}.manifesto_gerda z
       ON z.gerda_partei = e.partei
      AND z.wahl_jahrmonat / 100 = e.wahljahr
LEFT JOIN {DB_SCHEMA}.manifesto_programm m
       ON m.partei_code = z.manifesto_code
      AND m.wahl_jahrmonat = z.wahl_jahrmonat;
"""


def lit(w):
    return "'" + str(w).replace("'", "''") + "'"


def lade_zuordnung():
    run_sql(DDL_ZUORDNUNG, "tabelle manifesto_gerda")
    programme = query(f"""
        SELECT partei_code, wahl_jahrmonat,
               coalesce(partei_kuerzel, partei_name)
        FROM {DB_SCHEMA}.manifesto_programm
        WHERE land = '{LAND}' AND wahl_jahrmonat >= {AB_WAHL}
        ORDER BY 2, 1;
    """)
    werte = []
    for code, wahl, name in programme:
        spalten, verfahren = gerda_spalten(name)
        for sp in spalten:
            werte.append(f"({lit(code)}, {wahl}, {lit(sp)}, {lit(verfahren)})")
    run_sql(f"""
    INSERT INTO {DB_SCHEMA}.manifesto_gerda
        (manifesto_code, wahl_jahrmonat, gerda_partei, verfahren)
    VALUES {", ".join(werte)}
    ON CONFLICT DO NOTHING;
    """, "zuordnung")
    log.info("%d Programme -> %d Zuordnungszeilen", len(programme), len(werte))


def pruefe():
    log.info("--- Gibt es jede zugeordnete GERDA-Partei in ihrer Wahl? ---")
    fehl = query(f"""
        SELECT z.wahl_jahrmonat, z.manifesto_code, z.gerda_partei
        FROM {DB_SCHEMA}.manifesto_gerda z
        WHERE NOT EXISTS (
            SELECT 1 FROM {GERDA_SCHEMA}.{T_ERGEBNIS} e
            WHERE e.partei = z.gerda_partei
              AND e.wahljahr = z.wahl_jahrmonat / 100)
        ORDER BY 1, 2;
    """)
    if fehl:
        for z in fehl:
            log.warning("  FEHLT: Wahl %s, %s -> %s", *z)
    else:
        log.info("  alle vorhanden")

    log.info("--- Umfang ---")
    for z in query(f"""
        SELECT (SELECT count(*) FROM {DB_SCHEMA}.de_programm),
               (SELECT count(*) FROM {DB_SCHEMA}.de_kategorie),
               (SELECT count(*) FROM {DB_SCHEMA}.eu_referenz),
               (SELECT count(*) FROM {DB_SCHEMA}.manifesto_gerda);
    """):
        log.info("  de_programm %s, de_kategorie %s, eu_referenz %s, " "zuordnung %s", *z)

    log.info("--- Wieviel Prozent der Stimmen haben je Wahl einen Score? ---")
    for z in query(f"""
        SELECT wahljahr,
               count(DISTINCT ags),
               round((100.0 * sum(anteil) FILTER (WHERE hat_score)
                      / sum(anteil))::numeric, 2)
        FROM {DB_SCHEMA}.gemeinde_partei
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden, %s %% der Stimmen mit Score", *z)

    log.info("--- Probe: Koeln und Muenchen 2021, Union ---")
    for z in query(f"""
        SELECT g.ags, e.gemeindename, g.partei,
               round(g.anteil::numeric, 4), g.manifesto_code, g.rile
        FROM {DB_SCHEMA}.gemeinde_partei g
        JOIN {GERDA_SCHEMA}.gemeinde_harm21 e
          ON e.ags = g.ags AND e.wahljahr = g.wahljahr
        WHERE g.wahljahr = 2021 AND g.partei IN ('cdu', 'csu')
          AND g.ags IN ('05315000', '09162000')
        ORDER BY 1, 3;
    """):
        log.info("  %s %-24s %-4s %8s  %s  rile %s", *z)

    log.info("--- EU-Perzentil, Wahl 2021 ---")
    for z in query(f"""
        SELECT partei_kuerzel, rile, rile_perzentil_eu
        FROM {DB_SCHEMA}.de_programm
        WHERE wahl_jahrmonat = 202109 ORDER BY rile;
    """):
        log.info("  %-10s rile %8s  rechter als %5s %% der EU-Programme", *z)


def main():
    lade_zuordnung()
    run_sql(DDL_SICHTEN, "sichten deutschland")
    pruefe()


if __name__ == "__main__":
    main()
