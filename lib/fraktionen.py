import re
import unicodedata


WEICHES_TRENNZEICHEN = "\u00ad"
LEGISLATUR = re.compile(r"\s*\(Bundestag\s*(\d{4})\s*-\s*(\d{4})\)\s*$")


WAHLPERIODE_AB_JAHR = {2013: 18, 2017: 19, 2021: 20}


KANON = [

    ("CDU/CSU",       "CDU/CSU",                "CDU und CSU"),
    ("SPD",           "SPD",                    "SPD"),
    ("GRUENE",        "BÜNDNIS 90/DIE GRÜNEN", "BÜNDNIS 90/DIE GRÜNEN"),
    ("LINKE",         "DIE LINKE",              "DIE LINKE"),
    ("AFD",           "AfD",                    "AfD"),
    ("FDP",           "FDP",                    "FDP"),
    ("BSW",           "BSW",                    "BSW"),
    ("FRAKTIONSLOS",  "fraktionslos",           None),
]


ALIAS = {

    "CDU/CSU": "CDU/CSU",
    "SPD": "SPD",
    "BÜNDNIS 90/DIE GRÜNEN": "GRUENE",
    "DIE LINKE": "LINKE",
    "AfD": "AFD",
    "FDP": "FDP",
    "BSW": "BSW",
    "fraktionslos": "FRAKTIONSLOS",


    "Fraktion der Christlich Demokratischen Union/" "Christlich - Sozialen Union": "CDU/CSU",
    "Fraktion der Sozialdemokratischen Partei Deutschlands": "SPD",
    "Fraktion BÜNDNIS 90/DIE GRÜNEN": "GRUENE",
    "Fraktion DIE LINKE.": "LINKE",
    "Gruppe Die Linke": "LINKE",
    "Fraktion Alternative für Deutschland": "AFD",
    "Fraktion der Freien Demokratischen Partei": "FDP",
    "Gruppe BSW - Bündnis Sahra Wagenknecht - " "Vernunft und Gerechtigkeit": "BSW",
    "Fraktionslos": "FRAKTIONSLOS",


    "CDU": "CDU/CSU",
    "DIE GRÜNEN": "GRUENE",
    "DIE LINKE.": "LINKE",
    "Die Linke. (Gruppe)": "LINKE",
    "BSW (Gruppe)": "BSW",


    "BÜ90/GR": "GRUENE",
    "BÜNDNIS`90/DIE GRÜNEN": "GRUENE",
    "Die Linke": "LINKE",


    "CSU": "CDU/CSU",
    "BÜNDNISSES 90/DIE GRÜNEN": "GRUENE",
    "BÜNDNIS 90/ DIE GRÜNEN": "GRUENE",
    "BÜNDNISSES 90/ DIE GRÜNEN": "GRUENE",
    "BÜNDNIS90/DIE GRÜNEN": "GRUENE",
    "GRÜNEN": "GRUENE",
    "Grünen": "GRUENE",
    "DIE LINKEN": "LINKE",
    "LINKEN": "LINKE",
    "Linken": "LINKE",
    "Linke": "LINKE",
    "Fraktionslosen": "FRAKTIONSLOS",
}


MUSTER = [
    ("CDU/CSU",      r"CDU/CSU"),
    ("CDU/CSU",      r"CDU\b"),
    ("CDU/CSU",      r"CSU\b"),
    ("SPD",          r"SPD\b"),
    ("GRUENE",       r"BÜNDNIS(?:SES)?\s*90\s*/\s*DIE\s+GRÜNEN"),
    ("GRUENE",       r"GRÜNEN\b"),
    ("GRUENE",       r"Grünen\b"),
    ("LINKE",        r"DIE\s+LINKE[N]?\b"),
    ("LINKE",        r"LINKEN\b"),
    ("LINKE",        r"Linken\b"),
    ("LINKE",        r"Linke\b"),
    ("AFD",          r"AfD\b"),
    ("FDP",          r"FDP\b"),
    ("BSW",          r"BSW\b"),
    ("FRAKTIONSLOS", r"Fraktionslosen"),
    ("FRAKTIONSLOS", r"fraktionslos"),
]

NAME = {i: n for i, n, _ in KANON}
IDS = [i for i, _, _ in KANON]


def normiere(wert):
    if wert is None:
        return "", None
    s = unicodedata.normalize("NFKC", str(wert))
    s = s.replace(WEICHES_TRENNZEICHEN, "")
    s = re.sub(r"\s+", " ", s).strip()
    wp = None
    treffer = LEGISLATUR.search(s)
    if treffer:
        wp = WAHLPERIODE_AB_JAHR.get(int(treffer.group(1)))
        s = s[:treffer.start()].strip()
    return s, wp


def zu_id(wert):
    kern, _ = normiere(wert)
    return ALIAS.get(kern)
