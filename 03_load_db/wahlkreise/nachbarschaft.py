from pathlib import Path

import sys
import logging

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import DB_SCHEMA, run_sql, query


MIN_GRENZE_M = 100.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wk-nachbarn")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.nachbarschaft (
    wahljahr       SMALLINT NOT NULL,
    wkr_von        SMALLINT NOT NULL,
    wkr_nach       SMALLINT NOT NULL,
    grenzlaenge_m  DOUBLE PRECISION NOT NULL,
    azimut_grad    DOUBLE PRECISION NOT NULL,
    richtung       TEXT NOT NULL,
    distanz_m      DOUBLE PRECISION NOT NULL,
    berechnet_am   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (wahljahr, wkr_von, wkr_nach),
    FOREIGN KEY (wahljahr, wkr_von)
        REFERENCES {DB_SCHEMA}.wahlkreis (wahljahr, wkr_nr) ON DELETE CASCADE,
    FOREIGN KEY (wahljahr, wkr_nach)
        REFERENCES {DB_SCHEMA}.wahlkreis (wahljahr, wkr_nr) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_nachbar_von      ON {DB_SCHEMA}.nachbarschaft (wahljahr, wkr_von);
CREATE INDEX IF NOT EXISTS idx_nachbar_richtung ON {DB_SCHEMA}.nachbarschaft (wahljahr, richtung);
"""


def berechne(jahr):
    sql = f"""
    DELETE FROM {DB_SCHEMA}.nachbarschaft WHERE wahljahr = {jahr};

    WITH pt AS (
        SELECT wkr_nr, geom, ST_PointOnSurface(geom) AS p
        FROM {DB_SCHEMA}.wahlkreis
        WHERE wahljahr = {jahr}
    ),
    paare AS (
        SELECT a.wkr_nr AS von,
               b.wkr_nr AS nach,
               ST_Length(ST_CollectionExtract(
                   ST_Intersection(a.geom, b.geom), 2)) AS grenze,
               degrees(ST_Azimuth(a.p, b.p))            AS az,
               ST_Distance(a.p, b.p)                    AS dist
        FROM pt a
        JOIN pt b ON a.wkr_nr <> b.wkr_nr AND ST_Intersects(a.geom, b.geom)
    )
    INSERT INTO {DB_SCHEMA}.nachbarschaft
        (wahljahr, wkr_von, wkr_nach, grenzlaenge_m, azimut_grad, richtung, distanz_m)
    SELECT {jahr}, von, nach, grenze, az,
           (ARRAY['N','NO','O','SO','S','SW','W','NW'])[
               floor((((az + 22.5)::numeric) % 360) / 45)::int + 1],
           dist
    FROM paare
    WHERE grenze >= {MIN_GRENZE_M};
    """
    run_sql(sql, label=f"nachbarschaft {jahr}")


def report():
    rows = query(f"""
        WITH grad AS (
            SELECT w.wahljahr, w.wkr_nr, count(n.wkr_nach) AS anz
            FROM {DB_SCHEMA}.wahlkreis w
            LEFT JOIN {DB_SCHEMA}.nachbarschaft n
                   ON n.wahljahr = w.wahljahr AND n.wkr_von = w.wkr_nr
            GROUP BY w.wahljahr, w.wkr_nr
        )
        SELECT wahljahr,
               round(sum(anz)/2.0)                    AS kanten,
               min(anz), max(anz), round(avg(anz), 2),
               count(*) FILTER (WHERE anz > 6)        AS ueber6,
               count(*) FILTER (WHERE anz = 0)        AS isoliert,





               round(sum(anz)/2.0) - round(sum(least(anz, 4))/2.0) AS verlust_q4,
               round(sum(anz)/2.0) - round(sum(least(anz, 6))/2.0) AS verlust_hex,
               round(sum(anz)/2.0) - round(sum(least(anz, 8))/2.0) AS verlust_q8
        FROM grad GROUP BY wahljahr ORDER BY wahljahr;
    """)
    log.info("--- Nachbarschaftsgraph ---")
    log.info("%-6s %-7s %-5s %-5s %-8s %-9s %s",
             "Jahr", "Kanten", "min", "max", "Schnitt", "ueber 6", "isoliert")
    for jahr, kanten, gmin, gmax, gavg, ueber6, isoliert, *_ in rows:
        log.info("%-6s %-7s %-5s %-5s %-8s %-9s %s",
                 jahr, kanten, gmin, gmax, gavg, ueber6, isoliert)

    log.info("--- untere Schranke fuer den Kantenverlust je Zelltyp ---")
    log.info("%-6s %-18s %-18s %s",
             "Jahr", "Quadrat (4 Nb.)", "Hexagon (6 Nb.)", "Quadrat+Diag (8 Nb.)")
    for jahr, kanten, _gmin, _gmax, _gavg, _u6, _iso, q4, hex6, q8 in rows:
        k = float(kanten)
        log.info("%-6s %-18s %-18s %s",
                 jahr,
                 f"{q4} ({100*float(q4)/k:.1f} %)",
                 f"{hex6} ({100*float(hex6)/k:.1f} %)",
                 f"{q8} ({100*float(q8)/k:.1f} %)")

    for jahr, *_ in rows:
        iso = query(f"""
            SELECT w.wkr_nr, w.wkr_name
            FROM {DB_SCHEMA}.wahlkreis w
            LEFT JOIN {DB_SCHEMA}.nachbarschaft n
                   ON n.wahljahr = w.wahljahr AND n.wkr_von = w.wkr_nr
            WHERE w.wahljahr = {jahr}
            GROUP BY w.wkr_nr, w.wkr_name
            HAVING count(n.wkr_nach) = 0
            ORDER BY w.wkr_nr;
        """)
        if iso:
            log.warning("[%s] ohne Landnachbarn: %s", jahr,
                        ", ".join(f"{nr} {name}" for nr, name in iso))

    verteilung = query(f"""
        SELECT richtung, count(*)
        FROM {DB_SCHEMA}.nachbarschaft
        GROUP BY richtung ORDER BY count(*) DESC;
    """)
    log.info("Richtungen gesamt: %s",
             ", ".join(f"{r} {n}" for r, n in verteilung))


def main():
    jahre = [int(a) for a in sys.argv[1:]] or [
        int(j) for (j,) in query(
            f"SELECT DISTINCT wahljahr FROM {DB_SCHEMA}.wahlkreis ORDER BY 1;")
    ]
    if not jahre:
        raise SystemExit("Keine Wahlkreise geladen - erst lib/db.py laufen lassen.")

    run_sql(DDL, "nachbarschaft-ddl")
    for jahr in jahre:
        log.info("[%s] berechne Nachbarschaften (Schwelle %.0f m) ...", jahr, MIN_GRENZE_M)
        berechne(jahr)
    report()


if __name__ == "__main__":
    main()
