import sys
import logging
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql_file, query

META_SCHEMA = "meta"
TABELLE     = "datenlieferung"


def nicht_angegeben(wo, datum):
    return f"nicht angegeben ({wo}, geprueft {datum})"


GERDA_ZITAT = ("Heddesheimer, Hilbig, Sichart & Wiedemann (2025): German " "Election Database. Scientific Data 12, 618. " "doi:10.1038/s41597-025-04811-5")
GERDA_AUTOR = "Heddesheimer, Hilbig, Sichart & Wiedemann"
GERDA_HRSG  = "Springer Nature (Scientific Data)"
BBSR_ZITAT  = ("Bundesinstitut fuer Bau-, Stadt- und Raumforschung (BBSR), " "Bonn: Umsteigeschluessel der laufenden Raumbeobachtung")
BBSR        = "Bundesinstitut fuer Bau-, Stadt- und Raumforschung (BBSR), Bonn"
BWL         = "Die Bundeswahlleiterin"
BT          = "Deutscher Bundestag"
DIP         = "Deutscher Bundestag / Dokumentations- und Informationssystem DIP"
BT_LIZENZ   = nicht_angegeben("bundestag.de/services/opendata", "25.08.2026")


V_SHP    = "shp2pgsql in eine Staging-Tabelle, danach SQL in die Clean-Schicht"
V_COPY   = "psql \\copy der gelieferten Datei in eine Staging-Tabelle"
V_PYCSV  = "Python liest die Datei und schreibt sie ueber psql ein"
V_API    = "HTTP-Abruf der API, Roh-JSON in JSONB, danach SQL in die Clean-Schicht"
V_XML    = "XML-Auswertung in Python, danach SQL"
V_XLSX   = "XLSX-Auswertung in Python, danach SQL"
V_HTML   = "HTML-Auswertung in Python, danach SQL"
V_PDF    = "PDF-Auswertung in Python nach CSV, danach SQL"
V_SQL    = "aus vorhandenen Tabellen gerechnet, reines SQL"


LIEFERUNGEN = [


    {
        "lieferung_id": "gerda_federal_muni_unharm",
        "bezeichnung":  "GERDA federal_muni_unharm: Wahlergebnisse je Gemeinde im Gebietsstand " "der jeweiligen Wahl. Die Briefwahl ist nicht als Verbund ausgewiesen, " "sondern gewichtet auf die beteiligten Gemeinden verteilt, sodass jede " "Gemeinde ein vollstaendiges Ergebnis traegt. Parteiwerte als Anteil, " "nicht als Stimmenzahl",
        "herausgeber":  GERDA_HRSG,
        "urheber":      GERDA_AUTOR,
        "zitat":        GERDA_ZITAT,
        "datei":        "federal_muni_unharm.txt",
        "lizenz":       "CC-BY-4.0",
        "art":          "forschung",
        "limitierungen": "Die Parteiwerte sind ANTEILE, keine Stimmen; " "stimmen_zurueckgerechnet ist eine Rueckrechnung mit Rundungsfehler. " "Wer exakte Stimmen braucht, nimmt die amtliche Ebene. Fuer Gemeinden " "in einem Briefwahlverbund sind die Werte nicht ausgezaehlt, sondern " "gewichtet zugeteilt; reicht ein Verbund ueber eine Wahlkreisgrenze, " "wandert dabei Stimmanteil ueber diese Grenze -- gemessen bis zu " "gut zehn Prozentpunkte. Kein Wahlkreisbezug, geteilte Grossstaedte " "stehen als ganze Stadt. cdu_csu, far_right, far_left sind " "GERDA-Zusammenfassungen und keine Parteien. Der Nenner ist " "number_voters -- Anteile aus den harm-Fassungen sind damit nicht " "vergleichbar",
        "uebernahme_verfahren": V_COPY,
    },
    {
        "lieferung_id": "gerda_federal_muni_harm_21",
        "bezeichnung":  "GERDA federal_muni_harm_21: dieselben Wahlergebnisse je Gemeinde, " "ueber den BBSR-Umsteigeschluessel auf den einheitlichen Gebietsstand " "2021 gerechnet. Damit sind Gemeinden ueber Wahlen hinweg vergleichbar, " "auch wo sie zwischenzeitlich fusioniert wurden",
        "herausgeber":  GERDA_HRSG,
        "urheber":      GERDA_AUTOR,
        "zitat":        GERDA_ZITAT,
        "datei":        "federal_muni_harm_21.txt",
        "gebietsstand": "2021-12-31",
        "lizenz":       "CC-BY-4.0",
        "art":          "forschung",
        "limitierungen": "Ausgerechnet das Bezugsjahr 2021 ist unvollstaendig: 10.641 " "Gemeinden gegen 10.787 in den harmonisierten Jahren. 146 Gemeinden " "haben 2013 und 2017 eine Zeile, 2021 keine -- Kleinstgemeinden nach " "Paragraf 68 BWO und die zwoelf Ahrtal-Gemeinden nach der Flut. Ihre " "Stimmen stecken in der aufnehmenden Gemeinde, deren Wert dadurch zu " "hoch ist, ohne dass man es der Zeile ansieht. Die Publikation " "behauptet das Gegenteil (balanced panels, all municipalities). Vier " "Spalten sind in jeder Zeile leer -- area_cw, pop_cw, ags_21, " "flag_unsuccessful_naive_merge --, sodass aus der Datei allein nicht " "erkennbar ist, ob eine Zeile durchgereicht oder gerechnet wurde. " "2021 ist nicht harmonisiert, sondern unveraendert durchgereicht. Der " "Nenner ist total_votes, nicht number_voters",
        "uebernahme_verfahren": V_COPY,
    },
    {
        "lieferung_id": "gerda_federal_cty_unharm",
        "bezeichnung":  "GERDA federal_cty_unharm: Wahlergebnisse je Kreis im Gebietsstand der " "jeweiligen Wahl, aus der Gemeindeebene aggregiert. Nur Zweitstimmen, " "Parteiwerte als Anteil an den gueltigen Stimmen",
        "herausgeber":  GERDA_HRSG,
        "urheber":      GERDA_AUTOR,
        "zitat":        GERDA_ZITAT,
        "datei":        "federal_cty_unharm.txt",
        "lizenz":       "CC-BY-4.0",
        "art":          "forschung",
        "limitierungen": "Der Gebietsstand ist der Jahresendstand des Wahljahrs, nicht der " "Wahltag (gemessen gegen raum.kreisstand: 402/402 auf 31.12.2013, " "401/401 auf 31.12.2017, 400/400 auf 31.12.2021). Die Parteianteile " "summieren sich je Kreis auf 0,96 bis 0,997 statt auf 1: die " "ungueltigen Stimmen stecken im Nenner, und nicht jede Partei ist " "einzeln ausgewiesen -- in 421 von 1.203 Kombinationen fehlen bis zu " "1.810 Stimmen, eine Sammelspalte gibt es nicht. 2013 sind 81 der 110 " "Parteispalten durchgaengig leer; eine fehlende Zeile heisst 'nicht " "ausgewiesen', nicht 'null Stimmen', und beides ist in der Quelle " "nicht unterscheidbar. Nur Zweitstimmen, keine Flaeche, keine " "Einwohnerzahl. Berlin 2021 weicht um rund 8.300 Wahlberechtigte ab, " "weil unsere Quelle den Stand nach der Wiederholungswahl fuehrt",
        "uebernahme_verfahren": V_COPY,
    },
    {
        "lieferung_id": "gerda_federal_wkr_unharm",
        "bezeichnung":  "GERDA federal_wkr_unharm: Wahlergebnisse je Wahlkreis, aus der " "Gemeindeebene aggregiert. Erst- und Zweitstimmen je Partei sowie die " "siegreiche Partei je Wahlkreis -- Personen fuehrt die Lieferung nicht",
        "herausgeber":  GERDA_HRSG,
        "urheber":      GERDA_AUTOR,
        "zitat":        GERDA_ZITAT,
        "datei":        "federal_wkr_unharm.txt",
        "lizenz":       "CC-BY-4.0",
        "art":          "forschung",
        "limitierungen": "Urnen- und Briefwahl sind nur summiert ausgewiesen und auf keiner " "Ebene trennbar. Erststimmen stehen ausschliesslich nach Partei; " "elected_party nennt die Partei und nicht die gewaehlte Person. " "Kleinparteien sind nicht durchgaengig einzeln ausgewiesen. Die " "Jahrgaenge sind ungleich besetzt: 2013 fuehrt jede Partei in jedem " "Wahlkreis, auch wo sie nicht angetreten ist (13.122 Nullzeilen), " "2017 und 2021 lassen die Zeile weg -- 'nicht angetreten' und 'null " "Stimmen' sind deshalb nicht unterscheidbar, und die Zahl der " "antretenden Parteien ergibt sich nicht aus der Zeilenzahl",
        "uebernahme_verfahren": V_COPY,
    },
    {


        "lieferung_id": "gerda_federal_cty_harm",
        "bezeichnung":  "GERDA federal_cty_harm: Wahlergebnisse je Kreis, ueber den " "BBSR-Kreisschluessel auf den einheitlichen Gebietsstand 2021 " "gerechnet. 400 Kreise in jeder Wahl ab 1990 und damit als Zeitreihe " "auswertbar",
        "herausgeber":  GERDA_HRSG,
        "urheber":      GERDA_AUTOR,
        "zitat":        GERDA_ZITAT,
        "datei":        "federal_cty_harm.txt",
        "gebietsstand": "2021-12-31",
        "lizenz":       "CC-BY-4.0",
        "art":          "abgeleitet",
        "limitierungen": "Die Abdeckung beginnt 1990 und nicht 1953: die Publikation nennt " "1953 fuer federal_cty_unharm, fuer die harmonisierte Fassung fehlen " "davor die Umsteigeschluessel. Keine Erststimmen. Die Anteile " "beziehen sich auf total_votes und sind damit nicht mit " "gemeinde_gerda_unharm oder kreis_gerda_unharm vergleichbar. " "Umgerechnet ist mit dem Bevoelkerungsgewicht des " "BBSR-Kreisschluessels auf den Gebietsstand 2021",
        "uebernahme_verfahren": V_COPY,
    },


    {
        "lieferung_id": "kreisebene_amtlich",
        "bezeichnung":  "Wahlergebnisse je Kreisteil (Kreis x Wahlkreis), aus den Wahlbezirken " "aggregiert. Erststimmen bleiben je Wahlkreis getrennt, weil sie " "wahlkreisgebunden sind.",
        "herausgeber":  "eigene Ableitung",
        "zitat":        f"{BWL}: Wahlbezirksstatistik der Bundestagswahlen 2013, 2017 und 2021, " "aggregiert",
        "lizenz":       "dl-de/by-2-0",
        "art":          "abgeleitet",
        "limitierungen": "Erststimmen duerfen NICHT ueber die Wahlkreisnummer summiert werden: " "die Summe waere die Stimmenzahl fuer verschiedene Kandidatinnen und " "Kandidaten und damit eine Zahl ohne Bedeutung -- betroffen waeren " "2021 rund 21,9 Millionen Erststimmen. Die Aggregation selbst ist " "exakt, drei Bedingungen sind geprueft: keine der 145 Gemeinden ohne " "eigenen Wahlbezirk zaehlt in einem fremden Kreis mit, kein " "Briefwahlverbund reicht ueber eine Kreisgrenze, jede Gemeinde " "gehoert ueber den AGS zu genau einem Kreis. Die Aggregation sagt " "nichts ueber Wahlkreise: 108 von 400 Kreisen liegen 2021 in " "mehreren. Berlin 2021 weicht gegen GERDA um rund 8.300 " "Wahlberechtigte ab, weil unsere Quelle den Stand nach der " "Wiederholungswahl fuehrt",
        "basis":        ["bwl_wahlbezirke_2013", "bwl_wahlbezirke_2017",
                         "bwl_wahlbezirke_2021"],
        "uebernahme_verfahren": V_SQL,
    },
    {


        "lieferung_id": "grossstadt_wkr_2013",
        "bezeichnung":  "Geteilte Gemeinden je Wahlkreis 2013: 19 Staedte liegen in mehr als " "einem Wahlkreis und werden deshalb je Wahlkreisteil gefuehrt, mit dem " "Ergebnis der dortigen Wahlbezirke und der am Wahlkreis zerschnittenen " "Flaeche. Einzige nicht-grossstaedtische darunter ist Suedeichsfeld",
        "herausgeber":  "eigene Ableitung (kein Herausgeber)",
        "zitat":        f"{BWL}: Wahlbezirksstatistik zur Bundestagswahl 2013, veraendert",
        "lizenz":       "dl-de/by-2-0 (Basis Bundeswahlleiterin)",
        "wahljahr":     2013,
        "art":          "abgeleitet",
        "limitierungen": "Das Ergebnis je Stadtteil ist exakt -- es ist die Summe der " "Wahlbezirke mit dieser Wahlkreisnummer. Die FLAECHE je Teil " "entsteht dagegen, indem das Stadtpolygon an den Wahlkreisgrenzen " "zerschnitten wird; keine amtliche Quelle sagt, welcher Teil einer " "Stadt zu welchem Wahlkreis gehoert. Es ist die einzige Stelle im " "Bestand, an der geschnitten statt vereinigt wird. Diese Einheiten " "fehlen im Bestand der amtlichen Auszaehleinheiten: Wer nur einen " "der beiden nimmt, hat Loecher. Die Teilnummer ist als Schluessel " "stabil, nicht als Gebiet -- derselbe Teil einer Stadt kann von " "Wahl zu Wahl in einem anderen Wahlkreis liegen. Fuer 2013 liegen " "die Wahlkreise groeber vor als die Gemeinden, sodass die " "Trennlinie im Stadtinneren ungenauer ist als in den spaeteren " "Wahlen und Randstreifen ohne Sonderbehandlung keinen Wahlkreis " "finden.",
        "basis":        ["bwl_wahlbezirke_2013"],
        "uebernahme_verfahren": V_SQL,
    },
    {
        "lieferung_id": "grossstadt_wkr_2017",
        "bezeichnung":  "Geteilte Gemeinden je Wahlkreis 2017: 18 Staedte liegen in mehr als " "einem Wahlkreis und werden je Wahlkreisteil gefuehrt, mit dem Ergebnis " "der dortigen Wahlbezirke und der am Wahlkreis zerschnittenen Flaeche",
        "herausgeber":  "eigene Ableitung (kein Herausgeber)",
        "zitat":        f"{BWL}: Wahlbezirksstatistik zur Bundestagswahl 2017, veraendert",
        "lizenz":       "dl-de/by-2-0 (Basis Bundeswahlleiterin)",
        "wahljahr":     2017,
        "art":          "abgeleitet",
        "limitierungen": "Das Ergebnis je Teil ist exakt -- es ist die Summe der Wahlbezirke " "mit dieser Wahlkreisnummer. Die FLAECHE je Teil entsteht dagegen, " "indem das Stadtpolygon an den Wahlkreisgrenzen zerschnitten wird; es " "gibt keine amtliche Quelle, die sagt, welcher Teil Koelns zu " "Wahlkreis 101 gehoert. Es ist die einzige Stelle im Bestand, an der " "geschnitten statt vereinigt wird. Diese Einheiten sind in " "kleinst_100_amtlich NICHT enthalten: wer nur einen der beiden " "Bestaende nimmt, hat Loecher. Die Teilnummer ist als Schluessel " "stabil, nicht als Gebiet -- Muenchen-Teil 1 ist 2013 der Wahlkreis " "218, ab 2017 der Wahlkreis 217. 18 geteilte Staedte, zusammen 55 " "Stadtteile",
        "basis":        ["bwl_wahlbezirke_2017"],
        "uebernahme_verfahren": V_SQL,
    },
    {
        "lieferung_id": "grossstadt_wkr_2021",
        "bezeichnung":  "Geteilte Gemeinden je Wahlkreis 2021: 18 Staedte liegen in mehr als " "einem Wahlkreis und werden je Wahlkreisteil gefuehrt, mit dem Ergebnis " "der dortigen Wahlbezirke und der am Wahlkreis zerschnittenen Flaeche. " "Zusammen 55 Teile und 17,0 Prozent der Wahlberechtigten",
        "herausgeber":  "eigene Ableitung (kein Herausgeber)",
        "zitat":        f"{BWL}: Wahlbezirksstatistik zur Bundestagswahl 2021, veraendert",
        "lizenz":       "dl-de/by-2-0 (Basis Bundeswahlleiterin)",
        "wahljahr":     2021,
        "art":          "abgeleitet",
        "limitierungen": "Das Ergebnis je Teil ist exakt -- es ist die Summe der Wahlbezirke " "mit dieser Wahlkreisnummer. Die FLAECHE je Teil entsteht dagegen, " "indem das Stadtpolygon an den Wahlkreisgrenzen zerschnitten wird; es " "gibt keine amtliche Quelle, die sagt, welcher Teil Koelns zu " "Wahlkreis 101 gehoert. Es ist die einzige Stelle im Bestand, an der " "geschnitten statt vereinigt wird. Diese Einheiten sind in " "kleinst_100_amtlich NICHT enthalten: wer nur einen der beiden " "Bestaende nimmt, hat Loecher. Die Teilnummer ist als Schluessel " "stabil, nicht als Gebiet -- Muenchen-Teil 1 ist 2013 der Wahlkreis " "218, ab 2017 der Wahlkreis 217. 18 geteilte Staedte, zusammen 55 " "Stadtteile -- das sind 17,0 Prozent der Wahlberechtigten",
        "basis":        ["bwl_wahlbezirke_2021"],
        "uebernahme_verfahren": V_SQL,
    },


    {
        "lieferung_id": "gemeindefrei_wahlkreis",
        "bezeichnung":  "Wahlkreis der gemeindefreien Gebiete, aus der Flaeche bestimmt: " "643 Zuordnungen ueber die drei Wahlen. Waelder, Seen und " "Truppenuebungsplaetze haben nie einen Wahlbezirk, weil dort " "niemand waehlt -- sie fehlen deshalb in der Wahlbezirksstatistik, " "aus der die Zuordnung sonst kommt. Ihr Wahlkreis entsteht hier " "aus der Verschneidung des Gemeindepolygons am Wahltag mit den " "Wahlkreisen derselben Wahl; die groesste Ueberlappung entscheidet.",
        "herausgeber":  "eigene Ableitung",
        "zitat":        "(c) GeoBasis-DE / BKG (Daten veraendert) sowie Bundeswahlleiter / " "Statistisches Bundesamt: Geometrie der Wahlkreise, verschnitten",
        "art":          "abgeleitet",
        "basis":        ["bkg_vg250", "bwl_wahlkreisgeometrie"],
        "uebernahme_verfahren": "PostGIS-Verschneidung, groesste Ueberlappung je Gebiet",
        "eingriffe":    "G1 in: drei Gebiete der Wahl 2013, deren " "Wahlkreis die grobe VG1000-Geometrie nicht hergibt",
        "limitierungen": "Die Zuteilung ist eine ENTSCHEIDUNG, keine abgelesene Angabe: Nur " "ein Teil der gemeindefreien Gebiete liegt ganz in einem Wahlkreis, " "die uebrigen schneiden zwei bis fuenf -- Waelder und Seen machen an " "Wahlkreisgrenzen nicht halt. Welche Gebiete betroffen sind, weist " "eine eigene Spalte je Zeile aus. Fuer die Wahl 2013 liegt die " "Wahlkreisgeometrie groeber vor als die Gemeindegeometrie, sodass die " "Verschneidung dort unzuverlaessig ist.",
    },
    {
        "lieferung_id": "kreis_wahlkreis_zuschnitt",
        "bezeichnung":  "Kreisteile je Wahlkreis: das Stueck eines Kreises, das in einem " "bestimmten Wahlkreis liegt. Aus der Verschneidung von Kreisstand " "und Wahlkreisstand, weil Kreise und Wahlkreise einander nicht " "enthalten - 108 der 400 Kreise reichen 2021 ueber mehr als einen " "Wahlkreis.",
        "herausgeber":  "eigene Ableitung",
        "zitat":        "(c) GeoBasis-DE / BKG (Daten veraendert) sowie Bundeswahlleiter / " "Statistisches Bundesamt: Geometrie der Wahlkreise, verschnitten",
        "art":          "abgeleitet",
        "limitierungen": "Die Richtung nach unten ist nicht exakt: ein Merkmal, das nur je " "Kreis vorliegt -- Arbeitslosenquote, Altersstruktur --, laesst sich " "nicht ohne Annahme auf Wahlkreise verteilen. Deshalb fuehrt die " "Lieferung Wahlberechtigte und Gemeindezahl je Schnitt mit: wer " "gewichten will, hat damit den Nenner; die Gewichtung selbst bleibt " "eine Entscheidung und wird hier nicht getroffen. Fuer Analysen, die " "Strukturdaten mit Wahlergebnissen verbinden, ist der Weg nach oben " "der richtige. Die Zuordnung gilt je Wahl und nicht allgemein, weil " "sich Kreise und Wahlkreise beide aendern. Wahlberechtigte stehen nur " "bei Urnenwahlbezirken, Briefwahlbezirke fuehren 0",
        "basis":        ["bkg_vg250", "bwl_wahlkreisgeometrie"],
        "uebernahme_verfahren": V_SQL,
    },
    {
        "lieferung_id": "hexkarte_wahlkreis",
        "bezeichnung":  "Kartogramm der Wahlkreise: je Wahlkreisstand ein gleich grosses " "Sechseck, das die Nachbarschaftsbeziehungen der tatsaechlichen " "Geometrie bewahrt. Dient allein der Darstellung und ist fuer " "raeumliche Berechnungen nicht zu verwenden.",
        "herausgeber":  "eigene Berechnung",
        "zitat":        "Bundeswahlleiter / Statistisches Bundesamt: Geometrie der " "Wahlkreise, in ein Sechseckraster ueberfuehrt",
        "art":          "abgeleitet",
        "basis":        ["bwl_wahlkreisgeometrie"],
        "uebernahme_verfahren": "Rasterberechnung ueber den Wahlkreisgeometrien, danach " "Handarbeit in QGIS und einem eigenen Browser-Editor",
        "limitierungen": "Nicht vollstaendig gerechnet: Die Lage einzelner Sechsecke ist von " "Hand gesetzt. Die Guete steht je Wahlkreis in `nachbarn_real`, " "`nachbarn_erhalten` und `nachbarn_quote`",
    },
    {
        "lieferung_id": "wahlkreisuebergang",
        "bezeichnung":  "Kontinuitaet der Wahlkreiszuschnitte zwischen zwei Wahlen, samt der " "Gemeinden, die den Wahlkreis gewechselt haben. Eine amtliche " "Kontinuitaet gibt es nicht; sie wird aus dem Vergleich der " "zugeordneten Gemeindemengen hergestellt, wobei die aeltere Menge " "zuvor ueber die Gemeindefiliationen auf den juengeren Gebietsstand " "gehoben wird.",
        "herausgeber":  "eigene Ableitung",
        "zitat":        "Die Bundeswahlleiterin: Wahlbezirksstatistik der Bundestagswahlen " "2013, 2017 und 2021, sowie Statistisches Bundesamt: Gebietsaenderungen " "- verglichen",
        "art":          "abgeleitet",


        "basis":        ["bwl_wahlbezirke_2013", "bwl_wahlbezirke_2017",
                         "bwl_wahlbezirke_2021", "bwl_wahlkreisgeometrie",
                         "destatis_gebietsaenderungen"],
        "uebernahme_verfahren": V_SQL,
        "limitierungen": "Konstruiert, nicht belegt: Die Kontinuitaet gilt nur unter den " "Annahmen der Bildungsregel. Fuer 2021 nennt die amtliche Liste " "17 veraenderte Wahlkreise, der Mengenvergleich zeigt bei einem " "davon keinen Wechsel; beide Angaben stehen nebeneinander und " "werden nicht gegeneinander aufgerechnet",
    },
    {
        "lieferung_id": "einheitsuebergang",
        "bezeichnung":  "Uebergaenge zwischen den Auswertungseinheiten je Paar " "aufeinanderfolgender Wahlen: welche Einheit wurde zu welcher, blieb " "unveraendert, wechselte den Typ oder loeste sich auf. Aus dem " "Vergleich der Mitgliedermengen - gleiche Menge heisst gleiche " "Einheit.",
        "herausgeber":  "eigene Ableitung",
        "zitat":        "Die Bundeswahlleiterin: Wahlbezirksstatistik der Bundestagswahlen " "2013, 2017 und 2021 - Mitgliedermengen verglichen",
        "art":          "abgeleitet",
        "basis":        ["bwl_wahlbezirke_2013", "bwl_wahlbezirke_2017",
                         "bwl_wahlbezirke_2021", "grossstadt_wkr_2013",
                         "grossstadt_wkr_2017", "grossstadt_wkr_2021"],
        "uebernahme_verfahren": V_SQL,
        "limitierungen": "Die Zusammensetzung der Auswertungseinheiten folgt der Organisation " "der Wahlvorstaende und nicht dem Gebietsstand: 746, 707 und 624 " "Briefwahlverbuende in den drei Wahlen, ohne dass eine entsprechende " "Zahl von Gemeinden entstand oder verging",
    },
    {
        "lieferung_id": "nachbarschaft_wahlkreis",
        "bezeichnung":  "Welche Wahlkreise aneinandergrenzen, je Wahl neu berechnet, mit der " "Laenge der gemeinsamen Grenze. Aus den Geometrien abgeleitet und " "Grundlage fuer Nachbarschaftsanalysen und das Hexagon-Kartogramm",
        "herausgeber":  "eigene Berechnung",
        "zitat":        "Bundeswahlleiter / Statistisches Bundesamt: Geometrie der " "Wahlkreise - Nachbarschaften berechnet",
        "art":          "abgeleitet",
        "basis":        ["bwl_wahlkreisgeometrie"],
        "uebernahme_verfahren": "PostGIS-Berechnung ueber den Wahlkreisgeometrien",
        "limitierungen": "An die Auflösung der Ausgangsgeometrie gebunden: 2013 liegt VG1000 " "zugrunde, 2017 und 2021 VG250. Die Grenzlaengen der drei Wahlen " "sind daher nicht unmittelbar vergleichbar",
    },
    {
        "lieferung_id": "cpp_bt_fobbe",
        "bezeichnung":  "Corpus der Plenarprotokolle des Bundestages (CPP-BT), " "aufbereitet von Seán Fobbe: 72.021 Reden der " "Wahlperioden 18 bis 20 mit Sprecherkennung, " "Fraktionsangabe, Rolle, Fundstelle und Volltext. " "ID-fuer-ID identisch mit den 698 annotierten " "Protokoll-XML des Bundestages, geprueft am 28.08.2026. " "Grundlage saemtlicher Reden im Bestand - die " "DIP-Schnittstelle fuehrt das Protokoll als Dokument, " "nicht die einzelne Rede.",
        "herausgeber":  "Seán Fobbe",
        "urheber":      "Fobbe, Seán",
        "zitat":        "Fobbe, Seán (2026): Corpus der Plenarprotokolle des " "Deutschen Bundestages (CPP-BT), Version 2026-01-17. " "Zenodo. doi:10.5281/zenodo.18177196",
        "datei":        "CPP-BT_2026-01-17_DE_PQT_Reden_Gesamt.parquet",
        "lizenz":       "CC0-1.0",
        "art":          "forschung",
        "uebernahme_verfahren": "Parquet gelesen, Spalten uebernommen, keine " "eigene Bearbeitung des Textes",
        "limitierungen": "Die Quelle hat vor der Veroeffentlichung selbst eingegriffen und " "legt das im eigenen Quellcode offen: sechs Sitzungsdaten repariert, " "deren XML-Attribut eine fehlerhafte Zeichenkette traegt, die " "Fraktionsschreibweisen normalisiert, drei Personenfaelle einzeln " "korrigiert und 42 Reden entfernt, die durch einen Protokollfehler " "doppelt vorlagen. Diese Eingriffe sind nicht die dieser Arbeit und " "werden nicht wiederholt. Die Sprecherkennung ist die des Protokolls " "und keine Personenkennung; acht Kennungen tragen Namen verschiedener " "Personen und sind als mehrdeutig markiert. 5.962 Reden wurden zu " "Protokoll gegeben und nie gesprochen, was aus der Tabelle NICHT " "hervorgeht -- dafuer ist das Protokoll-XML noetig. Sieben Reden " "haben keine Sprecherkennung, sechs davon auch keinen Text.",
    },
    {
        "lieferung_id": "plenarkommentare",
        "bezeichnung":  "Zwischenrufe und Reaktionen aus den Plenarprotokollen: " "558.503 Klammerbloecke mit 661.412 Einzelereignissen und " "943.585 Urhebern. Je Ereignis eine Art und je Urheber die " "Angabe, ob eine ganze Fraktion, ein Teil von ihr, eine " "namentlich genannte Person oder das ganze Haus gemeint " "ist. Bisher stand davon nur ein Zaehler je Rede im " "Bestand.",
        "herausgeber":  "eigene Extraktion und Einteilung",
        "zitat":        "Deutscher Bundestag, Plenarprotokolle - Kommentare " "extrahiert; Einteilung nach Richter, Florian; Koch, " "Philipp; Franke, Oliver et al. 2020: Open Discourse. " "Harvard Dataverse, https://doi.org/10.7910/DVN/FIKIBO",
        "art":          "abgeleitet",
        "basis":        ["dip_plenarprotokolle"],
        "uebernahme_verfahren": "Klammerausdruecke aus dem annotierten XML, " "zerlegt in Einzelereignisse. Die dreizehn Arten folgen " "der Einteilung von Open Discourse; die Muster sind fuer " "die sauber gesetzten XML ab WP 18 neu geschrieben, da " "jene auf OCR-Text aelterer Protokolle arbeiten. " "Uebernommen ist die EINTEILUNG, nicht der Code.",
        "limitierungen": "Vier der dreizehn Arten fuehrt Open Discourse nicht und sind fuer " "diesen Bestand eigens gebildet. Ein kleiner Teil der namentlich " "genannten Urheber bleibt ohne Personenknoten -- ohne Treffer, mit " "widersprechender Fraktionsangabe oder mehrdeutig. Einige Ereignisse " "liessen sich keiner Art zuordnen.",
    },
    {
        "lieferung_id": "entschuldigte_abgeordnete",
        "bezeichnung":  "Entschuldigt fehlende Abgeordnete je Sitzung aus der " "Anlage der Plenarprotokolle: 26.902 Nennungen ueber 697 " "Sitzungen. Macht Anwesenheit als Bezugsgroesse " "verfuegbar - bisher war nicht zu unterscheiden, wer " "anwesend schwieg und wer fehlte.",
        "herausgeber":  "eigene Extraktion",
        "zitat":        "Deutscher Bundestag, Plenarprotokolle - Anlage 'Liste " "der entschuldigten Abgeordneten'",
        "art":          "abgeleitet",
        "basis":        ["dip_plenarprotokolle"],
        "uebernahme_verfahren": "Anlage ueber Attribut ODER Ueberschrift " "gegriffen, da acht Protokolle kein oder ein leeres " "anlagen-typ tragen. Namen in drei Schreibweisen, " "Ortszusatz vor und Grund hinter dem Namen getrennt.",
        "limitierungen": "KEINE Anwesenheitsliste: Gefuehrt wird, wer sich entschuldigt hat -- " "nicht, wer anwesend war, und nicht, wer unentschuldigt fehlte. Aus " "dem Fehlen einer Zeile folgt keine Anwesenheit. 49 von 697 Sitzungen " "fuehren ueberhaupt keine Liste, ohne dass die Daten den Grund " "nennen. Die Namen tragen keine Personenkennung.",
    },
    {
        "lieferung_id": "rede_top_zuordnung",
        "bezeichnung":  "Zuordnung der Reden zu den Tagesordnungspunkten: " "71.470 Zuordnungen zu 72.021 Reden. Das Protokoll " "fuehrt die Reden, das Dokumentations- und " "Informationssystem die Tagesordnung; eine gemeinsame " "Kennung fuehrt keine der beiden Quellen.",
        "herausgeber":  "eigene Zuordnung",
        "zitat":        "Deutscher Bundestag, Plenarprotokolle und DIP - Reden " "und Tagesordnungspunkte ueber die Protokollstruktur " "verbunden",
        "art":          "abgeleitet",
        "basis":        ["dip_plenarprotokolle", "cpp_bt_fobbe"],
        "uebernahme_verfahren": "Zwei Wege, beide an der Zeile vermerkt: 66.015 " "Zuordnungen ueber die Reihenfolge im Protokoll -- eine " "Rede gehoert zu dem Tagesordnungspunkt, unter dem sie " "steht --, 5.455 ueber den Kopf einer Anlage, der den " "Punkt ausdruecklich nennt.",
        "limitierungen": "Ein Teil der Reden bekommt keinen Tagesordnungspunkt: Sie stehen " "ausserhalb der Verhandlungsgliederung. Dort entsteht keine Zeile, " "und es wird keine geraten.",
    },
    {
        "lieferung_id": "erststimmen_bewerber_zuordnung",
        "bezeichnung":  "Zuordnung der amtlichen Erststimmen zu den Personen, die sie erhalten " "haben: 8.677 Direktbewerbungen der Wahlen 2013, 2017 und 2021. Noetig, " "weil die amtliche Statistik Stimmen nur je Partei und Raumeinheit " "fuehrt und keine Personen kennt",
        "herausgeber":  "eigene Zuordnung",
        "zitat":        "Bundeswahlleiterin, Endgueltige Ergebnisse - " "Erststimmen ueber die Direktbewerbung je Partei und " "Wahlkreis den Bewerberinnen und Bewerbern zugeordnet",
        "art":          "abgeleitet",
        "basis":        ["wahlkreisebene_amtlich", "aw_api_v2"],
        "uebernahme_verfahren": "Je Partei und Wahlkreis stellt jede Partei " "genau eine Direktkandidatur auf. Die Erststimmen " "einer Partei in einem Wahlkreis sind damit die " "Stimmen genau dieser Person. Der Anschluss laeuft " "ueber den normalisierten Parteischluessel in " "meta.partei_mapping, weil beide Herausgeber die " "Parteinamen verschieden schreiben.",
        "limitierungen": "Die Zuordnung gilt nur fuer Direktbewerbungen: Wer allein ueber eine " "Landesliste antritt, erhaelt keine Erststimmen und kommt hier nicht " "vor. Ein kleiner Teil der Bewerbungen findet keinen Personenknoten " "und bleibt ohne Kante.",
    },
    {
        "lieferung_id": "rede_aktivitaet_zuordnung",
        "bezeichnung":  "Zuordnung der Reden des Plenarprotokolls zu den " "Aktivitaeten des Dokumentations- und " "Informationssystems: 72.478 Zuordnungen zu 72.021 Reden. " "Beide Quellen beschreiben dieselbe Handlung, fuehren " "aber keine gemeinsame Kennung; die Verbindung entsteht " "ueber Fundstelle und Person.",
        "herausgeber":  "eigene Zuordnung",
        "zitat":        "Deutscher Bundestag, DIP und Plenarprotokolle - Reden " "und Aktivitaeten ueber die Fundstelle verbunden",
        "art":          "abgeleitet",
        "basis":        ["dip_dokumente", "cpp_bt_fobbe"],
        "uebernahme_verfahren": "Abgleich ueber Protokollnummer, Seite und " "Quadrant der Fundstelle, zusaetzlich ueber die Person. " "Jede Zuordnung traegt, worauf sie beruht.",
        "limitierungen": "Nicht durchweg gleich sicher: Ein Teil der Zuordnungen stuetzt sich " "auf Fundstelle UND Person, die uebrigen nur auf den " "Fundstellenbereich, nur auf die Person oder auf eine Fundstelle, bei " "der die Person gerade nicht passt. Wie eine Zuordnung zustande kam, " "weist eine eigene Spalte aus; wer nur sichere will, filtert darauf. " "Ein Teil der Reden traegt ausdruecklich keine Aktivitaet.",
    },
    {


        "lieferung_id": "partei_normalisierung",
        "bezeichnung":  "Normalisierte Parteien dieses Bestands: 75 Einheiten, " "auf die 138 gelieferte Schreibweisen aus vier " "Lieferungen abgebildet sind. Grundlage der " "Parteizuordnung von Kandidaturen, Mandaten, " "Landeslisten und Wahlergebnissen.",
        "herausgeber":  "eigene Zuordnung",
        "zitat":        "Parteien, normalisiert aus den Schreibweisen der " "Ergebnisdateien und von abgeordnetenwatch.de",
        "art":          "abgeleitet",
        "basis":        ["bwl_wahlbezirke_2013", "bwl_wahlbezirke_2017",
                         "bwl_wahlbezirke_2021", "aw_api_v2"],
        "uebernahme_verfahren":
            "Je gelieferter Schreibweise eine Zeile in meta.partei_mapping, " "mit dem Verfahren, nach dem sie zugeordnet wurde. Die " "Schreibweise bleibt als eigener Knoten erhalten, sodass " "nachvollziehbar ist, welche Form in welcher Lieferung stand.",
        "limitierungen":
            "Der Bestand bildet die Parteien der Wahlen 2013, 2017 und 2021 " "ab. Parteien, die zu keiner dieser Wahlen angetreten sind, " "fehlen -- das BSW etwa, 2024 gegruendet, dessen Gruppe in " "Wahlperiode 20 im Bundestag sitzt; es kommt aus aw_api_v2 " "hinzu. Eine Schreibweise zeigt auf zwei Parteien: " "\"Buendnis21\" ueber die Wahlergebnisse auf buendnis21, ueber " "abgeordnetenwatch auf buendnis_21_rrp. Wer zuordnet, hat die " "Lieferung mitzufuehren.",
        "lizenz":       "CC0-1.0",
    },
    {


        "lieferung_id": "regierungsamt_zuordnung",
        "bezeichnung":  "Welche der 176 erfassten Aemter zur Bundesregierung gehoeren: 24 " "Aemter mit 144 Amtszeiten von 86 Personen. Die Quellen nennen " "Amtsbezeichnungen, sagen aber nicht, welche davon Regierungsaemter " "sind -- diese Zuordnung stellt das her. Aufgenommen sind die " "Bundesregierung nach Artikel 62 GG, also Kanzler und Minister " "einschliesslich des Vizekanzlers, und die Aemter, die in der Regierung " "mitarbeiten, ohne ihr anzugehoeren: Parlamentarische Staatssekretaere, " "Staatsminister, Staatssekretaere und der Chef des Bundeskanzleramtes",
        "herausgeber":  "eigene Zuordnung",
        "zitat":        "Zuordnung der Wikidata-Aemter zur Bundesregierung, " "von Hand getroffen",
        "art":          "abgeleitet",
        "basis":        ["wikidata"],
        "uebernahme_verfahren":
            "Von Hand eingeteilt. Die 176 Aemter wurden einzeln durchgesehen " "und die zur Bundesregierung gehoerenden als Liste von " "Wikidata-Kennungen im Ladeskript festgehalten. Keine Regel, " "kein Namensmuster, keine automatische Ableitung -- die Liste " "steht im Klartext und ist Zeile fuer Zeile nachpruefbar.",
        "limitierungen":
            "Nicht aufgenommen sind die Beauftragten der Bundesregierung " "(35 Amtszeiten): Sie werden von ihr bestellt, gehoeren ihr aber " "nicht an. Ebenso wenig die Landesregierungen -- Landesminister " "und Ministerpraesidenten sind Regierungsaemter, aber nicht die " "einer Bundesregierung; eine eigene Angabe dafuer waere zu " "ergaenzen, sobald sie gebraucht wird. Die Einteilung gilt fuer " "den Stand der Aemterabfrage vom 30.08.2026; kommt ein Amt " "hinzu, ist die Liste zu erweitern.",
        "lizenz":       "CC0-1.0",
    },
    {


        "lieferung_id": "personenknoten",
        "bezeichnung":  "Personenverzeichnis dieser Arbeit: 7.275 Menschen, zusammengefuehrt " "aus drei Quellen mit je eigenem Nummernkreis -- abgeordnetenwatch " "(6.905 Personen), DIP (1.654) und Bundestagsverwaltung (1.493). Jede " "Person traegt mindestens eine Kennung, viele mehrere, weil dieselbe " "Person in mehreren Quellen vorkommt. Enthalten sind neben den 1.271 " "Gewaehlten die unterlegenen Direktkandidaten und 301 Personen, die " "allein das DIP fuehrt: Landesministerinnen als Mitglieder des " "Bundesrates, Staatssekretaere und Beauftragte",
        "herausgeber":  "eigene Zusammenfuehrung",
        "zitat":        "Personenverzeichnis, zusammengefuehrt aus DIP, " "Stammdaten des Bundestages und abgeordnetenwatch.de",
        "art":          "abgeleitet",
        "basis":        ["dip_dokumente", "bt_mdb_stammdaten", "aw_api_v2",
                         "cpp_bt_fobbe"],
        "uebernahme_verfahren":
            "Zwei Wege verschiedener Belegqualitaet. HARTER SCHLUESSEL " "zwischen abgeordnetenwatch und der Bundestagsverwaltung: " "abgeordnetenwatch fuehrt deren Kennung selbst, in " "ext_id_bundestagsverwaltung und in mdb_zu_aw. NAMENSABGLEICH " "dagegen zum DIP: Dessen Personentabelle fuehrt nur die eigene " "person_id und keine Kennung der Bundestagsverwaltung " "(geprueft 28.09.2026 an parlamentsarbeit.dip_person). Die " "Personenbruecke entsteht deshalb ueber den Namen: Vor- und " "Nachname muessen beide als Zeichenkette im DIP-Titel stehen " "-- keine Aehnlichkeitssuche, kein Abstandsmass. Zusammengelegt " "wird nur, wo der normalisierte Name auf BEIDEN Seiten genau " "einmal vorkommt. Die Nummer wird einmal vergeben und bei " "spaeteren Laeufen uebernommen, nicht neu berechnet.",
        "limitierungen": "Die Nummer ist keine amtliche Kennung. Ein Teil der Personen ist bei " "abgeordnetenwatch nicht gefuehrt und kann eine Kennung der " "Bundestagsverwaltung nie erhalten, da diese an ein Mandat gebunden " "ist. Einige Faelle bleiben offen: Kennungen, die ueber den Namen " "zusammenpassen wuerden, wo der Name aber auf mehrere Menschen zeigt " "-- sie bleiben getrennte Knoten, statt verschiedene Menschen zu " "verschmelzen. Biographische Angaben liegen nur fuer die Gewaehlten " "vor; die uebrigen tragen ausser Namen und Kennung wenig bis nichts.",
        "lizenz":       "CC0-1.0",
    },


    {
        "lieferung_id": "person_rolle_erschlossen",
        "bezeichnung":  "Rollen und Aemter, wie die Protokollkoepfe sie bei einer sprechenden " "Person nennen: 5.369 Zeilen, darunter Parlamentarische " "Staatssekretaerinnen, Ministerinnen und Mitglieder des Bundesrates. " "Erschlossen wird aus dem Wortlaut des Protokollkopfes: die gelieferte " "Bezeichnung wird normalisiert und auf eine kanonische Rolle " "abgebildet, weil dieselbe Funktion in verschiedenen Schreibweisen " "erscheint",
        "herausgeber":  "eigene Erschliessung",
        "zitat":        "Deutscher Bundestag, Plenarprotokolle - Rollenangaben " "der Redner ausgewertet",
        "art":          "abgeleitet",
        "basis":        ["cpp_bt_fobbe"],
        "uebernahme_verfahren": "Rollenbezeichnung aus dem Protokollkopf, " "normalisiert ueber eine eigene Zuordnungstabelle",
        "limitierungen": "OHNE DATUM: Das Protokoll nennt die Rolle zur Sitzung, " "nicht deren Beginn und Ende. Ein Teil der Zeilen " "doppelt ausserdem Angaben, die amtlich vorliegen - die " "2.181 Zeilen der Art mandatsart sind zum Mandat " "redundant, und die Regierungsaemter stehen in " "bt_mdb_stammdaten mit Datum",
    },


    {
        "lieferung_id": "top_deskriptor_zuordnung",
        "bezeichnung":  "Deskriptoren je Tagesordnungspunkt, uebernommen aus der " "Drucksache der dort verhandelten Vorlage. 201.881 " "Zuordnungen.",
        "herausgeber":  "eigene Zuordnung",
        "zitat":        "Deutscher Bundestag, DIP - Deskriptoren der Vorlage dem " "Tagesordnungspunkt zugeordnet",
        "art":          "abgeleitet",
        "basis":        ["dip_dokumente", "dip_plenarprotokolle"],
        "uebernahme_verfahren": "Ueber die Drucksache des Punktes zum Vorgang und " "dessen Deskriptoren",
        "limitierungen": "Beschreibt die VORLAGE, nicht den Verlauf der Debatte. " "Ein Punkt kann bei verbundener Beratung mehrere Vorlagen " "zusammenfassen und traegt dann deren Deskriptoren " "nebeneinander",
    },
    {
        "lieferung_id": "top_sachgebiet_zuordnung",
        "bezeichnung":  "Sachgebiet je Tagesordnungspunkt, uebernommen aus dem " "Vorgang der verhandelten Vorlage. 17.577 Zuordnungen an " "5.634 Punkten -- die Quelle fuehrt 45.074 Zeilen, weil " "dieselbe Kombination einmal je Vorgang wiederholt wird. Das " "Sachgebiet ist die grobe Einordnung des Herausgebers mit " "achtundzwanzig Werten und haengt dort am Vorgang, nicht " "an der Rede und nicht an der Aktivitaet.",
        "herausgeber":  "eigene Zuordnung",
        "zitat":        "Deutscher Bundestag, DIP - Sachgebiete der Vorlage dem " "Tagesordnungspunkt zugeordnet",
        "art":          "abgeleitet",
        "basis":        ["dip_dokumente", "dip_plenarprotokolle"],
        "uebernahme_verfahren": "Ueber die Drucksache des Punktes zum Vorgang und " "dessen Sachgebiet",
        "limitierungen": "Sachgebiet der Debatte, nicht der einzelnen Rede. Bei " "verbundener Beratung traegt ein Punkt mehrere - 2.221 " "Punkte haben zwei, 536 mehr als sechs",
    },
    {
        "lieferung_id": "gemeinde_gerda_zuordnung",
        "bezeichnung":  "Ueberleitung der Gemeindeschluessel aus den GERDA-Wahlergebnissen " "auf die Gebietsstaende dieses Bestands, je GERDA-Fassung eine " "Zuordnung. In 97.964 von 99.507 Zeilen sind die Schluessel gleich; " "1.472 Zeilen betreffen Sammelposten ohne Gebiet, 51 gehobene und " "20 aufgeteilte Schluessel.",
        "herausgeber":  "eigene Ableitung",
        "zitat":        GERDA_ZITAT + " (Gemeindeschluessel), zugeordnet",
        "art":          "abgeleitet",
        "basis":        ["gerda_federal_muni_unharm",
                         "gerda_federal_muni_harm_21", "bkg_vg250"],
        "uebernahme_verfahren": V_SQL,
        "limitierungen": "Nur ein Teil der Zuordnungen beruht auf Schluesselgleichheit; die " "uebrigen betreffen Sammelposten ohne Gebiet sowie gehobene und " "aufgeteilte Schluessel. Wie eine Zeile zustande kam, weist eine " "eigene Spalte aus -- ohne sie ist die Zuordnung nicht zu beurteilen.",
    },


    {
        "lieferung_id": "bwl_wahlbezirke_2013",
        "bezeichnung":  "Wahlbezirksstatistik zur Bundestagswahl 2013: 87.927 Wahlbezirke in " "11.348 Gemeinden mit 1.812.629 Ergebniszeilen zu 35 Parteien. Feinste " "Ebene, auf der das amtliche Ergebnis vorliegt; jeder Bezirk traegt " "Erst- und Zweitstimmen, Wahlberechtigte, Waehlende und gueltige " "Stimmen. Getrennt ausgewiesen sind Urnenwahl (73.522 Bezirke), " "Briefwahl (14.349) und Sonderwahlbezirke (16)",
        "herausgeber":  f"{BWL} (im Auftrag der Herausgebergemeinschaft)",
        "zitat":        f"{BWL}: Wahlbezirksstatistik zur Bundestagswahl 2013",
        "lizenz":       "Nutzung mit Quellenangabe gestattet",
        "wahljahr":     2013,
        "art":          "amtlich",
        "limitierungen": "Die Bezirksart 8 ist in keiner Dokumentation erklaert: 40 Bezirke " "mit kuenstlichen Nummern, die Wahlberechtigte tragen. Wer auf die " "Urnenwahl filtert, verliert sie stillschweigend. Sonderwahlbezirke " "sind nur unvollstaendig als solche gekennzeichnet; die ausgewiesene " "Zahl ist eine Untergrenze. Ergebniszeilen mit null Stimmen fehlen, " "sodass nicht angetreten und null Stimmen nicht unterscheidbar sind. " "Die Parteinamen sind nicht harmonisiert -- anders als bei GERDA " "traegt dieselbe Partei je Land verschiedene Schreibweisen. Alle " "Briefwahlverbuende eines Kreises tragen dieselbe Gemeindeziffer und " "dieselbe Bezirksnummer; ohne das Originalfeld der Lieferung fielen " "Bezirke zusammen. Ein Gemeindename steht nicht in der Datei.",
        "uebernahme_verfahren": V_PYCSV,
        "eingriffe":    "E3, E4, E5 in: Gemeindeschluessel, die am Wahltag und " "in der Ergebnisdatei auseinanderfallen",
    },
    {
        "lieferung_id": "bwl_wahlbezirke_2017",
        "bezeichnung":  "Wahlbezirksstatistik zur Bundestagswahl 2017: 88.510 Wahlbezirke in " "11.769 Gemeinden mit 1.871.712 Ergebniszeilen zu 44 Parteien. Feinste " "Ebene, auf der das amtliche Ergebnis vorliegt; jeder Bezirk traegt " "Erst- und Zweitstimmen, Wahlberechtigte, Waehlende und gueltige " "Stimmen. Getrennt ausgewiesen sind Urnenwahl (71.865 Bezirke), " "Briefwahl (16.626) und Sonderwahlbezirke (12)",
        "herausgeber":  f"{BWL} (im Auftrag der Herausgebergemeinschaft)",
        "zitat":        f"{BWL}: Wahlbezirksstatistik zur Bundestagswahl 2017",
        "lizenz":       "Nutzung mit Quellenangabe gestattet",
        "wahljahr":     2017,
        "art":          "amtlich",
        "limitierungen": "Die Bezirksart 8 ist in keiner Dokumentation erklaert: 7 Bezirke, " "die Wahlberechtigte tragen. Sonderwahlbezirke sind nur " "unvollstaendig gekennzeichnet, die ausgewiesene Zahl ist eine " "Untergrenze. Ergebniszeilen mit null Stimmen fehlen. Die Parteinamen " "sind nicht harmonisiert. Bezirksnummern kollidieren nach dem " "Systematisieren in drei Gemeinden; nur das Originalfeld der " "Lieferung trennt sie. Nicht angetreten steht als Gedankenstrich und " "nicht als Leerfeld. Zwischen den Parteispalten steht ein Textfeld, " "dessen Werte wie Stimmenzahlen aussehen. Die Datei ist " "cp1252-kodiert, nicht UTF-8.",
        "uebernahme_verfahren": V_PYCSV,
        "eingriffe":    "E3, E4, E5 in",
    },
    {
        "lieferung_id": "bwl_wahlbezirke_2021",
        "bezeichnung":  "Wahlbezirksstatistik zur Bundestagswahl 2021: 94.668 Wahlbezirke in " "11.281 Gemeinden mit 2.333.180 Ergebniszeilen zu 48 Parteien. Feinste " "Ebene, auf der das amtliche Ergebnis vorliegt; jeder Bezirk traegt " "Erst- und Zweitstimmen, Wahlberechtigte, Waehlende und gueltige " "Stimmen. Getrennt ausgewiesen sind Urnenwahl (67.013 Bezirke), " "Briefwahl (27.647) und Sonderwahlbezirke (2)",
        "herausgeber":  f"{BWL} (im Auftrag der Herausgebergemeinschaft)",
        "zitat":        f"{BWL}: Wahlbezirksstatistik zur Bundestagswahl 2021",
        "lizenz":       "Nutzung mit Quellenangabe gestattet",
        "wahljahr":     2021,
        "art":          "amtlich",
        "limitierungen": "Die Datei ist die Fassung nach der Berliner Wiederholungswahl vom " "11.02.2024: Die Berliner Bezirke tragen nicht den Wahltag 2021, " "sodass Berlin in jeder Gegenueberstellung gesondert auszuweisen ist. " "Zwoelf Gemeinden des Ahrtals stehen nach der Flut als eine Einheit; " "ihr Ergebnis ist auf die zwoelf nicht rueckfuehrbar. Langelsheim " "fuehrt den Schluessel einer Fusion, die erst fuenf Wochen nach dem " "Wahltag wirksam wurde -- ein Ergebnis fuer vier Gebiete, nicht " "rueckrechenbar. Die Bezirksart 8 ist in keiner Dokumentation " "erklaert. Bezirksnummern sind nur je Bezirksart eindeutig. " "Aufgenommene Gemeinden haben keine eigene Zeile, weil ihre " "Wahlbezirke mit denen einer Nachbargemeinde zusammengelegt wurden.",
        "uebernahme_verfahren": V_PYCSV,
        "eingriffe":    "E3, E4, E5 in",
    },


    {
        "lieferung_id": "bwl_wahlkreisgeometrie",
        "bezeichnung":  "Geometrie der Bundestagswahlkreise 2013, 2017 und 2021, je 299 " "Wahlkreise mit WKR_NR, WKR_NAME, LAND_NR und LAND_NAME",
        "herausgeber":  "Bundeswahlleiter / Statistisches Bundesamt",
        "zitat":        "Bundeswahlleiter / Statistisches Bundesamt: Geometrie der " "Wahlkreise zur Bundestagswahl",
        "datei":        "je Wahljahr ein Shapefile",
        "lizenz":       "keine Angabe; Copyright-Vermerk des Herausgebers verpflichtend",
        "art":          "amtlich",
        "uebernahme_verfahren": V_SHP,
        "limitierungen": "Verschiedene Generalisierung je Jahrgang: 2013 VG1000 " "(1:1.000.000), 2017 und 2021 VG250 (1:250.000). Eine " "ungeneralisierte Fassung existiert nicht - die VG-Datensaetze " "sind bereits generalisierte Produkte. 2013 wurde vom Herausgeber " "per NTv2-Gitter (BeTA2007) aus dem Potsdam-Datum ueberfuehrt, " "laut Lineage in der .shp.xml",
    },


    *[{
        "lieferung_id": f"bwl_strukturdaten_{jahr}",
        "bezeichnung":  f"Strukturdaten der Wahlkreise zur Bundestagswahl "
                        f"{jahr}, 299 Zeilen je Wahlkreis",
        "herausgeber":  BWL,
        "zitat":        f"{BWL}: Strukturdaten fuer die Wahlkreise zur "
                        f"Bundestagswahl {jahr}, Open Data",
        "datei":        datei,
        "lizenz":       "keine Angabe",
        "wahljahr":     jahr,
        "art":          "amtlich",
        "uebernahme_verfahren": V_PYCSV,
        "limitierungen": "Nur fuenf Merkmale sind unterhalb der " "Gemeindeebene gerechnet: Bevoelkerung insgesamt, " "Bevoelkerung Deutsche, Bevoelkerungsdichte, " "Flaeche und Auslaenderanteil. Nachgewiesen ueber " "die 18 Gemeinden, die auf mehrere Wahlkreise " "fallen: nur diese fuenf variieren dort zwischen " "den Wahlkreisen. Alle uebrigen Merkmale sind " "nicht feiner als die Gemeinde, sodass die " "Wahlkreise, die ganz in einer geteilten Stadt " "liegen, den Wert der ganzen Stadt tragen -- " "Berlins zwoelf Wahlkreise fuehren dasselbe " "Einkommen. Welche Merkmale betroffen sind, steht " "je Merkmal in strukturdaten.wk_indikator." "aufloesung. Die Bezugsgroesse der " "Arbeitslosenquote -- alle zivilen oder nur die " "abhaengigen Erwerbspersonen -- nennt keine der " "drei Dateien und ist aus dem Bestand nicht zu " "entscheiden",
    } for jahr, datei in ((2013, "btw2013_strukturdaten.csv"),
                          (2017, "btw2017_strukturdaten.csv"),
                          (2021, "btw21_strukturdaten.csv"))],

    {
        "lieferung_id": "wahlkreisebene_amtlich",
        "bezeichnung":  "Wahlergebnisse je Wahlkreis, aus den Wahlbezirken aggregiert. " "Erst- und Zweitstimmen je Partei sowie Wahlberechtigte, " "Waehlende und gueltige Stimmen.",
        "herausgeber":  "eigene Ableitung",
        "zitat":        f"{BWL}: Wahlbezirksstatistik der Bundestagswahlen 2013, 2017 und 2021, " "aggregiert",
        "lizenz":       "dl-de/by-2-0",
        "art":          "abgeleitet",
        "basis":        ["bwl_wahlbezirke_2013", "bwl_wahlbezirke_2017",
                         "bwl_wahlbezirke_2021"],
        "uebernahme_verfahren": V_SQL,
        "limitierungen": "Jeder Wahlbezirk traegt seine Wahlkreisnummer selbst, die " "Aggregation ist deshalb exakt und braucht keine " "Zuordnungstabelle. Die Kennzahlen stehen je Stimmart getrennt, " "auch wo sie gleich sind - wer ueber beide summiert, zaehlt " "doppelt",
    },


    {
        "lieferung_id": "bkg_vg250",
        "bezeichnung":  "Verwaltungsgebiete 1:250.000: Flaechengeometrien der Gemeinden, Kreise " "und Laender, je Jahresstand zum 31.12. von 2010 bis 2021. Grundlage " "aller Flaechen im Bestand -- Wahlkreise, Kreisteile und " "Auszaehleinheiten sind daraus zusammengesetzt",
        "herausgeber":  "Bundesamt fuer Kartographie und Geodaesie",
        "zitat":        "(c) GeoBasis-DE / BKG (Daten veraendert) - Verwaltungsgebiete 1:250 000",
        "lizenz":       "dl-de/by-2-0",
        "art":          "amtlich",
        "limitierungen": "Generalisiertes Produkt im Massstab 1:250.000: Verschnitte zwischen " "Jahrgaengen erzeugen Schein-Schnittflaechen entlang unveraenderter " "Grenzen und brauchen eine Mindestflaechen-Schwelle. Die Flaeche " "schwankt zwischen den Jahrgaengen, ohne dass sich ein Gebiet " "geaendert haette -- VG250 wird neu vermessen und generalisiert; " "Schleswig-Holstein schwankt ueber zwoelf Jahrgaenge um 105 km2, das " "ist die Wattmodellierung. Fuer Aussagen ueber Gebietsaenderungen " "taugen Flaechen deshalb nicht. Die Einwohnerzahl ist nur fuer 2010 " "und 2011 belegt, danach NULL. Der Stand beschreibt das Jahresende; " "ein Stichtag mitten im Jahr ist aus zwei Jahrgaengen " "zusammenzustellen. Das Attributschema wechselt dreimal. Berlin und " "Hamburg sind je ein Kreis, waehrend die Wahlbezirksstatistik sie auf " "Stadtbezirke schluesselt",
        "uebernahme_verfahren": V_SHP,
    },
    {


        "lieferung_id": "bkg_gn250",
        "bezeichnung":  "Geographische Namen 1:250.000 - benannte Oertlichkeiten " "mit Punktkoordinate und Objektart",
        "herausgeber":  "Bundesamt fuer Kartographie und Geodaesie",
        "zitat":        "(c) BKG 2023 dl-de/by-2-0 - Geographische Namen 1:250 000 (GN250), " "Datenquellen: https://sgx.geodatenzentrum.de/web_public/gdz/" "datenquellen/datenquellen_gn250.pdf",
        "datei":        "GN250_p.shp",
        "lizenz":       "dl-de/by-2-0",
        "art":          "amtlich",
        "limitierungen": "Kein einheitlicher Gebietsstand: das Attribut datum nennt 59 " "Bearbeitungstage zwischen dem 10.01.2018 und dem 13.11.2025, die " "Produktbeilage pauschal den 31.12.2023. Das Datum ist der Stand der " "Fortschreibung beim Herausgeber und kein Zeitpunkt des Objekts -- " "ein Ortsteil, dessen Zeile 2018 geaendert wurde, besteht seit " "Jahrhunderten. Die zweite Schicht GN250_b ist kein Umriss, sondern " "das umschliessende Rechteck; 89.712 davon sind eine Standardkachel " "von 1 x 1 km um ein punktfoermiges Objekt. Je Objekt steht ein " "Punkt, auch fuer Fluesse, Waelder und Landschaften. ags und ars " "stehen im Gebietsstand der Lieferung, nicht in dem der Wahl. Zittel, " "Nyhuis und Baumann (2019) benutzen dieselbe Quelle in einer anderen " "Produktversion",
        "uebernahme_verfahren": V_SHP,
    },


    {


        "lieferung_id": "bbsr_ags_crosswalk",
        "bezeichnung":  "BBSR-Umsteigeschluessel Gemeinden, Jahrgaenge 1990-2020 auf " "Gebietsstand 2021",
        "herausgeber":  "BBSR, verteilt ueber GERDA " "(Heddesheimer u.a. 2025, doi:10.1038/s41597-025-04811-5)",
        "urheber":      BBSR,
        "zitat":        BBSR_ZITAT + ", verteilt ueber " + GERDA_ZITAT,
        "datei":        "ags_crosswalk.csv",
        "gebietsstand": "2021-12-31",
        "lizenz":       "CC-BY-4.0",
        "art":          "amtlich",
        "limitierungen": "Nur absolute Groessen lassen sich mit diesen Gewichten umrechnen -- " "Einwohner, Beschaeftigte, Stimmen. Quoten und Durchschnitte muessen " "in Zaehler und Nenner zerlegt, beide umgerechnet und erst danach " "geteilt werden. Die Richtung ist einseitig: alles zeigt auf 2021, " "nie zurueck. 35 Schluessel summieren ihr Bevoelkerungsgewicht nicht " "auf 1, sondern auf 2 bis 11 -- bayerische Sammeleintraege fuer " "gemeindefreie Gebiete; das Flaechengewicht ist dort korrekt. 20 " "Schluessel bleiben ohne Eintrag, unbewohnte Forste in Bayern, die " "zwischen zwei Jahresstaenden aus dem Gebietsstand verschwinden, ohne " "dass eine Quelle sagt wohin. Ziel ist der 31.12.2021 und nicht der " "Wahltag: dazwischen liegen 15 Gemeindezeilen",
        "uebernahme_verfahren": V_PYCSV,
    },
    {
        "lieferung_id": "bbsr_cty_crosswalk",
        "bezeichnung":  "BBSR-Umsteigeschluessel Kreise auf Gebietsstand 2021",
        "herausgeber":  "BBSR, verteilt ueber GERDA " "(Heddesheimer u.a. 2025, doi:10.1038/s41597-025-04811-5)",
        "urheber":      BBSR,
        "zitat":        BBSR_ZITAT + ", verteilt ueber " + GERDA_ZITAT,
        "datei":        "cty_crosswalk.csv",
        "gebietsstand": "2021-12-31",
        "lizenz":       "CC-BY-4.0",
        "art":          "amtlich",
        "limitierungen": "Nur absolute Groessen lassen sich mit den Gewichten umrechnen, " "Quoten muessen in Zaehler und Nenner zerlegt werden. Auf Kreisebene " "aendert sich zwischen 2013 und 2021 wenig: zwei Fusionen " "(Goettingen/Osterode 2016, Eisenach 2021) und neun reine " "Namensaenderungen. Weil die letzte Aenderung vor dem Wahltag 2021 " "wirksam wurde, sind Wahltagsstand und Jahresendstand auf dieser " "Ebene identisch. Der Jahresstand 2010 fuehrt 412 Kreise, weil die " "mecklenburgische Kreisgebietsreform erst zum 04.09.2011 wirksam " "wurde. Die Wahlbezirksstatistik fuehrt eine eigene Kreisspalte, die " "nicht in jedem Fall dem amtlichen Kreisschluessel entspricht",
        "uebernahme_verfahren": V_PYCSV,
    },


    {
        "lieferung_id": "bbsr_inkar_2024",
        "bezeichnung":  "INKAR - Indikatoren und Karten zur Raum- und Stadtentwicklung, " "Ausgabe 03/2024. Gesamtdatei je Ausgabe als CSV, Jahrgaenge ab 1995.",
        "herausgeber":  BBSR,
        "zitat":        "Laufende Raumbeobachtung des BBSR - INKAR, Ausgabe 03/2024. " "Hrsg.: Bundesinstitut fuer Bau-, Stadt- und Raumforschung (BBSR), " "Bonn (https://www.inkar.de/)",
        "datei":        "INKAR-Gesamtdatei, CSV je Ausgabe",
        "gebietsstand": "2022-12-31",
        "lizenz":       "dl-de/by-2-0",
        "art":          "amtlich",
        "uebernahme_verfahren": V_PYCSV,
        "eingriffe":    "I1 in: sechs Gemeinden bekommen durchgehend keinen Wert",
        "limitierungen": "Die Gebietsstaende dieses Bestands reichen bis zum 31.12.2021, die " "Werte stehen auf dem Stand 31.12.2022 -- fuer Schluessel, die sich " "in diesem Jahr geaendert haben, gibt es keine Bezugsgeometrie. Der " "Gebietsstand des Berichtsjahres ist nicht mitgeliefert, sodass ein " "Wert von 1995 nicht auf das Gebiet von 1995 zurueckzufuehren ist.",
    },


    {
        "lieferung_id": "bbsr_wachsen_schrumpfen_2021",
        "bezeichnung":  "Wachsende und schrumpfende Staedte und Gemeinden, Zeitintervall " "2016-2021. Einstufung in fuenf Entwicklungsklassen aus sechs " "Indikatoren (Bevoelkerungsentwicklung, Wanderungssaldo, " "Erwerbsfaehige, Beschaeftigte am Arbeitsort, Arbeitslosenquote, " "Gewerbesteuergrundaufkommen).",
        "herausgeber":  BBSR,
        "zitat":        "Bundesinstitut fuer Bau-, Stadt- und Raumforschung: Laufende " "Raumbeobachtung des BBSR - Wachsende und schrumpfende Staedte " "und Gemeinden, Bonn",
        "datei":        "zeitlicher-verlauf-ws-1924.xlsx, Spalte Zeitintervall 2016-2021",
        "gebietsstand": "2021-12-31",


        "lizenz":       "keine Angabe",
        "art":          "amtlich",
        "uebernahme_verfahren": V_PYCSV,
        "limitierungen": "Der Index ist je Einheitsgemeinde und Gemeindeverband gerechnet, " "nicht je Gemeinde: Der Herausgeber schreibt den Wert des Verbands " "auf dessen Gemeinden durch, sodass mehrere Gemeinden denselben Wert " "tragen und eine Auswertung je Gemeinde weniger Werte vor sich hat, " "als sie Gemeinden zaehlt. Gewichtung und Klassengrenzen setzt der " "Herausgeber; die drei demografischen Indikatoren zaehlen doppelt. " "Ein Teil der Gemeinden traegt keinen Wert -- teils, weil fuer ihre " "Einheit keiner geliefert ist, teils weil ihr Verband in der Rechnung " "fehlt.",
    },
    {
        "lieferung_id": "destatis_regionaldatenbank",
        "bezeichnung":  "Regionaldatenbank Deutschland: Strukturdaten im Gebietsstand des " "jeweiligen Berichtsjahres, abgerufen ueber die GENESIS-Schnittstelle",
        "herausgeber":  "Statistische Aemter des Bundes und der Laender",
        "zitat":        "Statistische Aemter des Bundes und der Laender: Regionaldatenbank " "Deutschland (regionalstatistik.de)",
        "datei":        "Abruf ueber pystatis / GENESIS, je (Tabelle, Jahr)",
        "lizenz":       "dl-de/by-2-0",
        "art":          "amtlich",
        "uebernahme_verfahren": "Abruf ueber pystatis, Werte je Zeile mit Merkmalen als JSONB",
        "eingriffe":    "R1 in: 57 Gemeinden bekommen den Wert des Vorjahres",
    },
    {
        "lieferung_id": "bbsr_raumgliederung",
        "bezeichnung":  "Raumgliederungssystem des BBSR: welche Gemeinde und welcher Kreis in " "welcher Raumabgrenzung liegt. Bezogen ist der Gebietsstand " "31.12.2021; der Herausgeber bietet je Gebietsstand eine XLSX",
        "herausgeber":  BBSR,
        "zitat":        BBSR + ": Raumgliederungssystem des BBSR",
        "datei":        "raumgliederungen-referenzen-2021.xlsx",
        "lizenz":       "dl-de/by-2-0",


        "gebietsstand": "2021-12-31",
        "art":          "amtlich",
        "uebernahme_verfahren": V_XLSX,
    },
    {
        "lieferung_id": "destatis_gebietsaenderungen",
        "bezeichnung":  "Gebietsaenderungen der Gemeinden aus dem Gemeindeverzeichnis, " "eine XLSX je Jahrgang",
        "herausgeber":  "Statistisches Bundesamt",
        "zitat":        "Statistisches Bundesamt: Gebietsaenderungen aus dem " "Gemeindeverzeichnis (GV-ISys)",
        "datei":        "je Jahrgang eine XLSX",
        "lizenz":       "Nutzung mit Quellennachweis gestattet",
        "art":          "amtlich",
        "uebernahme_verfahren": V_XLSX,
        "limitierungen": "Enthaelt ausschliesslich VERAENDERUNGEN: Aus dem Fehlen eines " "Eintrags folgt, dass die Gemeinde unveraendert fortbestand -- eine " "Bestandsliste ist es nicht. Eine vollstaendige Fortschreibung " "braucht zusaetzlich die Gebietsstaende.",
    },


    {
        "lieferung_id": "aw_api_v2",
        "bezeichnung":  "Abgeordnetenwatch API v2: Personen, Mandate und Kandidaturen, " "namentliche Abstimmungen, Nebentaetigkeiten, Ausschuesse, Wahlkreise " "und Landeslisten. Abgefragt fuer die sechs Wahlperioden der Wahlen " "und Legislaturen 2013, 2017 und 2021.",
        "herausgeber":  "abgeordnetenwatch.de",
        "zitat":        "abgeordnetenwatch.de: API v2, https://www.abgeordnetenwatch.de/api/v2",
        "datei":        "API v2, https://www.abgeordnetenwatch.de/api/v2",
        "lizenz":       "CC0-1.0",
        "art":          "zivilgesellschaftlich",
        "uebernahme_verfahren": V_API,
        "eingriffe":    "E1, E1b, E2, E6, E7, E8 in: Wahlkreisnummer und " "Mandatsart ergaenzt, falsche Referenzen und Kandidaturen " "richtiggestellt, Geburtsjahr aus den amtlichen Stammdaten",
        "limitierungen": "Fuer die Legislatur 2021-2025 fehlt der Wahlkreis bei jedem " "Direktgewaehlten der Nummern 1 bis 50 -- die Lieferung nennt kein " "Wahlkreisobjekt. Wahlkreis- und Listenobjekte sind " "periodenspezifisch, und Mandate verweisen teils auf die Objekte " "einer anderen Wahl. Die Wahlperiode steht nicht am Wahlkreisobjekt, " "sodass gleichnamige Wahlkreise verschiedener Wahlen nicht " "unterscheidbar sind. Vorzeitig Ausgeschiedene liefert die " "Schnittstelle nur mit current_on=all; ohne diesen Parameter fehlen " "sie. Der Beginn einer Nebentaetigkeit steht als Unix-Zeitstempel, " "nicht als Datum. Jeder Endpunkt filtert Perioden anders. Neun " "Personen tragen keine Kennung der Bundestagsverwaltung und sind " "deshalb nicht an die amtlichen Stammdaten anschliessbar. Nachruecker " "sind erst ab 2017 als solche markiert, und der Vorgaenger wird nie " "genannt.",
    },
    {
        "lieferung_id": "bt_mdb_stammdaten",
        "bezeichnung":  "Stammdaten der Abgeordneten aus dem XML-Verzeichnis der " "Bundestagsverwaltung. Die Datei reicht bis 1949 zurueck; uebernommen " "sind die 1.493 Personen der Wahlperioden 18 bis 20. Sie traegt die " "amtliche Wahlkreisnummer, die Mandatsart sowie Anfang und Ende jedes " "Mandats auf den Tag, dazu den biografischen Block: Geburtsdatum bei " "1.270 von 1.270 Gewaehlten, Geburtsort bei 1.269, Beruf bei 1.245",
        "herausgeber":  BT,
        "zitat":        f"{BT}: Stammdaten aller Abgeordneten seit 1949 (MDB_STAMMDATEN.XML)",
        "datei":        "MDB_STAMMDATEN.XML",
        "lizenz":       BT_LIZENZ,
        "art":          "amtlich",
        "uebernahme_verfahren": V_XML,
        "limitierungen": "Der biografische Block steht EINMAL JE PERSON, nicht je Wahlperiode: " "Beruf, Familienstand, Religion, Parteizugehoerigkeit und Kurzvita " "gelten fuer den Stand der letzten Fortschreibung. 650 der " "uebernommenen Abgeordneten sitzen in mehreren der Wahlperioden 18 " "bis 20 -- fuer sie ist nicht zu sagen, auf welche Periode die Angabe " "zutrifft, und die Lieferung nennt keinen Stand. Der Name ist dagegen " "datiert und wechselt belegt: eine eigene Tabelle fuehrt ihn mit " "Gueltigkeitsspanne. Die Kurzvita ist nur bei einem Bruchteil der " "Personen gefuellt. Die amtliche Wahlkreisnummer ist nur bei " "Direktgewaehlten vollstaendig; bei Listenmandaten bleibt sie leer, " "auch wo die Person in einem Wahlkreis angetreten ist. Die Mandatsart " "traegt den Wert Direktwahl, waehrend die zugehoerige DTD " "Direktmandat vorschreibt. Bei Nachrueckern koennen Wahlkreis und " "Landesliste aus verschiedenen Bundeslaendern stammen, weil die Zeile " "den Vorgaenger fortschreibt.",
    },
    {
        "lieferung_id": "bt_ausgeschiedene",
        "bezeichnung":  "Ausgeschiedene Abgeordnete und deren Nachfolger, je Wahlperiode eine " "Seite (18, 19, 20). Nennt Ausscheidedatum, Vorgaenger, Nachfolger und " "Eintrittsdatum, dazu Namensaenderungen waehrend des Mandats. Einzige " "Quelle fuer die Nachfolgebeziehung: abgeordnetenwatch markiert " "Nachruecker erst ab 2017 und nennt nie den Vorgaenger.",
        "herausgeber":  BT,
        "zitat":        f"{BT}: Ausgeschiedene Abgeordnete der Wahlperioden 18 bis 20",
        "datei":        "wp18.html, wp19.html, wp20.html - URL, Abrufdatum und SHA-256 je " "Seite in abruf.json",
        "lizenz":       BT_LIZENZ,
        "art":          "amtlich",
        "uebernahme_verfahren": V_HTML,
        "limitierungen": "Enthaelt KEINEN Personenschluessel: Die Quelle nennt Namen im " "Klartext, und die Kennungen in ihren Verweisen sind solche eines " "Redaktionssystems, die je Wahlperiode wechseln. In vier von 109 " "Uebergaengen wird kein Nachfolger benannt -- dreimal gibt die " "Landesliste niemanden mehr her, einmal entfiel das Mandat durch die " "Berliner Wiederholungswahl. Ein Ausscheiden vor Mandatsantritt ist " "aus der Struktur der Quelle nicht abbildbar.",
    },


    {
        "lieferung_id": "bt_namentliche_abstimmungen",
        "bezeichnung":  "Verzeichnis der namentlichen Abstimmungen, Wahlperioden 18 bis 20: " "642 Abstimmungen mit 443.382 Stimmen. Je Abstimmung ZWEI Dateien - " "eine XLSX mit dem Stimmverhalten aller Mitglieder und ein PDF, das im " "Kopf die Drucksachennummer, den vollen Vorlagentitel und das amtliche " "Ergebnis nennt. Beides steht in derselben Zeile der Trefferliste; die " "PDF-Adresse ist nicht aus der XLSX-Adresse ableitbar.",
        "herausgeber":  BT,
        "zitat":        f"{BT}: Namentliche Abstimmungen der Wahlperioden 18 bis 20",
        "datei":        "642 XLSX/XLS und 642 PDF - URL, Abrufdatum und SHA-256 je Datei in " "abruf.json",
        "lizenz":       nicht_angegeben("bundestag.de", "29.08.2026"),
        "art":          "amtlich",
        "uebernahme_verfahren": V_XLSX,
        "limitierungen": "Je Abstimmung liegen zwei getrennte Dateien vor, und die Adresse der " "einen ist aus der der anderen nicht ableitbar -- das amtliche " "Ergebnis und der Vorlagentitel stehen nur im PDF, das Stimmverhalten " "nur in der Tabelle.",
    },
    {
        "lieferung_id": "wikidata",
        "bezeichnung":  "Kennungen und Namensangaben der 1.271 Abgeordneten mit Mandat, ueber " "die von abgeordnetenwatch gelieferte Q-Nummer per SPARQL abgefragt. " "Sieben Kennungssysteme erreichen mindestens 90 Prozent der Personen " "und bekommen eine eigene Spalte: GND, VIAF, OpenSanctions, " "OpenParliamentTV, abgeordnetenwatch, Bundestagsbiografie und die " "offizielle Website. Die Zuordnung ist beidseitig geprueft -- Wikidata " "fuehrt selbst eine abgeordnetenwatch-Kennung, und sie stimmt bei allen " "1.271 Personen mit unserer ueberein. Zweite Verwendung sind die " "GEBURTSORTE: Wikidata verweist vom Menschen auf ein Ortsobjekt, dessen " "Koordinate den raeumlichen Anschluss gibt, ohne den amtlichen Ortstext " "geokodieren zu muessen. Der Name bleibt amtlich aus den Stammdaten, " "nur die Koordinate kommt von hier",
        "herausgeber":  "Wikidata / Wikimedia Foundation",
        "zitat":        "Wikidata, Wikimedia Foundation, abgefragt ueber den Wikidata Query " "Service",
        "datei":        "wikidata_kennungen_gewaehlte_JJJJMMTT_HHMMSS.json und " "wikidata_geburtsorte_JJJJMMTT_HHMMSS.json in " "01_fetch/wikidata/export, dazu das Eigenschafteninventar als CSV " "und korrekturen_geburtsort.csv mit drei nachgetragenen Ortsobjekten",
        "lizenz":       "CC0-1.0",
        "art":          "zivilgesellschaftlich",
        "basis":        ["aw_api_v2"],
        "uebernahme_verfahren": "SPARQL gegen den Wikidata Query Service, JSON in JSONB, " "danach SQL",
        "eingriffe":    "E9 in: drei Personen, deren Geburtsort in Wikidata keine " "Koordinate fuehrt, aus korrekturen_geburtsort.csv verortet",
        "limitierungen": "Kollaborative Quelle: Die Kennungen sind Zeiger auf andere Bestaende, " "keine Belege. " "Welche Eigenschaft eine Kennung und welche ein Konto ist, sagt " "Wikidata ueber sich selbst -- ueber P31, den Gegenstand P1629 und " "die Formatierungs-URL P1630. Danach fallen 340 Eigenschaften unter " "Kennung, 30 unter Konto, 7 unter Webadresse und 6 unter " "Namensvariante. Die Einordnung der Quelle wird nicht " "ueberschrieben, auch wo sie ueberrascht: Die ORCID-Kennung und der " "Wikimedia-Benutzername stehen danach als KONTO, obwohl beide keine " "Auftritte in sozialen Netzwerken sind. 194 der 383 Eigenschaften " "tragen keinen Gegenstand, sodass fuer sie keine Plattform gebildet " "werden kann",
    },


    {
        "lieferung_id": "dip_dokumente",
        "bezeichnung":  "Vollabzug der DIP-API fuer die Wahlperioden 18 bis 20: Drucksachen, " "Vorgaenge, Vorgangspositionen, Aktivitaeten und Personen als CSV. " "Traegt zu jedem Vorgang Sachgebiet (28 Begriffe), Deskriptoren, " "Vorgangstyp und Abstract. Ueber vorgangsposition.dokumentnummer " "haengt jede Drucksachennummer an ihren Vorgaengen - das ist der Weg " "von einer namentlichen Abstimmung zu ihrem Sachgebiet. Aus derselben " "Lieferung stammen die Ordnungsrufe (Vorgangstyp Geschaeftsordnung, " "Vorgangsposition Ordnungsruf).",
        "herausgeber":  DIP,
        "zitat":        f"{DIP}: Vollabzug der Wahlperioden 18 bis 20",
        "datei":        "01_fetch/dip/export/dokumente_JJJJMMTT_HHMMSS/ - je Entitaet und " "Wahlperiode eine CSV, Lauflog in vollabzug_lauf.log",
        "lizenz":       "frei nutzbar mit Quellenangabe (DIP-Nutzungsbedingungen)",
        "art":          "amtlich",
        "uebernahme_verfahren": V_API,
        "limitierungen": "Wahlperiode 18 fuehrt das DIP ohne Ordnungsrufe (laut " "Presserecherche gab es dort zwei, die im Protokolltext stehen)",
    },
    {
        "lieferung_id": "dip_plenarprotokolle",
        "bezeichnung":  "Annotierte Plenarprotokolle der Wahlperioden 18 bis 20 als XML. Im " "Graphen stehen nicht die Dokumente, sondern was aus ihnen gewonnen " "wird: 697 Sitzungen und 7.125 Tagesordnungspunkte. Die Protokolle " "liefern ausserdem zu jeder namentlichen Abstimmung die " "Drucksachennummer, den Vorlagentitel, das amtliche Ergebnis und die " "Namensliste je Stimme",
        "herausgeber":  DIP,
        "zitat":        f"{DIP}: Plenarprotokolle der Wahlperioden 18 bis 20",
        "datei":        "698 XML in Daten/Parlamentsarbeit/dip_plenarprotokolle_xml - URL, " "Abrufdatum und SHA-256 je Datei in abruf.json",
        "lizenz":       "amtliches Werk, gemeinfrei nach Paragraf 5 UrhG",
        "art":          "amtlich",
        "uebernahme_verfahren": V_XML,
        "eingriffe":    "P1 bis P4 in: Sprecherkennung ersetzt, ergaenzt oder " "eigens vergeben, Namen richtiggestellt",
        "limitierungen": "Sechs von 698 Protokollen tragen statt des Sitzungsdatums eine " "fehlerhafte Zeichenkette; der Fehler steckt im gelieferten XML. Die " "Anlage mit den entschuldigten Abgeordneten fehlt in 49 von 697 " "Sitzungen, darunter drei zu Beginn der Corona-Pandemie -- warum, " "geht aus den Daten nicht hervor. Acht Protokolle tragen keine oder " "eine leere Anlagenart, sodass Anlagen nur ueber die Ueberschrift " "greifbar sind.",
    },


    {


        "lieferung_id": "manifesto_mpds_2025a",
        "bezeichnung":  "Manifesto Project Dataset MPDS2025a, Programmpositionen von " "5.285 Wahlprogrammen aus 67 Laendern, 1920-2025",
        "herausgeber":  "WZB Berlin Social Science Center / IfDem Goettingen",
        "urheber":      "Lehmann et al.",
        "zitat":        "Lehmann et al. (2025): Manifesto Project Dataset MPDS2025a. WZB " "Berlin / IfDem Goettingen. doi:10.25522/manifesto.mpds.2025a",
        "datei":        "MPDataset_MPDS2025a.csv",
        "lizenz":       "keine Angabe; Freigabe beim Herausgeber einzuholen",
        "art":          "amtlich",
        "uebernahme_verfahren": V_PYCSV,
        "limitierungen": (
            "Gemessen wird BETONUNG, nicht Position: wieviel Text ein Programm " "einem Thema widmet. Eine massvolle und eine weitreichende " "Forderung zaehlen beide einen Satz. Nur etwa die Haelfte der " "Kategorien hat ein Gegenstueck, sodass sich bei den uebrigen ein " "niedriger Wert nicht deuten laesst - er kann Ablehnung oder " "Nichtbehandlung bedeuten. Welche Kategorien erhoben wurden, haengt " "an der Fassung des Codierhandbuchs: fuer deutsche Programme " "durchgehend 56 Hauptkategorien von 1990 bis 2013, ab 2017 " "zusaetzlich 32 Verfeinerungen. Fehlwert und Null sind deshalb zu " "unterscheiden. CDU und CSU treten seit 1949 mit EINEM gemeinsamen " "Programm an, das unter einer Kennung gefuehrt wird - wer Programme " "je Partei zaehlt, zaehlt es zweimal. Die 54 Zusatzkategorien fuer " "mittel- und osteuropaeische Staaten kommen in deutschen " "Programmen nicht vor "
        ),
    },
]


EIGENE_LIZENZ = "CC0-1.0"

for _eintrag in LIEFERUNGEN:
    if _eintrag.get("herausgeber", "").startswith("eigene"):
        _eintrag["lizenz"] = EIGENE_LIZENZ


BESCHREIBUNG = {

    "bkg_vg250":
        "Bildet die Gebietsstaende dreier Ebenen, je Stichtag und Schluessel " "einen Knoten: Gemeindestand, Kreisstand und Bundesland. An jedem " "haengen der amtliche Schluessel, der Name und der Gueltigkeitsbeginn, " "dazu die Flaeche als WKT-Geometrie in EPSG:25832. Der Gemeindestand " "traegt zusaetzlich den zwoelfstelligen Regionalschluessel, weil sich " "bei 1.218 von 1.230 Schluesselaenderungen allein dieser aendert. " "Einwohnerzahl und Flaechengroesse werden nicht als Merkmale des " "Gebiets gefuehrt, sondern als Beobachtungen mit dem Stichtag als " "Erhebungszeitpunkt. Aus derselben Lieferung stammen die " "Zugehoerigkeiten Gemeinde zu Kreis, Gemeinde zu Bundesland und Kreis " "zu Bundesland; sie folgen den ersten Stellen des Schluessels und " "stehen als eigene Knoten, damit eine Abfrage die Regel nicht kennen " "muss. Gefuehrt sind zwoelf Jahresstaende zum 31.12. von 2010 bis " "2021 und acht Stichtagsstaende bis zum Wahltag 2021.",

    "bwl_wahlkreisgeometrie":
        "Bildet die Wahlkreisstaende, je Wahl und Nummer einen Knoten, 299 " "mal drei. An jedem haengen Wahlkreisnummer und -name, die Kante auf " "die Wahl, fuer die der Zuschnitt gilt, und die Flaeche als " "WKT-Geometrie in EPSG:25832. Die Zugehoerigkeit zum Bundesland " "stammt aus derselben Lieferung: Sie steht als Attribut in der " "Shapefile-Tabelle und wird nicht aus der Geometrie erschlossen. " "Die Flaechengroesse wird als Beobachtung gefuehrt, nicht als " "Eigenschaft des Zuschnitts.",

    "bwl_wahlbezirke_2013":
        "Traegt die Zuordnung Gemeinde zu Wahlkreis am Wahltag. Jeder " "Wahlbezirk nennt Gemeinde UND " "Wahlkreis in derselben Quellzeile, im Stand des Wahltags: keine " "Umschluesselung, kein Stichtagsversatz, nichts abgeleitet " "(herkunft = 'bezirk'). Wo eine Gemeinde keinen eigenen Bezirk hat " "(Par. 68 Abs. 2 BWO), nennt die Datei die aufnehmende Gemeinde, " "deren Wahlkreis dann gilt (herkunft = 'aufnahme'). Verteilen sich " "die Bezirke einer Gemeinde auf mehrere Wahlkreise, ist die " "Zugehoerigkeit als anteilig gekennzeichnet. " "Speist ausserdem die Auszaehleinheiten - die kleinste Einheit, fuer " "die ein Ergebnis vollstaendig vorliegt - und deren Zugehoerigkeiten " "zu den Gemeindestaenden. An der Auszaehleinheit haengen ihre " "Bezeichnung und die Flaeche als Vereinigung der Mitglieder. Die " "Wahlergebnisse selbst gehoeren zu Modul 05 und sind hier noch nicht " "beschrieben.",

    "bwl_wahlbezirke_2017":
        "Wie bwl_wahlbezirke_2013, fuer die Wahl 2017.",

    "bwl_wahlbezirke_2021":
        "Wie bwl_wahlbezirke_2013, fuer die Wahl 2021.",

    "grossstadt_wkr_2013":
        "Bildet die Wahlkreisanteile geteilter Grossstaedte als " "Auszaehleinheiten: Wo eine Gemeinde ueber mehrere Wahlkreise reicht, " "entsteht je Anteil ein Knoten mit eigener Flaeche und der " "Zugehoerigkeit zur Gemeinde. Ohne sie liesse sich das Ergebnis einer " "geteilten Stadt keinem Wahlkreis zuordnen.",

    "grossstadt_wkr_2017":
        "Wie grossstadt_wkr_2013, fuer die Wahl 2017.",

    "grossstadt_wkr_2021":
        "Wie grossstadt_wkr_2013, fuer die Wahl 2021.",

    "gv100ad_2013":
        "Nennt den Wahlkreis der 226 gemeindefreien Gebiete des Wahltags " "2013 -- Forst, See, Truppenuebungsplatz. Sie haben keinen " "Wahlbezirk, weil dort niemand waehlt, und werden deshalb von keiner " "anderen Quelle einem Wahlkreis zugeordnet; im Bestand sind sie an " "herkunft = 'zuordnungsliste' erkennbar. " "Der Gebietsstand des Verzeichnisses ist der 31.12.2013 und liegt " "damit hundert Tage hinter der Wahl. " "Die Quelle nennt den Wahlkreis als Spanne von-bis; wo daraus kein " "eindeutiger Wahlkreis folgt, weist die Herkunft es je Zeile aus. " "Liefert ausserdem die Gemeindemenge je Wahlkreis 2013, aus der die " "Wahlkreisuebergaenge gebildet werden.",

    "bwl_zuordnung_2017":
        "Nennt den Wahlkreis der 214 gemeindefreien Gebiete des Wahltags " "2017, die keinen Wahlbezirk haben und deshalb von keiner anderen " "Quelle einem Wahlkreis zugeordnet werden; erkennbar an " "herkunft = 'zuordnungsliste'. " "Ihr Gebietsstand ist der 28.02.2017 und liegt sieben Monate vor dem " "Wahltag; je Zeile ist in raum.gebietsuebergang geprueft, ob sich " "der Schluessel bis zum Wahltag geaendert hat -- wenn ja, steht die " "Zeile als unsicher.",

    "bwl_zuordnung_2021":
        "Wie bwl_zuordnung_2017, fuer die Wahl 2021: 207 gemeindefreie " "Gebiete. Der Stichtagsversatz ist hier am groessten -- der " "Gebietsstand vom 15.04.2020 liegt siebzehn Monate vor dem " "Wahltag.",

    "destatis_gebietsaenderungen":
        "Bildet die Filiationen zwischen Gemeinde- und Kreisstaenden: je " "Uebergang ein Knoten mit Vorgaenger, Nachfolger, der Art der " "Filiation und dem Grund - ob sich Bezeichnung, Schluessel oder " "Gebiet geaendert hat. Das Wirksamkeitsdatum steht an der Beziehung " "und nicht an den Staenden, weil es genauer ist als deren " "Gueltigkeitsgrenzen. Welche Flaeche gewechselt hat, benennt die " "Quelle nicht; die Kante auf die betroffenen Einheiten bleibt hier " "daher leer.",

    "bbsr_ags_crosswalk":
        "Bildet die Umrechnungen zwischen Gemeindestaenden: je Paar aus " "abgebendem und aufnehmendem Stand ein Knoten mit zwei Gewichten - " "dem Anteil der Bevoelkerung und dem der Flaeche. Beide werden " "gefuehrt und nicht zu einem zusammengefasst, weil sie bei " "Bevoelkerungsgroessen zu verschiedenen Ergebnissen fuehren. Ziel ist " "durchgehend der Stand 31.12.2021. Nur absolute Groessen lassen sich " "damit umrechnen; Quoten sind zuvor in Zaehler und Nenner zu zerlegen.",

    "bbsr_cty_crosswalk":
        "Wie bbsr_ags_crosswalk, auf Kreisebene.",

    "kreis_wahlkreis_zuschnitt":
        "Bildet die Kreis-Wahlkreis-Zuschnitte: je Kreis und Wahlkreis, die " "einander ueberlappen, ein Knoten mit der verschnittenen Flaeche. " "Noetig, weil Kreise und Wahlkreise einander nicht enthalten - 255 " "der 400 Kreise reichen 2021 ueber mehr als einen Wahlkreis. Die " "Flaechengroesse wird als Beobachtung gefuehrt.",

    "hexkarte_wahlkreis":
        "Bildet je Wahlkreisstand eine zweite Geometrie: ein gleich grosses " "Sechseck, das die Nachbarschaftsbeziehungen der tatsaechlichen " "Flaeche bewahrt. Sie haengt ueber die allgemeine Geometriekante am " "Wahlkreisstand und ausdruecklich NICHT ueber die massgebliche, damit " "eine raeumliche Abfrage sie nicht versehentlich mitnimmt. Die " "Unterscheidung liegt zusaetzlich am Knoten selbst, der eine eigene " "Klasse traegt. Dient allein der Darstellung.",

    "wahlkreisuebergang":
        "Bildet die Filiationen zwischen Wahlkreisstaenden zweier " "aufeinanderfolgender Wahlen: je Uebergang ein Knoten mit Vorgaenger, " "Nachfolger und der Art der Kontinuitaet. Anders als bei den " "Gemeinden traegt die Beziehung hier auch die betroffenen Einheiten - " "die Gemeindestaende, die den Wahlkreis gewechselt haben, weil die " "Bildungsregel sie einzeln ausweist.",

    "einheitsuebergang":
        "Bildet die Filiationen zwischen den Auszaehleinheiten zweier " "aufeinanderfolgender Wahlen: je Uebergang ein Knoten mit Vorgaenger " "und Nachfolger. Wo eine Einheit sich aufloest oder neu entsteht, ist " "nur eine der beiden Seiten gesetzt.",

    "nachbarschaft_wahlkreis":
        "Bildet die Nachbarschaften zwischen Wahlkreisstaenden derselben " "Wahl: je Paar aneinandergrenzender Zuschnitte ein Knoten mit der " "Laenge der gemeinsamen Grenze in Metern. Die beiden Enden sind " "gleichwertig, da Nachbarschaft symmetrisch ist. Daneben steht " "dieselbe Aussage als einfache Kante in beiden Richtungen, damit eine " "Abfrage nach blosser Angrenzung nicht ueber den Knoten laufen muss.",

    "gemeinde_gerda_zuordnung":
        "Bildet die Zugehoerigkeiten zwischen den Gemeindeschluesseln der " "GERDA-Wahlergebnisse und den Gemeindestaenden dieses Bestands, je " "GERDA-Fassung eine eigene Zuordnung. An jeder steht, wie sie " "zustande kam: durch Schluesselgleichheit, als Sammelposten ohne " "Gebiet, gehoben oder aufgeteilt. Ohne diese Knoten haetten die " "GERDA-Ergebnisse keinen Raumbezug.",
}

for _eintrag in LIEFERUNGEN:
    _text = BESCHREIBUNG.get(_eintrag["lieferung_id"])
    if _text:
        _eintrag["beschreibung"] = _text


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("datenlieferung")


SPALTEN = [
    "lieferung_id", "bezeichnung", "herausgeber", "datei", "gebietsstand",
    "lizenz", "wahljahr", "art", "basis",
    "zitat", "beschreibung", "urheber", "stand_quelle", "geaendert_quelle",
    "uebernahme_zeitpunkt", "uebernahme_verfahren", "eingriffe", "limitierungen",
]


PFLICHT = ["bezeichnung", "herausgeber", "zitat"]

DDL = f"""
ALTER TABLE {META_SCHEMA}.{TABELLE}
    ALTER COLUMN art DROP NOT NULL,
    ALTER COLUMN art DROP DEFAULT;

ALTER TABLE {META_SCHEMA}.{TABELLE}
    ADD COLUMN IF NOT EXISTS zitat                TEXT,
    ADD COLUMN IF NOT EXISTS beschreibung         TEXT,
    ADD COLUMN IF NOT EXISTS urheber              TEXT,
    ADD COLUMN IF NOT EXISTS stand_quelle         DATE,
    ADD COLUMN IF NOT EXISTS geaendert_quelle     DATE,
    ADD COLUMN IF NOT EXISTS uebernahme_zeitpunkt TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS uebernahme_verfahren TEXT,
    ADD COLUMN IF NOT EXISTS eingriffe            TEXT,
    ADD COLUMN IF NOT EXISTS limitierungen        TEXT;

COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.zitat IS
    'dcterms:bibliographicCitation - Pflicht an jeder Lieferung (mod:2.4)';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.beschreibung IS
    'dcterms:description - erklaert die Felder der Lieferung (mod:2.5)';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.urheber IS
    'dcterms:creator - nur wo Urheber und Herausgeber auseinanderfallen (mod:2.4)';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.stand_quelle IS
    'dcterms:issued - wann der Herausgeber diese Fassung veroeffentlicht hat';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.geaendert_quelle IS
    'dcterms:modified - nur wo die Quelle die Angabe selbst mitliefert';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.uebernahme_zeitpunkt IS
    'prov:generatedAtTime - wann die Lieferung in den Bestand gelangt ist';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.uebernahme_verfahren IS
    'stkg:uebernahmeVerfahren - womit die Lieferung eingespielt wurde';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.eingriffe IS
    'stkg:eingriffe - eigene Aenderungen, Verweis auf(mod:2.5)';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.limitierungen IS
    'stkg:limitierungen - was die Lieferung nicht hergibt (mod:2.5)';
"""


def lit(wert):
    if wert is None:
        return "NULL"
    if isinstance(wert, list):
        inhalt = ", ".join("'" + w.replace("'", "''") + "'" for w in wert)
        return f"ARRAY[{inhalt}]"
    if isinstance(wert, int):
        return str(wert)
    return "'" + str(wert).replace("'", "''") + "'"


def pruefe():
    kennungen = [e["lieferung_id"] for e in LIEFERUNGEN]
    doppelt = {k for k in kennungen if kennungen.count(k) > 1}
    if doppelt:
        raise SystemExit(f"Kennung mehrfach vergeben: {', '.join(sorted(doppelt))}")

    unbekannt = [f for e in LIEFERUNGEN for f in e if f not in SPALTEN]
    if unbekannt:
        raise SystemExit(f"Feld ohne Spalte: {', '.join(sorted(set(unbekannt)))}")

    for eintrag in LIEFERUNGEN:
        fehlend = [f for f in PFLICHT if not eintrag.get(f)]
        if fehlend:
            log.warning("  %-30s ohne %s", eintrag["lieferung_id"],
                        ", ".join(fehlend))

    for feld in SPALTEN:
        leer = [e["lieferung_id"] for e in LIEFERUNGEN if e.get(feld) is None]
        if leer:
            log.info("  %-22s leer bei %2s von %s Lieferungen",
                     feld, len(leer), len(LIEFERUNGEN))


def schreibe():
    zeilen = []
    for eintrag in LIEFERUNGEN:
        werte = [lit(eintrag.get(spalte)) for spalte in SPALTEN]
        zeilen.append("(" + ", ".join(werte) + ")")


    updates = ",\n    ".join(
        f"{s} = coalesce(EXCLUDED.{s}, {META_SCHEMA}.{TABELLE}.{s})"
        for s in SPALTEN if s != "lieferung_id"
    )

    sql = DDL + f"""
INSERT INTO {META_SCHEMA}.{TABELLE}
    ({", ".join(SPALTEN)})
VALUES
""" + ",\n".join(zeilen) + f"""
ON CONFLICT (lieferung_id) DO UPDATE SET
    {updates};
"""


    tmp = Path(tempfile.gettempdir()) / "datenlieferung.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, "datenlieferung")


def report():
    log.info("--- %s.%s ---", META_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT coalesce(art, '(leer)'), count(*) FROM {META_SCHEMA}.{TABELLE}
        GROUP BY 1 ORDER BY 2 DESC;
    """):
        log.info("  %-22s %s Lieferungen", *zeile)

    log.info("--- Lieferungen ohne Zitat (mod:2.4 verlangt es an jeder) ---")
    ohne = query(f"""
        SELECT lieferung_id FROM {META_SCHEMA}.{TABELLE}
        WHERE zitat IS NULL ORDER BY 1;
    """)
    if ohne:
        for zeile in ohne:
            log.warning("  %s", zeile[0])
    else:
        log.info("  keine - jede Lieferung traegt ein Zitat")

    log.info("--- Steht jede Lieferung der Tabelle auch in dieser Datei? ---")
    hier = {e["lieferung_id"] for e in LIEFERUNGEN}


    zeilen = query(f"""
        SELECT lieferung_id, art FROM {META_SCHEMA}.{TABELLE} ORDER BY 1;
    """)
    archiv = [z[0] for z in zeilen if z[1] == "archiv"]
    fremd  = [z[0] for z in zeilen if z[0] not in hier and z[1] != "archiv"]
    if archiv:
        log.info("  %s als archiv gekennzeichnet, absichtlich nicht hier: %s",
                 len(archiv), ", ".join(archiv))
    if fremd:
        log.warning("  %s Lieferungen stehen in der Tabelle, aber nicht hier - " "ein Ladeskript hat sie angelegt: %s",
                    len(fremd), ", ".join(fremd))
    else:
        log.info("  ja, alle %s", len(hier))

    log.info("--- Verweist jede basis auf eine bekannte Lieferung? ---")
    offen = query(f"""
        SELECT DISTINCT b
        FROM {META_SCHEMA}.{TABELLE}, unnest(basis) AS b
        WHERE NOT EXISTS (SELECT 1 FROM {META_SCHEMA}.{TABELLE} d
                          WHERE d.lieferung_id = b);
    """)
    if offen:
        for zeile in offen:
            log.warning("  unbekannte Basis: %s", zeile[0])
    else:
        log.info("  ja, alle Verweise loesen auf")


def main():
    if not query(f"SELECT 1 FROM {META_SCHEMA}.{TABELLE} LIMIT 1;"):
        raise SystemExit(f"{META_SCHEMA}.{TABELLE} fehlt - erst ein Ladeskript laufen lassen")
    log.info("--- Vorabpruefung der %s Eintraege ---", len(LIEFERUNGEN))
    pruefe()
    schreibe()
    report()


if __name__ == "__main__":
    main()
