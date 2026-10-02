import csv
import sys
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

DB_SCHEMA   = "wahlergebnisse"
META_SCHEMA = "meta"
T_BEZIRK    = "wahlbezirk"
T_ERG       = "wahlbezirksergebnis"

WBZ = (Path(__file__).resolve().parents[4] / "Daten" / "wahlergebnisse"
       / "Wahlbezirke_Bundeswahlleiterin")


QUELLEN = {
    2013: {
        "encoding": "utf-8-sig", "kopfzeile": 5, "gemeindename": False,
        "kennziffer68": False,
        "dateien": [("zweitstimme", WBZ / "btw13_wbz" / "BTW13_Zweitstimmen_Wahlbezirke.csv"),
                    ("erststimme",  WBZ / "btw13_wbz" / "BTW13_Erststimmen_Wahlbezirke.csv")],
    },
    2017: {
        "encoding": "cp1252", "kopfzeile": 5, "gemeindename": False,
        "kennziffer68": False,
        "dateien": [("zweitstimme", WBZ / "btw17_wbz" / "btw17_wbz_zweitstimmen.csv"),
                    ("erststimme",  WBZ / "btw17_wbz" / "btw17_wbz_erststimmen.csv")],
    },
    2021: {
        "encoding": "utf-8-sig", "kopfzeile": 1, "gemeindename": True,
        "kennziffer68": True,
        "dateien": [("beide", WBZ / "btw21_wbz" / "btw21_wbz_ergebnisse.csv")],
    },
}


KENNZAHL_KLAMMERN = ("(a)", "(a1)", "(a2)", "(a3)", "(b)", "(b1)")
KENNZAHL_ENDUNGEN = ("ungültig", "ungültige", "gültig", "gültige",
                     "ungultig", "ungultige", "gultig", "gultige")


KEINE_PARTEI = ("wahlbezirksbezeichnung", "bezeichnung", "wahlbezirksname")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wahlbezirk")


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

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_BEZIRK} (
    wahljahr        SMALLINT NOT NULL,
    wkr_nr          SMALLINT NOT NULL,
    ags             CHAR(8)  NOT NULL,
    bezirk_nr       TEXT     NOT NULL,




    bezirksart      TEXT     NOT NULL,
    kreis           CHAR(5)  NOT NULL,






    bwbez           CHAR(2)  NOT NULL,





    bezirk_original TEXT     NOT NULL,
    gemeindename    TEXT,

    wahlberechtigte       INTEGER,
    wb_ohne_sperrvermerk  INTEGER,
    wb_mit_sperrvermerk   INTEGER,
    wb_par25              INTEGER,

    waehlende             INTEGER,
    waehlende_wahlschein  INTEGER,

    ungueltig_erst        INTEGER,
    gueltig_erst          INTEGER,
    ungueltig_zweit       INTEGER,
    gueltig_zweit         INTEGER,









    zusammenlegung_id TEXT,
    abgebend        BOOLEAN NOT NULL DEFAULT false,
    aufnehmend      BOOLEAN NOT NULL DEFAULT false,
    lieferung_id    TEXT,
    PRIMARY KEY (wahljahr, wkr_nr, ags, bezirk_nr, bezirksart, bwbez, bezirk_original),
    FOREIGN KEY (lieferung_id)
        REFERENCES {META_SCHEMA}.datenlieferung (lieferung_id)
);
CREATE INDEX IF NOT EXISTS {T_BEZIRK}_ags  ON {DB_SCHEMA}.{T_BEZIRK} (wahljahr, ags);
CREATE INDEX IF NOT EXISTS {T_BEZIRK}_wkr  ON {DB_SCHEMA}.{T_BEZIRK} (wahljahr, wkr_nr);
CREATE INDEX IF NOT EXISTS {T_BEZIRK}_art  ON {DB_SCHEMA}.{T_BEZIRK} (wahljahr, bezirksart);
CREATE INDEX IF NOT EXISTS {T_BEZIRK}_bw   ON {DB_SCHEMA}.{T_BEZIRK} (wahljahr, kreis, bwbez);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.{T_ERG} (
    wahljahr  SMALLINT NOT NULL,
    wkr_nr    SMALLINT NOT NULL,
    ags       CHAR(8)  NOT NULL,
    bezirk_nr  TEXT    NOT NULL,
    bezirksart TEXT    NOT NULL,
    bwbez           CHAR(2) NOT NULL,
    bezirk_original TEXT    NOT NULL,
    stimme    TEXT     NOT NULL CHECK (stimme IN ('erststimme', 'zweitstimme')),
    partei    TEXT     NOT NULL,
    stimmen   INTEGER  NOT NULL,
    PRIMARY KEY (wahljahr, wkr_nr, ags, bezirk_nr, bezirksart, bwbez,
                 bezirk_original, stimme, partei)
);
CREATE INDEX IF NOT EXISTS {T_ERG}_partei ON {DB_SCHEMA}.{T_ERG} (wahljahr, partei, stimme);
CREATE INDEX IF NOT EXISTS {T_ERG}_ags    ON {DB_SCHEMA}.{T_ERG} (wahljahr, ags);
"""


def lieferung_id(jahr):
    return f"bwl_wahlbezirke_{jahr}"


def merke_lieferung(jahr, cfg):
    dateien = ", ".join(d.name for _, d in cfg["dateien"])
    run_sql(f"""
    INSERT INTO {META_SCHEMA}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, datei, lizenz, wahljahr, art)
    VALUES ('{lieferung_id(jahr)}',
            'Wahlbezirksstatistik {jahr}',
            'Die Bundeswahlleiterin (im Auftrag der Herausgebergemeinschaft)',
            '{dateien}', 'dl-de/by-2-0', {jahr}, 'amtlich')
    ON CONFLICT (lieferung_id) DO UPDATE SET
        bezeichnung = EXCLUDED.bezeichnung, datei = EXCLUDED.datei;
    """, f"lieferung {lieferung_id(jahr)}")


def ist_kennzahl(name):
    n = name.lower().strip()

    for p in ("e_", "z_"):
        if n.startswith(p):
            n = n[len(p):]
            break
    if any(k in n for k in KENNZAHL_KLAMMERN):
        return True
    if any(k in n for k in KEINE_PARTEI):
        return True
    return n in KENNZAHL_ENDUNGEN


def lies_kopf(pfad, encoding, kopfzeile):
    with pfad.open(encoding=encoding, newline="") as fh:
        for i, teile in enumerate(csv.reader(fh, delimiter=";", quotechar='"'), 1):
            if i == kopfzeile:
                return [s.strip() for s in teile]
    raise SystemExit(f"Kopfzeile {kopfzeile} nicht gefunden in {pfad.name}")


def bereinige(pfad, encoding, kopfzeile, ziel):
    zeilen, breite, abweichend = 0, None, []
    with pfad.open(encoding=encoding, newline="") as fh, \
         ziel.open("w", encoding="utf-8", newline="") as out:
        schreiber = csv.writer(out, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        for i, teile in enumerate(csv.reader(fh, delimiter=";", quotechar='"'), 1):
            if i < kopfzeile or not teile or not teile[0].strip():
                continue
            werte = [s.strip() for s in teile]
            if breite is None:
                breite = len(werte)
            elif len(werte) != breite:
                abweichend.append((i, len(werte), werte[:6]))
                werte = (werte + [""] * breite)[:breite]
            schreiber.writerow(werte)
            zeilen += 1

    for nr, n, kopf in abweichend:
        log.warning("Zeile %d hat %d statt %d Felder, auf Kopfbreite gebracht: %s",
                    nr, n, breite, ";".join(kopf))
    return zeilen - 1


def staging(jahr, kennung, pfad, spalten, encoding, kopfzeile):
    tab = f"{DB_SCHEMA}.stg_wbz_{jahr}_{kennung}"
    namen = [f"c{i:03d}" for i in range(len(spalten))]
    felder = ",\n    ".join(f"{n} TEXT" for n in namen)

    tmp_csv = Path(tempfile.gettempdir()) / f"wbz_{jahr}_{kennung}.csv"
    anzahl = bereinige(pfad, encoding, kopfzeile, tmp_csv)
    log.info("[%s/%s] %d Datenzeilen aufbereitet", jahr, kennung, anzahl)

    sql = Path(tempfile.gettempdir()) / f"wbz_{jahr}_{kennung}.sql"
    sql.write_text(
        f"DROP TABLE IF EXISTS {tab};\n"
        f"CREATE TABLE {tab} (\n    {felder}\n);\n"
        f"\\copy {tab} FROM '{tmp_csv.as_posix()}' "
        f"WITH (FORMAT csv, HEADER true, DELIMITER ';', ENCODING 'UTF8');\n",
        encoding="utf-8")
    run_sql_file(sql, label=f"staging {jahr} {kennung}")
    sql.unlink(missing_ok=True)
    tmp_csv.unlink(missing_ok=True)
    return tab, namen


def spaltenlage(spalten, cfg):
    i = 0
    lage = {}
    for name in ("wkr", "land", "regbez", "kreis", "vg", "gemeinde"):
        lage[name] = i
        i += 1
    if cfg["kennziffer68"]:
        lage["kz68"] = i
        i += 1
    lage["bwbez"] = i
    i += 1
    if cfg["gemeindename"]:
        lage["gemeindename"] = i
        i += 1
    lage["bezirk"] = i
    i += 1
    lage["bezirksart"] = i
    i += 1


    parteien = []
    for j in range(i, len(spalten)):
        roh = spalten[j]
        n = roh.lower().strip()
        for p in ("e_", "z_"):
            if n.startswith(p):
                n = n[len(p):]
                break

        if any(k in roh.lower() for k in KEINE_PARTEI):
            lage["bezirk_original"] = j
            continue
        if not ist_kennzahl(roh):
            parteien.append((j, roh))
            continue


        if   "(a1)" in n: lage["wb_ohne_sperr"] = j
        elif "(a2)" in n: lage["wb_mit_sperr"]  = j
        elif "(a3)" in n: lage["wb_par25"]      = j
        elif "(a)"  in n: lage["wahlberechtigte"] = j
        elif "(b1)" in n: lage["waehlende_wahlschein"] = j
        elif "(b)"  in n: lage["waehlende"]     = j
        elif n.startswith("ungültig") or n.startswith("ungultig"):
            lage["ungueltig_" + _stimmenart(roh)] = j
        elif n.startswith("gültig") or n.startswith("gultig"):
            lage["gueltig_" + _stimmenart(roh)] = j
    return lage, parteien


def _stimmenart(spaltenname):
    n = spaltenname.lower().strip()
    if n.startswith("e_"):
        return "erst"
    if n.startswith("z_"):
        return "zweit"
    return "datei"


def verteile(jahr, cfg, tab, namen, spalten, kennung):
    lage, parteien = spaltenlage(spalten, cfg)
    lid = lieferung_id(jahr)
    c = lambda k: namen[lage[k]]

    ags = (f"({c('land')} || {c('regbez')} || {c('kreis')} || {c('gemeinde')})")
    kreis = f"({c('land')} || {c('regbez')} || {c('kreis')})"


    bezirk = f"coalesce(nullif(trim({c('bezirk')}), ''), '000')"
    bezart = f"coalesce(nullif(trim({c('bezirksart')}), ''), '?')"
    bwb    = f"coalesce(nullif(trim({c('bwbez')}), ''), '00')"


    original = (f"coalesce(nullif(trim({c('bezirk_original')}), ''), {bezirk})"
                if "bezirk_original" in lage else bezirk)
    gemname = f"{c('gemeindename')}" if cfg["gemeindename"] else "NULL"

    def kennzahl(schluessel):
        return zahl(namen[lage[schluessel]]) if schluessel in lage else "NULL"


    if kennung == "beide":
        ung_erst,  gue_erst  = kennzahl("ungueltig_erst"),  kennzahl("gueltig_erst")
        ung_zweit, gue_zweit = kennzahl("ungueltig_zweit"), kennzahl("gueltig_zweit")
    elif kennung == "zweitstimme":
        ung_erst,  gue_erst  = "NULL", "NULL"
        ung_zweit, gue_zweit = kennzahl("ungueltig_datei"), kennzahl("gueltig_datei")
    else:
        ung_erst,  gue_erst  = kennzahl("ungueltig_datei"), kennzahl("gueltig_datei")
        ung_zweit, gue_zweit = "NULL", "NULL"


    if cfg["kennziffer68"]:


        kz = (f"CASE WHEN trim({c('kz68')}) ~ '^0*$' THEN NULL "
              f"ELSE nullif(trim({c('kz68')}), '') END")
        zusammenlegung = kz
        abgebend   = f"({kz} IS NOT NULL AND coalesce({kennzahl('waehlende')}, 0) = 0)"
        aufnehmend = f"({kz} IS NOT NULL AND coalesce({kennzahl('waehlende')}, 0) > 0)"
    else:
        zusammenlegung, abgebend, aufnehmend = "NULL", "false", "false"


    if kennung in ("zweitstimme", "beide"):
        sql_ueber_datei(f"""
        DELETE FROM {DB_SCHEMA}.{T_BEZIRK} WHERE wahljahr = {jahr};
        INSERT INTO {DB_SCHEMA}.{T_BEZIRK}
            (wahljahr, wkr_nr, ags, bezirk_nr, bezirksart, kreis, bwbez,
             bezirk_original, gemeindename,
             wahlberechtigte, wb_ohne_sperrvermerk, wb_mit_sperrvermerk, wb_par25,
             waehlende, waehlende_wahlschein,
             ungueltig_erst, gueltig_erst, ungueltig_zweit, gueltig_zweit,
             zusammenlegung_id, abgebend, aufnehmend, lieferung_id)
        SELECT {jahr}, {c('wkr')}::int, {ags}, {bezirk}, {bezart}, {kreis},
               {bwb}, {original}, {gemname},
               {kennzahl('wahlberechtigte')}, {kennzahl('wb_ohne_sperr')},
               {kennzahl('wb_mit_sperr')}, {kennzahl('wb_par25')},
               {kennzahl('waehlende')}, {kennzahl('waehlende_wahlschein')},
               {ung_erst}, {gue_erst}, {ung_zweit}, {gue_zweit},
               {zusammenlegung}, {abgebend}, {aufnehmend}, '{lid}'
        FROM {tab}
        WHERE {c('wkr')} ~ '^[0-9]+$'
        ON CONFLICT DO NOTHING;
        """, f"bezirke {jahr}")


    elif kennung == "erststimme":
        sql_ueber_datei(f"""
        UPDATE {DB_SCHEMA}.{T_BEZIRK} b
        SET ungueltig_erst = q.ung, gueltig_erst = q.gue
        FROM (SELECT {c('wkr')}::int AS wkr_nr, {ags} AS ags, {bezirk} AS bezirk_nr,
                     {bezart} AS bezirksart, {bwb} AS bwbez,
                     {original} AS bezirk_original,
                     {ung_erst} AS ung, {gue_erst} AS gue
              FROM {tab} WHERE {c('wkr')} ~ '^[0-9]+$') q
        WHERE b.wahljahr = {jahr}
          AND (b.wkr_nr, b.ags, b.bezirk_nr, b.bezirksart, b.bwbez, b.bezirk_original)
            = (q.wkr_nr, q.ags, q.bezirk_nr, q.bezirksart, q.bwbez, q.bezirk_original);
        """, f"erststimmen-kennzahlen {jahr}")


    arten = {"zweitstimme": ["zweitstimme"], "erststimme": ["erststimme"],
             "beide": ["erststimme", "zweitstimme"]}[kennung]
    for art in arten:
        praefix = {"erststimme": "e_", "zweitstimme": "z_"}[art] if kennung == "beide" else None
        teile = []
        for idx, roh in parteien:
            name = roh.lower()
            if praefix:
                if not name.startswith(praefix):
                    continue
                name = name[len(praefix):]
            teile.append(
                f"SELECT {jahr} AS wahljahr, {c('wkr')}::int AS wkr_nr, {ags} AS ags,\n"
                f"       {bezirk} AS bezirk_nr, {bezart} AS bezirksart,\n"
                f"       {bwb} AS bwbez, {original} AS bezirk_original,\n"
                f"       '{art}' AS stimme,\n"
                f"       {_lit(name)} AS partei, {zahl(namen[idx])} AS stimmen\n"
                f"FROM {tab} WHERE {c('wkr')} ~ '^[0-9]+$'\n"
                f"  AND {zahl(namen[idx])} > 0")
        if not teile:
            log.warning("[%s/%s] keine Parteispalten fuer %s", jahr, kennung, art)
            continue

        sql_ueber_datei(f"""
        DELETE FROM {DB_SCHEMA}.{T_ERG}
        WHERE wahljahr = {jahr} AND stimme = '{art}';
        INSERT INTO {DB_SCHEMA}.{T_ERG}
            (wahljahr, wkr_nr, ags, bezirk_nr, bezirksart, bwbez, bezirk_original,
             stimme, partei, stimmen)
        """ + "\nUNION ALL\n".join(teile) + "\nON CONFLICT DO NOTHING;",
                f"ergebnisse {jahr} {art}")
        log.info("[%s] %s: %d Parteispalten verarbeitet", jahr, art, len(teile))


def _lit(wert):
    return "'" + str(wert).replace("'", "''") + "'"


def zahl(spalte):
    return f"(CASE WHEN {spalte} ~ '^[0-9]+$' THEN {spalte}::int END)"


def sql_ueber_datei(sql, label):
    pfad = Path(tempfile.gettempdir()) / f"wbz_{abs(hash(label))}.sql"
    pfad.write_text("SET client_encoding TO 'UTF8';\n" + sql, encoding="utf-8")
    try:
        run_sql_file(pfad, label=label)
    finally:
        pfad.unlink(missing_ok=True)


def lade(jahr, cfg):
    merke_lieferung(jahr, cfg)
    for kennung, pfad in cfg["dateien"]:
        if not pfad.exists():
            raise SystemExit(f"Datei fehlt: {pfad}")
        log.info("[%s] lese %s (%s)", jahr, pfad.name, cfg["encoding"])
        spalten = lies_kopf(pfad, cfg["encoding"], cfg["kopfzeile"])
        tab, namen = staging(jahr, kennung, pfad, spalten,
                             cfg["encoding"], cfg["kopfzeile"])
        verteile(jahr, cfg, tab, namen, spalten, kennung)
        run_sql(f"DROP TABLE IF EXISTS {tab};", f"staging weg {jahr} {kennung}")


def report():
    log.info("--- %s.%s ---", DB_SCHEMA, T_BEZIRK)
    log.info("%-6s %10s %10s %10s %14s", "Jahr", "Bezirke", "Gemeinden",
             "Wahlkreise", "Wahlberecht.")
    for zeile in query(f"""
        SELECT wahljahr, count(*), count(DISTINCT ags), count(DISTINCT wkr_nr),
               to_char(sum(wahlberechtigte), 'FM999G999G999')
        FROM {DB_SCHEMA}.{T_BEZIRK} GROUP BY 1 ORDER BY 1;
    """):
        log.info("%-6s %10s %10s %10s %14s", *zeile)

    log.info("--- Bezirksart ---")
    for zeile in query(f"""
        SELECT wahljahr, bezirksart, count(*),
               to_char(sum(wahlberechtigte), 'FM999G999G999')
        FROM {DB_SCHEMA}.{T_BEZIRK} GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  %s art=%s: %s Bezirke, %s Wahlberechtigte", *zeile)

    log.info("--- Kennzahlen: wie viele Bezirke haben den Wert? ---")
    log.info("%-6s %9s %9s %9s %9s %9s %9s %9s", "Jahr", "A1", "A2", "A3", "B1",
             "ung.E", "ung.Z", "gue.Z")
    for zeile in query(f"""
        SELECT wahljahr,
               count(wb_ohne_sperrvermerk), count(wb_mit_sperrvermerk),
               count(wb_par25), count(waehlende_wahlschein),
               count(ungueltig_erst), count(ungueltig_zweit), count(gueltig_zweit)
        FROM {DB_SCHEMA}.{T_BEZIRK} GROUP BY 1 ORDER BY 1;
    """):
        log.info("%-6s %9s %9s %9s %9s %9s %9s %9s", *zeile)

    log.info("--- Gegenprobe: gueltige Stimmen gegen die Summe der Parteien ---")
    for zeile in query(f"""
        SELECT b.wahljahr, r.stimme,
               count(*) FILTER (WHERE b.gue <> r.summe) AS abweichend,
               count(*) AS bezirke
        FROM (SELECT wahljahr, wkr_nr, ags, bezirk_nr, bezirksart, bwbez,
                     bezirk_original, gueltig_erst, gueltig_zweit,
                     unnest(ARRAY['erststimme','zweitstimme']) AS stimme,
                     unnest(ARRAY[gueltig_erst, gueltig_zweit]) AS gue
              FROM {DB_SCHEMA}.{T_BEZIRK}) b
        JOIN (SELECT wahljahr, wkr_nr, ags, bezirk_nr, bezirksart, bwbez,
                     bezirk_original, stimme, sum(stimmen) AS summe
              FROM {DB_SCHEMA}.{T_ERG}
              GROUP BY 1,2,3,4,5,6,7,8) r
          USING (wahljahr, wkr_nr, ags, bezirk_nr, bezirksart, bwbez,
                 bezirk_original, stimme)
        WHERE b.gue IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  %s %s: %s von %s Bezirken abweichend", *zeile)

    log.info("--- § 68 BWO: abgebende und aufnehmende Bezirke ---")
    for zeile in query(f"""
        SELECT wahljahr,
               count(*) FILTER (WHERE abgebend)                       AS abgebend,
               count(DISTINCT ags) FILTER (WHERE abgebend)            AS gemeinden,
               count(*) FILTER (WHERE aufnehmend)                     AS aufnehmend,
               coalesce(sum(waehlende) FILTER (WHERE abgebend), 0)    AS waehlende
        FROM {DB_SCHEMA}.{T_BEZIRK} GROUP BY 1 ORDER BY 1;
    """):
        log.info("  %s: %s abgebende Bezirke (%s Gemeinden), %s aufnehmende, " "%s Waehlende bei den abgebenden", *zeile)

    log.info("--- Ergebniszeilen ---")
    for zeile in query(f"""
        SELECT wahljahr, stimme, count(*), count(DISTINCT partei),
               to_char(sum(stimmen), 'FM999G999G999')
        FROM {DB_SCHEMA}.{T_ERG} GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  %s %s: %s Zeilen, %s Parteien, %s Stimmen", *zeile)

    log.info("--- Gegenprobe: Zweitstimmen gegen die Wahlkreisebene (GERDA) ---")
    for zeile in query(f"""
        SELECT b.wahljahr,
               to_char(b.summe, 'FM999G999G999'), to_char(g.summe, 'FM999G999G999'),
               to_char(b.summe - g.summe, 'FM999G999G999')
        FROM (SELECT wahljahr, sum(stimmen) AS summe FROM {DB_SCHEMA}.{T_ERG}
              WHERE stimme = 'zweitstimme' GROUP BY 1) b
        JOIN (SELECT wahljahr, sum(stimmen) AS summe
              FROM gerda.wahlergebnis_gerda_wahlkreis
              WHERE stimme = 'zweitstimme' GROUP BY 1) g USING (wahljahr)
        ORDER BY 1;
    """):
        log.info("  %s: Wahlbezirke %s, GERDA %s, Differenz %s", *zeile)


def main():
    argumente = sys.argv[1:]
    if "--neu" in argumente:
        argumente.remove("--neu")
        for t in (T_ERG, T_BEZIRK):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;", f"drop {t}")
        log.warning("Tabellen verworfen.")

    jahre = [int(a) for a in argumente] or sorted(QUELLEN)
    unbekannt = [j for j in jahre if j not in QUELLEN]
    if unbekannt:
        raise SystemExit(f"Unbekannte Jahre: {unbekannt}. Verfuegbar: {sorted(QUELLEN)}")


    sql_ueber_datei(DDL, "ddl")
    for jahr in jahre:
        lade(jahr, QUELLEN[jahr])
    report()


if __name__ == "__main__":
    main()
