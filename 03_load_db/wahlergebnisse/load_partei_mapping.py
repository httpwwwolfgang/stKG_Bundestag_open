import re
import sys
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

DB_SCHEMA   = "wahlergebnisse"
META_SCHEMA = "meta"
TABELLE     = "partei_mapping"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("partei")


REGELN = [

    (r"^CDU$",                                  "cdu"),
    (r"CHRISTLICH.DEMOKRATISCHE UNION",         "cdu"),
    (r"^CSU$",                                  "csu"),
    (r"CHRISTLICH.SOZIALE UNION",               "csu"),
    (r"^SPD$",                                  "spd"),
    (r"SOZIALDEMOKRATISCHE PARTEI",             "spd"),


    (r"^GR[UÜ]NE|^GR[UÜ].?NF|^B[UÜ]NDNIS\s*90.*GR|B[UÜ].*90.*GR[UÜ]|^DIE GR[UÜ]NE",
                                                "gruene"),
    (r"^FDP|^F[.]D[.]P",                        "fdp"),
    (r"^FDP/DVP",                               "fdp"),
    (r"FREIE DEMOKRATISCHE PARTEI",             "fdp"),
    (r"LINKE|^PDS|^LL.PDS|^DIE LINKE",          "linke_pds"),
    (r"^AFD$|^AFD\s|ALTERNATIVE F[UÜ]R DEUTSCHLAND", "afd"),
    (r"^BSW$|^BSW\s|WAGENKNECHT",               "bsw"),

    (r"^NPD",                                   "npd"),
    (r"^REP$|REPUBLIKANER",                     "rep"),
    (r"^DVU$",                                  "dvu"),
    (r"^III[.]|^DER III",                       "iii_weg"),
    (r"^DIE.?RECHTE",                           "die_rechte"),
    (r"HEIMAT$",                                "npd"),

    (r"^DKP$",                                  "dkp"),
    (r"DEUTSCHE KOMMUNISTISCHE PARTEI",         "dkp"),
    (r"^MLPD$",                                 "mlpd"),
    (r"^SGP$",                                  "sgp"),

    (r"^PIRATEN",                               "piraten"),
    (r"^FREIE W[AÄ]HLER|^FW$|^FWG",             "freie_wahler"),
    (r"^BVB.*FREIE",                            "freie_wahler"),
    (r"[OÖ]DP$|^[OÖ]DP\s",                      "odp"),
    (r"[OÖ]KOLOGISCH.{0,4}DEMOKRATISCHE",       "odp"),
    (r"^DIE.?PARTEI$|^PARTEI$",                 "die_partei"),


    (r"ELITENF[OÖ]RDERUNG|RECHTSSTAAT.*TIERSCHUTZ.*ELITEN", "die_partei"),
    (r"TIER.?SCHUTZ.*ALLIANZ",                  "tierschutzallianz"),
    (r"TIERSCHUTZ.*HIER",                       "tierschutz_hier"),
    (r"TIERSCHUTZ",                             "tierschutz"),
    (r"^V.PARTEI",                              "v_partei3"),
    (r"^SSW$",                                  "ssw"),
    (r"^VOLT$",                                 "volt"),
    (r"^DIEBASIS|^DIE BASIS",                   "diebasis"),
    (r"B[UÜ]NDNIS\s*C$|^B[UÜ]NDNIS C\s",        "bundnis_c"),
    (r"B[UÜ]NDNIS.*DEUTSCHLAND",                "bundnis_deutschland"),
    (r"^FAMILIE$|^FAMILIEN",                    "familie"),
    (r"^BAYERNPARTEI$|^BP$",                    "bp"),
    (r"^SCHILL|^PRO$|^RECHTSSTAATLICHE|RECHTSSTAATLICH.*OFFENSIVE", "schill"),
    (r"^STATT",                                 "statt_partei"),
    (r"^GRAUE|^DIE GRAUEN",                     "graue"),
    (r"^ZENTRUM$",                              "zentrum"),
    (r"^FREIE SACHSEN",                         "freie_sachsen"),
    (r"WERTEUNION|^WU$",                        "werteunion"),
    (r"^TEAM TODENHÖFER|^TEAM TODENH",          "team_todenhofer"),
    (r"^HUMANISTEN|^DIE HUMANISTEN",            "die_humanisten"),
    (r"^VIOLETTEN|^DIE VIOLETTEN",              "violetten"),
    (r"^VOLKSAB.?STIMMUNG",                     "volksabstimmung"),
    (r"^LKR$|^LIBERAL.KONSERVATIV",             "lkr"),
    (r"^PRO DEUTSCHLAND|^PRO NRW|^PRO CHEMNITZ", "pro_deutschland"),
    (r"^RENTNER|^RRP",                          "rentner"),
    (r"^BIG$",                                  "big"),
    (r"^UNABH[AÄ]NGIGE",                        "unabhangige"),
    (r"^AUFBRUCH",                              "aufbruch"),
    (r"^BFB$|^B[UÜ]RGER F[UÜ]R",                "bfb"),
    (r"^BGE$",                                  "bge"),
    (r"^B[UÜ]SO$|B[UÜ]RGERRECHTSBEWEGUNG.SOLIDARIT", "bueso"),


    (r"GESUNDHEITS.*FORSCHUNG|VERJ.NGUNGSFORSCHUNG", "gesundheitsforschung"),
    (r"^MERA25",                                "mera25"),
    (r"^PATRIOTEN",                             "patrioten"),
    (r"^PBC$",                                  "pbc"),
    (r"PARTEI BIBELTREUER CHRISTEN",            "pbc"),
    (r"^PDV$|^PARTEI DER VERNUNFT",             "partei_der_vernunft"),
    (r"^DSU$",                                  "dsu"),
    (r"^AB JETZT",                              "ab_jetzt"),
    (r"^AD.?DEMOKRATEN",                        "ad_demokraten"),
    (r"^DIB$|^DEMOKRATIE IN BEWEGUNG",          "dib"),
    (r"^DM$|^DEUTSCHE MITTE",                   "dm"),
    (r"^MENSCHLICHE WELT",                      "menschliche_welt"),
    (r"GARTENPARTEI",                           "gartenpartei"),
    (r"^NATUR.?GESETZ",                         "naturgesetz"),
    (r"^DA$|^DEMOKRATIEALTERNATIVE",            "da"),
    (r"^50.?PLUS",                              "50plus"),
    (r"^GB.?BHE",                               "gb_bhe"),
    (r"^B[UÜ]NDNIS.?DKP.?KPD",                  "buendnis_dkp_kpd"),
    (r"^OFFEN.*SIVE.*D",                        "offensive_d"),
    (r"^CHR.?L$",                               "chr_l"),


    (r"^PARTEI DER NICHTW[AÄ]HLER|^NICHTW[AÄ]HLER", "nichtwaehler"),
    (r"^M[UÜ]NDIGE B[UÜ]RGER",                  "muendige"),


    (r"^90.?GREENS|^GREENS.?90",                "gruene"),
    (r"^L.?PDS",                                "linke_pds"),
    (r"^PIRATES",                               "piraten"),
]


SAMMELSPALTEN = {
    "cdu_csu": ["cdu", "csu"],
    "far_right": None,
    "far_left": None,
    "far_left_w_linke": None,
}


def gerda_spalten(pname):
    schluessel, verfahren = normalise_party(pname)
    if schluessel not in SAMMELSPALTEN:
        return [schluessel], verfahren
    aufloesung = SAMMELSPALTEN[schluessel]
    if aufloesung is None:
        raise ValueError(
            "%r normalisiert zu %r - eine GERDA-Sammelspalte ohne feste " "Zusammensetzung. Aus einem Parteinamen kann das nicht entstehen; " "hier stimmt etwas nicht." % (pname, schluessel))
    return list(aufloesung), verfahren


KOMPAKT = {
    "CDU": "cdu", "CSU": "csu", "SPD": "spd",
    "FDP": "fdp", "FDPDVP": "fdp",
    "NPD": "npd", "DVU": "dvu", "DKP": "dkp",
    "PBC": "pbc", "REP": "rep", "SSW": "ssw",
}


KEINE_PARTEI = {
    "WGR/EB",
    "ÜBRIGE",
    "SONSTIGE",
}


def _snake(p):
    cleaned = p.lower()
    cleaned = re.sub(r"[^a-z0-9äöüß]+", "_", cleaned)
    for such, ersatz in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        cleaned = cleaned.replace(such, ersatz)
    cleaned = re.sub(r"^_|_$", "", cleaned)
    return re.sub(r"_+", "_", cleaned)


def normalise_party(pname):


    ann = re.search(r"\(20[0-9]{2}:[^)]*\)", pname)
    if ann:
        inyear = re.sub(r"\)$", "", re.sub(r"^\(20[0-9]{2}:\s*", "", ann.group(0)))
        if inyear.strip():
            pname = inyear.strip()

    p = pname.strip()
    p_up = p.upper()
    p_cmp = re.sub(r"[\s.]+", "", p_up)

    if p_cmp in KEINE_PARTEI:
        return _snake(p), "keine_partei"

    if p_cmp in KOMPAKT:
        return KOMPAKT[p_cmp], "kompakt"
    if p_cmp.startswith("FWG"):
        return "freie_wahler", "kompakt"

    for muster, ziel in REGELN:
        if re.search(muster, p_up):
            return ziel, "regel"


    return _snake(p), "fallback"


DDL = f"""
CREATE SCHEMA IF NOT EXISTS {META_SCHEMA};
CREATE TABLE IF NOT EXISTS {META_SCHEMA}.{TABELLE} (
    partei_roh    TEXT PRIMARY KEY,
    partei        TEXT NOT NULL,



    verfahren     TEXT NOT NULL,
    in_gerda      BOOLEAN,
    stimmen       BIGINT
);
CREATE INDEX IF NOT EXISTS {TABELLE}_partei ON {META_SCHEMA}.{TABELLE} (partei);

ALTER TABLE {META_SCHEMA}.{TABELLE}
    ADD COLUMN IF NOT EXISTS lieferung_ids TEXT[];
CREATE INDEX IF NOT EXISTS {TABELLE}_lieferung
    ON {META_SCHEMA}.{TABELLE} USING GIN (lieferung_ids);

COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.lieferung_ids IS
 'lieferung_id-Werte aus meta.datenlieferung, in denen dieser Rohname genau so '
 'vorkommt. bwl_wahlbezirke_2013/2017/2021 = amtliche Wahlbezirksstatistik, '
 'aw_api_v2 = abgeordnetenwatch. Der Rohname gehoert der Lieferung: dieselbe '
 'Partei heisst amtlich afd und bei abgeordnetenwatch AfD.';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.stimmen IS
 'Zweitstimmen ueber alle Wahlen, NUR fuer Namen aus der amtlichen Statistik. '
 'Bei Namen, die nur aus aw_api_v2 stammen, NULL - jene Lieferung fuehrt keine '
 'Stimmen.';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.verfahren IS
 'kompakt / regel / fallback aus normalise_party(). Dazu keine_partei fuer '
 'Rohnamen, die gar keine Partei bezeichnen - bisher nur Einzelbewerbung, das '
 'Label fuer parteilose Bewerber bei abgeordnetenwatch (351 Kandidaturen).';
"""


EIGENE_LIEFERUNGEN = ("bwl_wahlbezirke_2013", "bwl_wahlbezirke_2017",
                      "bwl_wahlbezirke_2021")


def lit(wert):
    return "'" + str(wert).replace("'", "''") + "'"


def lade():


    roh = query(f"""
        SELECT partei, sum(stimmen),
               string_agg(DISTINCT wahljahr::text, ',' ORDER BY wahljahr::text)
        FROM {DB_SCHEMA}.wahlbezirksergebnis
        GROUP BY 1 ORDER BY 1;
    """)
    log.info("%d verschiedene Parteinamen in der amtlichen Statistik", len(roh))

    gerda = {name for name, in query(f"""
        SELECT DISTINCT partei FROM gerda.wahlergebnis_gerda_wahlkreis;
    """)}

    werte, fallbacks, unbekannt = [], [], []
    for name, stimmen, jahre in roh:
        schluessel, verfahren = normalise_party(name)
        drin = schluessel in gerda
        ids = ", ".join(lit(f"bwl_wahlbezirke_{j}") for j in jahre.split(","))
        werte.append(f"({lit(name)}, {lit(schluessel)}, {lit(verfahren)}, "
                     f"{'true' if drin else 'false'}, {stimmen}, "
                     f"ARRAY[{ids}])")
        if verfahren == "fallback":
            fallbacks.append((name, schluessel, drin))
        if not drin:
            unbekannt.append((name, schluessel, verfahren, int(stimmen)))


    eigene = ", ".join(lit(x) for x in EIGENE_LIEFERUNGEN)
    sql = (f"DELETE FROM {META_SCHEMA}.{TABELLE}\n"
           f" WHERE lieferung_ids IS NULL\n"
           f"    OR lieferung_ids && ARRAY[{eigene}];\n"
           f"INSERT INTO {META_SCHEMA}.{TABELLE} "
           f"(partei_roh, partei, verfahren, in_gerda, stimmen, lieferung_ids)"
           f"\nVALUES\n"
           + ",\n".join(werte) + ";\n")
    tmp = Path(tempfile.gettempdir()) / "partei_mapping.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, label="partei_mapping")
    tmp.unlink(missing_ok=True)

    if fallbacks:
        log.info("--- Ueber den Fallback normalisiert (keine Regel gegriffen) ---")
        for name, schluessel, drin in fallbacks:
            log.info("  %-34s -> %-24s %s", name, schluessel,
                     "in GERDA" if drin else "NICHT in GERDA")
    return unbekannt


def report(unbekannt):
    log.info("--- Verfahren ---")
    for zeile in query(f"""
        SELECT verfahren, count(*), count(*) FILTER (WHERE in_gerda) AS in_gerda,
               to_char(sum(stimmen), 'FM999G999G999') AS stimmen
        FROM {META_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 2 DESC;
    """):
        log.info("  %-10s %4s Namen, davon %s in GERDA, %s Stimmen", *zeile)

    if unbekannt:
        log.warning("--- Schluessel, die GERDA nicht kennt ---")
        for name, schluessel, verfahren, stimmen in sorted(
                unbekannt, key=lambda x: -x[3]):
            log.warning("  %-34s -> %-22s (%s) %s Stimmen",
                        name, schluessel, verfahren, f"{stimmen:,}".replace(",", "."))

    log.info("--- Gegenprobe: Stimmensummen je Partei gegen GERDA ---")
    zeilen = query(f"""
        WITH eigen AS (
            SELECT r.wahljahr, m.partei, sum(r.stimmen) AS summe
            FROM {DB_SCHEMA}.wahlbezirksergebnis r
            JOIN {META_SCHEMA}.{TABELLE} m ON m.partei_roh = r.partei
            WHERE r.stimme = 'zweitstimme'
            GROUP BY 1, 2),
        gerda AS (
            SELECT wahljahr, partei, sum(stimmen) AS summe
            FROM gerda.wahlergebnis_gerda_wahlkreis
            WHERE stimme = 'zweitstimme' GROUP BY 1, 2)
        SELECT coalesce(e.wahljahr, g.wahljahr), coalesce(e.partei, g.partei),
               coalesce(e.summe, 0), coalesce(g.summe, 0),
               coalesce(e.summe, 0) - coalesce(g.summe, 0) AS differenz
        FROM eigen e FULL JOIN gerda g USING (wahljahr, partei)
        WHERE coalesce(e.summe, 0) <> coalesce(g.summe, 0)
          AND coalesce(g.summe, 0) > 0
        ORDER BY abs(coalesce(e.summe, 0) - coalesce(g.summe, 0)) DESC LIMIT 20;
    """)
    if not zeilen:
        log.info("  alle Parteien stimmen exakt ueberein")
    for jahr, partei, eigen, gerda_summe, diff in zeilen:
        log.warning("  %s %-22s eigen %12s  GERDA %12s  Differenz %s",
                    jahr, partei, eigen, gerda_summe, diff)

    log.info("--- Abdeckung: wie viele Stimmen sind zugeordnet? ---")
    for zeile in query(f"""
        SELECT r.wahljahr, r.stimme,
               to_char(sum(r.stimmen), 'FM999G999G999') AS gesamt,
               to_char(sum(r.stimmen) FILTER (WHERE m.in_gerda),
                       'FM999G999G999') AS gerda_bekannt,
               count(DISTINCT m.partei) AS parteien
        FROM {DB_SCHEMA}.wahlbezirksergebnis r
        JOIN {META_SCHEMA}.{TABELLE} m ON m.partei_roh = r.partei
        GROUP BY 1, 2 ORDER BY 1, 2;
    """):
        log.info("  %s %s: %s Stimmen, davon %s bei GERDA bekannt, %s Parteien",
                 *zeile)


def main():
    run_sql(DDL, "ddl")
    report(lade())


if __name__ == "__main__":
    main()
