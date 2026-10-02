import sys
import csv
import logging
import tempfile
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

warnings.filterwarnings("ignore")
import pandas as pd

from db import run_sql, run_sql_file, query


import lieferung
LIEFERUNG = "bbsr_raumgliederung"

DB_SCHEMA = "strukturdaten"
DATEN     = Path(__file__).resolve().parents[4] / "Daten" / "Strukturdaten"


REFERENZEN = {
    "2021": (DATEN / "raumgliederungen-referenzen-2021.xlsx", "2021-12-31"),
    "2022": (DATEN / "inkar_2024" / "BBSR_Raumgliederungen_Referenzen_2022.xlsx",
             "2022-12-31"),
    "2023": (DATEN / "inkar_2025" / "BBSR_Raumgliederungen_Referenz_2023.xlsx",
             "2023-12-31"),
}
STANDARD = ["2021", "2022"]

BLATT_GEM   = "Gemeindereferenz (inkl. Kreise)"
BLATT_KREIS = "Kreisreferenz"


KEINE_GLIEDERUNG = {"bev21", "bev22", "bev23", "fl21", "fl22", "fl23"}


GEBIETE = {
    "VWG",
    "GMB",
    "KRS",
    "N3D",
    "KKR",
    "GSL",
    "KAM",
    "KRO",
    "GIB",
    "GSR",
    "GGR",
    "GVR",
    "N2D",
    "KBN",
}


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bbsr-referenz")


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.raumtyp (
    gebietsstand DATE NOT NULL,
    gliederung   TEXT NOT NULL,
    bezeichnung  TEXT NOT NULL,
    ebene        TEXT NOT NULL,
    art          TEXT NOT NULL,
    typ_id       TEXT NOT NULL,
    typ_name     TEXT,
    restklasse   BOOLEAN NOT NULL DEFAULT false,

    PRIMARY KEY (gebietsstand, gliederung, typ_id)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.gemeinde_raumgliederung (
    gebietsstand DATE    NOT NULL,
    ags          CHAR(8) NOT NULL,
    gliederung   TEXT    NOT NULL,
    typ_id       TEXT    NOT NULL,
    PRIMARY KEY (gebietsstand, ags, gliederung)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.gemeinde_typisierung (
    gebietsstand DATE    NOT NULL,
    ags          CHAR(8) NOT NULL,
    gliederung   TEXT    NOT NULL,
    typ_id       TEXT    NOT NULL,
    PRIMARY KEY (gebietsstand, ags, gliederung)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.kreis_raumgliederung (
    gebietsstand DATE    NOT NULL,
    kreis        CHAR(5) NOT NULL,
    gliederung   TEXT    NOT NULL,
    typ_id       TEXT    NOT NULL,
    PRIMARY KEY (gebietsstand, kreis, gliederung)
);

CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.kreis_typisierung (
    gebietsstand DATE    NOT NULL,
    kreis        CHAR(5) NOT NULL,
    gliederung   TEXT    NOT NULL,
    typ_id       TEXT    NOT NULL,
    PRIMARY KEY (gebietsstand, kreis, gliederung)
);

CREATE INDEX IF NOT EXISTS gemeinde_raumgliederung_such
    ON {DB_SCHEMA}.gemeinde_raumgliederung (gebietsstand, gliederung, typ_id);
CREATE INDEX IF NOT EXISTS gemeinde_typisierung_such
    ON {DB_SCHEMA}.gemeinde_typisierung (gebietsstand, gliederung, typ_id);
CREATE INDEX IF NOT EXISTS kreis_raumgliederung_such
    ON {DB_SCHEMA}.kreis_raumgliederung (gebietsstand, gliederung, typ_id);

COMMENT ON TABLE {DB_SCHEMA}.gemeinde_raumgliederung IS
  'Gemeinde -> Gebiet, je Gebietsstand. Arbeitsmarktregion, Mittelbereich, '
  'Kreisregion, NUTS und aehnliche - Einheiten mit Eigennamen. Gemeinden ohne '
  'Zugehoerigkeit haben keine Zeile, nicht eine auf "keine".';
COMMENT ON TABLE {DB_SCHEMA}.gemeinde_typisierung IS
  'Gemeinde -> Klasse, je Gebietsstand. Stadt- und Gemeindetyp, RegioStaR, '
  'Degree of Urbanisation und aehnliche - Kategorien, keine Gebiete. Als '
  'Strukturmerkmal der Gemeinde zu lesen, nicht als Raumeinheit.';
COMMENT ON TABLE {DB_SCHEMA}.raumtyp IS
  'Klartext zu den Kennziffern, je Gebietsstand. ebene sagt, ob die Zeile zu '
  'einer Gemeinde- oder Kreisgliederung gehoert, art ob Gebiet oder Klasse.';
"""


def paare(kurz, lang):
    namen = {}
    for j, k in enumerate(kurz):
        if k.endswith("_NAME"):
            namen[k[:-5]] = j
    gefunden, ohne_namen = [], []
    for j, k in enumerate(kurz):
        if k.endswith("_NAME") or k in KEINE_GLIEDERUNG or k.endswith("_RS"):
            continue

        p = k[:-4] if k[-4:].isdigit() else k
        if p in namen:
            gefunden.append((p, str(lang[j]).strip(), j, namen[p]))
        else:
            ohne_namen.append(k)
    return gefunden, ohne_namen


def schluessel(v, stellen):
    if pd.isna(v):
        return None
    t = str(v).strip()
    if t.endswith(".0"):
        t = t[:-2]
    if not t or not t.replace("-", "").isdigit():
        return t or None
    if stellen == 5:
        return t.zfill(8)[:5] if len(t) > 5 else t.zfill(5)
    return t.zfill(stellen)


def ist_restklasse(gliederung, typ_name):
    if gliederung not in GEBIETE or not typ_name:
        return False
    t = typ_name.strip().lower()
    return t.startswith("kein ") or t.startswith("keine ") or t.startswith("nicht ")


def lies_blatt(pfad, blatt, stellen):
    roh = pd.ExcelFile(pfad).parse(blatt, header=None)
    kurz = [str(v).strip() for v in roh.iloc[0].tolist()]
    lang = roh.iloc[1].tolist()
    daten = roh.iloc[2:]
    gliederungen, ohne_namen = paare(kurz, lang)
    if ohne_namen:
        log.warning("  %s: Kennziffernspalten ohne Namensspalte, uebersprungen: %s",
                    blatt, ", ".join(ohne_namen))

    eigen = gliederungen[0][0] if gliederungen else None
    gebiete, klassen, typen = [], [], {}
    weggelassen = {}
    for _, r in daten.iterrows():
        einheit = schluessel(r[0], stellen)
        if not einheit:
            continue
        for p, bez, j_id, j_name in gliederungen:
            if p == eigen:
                continue
            tid = schluessel(r[j_id], 0) if p not in ("VWG",) else schluessel(r[j_id], 8)
            if tid is None:
                continue
            name = None if pd.isna(r[j_name]) else str(r[j_name]).strip()
            rest = ist_restklasse(p, name)
            typen.setdefault((p, bez, tid), (name, p in GEBIETE, rest))
            if rest:
                weggelassen[p] = weggelassen.get(p, 0) + 1
                continue
            (gebiete if p in GEBIETE else klassen).append((einheit, p, tid))
    for p, n in sorted(weggelassen.items(), key=lambda x: -x[1]):
        log.info("      %s: %s ohne Zugehoerigkeit, keine Zeile angelegt", p, n)
    return gliederungen, gebiete, klassen, typen


def kopiere(tabelle, spalten, zeilen, label):
    tmp = Path(tempfile.gettempdir()) / f"{tabelle}.csv"
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(zeilen)
    sql = Path(tempfile.gettempdir()) / f"{tabelle}_copy.sql"
    sql.write_text(
        f"\\copy {DB_SCHEMA}.{tabelle} ({spalten}) "
        f"FROM '{tmp.as_posix()}' WITH (FORMAT csv, ENCODING 'UTF8');\n",
        encoding="utf-8")
    run_sql_file(sql, label=label)
    sql.unlink(missing_ok=True)
    tmp.unlink(missing_ok=True)


def laden(stand):
    pfad, gebietsstand = REFERENZEN[stand]
    if not pfad.exists():
        raise SystemExit(f"{pfad} fehlt")
    log.info("--- Gebietsstand %s: %s ---", gebietsstand, pfad.name)

    run_sql("\n".join(
        f"DELETE FROM {DB_SCHEMA}.{t} WHERE gebietsstand = DATE '{gebietsstand}';"
        for t in ("gemeinde_raumgliederung", "gemeinde_typisierung",
                  "kreis_raumgliederung", "kreis_typisierung", "raumtyp")),
        f"alter Stand {gebietsstand}")

    alle_typen = {}
    for blatt, stellen, spalte, ebene in (
            (BLATT_GEM,   8, "ags",   "gemeinde"),
            (BLATT_KREIS, 5, "kreis", "kreis")):
        gliederungen, gebiete, klassen, typen = lies_blatt(pfad, blatt, stellen)
        log.info("  %s: %d Gliederungen, %s Gebietszuordnungen, %s Typisierungen",
                 blatt, len(gliederungen) - 1,
                 f"{len(gebiete):,}".replace(",", "."),
                 f"{len(klassen):,}".replace(",", "."))
        for zeilen, tabelle in ((gebiete, f"{ebene}_raumgliederung"),
                                (klassen, f"{ebene}_typisierung")):
            if zeilen:
                kopiere(tabelle, f"gebietsstand, {spalte}, gliederung, typ_id",
                        [(gebietsstand, e, p, t) for e, p, t in zeilen],
                        f"{tabelle} {gebietsstand}")
        for (p, bez, tid), (name, ist_gebiet, rest) in typen.items():
            alle_typen.setdefault(
                (p, tid), (bez, ebene, "gebiet" if ist_gebiet else "klasse", name, rest))

    kopiere("raumtyp",
            "gebietsstand, gliederung, bezeichnung, ebene, art, typ_id, typ_name, restklasse",
            [(gebietsstand, p, bez, ebene, art, tid, name, rest)
             for (p, tid), (bez, ebene, art, name, rest) in alle_typen.items()],
            f"raumtyp {gebietsstand}")
    log.info("  %s Typbezeichnungen", f"{len(alle_typen):,}".replace(",", "."))


def report():
    for tab, spalte in (("gemeinde_raumgliederung", "ags"),
                        ("gemeinde_typisierung", "ags"),
                        ("kreis_raumgliederung", "kreis"),
                        ("kreis_typisierung", "kreis")):
        log.info("--- %s.%s ---", DB_SCHEMA, tab)
        for z in query(f"""
            SELECT gebietsstand::text, count(DISTINCT {spalte})::text,
                   count(DISTINCT gliederung)::text, count(*)::text
            FROM {DB_SCHEMA}.{tab} GROUP BY 1 ORDER BY 1;
        """):
            log.info("  %s: %s Einheiten, %s Gliederungen, %s Zuordnungen", *z)

    log.info("--- Gliederungen je Stand, Gemeindeebene ---")
    for z in query(f"""
        WITH typen AS (
            SELECT gebietsstand, gliederung, art, max(bezeichnung) AS bezeichnung,
                   count(DISTINCT typ_id) AS n_typen,
                   count(*) FILTER (WHERE restklasse) AS n_rest
            FROM {DB_SCHEMA}.raumtyp WHERE ebene = 'gemeinde'
            GROUP BY 1, 2, 3),
        belegt AS (
            SELECT gebietsstand, gliederung, count(*) AS n FROM (
                SELECT gebietsstand, gliederung FROM {DB_SCHEMA}.gemeinde_raumgliederung
                UNION ALL
                SELECT gebietsstand, gliederung FROM {DB_SCHEMA}.gemeinde_typisierung) x
            GROUP BY 1, 2)
        SELECT t.gebietsstand::text, t.art, t.gliederung, t.bezeichnung,
               t.n_typen::text, coalesce(b.n, 0)::text, t.n_rest::text
        FROM typen t LEFT JOIN belegt b USING (gebietsstand, gliederung)
        ORDER BY t.gebietsstand, t.art, t.n_typen DESC;
    """):
        marke = "" if z[6] == "0" else "  (Restklasse ausgelassen)"
        log.info("  %s %-7s %-6s %-44s %5s Typen, %6s Einheiten%s",
                 z[0], z[1], z[2], (z[3] or "")[:44], z[4], z[5], marke)


    log.info("--- Vollstaendigkeit der Typisierungen ---")
    for z in query(f"""
        WITH je AS (
          SELECT gebietsstand, ags, count(*) AS n
          FROM {DB_SCHEMA}.gemeinde_typisierung GROUP BY 1, 2),
        mx AS (SELECT gebietsstand, max(n) AS m FROM je GROUP BY 1)
        SELECT je.gebietsstand::text, mx.m::text,
               count(*) FILTER (WHERE je.n = mx.m)::text,
               count(*) FILTER (WHERE je.n < mx.m)::text
        FROM je JOIN mx USING (gebietsstand)
        GROUP BY 1, 2 ORDER BY 1;
    """):
        marke = "" if z[3] == "0" else f"  {z[3]} UNVOLLSTAENDIG"
        log.info("  %s: %s Typisierungen je Gemeinde, %s vollstaendig%s", *z[:3], marke)


    log.info("--- Deckt sich die Gemeindemenge mit raum.gemeindestand? ---")
    for z in query(f"""
        SELECT r.gebietsstand::text,
               (SELECT count(DISTINCT ags)::text FROM {DB_SCHEMA}.gemeinde_typisierung x
                WHERE x.gebietsstand = r.gebietsstand),
               (SELECT count(*)::text FROM raum.gemeindestand s
                WHERE s.stichtag = r.gebietsstand),
               (SELECT count(*)::text FROM (
                  SELECT DISTINCT ags FROM {DB_SCHEMA}.gemeinde_typisierung x
                  WHERE x.gebietsstand = r.gebietsstand) a
                WHERE NOT EXISTS (SELECT 1 FROM raum.gemeindestand s
                                  WHERE s.stichtag = r.gebietsstand AND s.ags = a.ags))
        FROM (SELECT DISTINCT gebietsstand FROM {DB_SCHEMA}.gemeinde_typisierung) r
        ORDER BY 1;
    """):
        log.info("  %s: BBSR %s, VG250 %s, nur bei BBSR %s", *z)


def main():
    lieferung.merke(LIEFERUNG)
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    staende = argumente or STANDARD
    unbekannt = [s for s in staende if s not in REFERENZEN]
    if unbekannt:
        raise SystemExit(f"unbekannter Stand: {', '.join(unbekannt)}. "
                         f"Bekannt: {', '.join(sorted(REFERENZEN))}")


    run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.gemeinde_raumtyp, "
            f"{DB_SCHEMA}.kreis_raumtyp CASCADE;", "Vorgaengertabellen")

    if "--neu" in sys.argv[1:]:
        for t in ("gemeinde_raumgliederung", "gemeinde_typisierung",
                  "kreis_raumgliederung", "kreis_typisierung", "raumtyp"):
            run_sql(f"DROP TABLE IF EXISTS {DB_SCHEMA}.{t} CASCADE;", f"{t} verwerfen")
        log.warning("Tabellen verworfen.")

    run_sql(DDL, "ddl")
    for s in staende:
        laden(s)
    report()


if __name__ == "__main__":
    main()
