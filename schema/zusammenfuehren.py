import re
import sys
from pathlib import Path

MODULE = Path("module")
ZIEL = Path("stkg-schema.ttl")
KOPF = MODULE / "00_kopf.ttl"

ANFANG = "# <<< MODULKOPF"
ENDE = "# MODULKOPF >>>"


GRUNDMUSTER = {
    "stkg:Ereignis", "stkg:Beobachtung",
    "stkg:Episode", "stkg:Stand",
}


OHNE_MUSTER_DAUERHAFT = {


    "stkg:Wahlprogramm",


    "stkg:Deskriptor", "stkg:Domaene", "stkg:RileSeite", "stkg:Themenkategorie", "stkg:Fraktion", "stkg:Ressort",

    "stkg:Ort", "stkg:Geometrie",


    "stkg:KartogrammGeometrie",


    "stkg:Merkmal", "stkg:Dimension", "stkg:Kategorie",

    "stkg:Person", "stkg:Organisation", "stkg:Partei", "stkg:Amt",


    "stkg:Kennung", "stkg:Konto", "stkg:Plattform", "stkg:Webadresse",


    "stkg:Parteischreibweise", "stkg:Fraktionsschreibweise",

    "stkg:Sachgebiet",
}


OHNE_MUSTER_VERBINDUNG = {


    "stkg:Kandidatur", "stkg:Nebentaetigkeit", "stkg:EntschuldigteAbwesenheit",


    "stkg:Urheberangabe", "stkg:Positionsurheber", "stkg:Dokumenturheber", "stkg:Reaktionsurheber", "stkg:Reaktionsblock", "stkg:Ressortzuordnung", "stkg:Vorgangsverweis",


    "stkg:Filiation", "stkg:Umrechnung", "stkg:Nachbarschaft",

    "stkg:Namensvariante",

    "stkg:Stimmabgabe", "stkg:Reaktion", "stkg:Tagesordnungspunkt",
}


OHNE_MUSTER_CODELISTE = {


    "stkg:Abwesenheitsgrund", "stkg:Aktivitaetsart", "stkg:Beratungsstand", "stkg:Deskriptortyp", "stkg:Fraktionsrolle", "stkg:Gebietsart", "stkg:Kategorienart", "stkg:Urheberart", "stkg:Urheberumfang",

    "stkg:Herkunftsart", "stkg:Eingriffsart",

    "stkg:Aggregationsart", "stkg:Filiationsart", "stkg:Filiationsgrund",
    "stkg:Zugehoerigkeitsart", "stkg:Einheitsart",

    "stkg:Zuordnungsverfahren", "stkg:Bezirksart",

    "stkg:Variantentyp", "stkg:Adressart", "stkg:Kennungssystem",
    "stkg:Verortungsgenauigkeit",

    "stkg:Gremienrolle", "stkg:Mandatstyp",
    "stkg:Fraktionsart",

    "stkg:Taetigkeitskategorie",

    "stkg:Reaktionsart", "stkg:Rednerrolle",
    "stkg:Vorgangstyp", "stkg:Votum", "stkg:Thema",
}


OHNE_MUSTER_METADATEN = {
    "stkg:Datenlieferung", "stkg:Herausgeber",


    "stkg:Eingriff",
}


OHNE_MUSTER = (OHNE_MUSTER_DAUERHAFT | OHNE_MUSTER_VERBINDUNG
               | OHNE_MUSTER_CODELISTE | OHNE_MUSTER_METADATEN)


def erbt_grundmuster(klasse, oberklassen):
    gesehen, offen = set(), list(oberklassen.get(klasse, ()))
    while offen:
        k = offen.pop()
        if k in GRUNDMUSTER:
            return True
        if k in gesehen:
            continue
        gesehen.add(k)
        offen.extend(oberklassen.get(k, ()))
    return False

def rumpf(text):
    if ENDE in text:
        return text.split(ENDE, 1)[1].lstrip("\n")
    return text


def zerlege(text):
    ohne = "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))
    return [s.strip() for s in re.split(r"\.\s*\n", ohne) if s.strip()]


def lies(stmt):
    m = re.match(r"^(\S+)\s+(.*)$", stmt, re.S)
    if not m or not m.group(1).startswith("stkg:"):
        return None, {}
    paare = {}
    for stueck in re.split(r";\s*", m.group(2)):
        stueck = stueck.strip()
        m2 = re.match(r"^(\S+)\s+(.*)$", stueck, re.S)
        if not m2:
            continue
        praedikat, objekt = m2.group(1), m2.group(2).strip()
        if objekt.startswith('"'):
            paare.setdefault(praedikat, []).append(objekt)
        else:
            for einzeln in re.split(r"\s*,\s*", objekt):
                if einzeln.strip():
                    paare.setdefault(praedikat, []).append(einzeln.strip())
    return m.group(1), paare


def pruefe(text):
    klassen, kanten, instanzen, oberklassen = {}, {}, [], {}
    benutzt = set()
    doppelt = []

    for stmt in zerlege(text):
        subj, p = lies(stmt)
        if not subj:
            continue
        typen = p.get("a", [])
        hat_label = "rdfs:label" in p

        if "owl:Class" in typen:
            if subj in klassen:
                doppelt.append(f"Klasse {subj} mehrfach deklariert")
            klassen[subj] = hat_label
            oberklassen[subj] = [o for o in p.get("rdfs:subClassOf", [])
                                 if o.startswith("stkg:")]
        elif any(t in typen for t in ("owl:ObjectProperty", "owl:DatatypeProperty")):
            if subj in kanten:
                doppelt.append(f"Kante {subj} mehrfach deklariert")
            kanten[subj] = {
                "objekt": "owl:ObjectProperty" in typen,
                "domain": p.get("rdfs:domain", [None])[0],
                "range": p.get("rdfs:range", [None])[0],
                "label": hat_label,
            }
        else:
            for t in typen:
                if t.startswith("stkg:"):
                    instanzen.append((subj, t))

        for pred in ("rdfs:domain", "rdfs:range", "rdfs:subClassOf"):
            for o in p.get(pred, []):
                if o.startswith("stkg:"):
                    benutzt.add(o)

    fehler = list(doppelt)
    for k in sorted(benutzt - set(klassen)):
        fehler.append(f"{k} wird benutzt, ist aber nicht als Klasse deklariert")
    for name, kl in sorted(instanzen):
        if kl not in klassen:
            fehler.append(f"Instanz {name} gehoert zur unbekannten Klasse {kl}")
    for name, e in sorted(kanten.items()):
        if not e["domain"]:
            fehler.append(f"Kante {name} hat keine Domain")
        if e["objekt"] and not e["range"]:
            fehler.append(f"Objekt-Kante {name} hat keine Range")
        if not e["label"]:
            fehler.append(f"Kante {name} hat kein Label")
    for name, lbl in sorted(klassen.items()):
        if not lbl:
            fehler.append(f"Klasse {name} hat kein Label")

    for name in sorted(klassen):
        if name in GRUNDMUSTER or name in OHNE_MUSTER:
            continue
        if not erbt_grundmuster(name, oberklassen):
            fehler.append(
                f"Klasse {name} erbt kein Grundmuster und steht nicht in " "OHNE_MUSTER -- Zuordnung entscheiden oder dort vermerken")
    for name in sorted(OHNE_MUSTER - set(klassen)):
        fehler.append(f"{name} steht in OHNE_MUSTER, ist aber keine Klasse mehr")

    return klassen, kanten, instanzen, oberklassen, fehler


def main():
    if not KOPF.exists():
        sys.exit(f"{KOPF} fehlt -- aus dem Verzeichnis schema starten.")

    teile = [KOPF.read_text(encoding="utf-8").rstrip("\n")]
    module = sorted(p for p in MODULE.glob("*.ttl") if p != KOPF)
    for m in module:
        teile.append(rumpf(m.read_text(encoding="utf-8")).rstrip("\n"))

    ganz = "\n\n\n".join(teile) + "\n"
    ZIEL.write_text(ganz, encoding="utf-8")

    klassen, kanten, instanzen, _ober, fehler = pruefe(ganz)
    print(f"{len(module)} Module -> {ZIEL} ({len(ganz.splitlines())} Zeilen)")
    print(f"{len(klassen)} Klassen, {len(kanten)} Kanten, "
          f"{len(instanzen)} Codelisten-Instanzen")
    if fehler:
        print(f"\n{len(fehler)} Beanstandungen:")
        for f in fehler:
            print(" " + f)
        sys.exit(1)
    print("Keine Beanstandungen.")


if __name__ == "__main__":
    main()
