import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import run_sql, query

DB_SCHEMA = "raum"
TABELLE   = "gemeinde_wahlkreis_wahltag"


GEHOBEN = """raum.gemeinde_ags(w.ags)"""

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gem-wkr-wahltag")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    wahljahr     SMALLINT NOT NULL,
    wahltag      DATE     NOT NULL,
    ags          CHAR(8)  NOT NULL,
    gemeindename TEXT,
    wkr_nr       SMALLINT NOT NULL,



    anteilig     BOOLEAN  NOT NULL DEFAULT false,
    herkunft     TEXT     NOT NULL,



    unsicher     BOOLEAN  NOT NULL DEFAULT false,
    PRIMARY KEY (wahljahr, ags, wkr_nr)
);

CREATE INDEX IF NOT EXISTS {TABELLE}_wkr ON {DB_SCHEMA}.{TABELLE} (wahljahr, wkr_nr);
CREATE INDEX IF NOT EXISTS {TABELLE}_ags ON {DB_SCHEMA}.{TABELLE} (wahljahr, ags);
"""


def lade(jahr, wahltag):
    run_sql(f"""
    DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE wahljahr = {jahr};



    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (wahljahr, wahltag, ags, gemeindename, wkr_nr, anteilig, herkunft)
    SELECT {jahr}, DATE '{wahltag}', b.ags, max(g.gen), b.wkr_nr,
           count(*) OVER (PARTITION BY b.ags) > 1, 'bezirk'
    FROM (SELECT DISTINCT {GEHOBEN} AS ags, w.wkr_nr
          FROM wahlergebnisse.wahlbezirk w
          WHERE w.wahljahr = {jahr} AND NOT raum.ist_sammelposten({GEHOBEN})) b
    LEFT JOIN {DB_SCHEMA}.gemeindestand_stichtag g
      ON g.stichtag = DATE '{wahltag}' AND g.ags = b.ags
    GROUP BY b.ags, b.wkr_nr
    ON CONFLICT DO NOTHING;


    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (wahljahr, wahltag, ags, gemeindename, wkr_nr, anteilig, herkunft)
    SELECT DISTINCT {jahr}, DATE '{wahltag}', a.ags, g.gen, z.wkr_nr,
           false, 'aufnahme'
    FROM {DB_SCHEMA}.gemeinde_aufnahme a
    JOIN {DB_SCHEMA}.{TABELLE} z
      ON z.wahljahr = {jahr} AND z.ags = a.ags_aufnehmend
    LEFT JOIN {DB_SCHEMA}.gemeindestand_stichtag g
      ON g.stichtag = DATE '{wahltag}' AND g.ags = a.ags
    WHERE a.wahljahr = {jahr}
    ON CONFLICT DO NOTHING;




    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (wahljahr, wahltag, ags, gemeindename, wkr_nr, anteilig, herkunft)
    SELECT DISTINCT {jahr}, DATE '{wahltag}', g.ags, g.gen, z.wkr_nr,
           false, 'gebietsuebergang'
    FROM {DB_SCHEMA}.gemeindestand_stichtag g
    JOIN {DB_SCHEMA}.gebietsuebergang u
      ON u.ebene = 'Gemeinde' AND u.ags_alt = g.ags
    JOIN {DB_SCHEMA}.{TABELLE} z
      ON z.wahljahr = {jahr} AND z.ags = u.ags_neu
    WHERE g.stichtag = DATE '{wahltag}'
      AND g.bez <> 'Gemeindefreies Gebiet'
      AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} v
                      WHERE v.wahljahr = {jahr} AND v.ags = g.ags)
    ON CONFLICT DO NOTHING;



    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (wahljahr, wahltag, ags, gemeindename, wkr_nr, anteilig, herkunft)
    SELECT DISTINCT {jahr}, DATE '{wahltag}', g.ags, g.gen, z.wkr_nr,
           false, 'gebietsuebergang'
    FROM {DB_SCHEMA}.gemeindestand_stichtag g
    JOIN {DB_SCHEMA}.gemeindestand_stichtag v
      ON v.stichtag = g.stichtag AND left(v.ags, 5) = left(g.ags, 5)
    JOIN {DB_SCHEMA}.{TABELLE} z
      ON z.wahljahr = {jahr} AND z.ags = v.ags
    WHERE g.stichtag = DATE '{wahltag}'
      AND g.bez <> 'Gemeindefreies Gebiet'
      AND left(g.ags, 5) = '07131'
      AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} x
                      WHERE x.wahljahr = {jahr} AND x.ags = g.ags)
    ON CONFLICT DO NOTHING;














    INSERT INTO {DB_SCHEMA}.{TABELLE}
        (wahljahr, wahltag, ags, gemeindename, wkr_nr, anteilig, herkunft,
         unsicher)
    SELECT DISTINCT ON (g.ags)
           {jahr}, DATE '{wahltag}', g.ags, g.gen, w.wkr_nr,
           false, 'geometrie',
           (SELECT count(*) > 1 FROM {DB_SCHEMA}.wahlkreis w2
             WHERE w2.wahljahr = {jahr} AND ST_Intersects(g.geom, w2.geom))
    FROM {DB_SCHEMA}.gemeindestand_stichtag g
    JOIN {DB_SCHEMA}.wahlkreis w
      ON w.wahljahr = {jahr} AND ST_Intersects(g.geom, w.geom)
    WHERE g.stichtag = DATE '{wahltag}'
      AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} v
                      WHERE v.wahljahr = {jahr} AND v.ags = g.ags)
    ORDER BY g.ags, ST_Area(ST_Intersection(g.geom, w.geom)) DESC
    ON CONFLICT DO NOTHING;















    DELETE FROM {DB_SCHEMA}.{TABELLE} z
    WHERE z.wahljahr = {jahr}
      AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeindestand_stichtag s
                      WHERE s.stichtag = DATE '{wahltag}' AND s.ags = z.ags);
    """, f"zuordnung {jahr}")


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT wahljahr, herkunft, count(*) AS zeilen,
               count(DISTINCT ags) AS gemeinden
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1, 2 ORDER BY 1, 3 DESC;
    """):
        log.info("  %s %-18s %6s Zeilen, %6s Gemeinden", *zeile)


    log.info("--- Geometrisch zugeteilt, Gebiet beruehrt mehrere WK ---")
    treffer = query(f"""
        SELECT wahljahr, count(*) FILTER (WHERE unsicher),
               count(*) FILTER (WHERE herkunft = 'geometrie')
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 1;
    """)
    for jahr, unsicher, aus_liste in treffer:
        log.info("  %s: %s von %s geometrisch zugeteilten Zeilen sind unsicher",
                 jahr, unsicher, aus_liste)

    if any(int(z[1]) for z in treffer):
        log.info("--- Welche das sind ---")
        for zeile in query(f"""
            SELECT wahljahr, ags, coalesce(gemeindename, '-'), wkr_nr
            FROM {DB_SCHEMA}.{TABELLE} WHERE unsicher
            ORDER BY wahljahr, ags LIMIT 30;
        """):
            log.info("  %s %s %-30s WK %s", *zeile)


    log.info("--- Deckt sich die Zuordnung mit dem Gebietsstand? ---")
    for zeile in query(f"""
        WITH wt AS (SELECT substring(bezug from '[0-9]+')::int AS jahr, datum
                    FROM zeit.stichtag WHERE art = 'wahltag')
        SELECT wt.jahr,
          (SELECT count(*) FROM {DB_SCHEMA}.gemeindestand_stichtag g
           WHERE g.stichtag = wt.datum) AS im_gebietsstand,
          (SELECT count(DISTINCT ags) FROM {DB_SCHEMA}.{TABELLE} z
           WHERE z.wahljahr = wt.jahr) AS zugeordnet,
          (SELECT count(*) FROM {DB_SCHEMA}.gemeindestand_stichtag g
           WHERE g.stichtag = wt.datum
             AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} z
                             WHERE z.wahljahr = wt.jahr AND z.ags = g.ags)) AS fehlt,
          (SELECT count(DISTINCT z.ags) FROM {DB_SCHEMA}.{TABELLE} z
           WHERE z.wahljahr = wt.jahr
             AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeindestand_stichtag g
                             WHERE g.stichtag = wt.datum AND g.ags = z.ags))
                                                                  AS ueberzaehlig
        FROM wt ORDER BY 1;
    """):
        jahr, soll, ist, fehlt, ueber = zeile
        if int(fehlt) == 0 and int(ueber) == 0:
            marke = "deckt sich"
        else:
            teile = []
            if int(fehlt):
                teile.append(f"{fehlt} OHNE ZUORDNUNG")
            if int(ueber):
                teile.append(f"{ueber} NICHT IM GEBIETSSTAND")
            marke = ", ".join(teile)
        log.info("  %s: %s Gebiete am Wahltag, %s zugeordnet  %s",
                 jahr, soll, ist, marke)


    ueberzaehlig = query(f"""
        WITH wt AS (SELECT substring(bezug from '[0-9]+')::int AS jahr, datum
                    FROM zeit.stichtag WHERE art = 'wahltag')
        SELECT z.wahljahr, z.ags, coalesce(z.gemeindename, '-'), z.herkunft
        FROM {DB_SCHEMA}.{TABELLE} z
        JOIN wt ON wt.jahr = z.wahljahr
        WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeindestand_stichtag g
                          WHERE g.stichtag = wt.datum AND g.ags = z.ags)
        GROUP BY 1, 2, 3, 4 ORDER BY 1, 2;
    """)
    if ueberzaehlig:
        log.info("--- Zugeordnet, aber nicht im Gebietsstand ---")
        for zeile in ueberzaehlig:
            log.info("  %s %s %-30s (%s)", *zeile)


    log.info("--- Liegen die aufgenommenen Gemeinden im geerbten Wahlkreis? ---")
    for zeile in query(f"""
        SELECT z.wahljahr, count(*),
               count(*) FILTER (WHERE anteil < 50)  AS widerspruch,
               round(min(anteil)::numeric, 1)       AS schwaechster
        FROM (
            SELECT z.wahljahr, z.ags,
                   100 * ST_Area(ST_Intersection(g.geom, w.geom))
                       / nullif(ST_Area(g.geom), 0) AS anteil
            FROM {DB_SCHEMA}.{TABELLE} z
            JOIN zeit.stichtag t
              ON t.art = 'wahltag' AND t.bezug = 'Wahl ' || z.wahljahr::text
            JOIN {DB_SCHEMA}.gemeindestand_stichtag g
              ON g.stichtag = t.datum AND g.ags = z.ags
            JOIN {DB_SCHEMA}.wahlkreis w
              ON w.wahljahr = z.wahljahr AND w.wkr_nr = z.wkr_nr
            WHERE z.herkunft = 'aufnahme'
        ) z GROUP BY 1 ORDER BY 1;
    """):
        jahr, ges, wider, min_anteil = zeile
        marke = ("kein Widerspruch" if int(wider) == 0
                 else f"{wider} WIDERSPRECHEN")
        log.info("  %s: %s geprueft, schwaechste Ueberdeckung %s %% - %s",
                 jahr, ges, min_anteil, marke)

    widerspruch = query(f"""
        SELECT z.wahljahr, z.ags, coalesce(z.gemeindename, '-'), z.wkr_nr,
               round((100 * ST_Area(ST_Intersection(g.geom, w.geom))
                          / nullif(ST_Area(g.geom), 0))::numeric, 1)
        FROM {DB_SCHEMA}.{TABELLE} z
        JOIN zeit.stichtag t
          ON t.art = 'wahltag' AND t.bezug = 'Wahl ' || z.wahljahr::text
        JOIN {DB_SCHEMA}.gemeindestand_stichtag g
          ON g.stichtag = t.datum AND g.ags = z.ags
        JOIN {DB_SCHEMA}.wahlkreis w
          ON w.wahljahr = z.wahljahr AND w.wkr_nr = z.wkr_nr
        WHERE z.herkunft = 'aufnahme'
          AND 100 * ST_Area(ST_Intersection(g.geom, w.geom))
                  / nullif(ST_Area(g.geom), 0) < 50
        ORDER BY 5;
    """)
    for zeile in widerspruch:
        log.warning("  %s %s %-26s geerbt WK %s, liegt dort nur zu %s %%", *zeile)

    log.info("--- Geteilte Gemeinden (anteilig) ---")
    for zeile in query(f"""
        SELECT wahljahr, count(DISTINCT ags) AS gemeinden, count(*) AS teile
        FROM {DB_SCHEMA}.{TABELLE} WHERE anteilig GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Gemeinden in zusammen %s Wahlkreisteilen", *zeile)

    log.info("--- Was fehlt noch? ---")
    for zeile in query(f"""
        WITH wt AS (SELECT substring(bezug from '[0-9]+')::int AS jahr, datum
                    FROM zeit.stichtag WHERE art = 'wahltag')
        SELECT wt.jahr, g.ags, g.gen, g.bez
        FROM wt JOIN {DB_SCHEMA}.gemeindestand_stichtag g ON g.stichtag = wt.datum
        WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} z
                          WHERE z.wahljahr = wt.jahr AND z.ags = g.ags)
        ORDER BY 1, 2 LIMIT 10;
    """):
        log.info("  %s %s %-24s %s", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "verwerfen")
        log.warning("Tabelle %s verworfen.", TABELLE)

    run_sql(DDL, "ddl")
    for jahr, wahltag in query("""
        SELECT substring(bezug from '[0-9]+')::int, datum
        FROM zeit.stichtag WHERE art = 'wahltag' ORDER BY datum;
    """):
        log.info("%s: Wahltag %s", jahr, wahltag)
        lade(jahr, wahltag)
    report()


if __name__ == "__main__":
    main()
