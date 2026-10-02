import csv
import glob
import os
import re
import sys

import pdfplumber

DATEN = os.path.join("..", "..", "..", "Daten", "PArteipositionen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand
EXPORT = zwischenstand.fuer(__file__)
AUSGABE = "manifesto_kategorien.csv"

DOMAENE = {
    1: "External Relations",
    2: "Freedom and Democracy",
    3: "Political System",
    4: "Economy",
    5: "Welfare and Quality of Life",
    6: "Fabric of Society",
    7: "Social Groups",
}


RILE_RECHTS = ("104 201 203 305 401 402 407 414 505 601 603 605 606").split()
RILE_LINKS = ("103 105 106 107 403 404 406 412 413 504 506 701 202").split()


PAARE_VON_HAND = {"301": "302", "504": "505", "506": "507"}


NICHT_AGGREGIERT = {"202_2", "605_2", "703_2"}


def finde(muster):
    treffer = sorted(glob.glob(os.path.join(DATEN, muster)))
    if len(treffer) != 1:
        sys.exit("Erwarte genau eine Datei fuer %s, gefunden: %s"
                 % (muster, treffer))
    return treffer[0]


def lies_codes(csv_pfad):
    with open(csv_pfad, encoding="utf-8", newline="") as fh:
        kopf = next(csv.reader(fh))
    codes = []
    for spalte in kopf:
        m = re.fullmatch(r"per(\d{3}(?:_\d)?|\d{4})", spalte)
        if m:
            codes.append(m.group(1))
    return codes


def lies_bezeichnungen(pdf_pfad, codes):
    with pdfplumber.open(pdf_pfad) as pdf:
        text = "\n".join((s.extract_text(x_tolerance=1.0) or "")
                         for s in pdf.pages)

    namen = {}
    for code in codes:
        muster = r"(?:^|\n)per%s\s+([^\n]{3,70})" % re.escape(code)
        for m in re.finditer(muster, text):
            kandidat = re.sub(r"\s+", " ", m.group(1)).strip()
            if re.match(r"^[A-Z]", kandidat) and not kandidat.startswith(
                    ("For all", "This ", "All of")):
                namen[code] = kandidat
                break
    fehlend = [c for c in codes if c not in namen]
    if fehlend:
        sys.exit("Ohne Bezeichnung im Codebook: %s" % ", ".join(fehlend))
    return namen


def bestimme_gegenkategorien(namen):
    positiv, negativ = {}, {}
    for code, name in namen.items():
        if name.endswith(": Positive"):
            positiv[name[:-10].strip()] = code
        elif name.endswith(": Negative"):
            negativ[name[:-10].strip()] = code

    gegen = {}
    for stamm, code in positiv.items():
        if stamm in negativ:
            gegen[code] = negativ[stamm]
            gegen[negativ[stamm]] = code
    for a, b in PAARE_VON_HAND.items():
        if a not in namen or b not in namen:
            sys.exit("Handpaar %s/%s nicht im Datensatz" % (a, b))
        gegen[a], gegen[b] = b, a
    return gegen


def art_von(code):
    if "_" in code:
        return "unter"
    return "haupt" if len(code) == 3 else "cee"


def main():
    csv_pfad = finde("MPDataset_*.csv")
    pdf_pfad = finde("codebook_MPDataset_*.pdf")
    print("Codeliste aus: %s" % os.path.basename(csv_pfad))
    print("Bezeichnungen aus: %s" % os.path.basename(pdf_pfad))

    codes = lies_codes(csv_pfad)
    namen = lies_bezeichnungen(pdf_pfad, codes)
    gegen = bestimme_gegenkategorien(namen)

    zeilen = []
    for code in codes:
        art = art_von(code)
        haupt = code.split("_")[0] if art == "unter" else (
            code if art == "haupt" else "")
        domaene = int(code[0])
        zeilen.append([
            code,
            art,
            haupt,
            domaene,
            DOMAENE[domaene],
            namen[code],
            "rechts" if code in RILE_RECHTS else
            "links" if code in RILE_LINKS else "",
            gegen.get(code, ""),
            "ja" if code in NICHT_AGGREGIERT else "nein",
        ])

    os.makedirs(EXPORT, exist_ok=True)
    pfad = os.path.join(EXPORT, AUSGABE)
    with open(pfad, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["code", "art", "hauptkategorie", "domaene", "domaene_name",
                    "bezeichnung", "rile_seite", "gegenkategorie",
                    "zaehlt_als_uncodiert"])
        w.writerows(zeilen)
    print("\n  %s  %d Zeilen" % (AUSGABE, len(zeilen)))


    print("\nPruefungen")
    for art in ("haupt", "unter", "cee"):
        n = sum(1 for z in zeilen if z[1] == art)
        print("  %-6s %3d Kategorien" % (art, n))
    rechts = sum(1 for z in zeilen if z[6] == "rechts")
    links = sum(1 for z in zeilen if z[6] == "links")
    haupt = sum(1 for z in zeilen if z[1] == "haupt")
    print("  rile: %d rechts, %d links, %d Hauptkategorien in keiner Liste"
          % (rechts, links, haupt - rechts - links))
    if (rechts, links) != (13, 13):
        sys.exit("rile-Listen sind nicht 13 zu 13 - Formel pruefen")
    mit = sum(1 for z in zeilen if z[7])
    print("  Gegenkategorie vorhanden: %d von %d Kategorien" % (mit, len(zeilen)))
    print("  Hauptkategorien OHNE Gegenkategorie: %d"
          % sum(1 for z in zeilen if z[1] == "haupt" and not z[7]))

    einseitig = [z for z in zeilen
                 if z[1] == "haupt" and not z[7] and z[3] == 5]
    print("  Beispiel Domaene 5 ohne Gegenkategorie: %s"
          % ", ".join("per%s %s" % (z[0], z[5]) for z in einseitig[:4]))


if __name__ == "__main__":
    main()
