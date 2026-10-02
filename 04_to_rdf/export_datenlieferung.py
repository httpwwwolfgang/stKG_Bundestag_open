import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "03_load_db" / "meta"))

from load_datenlieferung import LIEFERUNGEN

BASIS = "https://skg-bundestag.de/"
ZIEL  = pfade.METADATEN / "datenlieferung.trig"


UPDATE_ZIEL = pfade.METADATEN / "datenlieferung_update.ru"

PRAEFIXE = [
    ("stkg",    "https://skg-bundestag.de/schema#"),
    ("dcterms", "http://purl.org/dc/terms/"),
    ("dcat",    "http://www.w3.org/ns/dcat#"),
    ("prov",    "http://www.w3.org/ns/prov#"),
    ("xsd",     "http://www.w3.org/2001/XMLSchema#"),
]


HERAUSGEBER = [
    ("bundeswahlleiterin",
     "Die Bundeswahlleiterin",
     ["Die Bundeswahlleiterin",
      "Die Bundeswahlleiterin (im Auftrag der Herausgebergemeinschaft)"]),


    ("bundeswahlleiter_destatis",
     "Bundeswahlleiter / Statistisches Bundesamt",
     ["Bundeswahlleiter / Statistisches Bundesamt"]),

    ("destatis",
     "Statistisches Bundesamt",
     ["Statistisches Bundesamt"]),

    ("statistische_aemter",
     "Statistische Ämter des Bundes und der Länder",
     ["Statistische Aemter des Bundes und der Laender"]),

    ("bkg",
     "Bundesamt für Kartographie und Geodäsie",
     ["Bundesamt fuer Kartographie und Geodaesie"]),

    ("bbsr",
     "Bundesinstitut für Bau-, Stadt- und Raumforschung (BBSR), Bonn",
     ["Bundesinstitut fuer Bau-, Stadt- und Raumforschung (BBSR), Bonn"]),


    ("bbsr_ueber_gerda",
     "BBSR, verteilt über GERDA (Heddesheimer u.a. 2025)",
     ["BBSR, verteilt ueber GERDA " "(Heddesheimer u.a. 2025, doi:10.1038/s41597-025-04811-5)"]),

    ("bundestag",
     "Deutscher Bundestag",
     ["Deutscher Bundestag"]),

    ("bundestag_dip",
     "Deutscher Bundestag / Dokumentations- und Informationssystem DIP",
     ["Deutscher Bundestag / Dokumentations- und Informationssystem DIP"]),

    ("bundesgesetzblatt",
     "Bundesrepublik Deutschland (Bundesgesetzblatt) / Die Bundeswahlleiterin",
     ["Bundesrepublik Deutschland (Bundesgesetzblatt) / Die Bundeswahlleiterin"]),

    ("abgeordnetenwatch",
     "abgeordnetenwatch.de",
     ["abgeordnetenwatch.de"]),

    ("wikimedia",
     "Wikidata / Wikimedia Foundation",
     ["Wikidata / Wikimedia Foundation"]),

    ("springer_nature",
     "Springer Nature (Scientific Data)",
     ["Springer Nature (Scientific Data)"]),


    ("gerda_autoren",
     "Heddesheimer, Hilbig, Sichart & Wiedemann",
     ["Heddesheimer, Hilbig, Sichart & Wiedemann"]),

    ("manifesto_autoren",
     "Lehmann et al.",
     ["Lehmann et al."]),

    ("wzb",
     "WZB Berlin Social Science Center / IfDem Göttingen",
     ["WZB Berlin Social Science Center / IfDem Goettingen"]),


    ("fobbe",
     "Seán Fobbe",
     ["Seán Fobbe", "Fobbe, Seán"]),

    ("diese_arbeit",
     "Eigene Berechnung im Rahmen dieser Arbeit",


     ["eigene Ableitung", "eigene Berechnung",
      "eigene Ableitung (kein Herausgeber)",
      "eigene Erschliessung", "eigene Extraktion",
      "eigene Extraktion und Einteilung", "eigene Zuordnung",
      "eigene Zusammenfuehrung"]),
]

FREITEXT_ZU_KENNUNG = {
    text: kennung for kennung, _, texte in HERAUSGEBER for text in texte
}
KENNUNG_ZU_NAME = {kennung: name for kennung, name, _ in HERAUSGEBER}


HERKUNFTSART = {
    "amtlich":               "stkg:herkunft_amtlich",
    "forschung":             "stkg:herkunft_forschung",
    "zivilgesellschaftlich": "stkg:herkunft_zivilgesellschaftlich",
    "abgeleitet":            "stkg:herkunft_abgeleitet",
}


def txt(wert):
    s = str(wert)
    for such, ersatz in (("\\", "\\\\"), ('"', '\\"'),
                         ("\n", "\\n"), ("\r", ""), ("\t", "\\t")):
        s = s.replace(such, ersatz)
    return f'"{s}"'


def iri(*teile):
    return "<" + BASIS + "/".join(str(t) for t in teile) + ">"


def tripel_der_lieferung(eintrag, unbekannt):
    aus = [("a", "stkg:Datenlieferung, dcat:Dataset, prov:Entity"),
           ("dcterms:identifier", txt(eintrag["lieferung_id"]))]

    def dazu(kante, wert, formatierer=txt):
        if wert is not None:
            aus.append((kante, formatierer(wert)))

    dazu("dcterms:title",                 eintrag.get("bezeichnung"))
    dazu("dcterms:description",           eintrag.get("beschreibung"))
    dazu("dcterms:bibliographicCitation", eintrag.get("zitat"))
    dazu("dcterms:license",               eintrag.get("lizenz"))
    dazu("dcterms:source",                eintrag.get("datei"))
    dazu("stkg:uebernahmeVerfahren",      eintrag.get("uebernahme_verfahren"))
    dazu("stkg:limitierungen",            eintrag.get("limitierungen"))

    dazu("dcterms:issued",   eintrag.get("stand_quelle"),
         lambda w: f'"{w}"^^xsd:date')
    dazu("dcterms:modified", eintrag.get("geaendert_quelle"),
         lambda w: f'"{w}"^^xsd:date')
    dazu("stkg:bezugszeitpunkt", eintrag.get("gebietsstand"),
         lambda w: f'"{w}"^^xsd:date')
    dazu("dcterms:temporal", eintrag.get("wahljahr"),
         lambda w: f'"{w}"^^xsd:gYear')
    dazu("prov:generatedAtTime", eintrag.get("uebernahme_zeitpunkt"),
         lambda w: f'"{w}"^^xsd:dateTime')

    art = eintrag.get("art")
    if art in HERKUNFTSART:
        aus.append(("stkg:hatHerkunftsart", HERKUNFTSART[art]))
    elif art:
        unbekannt.append(f"Herkunftsart ohne Codelisteneintrag: {art} "
                         f"({eintrag['lieferung_id']})")

    for rolle, feld in (("dcterms:publisher", "herausgeber"),
                        ("dcterms:creator",   "urheber")):
        text = eintrag.get(feld)
        if not text:
            continue
        kennung = FREITEXT_ZU_KENNUNG.get(text)
        if kennung is None:
            unbekannt.append(f"{feld} nicht in HERAUSGEBER: {text!r} "
                             f"({eintrag['lieferung_id']})")
            continue
        aus.append((rolle, iri("herausgeber", kennung)))

    for vorgaenger in eintrag.get("basis") or []:
        aus.append(("prov:wasDerivedFrom", iri("lieferung", vorgaenger)))

    return aus


def beteiligte_herausgeber(tripel):
    vorsatz = "<" + BASIS + "herausgeber/"
    return [o[len(vorsatz):-1] for _, o in tripel if o.startswith(vorsatz)]


def schreibe_update(unbekannt):
    teile = ["# Metadaten der Datenlieferungen auffrischen",
             "#",
             "# ERZEUGT von export_datenlieferung.py. In der GraphDB-",
             "# Workbench unter SPARQL einfuegen und ausfuehren, oder ueber",
             "# den Update-Endpunkt schicken.",
             "#",
             "# Ersetzt NUR die Aussagen ueber die Lieferungen und ihre",
             "# Herausgeber. Alles andere im jeweiligen Named Graph bleibt",
             "# stehen, insbesondere die Sachdaten.",
             ""]
    teile += [f"PREFIX {p}: <{u}>" for p, u in PRAEFIXE]
    teile.append("")

    for eintrag in sorted(LIEFERUNGEN, key=lambda e: e["lieferung_id"]):
        tripel = tripel_der_lieferung(eintrag, unbekannt)
        graph = iri("lieferung", eintrag["lieferung_id"])
        subjekte = [graph] + [iri("herausgeber", k)
                              for k in dict.fromkeys(beteiligte_herausgeber(tripel))]

        teile.append(f"# --- {eintrag['lieferung_id']} " + "-" * 40)
        for nr, subjekt in enumerate(subjekte):
            teile += [
                f"DELETE {{ GRAPH {graph} {{ {subjekt} ?p{nr} ?o{nr} }} }}",
                f"WHERE  {{ GRAPH {graph} {{ {subjekt} ?p{nr} ?o{nr} }} }} ;",
                "",
            ]

        zeilen = [f"INSERT DATA {{", f"  GRAPH {graph} {{", f"    {graph}"]
        zeilen += [f"        {k:<32} {o} ;" for k, o in tripel[:-1]]
        zeilen.append(f"        {tripel[-1][0]:<32} {tripel[-1][1]} .")
        for kennung in dict.fromkeys(beteiligte_herausgeber(tripel)):
            zeilen += [
                "",
                f"    {iri('herausgeber', kennung)}",
                "        a                                stkg:Herausgeber ;",
                f"        stkg:herausgeberbezeichnung      "
                f"{txt(KENNUNG_ZU_NAME[kennung])} .",
            ]
        zeilen += ["  }", "} ;", ""]
        teile.append("\n".join(zeilen))

    UPDATE_ZIEL.write_text("\n".join(teile).rstrip().rstrip(";") + "\n",
                           encoding="utf-8")


def baue():
    unbekannt, bloecke = [], []
    kennungen = {e["lieferung_id"] for e in LIEFERUNGEN}

    for eintrag in sorted(LIEFERUNGEN, key=lambda e: e["lieferung_id"]):
        for vorgaenger in eintrag.get("basis") or []:
            if vorgaenger not in kennungen:
                unbekannt.append(f"basis zeigt ins Leere: {vorgaenger} "
                                 f"({eintrag['lieferung_id']})")

        tripel = tripel_der_lieferung(eintrag, unbekannt)
        graph = iri("lieferung", eintrag["lieferung_id"])

        zeilen = [f"{graph} {{", f"    {graph}"]
        zeilen += [f"        {k:<32} {o} ;" for k, o in tripel[:-1]]
        zeilen.append(f"        {tripel[-1][0]:<32} {tripel[-1][1]} .")

        for kennung in dict.fromkeys(beteiligte_herausgeber(tripel)):
            zeilen += [
                "",
                f"    {iri('herausgeber', kennung)}",
                "        a                                stkg:Herausgeber ;",
                f"        stkg:herausgeberbezeichnung      "
                f"{txt(KENNUNG_ZU_NAME[kennung])} .",
            ]
        zeilen.append("}")
        bloecke.append("\n".join(zeilen))

    kopf = [
        "# Datenlieferungen des raumzeitlichen Wissensgraphen",
        "#",
        "# ERZEUGT von 03_load_db/graph/export_datenlieferung.py.",
        "# Je Lieferung ein Named Graph, der seine eigene Beschreibung",
        "# traegt (mod:2.3). Der Namensraum ist vorlaeufig.",
        "",
    ] + [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE] + [""]

    pfade.pruefe(pfade.METADATEN)
    ZIEL.write_text("\n".join(kopf) + "\n\n".join(bloecke) + "\n",
                    encoding="utf-8")

    schreibe_update(unbekannt)

    print(f"geschrieben: {ZIEL}")
    print(f"             {UPDATE_ZIEL.name} (fuer spaetere Aenderungen)")
    print(f"  {len(LIEFERUNGEN)} Named Graphs, "
          f"{sum(len(tripel_der_lieferung(e, [])) for e in LIEFERUNGEN)} "
          f"Tripel ueber Lieferungen")
    if unbekannt:
        print(f"  {len(unbekannt)} Punkte zu klaeren:")
        for zeile in dict.fromkeys(unbekannt):
            print(f"    {zeile}")
    else:
        print("  keine offenen Punkte")


if __name__ == "__main__":
    baue()
