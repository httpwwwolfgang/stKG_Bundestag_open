import sys
import logging
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import run_sql, run_sql_file, query

META_SCHEMA = "meta"
TABELLE     = "eingriff"


ERGAENZT = "ergaenzt"
ERSETZT  = "ersetzt"
ENTFERNT = "entfernt"
GELEERT  = "geleert"


EINGRIFFE = [


    {
        "eingriff_id":  "E1",
        "lieferung_id": "aw_api_v2",
        "art":          ERGAENZT,
        "bezeichnung":  "Amtliche Wahlkreisnummer je Mandat festschreiben",
        "faelle":       137,
        "betrifft_kante":   "stkg:hatMandatsWahlkreis",
        "nachweis_tabelle": "politiker_innen.mandat",
        "nachweis_spalte":  "wkr_herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E1",
        "begruendung":  "Bei 50 Direktgewaehlten fuehrt abgeordnetenwatch keinen " "Wahlkreis. Die amtlichen MdB-Stammdaten nennen ihn in WKR_NUMMER " "-- sie sagen die Nummer, statt sie aus dem Verhalten derselben " "Person zu erschliessen. Nach dem Eingriff hat kein " "Direktgewaehlter mehr einen leeren Wahlkreis.",
    },
    {
        "eingriff_id":  "E1b",
        "lieferung_id": "aw_api_v2",
        "art":          ERGAENZT,
        "bezeichnung":  "Fehlende Mandatsart aus dem XML ergaenzt",
        "faelle":       18,
        "betrifft_kante":   "stkg:hatMandatstyp",
        "nachweis_tabelle": "politiker_innen.mandat",
        "nachweis_spalte":  "mandatsart_herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E1b",
        "begruendung":  "Bei 18 Mandaten liefert abgeordnetenwatch keine Mandatsart, 17 " "davon in der Legislatur 2013-2017. Aus ihnen geht nicht hervor, " "ob die Person direkt gewaehlt wurde oder ueber die Liste kam. " "Die Luecke ist kein Zufallsausfall: 14 der 18 haengen an einem " "Wechsel mitten in oder unmittelbar vor der Wahlperiode. Das " "MdB-XML nennt die Art.",
    },


    {
        "eingriff_id":  "E1c",
        "lieferung_id": "aw_api_v2",
        "art":          ERSETZT,
        "bezeichnung":  "Mandatsart der Nachruecker durch die amtliche " "ersetzt",
        "begruendung":  "Die gelieferte Mandatsart kennt neben list und " "constituency den Wert moved_up. Er beantwortet eine " "andere Frage als die Spalte stellt und verdraengt " "dabei die Antwort auf sie: bei 77 Mandaten steht " "nicht, ob sie ueber Liste oder Wahlkreis errungen " "wurden. Zudem ist die Markierung nicht durchgaengig " "- abgeordnetenwatch setzt sie erst ab 2017, sodass " "die 27 Nachruecker der 18. Wahlperiode als list " "gefuehrt sind. Das amtliche XML nennt fuer alle 77 " "Landesliste; das Nachruecken selbst steht mit 109 " "Uebergaengen vollstaendiger in " "politiker_innen.nachfolge.",
        "faelle":       77,
        "betrifft_kante":   "stkg:hatMandatstyp",
        "nachweis_tabelle": "politiker_innen.mandat",
        "nachweis_spalte":  "mandatsart_herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E1c",
    },


    {
        "eingriff_id":  "E2a",
        "lieferung_id": "aw_api_v2",
        "art":          ERSETZT,
        "bezeichnung":  "Falsche Listenreferenzen auf die richtige Legislatur " "gesetzt",
        "begruendung":  "Die Mandate von Lambrecht und Wagenknecht hingen an " "der Landesliste einer anderen Legislatur, die " "Kandidatur 28411 Uhl an der falschen Liste.",
        "faelle":       3,
        "betrifft_kante":   "stkg:hatMandatsLandesliste",
        "nachweis_tabelle": "politiker_innen.mandat",
        "nachweis_spalte":  "liste_herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E2",
    },
    {
        "eingriff_id":  "E2b",
        "lieferung_id": "aw_api_v2",
        "art":          GELEERT,
        "bezeichnung":  "Wahlkreisnummern geleert, wo die Person dort nie " "angetreten ist",
        "begruendung":  "Listenmandate trugen eine Wahlkreisnummer, obwohl es " "zu dieser Wahl keine eigene Kandidatur gab. Belegt " "durch drei zusammentreffende Angaben: leere " "WKR_NUMMER im MdB-XML bei MANDATSART Landesliste, " "keine Kandidatur, und ein anderer Bewerber derselben " "Partei, dessen Erststimmenanteil sich mit dem " "amtlichen Parteianteil deckt. Bei dreien ist es die " "Wahlkreisnummer des Vorgaengers, auf den sie " "nachgerueckt sind.",
        "faelle":       11,
        "betrifft_kante":   "stkg:hatMandatsWahlkreis",
        "nachweis_tabelle": "politiker_innen.mandat",
        "nachweis_spalte":  "wkr_herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E2",
        "zu_klaeren":   "Fallzahl nachzurechnen: zwei Mandate (Uhl, Herdan), " "eine Kandidatur (28411) und acht aus dem Nachtrag vom " "28.08. ergeben 11. Ob Lotarewicz (8956) und Schwartz " "(52050) hierher gehoeren, sagtnicht " "eindeutig -- dort steht nur 'erledigt'.",
    },
    {
        "eingriff_id":  "E2c",
        "lieferung_id": "aw_api_v2",
        "art":          ENTFERNT,
        "bezeichnung":  "Zwei feldgleiche Duplikate aus der Clean-Schicht " "entfernt",
        "begruendung":  "28412 Uhl und 21955 Hansen sind feldgleiche Duplikate. " "Die Rohschicht behaelt beide, sie sind daraus " "jederzeit wiederherstellbar.",
        "faelle":       2,
        "betrifft_kante":   "stkg:hatMandatstraeger",
        "fundstelle":   ", Abschnitt E2;, A10",
    },
    {
        "eingriff_id":  "E6",
        "lieferung_id": "aw_api_v2",
        "art":          ERSETZT,
        "bezeichnung":  "Drei Wahlkreise aus abgeordnetenwatch statt aus den Stammdaten",
        "faelle":       3,
        "betrifft_kante":   "stkg:hatMandatsWahlkreis",
        "nachweis_tabelle": "politiker_innen.mandat",
        "nachweis_spalte":  "wkr_herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E6",
        "begruendung":  "Bei drei Mandaten weicht der Wahlkreis der Stammdaten von dem " "bei abgeordnetenwatch ab. Griewel wird auf 146 Soest gesetzt, " "Luehrmann auf 178 Rheingau-Taunus/Limburg, Gminder auf NULL. " "Grundlage ist die Limitierung S2: Zwei Kandidaturorte weichen " "von abgeordnetenwatch ab.",
    },

    {
        "eingriff_id":  "E7a",
        "lieferung_id": "aw_api_v2",
        "art":          ERSETZT,
        "bezeichnung":  "Zwei Kandidaturen richtiggestellt, die zwei Bewerber " "einer Partei in einen Wahlkreis setzen",
        "begruendung":  "Eine Partei reicht je Wahlkreis genau einen " "Kreiswahlvorschlag ein, und die amtliche Statistik " "weist je Partei und Wahlkreis genau eine " "Erststimmenzahl aus. Fiedler stand mit einem zweiten " "FDP-Bewerber in Wahlkreis 70, waehrend Wahlkreis 71 " "bei 10.637 FDP-Erststimmen leer war; Strickner stand " "als dieBasis-Bewerber neben einem zweiten, trat aber " "fuer die BueSo an, die dort ebenfalls Erststimmen hat.",
        "faelle":       2,
        "betrifft_kante":   "stkg:hatKandidaturWahlkreis",
        "nachweis_tabelle": "politiker_innen.kandidatur",
        "nachweis_spalte":  "wkr_herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E7;",
    },
    {
        "eingriff_id":  "E7b",
        "lieferung_id": "aw_api_v2",
        "art":          ENTFERNT,
        "bezeichnung":  "Drei Kandidaturen aus der Clean-Schicht entfernt, die " "es so nicht gab",
        "begruendung":  "Nicht als Duplikat -- es sind verschiedene Personen, " "aber Kandidaturen, die es so nicht gab. Je Fall steht " "der Beleg daneben: Ringger hat eine zweite, richtig " "erfasste Kandidatur 2021 als Einzelbewerbung; zu " "Heinrich liefert abgeordnetenwatch keinerlei " "Stammdaten, waehrend der Mitbewerber vollstaendig " "erfasst ist; Wandtner und Pfeffer tragen beide " "Listenplatz 1 derselben Landesliste.",
        "faelle":       3,
        "betrifft_kante":   "stkg:hatKandidat",
        "fundstelle":   ", Abschnitt E7;",


    },


    {
        "eingriff_id":  "E2e",
        "lieferung_id": "aw_api_v2",
        "art":          ERGAENZT,
        "bezeichnung":  "Landesliste aus dem amtlichen MdB-XML ergaenzt, wo " "abgeordnetenwatch keine fuehrt",
        "begruendung":  "Das MdB-XML nennt in stammdaten_mdb_wahlperiode das " "Bundesland der Liste direkt fuer die betroffene " "Wahlperiode. Ueber liste_je_land wird daraus das " "Listenobjekt, weil es je Bundesland und Wahl genau " "eines gibt. Gegengeprueft: Wo " "beide Quellen etwas sagen, stimmen sie in 1.255 von " "1.256 Faellen ueberein. Der gelieferte Wert bleibt " "in electoral_list_id unveraendert stehen.",
        "faelle":       456,
        "betrifft_kante":   "stkg:hatKandidaturLandesliste",
        "nachweis_tabelle": "politiker_innen.candidacy_mandate",
        "nachweis_spalte":  "liste_herkunft",
        "nachweis_wert":    "amtlich_ergaenzt",
        "fundstelle":   "03_load_db/politiker_innen/setze_landesliste.py; " "",
    },
    {
        "eingriff_id":  "E2f",
        "lieferung_id": "aw_api_v2",
        "art":          ERGAENZT,
        "bezeichnung":  "Landesliste aus dem Wahlkreis abgeleitet, wo weder " "abgeordnetenwatch noch das MdB-XML eine fuehren",
        "begruendung":  "Das Listenobjekt gibt es je Bundesland und Wahl genau " "einmal, und das Bundesland " "steht im Wahlkreis. Abgeleitet wird NUR, wo ein " "Listenplatz dasteht: Er ist der Beleg, dass die " "Person ueberhaupt auf einer Liste stand. Ohne ihn " "bliebe offen, ob sie nur im Wahlkreis antrat. Die " "Angabe ist damit erschlossen und nicht geliefert -- " "wer sie als Quellenangabe liest, irrt. Die " "Stammdaten des Bundestages kennen nur Mandate, " "deshalb greift E2c fuer reine Kandidaturen nicht.",
        "faelle":       1250,
        "betrifft_kante":   "stkg:hatKandidaturLandesliste",
        "nachweis_tabelle": "politiker_innen.candidacy_mandate",
        "nachweis_spalte":  "liste_herkunft",
        "nachweis_wert":    "abgeleitet",
        "fundstelle":   "03_load_db/politiker_innen/setze_landesliste.py; " "",
    },


    {
        "eingriff_id":  "E15",
        "lieferung_id": "aw_api_v2",
        "art":          ERGAENZT,
        "bezeichnung":  "Listenplatz aus dem Mandatseintrag an die Kandidatur",
        "faelle":       223,
        "betrifft_kante":   "stkg:listenplatz",


        "fundstelle":   ", Abschnitt E15",
        "begruendung":  "abgeordnetenwatch fuehrt je Wahl einen " "Kandidatureintrag, der Wahlkreis und Liste zusammen " "nennt, und daneben den Mandatseintrag. Beide tragen " "denselben Listenplatz -- bei 1.670 der 1.966 Mandate " "steht er tatsaechlich an beiden. Bei 223 steht er " "allein am Mandat, waehrend die Kandidatur derselben " "Wahl leer bleibt; darunter 127 Direktmandate. Dass " "es sich um einen Pflegemangel handelt und nicht um " "einen Sachverhalt, zeigt der Verlauf einer einzelnen " "Person: 2013 und 2017 steht der Platz an beiden " "Eintragungen, 2021 nur am Mandat. Der Wert wird " "deshalb an die Kandidatur ergaenzt, die zu diesem " "Mandat fuehrte. Ohne den Eingriff stuende der " "Listenplatz am Mandat, wo er nicht hingehoert: Er " "ist die Position, auf der jemand antrat, und nicht " "die Art, wie das Mandat zustande kam.",
    },
    {
        "eingriff_id":  "E13",
        "lieferung_id": "aw_api_v2",
        "art":          ERGAENZT,
        "bezeichnung":  "55 Platzhalter-Kandidaturen angelegt, wo die amtliche " "Statistik Erststimmen ausweist und abgeordnetenwatch " "keinen Bewerber fuehrt",
        "begruendung":  "Weist die Bundeswahlleiterin fuer eine Partei in " "einem Wahlkreis Erststimmen aus, muss es einen " "Direktbewerber gegeben haben. Betroffen sind 24 " "Kleinparteien, die abgeordnetenwatch nicht fuehrt, " "sieben Faelle bei gefuehrten Parteien und die " "amtlichen Sammelzeilen fuer Waehlergruppen und " "Einzelbewerber (12) sowie 'uebrige' (12). Danach ist " "jede der 8.520 amtlichen Erststimmen-Zeilen belegt. " "Es werden keine Stammdaten erfunden: kein Name, kein " "Geburtsjahr, keine Liste. Erkennbar an negativer " "Kennung -- abgeordnetenwatch vergibt nur positive. " "Im Graphen bekommen sie keinen Personenknoten: " "55 eigene behaupteten 55 Menschen, wo bei den " "Sammelzeilen nur mindestens einer feststeht, und ein " "gemeinsamer liesse eine Person in 55 Wahlkreisen " "kandidieren. Was bekannt ist, haengt an der " "Kandidatur: die Partei.",
        "faelle":       55,
        "betrifft_kante":   "stkg:hatKandidat",
        "nachweis_tabelle": "politiker_innen.candidacy_mandate",
        "nachweis_spalte":  "wkr_herkunft",
        "nachweis_wert":    "platzhalter",
        "fundstelle":   "03_load_db/politiker_innen/" "ergaenze_platzhalter_kandidaturen.py",
    },
    {
        "eingriff_id":  "E8",
        "lieferung_id": "aw_api_v2",
        "art":          ERSETZT,
        "bezeichnung":  "Zwei Geburtsjahre aus den amtlichen Stammdaten richtiggestellt",
        "begruendung":  "Das amtliche MdB-XML fuehrt das Geburtsdatum tagesgenau " "bei 1.270 von 1.270 Personen; abgeordnetenwatch nur das " "Jahr und in zwei Faellen abweichend.",
        "faelle":       2,
        "betrifft_kante":   "stkg:geburtsdatum",
        "nachweis_tabelle": "politiker_innen.politician",
        "nachweis_spalte":  "year_of_birth_herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E8",
    },


    {
        "eingriff_id":  "E9",
        "lieferung_id": "wikidata",
        "art":          ERGAENZT,
        "bezeichnung":  "Drei Geburtsorte nachtraeglich verortet",
        "begruendung":  "Wikidata fuehrt zu diesen drei Ortsobjekten keine " "Koordinate; sie stammen aus korrekturen_geburtsort.csv.",
        "faelle":       3,
        "betrifft_kante":   "stkg:hatGeburtsort",
        "nachweis_tabelle": "politiker_innen.geburtsort",
        "nachweis_spalte":  "herkunft_koordinate",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt E9",
    },
    {
        "eingriff_id":  "E14",
        "lieferung_id": "wikidata",
        "art":          ERSETZT,
        "betrifft_kante":   "stkg:hatGeburtsort",
        "bezeichnung":  "Vierundzwanzig Berliner Geburtsorte auf den Sektor " "genauer gesetzt",
        "begruendung":  "Beide Lieferungen nennen bei 27 der 36 in Berlin " "geborenen Mandatstraeger der Wahlperioden 18 bis 20 " "nur 'Berlin' (Q64), dessen Koordinate der " "Stadtmittelpunkt an der ehemaligen Sektorengrenze " "ist. Fuer 24 wurde der Sektor recherchiert und " "ort_qid auf Q56037 oder Q56036 gesetzt; beide " "Objekte fuehrt Wikidata bereits. Drei Faelle " "bleiben unbestimmt.",
        "faelle":       24,
        "nachweis_tabelle": "politiker_innen.geburtsort",
        "nachweis_spalte":  "herkunft_ort",
        "nachweis_wert":    "wikidata",
        "fundstelle":   ", Abschnitt E14",
        "zu_klaeren":   "Die Fundstellen der 24 Recherchen fehlen; " "'grundlage' nennt nur die eigene Recherche vom " "08.09.2026.",
    },


    {
        "eingriff_id":  "E3",
        "lieferung_id": "bwl_wahlbezirke_2013",
        "art":          ERSETZT,
        "bezeichnung":  "Rieder 2013 in Ballenstedt aufgehen lassen",
        "faelle":       1,
        "betrifft_kante":   "stkg:gehoertZu",
        "fundstelle":   ", Abschnitt E3",
        "begruendung":  "Rieder (15085255, Landkreis Harz) hat am Wahltag 2013 gewaehlt " "-- eigener Wahlbezirk, 1.533 Wahlberechtigte, 939 gueltige " "Zweitstimmen -- steht aber in keinem Gebietsstand. Es geht in " "Ballenstedt auf, in das es eingegliedert wurde.",
    },
    {
        "eingriff_id":  "E4",
        "lieferung_id": "bwl_wahlbezirke_2021",
        "art":          ERSETZT,
        "bezeichnung":  "Langelsheim 2021 aus seinen vier Vorgaengern bilden",
        "faelle":       4,
        "betrifft_kante":   "stkg:gehoertZu",
        "fundstelle":   ", Abschnitt E4",
        "begruendung":  "Am Wahltag, dem 26.09.2021, bestanden vier eigene Gemeinden: " "Hahausen, Langelsheim, Lutter am Barenberge und Wallmoden. Sie " "fusionierten erst am 01.11.2021, fuenf Wochen spaeter. Die " "Ergebnisdatei fuehrt aber bereits den Fusionsschluessel 03153019 " "und liefert damit ein Ergebnis fuer vier Gebiete.",
    },
    {
        "eingriff_id":  "E5",
        "lieferung_id": "bwl_wahlbezirke_2021",
        "art":          ERSETZT,
        "bezeichnung":  "Den Fusionsschluessel aus der Wahlkreiszuordnung nehmen",
        "fundstelle":   ", Abschnitt E5",
        "begruendung":  "raum.gemeinde_wahlkreis_wahltag wird aus den Wahlbezirken " "gebaut, also steht der Fusionsschluessel 03153019 dort mit " "herkunft 'bezirk' -- und die vier Vorgaenger zusaetzlich ueber " "die Aufnahme. Das ergibt 10.998 Zuordnungen bei 10.997 Gebieten " "des Wahltags. Die Zeile fuer den Fusionsschluessel entfaellt, " "weil er keine Gemeinde des Wahltagsstands bezeichnet; im Graphen " "waere er ein Knoten ohne Entsprechung.",
        "faelle":       1,
        "betrifft_kante":   "stkg:gehoertZu",
    },


    {
        "eingriff_id":  "E10",
        "lieferung_id": "bwl_wahlbezirke_2021",
        "art":          ERGAENZT,
        "bezeichnung":  "Elf Gemeinden der VG Altenahr einzeln zuordnen",
        "begruendung":  "Nach der Flutkatastrophe im Juli 2021 wurden die zwoelf " "Gemeinden der VG Altenahr vorab zusammengelegt; die " "Bezirksstatistik fuehrt nur noch Altenahr. Die elf " "uebrigen bestanden am Wahltag als eigene Gemeinden und " "stehen im Gebietsstand, aber nicht in der Bezirksdatei. " "Ohne die Ergaenzung haetten sie keine " "Wahlkreiszuordnung, obwohl der Wahlkreis feststeht: " "alle zwoelf Gemeinden der Verbandsgemeinde liegen im " "Wahlkreis 198.",
        "faelle":       11,
        "betrifft_kante":   "stkg:gehoertZu",
        "nachweis_tabelle": "raum.gemeinde_wahlkreis_wahltag",
        "nachweis_spalte":  "herkunft",
        "nachweis_wert":    "aufnahme",
        "fundstelle":   ", Abschnitt E10; Sachverhalt als G5 in " "",
        "zu_klaeren":   "nachweis_wert nennt den einzigen Wert, der wirklich " "geliefert ist. Unter 'alles andere' faellt damit auch " "herkunft = 'zuordnungsliste' -- das ist kein Eingriff " "in diese Lieferung, sondern eine zweite Quelle. Die " "Spalte kann diesen Unterschied nicht ausdruecken.",
    },


    {
        "eingriff_id":  "E11a",
        "lieferung_id": "bwl_wahlbezirke_2013",
        "art":          ERGAENZT,
        "bezeichnung":  "Gemeinden ohne eigenen Wahlbezirk aus der Aufnahme " "zuordnen (2013)",
        "begruendung":  "Nach Par. 68 Abs. 2 BWO duerfen die Wahlbezirke kleiner " "Gemeinden mit denen einer Nachbargemeinde zusammengelegt " "werden. Die aufgenommene Gemeinde erscheint dann nicht " "mit eigener Zeile in der Bezirksdatei, obwohl sie am " "Wahltag bestand. Die Datei nennt die Aufnahme selbst -- " "im Klartext im Bezirksnamen oder ueber die Kennziffer " "EF7 --, nicht aber die daraus folgende Zuordnung zum " "Wahlkreis. Genau die traegt der Bestand.",
        "betrifft_kante":   "stkg:gehoertZu",
        "nachweis_tabelle": "raum.gemeinde_wahlkreis_wahltag",
        "nachweis_spalte":  "herkunft",
        "nachweis_wert":    "aufnahme",
        "fundstelle":   ", Abschnitt E11; Sachverhalt als W4 in " "",


        "faelle":       3,
    },
    {
        "eingriff_id":  "E11b",
        "lieferung_id": "bwl_wahlbezirke_2017",
        "art":          ERGAENZT,
        "bezeichnung":  "Gemeinden ohne eigenen Wahlbezirk aus der Aufnahme " "zuordnen (2017)",
        "begruendung":  "Wie E11a, fuer die Wahl 2017.",
        "betrifft_kante":   "stkg:gehoertZu",
        "nachweis_tabelle": "raum.gemeinde_wahlkreis_wahltag",
        "nachweis_spalte":  "herkunft",
        "nachweis_wert":    "aufnahme",
        "fundstelle":   ", Abschnitt E11; Sachverhalt als W4 in " "",
        "faelle":       5,
    },
    {
        "eingriff_id":  "E11c",
        "lieferung_id": "bwl_wahlbezirke_2021",
        "art":          ERGAENZT,
        "bezeichnung":  "Gemeinden ohne eigenen Wahlbezirk aus der Aufnahme " "zuordnen (2021)",
        "begruendung":  "Wie E11a, fuer die Wahl 2021. Hier haengt zusaetzlich " "E5 daran: Die vier Vorgaenger von Langelsheim holen " "ihren Wahlkreis ueber diesen Weg vom " "Fusionsschluessel, der erst danach entfaellt.",
        "betrifft_kante":   "stkg:gehoertZu",
        "nachweis_tabelle": "raum.gemeinde_wahlkreis_wahltag",
        "nachweis_spalte":  "herkunft",
        "nachweis_wert":    "aufnahme",
        "fundstelle":   ", Abschnitt E11; Sachverhalt als W4 in " "",
        "faelle":       152,
    },
    {
        "eingriff_id":  "E12",
        "lieferung_id": "bwl_wahlbezirke_2021",
        "art":          ERGAENZT,
        "bezeichnung":  "Drei Aufnahmebeziehungen von Hand eingetragen",
        "begruendung":  "Der automatische Abgleich der Bezirksnamen fand fuer " "drei Gemeinden die aufnehmende nicht. Groede " "(01054039 -> Hallig Hooge 01054050) scheiterte am " "Abstandstest, weil zwischen beiden Halligen 11.408 m " "Wattenmeer liegen; Scheuern (07232117 -> Neuerburg " "07232088) an der Schreibweise. Bei Sevenig bei " "Neuerburg (07232121 -> Karlshausen 07232064) lag der " "Fall anders: Im Kreis gibt es zwei Gemeinden namens " "Sevenig, der Name allein entscheidet also nicht " "zwischen ihnen. Hier wurde eine Mehrdeutigkeit " "aufgeloest, nicht nur ein Parserfehler behoben.",
        "faelle":       3,
        "betrifft_kante":   "stkg:gehoertZu",
        "nachweis_tabelle": "raum.gemeinde_aufnahme",
        "nachweis_spalte":  "herkunft",
        "nachweis_wert":    "Bezirksname der Ergebnisdatei",
        "fundstelle":   ", Abschnitt E12",
        "zu_klaeren":   "Die drei Zeilen tragen denselben herkunft-Wert wie " "die 137 automatisch gefundenen ('Bezirksname der " "Ergebnisdatei') und sind im Bestand deshalb NICHT von " "ihnen zu unterscheiden. nachweis_spalte/-wert taugen " "hier also nicht zum Auffinden; die drei Schluessel " "stehen stattdessen in der Begruendung. Ein eigener " "Herkunftswert waere die saubere Loesung, aendert aber " "den Bestand und ist gesondert freizugeben.",
    },


    {
        "eingriff_id":  "P1",
        "lieferung_id": "cpp_bt_fobbe",
        "art":          ERSETZT,
        "bezeichnung":  "Sprecherkennung ersetzt, weil sie einer anderen Person gehoert",
        "zu_klaeren":   "Im Bestand nicht nachweisbar: parlamentsarbeit.rede " "traegt die korrigierte Sprecherkennung, und die " "gelieferte steht nur in Fobbes Parquet, also " "ausserhalb der Datenbank. Welche Kennungen wir " "angefasst haben, ist allein " "02_clean/plenarprotokolle/korrekturen.py zu " "entnehmen. Eine Begleitspalte redner_id_herkunft " "waere nachzuruesten - das erforderte einen neuen Lauf " "der Redenaufbereitung und ist bisher nicht " "vorgenommen.",
        "fundstelle":   ", Abschnitt P1",
        "begruendung":  "Sieben Reden tragen im redner-Element die Kennung einer anderen " "Person. Bei seiner Rede als Bundespraesident am 22.03.2017 steht " "bei Frank-Walter Steinmeier die Kennung von Thomas de Maiziere; " "bei zwei Reden am 24.10.2017 traegt Wolfgang Schaeuble die von " "Hermann Otto Solms. Ersetzt wird nur, wo zwei Bedingungen " "zugleich gelten: Die Rede nennt einen anderen Namen als die " "Kennung sonst traegt, UND diese Person hat im selben Bestand " "eine eigene Kennung mit mehreren Reden. Ohne den Eingriff zaehlt " "de Maiziere eine Rede zu viel und Steinmeier eine zu wenig.",
        "faelle":       7,
        "betrifft_kante":   "stkg:hatRedner",
    },
    {
        "eingriff_id":  "P2",
        "lieferung_id": "cpp_bt_fobbe",
        "art":          ERGAENZT,
        "bezeichnung":  "Sprecherkennung ergaenzt, weil sie fehlt",
        "zu_klaeren":   "Im Bestand nicht nachweisbar: parlamentsarbeit.rede " "traegt die korrigierte Sprecherkennung, und die " "gelieferte steht nur in Fobbes Parquet, also " "ausserhalb der Datenbank. Welche Kennungen wir " "angefasst haben, ist allein " "02_clean/plenarprotokolle/korrekturen.py zu " "entnehmen. Eine Begleitspalte redner_id_herkunft " "waere nachzuruesten - das erforderte einen neuen Lauf " "der Redenaufbereitung und ist bisher nicht " "vorgenommen.",
        "fundstelle":   ", Abschnitt P2",
        "begruendung":  "Sieben Reden tragen gar keine Kennung, weil das Protokoll den " "Sprecher in einer anderen Bauform benennt: fuenf zu Protokoll " "gegebene Reden in einer Anlage, bei denen der Name als Klartext " "im ersten Absatz steht; eine mit name- statt redner-Element; " "eine mit leerem Attribut. Name und Rolle sind in allen sieben " "Faellen vollstaendig ausgezeichnet.",
        "faelle":       7,
        "betrifft_kante":   "stkg:hatRedner",
    },
    {
        "eingriff_id":  "P3",
        "lieferung_id": "cpp_bt_fobbe",
        "art":          ERGAENZT,
        "bezeichnung":  "Eigene Kennung fuer Personen, die keine bekommen koennen",
        "zu_klaeren":   "Im Bestand nicht nachweisbar: parlamentsarbeit.rede " "traegt die korrigierte Sprecherkennung, und die " "gelieferte steht nur in Fobbes Parquet, also " "ausserhalb der Datenbank. Welche Kennungen wir " "angefasst haben, ist allein " "02_clean/plenarprotokolle/korrekturen.py zu " "entnehmen. Eine Begleitspalte redner_id_herkunft " "waere nachzuruesten - das erforderte einen neuen Lauf " "der Redenaufbereitung und ist bisher nicht " "vorgenommen.",
        "fundstelle":   ", Abschnitt P3",
        "begruendung":  "Fuenf Reden tragen eine Behelfsnummer, die einer anderen Person " "gehoert -- Andreas Bovenschulte bekam 999990124 von Annette " "Widmann-Mauz, Peter Beuth dreimal 999990127 von Enak Ferlemann, " "Mehmet Daimagueler 999990141 von Judith Gerlach. Alle drei sind " "keine Abgeordneten: Bremer Buergermeister, hessischer " "Innenminister, Antiziganismusbeauftragter. Sie koennen deshalb " "keine Kennung der Bundestagsverwaltung erhalten und bekommen " "eine eigene mit dem Praefix INTERN_.",
        "faelle":       5,
        "betrifft_kante":   "stkg:hatRedner",
    },
    {
        "eingriff_id":  "P4",
        "lieferung_id": "cpp_bt_fobbe",
        "art":          ERSETZT,
        "bezeichnung":  "Namen richtiggestellt",
        "fundstelle":   ", Abschnitt P4",
        "begruendung":  "Zwei Reden mit zwei verschiedenen Fehlern. In Protokoll 20/82 " "vom 26.01.2023 stehen zwei Personen in einem Feld: Vorname " "'Dirk-UlrichLena', Nachname 'Mende Kreck'. Der Fliesstext nennt " "Dr. Lena Kreck, Senatorin.",
        "faelle":       2,
        "betrifft_kante":   "stkg:hatRedner",
    },
    {


        "eingriff_id":  "P5",
        "lieferung_id": "cpp_bt_fobbe",
        "art":          ERGAENZT,
        "bezeichnung":  "Behelfskennungen des Protokolls zu Personen aufgeloest",
        "fundstelle":   ", Abschnitt zu den Behelfskennungen",
        "begruendung":  "Das Protokoll gibt manchen Rednern statt der Kennung der " "Bundestagsverwaltung eine Behelfsnummer (999xxxxxx, einmal " "10000). Wer dahintersteht, sagt die Lieferung nicht -- die " "Zuordnung ist hier erschlossen und betrifft 30 Kennungen mit " "471 Reden. Zwei Gruppen mit getrenntem Beleg: Bei 23 Kennungen " "(120 Reden, fast durchweg Nachrueckerinnen und Nachruecker bei " "ihren ersten Reden) stuetzt sich die Aufloesung auf einen " "eindeutigen Namen im MdB-Verzeichnis, eine belegte Wahlperiode " "UND dieselbe Fraktion in Protokoll und Stammdaten. Bei sieben " "Kennungen (351 Reden, Regierungsmitglieder mit Mandat, darunter " "Svenja Schulze mit 160) nennt das Protokoll keine Fraktion, der " "dritte Beleg faellt also weg; an seiner Stelle stehen drei " "andere: Die Kennung traegt im ganzen Bestand einen einzigen " "Namen, alle ihre Reden fuehren ein Regierungsamt als Rolle, und " "jedes Rededatum liegt im Mandat. Fuenf der sieben sprechen in " "derselben Wahlperiode zusaetzlich unter ihrer regulaeren " "Kennung, mit derselben Fraktion. Ohne den Eingriff fuehrten " "471 Reden auf keine Person und damit auf kein Mandat und keinen " "Wahlkreis.",
        "faelle":       471,
        "betrifft_kante":   "stkg:hatRedner",
        "nachweis_tabelle": "parlamentsarbeit.redner_mdb",
        "nachweis_spalte":  "herkunft",
        "nachweis_wert":    "kennung_des_bundestages",
    },

    {
        "eingriff_id":  "I1",
        "lieferung_id": "bbsr_inkar_2024",
        "art":          GELEERT,
        "bezeichnung":  "Sechs Gemeinden bekommen durchgehend keinen Wert",
        "begruendung":  "Zwischen dem Stand 31.12.2021 und dem INKAR-Stand " "31.12.2022 aendern vier Vorgaenge den Zuschnitt dieser " "sechs Schluessel. Da INKAR zeitreihenbereinigt ist, " "steht auch der Wert von 1995 im Zuschnitt von 2022; es " "gibt kein Jahr, in dem er den Wahltagszuschnitt " "beschreibt. Der Wert saehe aus wie jeder andere - " "genau der Fall, den CLAUDE.md Regel 6 meint.",
        "faelle":       16675,
        "betrifft_kante":   "stkg:wert",
        "nachweis_tabelle": "strukturdaten.gebietskonflikt",
        "fundstelle":   ", Abschnitt I1",
    },
    {
        "eingriff_id":  "R1",
        "lieferung_id": "destatis_regionaldatenbank",
        "art":          ERSETZT,
        "bezeichnung":  "57 Gemeinden bekommen den Wert des Vorjahres",
        "faelle":       57,
        "betrifft_kante":   "stkg:wert",
        "nachweis_tabelle": "strukturdaten.gemeinde_regional_wahltag",
        "nachweis_spalte":  "herkunft",
        "nachweis_wert":    "geliefert",
        "fundstelle":   ", Abschnitt R1",
        "begruendung":  "Die Regionaldatenbank fuehrt jeden Jahrgang im Gebietsstand " "seines eigenen Jahres, und dieser Stand ist der 31.12. -- nicht " "der Wahltag. Zwischen Wahltag und Jahresende aendern Gemeinden " "noch ihren Zuschnitt; fuer diese zeigt der Wahljahrgang ein " "anderes Gebiet als das, in dem gewaehlt wurde.",
    },


    {
        "eingriff_id":  "G1",
        "lieferung_id": "bwl_wahlkreisgeometrie",
        "art":          ERSETZT,
        "bezeichnung":  "Drei gemeindefreie Gebiete 2013 von Hand zugeordnet",
        "faelle":       3,
        "betrifft_kante":   "stkg:gehoertZu",
        "nachweis_tabelle": "raum.gemeinde_wahlkreis_wahltag",
        "nachweis_spalte":  "herkunft",
        "nachweis_wert":    "eingriff_vg1000",
        "fundstelle":   ", Abschnitt G1",
        "begruendung":  "Seit dem 28.09.2026 bestimmt der Bestand den Wahlkreis " "gemeindefreier Gebiete aus der Flaeche statt aus der " "amtlichen Zuordnungsliste, deren Gebietsstand Monate vor " "dem Wahltag liegt. Das trifft in 638 von 641 Faellen " "dasselbe Ergebnis; 2017 (212 von 212) und 2021 (205 von " "205) stimmen lueckenlos ueberein. Die drei Abweichungen " "liegen alle 2013 und haben dieselbe Ursache: Die " "Wahlkreisgeometrie dieser Wahl ist VG1000, die " "Gemeindegeometrie VG250 -- derselbe Generalisierungsbruch, " "der bei den geteilten Grossstaedten die Randstreifen " "erzeugt. Insel Luetje Hoern " "(03457501, 0,09 km2) ist in VG1000 ganz wegvereinfacht und " "findet gar keinen Wahlkreis; Giebel (03151501) und Rheinau " "(08317971) liegen an einer Wahlkreisgrenze, die dort " "anders verlaeuft. Gesetzt wird die Angabe der amtlichen " "Liste -- WK 25, 51 und 283 --, weil ihr eigener Fehler " "diese drei nicht trifft: Keines der Gebiete hat zwischen " "dem Stand der Liste und dem Wahltag eine Zeile in " "raum.gebietsuebergang. Gegenprobe ohne Flaechenargument: " "Giebel und Rheinau bekommen 2017 und 2021 mit " "VG250-Wahlkreisen geometrisch genau diese Werte.",
    },
]


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("eingriff")

SPALTEN = [
    "eingriff_id", "lieferung_id", "art", "bezeichnung", "begruendung",
    "faelle", "betrifft_kante", "nachweis_tabelle", "nachweis_spalte",
    "nachweis_wert", "fundstelle", "zu_klaeren",
]

ARTEN = (ERGAENZT, ERSETZT, ENTFERNT, GELEERT)

DDL = f"""
CREATE TABLE IF NOT EXISTS {META_SCHEMA}.{TABELLE} (
    eingriff_id      TEXT PRIMARY KEY,
    lieferung_id     TEXT NOT NULL
                     REFERENCES {META_SCHEMA}.datenlieferung (lieferung_id),
    art              TEXT NOT NULL
                     CHECK (art IN ('ergaenzt','ersetzt','entfernt','geleert')),
    bezeichnung      TEXT NOT NULL,
    begruendung      TEXT,
    faelle           INTEGER,
    betrifft_kante   TEXT,
    nachweis_tabelle TEXT,
    nachweis_spalte  TEXT,
    nachweis_wert    TEXT,
    fundstelle       TEXT NOT NULL,
    zu_klaeren       TEXT
);

COMMENT ON TABLE {META_SCHEMA}.{TABELLE} IS
    'Register der Eingriffe. Ein Knoten je Zeile im Graphen (stkg:Eingriff, mod:2.5). Der ausfuehrliche Text steht in , hierher gehoert nur, was der Knoten traegt.';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.art IS
    'stkg:hatEingriffsart - ergaenzt, ersetzt, entfernt oder geleert';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.begruendung IS
    'stkg:eingriffBegruendung - warum eingegriffen wurde, nicht was getan wurde';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.faelle IS
    'stkg:eingriffFaelle - wie viele Werte oder Zeilen betroffen sind';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.betrifft_kante IS
    'stkg:betrifftKante - welche Kante des betroffenen Knotens veraendert wurde';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.nachweis_tabelle IS
    'Wo die betroffenen Zeilen stehen. Leer bei entfernten Zeilen: die gibt es im Bestand nicht mehr.';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.nachweis_spalte IS
    'Die Begleitspalte <spalte>_herkunft, die den Eingriff je Zeile ausweist';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.nachweis_wert IS
    'Welcher Wert dieser Spalte KEINEN Eingriff bedeutet - alles andere ist einer';
COMMENT ON COLUMN {META_SCHEMA}.{TABELLE}.zu_klaeren IS
    'Offene Frage zu diesem Eintrag, solange sie nicht entschieden ist';
"""


def lit(wert):
    if wert is None:
        return "NULL"
    if isinstance(wert, int):
        return str(wert)
    return "'" + str(wert).replace("'", "''") + "'"


def pruefe():
    kennungen = [e["eingriff_id"] for e in EINGRIFFE]
    doppelt = {k for k in kennungen if kennungen.count(k) > 1}
    if doppelt:
        raise SystemExit(f"Kennung mehrfach: {', '.join(sorted(doppelt))}")

    unbekannt = [f for e in EINGRIFFE for f in e if f not in SPALTEN]
    if unbekannt:
        raise SystemExit(f"Feld ohne Spalte: {', '.join(sorted(set(unbekannt)))}")

    for eintrag in EINGRIFFE:
        if eintrag["art"] not in ARTEN:
            raise SystemExit(f"{eintrag['eingriff_id']}: unbekannte Art "
                             f"{eintrag['art']}")

    for feld in ("begruendung", "faelle", "betrifft_kante", "nachweis_tabelle"):
        leer = [e["eingriff_id"] for e in EINGRIFFE if e.get(feld) is None]
        if leer:
            log.info("  %-18s leer bei %2s von %s: %s", feld, len(leer),
                     len(EINGRIFFE), ", ".join(leer))

    offen = [e for e in EINGRIFFE if e.get("zu_klaeren")]
    if offen:
        log.warning("  %s Eintraege mit offener Frage:", len(offen))
        for eintrag in offen:
            log.warning("      %s: %s", eintrag["eingriff_id"],
                        eintrag["zu_klaeren"])


def schreibe():
    zeilen = ["(" + ", ".join(lit(e.get(s)) for s in SPALTEN) + ")"
              for e in EINGRIFFE]
    updates = ",\n    ".join(f"{s} = EXCLUDED.{s}"
                             for s in SPALTEN if s != "eingriff_id")
    sql = DDL + f"""
INSERT INTO {META_SCHEMA}.{TABELLE} ({", ".join(SPALTEN)})
VALUES
""" + ",\n".join(zeilen) + f"""
ON CONFLICT (eingriff_id) DO UPDATE SET
    {updates};
"""
    tmp = Path(tempfile.gettempdir()) / "eingriff.sql"
    tmp.write_text(sql, encoding="utf-8")
    run_sql_file(tmp, "eingriff")
    entferne_verwaiste()


def entferne_verwaiste():
    bekannt = {e["eingriff_id"] for e in EINGRIFFE}
    liste = ", ".join("'%s'" % k.replace("'", "''") for k in sorted(bekannt))
    verwaist = query(f"""
        SELECT eingriff_id, bezeichnung FROM {META_SCHEMA}.{TABELLE}
         WHERE eingriff_id NOT IN ({liste}) ORDER BY eingriff_id;""")
    if not verwaist:
        return
    for eid, bez in verwaist:
        log.warning("  aus der Tabelle entfernt, weil zurueckgezogen: " "%s - %s", eid, bez)
    run_sql(f"""
        DELETE FROM {META_SCHEMA}.{TABELLE}
         WHERE eingriff_id NOT IN ({liste});""",
            "zurueckgezogene Eingriffe entfernen")


def report():
    log.info("--- %s.%s ---", META_SCHEMA, TABELLE)
    for zeile in query(f"""
        SELECT art, count(*), coalesce(sum(faelle)::text, '-')
        FROM {META_SCHEMA}.{TABELLE} GROUP BY 1 ORDER BY 2 DESC;
    """):
        log.info("  %-10s %2s Eingriffe, %s Faelle", *zeile)

    log.info("--- Halten die Nachweisspalten? ---")
    for zeile in query(f"""
        SELECT e.eingriff_id, e.nachweis_tabelle, e.nachweis_spalte
        FROM {META_SCHEMA}.{TABELLE} e
        WHERE e.nachweis_spalte IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM information_schema.columns c
              WHERE c.table_schema = split_part(e.nachweis_tabelle, '.', 1)
                AND c.table_name   = split_part(e.nachweis_tabelle, '.', 2)
                AND c.column_name  = e.nachweis_spalte)
        ORDER BY 1;
    """) or []:
        log.warning("  %s: %s.%s gibt es nicht", *zeile)
    else:
        log.info("  jede genannte Spalte existiert")

    log.info("--- Zeigt jede Lieferung auf eine bekannte? ---")
    offen = query(f"""
        SELECT e.eingriff_id, e.lieferung_id
        FROM {META_SCHEMA}.{TABELLE} e
        WHERE NOT EXISTS (SELECT 1 FROM {META_SCHEMA}.datenlieferung d
                          WHERE d.lieferung_id = e.lieferung_id);
    """)
    for zeile in offen:
        log.warning("  %s verweist auf unbekannte Lieferung %s", *zeile)
    if not offen:
        log.info("  ja, alle")


def pruefe_kuerzel():
    gesehen = {}
    doppelt = []
    for e in EINGRIFFE:
        k = e["eingriff_id"]
        if k in gesehen:
            doppelt.append((k, gesehen[k], e["bezeichnung"][:60]))
        gesehen[k] = e["bezeichnung"][:60]
    if doppelt:
        for k, a, b in doppelt:
            print(f"  {k} doppelt:")
            print(f"      {a}")
            print(f"      {b}")
        raise SystemExit(f"{len(doppelt)} doppelte Eingriffskuerzel.")


def main():
    pruefe_kuerzel()
    log.info("--- Vorabpruefung der %s Eingriffe ---", len(EINGRIFFE))
    pruefe()
    schreibe()
    report()


if __name__ == "__main__":
    main()
