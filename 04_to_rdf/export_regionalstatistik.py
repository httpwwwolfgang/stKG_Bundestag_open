import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

from db import run_copy

BASIS     = "https://skg-bundestag.de/"
LIEFERUNG = "destatis_regionaldatenbank"
AUSGABE   = pfade.BEOBACHTUNGEN


WAHLTAG = {
    2013: "2013-09-22",
    2017: "2017-09-24",
    2021: "2021-09-26",
}

PRAEFIXE = [
    ("stkg", "https://skg-bundestag.de/schema#"),
    ("xsd",  "http://www.w3.org/2001/XMLSchema#"),
]

BESTAENDE = [
    {
        "name": "indikator_gemeinde",
        "tabelle": "strukturdaten.gemeinde_regional_wahltag",
        "schluessel": "ags",
        "raumbezug": "gemeindestand/{schluessel}_{wahltag}",
        "ebene": "Gemeinde",
    },
    {
        "name": "indikator_kreis",
        "tabelle": "strukturdaten.kreis_regional_wahltag",
        "schluessel": "kreis",
        "raumbezug": "kreisstand/{schluessel}_{wahltag}",
        "ebene": "Kreis",
    },
]


def txt(wert):
    s = str(wert)
    for such, ersatz in (("\\", "\\\\"), ('"', '\\"'),
                         ("\n", "\\n"), ("\r", ""), ("\t", "\\t")):
        s = s.replace(such, ersatz)
    return f'"{s}"'


def iri(pfad):
    return f"<{BASIS}{pfad}>"


def kopf():
    zeilen = [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE]
    zeilen += ["", f"{iri('lieferung/' + LIEFERUNG)} {{", ""]
    return "\n".join(zeilen)


def bezeichnung(name, merkmale_json):
    try:
        m = json.loads(merkmale_json) if merkmale_json else {}
    except (ValueError, TypeError):
        m = {}
    if not m:
        return name
    teile = [str(v) for _, v in sorted(m.items())]
    return f"{name}, " + ", ".join(teile)


def sql(bestand):
    s = bestand["schluessel"]
    return f"""
    SELECT w.{s}::text AS schluessel, w.wahl::text AS wahl,
           w.indikator_id::text AS merkmal, w.wert::text AS wert,
           coalesce(w.stichtag::text, '') AS stichtag,
           w.herkunft::text AS herkunft,
           i.indikator::text AS bezeichnung,
           coalesce(i.masseinheit, '')::text AS masseinheit,
           coalesce(i.merkmale::text, '') AS auspraegungen
    FROM {bestand['tabelle']} w
    JOIN strukturdaten.regional_indikator i
      ON  i.indikator_id = w.indikator_id
      AND i.ebene = '{bestand["ebene"].lower()}'
    WHERE w.wert IS NOT NULL
    """


def merkmalsblock(kennung, name, einheit, ebene):
    definition = (
        f"{name}. Erhoben von den Statistischen Aemtern des Bundes und der "
        f"Laender, Regionaldatenbank Deutschland, Ebene {ebene}. "
        f"Masseinheit: {einheit or 'nicht angegeben'}. "
        f"Der Wert steht im Gebietsstand des Berichtsjahres und ist dem "
        f"Wahltagszuschnitt zugeordnet; der Erhebungszeitpunkt steht an "
        f"der Beobachtung.")
    return "\n".join([
        f"    {iri('merkmal/' + LIEFERUNG + '/' + kennung)}",
        "        a                        stkg:Merkmal ;",
        f"        stkg:merkmalsbezeichnung {txt(name)} ;",
        f"        stkg:merkmalsdefinition  {txt(definition)} .",
        "",
    ])


def tripel(z, bestand):
    wahl = int(z["wahl"])
    tag = WAHLTAG.get(wahl)
    if tag is None:
        return ""
    raum = bestand["raumbezug"].format(schluessel=z["schluessel"], wahltag=tag)


    kennung = iri("beobachtung/regional_%s/%s_%s"
                  % (z["merkmal"], z["schluessel"], wahl))
    zeilen = [
        "    %s" % kennung,
        "        a                   stkg:Beobachtung ;",
        "        stkg:hatMerkmal     %s ;"
        % iri("merkmal/%s/%s" % (LIEFERUNG, z["merkmal"])),
        "        stkg:hatRaumbezug   %s ;" % iri(raum),
        "        stkg:wert           %s ;" % txt(z["wert"]),
    ]


    if z.get("stichtag"):
        zeilen.append('        stkg:erhebungszeitpunkt "%s"^^xsd:date ;'
                      % z["stichtag"])


    zeilen.append("        stkg:hatBezugsereignis  %s ." % iri("wahl/%d" % wahl))
    return "\n".join(zeilen) + "\n\n"


def baue(namen, max_mb=200):
    pfade.pruefe(AUSGABE)
    tmp = AUSGABE / "_regional.csv"
    grenze = max_mb * 1024 * 1024 if max_mb else 0
    merkmale = {}
    anzahl = defaultdict(int)
    teile = []
    vorjahr = defaultdict(set)

    for alt in list(AUSGABE.glob(f"{LIEFERUNG}.trig")) + \
               list(AUSGABE.glob(f"{LIEFERUNG}_[0-9][0-9].trig")):
        alt.unlink()

    zustand = {"nr": 1, "fh": None, "gross": 0}

    def dateiname(nr):
        return AUSGABE / (f"{LIEFERUNG}.trig" if nr == 1
                          else f"{LIEFERUNG}_{nr:02d}.trig")

    def oeffne():
        pfad = dateiname(zustand["nr"])
        fh = pfad.open("w", encoding="utf-8")
        fh.write(kopf())
        teile.append(pfad)
        return fh

    def schliesse(fh):
        for kennung, (name, einheit, ebene) in sorted(merkmale.items()):
            fh.write(merkmalsblock(kennung, name, einheit, ebene))
        fh.write("}\n")
        fh.close()

    def schreibe(text):
        if zustand["fh"] is None:
            zustand["fh"] = oeffne()
        if grenze and zustand["gross"] + len(text) > grenze:
            schliesse(zustand["fh"])
            if zustand["nr"] == 1:
                erst = teile[0]
                neu = erst.with_name(f"{LIEFERUNG}_01.trig")
                erst.replace(neu)
                teile[0] = neu
            zustand["nr"] += 1
            zustand["fh"] = oeffne()
            zustand["gross"] = 0
        zustand["fh"].write(text)
        zustand["gross"] += len(text)

    try:
        for bestand in BESTAENDE:
            if namen and bestand["name"] not in namen:
                continue
            run_copy(sql(bestand), tmp, bestand["name"])
            with tmp.open(encoding="utf-8", newline="") as fh:
                for z in csv.DictReader(fh):
                    merkmale.setdefault(
                        z["merkmal"],
                        (bezeichnung(z["bezeichnung"], z["auspraegungen"]),
                         z["masseinheit"], bestand["ebene"]))
                    if z["herkunft"] != "wahljahr":
                        vorjahr[z["wahl"]].add(z["schluessel"])
                    text = tripel(z, bestand)
                    if not text:
                        continue
                    schreibe(text)
                    anzahl[bestand["name"]] += 1
            print(f"  {bestand['name']:<26} "
                  f"{anzahl[bestand['name']]:>9} Beobachtungen", flush=True)
    finally:
        if zustand["fh"] is not None:
            schliesse(zustand["fh"])
        if tmp.exists():
            tmp.unlink()
        gesamt = 0
        for pfad in teile:
            gross = pfad.stat().st_size
            gesamt += gross
            print(f"  -> {pfad.name:<34} {gross/1024/1024:>8.1f} MB")
        print(f"\n  {len(teile)} Datei(en), {gesamt/1024/1024:.1f} MB")
        print(f"  {len(merkmale)} Merkmale, {sum(anzahl.values())} Beobachtungen")
        if vorjahr:
            print("\n  Werte aus dem VORJAHR (Gemeinde im Wahljahrgang nicht " "mehr gefuehrt):")
            for w in sorted(vorjahr):
                print(f"    Wahl {w}: {len(vorjahr[w])} Einheiten")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("bestand", nargs="*", help="nur diese Bestaende")
    p.add_argument("--liste", action="store_true")
    p.add_argument("--max-mb", type=int, default=200)
    a = p.parse_args()
    if a.liste:
        for b in BESTAENDE:
            print(f"  {b['name']:<26} {b['tabelle']}")
        raise SystemExit
    bekannt = {b["name"] for b in BESTAENDE}
    unbekannt = set(a.bestand) - bekannt
    if unbekannt:
        raise SystemExit(f"unbekannt: {', '.join(sorted(unbekannt))}\n"
                         f"bekannt:   {', '.join(sorted(bekannt))}")
    baue(set(a.bestand), a.max_mb)
