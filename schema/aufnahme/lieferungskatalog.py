import csv
import logging
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
sys.path.insert(0, str(REPO / "03_load_db" / "meta"))

from db import query
from load_datenlieferung import LIEFERUNGEN

SPALTEN = ("lieferung_id", "lieferung_ids")
SYSTEM  = ("information_schema", "pg_catalog", "pg_toast", "topology")
KATALOG = ("meta", "datenlieferung")

HIER          = Path(__file__).resolve().parent
ZIEL          = HIER / "lieferungskatalog.csv"
ZIEL_MD       = HIER / "lieferungskatalog.md"
ZEILENZAHLEN  = HIER / "zeilenzahlen.csv"


CODE_ENDUNGEN = (".py", ".sql")
DOKU_ENDUNGEN = (".md",)
UEBERSPRINGEN = (".git", "__pycache__", ".venv", "node_modules")


NICHT_LESEN   = {ZIEL, HIER / "inventar.csv", ZEILENZAHLEN,
                 Path(__file__).resolve()}

MAX_FUNDSTELLEN = 3

ZENTRAL = {eintrag["lieferung_id"] for eintrag in LIEFERUNGEN}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lieferungskatalog")


def _in_liste(werte):
    return ", ".join("'" + w.replace("'", "''") + "'" for w in werte)


def db_lieferungen():
    return {
        z[0]: (z[1], z[2])
        for z in query(f"""
            SELECT lieferung_id, coalesce(art, ''),
                   coalesce(array_to_string(basis, ' + '), '')
            FROM {KATALOG[0]}.{KATALOG[1]}
            ORDER BY 1;
        """)
    }


def basistabellen():
    return [
        (z[0], z[1])
        for z in query(f"""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ({_in_liste(SYSTEM)})
              AND NOT (table_schema = 'public'
                       AND table_name IN ('spatial_ref_sys'))
            ORDER BY 1, 2;
        """)
    ]


def lieferungsspalten():
    gefunden = {}
    for schema, tabelle, spalte, typ in query(f"""
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE column_name IN ({_in_liste(SPALTEN)})
          AND table_schema NOT IN ({_in_liste(SYSTEM)})
        ORDER BY 1, 2;
    """):
        if (schema, tabelle) == KATALOG:
            continue
        gefunden[(schema, tabelle)] = (spalte, typ == "ARRAY")
    return gefunden


def belegung(schema, tabelle, spalte, ist_array):
    gesamt = int(query(f"SELECT count(*) FROM {schema}.{tabelle};")[0][0])

    if ist_array:
        bedingung = f"{spalte} IS NULL OR cardinality({spalte}) = 0"
        ausdruck  = f"unnest({spalte})"
    else:
        bedingung = f"{spalte} IS NULL"
        ausdruck  = spalte

    ohne = int(query(f"""
        SELECT count(*) FROM {schema}.{tabelle} WHERE {bedingung};
    """)[0][0])

    verteilung = [
        (z[0], int(z[1]))
        for z in query(f"""
            SELECT {ausdruck} AS lieferung, count(*)
            FROM {schema}.{tabelle}
            WHERE NOT ({bedingung})
            GROUP BY 1
            ORDER BY 2 DESC, 1;
        """)
    ]
    return gesamt, ohne, verteilung


def basis_ohne_ziel():
    return [
        z[0]
        for z in query(f"""
            SELECT DISTINCT b
            FROM {KATALOG[0]}.{KATALOG[1]}, unnest(basis) AS b
            WHERE NOT EXISTS (
                SELECT 1 FROM {KATALOG[0]}.{KATALOG[1]} d
                WHERE d.lieferung_id = b)
            ORDER BY 1;
        """)
    ]


def zeilenzahlen():
    if not ZEILENZAHLEN.exists():
        log.warning("zeilenzahlen.csv fehlt - die Spalte `zeilen` bleibt leer. " "Erzeugen mit zeilenzahlen.sql.")
        return {}
    with ZEILENZAHLEN.open(encoding="utf-8", newline="") as fh:
        return {
            (z["schema"], z["tabelle"]): z["zeilen"]
            for z in csv.DictReader(fh, delimiter=";")
        }


def durchsuchbare_dateien():
    for pfad in REPO.rglob("*"):
        if not pfad.is_file() or pfad in NICHT_LESEN:
            continue
        if any(teil in UEBERSPRINGEN for teil in pfad.parts):
            continue
        if pfad.suffix in CODE_ENDUNGEN:
            yield pfad, "code"
        elif pfad.suffix in DOKU_ENDUNGEN:
            yield pfad, "doku"


def suche(begriffe, wortende=True):
    if not begriffe:
        return {}
    sortiert = sorted(begriffe, key=len, reverse=True)
    muster = re.compile(
        r"\b(" + "|".join(re.escape(b) for b in sortiert) + r")"
        + (r"\b" if wortende else ""),
        re.IGNORECASE,
    )
    treffer = {b: {"code": [], "doku": []} for b in begriffe}
    klein = {b.lower(): b for b in begriffe}

    for pfad, art in durchsuchbare_dateien():
        try:
            text = pfad.read_text(encoding="utf-8", errors="replace")
        except OSError as fehler:
            log.warning("nicht lesbar: %s (%s)", pfad, fehler)
            continue
        for nr, zeile in enumerate(text.splitlines(), start=1):
            for fund in muster.finditer(zeile):
                begriff = klein.get(fund.group(1).lower())
                if begriff is not None:
                    treffer[begriff][art].append(
                        (pfad.relative_to(REPO).as_posix(), nr, zeile))
    return treffer


def staemme(name):
    teile = name.split("_")
    return ["_".join(teile[:i]) + "_" for i in range(len(teile) - 1, 0, -1)]


def kuerzen(liste):
    if not liste:
        return ""
    orte = [f"{pfad}:{nr}" for pfad, nr, _ in liste]
    kopf = " | ".join(orte[:MAX_FUNDSTELLEN])
    if len(orte) > MAX_FUNDSTELLEN:
        return f"{kopf} | (+{len(orte) - MAX_FUNDSTELLEN} weitere, {len(orte)} gesamt)"
    return kopf


CREATE_MUSTER    = re.compile(r"\bCREATE\s+(?:\w+\s+)*TABLE\b", re.IGNORECASE)
ZUWEISUNG_MUSTER = re.compile(r"=\s*f?[\"']")


def anlegende_datei(fundstellen):
    if not fundstellen:
        return "", ""
    for pfad, _, zeile in fundstellen:
        if CREATE_MUSTER.search(zeile):
            return pfad, "create"
    for pfad, _, zeile in fundstellen:
        if ZUWEISUNG_MUSTER.search(zeile):
            return pfad, "zuweisung"
    zaehler = Counter(pfad for pfad, _, _ in fundstellen)
    return min(zaehler.items(), key=lambda kv: (-kv[1], kv[0]))[0], "nennung"


def tausender(wert):
    if wert in ("", None):
        return ""
    try:
        return f"{int(wert):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(wert)


def schreibe_markdown(zeilen, lieferungen, nur_db):
    offen = [z for z in zeilen if z[3] != "bestand"]
    text = [
        "# Lieferungskatalog - Arbeitsvorlage",
        "",
        "ERZEUGT von `lieferungskatalog.py`, nicht von Hand pflegen.",
        "",
        f"{len(zeilen)} Basistabellen, davon {len(zeilen) - len(offen)} mit "
        f"ihrer Lieferung in den Daten und {len(offen)} ohne. Fuer die " "letzteren ist einzutragen, aus welcher Datenlieferung sie stammen " "(Punkt M5 in `folgen_fuer_die_daten.md`).",
        "",
        "Gegliedert ist nach der Datei, die die Tabelle anlegt. **Welche " "Quelle dahintersteht, sagt erst deren Kopf** - die Gliederung " "stellt nur zusammen, was zusammen entsteht.",
        "",
        "| Zustand | heisst |",
        "|---|---|",
        "| `bestand` | die Tabelle fuehrt ihre Lieferung in jeder Zeile - nichts zu tun |",
        "| `skript` | der volle Name steht in einer Datei |",
        "| `stamm` | der Name entsteht zur Laufzeit; belegt ist nur sein Stamm |",
        "| `nur_doku` | der Name steht allein in der Dokumentation |",
        "| `ohne_beleg` | nirgends ein Fund |",
        "",
        "Wie sicher die Datei die anlegende ist, sagt die Spalte `woher`:",
        "",
        "| woher | heisst |",
        "|---|---|",
        "| `create` | der Name steht in einer Zeile mit `CREATE TABLE` |",
        "| `zuweisung` | der Name wird dort einer Variablen zugewiesen, die das `CREATE` einsetzt |",
        "| `nennung` | keins von beidem - nur die Datei mit den meisten Erwaehnungen, schwaechster Fall |",
        "",
        "## Vorhandene Lieferungen",
        "",
        f"{len(lieferungen)} Kennungen stehen in `meta.datenlieferung`. "
        f"{len(lieferungen) - len(nur_db)} davon pflegt " "`03_load_db/meta/load_datenlieferung.py` mit Zitat, Lizenz und "
        f"Basis; die folgenden {len(nur_db)} hat ein Ladeskript nebenbei " "angelegt und sie tragen diese Angaben nicht:",
        "",
        "```",
        "\n".join(f"{k:<32} art={lieferungen[k][0]}" for k in nur_db),
        "```",
        "",
    ]

    nach_schema = defaultdict(list)
    for zeile in zeilen:
        nach_schema[zeile[0]].append(zeile)

    for schema in sorted(nach_schema,
                         key=lambda s: (-sum(1 for z in nach_schema[s]
                                             if z[3] != "bestand"), s)):
        eintraege = nach_schema[schema]
        offen_hier = sum(1 for z in eintraege if z[3] != "bestand")
        text += [
            f"## {schema}",
            "",
            f"{len(eintraege)} Tabellen, davon {offen_hier} ohne Lieferung " "in den Daten.",
            "",
        ]

        nach_datei = defaultdict(list)
        for zeile in eintraege:
            nach_datei[zeile[10] or "(keine Fundstelle)"].append(zeile)

        for datei in sorted(nach_datei,
                            key=lambda d: (-len(nach_datei[d]), d)):
            gruppe = sorted(nach_datei[datei], key=lambda z: z[1])
            text += [
                f"### {datei} - {len(gruppe)} Tabellen",
                "",
                "| Tabelle | Zeilen | Zustand | woher | Lieferung |",
                "|---|---|---|---|---|",
            ]
            for z in gruppe:


                lieferung = z[5].replace("|", "&#124;") if z[3] == "bestand" else ""
                text.append(f"| `{z[1]}` | {tausender(z[2])} | {z[3]} "
                            f"| {z[11]} | {lieferung} |")
            text.append("")

    ZIEL_MD.write_text("\n".join(text) + "\n", encoding="utf-8")
    log.info("geschrieben: %s", ZIEL_MD)


def bericht():
    lieferungen = db_lieferungen()
    tabellen    = [t for t in basistabellen() if t != KATALOG]
    spalten     = lieferungsspalten()
    zeilen_db   = zeilenzahlen()

    log.info("--- Lieferungen in %s.%s ---", KATALOG[0], KATALOG[1])
    nur_db    = sorted(set(lieferungen) - ZENTRAL)
    nur_datei = sorted(ZENTRAL - set(lieferungen))
    log.info("  %s Lieferungen stehen in der Tabelle", len(lieferungen))
    log.info("  davon %s zentral in load_datenlieferung.py gepflegt, mit " "Zitat, Lizenz und Basis", len(set(lieferungen) & ZENTRAL))
    log.info("  %s nur von einem Ladeskript angelegt, ohne diese Angaben:",
             len(nur_db))
    for kennung in nur_db:
        log.info("      %-32s art=%s", kennung, lieferungen[kennung][0])
    if nur_datei:
        log.warning("  %s stehen in load_datenlieferung.py, aber NICHT in der " "Tabelle - das Skript lief seither nicht:", len(nur_datei))
        for kennung in nur_datei:
            log.warning("      %s", kennung)

    offen_basis = basis_ohne_ziel()
    if offen_basis:
        log.warning("  %s basis-Verweise zeigen auf keine vorhandene " "Lieferung: %s", len(offen_basis), ", ".join(offen_basis))
    else:
        log.info("  alle basis-Verweise loesen auf eine vorhandene Lieferung auf")

    log.info("--- Suche im Repo (%s) ---", REPO)
    treffer = suche({t for _, t in tabellen})


    ohne_code = {t for s, t in tabellen
                 if (s, t) not in spalten and not treffer[t]["code"]}
    stamm_je_name = {n: staemme(n) for n in ohne_code}
    stamm_treffer = suche({st for liste in stamm_je_name.values()
                           for st in liste}, wortende=False)
    log.info("  %s Tabellen ohne vollen Namenstreffer im Code, fuer sie " "zusaetzlich nach dem Namensstamm gesucht", len(ohne_code))

    def bester_stamm(name):
        for stamm in stamm_je_name.get(name, []):
            fund = stamm_treffer.get(stamm, {}).get("code")
            if fund:
                return stamm, fund
        return "", []

    zeilen_csv = []
    zaehler = {"bestand": 0, "bestand_teilweise": 0, "skript": 0,
               "stamm": 0, "nur_doku": 0, "ohne_beleg": 0}

    for schema, tabelle in tabellen:
        code = treffer[tabelle]["code"]
        doku = treffer[tabelle]["doku"]
        stamm, stamm_fund = bester_stamm(tabelle)
        gesamt = ohne = ""
        verteilung_text = ""
        spalte = ""

        if (schema, tabelle) in spalten:
            spalte, ist_array = spalten[(schema, tabelle)]
            gesamt, ohne, verteilung = belegung(schema, tabelle, spalte, ist_array)
            unbekannt = sorted({k for k, _ in verteilung} - set(lieferungen))
            verteilung_text = " | ".join(f"{k}={n}" for k, n in verteilung)
            zustand = "bestand" if (ohne == 0 and not unbekannt) else "bestand_teilweise"
            if unbekannt:
                log.warning("  %s.%s nennt %s Lieferungen, die es in %s.%s " "nicht gibt: %s", schema, tabelle, len(unbekannt),
                            KATALOG[0], KATALOG[1], ", ".join(unbekannt))
        elif code:
            zustand = "skript"
        elif stamm_fund:
            zustand = "stamm"
        elif doku:
            zustand = "nur_doku"
        else:
            zustand = "ohne_beleg"

        zaehler[zustand] += 1
        zeilen_csv.append([
            schema, tabelle, zeilen_db.get((schema, tabelle), ""), zustand,
            spalte, verteilung_text, ohne, kuerzen(code),
            f"{stamm} -> {kuerzen(stamm_fund)}" if stamm_fund else "",
            kuerzen(doku),
            *anlegende_datei(code or stamm_fund or doku),
        ])

    log.info("--- Tabellen: woher ist die Herkunft bekannt? ---")
    log.info("  %s Basistabellen geprueft (ohne %s.%s selbst und ohne Sichten)",
             len(tabellen), KATALOG[0], KATALOG[1])
    log.info("  %s tragen ihre Lieferung in jeder Zeile selbst",
             zaehler["bestand"])
    log.info("  %s haben die Spalte, aber nicht in jeder Zeile einen Wert",
             zaehler["bestand_teilweise"])
    log.info("  %s haben keine Spalte; ihr voller Name steht in einem Skript, " "aus dessen Kopf die Quelle hervorgehen muss", zaehler["skript"])
    log.info("  %s tragen einen zur Laufzeit gebildeten Namen; belegt ist " "nur der Stamm, nicht die einzelne Tabelle", zaehler["stamm"])
    log.info("  %s stehen nur in der Dokumentation, in keinem Skript",
             zaehler["nur_doku"])
    log.info("  %s haben WEDER Spalte NOCH einen Fund im Repo - zu ihnen sagt " "nichts, woher sie stammen:", zaehler["ohne_beleg"])

    for zeile in zeilen_csv:
        marke = zeile[3]
        wo = f"{zeile[0]}.{zeile[1]}"
        zeilen_text = f"{zeile[2]} Zeilen" if zeile[2] else "Zeilenzahl unbekannt"
        if marke == "ohne_beleg":
            log.info("      ohne Beleg: %-46s %s", wo, zeilen_text)
        elif marke == "nur_doku":
            log.info("      nur Doku:   %-46s %s", wo, zeile[9])
        elif marke == "stamm":
            log.info("      nur Stamm:  %-46s %s", wo, zeile[8])
        elif marke == "bestand_teilweise":
            log.info("      teilweise:  %-46s %s von %s Zeilen ohne Wert",
                     wo, zeile[6], zeile[2] or "?")

    with ZIEL.open("w", encoding="utf-8", newline="") as fh:
        schreiber = csv.writer(fh, delimiter=";")
        schreiber.writerow([
            "schema", "tabelle", "zeilen", "zustand", "lieferungsspalte",
            "lieferungen", "zeilen_ohne_lieferung",
            "fundstellen_skripte", "fundstelle_stamm", "fundstellen_doku",
            "angelegt_in", "beleg_stufe",
        ])
        schreiber.writerows(zeilen_csv)
    log.info("geschrieben: %s", ZIEL)

    schreibe_markdown(zeilen_csv, lieferungen, nur_db)


if __name__ == "__main__":
    bericht()
