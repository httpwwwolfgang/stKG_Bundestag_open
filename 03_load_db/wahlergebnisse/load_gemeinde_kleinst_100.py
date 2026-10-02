import sys
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, query

DB_SCHEMA   = "raum"
ERG_SCHEMA  = "wahlergebnisse"
TABELLE    = "gemeinde_kleinst_100"
MV_AMTLICH = "kleinst_100_amtlich"
MV_GETEILT = "kleinst_100_geteilt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("einheit-mitglied")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    wahljahr        SMALLINT NOT NULL,
    einheit_id      TEXT     NOT NULL,
    ags             CHAR(8)  NOT NULL,
    gemeindename    TEXT,
    rolle           TEXT     NOT NULL,
    bestand         TEXT     NOT NULL,
    wkr_nr          SMALLINT,
    kreis           CHAR(5),
    bwbez           TEXT,
    bezirke         INTEGER,
    wahlberechtigte INTEGER,
    waehlende       INTEGER,
    lieferung_id    TEXT,
    PRIMARY KEY (wahljahr, einheit_id, ags)
);

CREATE INDEX IF NOT EXISTS {TABELLE}_ags_idx
    ON {DB_SCHEMA}.{TABELLE} (wahljahr, ags);
CREATE INDEX IF NOT EXISTS {TABELLE}_einheit_idx
    ON {DB_SCHEMA}.{TABELLE} (wahljahr, einheit_id);
"""


SQL = f"""
TRUNCATE {DB_SCHEMA}.{TABELLE};

INSERT INTO {DB_SCHEMA}.{TABELLE}
    (wahljahr, einheit_id, ags, gemeindename, rolle, bestand,
     wkr_nr, kreis, bwbez, bezirke, wahlberechtigte, waehlende, lieferung_id)
WITH bezirk AS (

    SELECT w.*,
           raum.gemeinde_ags(w.ags) AS gem_ags
    FROM {ERG_SCHEMA}.wahlbezirk w
),
geteilt AS (
    SELECT wahljahr, gem_ags
    FROM (SELECT DISTINCT wahljahr, gem_ags, wkr_nr FROM bezirk) d
    WHERE NOT raum.ist_sammelposten(gem_ags)
    GROUP BY 1, 2 HAVING count(*) > 1
),
zuordnung AS (
    SELECT b.wahljahr, b.gem_ags, b.wkr_nr, b.kreis, b.bwbez,
           EXISTS (SELECT 1 FROM geteilt g
                   WHERE (g.wahljahr, g.gem_ags) = (b.wahljahr, b.gem_ags))
               AS ist_geteilt,
           raum.ist_sammelposten(b.gem_ags) AS ist_sammelposten,
           b.gemeindename, b.wahlberechtigte, b.waehlende
    FROM bezirk b
),
mit_einheit AS (
    SELECT z.*,
           CASE WHEN z.ist_geteilt THEN t.einheit_id
                WHEN z.bwbez = '00' THEN z.gem_ags
                ELSE 'V-' || z.kreis || '-' || z.bwbez
                     || '-' || lpad(z.wkr_nr::text, 3, '0') END AS einheit_id,
           CASE WHEN z.ist_geteilt THEN 'geteilt' ELSE 'amtlich' END AS bestand
    FROM zuordnung z
    LEFT JOIN {DB_SCHEMA}.{MV_GETEILT} t
      ON (t.wahljahr, t.ags, t.wkr_nr) = (z.wahljahr, z.gem_ags, z.wkr_nr)
),
benannt AS (
    SELECT m.wahljahr, m.gem_ags, g.gen
    FROM (SELECT DISTINCT wahljahr, gem_ags FROM mit_einheit
          WHERE NOT raum.ist_sammelposten(gem_ags)) m
    JOIN zeit.stichtag zt
      ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || m.wahljahr::text
    JOIN raum.gemeindestand_stichtag g
      ON g.stichtag = zt.datum AND g.ags = m.gem_ags
)
SELECT m.wahljahr, m.einheit_id, m.gem_ags,
       coalesce(b.gen, max(m.gemeindename))                 AS gemeindename,
       CASE WHEN m.ist_sammelposten THEN 'sammelposten'
            ELSE 'gemeinde' END                             AS rolle,
       m.bestand,
       max(m.wkr_nr)                                        AS wkr_nr,
       max(m.kreis)                                         AS kreis,
       max(m.bwbez)                                         AS bwbez,
       count(*)                                             AS bezirke,
       sum(m.wahlberechtigte)                               AS wahlberechtigte,
       sum(m.waehlende)                                     AS waehlende,
       CASE WHEN m.bestand = 'geteilt' THEN 'grossstadt_wkr_' || m.wahljahr
            ELSE 'bwl_wahlbezirke_' || m.wahljahr END       AS lieferung_id
FROM mit_einheit m
LEFT JOIN benannt b ON (b.wahljahr, b.gem_ags) = (m.wahljahr, m.gem_ags)
WHERE m.einheit_id IS NOT NULL
GROUP BY m.wahljahr, m.einheit_id, m.gem_ags, m.ist_sammelposten,
         m.bestand, b.gen;

INSERT INTO {DB_SCHEMA}.{TABELLE}
    (wahljahr, einheit_id, ags, gemeindename, rolle, bestand,
     wkr_nr, kreis, bwbez, bezirke, wahlberechtigte, waehlende, lieferung_id)
SELECT DISTINCT ON (a.wahljahr, m.einheit_id, a.ags)
       a.wahljahr, m.einheit_id, a.ags,
       coalesce(s.gen, a.gemeindename), 'aufgenommen', m.bestand,
       m.wkr_nr, m.kreis, m.bwbez, 0, NULL, NULL, m.lieferung_id
FROM raum.gemeinde_aufnahme a
JOIN {DB_SCHEMA}.{TABELLE} m
  ON m.wahljahr = a.wahljahr AND m.ags = a.ags_aufnehmend
JOIN zeit.stichtag zt
  ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || a.wahljahr::text
LEFT JOIN raum.gemeindestand_stichtag s
  ON s.stichtag = zt.datum AND s.ags = a.ags
ORDER BY a.wahljahr, m.einheit_id, a.ags
ON CONFLICT DO NOTHING;
"""


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    log.info("%-6s %-10s %-14s %9s %11s", "Jahr", "Bestand", "Rolle",
             "Zeilen", "Gemeinden")
    for zeile in query(f"""
        SELECT wahljahr, bestand, rolle, count(*), count(DISTINCT ags)
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;
    """):
        log.info("%-6s %-10s %-14s %9s %11s", *zeile)

    log.info("--- Jede Einheit hat Mitglieder? ---")
    for zeile in query(f"""
        SELECT e.wahljahr, count(*) AS einheiten,
               count(*) FILTER (WHERE m.n IS NULL) AS ohne_mitglied
        FROM (SELECT wahljahr, einheit_id FROM {DB_SCHEMA}.{MV_AMTLICH}
              UNION ALL
              SELECT wahljahr, einheit_id FROM {DB_SCHEMA}.{MV_GETEILT}) e
        LEFT JOIN (SELECT wahljahr, einheit_id, count(*) AS n
                   FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1, 2) m
          ON (m.wahljahr, m.einheit_id) = (e.wahljahr, e.einheit_id)
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Einheiten, davon ohne Mitglied %s", *zeile)

    log.info("--- Verbuende: Groesse und Sammelposten ---")
    for zeile in query(f"""
        SELECT wahljahr, count(*) AS verbuende,
               sum(gemeinden) AS mitglieder, max(gemeinden) AS groesster,
               count(*) FILTER (WHERE sammelposten = 0) AS ohne_sammelposten
        FROM (SELECT wahljahr, einheit_id,
                     count(*) FILTER (WHERE rolle = 'gemeinde')     AS gemeinden,
                     count(*) FILTER (WHERE rolle = 'sammelposten') AS sammelposten
              FROM {DB_SCHEMA}.{TABELLE}
              WHERE einheit_id LIKE 'V-%' GROUP BY 1, 2) v
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Verbuende, %s Mitgliedsgemeinden " "(groesster %s), ohne Sammelposten %s", *zeile)

    log.info("--- Gegenprobe: deckt sich die Zahl mit kleinst_100_amtlich? ---")
    for zeile in query(f"""
        SELECT a.wahljahr, a.gemeinden AS in_der_sicht,
               m.gemeinden AS hier, a.gemeinden - m.gemeinden AS differenz
        FROM (SELECT wahljahr, sum(gemeinden) AS gemeinden
              FROM {DB_SCHEMA}.{MV_AMTLICH} GROUP BY 1) a
        JOIN (SELECT wahljahr, count(*) AS gemeinden
              FROM {DB_SCHEMA}.{TABELLE}
              WHERE rolle = 'gemeinde' AND bestand = 'amtlich'
              GROUP BY 1) m USING (wahljahr)
        ORDER BY 1;
    """):
        log.info("  %s: Sicht %s, hier %s, Differenz %s", *zeile)

    log.info("--- Gegenprobe gegen GERDA (gerda.briefwahl_gemeinde) ---")
    for zeile in query(f"""
        SELECT m.wahljahr,
               count(*)                                             AS gemeinsam,
               count(*) FILTER (WHERE (m.einheit_id = m.ags) = (g.briefwahl = 'eigen'))
                                                                    AS gleich
        FROM (SELECT wahljahr, ags, einheit_id FROM {DB_SCHEMA}.{TABELLE}
              WHERE rolle = 'gemeinde' AND bestand = 'amtlich') m
        JOIN gerda.briefwahl_gemeinde g
          ON (g.wahljahr, g.ags) = (m.wahljahr, m.ags)
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden in beiden, davon gleich eingestuft %s",
                 *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;",
                "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    run_sql(DDL, "ddl")
    run_sql(SQL, "gemeinde_kleinst_100")
    report()


if __name__ == "__main__":
    main()
