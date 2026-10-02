import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

REPO = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(REPO / "03_load_db" / "meta"))

from load_eingriff import EINGRIFFE

BASIS  = "https://skg-bundestag.de/"
ZIEL   = pfade.METADATEN / "eingriff.trig"
UPDATE = pfade.METADATEN / "eingriff_update.ru"


SCHEMA = REPO / "schema" / "stkg-schema.ttl"

PRAEFIXE = [
    ("stkg",    "https://skg-bundestag.de/schema#"),
    ("dcterms", "http://purl.org/dc/terms/"),
    ("prov",    "http://www.w3.org/ns/prov#"),
    ("xsd",     "http://www.w3.org/2001/XMLSchema#"),
]


EINGRIFFSART = {
    "ergaenzt": "stkg:eingriff_ergaenzt",
    "ersetzt":  "stkg:eingriff_ersetzt",
    "entfernt": "stkg:eingriff_entfernt",
    "geleert":  "stkg:eingriff_geleert",
}


def txt(wert):
    s = str(wert)
    for such, ersatz in (("\\", "\\\\"), ('"', '\\"'),
                         ("\n", "\\n"), ("\r", ""), ("\t", "\\t")):
        s = s.replace(such, ersatz)
    return f'"{s}"'


def iri(*teile):
    return "<" + BASIS + "/".join(str(t) for t in teile) + ">"


def kanten_im_schema():
    if not SCHEMA.exists():
        return None
    text = SCHEMA.read_text(encoding="utf-8")
    return set(re.findall(
        r"^(stkg:\w+)\s+a\s+owl:(?:Object|Datatype|Annotation)Property",
        text, re.MULTILINE))


KANTEN = kanten_im_schema()


def tripel_des_eingriffs(eintrag, unbekannt):


    aus = [("a", "stkg:Eingriff, prov:Activity"),


           ("stkg:greiftEinIn",   iri("lieferung", eintrag["lieferung_id"]))]

    art = eintrag.get("art")
    if art in EINGRIFFSART:
        aus.append(("stkg:hatEingriffsart", EINGRIFFSART[art]))
    else:
        unbekannt.append(f"{eintrag['eingriff_id']}: Art {art!r} steht in "
                         f"keiner Codeliste")

    if eintrag.get("begruendung"):
        aus.append(("stkg:eingriffBegruendung", txt(eintrag["begruendung"])))

    if eintrag.get("faelle") is not None:
        aus.append(("stkg:eingriffFaelle",
                    f'"{eintrag["faelle"]}"^^xsd:integer'))

    kante = eintrag.get("betrifft_kante")
    if kante:
        if KANTEN is not None and kante not in KANTEN:
            unbekannt.append(f"{eintrag['eingriff_id']}: betrifft_kante "
                             f"{kante!r} ist im Schema nicht deklariert")
        aus.append(("stkg:betrifftKante", kante))


    if eintrag.get("fundstelle"):
        aus.append(("dcterms:source", txt(eintrag["fundstelle"])))

    return aus


def block(kennung, tripel, einzug=" "):
    breite = max(len(k) for k, _ in tripel)
    zeilen = [f"{einzug}    {k:<{breite}}  {o}" for k, o in tripel]
    return f"{einzug}{kennung}\n" + " ;\n".join(zeilen) + " ."


def nach_lieferung():
    gruppen = OrderedDict()
    for eintrag in EINGRIFFE:
        gruppen.setdefault(eintrag["lieferung_id"], []).append(eintrag)
    return gruppen


def schreibe_trig(gruppen, unbekannt):
    zeilen = [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE] + [""]
    for lieferung, eintraege in gruppen.items():
        zeilen += [f"# {'=' * 66}",
                   f"# {lieferung} -- {len(eintraege)} Eingriff(e)",
                   f"# {'=' * 66}",
                   "",
                   f"{iri('lieferung', lieferung)} {{",
                   ""]
        for eintrag in eintraege:
            zeilen.append(block(iri("eingriff", eintrag["eingriff_id"]),
                                tripel_des_eingriffs(eintrag, unbekannt)))
            zeilen.append("")
        zeilen += ["}", ""]
    pfade.pruefe(pfade.METADATEN)
    ZIEL.write_text("\n".join(zeilen), encoding="utf-8")


def schreibe_update(gruppen):
    zeilen = [f"PREFIX {p}: <{u}>" for p, u in PRAEFIXE] + [""]
    for lieferung, eintraege in gruppen.items():
        graph = iri("lieferung", lieferung)
        zeilen += [f"# {'=' * 66}", f"# {lieferung}", f"# {'=' * 66}", ""]
        for eintrag in eintraege:
            kennung = iri("eingriff", eintrag["eingriff_id"])
            zeilen += [
                f"DELETE {{ GRAPH {graph} {{ {kennung} ?p ?o }} }}",
                f"WHERE  {{ GRAPH {graph} {{ {kennung} ?p ?o }} }} ;",
                "",
                f"INSERT DATA {{ GRAPH {graph} {{",
                block(kennung, tripel_des_eingriffs(eintrag, [])),
                "} } ;",
                "",
            ]
    pfade.pruefe(pfade.METADATEN)
    UPDATE.write_text("\n".join(zeilen), encoding="utf-8")


def main():
    unbekannt = []
    gruppen = nach_lieferung()
    schreibe_trig(gruppen, unbekannt)
    schreibe_update(gruppen)

    print(f"{len(EINGRIFFE)} Eingriffe in {len(gruppen)} Lieferungsgraphen")
    print(f"  {ZIEL.name} ({ZIEL.stat().st_size/1024:.1f} kB), {UPDATE.name}")
    for lieferung, eintraege in gruppen.items():
        kennungen = ", ".join(e["eingriff_id"] for e in eintraege)
        print(f"    {lieferung:<30} {kennungen}")

    if KANTEN is None:
        print(f"\n  betrifft_kante NICHT geprueft - {SCHEMA.name} fehlt")

    ohne_kante = [e["eingriff_id"] for e in EINGRIFFE
                  if not e.get("betrifft_kante")]
    if ohne_kante:
        print(f"\n{len(ohne_kante)} ohne betrifft_kante - der Eingriff sagt "
              f"dann nicht, welche Aussage er veraendert hat:")
        print(" " + ", ".join(ohne_kante))

    ohne_zahl = [e["eingriff_id"] for e in EINGRIFFE
                 if e.get("faelle") is None]
    if ohne_zahl:
        print(f"\n{len(ohne_zahl)} ohne Fallzahl:")
        print(" " + ", ".join(ohne_zahl))

    offen = [(e["eingriff_id"], e["zu_klaeren"]) for e in EINGRIFFE
             if e.get("zu_klaeren")]
    if offen:
        print(f"\n{len(offen)} mit offener Frage - steht nicht im Graphen, "
              f"nur hier:")
        for kennung, frage in offen:
            print(f"    {kennung}: {frage}")

    if unbekannt:
        print(f"\n{len(unbekannt)} Beanstandungen:")
        for zeile in unbekannt:
            print(f"    {zeile}")

    print("\nLaden ZULETZT, nach den Sachdaten und den Metadaten: " "lade_in_graphdb.py leert je Lieferung ihren Graphen.")


if __name__ == "__main__":
    main()
