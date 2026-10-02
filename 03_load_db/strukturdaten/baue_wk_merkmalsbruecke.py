import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

from db import WK_DIR

DATEIEN = {2013: "btw2013_strukturdaten.csv",
           2017: "btw2017_strukturdaten.csv",
           2021: "btw21_strukturdaten.csv"}

QUELLE = WK_DIR.parent / "Strukturdaten"
HIER = Path(__file__).resolve().parent
import zwischenstand
EXPORT = zwischenstand.fuer(__file__)

KEIN_MERKMAL = {"wahlkreis nr", "wahlkreis name", "land", "fussnoten"}


KLEINRAEUMIG = {
    "bevoelkerung insgesamt in",
    "bevoelkerung deutsche in",
    "bevoelkerungsdichte einwohner je km",
    "flaeche km",
    "bevoelkerung auslaender",
    "bevoelkerung auslaender innen",
}


ALIAS = {

    "alter von bis unter jahren unter 18": "alter_u18",
    "alter von bis jahren unter 18": "alter_u18",
    "alter von bis unter jahren 18 25": "alter_18_24",
    "alter von bis jahren 18 24": "alter_18_24",
    "alter von bis unter jahren 25 35": "alter_25_34",
    "alter von bis jahren 25 34": "alter_25_34",
    "alter von bis unter jahren 35 60": "alter_35_59",
    "alter von bis jahren 35 59": "alter_35_59",
    "alter von bis unter jahren 60 75": "alter_60_74",
    "alter von bis jahren 60 74": "alter_60_74",
    "alter von bis unter jahren 75 und mehr": "alter_75plus",
    "alter von bis jahren 75 und mehr": "alter_75plus",

    "arbeitslosenquote insgesamt": "alq_gesamt",
    "arbeitslosenquote frauen": "alq_frauen",
    "arbeitslosenquote maenner": "alq_maenner",


    "allgemein bildendes schulwesen absolventen abgaenger nach dem abschluss " "ohne hauptschulabschluss": "schul_ohne_hs",
    "absolventen abgaenger allgemeinbildender schulen ohne hauptschulabschluss":
        "schul_ohne_hs",
    "schulabgaenger innen allgemeinbildender schulen ohne hauptschulabschluss":
        "schul_ohne_hs",
    "allgemein bildendes schulwesen absolventen abgaenger nach dem abschluss " "mit hauptschulabschluss": "schul_hs",
    "absolventen abgaenger allgemeinbildender schulen mit hauptschulabschluss":
        "schul_hs",
    "schulabgaenger innen allgemeinbildender schulen mit hauptschulabschluss":
        "schul_hs",


    "allgemein bildendes schulwesen absolventen abgaenger nach dem abschluss " "mit realschulabschluss": "schul_mittel",
    "absolventen abgaenger allgemeinbildender schulen mit mittlerem " "schulabschluss": "schul_mittel",
    "schulabgaenger innen allgemeinbildender schulen mit mittlerem " "schulabschluss": "schul_mittel",
    "absolventen abgaenger beruflicher schulen": "schul_beruflich",
    "schulabgaenger innen beruflicher schulen": "schul_beruflich",
    "absolventen abgaenger allgemeinbildender schulen mit allgemeiner und " "fachhochschulreife": "schul_hochschulreife",
    "schulabgaenger innen allgemeinbildender schulen mit allgemeiner und " "fachhochschulreife": "schul_hochschulreife",
    "absolventen abgaenger allgemeinbildender schulen insgesamt ohne externe " "je einwohner": "schul_gesamt",
    "schulabgaenger innen allgemeinbildender schulen insgesamt ohne externe " "je einwohner": "schul_gesamt",


    "bautaetigkeit und wohnungswesen bestand an wohnungen je einwohner":
        "wohn_bestand",
    "bestand an wohnungen insgesamt je einwohner": "wohn_bestand",
    "bautaetigkeit und wohnungswesen fertiggestellte wohnungen je einwohner":
        "wohn_fertig",
    "fertiggestellte wohnungen je einwohner": "wohn_fertig",

    "bevoelkerung auslaender": "bev_auslaender_anteil",
    "bevoelkerung auslaender innen": "bev_auslaender_anteil",
    "empfaenger innen von leistungen nach sgb ii auslaender": "sgb2_auslaender",
    "empfaenger innen von leistungen nach sgb ii auslaender innen":
        "sgb2_auslaender",

    "bruttoinlandsprodukt je einwohner": "bip_je_einwohner",
    "bruttoinlandsprodukt eur je einwohner": "bip_je_einwohner",
    "verfuegbares einkommen der privaten haushalte je einwohner":
        "einkommen_verfuegbar",
    "verfuegbares einkommen der privaten haushalte eur je einwohner":
        "einkommen_verfuegbar",
}


NAME = {
    "bevoelkerung insgesamt in": "bev_gesamt",
    "bevoelkerung deutsche in": "bev_deutsche",
    "bevoelkerung maennlich in": "bev_maennlich",
    "bevoelkerungsdichte einwohner je km": "bev_dichte",
    "flaeche km": "flaeche",
    "gemeinden anzahl": "gemeinden_anzahl",
    "zu bzw abnahme der bevoelkerung geburtensaldo je einwohner":
        "geburtensaldo",
    "zu bzw abnahme der bevoelkerung wanderungssaldo je einwohner":
        "wanderungssaldo",
    "sozialversicherungspflichtig beschaeftigte insgesamt je einwohner":
        "svb_gesamt",
    "sozialversicherungspflichtig beschaeftigte land und forstwirtschaft " "fischerei": "svb_landwirtschaft",
    "sozialversicherungspflichtig beschaeftigte produzierendes gewerbe":
        "svb_produzierend",
    "sozialversicherungspflichtig beschaeftigte handel gastgewerbe verkehr":
        "svb_handel_verkehr",
    "sozialversicherungspflichtig beschaeftigte oeffentliche und private " "dienstleister": "svb_dienst_oeffentlich",
    "sozialversicherungspflichtig beschaeftigte uebrige dienstleister und " "ohne angabe": "svb_dienst_uebrige",
    "empfaenger innen von leistungen nach sgb ii insgesamt je einwohner":
        "sgb2_gesamt",
    "empfaenger innen von leistungen nach sgb ii nicht erwerbsfaehige " "hilfebeduerftige": "sgb2_nicht_erwerbsfaehig",
    "arbeitslosenquote auslaender": "alq_auslaender",
    "arbeitslosenquote 15 bis unter 20 jahre": "alq_15_19",
    "arbeitslosenquote 15 bis 24 jahre": "alq_15_24",
    "arbeitslosenquote 55 bis unter 65 jahre": "alq_55_64",
    "arbeitslosenquote 55 bis 64 jahre": "alq_55_64_2021",
    "kraftfahrzeugbestand je einwohner": "kfz_bestand",
    "pkw bestand pkw insgesamt je einwohner": "pkw_bestand",
    "pkw bestand pkw mit elektro oder hybrid antrieb": "pkw_elektro_anteil",
    "unternehmensregister unternehmen insgesamt je einwohner":
        "unternehmen_gesamt",
    "unternehmensregister handwerksunternehmen je einwohner":
        "unternehmen_handwerk",
    "betriebe im bergbau und verarbeitenden gewerbe je einwohner":
        "betriebe_bergbau_verarbeitend",
    "gewerbeanzeigenstatistik gewerbeanmeldungen je einwohner":
        "gewerbe_anmeldungen",
    "gewerbeanzeigenstatistik gewerbeabmeldungen je einwohner":
        "gewerbe_abmeldungen",
    "gewerbesteuereinnahmen euro je einwohner": "gewerbesteuer",
    "insolvenzverfahren anzahl der beantragten verfahren je einwohner":
        "insolvenzen_verfahren",
    "insolvenzverfahren beschaeftigte je einwohner": "insolvenzen_beschaeftigte",
    "wohnflaeche je einwohner": "wohnflaeche_je_einwohner",
    "wohnflaeche je wohnung": "wohnflaeche_je_wohnung",
    "bodenflaeche nach art der tatsaechlichen nutzung siedlung und verkehr":
        "boden_siedlung_verkehr",
    "bodenflaeche nach art der tatsaechlichen nutzung vegetation und gewaesser":
        "boden_vegetation_gewaesser",
    "kindertagesbetreuung betreute kinder je einwohner": "kita_betreute_kinder",
    "kindertagesbetreuung betreute kinder unter 3 jahre betreuungsquote":
        "kita_quote_u3",
    "kindertagesbetreuung betreute kinder 3 bis unter 6 jahre betreuungsquote":
        "kita_quote_3_5",
    "allgemein bildendes schulwesen absolventen abgaenger nach dem abschluss " "insgesamt einschl fachhochschulreife je einwohner": "schul_gesamt_2013",
    "allgemein bildendes schulwesen absolventen abgaenger nach dem abschluss " "mit allgemeiner hochschulreife": "schul_hochschulreife_2013",
    "zensus 2011 bevoelkerung nach migrationshintergrund mit " "migrationshintergrund": "zensus_mit_migrationshintergrund",
    "zensus 2011 bevoelkerung nach migrationshintergrund ohne " "migrationshintergrund": "zensus_ohne_migrationshintergrund",
    "zensus 2011 bevoelkerung nach religionszugehoerigkeit evangelische kirche":
        "zensus_evangelisch",
    "zensus 2011 bevoelkerung nach religionszugehoerigkeit roemisch " "katholische kirche": "zensus_katholisch",
    "zensus 2011 bevoelkerung nach religionszugehoerigkeit sonstige keine " "ohne angabe": "zensus_sonstige_keine",
    "zensus 2011 wohnungen in wohngebaeuden eigentuemerquote":
        "zensus_eigentuemerquote",
}

MONATE = ["januar", "februar", "märz", "april", "mai", "juni", "juli",
          "august", "september", "oktober", "november", "dezember"]

DATUM = re.compile(
    r"(am\s+|ende\s+)?\d{1,2}\.\d{1,2}\.\d{4}"
    r"|(am\s+|ende\s+)?(januar|februar|märz|maerz|april|mai|juni|juli|august"
    r"|september|oktober|november|dezember)\s*\d{4}"
    r"|(?<![\d,.])\d{4}(?![\d,.])", re.I)


def norm(s):
    s = DATUM.sub(" ", s).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"),
                 ("ß", "ss"), ("blldender", "bildender"),
                 ("ende dezember", " ")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\bew\b", "einwohner", s)
    return re.sub(r"\s+", " ", s).strip()


def lies_kopf(datei):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(QUELLE / datei, encoding=enc) as f:
                zeilen = [z.rstrip("\n") for z in f if not z.startswith("#")]
            rohe = list(csv.reader(zeilen, delimiter=";"))
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"Zeichensatz nicht erkannt: {datei}")


    i = next(i for i, z in enumerate(rohe[:8])
             if any("Wahlkreis" in c and len(c) > 5 for c in z))
    return [c.strip() for c in rohe[i] if c.strip()], enc


def stichtag(name):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", name)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"(" + "|".join(MONATE) + r")\s*(\d{4})", name, re.I)
    if m:
        return f"{m.group(2)}-{MONATE.index(m.group(1).lower()) + 1:02d}"
    m = re.search(r"(?<![\d,.])(\d{4})(?![\d,.])", name)
    return m.group(1) if m else ""


def einheit(name):
    m = re.findall(r"\(([^)]*)\)\s*$", name)
    return m[0] if m else ""


def main():
    EXPORT.mkdir(exist_ok=True)
    spalten, art, koepfe = {}, {}, {}

    for jahr, datei in DATEIEN.items():
        kopf, enc = lies_kopf(datei)
        koepfe[jahr] = (kopf, enc)
        for rohname in kopf:
            n = norm(rohname)
            if not n or n in KEIN_MERKMAL:
                continue
            schluessel = ALIAS.get(n, n)
            spalten.setdefault(schluessel, {})[jahr] = rohname
            art[schluessel] = "alias" if n in ALIAS else "wortgleich"

    zeilen = []
    for schluessel, je_jahr in sorted(spalten.items()):
        for jahr in sorted(je_jahr):
            roh = je_jahr[jahr]
            zeilen.append({
                "bruecke": schluessel,
                "wahljahr": jahr,
                "wahlen": len(je_jahr),
                "in_allen_drei": "ja" if len(je_jahr) == 3 else "nein",
                "art": art[schluessel],
                "quellspalte": roh,
                "stichtag": stichtag(roh),
                "einheit": einheit(roh),
                "aufloesung": ("unter_gemeinde" if norm(roh) in KLEINRAEUMIG
                               else "nicht_feiner_als_gemeinde"),
                "spaltenname_db": NAME.get(schluessel, schluessel),


                "uebernehmen": "ja",


                "pruefen": "ja" if art[schluessel] == "alias" else "",
            })

    ohne_namen = sorted(s for s in spalten if s not in NAME and s not in
                        set(ALIAS.values()))
    if ohne_namen:
        print("ACHTUNG -- ohne vorgeschlagenen Spaltennamen:")
        for s in ohne_namen:
            print(f"    {s}")

    ziel = EXPORT / "wk_merkmalsbruecke.csv"
    with open(ziel, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(zeilen[0]), delimiter=";")
        w.writeheader()
        w.writerows(zeilen)

    drei = sorted(s for s, j in spalten.items() if len(j) == 3)
    zwei = sorted(s for s, j in spalten.items() if len(j) == 2)
    eins = sorted(s for s, j in spalten.items() if len(j) == 1)

    print("Spalten je Datei: " + ", ".join(
        f"{j}: {len(k)} ({e})" for j, (k, e) in koepfe.items()))
    print(f"\nMerkmale in allen drei Wahlen: {len(drei)}")
    print(f"           nur in zwei Wahlen: {len(zwei)}")
    print(f"           nur in einer Wahl:  {len(eins)}")

    print("\n=== IN ALLEN DREI WAHLEN -- Grundlage der gepoolten Auswertung ===")
    for i, s in enumerate(drei, 1):
        marke = "  [alias]" if art[s] == "alias" else ""
        auf = ("  <unter Gemeindeebene>"
               if norm(spalten[s][2021]) in KLEINRAEUMIG else "")
        print(f"  {i:>2}. {s}{marke}{auf}")

    print("\n=== NUR IN ZWEI WAHLEN ===")
    for s in zwei:
        print(f"  [{'/'.join(str(j) for j in sorted(spalten[s]))}]  {s}")


    alias = sorted(s for s in spalten if art[s] == "alias")
    print(f"\n\n=== DURCHZUSEHEN: die {len(alias)} Aliasentscheidungen ===")
    print("  Alles Uebrige steht wortgleich da und braucht keine Pruefung.\n")
    for s in alias:
        print(f"  {s}")
        for jahr in sorted(spalten[s]):
            print(f"      {jahr}  {spalten[s][jahr]}")
        print()

    print(f"  geschrieben: {ziel}")
    print(f"  {len(zeilen)} Zeilen, davon {sum(1 for z in zeilen if z['pruefen'])}"
          f" zur Durchsicht markiert (Spalte `pruefen`).")


if __name__ == "__main__":
    main()
