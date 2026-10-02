import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import query
import zwischenstand

AUSGABE = zwischenstand.fuer(__file__)


REGELN = [
    (r"^Bundeskanzl",                       "Bundeskanzler:in",            "Bund"),
    (r"^Altbundespr",                       "Altbundespräsident:in",       "Bund"),
    (r"^Bundespr(äs|as)",                   "Bundespräsident:in",          "Bund"),
    (r"^(Bundesratspr|Präsident(in)? des Bundesrates)",
                                            "Bundesratspräsident:in",      "Bundesrat"),
    (r"^Bundestagspr",                      "Bundestagspräsident:in",      "Bundestag"),
    (r"^Bundestagsvizepr|^Vizepr",          "Bundestagsvizepräsident:in",  "Bundestag"),
    (r"^Alterspr",                          "Alterspräsident:in",          "Bundestag"),


    (r"^Präsident(in)? (der|des) (Assemblée|Europäischen|Republik|Staates)",
                                            "Gast (auswärtig)",            ""),
    (r"^Präsident(in)?\b",                  "Bundestagspräsident:in",      "Bundestag"),
    (r"^Wehrbeauftr",                       "Wehrbeauftragte:r",           "Bundestag"),
    (r"^Polizeibeauftr",                    "Polizeibeauftragte:r",        "Bundestag"),
    (r"^Parl\.? ?Staatssekret|^Parl\. Staatssekr",
                                            "Parl. Staatssekretär:in",     "Bund"),
    (r"^Staatssekret|^Staatssekr",          "Staatssekretär:in",           "Bund"),
    (r"^Staatsmin",                         "Staatsminister:in",           "Bund"),
    (r"^Bundesmin",                         "Bundesminister:in",           "Bund"),
    (r"^(Koordinator|Koordinatorin)\b",     "Koordinator:in der Bundesregierung", "Bund"),
    (r"^(Drogenbeauftragte|Beauftr)",       "Beauftragte:r der Bundesregierung",  "Bund"),
    (r"^Ministerpr",                        "Ministerpräsident:in (Land)", "Land"),
    (r"^(Regierende|Regierender) B",        "Regierende:r Bürgermeister:in (Land)", "Land"),
    (r"^(Erster|Erste) B",                  "Erste:r Bürgermeister:in (Land)", "Land"),
    (r"^(Bürgermeister|Bürgermeisterin)\b",  "Bürgermeister:in (Land)",     "Land"),
    (r"^(Senator|Senatorin)\b",             "Senator:in (Land)",           "Land"),
    (r"^(Minister|Ministerin)\b",           "Minister:in (Land)",          "Land"),
    (r"^Stellv\.? MdBR",                    "Stellv. Mitglied des Bundesrates", "Bundesrat"),
    (r"^MdBR",                              "Mitglied des Bundesrates",    "Bundesrat"),
    (r"^MdB",                               "MdB",                         "Bundestag"),
    (r"^Gast",                              "Gast",                        ""),
    (r"^Stellv\.? Ch",                      "Chef:in des Bundeskanzleramtes (stellv.)", "Bund"),
]


SCHREIBFEHLER = {
    "B undesministerin für Bildung und Forschung":
        "Bundesministerin für Bildung und Forschung",
    "Bundesministerin f ür Ernährung und Landwirtschaft":
        "Bundesministerin für Ernährung und Landwirtschaft",
    "Bundesminister für wirtscha ftliche Zusammenarbeit und Entwicklung":
        "Bundesminister für wirtschaftliche Zusammenarbeit und Entwicklung",
    "Parl. Staatssekretär beim Bundesminister für wirtscha ftliche " "Zusammenarbeit und Entwicklung":
        "Parl. Staatssekretär beim Bundesminister für wirtschaftliche " "Zusammenarbeit und Entwicklung",
}


HAND = {}


MANDATSART = {"constituency": "MdB", "list": "MdB", "moved_up": "MdB"}


def ressort_aus_text(w):
    m = re.search(r"\((.+?)\)\s*$", w)
    if m:
        return m.group(1).strip(), "geparst"
    m = re.search(r"bei(?:m| der| dem)?\s+(?:Bundesminister(?:in)?|"
                  r"Bundeskanzler(?:in)?)\s+(.+)$", w)
    if m:
        return "Bundesministerium " + m.group(1).strip(), "geparst"
    m = re.match(r"^Bundesminister(?:in)?\s+(der|für|des)\s+(.+)$", w)
    if m:
        return f"Bundesministerium {m.group(1)} {m.group(2)}".strip(), "geparst"

    m = re.search(r"\bim\s+(Auswärtigen Amt|Bundeskanzleramt|.+?)\s*$", w)
    if m:
        return m.group(1).strip(), "geparst"


    if re.search(r"bei(?:m| der| dem)?\s+Bundeskanzler(?:in)?\s*$", w):
        return "Bundeskanzleramt", "geparst"


    m = re.search(r"\b(BM[A-Za-z]{1,5}|AA|BK|BPA)\s*$", w)
    if m:
        return m.group(1), "geparst"
    return "", ""


RESSORTKUERZEL = re.compile(r"^(BM[A-Za-z]{0,5}|AA|BK|BPA)$")


def normalisiere(w):
    if RESSORTKUERZEL.match(w.strip()):
        return "", "Bund", "Ressortkuerzel ohne Rollenwort"
    for muster, rolle, ebene in REGELN:
        if re.match(muster, w, flags=re.IGNORECASE):
            return rolle, ebene, muster
    return "ZU ENTSCHEIDEN", "", ""


def main():
    zeilen = []


    for wert, n in query(
            "SELECT funktion, count(DISTINCT person_id) " "FROM parlamentsarbeit.dip_person WHERE funktion <> '' " "GROUP BY funktion ORDER BY 2 DESC;"):
        rolle, ebene, regel = normalisiere(wert)
        zeilen.append({"quelle": "dip_person", "art": "funktion", "wert": wert,
                       "rolle_normalisiert": rolle, "ressort": "",
                       "ressort_herkunft": "je Person in dip_person.ressort",
                       "ebene": ebene, "personen": int(n),
                       "regel": regel or "", "anmerkung": ""})


    for wert, n in query(
            "SELECT mandatsart, count(DISTINCT politician_id) " "FROM politiker_innen.mandat WHERE mandatsart <> '' " "GROUP BY 1 ORDER BY 2 DESC;"):
        zeilen.append({"quelle": "mandat", "art": "mandatsart", "wert": wert,
                       "rolle_normalisiert": MANDATSART.get(wert, "ZU ENTSCHEIDEN"),
                       "ressort": "", "ressort_herkunft": "",
                       "ebene": "Bundestag", "personen": int(n),
                       "regel": "mandatsart ist keine Rolle",
                       "anmerkung": "Weg ins Mandat, bleibt als eigene Spalte"})


    for art, wert, n in query(
            "SELECT art, wert, count(DISTINCT redner_id) " "FROM parlamentsarbeit.redner_merkmal " "WHERE art IN ('rolle_lang','rolle_kurz') " "GROUP BY 1,2 ORDER BY 1,3 DESC;"):
        if art == "rolle_kurz":
            zeilen.append({"quelle": "redner_merkmal", "art": art,
                           "wert": wert, "rolle_normalisiert": "",
                           "ressort": "", "ressort_herkunft": "",
                           "ebene": "", "personen": int(n),
                           "regel": "Schreibvariante, keine Rolle",
                           "anmerkung": "Rolle steht an derselben Kennung " "unter rolle_lang"})
            continue
        gelesen = SCHREIBFEHLER.get(wert, wert)
        rolle, ebene, regel = normalisiere(gelesen)
        ressort, herkunft = ressort_aus_text(gelesen)
        zeilen.append({"quelle": "redner_merkmal", "art": art, "wert": wert,
                       "rolle_normalisiert": rolle, "ressort": ressort,
                       "ressort_herkunft": herkunft, "ebene": ebene,
                       "personen": int(n), "regel": regel or "",
                       "anmerkung": ("Schreibfehler der Quelle repariert"
                                     if gelesen != wert else "")})

    d = pd.DataFrame(zeilen)
    AUSGABE.mkdir(parents=True, exist_ok=True)
    d.to_csv(AUSGABE / "rollen_normalisierung.csv", index=False,
             encoding="utf-8")

    print(f"rollen_normalisierung.csv: {len(d)} Zeilen")
    print(f"\nQuellwerte je Quelle:")
    print(d["quelle"].value_counts().to_string())
    print(f"\nKanonische Rollen: {d['rolle_normalisiert'].nunique()}")
    print(d.groupby("rolle_normalisiert")
          .agg(quellwerte=("wert", "nunique"), personen=("personen", "sum"))
          .sort_values("personen", ascending=False).to_string())
    offen = d[d["rolle_normalisiert"] == "ZU ENTSCHEIDEN"]
    print(f"\nZU ENTSCHEIDEN: {len(offen)}")
    if len(offen):
        print(offen[["quelle", "art", "wert", "personen"]]
              .to_string(index=False))
    ohne_ressort = d[(d["quelle"] == "redner_merkmal")
                     & (d["ressort"] == "")
                     & (d["ebene"].isin(["Bund", "Land"]))]
    print(f"\nRollen mit Ebene Bund/Land, aber ohne erkanntes Ressort: "
          f"{len(ohne_ressort)}")
    if len(ohne_ressort):
        print(ohne_ressort[["wert", "rolle_normalisiert"]].head(12)
              .to_string(index=False))


if __name__ == "__main__":
    main()
