import csv
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))

from load_datenlieferung import LIEFERUNGEN

REPO = HIER.parents[1]


ZIEL_MD = REPO / "schema" / "export" / "datenlieferungen_anhang.md"
ZIEL_CSV = REPO / "schema" / "export" / "datenlieferungen.csv"


ARTEN = [
    ("amtlich", "Amtliche Lieferungen",
     "Von einer amtlichen Stelle herausgegeben und ohne weitere " "Pruefung als massgeblich uebernommen."),
    ("forschung", "Forschungsdatensaetze",
     "Von Wissenschaftlerinnen und Wissenschaftlern erhoben und " "publiziert, mit eigener Zitation."),
    ("zivilgesellschaftlich", "Zivilgesellschaftliche Lieferungen",
     "Von einer nichtstaatlichen, nichtakademischen Stelle erhoben. " "Der eigene Wert ist noetig, weil \"amtlich\" eine Gewaehr " "behauptet, die hier niemand gibt."),
    ("abgeleitet", "Im Projekt gerechnete Lieferungen",
     "Nicht uebernommen, sondern aus einer oder mehreren Lieferungen " "berechnet. Die Spalte \"beruht auf\" nennt sie."),
]


def istwert(eintrag, feld):
    if feld not in eintrag:
        return "--", "fehlt"
    wert = eintrag[feld]
    if wert is None:
        return "nicht angegeben", "nicht_angegeben"
    text = str(wert).strip()
    if not text:
        return "nicht angegeben", "nicht_angegeben"
    return text, "wert"


def zeitbezug(eintrag):
    teile = []
    if eintrag.get("wahljahr"):
        teile.append(str(eintrag["wahljahr"]))
    if eintrag.get("gebietsstand"):
        teile.append(f"Gebietsstand {eintrag['gebietsstand']}")
    return " · ".join(teile) if teile else "--"


def kuerze(text, laenge=160):
    text = " ".join(str(text).split())
    if len(text) <= laenge:
        return text
    return text[:laenge - 1].rstrip() + "…"


def escape_md(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


NACH_ID = {e["lieferung_id"]: e for e in LIEFERUNGEN}


def wurzeln_von(kennung, gesehen=None):
    gesehen = gesehen or set()
    if kennung in gesehen or kennung not in NACH_ID:
        return set()
    basis = NACH_ID[kennung].get("basis") or []
    if not basis:
        return {kennung}
    aus = set()
    for b in basis:
        aus |= wurzeln_von(b, gesehen | {kennung})
    return aus


def stufe_von(kennung, gesehen=None):
    gesehen = gesehen or set()
    if kennung in gesehen or kennung not in NACH_ID:
        return 0
    basis = NACH_ID[kennung].get("basis") or []
    if not basis:
        return 0
    return 1 + max(stufe_von(b, gesehen | {kennung}) for b in basis)


TEXTE = {

    "gerda_federal_muni_unharm": (
        "GERDA Gemeindeergebnisse, Briefwahl verteilt",
        "Bundestagswahlergebnisse je Gemeinde, mit der gemeinsamen " "Briefwahl rechnerisch auf die Gemeinden verteilt."),
    "gerda_federal_muni_harm_21": (
        "GERDA Gemeindeergebnisse auf Gebietsstand 2021",
        "Bundestagswahlergebnisse je Gemeinde seit 1990, auf den " "Gebietsstand 31.12.2021 umgerechnet."),
    "gerda_federal_cty_unharm": (
        "GERDA Kreisergebnisse",
        "Bundestagswahlergebnisse je Kreis im Gebietsstand der " "jeweiligen Wahl."),
    "gerda_federal_cty_harm": (
        "GERDA Kreisergebnisse auf Gebietsstand 2021",
        "Bundestagswahlergebnisse je Kreis seit 1990, auf einen festen " "Gebietsstand umgerechnet."),
    "gerda_federal_wkr_unharm": (
        "GERDA Wahlkreisergebnisse",
        "Erst- und Zweitstimmen je Partei fuer die 299 Wahlkreise, dazu " "die Partei des Direktmandats."),


    "bwl_wahlbezirke_2013": (
        "Wahlbezirksstatistik 2013",
        "Wahlergebnisse je Wahlbezirk, der feinsten Ebene; jede Zeile " "nennt Gemeinde und Wahlkreis im Stand des Wahltags."),
    "bwl_wahlbezirke_2017": (
        "Wahlbezirksstatistik 2017",
        "Wahlergebnisse je Wahlbezirk, der feinsten Ebene; jede Zeile " "nennt Gemeinde und Wahlkreis im Stand des Wahltags."),
    "bwl_wahlbezirke_2021": (
        "Wahlbezirksstatistik 2021",
        "Wahlergebnisse je Wahlbezirk, der feinsten Ebene; jede Zeile " "nennt Gemeinde und Wahlkreis im Stand des Wahltags."),
    "wahlkreisebene_amtlich": (
        "Wahlergebnisse je Wahlkreis",
        "Erst- und Zweitstimmen je Partei fuer die 299 Wahlkreise, aus " "den Wahlbezirken aufsummiert."),
    "bwl_wahlkreisgeometrie": (
        "Wahlkreisgeometrien",
        "Flaechen der 299 Wahlkreise je Wahl, mit Nummer, Name und " "Bundesland."),
    "bwl_strukturdaten_2013": (
        "Strukturdaten der Wahlkreise 2013",
        "43 Strukturmerkmale je Wahlkreis: Bevoelkerung, Flaeche, " "Schulabschluesse, Einkommen, Arbeitslosenquoten."),
    "bwl_strukturdaten_2017": (
        "Strukturdaten der Wahlkreise 2017",
        "52 Strukturmerkmale je Wahlkreis: Bevoelkerung, Flaeche, " "Schulabschluesse, Einkommen, Arbeitslosenquoten."),
    "bwl_strukturdaten_2021": (
        "Strukturdaten der Wahlkreise 2021",
        "52 Strukturmerkmale je Wahlkreis: Bevoelkerung, Flaeche, " "Schulabschluesse, Einkommen, Arbeitslosenquoten."),
    "bwl_zuordnung_2017": (
        "Zuordnungsliste Gemeinde-Wahlkreis 2017",
        "Amtliche Zuordnung jeder Gemeinde zu ihrem Wahlkreis; im " "Bestand nur fuer die gemeindefreien Gebiete verwendet."),
    "bwl_zuordnung_2021": (
        "Zuordnungsliste Gemeinde-Wahlkreis 2021",
        "Amtliche Zuordnung jeder Gemeinde zu ihrem Wahlkreis; im " "Bestand nur fuer die gemeindefreien Gebiete verwendet."),
    "gv100ad_2013": (
        "Gemeindeverzeichnis GV100AD 2013",
        "Gemeindeverzeichnis mit dem Wahlkreis je Gemeinde; im Bestand " "nur fuer die gemeindefreien Gebiete verwendet."),


    "bkg_vg250": (
        "Verwaltungsgebiete VG250",
        "Flaechen und Schluessel der Gemeinden, Kreise und Bundeslaender " "je Stichtag."),
    "bkg_gn250": (
        "Geographische Namen GN250",
        "Benannte Oertlichkeiten mit Punktkoordinate: Ortslagen, " "Gewaesser, Waelder, Bauwerke und weitere."),
    "destatis_gebietsaenderungen": (
        "Gebietsaenderungen der Gemeinden",
        "Fusionen, Eingliederungen, Schluessel- und Namensaenderungen " "von Gemeinden und Kreisen, mit Wirksamkeitsdatum."),
    "bbsr_ags_crosswalk": (
        "Umsteigeschluessel Gemeinden",
        "Umrechnungsgewichte zwischen Gemeindestaenden, nach " "Bevoelkerung und nach Flaeche."),
    "bbsr_cty_crosswalk": (
        "Umsteigeschluessel Kreise",
        "Umrechnungsgewichte zwischen Kreisstaenden, nach Bevoelkerung " "und nach Flaeche."),


    "bbsr_inkar_2024": (
        "INKAR, Ausgabe 03/2024",
        "Strukturindikatoren fuer Gemeinden und Kreise, auf einen festen " "Gebietsstand zeitreihenbereinigt."),
    "bbsr_raumgliederung": (
        "BBSR-Raumgliederungen",
        "Zuordnung jeder Gemeinde und jedes Kreises zu den " "Raumabgrenzungen und Typisierungen des BBSR."),
    "bbsr_wachsen_schrumpfen_2021": (
        "Wachsende und schrumpfende Gemeinden",
        "Einstufung jeder Gemeinde in fuenf Entwicklungsklassen, " "verdichtet aus sechs Indikatoren."),
    "destatis_regionaldatenbank": (
        "Regionaldatenbank Deutschland",
        "Strukturdaten fuer Gemeinden und Kreise im Gebietsstand des " "jeweiligen Berichtsjahres."),


    "aw_api_v2": (
        "Abgeordnetenwatch API v2",
        "Personen, Mandate und Kandidaturen, Nebentaetigkeiten, " "Ausschuesse und Landeslisten der Wahlen 2013, 2017 und 2021."),
    "bt_mdb_stammdaten": (
        "Stammdaten der Abgeordneten seit 1949",
        "Amtliche Stammdaten aller Abgeordneten: Wahlkreis, Mandatsart, " "Mandatszeitraum und biografische Angaben."),
    "bt_ausgeschiedene": (
        "Ausgeschiedene Abgeordnete und Nachfolger",
        "Wer wann ausgeschieden ist und wer nachgerueckt ist, je " "Wahlperiode."),
    "bt_namentliche_abstimmungen": (
        "Namentliche Abstimmungen",
        "Stimmverhalten jedes Mitglieds bei jeder namentlichen " "Abstimmung, dazu Vorlage und amtliches Ergebnis."),
    "dip_dokumente": (
        "DIP-Vollabzug: Drucksachen und Vorgaenge",
        "Drucksachen, Vorgaenge, Vorgangspositionen und Aktivitaeten des " "Bundestages, mit Sachgebiet und Deskriptoren."),
    "dip_plenarprotokolle": (
        "Plenarprotokolle (DIP-XML)",
        "Annotierte Plenarprotokolle mit Tagesordnung, Fundstellen, " "Zwischenrufen und Abstimmungslisten."),
    "cpp_bt_fobbe": (
        "Plenarprotokoll-Korpus (CPP-BT)",
        "Die einzelnen Reden des Bundestages als Volltext, mit Sprecher, " "Fraktion, Rolle und Fundstelle."),
    "wikidata": (
        "Wikidata: Kennungen und Geburtsorte",
        "Externe Kennungen und Geburtsortkoordinaten der Abgeordneten " "mit Mandat."),
    "manifesto_mpds_2025a": (
        "Manifesto Project: Wahlprogramme",
        "Inhaltlich codierte Wahlprogramme: wie stark ein Programm " "welches Thema betont."),


    "gemeinde_gerda_zuordnung": (
        "Gemeindeschluessel GERDA zu Gebietsstand",
        "Ueberleitung der Gemeindeschluessel aus den GERDA-Ergebnissen " "auf die Gebietsstaende dieses Bestands."),
    "kreisebene_amtlich": (
        "Wahlergebnisse je Kreisteil",
        "Wahlergebnisse je Kreis und Wahlkreis, aus den Wahlbezirken " "aufsummiert."),
    "grossstadt_wkr_2013": (
        "Geteilte Gemeinden je Wahlkreis 2013",
        "Der Teil einer Gemeinde, der in einem bestimmten Wahlkreis " "liegt, fuer die ueber mehrere Wahlkreise geteilten Staedte."),
    "grossstadt_wkr_2017": (
        "Geteilte Gemeinden je Wahlkreis 2017",
        "Der Teil einer Gemeinde, der in einem bestimmten Wahlkreis " "liegt, fuer die ueber mehrere Wahlkreise geteilten Staedte."),
    "grossstadt_wkr_2021": (
        "Geteilte Gemeinden je Wahlkreis 2021",
        "Der Teil einer Gemeinde, der in einem bestimmten Wahlkreis " "liegt, fuer die ueber mehrere Wahlkreise geteilten Staedte."),
    "kreis_wahlkreis_zuschnitt": (
        "Kreisteile je Wahlkreis",
        "Das Stueck eines Kreises, das in einem bestimmten Wahlkreis " "liegt, samt Flaeche."),
    "nachbarschaft_wahlkreis": (
        "Nachbarschaft der Wahlkreise",
        "Welche Wahlkreise aneinandergrenzen, mit der Laenge der " "gemeinsamen Grenze."),
    "hexkarte_wahlkreis": (
        "Hexagon-Kartogramm der Wahlkreise",
        "Je Wahlkreis ein gleich grosses Sechseck, das die Nachbarschaft " "bewahrt; nur zur Darstellung."),
    "wahlkreisuebergang": (
        "Uebergaenge der Wahlkreise",
        "Welcher Wahlkreis einer Wahl welchem der naechsten entspricht, " "samt der Gemeinden, die gewechselt haben."),
    "einheitsuebergang": (
        "Uebergaenge der Auswertungseinheiten",
        "Welche Auswertungseinheit einer Wahl welcher der naechsten " "entspricht."),
    "partei_normalisierung": (
        "Normalisierte Parteien",
        "Einheitliche Parteien, auf die die verschiedenen Schreibweisen " "der Lieferungen abgebildet sind."),
    "personenknoten": (
        "Personenverzeichnis",
        "Alle Personen dieser Arbeit mit ihren Kennungen aus DIP, " "Bundestagsverwaltung und abgeordnetenwatch."),
    "person_rolle_erschlossen": (
        "Rollen und Aemter, erschlossen",
        "In welcher Rolle eine Person gesprochen hat, aus den " "Protokollkoepfen."),
    "regierungsamt_zuordnung": (
        "Aemter der Bundesregierung",
        "Welche Aemter zur Bundesregierung gehoeren und wer sie wann " "innehatte."),
    "erststimmen_bewerber_zuordnung": (
        "Erststimmen je Bewerberin",
        "Welche Person die Erststimmen erhalten hat, die die amtliche " "Statistik nur je Partei ausweist."),
    "plenarkommentare": (
        "Zwischenrufe und Reaktionen",
        "Zwischenrufe, Beifall und Reaktionen aus den Plenarprotokollen, " "je Ereignis mit Art und Urheber."),
    "entschuldigte_abgeordnete": (
        "Entschuldigte Abgeordnete",
        "Wer sich fuer welche Sitzung entschuldigt hat."),
    "rede_aktivitaet_zuordnung": (
        "Rede zu DIP-Aktivitaet",
        "Welche Rede welcher im DIP verzeichneten Aktivitaet " "entspricht."),
    "rede_top_zuordnung": (
        "Rede zu Tagesordnungspunkt",
        "Unter welchem Tagesordnungspunkt eine Rede gehalten wurde."),
    "top_deskriptor_zuordnung": (
        "Deskriptoren je Tagesordnungspunkt",
        "Worum es bei einem Tagesordnungspunkt geht, aus den " "Schlagworten der verhandelten Drucksache."),
    "top_sachgebiet_zuordnung": (
        "Sachgebiet je Tagesordnungspunkt",
        "Die grobe thematische Einordnung eines Tagesordnungspunkts."),
}


FORMATE = {
    "gerda_federal_muni_unharm":    "CSV (.txt)",
    "gerda_federal_muni_harm_21":   "CSV (.txt)",
    "gerda_federal_cty_unharm":     "CSV (.txt)",
    "gerda_federal_wkr_unharm":     "CSV (.txt)",
    "cpp_bt_fobbe":                 "Parquet",
    "bwl_wahlbezirke_2013":         "CSV",
    "bwl_wahlbezirke_2017":         "CSV",
    "bwl_wahlbezirke_2021":         "CSV",
    "gv100ad_2013":                 "ASCII, feste Satzstellen",
    "bwl_zuordnung_2017":           "CSV",
    "bwl_zuordnung_2021":           "CSV",
    "bwl_wahlkreisgeometrie":       "Shapefile",
    "bwl_strukturdaten_2013":       "CSV",
    "bwl_strukturdaten_2017":       "CSV",
    "bwl_strukturdaten_2021":       "CSV",
    "bkg_vg250":                    "Shapefile",
    "bkg_gn250":                    "Shapefile",
    "bbsr_ags_crosswalk":           "CSV (.txt)",
    "bbsr_cty_crosswalk":           "CSV (.txt)",
    "bbsr_inkar_2024":              "CSV",
    "bbsr_wachsen_schrumpfen_2021": "XLSX",
    "destatis_regionaldatenbank":   "API (GENESIS)",
    "bbsr_raumgliederung":          "XLSX",
    "destatis_gebietsaenderungen":  "XLSX",
    "aw_api_v2":                    "API (JSON)",
    "bt_mdb_stammdaten":            "XML",
    "bt_ausgeschiedene":            "HTML",
    "bt_namentliche_abstimmungen":  "XLSX/XLS und PDF",
    "wikidata":                     "API (SPARQL/JSON)",
    "dip_dokumente":                "API (JSON)",
    "dip_plenarprotokolle":         "XML",
    "manifesto_mpds_2025a":         "CSV",
}


NAMEN = {

    "aw_api_v2":                    "Abgeordnetenwatch API v2",
    "bbsr_inkar_2024":              "INKAR, Ausgabe 03/2024",
    "bbsr_raumgliederung":          "BBSR-Raumgliederungen",
    "bbsr_wachsen_schrumpfen_2021": "Wachsende und schrumpfende Gemeinden",
    "bt_ausgeschiedene":            "Ausgeschiedene Abgeordnete und Nachfolger",
    "bt_mdb_stammdaten":            "Stammdaten der Abgeordneten seit 1949",
    "bt_namentliche_abstimmungen":  "Namentliche Abstimmungen",
    "cpp_bt_fobbe":                 "Plenarprotokoll-Korpus (CPP-BT)",
    "destatis_regionaldatenbank":   "Regionaldatenbank Deutschland",
    "dip_dokumente":                "DIP-Vollabzug: Drucksachen und Vorgaenge",
    "dip_plenarprotokolle":         "Plenarprotokolle (DIP-XML)",
    "wikidata":                     "Wikidata: Kennungen und Geburtsorte",
    "bwl_wahlbezirke_2013":         "Wahlbezirksstatistik 2013",
    "bwl_wahlbezirke_2017":         "Wahlbezirksstatistik 2017",
    "bwl_wahlbezirke_2021":         "Wahlbezirksstatistik 2021",
    "bwl_wahlkreisgeometrie":       "Wahlkreisgeometrien",
    "bwl_zuordnung_2017":           "Zuordnungsliste Gemeinde-Wahlkreis 2017",
    "bwl_zuordnung_2021":           "Zuordnungsliste Gemeinde-Wahlkreis 2021",
    "gv100ad_2013":                 "Gemeindeverzeichnis GV100AD 2013",
    "bkg_vg250":                    "Verwaltungsgebiete VG250",
    "bkg_gn250":                    "Geographische Namen GN250",
    "bbsr_ags_crosswalk":           "Umsteigeschluessel Gemeinden",
    "bbsr_cty_crosswalk":           "Umsteigeschluessel Kreise",
    "destatis_gebietsaenderungen":  "Gebietsaenderungen der Gemeinden",


    "entschuldigte_abgeordnete":    "Entschuldigte Abgeordnete",
    "erststimmen_bewerber_zuordnung": "Erststimmen je Bewerberin",
    "kreisebene_amtlich":           "Wahlergebnisse je Kreisteil",
    "partei_normalisierung":        "Normalisierte Parteien",
    "person_rolle_erschlossen":     "Rollen und Aemter, erschlossen",
    "personenknoten":               "Personenverzeichnis",
    "plenarkommentare":             "Zwischenrufe und Reaktionen",
    "rede_aktivitaet_zuordnung":    "Rede zu DIP-Aktivitaet",
    "rede_top_zuordnung":           "Rede zu Tagesordnungspunkt",
    "regierungsamt_zuordnung":      "Aemter der Bundesregierung",
    "top_deskriptor_zuordnung":     "Deskriptoren je Tagesordnungspunkt",
    "top_sachgebiet_zuordnung":     "Sachgebiet je Tagesordnungspunkt",
}


def name_und_text(eintrag):
    kennung = eintrag["lieferung_id"]
    if kennung in TEXTE:
        return (*TEXTE[kennung], "geschrieben")


    if kennung in NAMEN:
        roh = " ".join(eintrag["bezeichnung"].split())
        text = eintrag.get("beschreibung") or roh
        quelle = "quelle" if eintrag.get("beschreibung") else "aus_titel"
        return NAMEN[kennung], text, quelle

    roh = " ".join(eintrag["bezeichnung"].split())
    if eintrag.get("beschreibung"):
        return roh, eintrag["beschreibung"], "quelle"

    if len(roh) >= 120:


        for trenner in (": ", ". ", " - "):
            if trenner in roh[:90]:
                kopf, rest = roh.split(trenner, 1)
                return kopf.strip(), roh, "aus_titel"
        return roh[:80].rstrip() + "…", roh, "aus_titel"

    return roh, "", "fehlt"


def zeilen():
    aus = []
    for e in LIEFERUNGEN:
        lizenz, lizenz_zustand = istwert(e, "lizenz")
        basis = e.get("basis") or []
        name, text, textquelle = name_und_text(e)
        wurzeln = sorted(wurzeln_von(e["lieferung_id"]) - {e["lieferung_id"]})
        aus.append({
            "name":          name,
            "format":        FORMATE.get(e["lieferung_id"], "--"),
            "beschreibung":  text,
            "textquelle":    textquelle,
            "stufe":         stufe_von(e["lieferung_id"]),
            "wurzeln":       ", ".join(wurzeln) if wurzeln else "--",
            "kennung":       e["lieferung_id"],
            "bezeichnung":   e["bezeichnung"],
            "herausgeber":   e["herausgeber"],
            "urheber":       istwert(e, "urheber")[0],
            "art":           e["art"],
            "lizenz":        lizenz,
            "lizenz_zustand": lizenz_zustand,
            "zeitbezug":     zeitbezug(e),
            "datei":         istwert(e, "datei")[0],
            "verfahren":     e.get("uebernahme_verfahren", "--"),
            "beruht_auf":    ", ".join(basis) if basis else "--",
            "zahl_basis":    len(basis),
            "zitat":         istwert(e, "zitat")[0],
            "limitierungen": istwert(e, "limitierungen")[0],
        })
    return aus


def schreibe_markdown(daten):
    ZIEL_MD.parent.mkdir(parents=True, exist_ok=True)
    t = [
        "# Datenlieferungen — Tabelle fuer den Anhang",
        "",
        "ERZEUGT von `03_load_db/meta/baue_lieferungstabelle.py` aus der " "Liste `LIEFERUNGEN`",
        "in `03_load_db/meta/load_datenlieferung.py`. **Nicht von Hand " "pflegen.**",
        "",
        "Dieselbe Liste erzeugt `meta.datenlieferung` und die Named Graphs " "des",
        "Wissensgraphen: Die Spalte **Kennung** ist zugleich der Name des " "Named Graph,",
        "in dem die Lieferung liegt. Jede Tabellenzeile ist damit auf ihre " "Tripel",
        "zurueckfuehrbar.",
        "",
        f"**{len(daten)} Lieferungen.**",
        "",
        "## Wie die Spalten zu lesen sind",
        "",
        "| Eintrag | heisst |",
        "|---|---|",
        "| ein Wert | die Quelle nennt ihn |",
        "| `nicht angegeben` | nachgesehen, die Quelle nennt ihn nicht |",
        "| `--` | noch nicht erhoben |",
        "",
        "Die Unterscheidung ist noetig, weil alle drei in einer Leerzelle " "gleich",
        "aussaehen: Eine geprueft fehlende Lizenzangabe ist ein Ergebnis, " "eine nicht",
        "erhobene ist offene Arbeit.",
        "",
        "**Was diese Tabelle nicht sagt:** ob die Lieferung im Graphen " "steht. Das ist",
        "eine Frage an den Store und wird getrennt beantwortet.",
        "",
        "---",
        "",
    ]


    for art, titel, erklaerung in ARTEN:
        teil = [z for z in daten if z["art"] == art]
        if not teil:
            continue
        t += [f"## {titel} ({len(teil)})", "", erklaerung, ""]
        abgeleitet = (art == "abgeleitet")
        if abgeleitet:
            t += ["| Name | Kennung | Beschreibung | Beruht auf | Lizenz |",
                  "|---|---|---|---|---|"]
        else:
            t += ["| Name | Kennung | Beschreibung | Herausgeber | " "Format | Lizenz |",
                  "|---|---|---|---|---|---|"]
        for z in sorted(teil, key=lambda x: x["name"].lower()):
            text = (escape_md(z["beschreibung"]) if z["beschreibung"]
                    else "**fehlt**")
            zeile = (f"| {escape_md(z['name'])} "
                     f"| `{z['kennung']}` "
                     f"| {text} ")
            zeile += (f"| {escape_md(z['beruht_auf'])} " if abgeleitet
                      else (f"| {escape_md(z['herausgeber'])} "
                            f"| {escape_md(z['format'])} "))
            zeile += f"| {escape_md(z['lizenz'])} |"
            t.append(zeile)
        t.append("")


    ohne_lizenz = [z for z in daten if z["lizenz_zustand"] != "wert"]
    ohne_zeit = [z for z in daten if z["zeitbezug"] == "--"]
    ohne_datei = [z for z in daten if z["datei"] == "--"]
    ohne_text = [z for z in daten if z["textquelle"] == "fehlt"]
    aus_titel = [z for z in daten if z["textquelle"] == "aus_titel"]


    art_ohne_basis = [z for z in daten
                      if z["art"] == "abgeleitet" and z["beruht_auf"] == "--"]
    basis_ohne_art = [z for z in daten
                      if z["art"] != "abgeleitet" and z["beruht_auf"] != "--"]

    t += [
        "---",
        "",
        "## Was in dieser Tabelle offen ist",
        "",
        "### Fehlende Angaben",
        "",
        f"- **Beschreibung:** {len(ohne_text)} von {len(daten)} Lieferungen "
        f"haben keinen beschreibenden Text.",
        f"- **Beschreibung aus dem Titelfeld:** Bei {len(aus_titel)} steht "
        f"der Text in `bezeichnung`, dem Feld, das als `dcterms:title` "
        f"exportiert wird. Er ist in die Beschreibungsspalte uebernommen; "
        f"im Graphen steht er weiterhin als Titel.",
        f"- **Lizenz:** {len(ohne_lizenz)} tragen keine Lizenzangabe.",
        f"- **Zeitbezug:** {len(ohne_zeit)} fuehren weder `wahljahr` noch "
        f"`gebietsstand`.",
        f"- **Datei:** {len(ohne_datei)} nennen keinen Dateinamen — das "
        f"betrifft vor allem die gerechneten Lieferungen, die aus der "
        f"Datenbank stammen.",
        "",
        "Diese Zahlen sind Messwerte, keine Maengelliste: Wo eine Quelle " "nichts nennt,",
        "bleibt die Angabe leer und wird nicht aus der Art der Stelle " "geschlossen.",
        "",
        "### Herkunftsart und Abstammung widersprechen einander",
        "",
    ]
    if art_ohne_basis:
        t += ["Als `abgeleitet` gefuehrt, aber ohne `basis` — es steht " "nicht dabei, woraus:", ""]
        t += [f"- `{z['kennung']}`" for z in art_ohne_basis]
        t.append("")
    if basis_ohne_art:
        t += ["Nicht als `abgeleitet` gefuehrt, aber mit `basis` — bezogen " "und zugleich aus dem Bestand gespeist:", ""]
        t += [f"- `{z['kennung']}` ({z['art']}) beruht auf "
              f"{z['beruht_auf']}" for z in basis_ohne_art]
        t.append("")
    if not (art_ohne_basis or basis_ohne_art):
        t += ["Keine Widersprueche.", ""]

    ZIEL_MD.write_text("\n".join(t), encoding="utf-8")
    return ohne_lizenz, ohne_zeit, ohne_datei, ohne_text, aus_titel


def schreibe_csv(daten):
    ZIEL_CSV.parent.mkdir(parents=True, exist_ok=True)
    spalten = ["kennung", "name", "beschreibung", "format", "textquelle",
               "bezeichnung", "herausgeber", "urheber", "art", "lizenz",
               "zeitbezug", "datei", "verfahren", "stufe", "beruht_auf",
               "wurzeln", "zitat", "limitierungen"]
    with ZIEL_CSV.open("w", encoding="utf-8", newline="") as fh:
        s = csv.DictWriter(fh, fieldnames=spalten, extrasaction="ignore")
        s.writeheader()
        for z in sorted(daten, key=lambda x: (x["art"], x["kennung"])):
            s.writerow(z)


def main():
    daten = zeilen()

    kennungen = [z["kennung"] for z in daten]
    doppelt = {k for k in kennungen if kennungen.count(k) > 1}
    if doppelt:
        raise SystemExit(f"Kennungen doppelt vergeben: {sorted(doppelt)}")


    bekannt = set(kennungen)
    for z in daten:
        for v in (z["beruht_auf"].split(", ") if z["zahl_basis"] else []):
            if v not in bekannt:
                print(f"  WARNUNG  {z['kennung']}: basis zeigt ins Leere "
                      f"-> {v}")

    ohne_lizenz, ohne_zeit, ohne_datei, ohne_text, aus_titel = \
        schreibe_markdown(daten)
    schreibe_csv(daten)

    print(f"\n  {len(daten)} Lieferungen")
    for art, titel, _ in ARTEN:
        n = len([z for z in daten if z["art"] == art])
        print(f"    {titel:<38} {n:>3}")

    print("\n  Abstammung")
    for stufe in sorted({z["stufe"] for z in daten}):
        n = len([z for z in daten if z["stufe"] == stufe])
        was = ("Wurzel, von aussen bezogen" if stufe == 0
               else f"{stufe} Ableitungsschritt(e) bis zur Wurzel")
        print(f"    Stufe {stufe}: {n:>3}  {was}")

    print("\n  Beschreibungen")
    for quelle, was in (("quelle",      "aus load_datenlieferung.py"),
                        ("geschrieben", "hier geschrieben"),
                        ("aus_titel",   "aus dem Titelfeld uebernommen"),
                        ("fehlt",       "FEHLT")):
        n = len([z for z in daten if z["textquelle"] == quelle])
        print(f"    {was:<32} {n:>3}")

    print("\n  Fehlende Angaben")
    print(f"    ohne Lizenzangabe     {len(ohne_lizenz):>3}")
    print(f"    ohne Zeitbezug        {len(ohne_zeit):>3}")
    print(f"    ohne Dateinamen       {len(ohne_datei):>3}")
    print(f"\n  geschrieben:\n    {ZIEL_MD}\n    {ZIEL_CSV}\n")


if __name__ == "__main__":
    main()
