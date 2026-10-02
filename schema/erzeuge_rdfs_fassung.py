import re
import sys
from pathlib import Path

QUELLE = Path("stkg-schema.ttl")
ZIEL = Path("stkg-schema-rdfs.ttl")


ERSETZUNGEN = [
    (re.compile(r"(\ba\s+)owl:Class\b"), r"\1rdfs:Class"),
    (re.compile(r"(\ba\s+)owl:ObjectProperty\b"), r"\1rdf:Property"),
    (re.compile(r"(\ba\s+)owl:DatatypeProperty\b"), r"\1rdf:Property"),
]

XSD = re.compile(r"rdfs:range\s+xsd:")


def zaehle(text, muster):
    return len(re.findall(muster, text))


def kopf_umschreiben(text):
    text = text.replace("a owl:Ontology ;", "a dcterms:Standard ;")
    text = re.sub(r"owl:versionInfo\s+", "dcterms:hasVersion ", text)
    return text


def main():
    if not QUELLE.is_file():
        raise SystemExit(f"Quelle fehlt: {QUELLE.resolve()}")

    text = QUELLE.read_text(encoding="utf-8")

    vorher = {
        "owl:Class": zaehle(text, r"\ba\s+owl:Class\b"),
        "owl:ObjectProperty": zaehle(text, r"\ba\s+owl:ObjectProperty\b"),
        "owl:DatatypeProperty": zaehle(text, r"\ba\s+owl:DatatypeProperty\b"),
    }

    neu = kopf_umschreiben(text)
    for muster, ersatz in ERSETZUNGEN:
        neu = muster.sub(ersatz, neu)


    rest = [z for z in neu.splitlines()
            if "owl:" in z and not z.lstrip().startswith(("#", "@prefix owl"))]
    if not rest:
        neu = "\n".join(z for z in neu.splitlines()
                        if not z.startswith("@prefix owl:"))


    hinweis = (
        "# RDFS-FASSUNG -- erzeugt aus stkg-schema.ttl mit\n" "# erzeuge_rdfs_fassung.py. Inhaltlich gleichbedeutend; die\n" "# Typdeklarationen stehen hier in den Begriffen von RDF Schema\n" "# statt in denen von OWL. Nicht von Hand bearbeiten.\n" "#\n"
    )
    neu = hinweis + neu

    ZIEL.write_text(neu, encoding="utf-8")

    offen = zaehle(neu, r"\bowl:")
    ohne_range = 0
    for block in re.split(r"\.\s*\n", neu):
        if re.search(r"\ba\s+rdf:Property\b", block) and "rdfs:range" not in block:
            ohne_range += 1

    print(f"{ZIEL} geschrieben")
    print(f"  {vorher['owl:Class']:4d} owl:Class            -> rdfs:Class")
    print(f"  {vorher['owl:ObjectProperty']:4d} owl:ObjectProperty   -> rdf:Property")
    print(f"  {vorher['owl:DatatypeProperty']:4d} owl:DatatypeProperty -> rdf:Property")
    print(f"  {offen:4d} verbliebene owl:-Vorkommen")
    print(f"  {ohne_range:4d} Eigenschaften ohne Wertebereich "
          f"(dort ist Knoten/Literal nicht ablesbar)")

    if offen:
        print("\n  Verbliebene Stellen:", file=sys.stderr)
        for nr, zeile in enumerate(neu.splitlines(), 1):
            if "owl:" in zeile and not zeile.lstrip().startswith("#"):
                print(f"    {nr}: {zeile.strip()[:90]}", file=sys.stderr)


if __name__ == "__main__":
    main()
