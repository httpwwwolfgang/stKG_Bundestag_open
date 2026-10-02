import csv
import sys
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import DB_SCHEMA as WK_SCHEMA, run_sql, run_sql_file, query

DB_SCHEMA   = "raum"
META_SCHEMA = "meta"
STAMM       = "gv100ad_gemeinde"

DATEN = Path(__file__).resolve().parents[4] / "Daten" / "Wahlkreise" / "Gemeindezuordnungen"

QUELLEN = {
    2013: {
        "art":          "gv100ad",
        "datei":        DATEN / "GV100AD31122013" / "GV100AD_311213_J.asc",
        "encoding":     "cp1252",
        "lieferung":    "gv100ad_2013",
        "bezeichnung":  "Gemeindeverzeichnis GV100AD zum 31.12.2013, Satzart 60",
        "herausgeber":  "Statistisches Bundesamt",
        "gebietsstand": "2013-12-31",
        "lizenz":       "dl-de/by-2-0",
        "art_lieferung": "archiv",
        "limitierungen":
            "Die Quelle nennt den Wahlkreis als Spanne von-bis und nicht je " "Gemeinde: Wo eine Gemeinde in mehreren Wahlkreisen liegt, folgt " "aus der Spanne nicht, welcher gilt. Der Gebietsstand ist der " "31.12.2013 und liegt damit hundert Tage hinter dem Wahltag.",
    },
    2017: {
        "art":          "csv",
        "datei":        DATEN / "btw17_wkr_gemeinden" / "20170228_BTW17_WKr_Gemeinden_ASCII.csv",
        "encoding":     "cp1252",
        "lieferung":    "bwl_zuordnung_2017",
        "bezeichnung":  "Wahlkreise und zugeordnete Gemeinden, BTW 2017",
        "herausgeber":  "Die Bundeswahlleiterin",
        "gebietsstand": "2017-02-28",
        "lizenz":       "dl-de/by-2-0",
        "art_lieferung": "archiv",
    },
    2021: {
        "art":          "csv",
        "datei":        DATEN / "btw21_wkr_gemeinden" / "20200415_btw21_wkr_gemeinden_utf8.csv",
        "encoding":     "utf-8-sig",
        "lieferung":    "bwl_zuordnung_2021",
        "bezeichnung":  "Wahlkreise und zugeordnete Gemeinden, BTW 2021",
        "herausgeber":  "Die Bundeswahlleiterin",
        "gebietsstand": "2020-04-15",
        "lizenz":       "dl-de/by-2-0",
        "art_lieferung": "archiv",
    },
}


SP_WKR_NR, SP_LAND, SP_REGBEZ, SP_KREIS, SP_GEMEINDE, SP_GEMNAME = 0, 2, 3, 4, 6, 11


F_SATZART, F_STAND, F_AGS   = (0, 2), (2, 8), (10, 8)
F_NAME, F_TEXTKZ            = (22, 50), (122, 2)
F_FLAECHE, F_BEV            = (128, 11), (139, 11)
F_WK_VON, F_WK_BIS          = (190, 3), (193, 3)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gemeinde-wk")


DDL = f"""
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

CREATE TABLE IF NOT EXISTS roh_gemeinden.{STAMM} (
    stichtag        DATE     NOT NULL,
    ags             CHAR(8)  NOT NULL,
    gemeindename    TEXT,
    textkennzeichen TEXT,
    flaeche_ha      INTEGER,
    bevoelkerung    INTEGER,
    wkr_von         SMALLINT,
    wkr_bis         SMALLINT,
    PRIMARY KEY (stichtag, ags)
);

CREATE TABLE IF NOT EXISTS archiv.gemeinde_wahlkreis (
    wahljahr     SMALLINT NOT NULL,
    ags          CHAR(8)  NOT NULL,
    gemeindename TEXT,
    wkr_nr       SMALLINT NOT NULL,
    herkunft     TEXT NOT NULL DEFAULT 'csv',












    gemeindefrei BOOLEAN NOT NULL DEFAULT false,
    lieferung_id TEXT,
    PRIMARY KEY (wahljahr, ags, wkr_nr),
    FOREIGN KEY (wahljahr, wkr_nr)
        REFERENCES {WK_SCHEMA}.wahlkreis (wahljahr, wkr_nr) ON DELETE CASCADE,
    FOREIGN KEY (lieferung_id)
        REFERENCES {META_SCHEMA}.datenlieferung (lieferung_id)
);
CREATE INDEX IF NOT EXISTS idx_gemwk_wkr
    ON archiv.gemeinde_wahlkreis (wahljahr, wkr_nr);
CREATE INDEX IF NOT EXISTS idx_gemwk_lieferung
    ON archiv.gemeinde_wahlkreis (lieferung_id);

ALTER TABLE archiv.gemeinde_wahlkreis
    ADD COLUMN IF NOT EXISTS lieferung_id TEXT,
    ADD COLUMN IF NOT EXISTS gemeindefrei BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS stichtag DATE;

UPDATE archiv.gemeinde_wahlkreis SET stichtag = CASE wahljahr
    WHEN 2013 THEN DATE '2013-12-31'
    WHEN 2017 THEN DATE '2017-02-28'
    WHEN 2021 THEN DATE '2020-04-15' END
WHERE stichtag IS NULL;
CREATE INDEX IF NOT EXISTS idx_gemwk_gemeindefrei
    ON archiv.gemeinde_wahlkreis (wahljahr, gemeindefrei);
"""


def lit(wert):
    return "NULL" if wert is None else "'" + str(wert).replace("'", "''") + "'"


def merke_lieferung(jahr, cfg):
    run_sql(f"""
    INSERT INTO {META_SCHEMA}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, datei, gebietsstand, lizenz,
         wahljahr, limitierungen, art)
    VALUES ({lit(cfg['lieferung'])}, {lit(cfg['bezeichnung'])}, {lit(cfg['herausgeber'])},
            {lit(cfg['datei'].name)}, DATE {lit(cfg['gebietsstand'])},
            {lit(cfg['lizenz'])}, {jahr}, {lit(cfg.get('limitierungen'))},
            {lit(cfg.get('art_lieferung'))})
    ON CONFLICT (lieferung_id) DO UPDATE SET
        bezeichnung = EXCLUDED.bezeichnung, herausgeber = EXCLUDED.herausgeber,
        datei = EXCLUDED.datei, gebietsstand = EXCLUDED.gebietsstand,
        lizenz = EXCLUDED.lizenz, wahljahr = EXCLUDED.wahljahr,
        limitierungen = EXCLUDED.limitierungen, art = EXCLUDED.art;
    """, f"lieferung {cfg['lieferung']}")


def lies_csv(pfad, encoding):
    zeilen = []
    with pfad.open(encoding=encoding, newline="") as fh:
        for teile in csv.reader(fh, delimiter=";"):
            if not teile or not teile[0].strip():
                continue
            if teile[0].startswith("#") or teile[0].strip() == "Wahlkreis-Nr":
                continue
            ags = (teile[SP_LAND] + teile[SP_REGBEZ]
                   + teile[SP_KREIS] + teile[SP_GEMEINDE])
            if len(ags) != 8 or not ags.isdigit():
                raise SystemExit(f"Unerwarteter AGS {ags!r} in {pfad.name}: {teile[:7]}")
            zeilen.append((ags, teile[SP_GEMNAME].strip(), int(teile[SP_WKR_NR])))
    return zeilen


def feld(zeile, spec):
    start, laenge = spec
    return zeile[start:start + laenge].strip()


def lies_gv100ad(pfad, encoding):
    saetze, ohne_wk, stand = [], 0, None
    with pfad.open("r", encoding=encoding, newline="") as fh:
        for zeile in fh:
            zeile = zeile.rstrip("\r\n")
            if len(zeile) < 196 or feld(zeile, F_SATZART) != "60":
                continue
            stand = stand or feld(zeile, F_STAND)
            von = feld(zeile, F_WK_VON)
            if not von:
                ohne_wk += 1
                continue
            saetze.append({
                "ags":     feld(zeile, F_AGS),
                "name":    feld(zeile, F_NAME),
                "textkz":  feld(zeile, F_TEXTKZ),
                "flaeche": feld(zeile, F_FLAECHE),
                "bev":     feld(zeile, F_BEV),
                "von":     int(von),
                "bis":     int(feld(zeile, F_WK_BIS)) if feld(zeile, F_WK_BIS) else None,
            })
    log.info("%s: %d Gemeinden, davon %d mit Spanne, %d ohne Wahlkreisangabe",
             pfad.name, len(saetze),
             sum(1 for s in saetze if s["bis"] is not None), ohne_wk)
    return saetze, stand


def loese_spannen(saetze, jahr):
    namen = {int(nr): name for nr, name in
             query(f"SELECT wkr_nr, wkr_name FROM {WK_SCHEMA}.wahlkreis "
                   f"WHERE wahljahr = {jahr};")}
    zeilen, eingegrenzt = [], []
    for s in saetze:
        if s["bis"] is None or s["bis"] == s["von"]:
            zeilen.append((s["ags"], s["name"], s["von"], "gv100ad"))
            continue
        spanne = list(range(s["von"], s["bis"] + 1))
        kern = s["name"].split(",")[0].strip()
        passend = [nr for nr in spanne if kern and kern in namen.get(nr, "")]
        gewaehlt = passend or spanne
        herkunft = "gv100ad_spanne_namensfilter" if passend else "gv100ad_spanne"
        if passend and len(passend) < len(spanne):
            eingegrenzt.append((s["ags"], kern, s["von"], s["bis"],
                                sorted(set(spanne) - set(passend))))
        for nr in gewaehlt:
            zeilen.append((s["ags"], s["name"], nr, herkunft))

    for ags, kern, von, bis, raus in eingegrenzt:
        log.info("Spanne eingegrenzt: %s %s (%03d-%03d) ohne %s",
                 ags, kern, von, bis, raus)
    offen = [z for z in zeilen if z[3] == "gv100ad_spanne"]
    if offen:
        log.warning("%d Zuordnungen aus nicht eingrenzbarer Spanne: %s",
                    len(offen), ", ".join(sorted({z[0] for z in offen})))
    return zeilen


def schreibe_stamm(saetze, stand):
    datum = f"{stand[:4]}-{stand[4:6]}-{stand[6:8]}"
    werte = ",\n".join(
        f"({lit(datum)}, {lit(s['ags'])}, {lit(s['name'])}, {lit(s['textkz'])}, "
        f"{s['flaeche'] or 'NULL'}, {s['bev'] or 'NULL'}, {s['von']}, "
        f"{s['bis'] if s['bis'] is not None else 'NULL'})" for s in saetze)
    sql = (f"DELETE FROM roh_gemeinden.{STAMM} WHERE stichtag = DATE '{datum}';\n"
           f"INSERT INTO roh_gemeinden.{STAMM} (stichtag, ags, gemeindename, "
           f"textkennzeichen, flaeche_ha, bevoelkerung, wkr_von, wkr_bis)\n"
           f"VALUES\n{werte};\n")
    tmp = Path(tempfile.gettempdir()) / "gv100ad_stamm.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, label="gv100ad stamm")
    tmp.unlink(missing_ok=True)


def schreibe_zuordnung(jahr, cfg, zeilen):
    werte = ",\n".join(
        f"({jahr}, {lit(ags)}, {lit(name)}, {nr}, {lit(herkunft)}, {lit(cfg['lieferung'])})"
        for ags, name, nr, herkunft in zeilen)
    sql = (f"DELETE FROM archiv.gemeinde_wahlkreis WHERE wahljahr = {jahr};\n"
           f"INSERT INTO archiv.gemeinde_wahlkreis "
           f"(wahljahr, ags, gemeindename, wkr_nr, herkunft, lieferung_id)\n"
           f"VALUES\n{werte}\nON CONFLICT DO NOTHING;\n")


    tmp = Path(tempfile.gettempdir()) / f"gemeinde_wahlkreis_{jahr}.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, label=f"zuordnung {jahr}")
    tmp.unlink(missing_ok=True)
    log.info("[%s] %d Zuordnungen geschrieben.", jahr, len(zeilen))


def lade(jahr, cfg):
    if not cfg["datei"].exists():
        raise SystemExit(f"Quelldatei fehlt: {cfg['datei']}")
    log.info("[%s] lese %s (%s)", jahr, cfg["datei"].name, cfg["encoding"])
    merke_lieferung(jahr, cfg)

    if cfg["art"] == "csv":
        roh = lies_csv(cfg["datei"], cfg["encoding"])
        zeilen = [(ags, name, nr, "csv") for ags, name, nr in roh]
    else:
        saetze, stand = lies_gv100ad(cfg["datei"], cfg["encoding"])
        if stand:
            log.info("[%s] Gebietsstand laut Datei: %s-%s-%s",
                     jahr, stand[:4], stand[4:6], stand[6:8])
            schreibe_stamm(saetze, stand)
        zeilen = loese_spannen(saetze, jahr)

    schreibe_zuordnung(jahr, cfg, zeilen)


def loese_sammelposten(jahr):
    mehrdeutig = query(f"""
        SELECT substr(z.ags, 1, 5), count(DISTINCT z.wkr_nr)
        FROM archiv.gemeinde_wahlkreis z
        WHERE z.wahljahr = {jahr} AND z.gemeindename LIKE 'Gdefr%%'
          AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeindestand_stichtag s
                          JOIN zeit.stichtag t ON t.art = 'wahltag'
                           AND t.bezug = 'Wahl {jahr}' AND s.stichtag = t.datum
                          WHERE s.ags = z.ags)
        GROUP BY 1 HAVING count(DISTINCT z.wkr_nr) > 1;
    """)
    if mehrdeutig:
        raise SystemExit(
            f"[{jahr}] Sammeleintrag fuer gemeindefreie Gebiete verweist auf "
            f"mehrere Wahlkreise: {mehrdeutig}. Regel nicht anwendbar.")

    run_sql(f"""
    CREATE TEMP TABLE wahltagstand AS
        SELECT s.ags, s.gen, s.bez
        FROM {DB_SCHEMA}.gemeindestand_stichtag s
        JOIN zeit.stichtag t ON t.art = 'wahltag'
         AND t.bezug = 'Wahl {jahr}' AND s.stichtag = t.datum;

    INSERT INTO archiv.gemeinde_wahlkreis
        (wahljahr, ags, gemeindename, wkr_nr, herkunft, gemeindefrei, lieferung_id)
    SELECT {jahr}, g.ags, g.gen, s.wkr_nr, 'sammelposten', true, s.lieferung_id
    FROM (
        SELECT DISTINCT z.ags, z.wkr_nr, z.lieferung_id, substr(z.ags, 1, 5) AS kreis
        FROM archiv.gemeinde_wahlkreis z
        WHERE z.wahljahr = {jahr} AND z.gemeindename LIKE 'Gdefr%%'
          AND NOT EXISTS (SELECT 1 FROM wahltagstand w WHERE w.ags = z.ags)
    ) s
    JOIN wahltagstand g
      ON substr(g.ags, 1, 5) = s.kreis AND g.bez ILIKE 'Gemeindefrei%%'
    ON CONFLICT DO NOTHING;

    DELETE FROM archiv.gemeinde_wahlkreis z
    WHERE z.wahljahr = {jahr} AND z.gemeindename LIKE 'Gdefr%%'
      AND NOT EXISTS (SELECT 1 FROM wahltagstand w WHERE w.ags = z.ags);




    UPDATE archiv.gemeinde_wahlkreis z
    SET gemeindefrei = true
    FROM wahltagstand w
    WHERE z.wahljahr = {jahr} AND z.ags = w.ags
      AND w.bez ILIKE 'Gemeindefrei%%' AND NOT z.gemeindefrei;

    DROP TABLE wahltagstand;
    """, label=f"sammelposten {jahr}")

    anz, = query(f"""
        SELECT count(*) FROM archiv.gemeinde_wahlkreis
        WHERE wahljahr = {jahr} AND herkunft = 'sammelposten';
    """)[0]
    frei, = query(f"""
        SELECT count(*) FROM archiv.gemeinde_wahlkreis
        WHERE wahljahr = {jahr} AND gemeindefrei;
    """)[0]
    log.info("[%s] %s gemeindefreie Gebiete aus Sammeleintraegen ausgeschrieben, " "%s insgesamt gekennzeichnet.", jahr, anz, frei)


def pruefe(jahr):
    ohne_zuordnung = query(f"""
        SELECT s.ags, s.gen FROM {DB_SCHEMA}.gemeindestand_stichtag s
        JOIN zeit.stichtag t ON t.art = 'wahltag'
         AND t.bezug = 'Wahl {jahr}' AND s.stichtag = t.datum
        WHERE NOT EXISTS (SELECT 1 FROM archiv.gemeinde_wahlkreis z
                          WHERE z.wahljahr = {jahr} AND z.ags = s.ags)
        ORDER BY s.ags;
    """)
    ohne_gemeinde = query(f"""
        SELECT z.ags, z.gemeindename, z.herkunft
        FROM archiv.gemeinde_wahlkreis z
        WHERE z.wahljahr = {jahr}
          AND NOT EXISTS (SELECT 1 FROM {DB_SCHEMA}.gemeindestand_stichtag s
                          JOIN zeit.stichtag t ON t.art = 'wahltag'
                           AND t.bezug = 'Wahl {jahr}' AND s.stichtag = t.datum
                          WHERE s.ags = z.ags)
        ORDER BY z.ags;
    """)
    if ohne_zuordnung:
        log.warning("[%s] %d Gemeinden im Wahltagsstand ohne Wahlkreiszuordnung:",
                    jahr, len(ohne_zuordnung))
        for ags, name in ohne_zuordnung[:20]:
            log.warning("[%s]   %s %s", jahr, ags, name)
    if ohne_gemeinde:
        log.warning("[%s] %d Zuordnungen auf AGS ohne Gemeinde im Wahltagsstand:",
                    jahr, len(ohne_gemeinde))
        for ags, name, herkunft in ohne_gemeinde[:20]:
            log.warning("[%s]   %s %s (%s)", jahr, ags, name, herkunft)
    if not ohne_zuordnung and not ohne_gemeinde:
        log.info("[%s] Zuordnung und Wahltagsstand decken sich vollstaendig.", jahr)


def report(jahre):
    log.info("--- %s.gemeinde_wahlkreis ---", DB_SCHEMA)
    log.info("%-6s %-30s %10s %10s", "Jahr", "Herkunft", "Zeilen", "Gemeinden")
    for zeile in query(f"""
        SELECT wahljahr, herkunft, count(*), count(DISTINCT ags)
        FROM archiv.gemeinde_wahlkreis GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("%-6s %-30s %10s %10s", *zeile)

    log.info("--- Datenlieferungen ---")
    for zeile in query(f"""
        SELECT d.lieferung_id, d.herausgeber, d.gebietsstand::text,
               count(z.ags)
        FROM {META_SCHEMA}.datenlieferung d
        LEFT JOIN archiv.gemeinde_wahlkreis z ON z.lieferung_id = d.lieferung_id
        GROUP BY 1, 2, 3 ORDER BY 1;
    """):
        log.info("  %-22s %-26s Stand %s, %s Zeilen", *zeile)

    log.info("--- Gemeindefreie Gebiete ---")
    for zeile in query(f"""
        SELECT wahljahr, count(*) FILTER (WHERE gemeindefrei) AS gemeindefrei,
               count(DISTINCT ags) FILTER (WHERE gemeindefrei) AS ags,
               count(*) FILTER (WHERE NOT gemeindefrei) AS gemeinden
        FROM archiv.gemeinde_wahlkreis GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Zuordnungen gemeindefrei (%s Gebiete), " "%s regulaere Gemeinden", *zeile)

    log.info("--- Wahlkreise je Jahr (Soll 299) und geteilte Gemeinden ---")
    for zeile in query(f"""
        SELECT wahljahr, count(DISTINCT wkr_nr),
               count(*) FILTER (WHERE n > 1)
        FROM (SELECT wahljahr, ags, wkr_nr,
                     count(*) OVER (PARTITION BY wahljahr, ags) AS n
              FROM archiv.gemeinde_wahlkreis) t
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s Wahlkreise, %s Mehrfachzuordnungen", *zeile)


def main():
    argumente = sys.argv[1:]
    if "--neu" in argumente:
        argumente.remove("--neu")
        run_sql(f"DROP TABLE IF EXISTS archiv.gemeinde_wahlkreis CASCADE;",
                "zuordnung verwerfen")
        log.warning("gemeinde_wahlkreis verworfen, wird neu aufgebaut.")

    jahre = [int(a) for a in argumente] or sorted(QUELLEN)
    unbekannt = [j for j in jahre if j not in QUELLEN]
    if unbekannt:
        raise SystemExit(f"Unbekannte Jahre: {unbekannt}. Verfuegbar: {sorted(QUELLEN)}")

    for jahr in jahre:
        vorhanden, = query(
            f"SELECT count(*) FROM {WK_SCHEMA}.wahlkreis WHERE wahljahr = {jahr};")[0]
        if vorhanden == "0":
            raise SystemExit(f"Keine Wahlkreise fuer {jahr} - erst lib/db.py "
                             f"laufen lassen.")

    run_sql(DDL, "ddl")
    for jahr in jahre:
        lade(jahr, QUELLEN[jahr])
        loese_sammelposten(jahr)
        pruefe(jahr)
    report(jahre)


if __name__ == "__main__":
    main()
