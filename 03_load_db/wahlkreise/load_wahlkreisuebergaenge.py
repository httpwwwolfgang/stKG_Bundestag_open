import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import DB_SCHEMA as WK_SCHEMA, run_sql, query

DB_SCHEMA = "raum"
TABELLE     = "wahlkreisuebergang"
TABELLE_GEM = "wahlkreisuebergang_gemeinde"


UEBERGAENGE = [(2013, 2017), (2017, 2021)]


AMTLICH_GEAENDERT = {
    2017: {

        18, 22,
        56, 57, 58, 59, 60, 61, 62,
        189, 190, 191, 194, 195, 196,
        205, 206,
        214, 215, 221, 223, 224, 226,
        216, 227, 228, 229, 230, 238, 239,
        260, 265,

        12, 13,
    },
    2021: {

        60, 61, 135, 136, 137, 228, 230, 233, 234, 242, 243, 253, 254,

        190, 192, 195, 196,
    },
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wk-uebergang")


DDL = f"""
CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    von_wahljahr      SMALLINT NOT NULL,
    von_wkr_nr        SMALLINT,
    nach_wahljahr     SMALLINT NOT NULL,
    nach_wkr_nr       SMALLINT,
    kontinuitaet      TEXT     NOT NULL,
    nummer_geaendert  BOOLEAN,
    name_geaendert    BOOLEAN,
    gemeinden_ab      INTEGER,
    gemeinden_zu      INTEGER,
    amtlich_geaendert BOOLEAN,
    herkunft          TEXT     NOT NULL,
    CHECK (von_wkr_nr IS NOT NULL OR nach_wkr_nr IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS {TABELLE}_key
    ON {DB_SCHEMA}.{TABELLE}
       (von_wahljahr, nach_wahljahr,
        coalesce(von_wkr_nr, -1), coalesce(nach_wkr_nr, -1));

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE_GEM} (
    von_wahljahr   SMALLINT NOT NULL,
    von_wkr_nr     SMALLINT,
    nach_wahljahr  SMALLINT NOT NULL,
    nach_wkr_nr    SMALLINT,


    ags            CHAR(8)  NOT NULL,


    richtung       TEXT     NOT NULL,
    CHECK (richtung IN ('ab', 'zu'))
);

CREATE UNIQUE INDEX IF NOT EXISTS {TABELLE_GEM}_key
    ON {DB_SCHEMA}.{TABELLE_GEM}
       (von_wahljahr, nach_wahljahr,
        coalesce(von_wkr_nr, -1), coalesce(nach_wkr_nr, -1), ags, richtung);

CREATE INDEX IF NOT EXISTS {TABELLE_GEM}_ags
    ON {DB_SCHEMA}.{TABELLE_GEM} (ags);
"""


def hat_zuordnung(jahr):
    zeilen = query(f"""
        SELECT count(*) FROM raum.gemeinde_wahlkreis_wahltag WHERE wahljahr = {jahr};
    """)
    return bool(zeilen) and int(zeilen[0][0]) > 0


def gebietsstand(jahr):
    zeilen = query(f"""
        SELECT datum FROM zeit.stichtag
        WHERE art = 'wahltag' AND bezug = 'Wahl {jahr}';
    """)
    if not zeilen:
        raise SystemExit(f"Kein wahltag fuer Wahl {jahr}")
    return zeilen[0][0]


def _mengen_cte(von, nach, stand_von, stand_nach):
    return f"""
        WITH RECURSIVE






        gemeindefrei AS (
            SELECT ags FROM roh_gemeinden.gv100ad_gemeinde
             WHERE textkennzeichen IN ('65', '66')
            UNION
            SELECT ags FROM raum.gemeindestand
             WHERE bez = 'Gemeindefreies Gebiet'



            UNION
            SELECT ags FROM raum.gemeinde_wahlkreis_wahltag
             WHERE raum.ist_sammelposten(ags)
        ),

        wechsel AS (
            SELECT DISTINCT ags_alt, ags_neu
            FROM raum.gebietsuebergang
            WHERE wirksam > DATE '{stand_von}' AND wirksam <= DATE '{stand_nach}'
              AND ags_alt <> ags_neu
              AND art IN ('eingliederung', 'zusammenschluss', 'schluesselaenderung')
        ),

        kette (ags_alt, ags_neu, tiefe) AS (
            SELECT ags_alt, ags_neu, 1 FROM wechsel
            UNION
            SELECT k.ags_alt, w.ags_neu, k.tiefe + 1
            FROM kette k JOIN wechsel w ON w.ags_alt = k.ags_neu
            WHERE k.tiefe < 5
        ),
        endziel AS (
            SELECT DISTINCT ON (ags_alt) ags_alt, ags_neu
            FROM kette ORDER BY ags_alt, tiefe DESC
        ),

        menge_alt AS (
            SELECT gw.wkr_nr, coalesce(e.ags_neu, gw.ags) AS ags
            FROM raum.gemeinde_wahlkreis_wahltag gw
            LEFT JOIN endziel e ON e.ags_alt = gw.ags
            WHERE gw.wahljahr = {von}
              AND gw.ags NOT IN (SELECT ags FROM gemeindefrei)
              AND coalesce(e.ags_neu, gw.ags) NOT IN (SELECT ags FROM gemeindefrei)
        ),
        menge_neu AS (
            SELECT wkr_nr, ags FROM raum.gemeinde_wahlkreis_wahltag
            WHERE wahljahr = {nach}
              AND ags NOT IN (SELECT ags FROM gemeindefrei)
        ),


        namenspaar AS (
            SELECT a.wkr_nr AS nr_alt, b.wkr_nr AS nr_neu
            FROM {WK_SCHEMA}.wahlkreis a
            JOIN {WK_SCHEMA}.wahlkreis b
              ON b.wahljahr = {nach} AND b.wkr_name = a.wkr_name
            WHERE a.wahljahr = {von}
        ),
        ueberschneidung AS (
            SELECT a.wkr_nr AS nr_alt, b.wkr_nr AS nr_neu, count(*) AS gemeinsam,
                   row_number() OVER (PARTITION BY a.wkr_nr ORDER BY count(*) DESC) AS rang
            FROM menge_alt a JOIN menge_neu b ON b.ags = a.ags
            GROUP BY a.wkr_nr, b.wkr_nr
        ),
        paar AS (
            SELECT a.wkr_nr AS nr_alt,
                   coalesce(n.nr_neu, u.nr_neu) AS nr_neu,
                   (n.nr_neu IS NOT NULL)       AS aus_name
            FROM (SELECT DISTINCT wkr_nr FROM menge_alt) a
            LEFT JOIN namenspaar n ON n.nr_alt = a.wkr_nr
            LEFT JOIN ueberschneidung u ON u.nr_alt = a.wkr_nr AND u.rang = 1
        ),
"""


def lade(von, nach):
    stand_von, stand_nach = gebietsstand(von), gebietsstand(nach)
    amtlich = AMTLICH_GEAENDERT.get(nach, set())
    amtlich_sql = ", ".join(str(n) for n in sorted(amtlich)) or "NULL"

    run_sql(f"""
        DELETE FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach};
        DELETE FROM {DB_SCHEMA}.{TABELLE_GEM}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach};

        """ + _mengen_cte(von, nach, stand_von, stand_nach) + f"""
        bilanz AS (
            SELECT p.nr_alt, p.nr_neu, p.aus_name,
                   (SELECT count(DISTINCT x.ags) FROM menge_alt x WHERE x.wkr_nr = p.nr_alt
                     AND NOT EXISTS (SELECT 1 FROM menge_neu y
                                     WHERE y.wkr_nr = p.nr_neu AND y.ags = x.ags)) AS ab,
                   (SELECT count(DISTINCT y.ags) FROM menge_neu y WHERE y.wkr_nr = p.nr_neu
                     AND NOT EXISTS (SELECT 1 FROM menge_alt x
                                     WHERE x.wkr_nr = p.nr_alt AND x.ags = y.ags)) AS zu,
                   (SELECT count(DISTINCT x.ags) FROM menge_alt x JOIN menge_neu y
                     ON y.ags = x.ags AND y.wkr_nr = p.nr_neu
                    WHERE x.wkr_nr = p.nr_alt) AS gemeinsam
            FROM paar p
        )
        INSERT INTO {DB_SCHEMA}.{TABELLE}
            (von_wahljahr, von_wkr_nr, nach_wahljahr, nach_wkr_nr, kontinuitaet,
             nummer_geaendert, name_geaendert, gemeinden_ab, gemeinden_zu,
             amtlich_geaendert, herkunft)
        SELECT {von}, b.nr_alt, {nach}, b.nr_neu,
               CASE WHEN b.gemeinsam = 0            THEN 'ohne_entsprechung'
                    WHEN b.ab = 0 AND b.zu = 0      THEN 'identisch'
                    WHEN b.ab = 0                   THEN 'nur_zugang'
                    WHEN b.zu = 0                   THEN 'nur_abgang'
                    ELSE                                 'austausch' END,
               b.nr_alt IS DISTINCT FROM b.nr_neu,
               wa.wkr_name IS DISTINCT FROM wn.wkr_name,
               b.ab, b.zu,
               b.nr_neu IN ({amtlich_sql}),
               CASE WHEN b.aus_name THEN 'zuordnung ueber amtlichen Wahlkreisnamen'
                    ELSE 'zuordnung ueber groesste gemeinsame Gemeindemenge' END
        FROM bilanz b
        LEFT JOIN {WK_SCHEMA}.wahlkreis wa ON (wa.wahljahr, wa.wkr_nr) = ({von}, b.nr_alt)
        LEFT JOIN {WK_SCHEMA}.wahlkreis wn ON (wn.wahljahr, wn.wkr_nr) = ({nach}, b.nr_neu);
    """, f"uebergang {von}->{nach}")


    run_sql(_mengen_cte(von, nach, stand_von, stand_nach) + f"""
        wechselnde AS (
            SELECT DISTINCT p.nr_alt, p.nr_neu, x.ags, 'ab' AS richtung
            FROM paar p JOIN menge_alt x ON x.wkr_nr = p.nr_alt
            WHERE NOT EXISTS (SELECT 1 FROM menge_neu y
                              WHERE y.wkr_nr = p.nr_neu AND y.ags = x.ags)
            UNION ALL
            SELECT DISTINCT p.nr_alt, p.nr_neu, y.ags, 'zu'
            FROM paar p JOIN menge_neu y ON y.wkr_nr = p.nr_neu
            WHERE NOT EXISTS (SELECT 1 FROM menge_alt x
                              WHERE x.wkr_nr = p.nr_alt AND x.ags = y.ags)
        )
        INSERT INTO {DB_SCHEMA}.{TABELLE_GEM}
            (von_wahljahr, von_wkr_nr, nach_wahljahr, nach_wkr_nr, ags, richtung)
        SELECT {von}, w.nr_alt, {nach}, w.nr_neu, w.ags, w.richtung
        FROM wechselnde w;
    """, f"gemeinden je uebergang {von}->{nach}")


def report(von, nach):
    log.info("--- %s -> %s ---", von, nach)
    for zeile in query(f"""
        SELECT kontinuitaet, herkunft, count(*)
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach}
        GROUP BY 1, 2 ORDER BY 3 DESC;
    """):
        log.info("  %-22s %-28s %s", *zeile)


    zeilen = query(f"""
        SELECT count(*) FILTER (WHERE amtlich_geaendert AND kontinuitaet <> 'identisch'),
               count(*) FILTER (WHERE amtlich_geaendert AND kontinuitaet =  'identisch'),
               count(*) FILTER (WHERE NOT amtlich_geaendert AND kontinuitaet <> 'identisch')
        FROM {DB_SCHEMA}.{TABELLE}
        WHERE von_wahljahr = {von} AND nach_wahljahr = {nach} AND nach_wkr_nr IS NOT NULL;
    """)
    if zeilen:
        treffer, amtlich_ohne_befund, befund_ohne_amtlich = zeilen[0]
        log.info("  Gegenprobe: %s amtlich und im Mengenvergleich, " "%s amtlich ohne Befund, %s Befund ohne amtliche Nennung",
                 treffer, amtlich_ohne_befund, befund_ohne_amtlich)


    zeilen = query(f"""
        WITH anteil AS (
            SELECT u.von_wkr_nr, u.nach_wkr_nr, u.herkunft,
                   ST_Area(ST_Intersection(a.geom, b.geom)) / ST_Area(a.geom) AS q
            FROM {DB_SCHEMA}.{TABELLE} u
            JOIN {WK_SCHEMA}.wahlkreis a
              ON (a.wahljahr, a.wkr_nr) = (u.von_wahljahr, u.von_wkr_nr)
            JOIN {WK_SCHEMA}.wahlkreis b
              ON (b.wahljahr, b.wkr_nr) = (u.nach_wahljahr, u.nach_wkr_nr)
            WHERE u.von_wahljahr = {von} AND u.nach_wahljahr = {nach}
        )
        SELECT count(*) FILTER (WHERE q >= 0.95),
               count(*) FILTER (WHERE q >= 0.80 AND q < 0.95),
               count(*) FILTER (WHERE q <  0.80),
               round(min(q)::numeric, 3)
        FROM anteil;
    """)
    if zeilen:
        log.info("  Flaechendeckung der Paare: %s ab 95%%, %s 80-95%%, " "%s unter 80%% (kleinster Wert %s)", *zeilen[0])


def main():
    if "--neu" in sys.argv[1:]:
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "tabelle verwerfen")
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE_GEM} CASCADE;", "tabelle verwerfen")
        log.warning("Tabellen %s.%s und %s verworfen.", DB_SCHEMA, TABELLE, TABELLE_GEM)

    run_sql(DDL, "ddl")

    for von, nach in UEBERGAENGE:
        if not hat_zuordnung(von):
            log.warning("%s -> %s: keine Gemeindezuordnung fuer %s - uebersprungen",
                        von, nach, von)
            continue
        if not hat_zuordnung(nach):
            log.warning("%s -> %s: keine Gemeindezuordnung fuer %s - uebersprungen",
                        von, nach, nach)
            continue
        lade(von, nach)
        report(von, nach)


if __name__ == "__main__":
    main()
