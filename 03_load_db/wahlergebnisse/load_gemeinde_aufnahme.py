import sys
import logging
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query


def sql_ueber_datei(sql, label):
    pfad = Path(tempfile.gettempdir()) / f"aufn_{abs(hash(label))}.sql"
    pfad.write_text("SET client_encoding TO 'UTF8';\n" + sql, encoding="utf-8")
    try:
        run_sql_file(pfad, label=label)
    finally:
        pfad.unlink(missing_ok=True)

DB_SCHEMA  = "raum"
ERG_SCHEMA = "wahlergebnisse"
TABELLE    = "gemeinde_aufnahme"


AUFNAHME_2013 = {
    "01061111": "01061036",
    "07231021": "07231080",
    "07232052": "07232021",
}

AUFNAHME_2017 = {
    "01061111": "01061036",
    "01058158": "01058119",
    "01061005": "01061115",
    "07231021": "07231080",
    "07232052": "07232021",
}


AUFNAHME_2021 = {
    "01051033": "01051093",
    "01051050": "01051079",
    "01051054": "01051015",
    "01051104": "01051002",
    "01051126": "01051001",
    "01054048": "01054142",
    "01054157": "01054105",
    "01058158": "01058119",
    "01061002": "01061025",
    "01061005": "01061115",
    "01061008": "01061059",
    "01061020": "01061095",
    "01061060": "01061063",
    "01061089": "01061028",
    "01061102": "01061062",
    "01061103": "01061049",
    "01061111": "01061036",
    "07131021": "07131005",
    "07132027": "07132094",
    "07132029": "07132016",
    "07132056": "07132022",
    "07132058": "07132092",
    "07132068": "07132019",
    "07132077": "07132007",
    "07132102": "07132013",
    "07132103": "07132032",
    "07132110": "07132092",
    "07133016": "07133202",
    "07133042": "07133202",
    "07133047": "07133205",
    "07133113": "07133205",
    "07133203": "07133202",
    "07137063": "07137077",
    "07138010": "07138047",
    "07138027": "07138048",
    "07231021": "07231080",
    "07231023": "07231051",
    "07231050": "07231051",
    "07231091": "07231046",
    "07231116": "07231026",
    "07232001": "07232110",
    "07232003": "07232132",
    "07232004": "07232131",
    "07232008": "07232110",
    "07232012": "07232068",
    "07232017": "07232079",
    "07232022": "07232080",
    "07232032": "07232045",
    "07232035": "07232135",
    "07232036": "07232009",
    "07232038": "07232102",
    "07232041": "07232110",
    "07232042": "07232067",
    "07232046": "07232015",
    "07232047": "07232005",
    "07232049": "07232064",
    "07232056": "07232068",
    "07232059": "07232072",
    "07232066": "07232110",
    "07232071": "07232313",
    "07232073": "07232064",
    "07232083": "07232009",
    "07232084": "07232068",
    "07232085": "07232068",
    "07232089": "07232072",
    "07232090": "07232102",
    "07232092": "07232098",
    "07232096": "07232072",
    "07232097": "07232091",
    "07232112": "07232067",
    "07232116": "07232064",
    "07232120": "07232119",
    "07232124": "07232045",
    "07232127": "07232110",
    "07232128": "07232005",
    "07232129": "07232113",
    "07232130": "07232110",
    "07232133": "07232013",
    "07232138": "07232088",
    "07232203": "07232210",
    "07232207": "07232308",
    "07232264": "07232322",
    "07232276": "07232216",
    "07232284": "07232216",
    "07232291": "07232322",
    "07232298": "07232213",
    "07232306": "07232313",
    "07232309": "07232220",
    "07232315": "07232262",
    "07232327": "07232216",
    "07232331": "07232113",
    "07232502": "07232009",
    "07233216": "07233226",
    "07233243": "07233226",
    "07235044": "07235021",
    "07235129": "07235038",
    "07333068": "07333008",
    "07333072": "07333067",
    "07336035": "07336012",
    "07336065": "07336075",
    "07336072": "07336042",
    "07337013": "07337008",
    "13071017": "13071006",
    "13071064": "13071089",
    "13072034": "13072118",
    "13072037": "13072107",
    "13072076": "13072107",
    "13072097": "13072105",
    "13072102": "13072118",
    "13073039": "13073020",
    "13074070": "13074043",
    "16061002": "16061024",
    "16063037": "16063058",
    "16064007": "16064009",
    "16064021": "16064045",
    "16064027": "16064045",
    "16064062": "16064064",
    "16074046": "16074029",
    "16074055": "16074073",
    "16074058": "16074094",
    "16074061": "16074028",
    "16074068": "16074028",
    "16074071": "16074108",
    "16074082": "16074001",
    "16075047": "16075127",
    "16075069": "16075081",
    "16075079": "16075127",
    "16075087": "16075039",
    "16075101": "16075081",
    "16075105": "16075075",
    "16075114": "16075057",
    "16076028": "16076006",
    "16076038": "16076039",
    "16076067": "16076036",

    "01054039": "01054050",
    "07232121": "07232064",
    "07232117": "07232088",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aufnahme")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    wahljahr         SMALLINT NOT NULL,
    ags              CHAR(8)  NOT NULL,
    gemeindename     TEXT,
    ags_aufnehmend   CHAR(8)  NOT NULL,
    name_aufnehmend  TEXT,
    abstand_m        DOUBLE PRECISION,
    eigener_bezirk   BOOLEAN,
    herkunft         TEXT     NOT NULL,
    PRIMARY KEY (wahljahr, ags)
);

CREATE INDEX IF NOT EXISTS {TABELLE}_auf_idx
    ON {DB_SCHEMA}.{TABELLE} (wahljahr, ags_aufnehmend);
"""


def lade():
    for jahr, zuordnung in ((2013, AUFNAHME_2013),
                            (2017, AUFNAHME_2017),
                            (2021, AUFNAHME_2021)):
        werte = ",\n        ".join(f"('{a}','{z}')" for a, z in zuordnung.items())
        sql_ueber_datei(f"""
            DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE wahljahr = {jahr};

            INSERT INTO {DB_SCHEMA}.{TABELLE}
                (wahljahr, ags, gemeindename, ags_aufnehmend, name_aufnehmend,
                 abstand_m, eigener_bezirk, herkunft)
            SELECT {jahr}, v.ags, g.gen, v.ziel, a.gen,
                   round(ST_Distance(g.geom, a.geom)),
                   EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
                           WHERE w.wahljahr = {jahr} AND w.ags = v.ags),
                   '{"Bezirksname der Ergebnisdatei" if jahr == 2021
                     else "Leitband, Feld Name"}'
            FROM (VALUES
            {werte}
            ) AS v(ags, ziel)
            LEFT JOIN {DB_SCHEMA}.gemeindestand_stichtag g
              ON g.stichtag = (SELECT datum FROM zeit.stichtag WHERE art='wahltag' AND bezug='Wahl {jahr}') AND g.ags = v.ags
            LEFT JOIN {DB_SCHEMA}.gemeindestand_stichtag a
              ON a.stichtag = (SELECT datum FROM zeit.stichtag WHERE art='wahltag' AND bezug='Wahl {jahr}') AND a.ags = v.ziel;
        """, f"aufnahme {jahr}")
        log.info("%s: %s Zuordnungen", jahr, len(zuordnung))


    aus_kennziffer()
    aus_zusammenlegung()
    aus_fusion()


def aus_kennziffer():
    sql_ueber_datei(f"""
        INSERT INTO {DB_SCHEMA}.{TABELLE}
            (wahljahr, ags, gemeindename, ags_aufnehmend, name_aufnehmend,
             abstand_m, eigener_bezirk, herkunft)
        SELECT DISTINCT ON (ab.wahljahr, ab.ags)
               ab.wahljahr, ab.ags, g.gen, auf.ags, a.gen,
               round(ST_Distance(g.geom, a.geom)),
               true,
               'Kennziffer nach Par. 68 BWO (Feld EF7)'
        FROM {ERG_SCHEMA}.wahlbezirk ab
        JOIN {ERG_SCHEMA}.wahlbezirk auf
          ON  auf.wahljahr          = ab.wahljahr
          AND auf.kreis             = ab.kreis
          AND auf.zusammenlegung_id = ab.zusammenlegung_id
          AND auf.aufnehmend
        JOIN zeit.stichtag zt
          ON zt.art = 'wahltag' AND zt.bezug = 'Wahl ' || ab.wahljahr::text
        LEFT JOIN {DB_SCHEMA}.gemeindestand_stichtag g
          ON g.stichtag = zt.datum AND g.ags = ab.ags
        LEFT JOIN {DB_SCHEMA}.gemeindestand_stichtag a
          ON a.stichtag = zt.datum AND a.ags = auf.ags
        WHERE ab.abgebend
          AND ab.ags <> auf.ags
          AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} v
                          WHERE v.wahljahr = ab.wahljahr AND v.ags = ab.ags)
        ORDER BY ab.wahljahr, ab.ags, auf.ags;
    """, "aufnahme aus kennziffer")

    for zeile in query(f"""
        SELECT wahljahr, count(*) FROM {DB_SCHEMA}.{TABELLE}
        WHERE herkunft LIKE 'Kennziffer%' GROUP BY 1 ORDER BY 1;
    """):
        log.info("%s: %s weitere ueber die Kennziffer", *zeile)


def aus_zusammenlegung():
    sql_ueber_datei(f"""
        INSERT INTO {DB_SCHEMA}.{TABELLE}
            (wahljahr, ags, gemeindename, ags_aufnehmend, name_aufnehmend,
             abstand_m, eigener_bezirk, herkunft)
        SELECT DISTINCT ON (zt.jahr, g.ags)
               zt.jahr, g.ags, g.gen, a.ags, a.gen,
               round(ST_Distance(g.geom, a.geom)),
               false,
               'Zusammenlegung ganzer Verbandsgemeinde (VG-Schluessel im ARS)'
        FROM (SELECT substring(bezug from '[0-9]+')::int AS jahr, datum
              FROM zeit.stichtag WHERE art = 'wahltag') zt


        JOIN {DB_SCHEMA}.gemeindestand_stichtag a
          ON a.stichtag = zt.datum
         AND EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
                     WHERE w.wahljahr = zt.jahr AND w.ags = a.ags
                       AND w.gemeindename ILIKE '%zusammengelegt%')




        JOIN {DB_SCHEMA}.gemeindestand_stichtag g
          ON g.stichtag = zt.datum
         AND g.ags <> a.ags
         AND g.bez <> 'Gemeindefreies Gebiet'
         AND left(g.ars, 9) = left(a.ars, 9)
         AND NOT EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
                         WHERE w.wahljahr = zt.jahr AND w.ags = g.ags)
        WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} v
                          WHERE v.wahljahr = zt.jahr AND v.ags = g.ags)
        ORDER BY zt.jahr, g.ags, a.ags;
    """, "aufnahme aus zusammenlegung")

    for zeile in query(f"""
        SELECT wahljahr, count(*), string_agg(DISTINCT name_aufnehmend, ', ')
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE herkunft LIKE 'Zusammenlegung%' GROUP BY 1 ORDER BY 1;
    """):
        log.info("%s: %s Gemeinden einer zusammengelegten VG -> %s", *zeile)


def aus_fusion():
    sql_ueber_datei(f"""
        INSERT INTO {DB_SCHEMA}.{TABELLE}
            (wahljahr, ags, gemeindename, ags_aufnehmend, name_aufnehmend,
             abstand_m, eigener_bezirk, herkunft)
        SELECT zt.jahr, g.ags, g.gen, u.ags_neu,
               coalesce(u.name_neu, (SELECT min(w.gemeindename)
                                     FROM {ERG_SCHEMA}.wahlbezirk w
                                     WHERE w.wahljahr = zt.jahr
                                       AND w.ags = u.ags_neu)),
               0,
               false,
               'Fusion vor dem Wahltag (raum.gebietsuebergang)'
        FROM (SELECT substring(bezug from '[0-9]+')::int AS jahr, datum
              FROM zeit.stichtag WHERE art = 'wahltag') zt
        JOIN {DB_SCHEMA}.gemeindestand_stichtag g
          ON g.stichtag = zt.datum

         AND g.bez <> 'Gemeindefreies Gebiet'
         AND NOT EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
                         WHERE w.wahljahr = zt.jahr AND w.ags = g.ags)
        JOIN {DB_SCHEMA}.gebietsuebergang u
          ON u.ags_alt = g.ags
         AND u.ags_neu <> g.ags

         AND EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
                     WHERE w.wahljahr = zt.jahr AND w.ags = u.ags_neu)
        WHERE NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} v
                          WHERE v.wahljahr = zt.jahr AND v.ags = g.ags)


          AND (SELECT count(DISTINCT u2.ags_neu)
               FROM {DB_SCHEMA}.gebietsuebergang u2
               WHERE u2.ags_alt = g.ags AND u2.ags_neu <> g.ags
                 AND EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
                             WHERE w.wahljahr = zt.jahr
                               AND w.ags = u2.ags_neu)) = 1;
    """, "aufnahme aus fusion")

    for zeile in query(f"""
        SELECT wahljahr, count(*), string_agg(DISTINCT name_aufnehmend, ', ')
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE herkunft LIKE 'Fusion%' GROUP BY 1 ORDER BY 1;
    """):
        log.info("%s: %s Gemeinden mit fusioniertem Nachfolger -> %s", *zeile)


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT herkunft, count(*), round(avg(abstand_m)) AS schnitt_m,
               max(abstand_m) AS max_m
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 2 DESC;
    """):
        log.info("  %-34s %4s Zeilen, Abstand im Schnitt %s m, hoechstens %s m",
                 *zeile)

    log.info("--- Wie viele Gemeinden bleiben offen? ---")
    for zeile in query(f"""
        WITH ohne AS (
            SELECT s.ags, s.gen, s.flaeche_km2
            FROM {DB_SCHEMA}.gemeindestand_stichtag s
            WHERE s.stichtag = DATE '2021-09-26'
              AND s.bez <> 'Gemeindefreies Gebiet'
              AND NOT EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
                              WHERE w.wahljahr = 2021
                                AND raum.gemeinde_ags(w.ags) = s.ags)
        )
        SELECT count(*) AS ohne_bezirk,
               count(*) FILTER (WHERE a.ags IS NOT NULL) AS zugeordnet,
               count(*) FILTER (WHERE a.ags IS NULL)     AS offen,
               round(sum(o.flaeche_km2) FILTER (WHERE a.ags IS NULL)::numeric,1)
                                                          AS km2_offen
        FROM ohne o
        LEFT JOIN {DB_SCHEMA}.{TABELLE} a
               ON a.wahljahr = 2021 AND a.ags = o.ags;
    """):
        log.info("  %s ohne Bezirk, %s zugeordnet, %s offen (%s km2)", *zeile)

    log.info("--- Die verbleibenden offenen Faelle ---")
    for zeile in query(f"""
        SELECT s.ags, s.gen, round(s.flaeche_km2::numeric,1),
               CASE WHEN left(s.ags,5) = '03153' THEN 'G10 Langelsheim'
                    WHEN left(s.ags,5) = '07131' THEN 'G5 Ahrtal'
                    ELSE 'ungeklaert' END
        FROM {DB_SCHEMA}.gemeindestand_stichtag s
        WHERE s.stichtag = DATE '2021-09-26' AND s.bez <> 'Gemeindefreies Gebiet'
          AND NOT EXISTS (SELECT 1 FROM {ERG_SCHEMA}.wahlbezirk w
                          WHERE w.wahljahr = 2021
                            AND raum.gemeinde_ags(w.ags) = s.ags)
          AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.{TABELLE} a
                          WHERE a.wahljahr = 2021 AND a.ags = s.ags)
        ORDER BY 4, 3 DESC;
    """):
        log.info("  %s %-30s %6s km2  %s", *zeile)

    log.info("--- Probe: liegt eine Zuordnung weiter als 2 km entfernt? ---")
    for zeile in query(f"""
        SELECT ags, gemeindename, name_aufnehmend, abstand_m
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE abstand_m > 2000 ORDER BY abstand_m DESC LIMIT 10;
    """):
        log.info("  %s %-24s -> %-24s %s m", *zeile)


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;",
                "tabelle verwerfen")
        log.warning("Tabelle %s.%s verworfen.", DB_SCHEMA, TABELLE)

    run_sql(DDL, "ddl")
    lade()
    report()


if __name__ == "__main__":
    main()
