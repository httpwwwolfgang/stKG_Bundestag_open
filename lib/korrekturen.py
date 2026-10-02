KENNUNG_KORREKTUR = {
    "ID19101300": ("11002190", "11001938", "Dr. Wolfgang Schäuble",
                   "Kennung 11002190 traegt 10 Reden von Hermann Otto Solms; " "Schaeuble hat 11001938 mit 81 Reden"),
    "ID19101900": ("11002190", "11001938", "Dr. Wolfgang Schäuble",
                   "wie ID19101300, dieselbe Sitzung 19/1 am 24.10.2017"),
    "ID1822300400": ("11004105", "11004167", "Frank-Walter Steinmeier",
                     "Kennung 11004105 traegt 229 Reden von Thomas de Maizière; " "Steinmeier hat 11004167 mit 92 Reden. Rede als " "Bundespraesident, 18/223 am 22.03.2017"),
    "ID196001500": ("10000", "11004157", "Carsten Sieling",
                    "10000 ist eine Sammelkennung mit drei Personen; " "Sieling hat 11004157 mit 11 Reden"),
    "ID191604600": ("10000", "11004667", "Olaf in der Beek",
                    "wie ID196001500; in der Beek hat 11004667 mit 72 Reden"),
    "ID1818302300": ("999990055", "11004741", "Thomas Heilmann",
                     "Behelfskennung 999990055 traegt sonst Monika Heinold; " "Heilmann hat 11004741 mit 57 Reden"),
    "ID1923412800": ("999990109", "11004367", "Tim Ostermann",
                     "Behelfskennung 999990109 traegt sonst Gabriele " "Loesekrug-Moeller; Ostermann hat 11004367 mit 29 Reden"),


    "ID1804617400": ("", "11004256", "Karl-Heinz Brunner",
                     "Anlagen-Rede, Name im Absatztext 'Karl-Heinz Brunner " "(SPD) :'; er hat 11004256 mit 146 Reden"),
    "ID1806309700": ("", "11004277", "Astrid Freudenstein",
                     "Anlagen-Rede, Name im Absatztext; sie hat 11004277 " "mit 72 Reden"),
    "ID1807611000": ("", "11002630", "Maria Böhmer",
                     "Anlagen-Rede, Name im Absatztext 'Dr. Maria Böhmer " "(Staatsministerin AA) :'; sie hat 11002630 mit 29 Reden"),
    "ID1811703000": ("", "11004215", "Harald Ebner",
                     "Anlagen-Rede, Name im Absatztext (dort mit dem " "Druckfehler 'GRÜNNEN'); er hat 11004215 mit 127 Reden"),
    "ID1811802900": ("", "11004060", "Andrej Hunko",
                     "Anlagen-Rede, Name im Absatztext; er hat 11004060 " "mit 115 Reden"),
    "ID19205800": ("", "11002617", "Peter Altmaier",
                   "Name und Rolle 'Bundesminister BMF' sind ausgezeichnet, " "nur die Kennung fehlt; er hat 11002617 mit 140 Reden"),
    "ID1810402200": ("", "11004333", "Christian Kühn (Tübingen)",
                     "Sprecher steht in einem <name>-Element statt in " "<redner> (wie PA7): '<name>Christian Kühn ( Tübingen) " "(BÜNDNIS 90/DIE GRÜNEN) : </name>'; er hat 11004333 " "mit 96 Reden"),
}


OHNE_KENNUNG = {
    "ID202101300": ("999990124", "Andreas Bovenschulte",
                    "Behelfskennung traegt sonst Annette Widmann-Mauz"),
    "ID204609000": ("999990127", "Peter Beuth",
                    "Behelfskennung traegt sonst Enak Ferlemann"),
    "ID207511900": ("999990127", "Peter Beuth", "wie ID204609000"),
    "ID209502300": ("999990127", "Peter Beuth", "wie ID204609000"),
    "ID2014407800": ("999990141", "Mehmet Daimagüler",
                     "Behelfskennung traegt sonst Judith Gerlach"),
}


INTERNE_KENNUNG = {
    "ID202101300": ("INTERN_b84215a8-c53a-5e5b-ac20-0f2794a4d75d",
                    "Dr. Andreas Bovenschulte", "7131",
                    "Name und Rolle 'Buergermeister (Bremen)' sind im XML " "ausgezeichnet; DIP fuehrt ihn als MdBR, Bremen"),
    "ID204609000": ("INTERN_acf3f0b9-bb9c-5d8e-97f5-cab2128ce2c0",
                    "Peter Beuth", "1809",
                    "Name und Rolle 'Staatsminister (Hessen)' ausgezeichnet; " "DIP fuehrt ihn als Stellv. MdBR, Hessen, mit 3 " "Aktivitaeten — genau seine 3 Reden"),
    "ID207511900": ("INTERN_acf3f0b9-bb9c-5d8e-97f5-cab2128ce2c0",
                    "Peter Beuth", "1809", "wie ID204609000"),
    "ID209502300": ("INTERN_acf3f0b9-bb9c-5d8e-97f5-cab2128ce2c0",
                    "Peter Beuth", "1809", "wie ID204609000"),
    "ID2014407800": ("INTERN_421b6add-7aaa-52b5-a6bf-a4200d31f98b",
                     "Dr. Mehmet Daimagüler", "7727",
                     "Name und Rolle 'Beauftragter der Bundesregierung gegen " "Antiziganismus' ausgezeichnet; DIP fuehrt ihn als " "Beauftr. d. Bundesregierung"),
}


UNBEKANNT = "UNBEKANNT"
OHNE_SPRECHER = {}


NAME_KORREKTUR = {
    "ID1814407700": ("Angela", "Marina", "Kermer",
                     "Kennung 11004326 traegt 9 Reden von Marina Kermer; " "das DIP kennt keine Angela Kermer"),
}


ENTSCHULDIGT_SCHREIBFEHLER = {
    ("20/139", "Abdi", "Saane"): (
        "Abdi", "Sanae", "11005000",
        "Buchstabendreher: 'Saane' statt 'Sanae'. Sanae Abdi (SPD) hat in " "WP 20 ein Mandat; eine Saane Abdi kennt das Verzeichnis nicht"),
    ("18/8", "Friedrich", "Hans-.Peter"): (
        "Friedrich", "Hans-Peter", "11003124",
        "Punkt statt Bindestrich im Vornamen. Dr. Hans-Peter Friedrich " "(CDU/CSU) hat in WP 18 ein Mandat"),
    ("19/109", "JIrmer", "Hans-Jürgen"): (
        "Irmer", "Hans-Jürgen", "11004766",
        "Grossbuchstabe J vor den Nachnamen geraten: 'JIrmer'. " "Hans-Jürgen Irmer (CDU/CSU) hat in WP 19 ein Mandat"),
    ("18/62", "Kühn-Menge", "Helga"): (
        "Kühn-Mengel", "Helga", "11003010",
        "Abgeschnittener Nachname: 'Kühn-Menge' statt 'Kühn-Mengel'. " "Dieselbe Sitzung nennt sie in Anlage 3 richtig, mit vollem Namen"),
}


NAME_VERSCHMOLZEN = {
    "ID208205200": ("Dr.", "Lena", "Kreck",
                    "Klartext im selben Element: 'Dr. Lena Kreck, Senatorin " "(Berlin):'; Rolle passt. Mende hat 11005303 mit 9 Reden " "und wurde in dieser Sitzung nur begruesst"),
}


BEHELFSKENNUNG = {
    "999980100": ("11004640", "Bettina Bähr-Losse", 9, "SPD"),
    "999980101": ("11004641", "Rainer Hajek", 1, "CDU/CSU"),
    "999980102": ("11004642", "Mathias Edwin Höschel", 3, "CDU/CSU"),
    "999980200": ("11004348", "Gisela Manderla", 2, "CDU/CSU"),
    "999980202": ("11004437", "Nina Warken", 1, "CDU/CSU"),
    "999190001": ("11004426", "Carsten Träger", 11, "SPD"),
    "999990084": ("11004951", "Charlotte Schneidewind-Hartnagel", 2,
                  "BÜNDNIS 90/DIE GRÜNEN"),
    "999990085": ("11004950", "Joe Weingarten", 8, "SPD"),
    "999990087": ("11004954", "Saskia Ludwig", 6, "CDU/CSU"),
    "999990088": ("11004953", "Sylvia Lehmann", 7, "SPD"),
    "999990089": ("11004956", "Sandra Bubendorfer-Licht", 6, "FDP"),
    "999990092": ("11004957", "Bela Bach", 6, "SPD"),
    "999990096": ("11004958", "Matthias Nölke", 5, "FDP"),
    "999990097": ("11004959", "Dorothee Martin", 7, "SPD"),
    "999990104": ("11004961", "Christian Natterer", 1, "CDU/CSU"),
    "999990105": ("11004962", "Janosch Dahmen", 11, "BÜNDNIS 90/DIE GRÜNEN"),
    "999990107": ("11004966", "Kristina Nordt", 3, "CDU/CSU"),
    "999990108": ("11004967", "Maika Friemann-Jennert", 1, "CDU/CSU"),
    "999990110": ("11004968", "Christopher Gohl", 2, "FDP"),
    "999990123": ("11005289", "Clara Bünger", 23, "DIE LINKE"),
    "999990130": ("11005301", "Alexander Bartz", 1, "SPD"),
    "999990132": ("11005302", "Emily Vontz", 2, "SPD"),
    "10000":     ("11004942", "Marja-Liisa Völlers", 2, "SPD"),
}


BEHELFSKENNUNG_REGIERUNG = {
    "999990074": ("11005217", "Svenja Schulze", 313,
                  "Bundesministerin BMU (WP 19), BMZ (WP 20)",
                  "einziger Name der Kennung ueber alle 313 Reden; keine " "regulaere Kennung im Protokoll; alle 160 Reden der WP 20 " "liegen im SPD-Mandat ab 26.10.2021. Die 153 Reden der " "WP 19 bleiben ohne Fraktion — damals ohne Mandat."),
    "999990112": ("11003574", "Günter Krings", 10,
                  "Parl. Staatssekretär beim Bundesminister des Innern",
                  "spricht in WP 18 auch unter 11003574 (31 Reden, CDU/CSU); " "alle 10 Reden liegen im Mandat"),
    "999990109": ("11003482", "Gabriele Lösekrug-Möller", 7,
                  "Parl. Staatssekretärin bei der Bundesministerin für " "Arbeit und Soziales",
                  "spricht in WP 18 auch unter 11003482 (9 Reden, SPD); " "alle 7 Reden liegen im Mandat"),
    "999990116": ("11003055", "Ralf Brauksiepe", 6,
                  "Parl. Staatssekretär bei der Bundesministerin der " "Verteidigung",
                  "Behelfskennung bis 05.02.2015, regulaere Kennung " "11003055 ab 19.03.2015 — sie loesen einander ab; alle 6 " "Reden liegen im Mandat"),
    "999990127": ("11003525", "Enak Ferlemann", 6,
                  "Parl. Staatssekretär beim Bundesminister für Verkehr und " "digitale Infrastruktur",
                  "Behelfskennung bis 05.03.2015, regulaere Kennung ab " "19.03.2015; alle 6 Reden liegen im Mandat. Dieselbe " "Nummer trug spaeter Peter Beuth (OHNE_KENNUNG)"),
    "999990124": ("11003259", "Annette Widmann-Mauz", 2,
                  "Parl. Staatssekretärin beim Bundesminister für Gesundheit",
                  "spricht in WP 18 auch unter 11003259 (11 Reden, CDU/CSU); " "beide Reden liegen im Mandat. Dieselbe Nummer trug " "spaeter Andreas Bovenschulte (OHNE_KENNUNG)"),
    "999990006": ("11003031", "Hans-Peter Bartels", 7,
                  "Wehrbeauftragter des Deutschen Bundestages",
                  "einziger Name der Kennung; **keine** der 7 Reden liegt im " "Mandat — sein SPD-Mandat endete am 20.05.2015, die Reden " "beginnen am 03.12.2015. Die Aufloesung dient allein der " "Personenbruecke und gibt ihm keine Fraktion."),
}


def mdb_kennung(redner_id):
    if not redner_id:
        return None
    if redner_id.startswith("11"):
        return redner_id
    if redner_id in BEHELFSKENNUNG:
        return BEHELFSKENNUNG[redner_id][0]
    if redner_id in BEHELFSKENNUNG_REGIERUNG:
        return BEHELFSKENNUNG_REGIERUNG[redner_id][0]
    return None


def korrigierter_vorname(rede_id, vorname):
    if rede_id in NAME_KORREKTUR:
        return NAME_KORREKTUR[rede_id][1]
    return vorname


def korrigierte_kennung(rede_id, kennung):
    if rede_id in KENNUNG_KORREKTUR:
        return KENNUNG_KORREKTUR[rede_id][1]
    if rede_id in INTERNE_KENNUNG:
        return INTERNE_KENNUNG[rede_id][0]
    if rede_id in OHNE_SPRECHER:
        return UNBEKANNT
    return kennung


def korrigierter_name(rede_id, titel, vorname, nachname):
    if rede_id in NAME_VERSCHMOLZEN:
        return NAME_VERSCHMOLZEN[rede_id][:3]
    if rede_id in NAME_KORREKTUR:
        eintrag = NAME_KORREKTUR[rede_id]
        return titel, eintrag[1], eintrag[2]
    if rede_id in INTERNE_KENNUNG:

        return titel, vorname, nachname
    return titel, vorname, nachname


def korrekturgrund(rede_id):
    if rede_id in KENNUNG_KORREKTUR:
        return KENNUNG_KORREKTUR[rede_id][3]
    if rede_id in INTERNE_KENNUNG:
        return (INTERNE_KENNUNG[rede_id][3] + " — eigene Kennung, weil die " "Person keine der Bundestagsverwaltung haben kann")
    if rede_id in OHNE_SPRECHER:
        return OHNE_SPRECHER[rede_id]
    if rede_id in NAME_VERSCHMOLZEN:
        return NAME_VERSCHMOLZEN[rede_id][3]
    return ""
