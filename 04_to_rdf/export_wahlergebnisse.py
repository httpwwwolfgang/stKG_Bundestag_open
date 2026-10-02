import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from export_raum import (BASIS, PRAEFIXE, txt, iri, literal,
                         spalten_von, sql_fuer, run_copy)


AUSGABE = pfade.BEOBACHTUNGEN
ORDNER_JE_LIEFERUNG = {
    "partei_normalisierung": pfade.ORGANISATIONEN,
    "aw_api_v2":             pfade.ORGANISATIONEN,
}


def ordner_von(lieferung):
    return ORDNER_JE_LIEFERUNG.get(lieferung, AUSGABE)


MERKMALE = {

    "stimmen_erst": ("Erststimmen",
                     "Gueltige Erststimmen fuer eine Partei in dieser " "Einheit, wie die Quelle sie ausweist."),
    "stimmen_zweit": ("Zweitstimmen",
                      "Gueltige Zweitstimmen fuer eine Partei in dieser " "Einheit, wie die Quelle sie ausweist."),
    "anteil_zweit": ("Zweitstimmenanteil",
                     "Anteil der gueltigen Zweitstimmen, den eine Partei in " "dieser Einheit erhielt, als Dezimalzahl zwischen 0 und " "1. GERDA fuehrt auf Gemeinde- und Kreisebene Anteile " "statt Stimmen; die Stimmenzahl ist daraus nur mit der " "Zahl der gueltigen Stimmen zurueckzurechnen."),


    "anteil_zweit_waehlende": (
        "Zweitstimmenanteil an den Waehlenden",
        "Anteil einer Partei an den Waehlenden dieser Einheit, als " "Dezimalzahl. Der Nenner sind alle abgegebenen Stimmen " "einschliesslich der ungueltigen -- nicht die gueltigen. Die " "Anteile aller Parteien summieren sich deshalb auf weniger als " "1 (in den drei Wahljahren auf 0,96 bis 0,997); der Rest sind " "ungueltige Stimmen und nicht einzeln ausgewiesene Parteien, " "die sich nicht voneinander trennen lassen. Nicht mit " "anteil_zweit vergleichbar."),


    "wahlberechtigte": ("Wahlberechtigte",
                        "Zahl der Wahlberechtigten in dieser Einheit."),
    "waehlende": ("Waehlende",
                  "Zahl der abgegebenen Stimmen, gueltige und ungueltige."),
    "waehlende_wahlschein": ("Waehlende mit Wahlschein",
                             "Darunter jene, die mit Wahlschein gewaehlt " "haben -- ueberwiegend Briefwahl."),
    "gueltig_erst": ("gueltige Erststimmen",
                     "Summe der gueltigen Erststimmen in dieser Einheit."),
    "gueltig_zweit": ("gueltige Zweitstimmen",
                      "Summe der gueltigen Zweitstimmen in dieser Einheit."),
    "ungueltig_erst": ("ungueltige Erststimmen",
                       "Zahl der ungueltigen Erststimmen."),
    "ungueltig_zweit": ("ungueltige Zweitstimmen",
                        "Zahl der ungueltigen Zweitstimmen."),
    "bezirke": ("Wahlbezirke",
                "Zahl der Wahlbezirke, aus denen die Einheit besteht."),
    "urnenbezirke": ("Urnenwahlbezirke",
                     "Darunter die Bezirke der Urnenwahl (Bezirksart 0). " "Sonderwahlbezirke zaehlen weder hier noch bei den " "Briefbezirken mit."),
    "briefbezirke": ("Briefwahlbezirke",
                     "Darunter die Briefwahlbezirke (Bezirksart 5)."),
    "abgebende_bezirke": ("abgebende Bezirke",
                          "Bezirke, die ihre Briefwahl an einen gemeinsamen " "Vorstand abgeben. Wo der aufnehmende Verbund " "liegt, sagt diese Zahl nicht."),
}


MERKMAL_ALIAS = {
    "wahlbezirke": "bezirke",
}


GERDA_MERKMAL = {
    ("gueltige_stimmen",   "erststimme"):  "gueltig_erst",
    ("gueltige_stimmen",   "zweitstimme"): "gueltig_zweit",
    ("ungueltige_stimmen", "erststimme"):  "ungueltig_erst",
    ("ungueltige_stimmen", "zweitstimme"): "ungueltig_zweit",
    ("wahlberechtigte",    "zweitstimme"): "wahlberechtigte",
    ("waehlende",          "zweitstimme"): "waehlende",
    ("wahlberechtigte",    "erststimme"):  None,
    ("waehlende",          "erststimme"):  None,
}


BEZIRKSART = {
    "0": "stkg:bezirksart_urnenwahl",
    "5": "stkg:bezirksart_briefwahl",
    "6": "stkg:bezirksart_sonderwahlbezirk",
    "8": "stkg:bezirksart_unbestimmt",
}


ZUORDNUNG = {
    "regel":        "stkg:zuordnung_regel",
    "kompakt":      "stkg:zuordnung_kompaktform",
    "alias":        "stkg:zuordnung_alias",
    "fallback":     "stkg:zuordnung_aus_schreibweise",
    "keine_partei": "stkg:zuordnung_keine_partei",
}


UNGUELTIG = re.compile(r'[\s<>"{}|\\^`]+')
KAPUTT = set()


def kennungsteil(wert):
    return UNGUELTIG.sub("_", str(wert))


def schluessel(wert):
    s = str(wert).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"^_|_$", "", s) or "leer"


WAHL = "wahl/{wahljahr}"


R_EINHEIT = "auszaehleinheit/{wahljahr}_{einheit_id}"
R_KREIS   = "kreiswahlkreis/{wahljahr}_{kreis}_{wkr_nr}"
R_WKR     = "wahlkreisstand/{wahljahr}_{wkr_nr}"
R_GEMEINDE_WAHL = "gemeindestand/{ags}_{wahltag}"


R_GEMEINDE_21   = "gemeindestand/{ags}_2021-12-31"
R_KREISSTAND_21 = "kreisstand/{kreis}_2021-12-31"


R_KREISSTAND_JAHR = "kreisstand/{kreis}_{wahljahr}-12-31"


WAHLTAG = ("(SELECT jahr, datum FROM (SELECT " "substring(bezug from '[0-9]+')::smallint AS jahr, datum " "FROM zeit.stichtag WHERE art = 'wahltag') t)")

BESTAENDE = [


    {
        "name": "partei", "art": "knoten",
        "tabelle": "(SELECT DISTINCT partei FROM meta.partei_mapping " "WHERE verfahren <> 'keine_partei')",
        "lieferung": "partei_normalisierung",
        "klasse": "stkg:Partei, stkg:Organisation",
        "iri": "partei/{partei}",
        "felder": [("partei", "rdfs:label", "text")],
    },
    {
        "name": "parteischreibweise", "art": "knoten",


        "tabelle": "(SELECT m.partei_roh, m.partei, m.verfahren, " "        unnest(m.lieferung_ids) AS lieferung_id " " FROM meta.partei_mapping m)",
        "lieferung": None, "lieferung_spalte": "lieferung_id",
        "klasse": "stkg:Parteischreibweise",
        "iri": "parteischreibweise/{lieferung_id}/{partei_roh_key}",
        "felder": [("partei_roh", "stkg:parteischreibweise", "text"),
                   ("verfahren", "stkg:hatZuordnungsverfahren", "code",
                    "zuordnung"),
                   ("partei", "stkg:betrifftPartei", "ref", "partei/{partei}")],
        "schluesselspalten": {"partei_roh_key": "partei_roh"},

        "weglassen_wenn": {"verfahren": "keine_partei",
                           "felder": ["partei"]},
    },


    {


        "name": "erststimmen_person", "art": "knoten",
        "tabelle": """(SELECT e.wahljahr, e.wkr_nr, k.person,
                              regexp_replace(
                                regexp_replace(lower(e.partei_amtlich),
                                               '[^a-z0-9]+', '_', 'g'),
                                '^_|_$', '', 'g') AS partei_key
                         FROM wahlergebnisse.erststimmen_kandidat e
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw'
                          AND k.kennung = e.politician_id::text)""",
        "lieferung": "erststimmen_bewerber_zuordnung",
        "klasse": None,
        "iri": "beobachtung/stimmen_erst_{wahljahr}_{wkr_nr}_{partei_key}",
        "felder": [("person", "stkg:hatEmpfaengerPerson", "ref",
                    "person/{person}")],
    },
    {
        "name": "wahl", "art": "knoten",
        "tabelle": "wahlergebnisse.wahl",
        "lieferung": "wahlkreisebene_amtlich",
        "klasse": "stkg:Ereignis",
        "iri": "wahl/{wahljahr}",
        "felder": [("wahltag", "stkg:ereignisDatum", "datum"),
                   ("wahljahr", "rdfs:label", "text")],
    },


    {
        "name": "bezirksergebnis", "art": "beobachtung",
        "tabelle": "wahlergebnisse.wahlbezirksergebnis",
        "lieferung": "bwl_wahlbezirke_{wahljahr}",
        "raumbezug": R_GEMEINDE_WAHL,
        "kennung_zusatz": "{wkr_nr}_{bezirk_nr}_{bezirksart}",
        "merkmal_aus": "stimme", "wertspalte": "stimmen", "wertart": "int",
        "partei": True, "wahltag_join": True,
        "bezirksangaben": True,
    },
    {
        "name": "bezirkskennzahl", "art": "beobachtung",


        "tabelle": "(SELECT wahljahr, wkr_nr, ags, bezirk_nr, bezirksart, " "        m.merkmal, m.wert " " FROM wahlergebnisse.wahlbezirk w " " CROSS JOIN LATERAL (VALUES " "   ('wahlberechtigte', w.wahlberechtigte), " "   ('waehlende', w.waehlende), " "   ('waehlende_wahlschein', w.waehlende_wahlschein), " "   ('gueltig_erst', w.gueltig_erst), " "   ('gueltig_zweit', w.gueltig_zweit), " "   ('ungueltig_erst', w.ungueltig_erst), " "   ('ungueltig_zweit', w.ungueltig_zweit) " " ) AS m(merkmal, wert) WHERE m.wert IS NOT NULL)",
        "lieferung": "bwl_wahlbezirke_{wahljahr}",
        "raumbezug": R_GEMEINDE_WAHL,
        "kennung_zusatz": "{wkr_nr}_{bezirk_nr}_{bezirksart}",
        "merkmal_spalte": "merkmal", "wertspalte": "wert", "wertart": "int",
        "wahltag_join": True, "bezirksangaben": True,
    },
    {
        "name": "auszaehleinheit_ergebnis", "art": "beobachtung",
        "tabelle": "wahlergebnisse.kleinst_100_amtlich_ergebnis",
        "lieferung": "bwl_wahlbezirke_{wahljahr}",
        "raumbezug": R_EINHEIT,
        "merkmal_aus": "stimme", "wertspalte": "stimmen", "wertart": "int",
        "partei": True,
    },
    {
        "name": "geteilt_ergebnis", "art": "beobachtung",
        "tabelle": "wahlergebnisse.kleinst_100_geteilt_ergebnis",
        "lieferung": "grossstadt_wkr_{wahljahr}",
        "raumbezug": R_EINHEIT,
        "merkmal_aus": "stimme", "wertspalte": "stimmen", "wertart": "int",
        "partei": True,
    },
    {
        "name": "kreisergebnis", "art": "beobachtung",
        "tabelle": "wahlergebnisse.kreis_ergebnis",
        "lieferung": "kreisebene_amtlich",
        "raumbezug": R_KREIS,
        "merkmal_aus": "stimme", "wertspalte": "stimmen", "wertart": "int",
        "partei": True,
    },
    {
        "name": "wahlkreisergebnis", "art": "beobachtung",
        "tabelle": "wahlergebnisse.wahlkreis_ergebnis",
        "lieferung": "wahlkreisebene_amtlich",
        "raumbezug": R_WKR,
        "merkmal_aus": "stimme", "wertspalte": "stimmen", "wertart": "int",
        "partei": True,
    },


    {
        "name": "auszaehleinheit_kennzahl", "art": "beobachtung",
        "tabelle": "wahlergebnisse.kleinst_100_amtlich_kennzahl",
        "lieferung": None, "lieferung_spalte": "lieferung_id",
        "raumbezug": R_EINHEIT,
        "merkmal_spalte": "merkmal", "wertspalte": "wert", "wertart": "int",
    },
    {
        "name": "geteilt_kennzahl", "art": "beobachtung",
        "tabelle": "wahlergebnisse.kleinst_100_geteilt_kennzahl",
        "lieferung": None, "lieferung_spalte": "lieferung_id",
        "raumbezug": R_EINHEIT,
        "merkmal_spalte": "merkmal", "wertspalte": "wert", "wertart": "int",
    },
    {
        "name": "kreiskennzahl", "art": "beobachtung",
        "tabelle": "wahlergebnisse.kreis_kennzahl",
        "lieferung": "kreisebene_amtlich",
        "raumbezug": R_KREIS,
        "merkmal_spalte": "merkmal", "wertspalte": "wert", "wertart": "int",
    },
    {
        "name": "wahlkreiskennzahl", "art": "beobachtung",
        "tabelle": "wahlergebnisse.wahlkreis_kennzahl",
        "lieferung": "wahlkreisebene_amtlich",
        "raumbezug": R_WKR,
        "merkmal_spalte": "merkmal", "wertspalte": "wert", "wertart": "int",
    },


    {
        "name": "gerda_gemeinde_unharm", "art": "beobachtung",
        "tabelle": "gerda.gemeinde_gerda_unharm_ergebnis",
        "lieferung": "gerda_federal_muni_unharm",
        "raumbezug": R_GEMEINDE_WAHL,
        "merkmal": "anteil_zweit", "wertspalte": "anteil", "wertart": "dez",
        "partei": True, "wahltag_join": True,
    },
    {


        "name": "gerda_gemeinde_harm21", "art": "beobachtung",
        "tabelle": "gerda_seit_1990.gemeinde_harm21_ergebnis",
        "lieferung": "gerda_federal_muni_harm_21",
        "raumbezug": R_GEMEINDE_21,
        "merkmal": "anteil_zweit", "wertspalte": "anteil", "wertart": "dez",
        "partei": True,
    },
    {
        "name": "gerda_kreis_harm", "art": "beobachtung",
        "tabelle": "gerda.kreis_gerda_harm_ergebnis",
        "lieferung": "gerda_federal_cty_harm",
        "raumbezug": R_KREISSTAND_21,
        "merkmal": "anteil_zweit", "wertspalte": "anteil", "wertart": "dez",
        "partei": True,
    },
    {


        "name": "gerda_kreis_unharm", "art": "beobachtung",
        "tabelle": "gerda.kreis_gerda_unharm_ergebnis",
        "lieferung": "gerda_federal_cty_unharm",
        "raumbezug": R_KREISSTAND_JAHR,
        "merkmal": "anteil_zweit_waehlende",
        "wertspalte": "anteil", "wertart": "dez",
        "partei": True,
    },
    {
        "name": "gerda_wahlkreis", "art": "beobachtung",
        "tabelle": "gerda.wahlergebnis_gerda_wahlkreis",
        "lieferung": "gerda_federal_wkr_unharm",
        "raumbezug": R_WKR,
        "merkmal_aus": "stimme", "wertspalte": "stimmen", "wertart": "int",
        "partei": True,
    },
    {
        "name": "gerda_wahlkreis_kennzahl", "art": "beobachtung",
        "tabelle": "gerda.wahlkennzahl_gerda_wahlkreis",
        "lieferung": "gerda_federal_wkr_unharm",
        "raumbezug": R_WKR,
        "merkmal_spalte": "merkmal", "wertspalte": "wert", "wertart": "int",
        "gerda_merkmal": True,
    },
]


STIMMART = {"erststimme": "stimmen_erst", "zweitstimme": "stimmen_zweit"}


UNBEKANNT = set()
OHNE_LIEFERUNG = set()


def platzhalter(*muster):
    noetig = set()
    for m in muster:
        if m:
            noetig |= set(re.findall(r"\{(\w+)\}", m))
    return noetig


def spalten_des_bestands(b):
    noetig = platzhalter(b.get("iri"), b.get("raumbezug"),
                         b.get("kennung_zusatz"), b.get("lieferung"))
    for feld in b.get("felder", []):
        noetig.add(feld[0])
        if len(feld) > 3:
            noetig |= platzhalter(feld[3])
    for schl in ("merkmal_aus", "merkmal_spalte", "wertspalte",
                 "lieferung_spalte"):
        if b.get(schl):
            noetig.add(b[schl])
    if b.get("partei"):
        noetig.add("partei")
    if b.get("bezirksangaben"):
        noetig |= {"bezirk_nr", "bezirksart"}
    if b.get("gerda_merkmal"):
        noetig.add("stimme")
    for ziel, quelle in (b.get("schluesselspalten") or {}).items():
        noetig.add(quelle)
        noetig.discard(ziel)
    for a, _, c in b.get("zusatz", []):
        noetig |= platzhalter(a, c)
    if b.get("weglassen_wenn"):
        noetig.add(b["weglassen_wenn"]["spalte"]
                   if "spalte" in b["weglassen_wenn"]
                   else list(b["weglassen_wenn"])[0])
    return sorted(noetig - {"wahltag"})


def sql(b):
    spalten = spalten_des_bestands(b)
    auswahl = [f"q.{s}::text AS {s}" for s in spalten]
    von = f"{b['tabelle']} q"
    if b.get("wahltag_join"):
        auswahl.append("wt.datum::text AS wahltag")
        von += (" JOIN (SELECT substring(bezug from '[0-9]+')::smallint AS jahr," "              datum FROM zeit.stichtag WHERE art = 'wahltag') wt" "   ON wt.jahr = q.wahljahr")


    for ziel, quelle in (b.get("schluesselspalten") or {}).items():
        auswahl.append(
            f"regexp_replace(regexp_replace(lower(q.{quelle}::text),"
            f" '[^a-z0-9]+', '_', 'g'), '^_|_$', '', 'g') AS {ziel}")
    return f"SELECT {', '.join(auswahl)} FROM {von}"


def lieferung_von(b, z):
    if b.get("lieferung_spalte"):
        wert = z.get(b["lieferung_spalte"])
        if not wert:
            OHNE_LIEFERUNG.add((b["name"], b["lieferung_spalte"]))
        return wert
    return b["lieferung"].format(**z) if b.get("lieferung") else None


def merkmal_von(b, z):
    if b.get("merkmal"):
        return b["merkmal"]
    if b.get("merkmal_aus"):
        m = STIMMART.get(str(z[b["merkmal_aus"]]).lower())
        if m is None:
            UNBEKANNT.add((b["name"], b["merkmal_aus"], z[b["merkmal_aus"]]))
        return m
    roh = str(z[b["merkmal_spalte"]])
    if b.get("gerda_merkmal"):
        paar = (roh, str(z.get("stimme", "")).lower())
        if paar not in GERDA_MERKMAL:
            UNBEKANNT.add((b["name"], "merkmal x stimme", paar))
            return None
        roh = GERDA_MERKMAL[paar]
        if roh is None:
            return None
    roh = MERKMAL_ALIAS.get(roh, roh)
    if roh not in MERKMALE:
        UNBEKANNT.add((b["name"], "merkmal", roh))
        return None
    return roh


def tripel_beobachtung(b, z, lieferung):
    merkmal = merkmal_von(b, z)
    if merkmal is None:
        return None
    wert = z.get(b["wertspalte"])
    if wert in (None, ""):
        return None

    raum = kennungsteil(b["raumbezug"].format(**z))
    teile = [merkmal, raum.split("/", 1)[1]]
    if b.get("kennung_zusatz"):
        teile.append(kennungsteil(b["kennung_zusatz"].format(**z)))
    if b.get("partei"):
        teile.append(schluessel(z["partei"]))
    pfad = "beobachtung/" + "_".join(teile)
    if UNGUELTIG.search(pfad):
        KAPUTT.add((b["name"], pfad[:80]))
        return None
    kennung = iri(pfad)

    zeilen = ["        a                  stkg:Beobachtung",
              f"        stkg:hatMerkmal    {iri('merkmal/' + lieferung + '/' + merkmal)}",
              f"        stkg:hatRaumbezug  {iri(raum)}",
              f"        stkg:wert          {literal(wert, b['wertart'])}"]
    if "wahljahr" in z:
        zeilen.append(f"        stkg:hatBezugsereignis  {iri(WAHL.format(**z))}")
    if b.get("partei"):


        zeilen.append("        stkg:hatEmpfaengerPartei  "
                      + iri("partei/" + schluessel(z["partei"])))
    if b.get("bezirksangaben"):
        if z.get("bezirk_nr"):
            zeilen.append(f"        stkg:bezirksnummer  {txt(z['bezirk_nr'])}")
        art = z.get("bezirksart")
        if art:
            code = BEZIRKSART.get(str(art).strip())
            if code is None:
                UNBEKANNT.add((b["name"], "bezirksart", art))
            else:
                zeilen.append(f"        stkg:hatBezirksart  {code}")

    return f"    {kennung}\n" + " ;\n".join(zeilen) + " .\n", merkmal


def tripel_knoten(b, z, lieferung):
    weg = set()
    regel = b.get("weglassen_wenn")
    if regel:
        spalte = [k for k in regel if k != "felder"][0]
        if str(z.get(spalte)) == regel[spalte]:
            weg = set(regel["felder"])


    zeilen = [f"        a  {b['klasse']}"] if b.get("klasse") else []
    for feld in b["felder"]:
        spalte, praedikat, art = feld[0], feld[1], feld[2]
        if spalte in weg:
            continue
        wert = z.get(spalte)
        if wert in (None, ""):
            continue
        if art == "ref":
            objekt = iri(feld[3].format(**z))
        elif art == "code":
            objekt = ZUORDNUNG.get(str(wert).lower())
            if objekt is None:
                UNBEKANNT.add((b["name"], spalte, wert))
                continue
        else:
            objekt = literal(wert, art)
        zeilen.append(f"        {praedikat}  {objekt}")

    pfad = kennungsteil(b["iri"].format(**z))
    if UNGUELTIG.search(pfad):
        KAPUTT.add((b["name"], pfad[:80]))
        return None, None
    aus = f"    {iri(pfad)}\n" + " ;\n".join(zeilen) + " .\n"
    for subj, praedikat, obj in b.get("zusatz", []):
        aus += (f"    {iri(kennungsteil(subj.format(**z)))} {praedikat} "
                f"{iri(kennungsteil(obj.format(**z)))} .\n")
    return aus, None


def kopf(lieferung):
    zeilen = [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE]
    zeilen.append('@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .')
    zeilen += ["", f"{iri('lieferung/' + lieferung)} {{", ""]
    return "\n".join(zeilen)


def merkmalsbloecke(lieferung, gebraucht):
    aus = []
    for k in sorted(gebraucht):
        bez, definition = MERKMALE[k]
        aus.append("\n".join([
            f"    {iri('merkmal/' + lieferung + '/' + k)}",
            "        a                        stkg:Merkmal ;",
            f"        stkg:merkmalsbezeichnung {txt(bez)} ;",
            f"        stkg:merkmalsdefinition  {txt(definition)} .",
            ""]))
    return aus


def baue(namen, max_mb):
    pfade.pruefe(AUSGABE, *ORDNER_JE_LIEFERUNG.values())
    tmp = AUSGABE / "_export.csv"
    grenze = max_mb * 1024 * 1024 if max_mb else 0

    offen = {}
    teile = defaultdict(list)
    merkmale = defaultdict(set)

    def dateiname(lieferung, nr):
        return ordner_von(lieferung) / (f"{lieferung}.trig" if nr == 1
                                        else f"{lieferung}_{nr:02d}.trig")

    def oeffne(lieferung, nr):
        if nr == 1:
            ordner = ordner_von(lieferung)
            for alt in list(ordner.glob(f"{lieferung}.trig")) + \
                       list(ordner.glob(f"{lieferung}_[0-9][0-9].trig")):
                alt.unlink()
        pfad = dateiname(lieferung, nr)
        fh = pfad.open("w", encoding="utf-8")
        fh.write(kopf(lieferung))
        teile[lieferung].append(pfad)
        return fh

    def schliesse(lieferung, fh):
        for block in merkmalsbloecke(lieferung, merkmale[lieferung]):
            fh.write(block)
        fh.write("}\n")
        fh.close()

    def schreibe(lieferung, text):
        if lieferung not in offen:
            offen[lieferung] = [oeffne(lieferung, 1), 1, 0]
        e = offen[lieferung]
        if grenze and e[2] + len(text) > grenze:
            schliesse(lieferung, e[0])
            if e[1] == 1:
                erst = teile[lieferung][0]
                neu = erst.with_name(f"{lieferung}_01.trig")
                erst.replace(neu)
                teile[lieferung][0] = neu
            e[1] += 1
            e[0] = oeffne(lieferung, e[1])
            e[2] = 0
        e[0].write(text)
        e[2] += len(text)

    try:
        for b in BESTAENDE:
            if namen and b["name"] not in namen:
                continue
            run_copy(sql(b), tmp, b["name"])
            anzahl = 0
            with tmp.open(encoding="utf-8", newline="") as fh:
                for z in csv.DictReader(fh):
                    lieferung = lieferung_von(b, z)
                    if not lieferung:
                        continue
                    if b["art"] == "beobachtung":
                        ergebnis = tripel_beobachtung(b, z, lieferung)
                    else:
                        ergebnis = tripel_knoten(b, z, lieferung)
                    if ergebnis is None:
                        continue
                    text, merkmal = ergebnis
                    if merkmal:
                        merkmale[lieferung].add(merkmal)
                    schreibe(lieferung, text)
                    anzahl += 1
            print(f"  {b['name']:<28} {anzahl:>9} Zeilen", flush=True)
    finally:
        for lieferung, e in sorted(offen.items()):
            schliesse(lieferung, e[0])
        if tmp.exists():
            tmp.unlink()

        gesamt = dateien = 0
        for lieferung in sorted(teile):
            for pfad in teile[lieferung]:
                gross = pfad.stat().st_size
                gesamt += gross
                dateien += 1
                print(f"  -> {pfad.name:<40} {gross/1024/1024:>8.1f} MB")
        print(f"\n{dateien} Dateien in {len(teile)} Named Graphs, "
              f"{gesamt/1024/1024:.1f} MB gesamt")

        if namen:
            print("\nTEILLAUF - nur die genannten Bestaende. Die Dateien " "enthalten NICHT alles, was in diese Graphen gehoert; " "beim Laden wuerde der Rest fehlen.")
        if OHNE_LIEFERUNG:
            print("\nZeilen ohne Lieferung - nicht geschrieben:")
            for name, spalte in sorted(OHNE_LIEFERUNG):
                print(f"    {name}: {spalte} leer")
        if UNBEKANNT:
            print(f"\n{len(UNBEKANNT)} Werte ohne Eintrag - die Zeile "
                  f"wurde NICHT geschrieben:")
            for name, spalte, wert in sorted(UNBEKANNT):
                print(f"    {name}.{spalte} = {wert!r}")


        if KAPUTT:
            print("\n%d UNGUELTIGE KENNUNGEN - nicht geschrieben:"
                  % len(KAPUTT))
            for name, pfad in sorted(KAPUTT)[:20]:
                print("    %-24s %s" % (name, pfad))
            raise SystemExit(
                "%d ungueltige Kennungen. Die Ausgabe ist unvollstaendig " "und darf nicht geladen werden." % len(KAPUTT))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("bestand", nargs="*", help="nur diese Bestaende")
    p.add_argument("--max-mb", type=int, default=200,
                   help="Umbruch in Teildateien ab dieser Groesse (0 = nie)")
    a = p.parse_args()
    bekannt = {b["name"] for b in BESTAENDE}
    unbekannt = set(a.bestand) - bekannt
    if unbekannt:
        raise SystemExit(f"unbekannte Bestaende: {', '.join(sorted(unbekannt))}\n"
                         f"bekannt: {', '.join(sorted(bekannt))}")
    baue(set(a.bestand), a.max_mb)
