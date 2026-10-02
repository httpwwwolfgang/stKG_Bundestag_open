import csv
import sys
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

DB_SCHEMA   = "wahlergebnisse"
META_SCHEMA = "meta"
TABELLE     = "briefwahlbezirk"

WBZ = (Path(__file__).resolve().parents[4] / "Daten" / "wahlergebnisse"
       / "Wahlbezirke_Bundeswahlleiterin")

QUELLEN = {


    2013: {"datei": WBZ / "btw13_wbz" / "BTW13_Leitband.csv",     "encoding": "utf-8-sig"},
    2017: {"datei": WBZ / "btw17_wbz" / "btw17_wbz_leitband.csv", "encoding": "cp1252"},
    2021: {"datei": WBZ / "btw21_wbz" / "Wbz_BTW21_Leitband.csv", "encoding": "utf-8-sig"},
}


SP_SATZART, SP_WKR, SP_LAND, SP_REGBEZ = 0, 1, 2, 3
SP_KREIS, SP_VG, SP_GEMEINDE, SP_BWBEZ = 4, 5, 6, 7
SP_NAME, SP_TEXTKZ = 8, 9


TK_BRIEFWAHL = {"73", "74", "75"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("briefwahlbezirk")


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
ALTER TABLE {META_SCHEMA}.datenlieferung
    ADD COLUMN IF NOT EXISTS art   TEXT NOT NULL DEFAULT 'amtlich',
    ADD COLUMN IF NOT EXISTS basis TEXT[];

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{TABELLE} (
    wahljahr        SMALLINT NOT NULL,
    wkr_nr          SMALLINT NOT NULL,
    ags             CHAR(8)  NOT NULL,
    kreis           CHAR(5)  NOT NULL,
    bwbez           CHAR(2)  NOT NULL,
    gemeindename    TEXT,
    textkennzeichen TEXT,
    sammelposten    BOOLEAN  NOT NULL DEFAULT false,

    verbund_amtlich TEXT,

    verbund_gerda   TEXT,
    lieferung_id    TEXT,



    PRIMARY KEY (wahljahr, wkr_nr, ags, bwbez),
    FOREIGN KEY (lieferung_id)
        REFERENCES {META_SCHEMA}.datenlieferung (lieferung_id)
);
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = '{DB_SCHEMA}.{TABELLE}'::regclass AND contype = 'p'
          AND array_length(conkey, 1) = 3
    ) THEN
        ALTER TABLE {DB_SCHEMA}.{TABELLE} DROP CONSTRAINT {TABELLE}_pkey;
        ALTER TABLE {DB_SCHEMA}.{TABELLE}
            ADD PRIMARY KEY (wahljahr, wkr_nr, ags, bwbez);
        RAISE NOTICE 'Primaerschluessel um bwbez erweitert';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS {TABELLE}_ags      ON {DB_SCHEMA}.{TABELLE} (wahljahr, ags);
CREATE INDEX IF NOT EXISTS {TABELLE}_amtlich  ON {DB_SCHEMA}.{TABELLE} (wahljahr, verbund_amtlich);
CREATE INDEX IF NOT EXISTS {TABELLE}_gerda    ON {DB_SCHEMA}.{TABELLE} (wahljahr, verbund_gerda);
"""


def lit(wert):
    return "NULL" if wert is None else "'" + str(wert).replace("'", "''") + "'"


def lieferung_id(jahr):
    return f"bwl_wahlbezirke_{jahr}"


def merke_lieferung(jahr, cfg):
    run_sql(f"""
    INSERT INTO {META_SCHEMA}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, datei, lizenz, wahljahr, art)
    VALUES ('{lieferung_id(jahr)}',
            'Wahlbezirksstatistik {jahr}, Leitband',
            'Die Bundeswahlleiterin (im Auftrag der Herausgebergemeinschaft)',
            {lit(cfg['datei'].name)}, 'dl-de/by-2-0', {jahr}, 'amtlich')
    ON CONFLICT (lieferung_id) DO UPDATE SET datei = EXCLUDED.datei;
    """, f"lieferung {lieferung_id(jahr)}")


def lies(cfg):
    if not cfg["datei"].exists():
        raise SystemExit(f"Leitband fehlt: {cfg['datei']}")
    zeilen = []
    with cfg["datei"].open(encoding=cfg["encoding"], newline="") as fh:
        for teile in csv.reader(fh, delimiter=";", quotechar='"'):
            if len(teile) <= SP_TEXTKZ:
                continue


            if teile[SP_SATZART].strip() != "60":
                if teile[SP_SATZART].strip() != "" or \
                   teile[SP_TEXTKZ].strip() not in TK_BRIEFWAHL:
                    continue
            t = [s.strip() for s in teile]
            ags = t[SP_LAND] + t[SP_REGBEZ] + t[SP_KREIS] + t[SP_GEMEINDE]
            if len(ags) != 8 or not ags.isdigit():
                raise SystemExit(f"Unerwarteter AGS {ags!r}: {t[:9]}")
            zeilen.append({
                "wkr":     int(t[SP_WKR]),
                "ags":     ags,
                "kreis":   t[SP_LAND] + t[SP_REGBEZ] + t[SP_KREIS],
                "bwbez":   t[SP_BWBEZ],
                "name":    t[SP_NAME],
                "textkz":  t[SP_TEXTKZ],
            })
    return zeilen


def schreibe(jahr, zeilen):
    lid = lieferung_id(jahr)
    werte = []
    for z in zeilen:

        verbund = z["bwbez"] not in ("00", "")
        v_amtlich = f"{z['wkr']:03d}-{z['kreis']}-{z['bwbez']}" if verbund else None
        v_gerda   = f"{z['kreis']}-{z['bwbez']}"                if verbund else None
        sammel    = z["ags"][5:].startswith("9")
        werte.append(
            f"({jahr}, {z['wkr']}, {lit(z['ags'])}, {lit(z['kreis'])}, "
            f"{lit(z['bwbez'])}, {lit(z['name'])}, {lit(z['textkz'])}, "
            f"{'true' if sammel else 'false'}, {lit(v_amtlich)}, {lit(v_gerda)}, "
            f"{lit(lid)})")

    sql = (f"DELETE FROM {DB_SCHEMA}.{TABELLE} WHERE wahljahr = {jahr};\n"
           f"INSERT INTO {DB_SCHEMA}.{TABELLE} (wahljahr, wkr_nr, ags, kreis, bwbez,"
           f" gemeindename, textkennzeichen, sammelposten, verbund_amtlich,"
           f" verbund_gerda, lieferung_id)\nVALUES\n" + ",\n".join(werte)
           + "\nON CONFLICT DO NOTHING;\n")
    tmp = Path(tempfile.gettempdir()) / f"briefwahlbezirk_{jahr}.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, label=f"briefwahlbezirke {jahr}")
    tmp.unlink(missing_ok=True)
    log.info("[%s] %d Gemeindesaetze geschrieben.", jahr, len(zeilen))


FLAECHEN = f"""

DROP TABLE IF EXISTS raum.briefwahlverbund_amtlich CASCADE;
DROP MATERIALIZED VIEW IF EXISTS gerda.briefwahlverbund_gerda;

CREATE TABLE raum.briefwahlverbund_amtlich AS
SELECT b.wahljahr, b.verbund_amtlich AS verbund_id, b.wkr_nr, b.kreis, b.bwbez,
       count(*)                                     AS gemeinden,
       ST_Area(ST_Union(s.geom)) / 1e6              AS flaeche_km2,
       ST_Multi(ST_Union(s.geom))::geometry(MultiPolygon, 25832) AS geom
FROM {DB_SCHEMA}.{TABELLE} b
JOIN zeit.stichtag t
  ON t.art = 'wahltag' AND t.bezug = 'Wahl ' || b.wahljahr::text
JOIN raum.gemeindestand_stichtag s
  ON s.stichtag = t.datum AND s.ags = b.ags
WHERE b.verbund_amtlich IS NOT NULL AND NOT b.sammelposten
GROUP BY 1, 2, 3, 4, 5;

ALTER TABLE raum.briefwahlverbund_amtlich ADD PRIMARY KEY (wahljahr, verbund_id);
CREATE INDEX briefwahlverbund_amtlich_gix
    ON raum.briefwahlverbund_amtlich USING GIST (geom);

CREATE MATERIALIZED VIEW gerda.briefwahlverbund_gerda AS
SELECT b.wahljahr, b.verbund_gerda AS verbund_id, b.kreis, b.bwbez,
       count(*)                                     AS gemeinden,
       count(DISTINCT b.wkr_nr)                     AS wahlkreise,
       (count(DISTINCT b.wkr_nr) > 1)               AS mehrdeutig,
       string_agg(DISTINCT b.wkr_nr::text, ', ' ORDER BY b.wkr_nr::text) AS wkr_liste,
       ST_Area(ST_Union(s.geom)) / 1e6              AS flaeche_km2,
       ST_Multi(ST_Union(s.geom))::geometry(MultiPolygon, 25832) AS geom
FROM {DB_SCHEMA}.{TABELLE} b
JOIN zeit.stichtag t
  ON t.art = 'wahltag' AND t.bezug = 'Wahl ' || b.wahljahr::text
JOIN raum.gemeindestand_stichtag s
  ON s.stichtag = t.datum AND s.ags = b.ags
WHERE b.verbund_gerda IS NOT NULL AND NOT b.sammelposten
GROUP BY 1, 2, 3, 4;

CREATE UNIQUE INDEX briefwahlverbund_gerda_pk
    ON gerda.briefwahlverbund_gerda (wahljahr, verbund_id);
CREATE INDEX briefwahlverbund_gerda_gix
    ON gerda.briefwahlverbund_gerda USING GIST (geom);
CREATE INDEX briefwahlverbund_gerda_mehr
    ON gerda.briefwahlverbund_gerda (wahljahr, mehrdeutig);
"""


def flaechen():
    run_sql(FLAECHEN, "flaechen")
    log.info("--- Flaechen je Schluesselung ---")
    for zeile in query(f"""
        SELECT a.wahljahr, a.n_amtlich, g.n_gerda, g.n_mehrdeutig
        FROM (SELECT wahljahr, count(*) AS n_amtlich
              FROM raum.briefwahlverbund_amtlich GROUP BY 1) a
        JOIN (SELECT wahljahr, count(*) AS n_gerda,
                     count(*) FILTER (WHERE mehrdeutig) AS n_mehrdeutig
              FROM gerda.briefwahlverbund_gerda GROUP BY 1) g
          USING (wahljahr)
        ORDER BY 1;
    """):
        log.info("  %s: amtlich %s Verbuende, GERDA %s, davon %s ueber mehrere " "Wahlkreise", *zeile)


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, TABELLE)
    log.info("%-6s %10s %12s %14s %14s", "Jahr", "Saetze", "Sammelp.",
             "Verb. amtlich", "Verb. GERDA")
    for zeile in query(f"""
        SELECT wahljahr, count(*), count(*) FILTER (WHERE sammelposten),
               count(DISTINCT verbund_amtlich), count(DISTINCT verbund_gerda)
        FROM {DB_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 1;
    """):
        log.info("%-6s %10s %12s %14s %14s", *zeile)

    log.info("--- Wo GERDAs Schluessel zu grob ist ---")
    zeilen = query(f"""
        SELECT wahljahr, verbund_gerda, count(DISTINCT wkr_nr) AS wahlkreise,
               string_agg(DISTINCT wkr_nr::text, ', ' ORDER BY wkr_nr::text),
               count(DISTINCT ags) FILTER (WHERE NOT sammelposten)
        FROM {DB_SCHEMA}.{TABELLE} WHERE verbund_gerda IS NOT NULL
        GROUP BY 1, 2 HAVING count(DISTINCT wkr_nr) > 1
        ORDER BY 1, 2;
    """)
    if not zeilen:
        log.info("  keine")
    for jahr, vg, n, wkr, gem in zeilen:
        log.warning("  %s %s: %s Wahlkreise (%s), %s Gemeinden - GERDA fuehrt " "das als EINEN Verbund", jahr, vg, n, wkr, gem)

    log.info("--- Gegenprobe gegen briefwahl_gemeinde (aus GERDA) ---")
    for zeile in query(f"""
        SELECT b.wahljahr,
               count(*) FILTER (WHERE b.verbund_id IS NOT NULL) AS gerda_verbund,
               count(*) FILTER (WHERE a.verbund_gerda IS NOT NULL) AS amtlich_verbund,
               count(*) FILTER (WHERE (b.verbund_id IS NULL)
                                   <> (a.verbund_gerda IS NULL)) AS uneinig
        FROM gerda.briefwahl_gemeinde b
        LEFT JOIN {DB_SCHEMA}.{TABELLE} a
          ON (a.wahljahr, a.ags) = (b.wahljahr, b.ags)
        GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: GERDA %s im Verbund, amtlich %s, uneinig %s", *zeile)


def main():
    argumente = sys.argv[1:]
    if "--neu" in argumente:
        argumente.remove("--neu")
        run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{TABELLE} CASCADE;", "drop")
        log.warning("Tabelle verworfen.")

    jahre = [int(a) for a in argumente] or sorted(QUELLEN)
    unbekannt = [j for j in jahre if j not in QUELLEN]
    if unbekannt:
        raise SystemExit(f"Unbekannte Jahre: {unbekannt}. Verfuegbar: {sorted(QUELLEN)}")

    run_sql(DDL, "ddl")
    for jahr in jahre:
        cfg = QUELLEN[jahr]
        log.info("[%s] lese %s (%s)", jahr, cfg["datei"].name, cfg["encoding"])
        merke_lieferung(jahr, cfg)
        schreibe(jahr, lies(cfg))
    flaechen()
    report()


if __name__ == "__main__":
    main()
