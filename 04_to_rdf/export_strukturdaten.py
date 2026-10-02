import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))
from export_raum import (PRAEFIXE, txt, iri, literal, run_copy)

AUSGABE = pfade.BEOBACHTUNGEN

LIEFERUNGEN = ["bwl_strukturdaten_2013",
               "bwl_strukturdaten_2017",
               "bwl_strukturdaten_2021"]


R_WKR = "wahlkreisstand/{wahljahr}_{wkr_nr}"

SQL = """
SELECT k.lieferung_id,
       k.merkmal,
       k.bezeichnung,
       k.stichtag,
       k.masseinheit,
       k.aufloesung,
       wi.wahljahr,
       wi.wkr_nr,
       wi.wert
  FROM strukturdaten.wahlkreis_indikator wi
  JOIN strukturdaten.wk_indikator k USING (indikator_id)
 WHERE wi.wert IS NOT NULL
 ORDER BY k.lieferung_id, k.merkmal, wi.wkr_nr
"""


ZEITKANTE = {10: ("stkg:erhebungszeitpunkt", "xsd:date"),
             7:  ("stkg:erhebungsmonat",     "xsd:gYearMonth"),
             4:  ("stkg:erhebungsjahr",      "xsd:gYear")}


def zeitangabe(stichtag):
    s = (stichtag or "").strip()
    eintrag = ZEITKANTE.get(len(s))
    if eintrag is None:
        return None
    kante, typ = eintrag
    return kante, f'"{s}"^^{typ}'


def definition(z):
    teile = [f"Spalte der Quelle: „{z['bezeichnung']}“."]
    if z["masseinheit"]:
        teile.append(f"Masseinheit: {z['masseinheit']}.")
    if z["aufloesung"] == "unter_gemeinde":
        teile.append("Von der Bundeswahlleiterin auf den Wahlkreiszuschnitt " "gerechnet, also unterhalb der Gemeindeebene.")
    else:
        teile.append("Nicht feiner als die Gemeinde: Wahlkreise, die ganz in " "einer geteilten Stadt liegen, tragen den Wert der " "ganzen Stadt.")
    return " ".join(teile)


def tripel(z):
    raum = R_WKR.format(wahljahr=z["wahljahr"], wkr_nr=int(z["wkr_nr"]))
    kennung = f"beobachtung/{z['merkmal']}_{z['wahljahr']}_{int(z['wkr_nr'])}"

    zeilen = [
        f"    {iri(kennung)}",
        "        a                  stkg:Beobachtung ;",
        f"        stkg:hatMerkmal    "
        f"{iri('merkmal/' + z['lieferung_id'] + '/' + z['merkmal'])} ;",
        f"        stkg:hatRaumbezug  {iri(raum)} ;",
    ]
    zeit = zeitangabe(z["stichtag"])
    if zeit:
        zeilen.append(f"        {zeit[0]:<18} {zeit[1]} ;")
    zeilen.append(f"        stkg:wert          {literal(z['wert'], 'dez')} .")
    return "\n".join(zeilen) + "\n\n"


def kopf(lieferung):
    zeilen = [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE]
    zeilen += ["", f"{iri('lieferung/' + lieferung)} {{", ""]
    return "\n".join(zeilen)


def merkmalsblock(lieferung, merkmal, z):
    return "\n".join([
        f"    {iri('merkmal/' + lieferung + '/' + merkmal)}",
        "        a                        stkg:Merkmal ;",
        f"        stkg:merkmalsbezeichnung {txt(z['bezeichnung'])} ;",
        f"        stkg:merkmalsdefinition  {txt(definition(z))} .",
        ""])


def baue():
    pfade.pruefe(AUSGABE)
    tmp = AUSGABE / "_export_strukturdaten.csv"
    run_copy(SQL, tmp, "strukturdaten")

    offen, merkmale = {}, defaultdict(dict)
    gezaehlt = defaultdict(int)
    genauigkeit = defaultdict(set)

    def schreibe(lieferung, text):
        if lieferung not in offen:
            for alt in AUSGABE.glob(f"{lieferung}*.trig"):
                alt.unlink()
            fh = (AUSGABE / f"{lieferung}.trig").open("w", encoding="utf-8")
            fh.write(kopf(lieferung))
            offen[lieferung] = fh
        offen[lieferung].write(text)

    try:
        with tmp.open(encoding="utf-8", newline="") as fh:
            for z in csv.DictReader(fh):
                lief = z["lieferung_id"]
                merkmale[lief].setdefault(z["merkmal"], z)
                eintrag = ZEITKANTE.get(len((z["stichtag"] or "").strip()))
                genauigkeit[eintrag[0] if eintrag else "ohne Stichtag"].add(
                    (lief, z["merkmal"]))
                schreibe(lief, tripel(z))
                gezaehlt[lief] += 1
    finally:
        for lief, fh in sorted(offen.items()):
            for merkmal, z in sorted(merkmale[lief].items()):
                fh.write(merkmalsblock(lief, merkmal, z))
            fh.write("}\n")
            fh.close()
        if tmp.exists():
            tmp.unlink()

    print("=== Geschrieben ===")
    for lief in LIEFERUNGEN:
        if lief not in gezaehlt:
            print(f"  {lief:<26} keine Zeilen -- geladen?")
            continue
        pfad = AUSGABE / f"{lief}.trig"
        print(f"  {lief:<26}{gezaehlt[lief]:>7} Beobachtungen, "
              f"{len(merkmale[lief]):>3} Merkmale, "
              f"{pfad.stat().st_size / 1024 / 1024:>6.1f} MB")

    print("\n  Genauigkeit der Datierung, je Merkmal und Wahl:")
    for kante in ("stkg:erhebungszeitpunkt", "stkg:erhebungsmonat",
                  "stkg:erhebungsjahr", "ohne Stichtag"):
        if genauigkeit.get(kante):
            print(f"      {kante:<26}{len(genauigkeit[kante]):>4}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--liste", action="store_true",
                   help="zeigt die Lieferungen und beendet sich")
    a = p.parse_args()
    if a.liste:
        for lief in LIEFERUNGEN:
            print(f"  {lief}")
        return
    baue()


if __name__ == "__main__":
    main()
