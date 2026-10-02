import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "03_load_db" / "wahlkreise"))
sys.path.insert(0, str(REPO / "03_load_db" / "meta"))

from load_wahlkreise import query
from load_eingriff import EINGRIFFE

BASIS  = "https://skg-bundestag.de/"
UPDATE = pfade.METADATEN / "eingriff_knoten_update.ru"
TRIG   = pfade.METADATEN / "eingriff_knoten.trig"

PRAEFIXE = [("stkg", "https://skg-bundestag.de/schema#")]


AUFLOESBAR = {


    "E1": {
        "tabelle": "politiker_innen.mandat",
        "spalte":  "wkr_herkunft",
        "wert":    "amtlich_ergaenzt",
        "felder":  ["aw_id"],
        "iri":     "mandat/{aw_id}",
    },
    "E2b": {
        "tabelle": """(SELECT aw_id FROM politiker_innen.mandat
                        WHERE wkr_herkunft = 'korrigiert'
                          AND wkr_nr IS NULL
                          AND aw_id <> 43944) x""",
        "spalte":  "aw_id",
        "wert":    None,
        "felder":  ["aw_id"],
        "iri":     "mandat/{aw_id}",
    },
    "E6": {
        "tabelle": """(SELECT aw_id FROM politiker_innen.mandat
                        WHERE aw_id IN (62904, 53558, 43944)) x""",
        "spalte":  "aw_id",
        "wert":    None,
        "felder":  ["aw_id"],
        "iri":     "mandat/{aw_id}",
    },

    "E1b": {
        "tabelle": "politiker_innen.mandat",
        "spalte":  "mandatsart_herkunft",
        "wert":    "amtlich_ergaenzt",
        "felder":  ["aw_id"],
        "iri":     "mandat/{aw_id}",
    },
    "E1c": {
        "tabelle": "politiker_innen.mandat",
        "spalte":  "mandatsart_herkunft",
        "wert":    "amtlich_ersetzt",
        "felder":  ["aw_id"],
        "iri":     "mandat/{aw_id}",
    },


    "E2e": {
        "tabelle": "politiker_innen.kandidatur",
        "spalte":  "liste_herkunft",
        "wert":    "amtlich_ergaenzt",
        "felder":  ["aw_id"],
        "iri":     "kandidatur/{aw_id}",
    },
    "E2f": {
        "tabelle": "politiker_innen.kandidatur",
        "spalte":  "liste_herkunft",
        "wert":    "abgeleitet",
        "felder":  ["aw_id"],
        "iri":     "kandidatur/{aw_id}",
    },
    "E13": {
        "tabelle": "politiker_innen.kandidatur",
        "spalte":  "wkr_herkunft",
        "wert":    "platzhalter",
        "felder":  ["aw_id"],
        "iri":     "kandidatur/{aw_id}",
    },
    "E15": {


        "tabelle": """(SELECT c.aw_id
                         FROM politiker_innen.kandidatur c
                         JOIN politiker_innen.mandat m ON m.aw_id = c.mandat_id
                        WHERE c.listenplatz IS NULL
                          AND m.listenplatz IS NOT NULL
                          AND c.wahl ~ '[0-9]{4}') x""",
        "spalte":  "aw_id",
        "wert":    None,
        "felder":  ["aw_id"],
        "iri":     "kandidatur/{aw_id}",
    },


    "E8": {
        "tabelle": """(SELECT k.person
                         FROM politiker_innen.politician p
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw' AND k.kennung = p.aw_id::text
                        WHERE p.year_of_birth_herkunft = 'korrigiert') x""",
        "spalte":  "person",
        "wert":    None,
        "felder":  ["person"],
        "iri":     "person/{person}",
    },


    "E14": {
        "tabelle": """(SELECT k.person
                         FROM politiker_innen.geburtsort g
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw' AND k.kennung = g.aw_id::text
                        WHERE g.herkunft_ort = 'korrigiert') x""",
        "spalte":  "person",
        "wert":    None,
        "felder":  ["person"],
        "iri":     "person/{person}",
    },


    "E2a": {
        "tabelle": """(SELECT 'mandat' AS art, aw_id FROM politiker_innen.mandat
                        WHERE liste_herkunft = 'korrigiert'
                       UNION ALL
                       SELECT 'kandidatur', aw_id FROM politiker_innen.kandidatur
                        WHERE liste_herkunft = 'korrigiert') x""",
        "spalte":  "aw_id", "wert": None,
        "felder":  ["art", "aw_id"],
        "iri":     "{art}/{aw_id}",
    },


    "E9": {
        "tabelle": """(SELECT k.person
                         FROM politiker_innen.geburtsort g
                         JOIN parlamentsarbeit.person_kennung k
                           ON k.system = 'aw' AND k.kennung = g.aw_id::text
                        WHERE g.ort_qid IN ('Q878458','Q232','Q1023313')) x""",
        "spalte":  "person", "wert": None,
        "felder":  ["person"],
        "iri":     "person/{person}",
    },


    "E7a": {
        "tabelle": """(SELECT aw_id FROM politiker_innen.kandidatur
                        WHERE wkr_herkunft = 'korrigiert') x""",
        "spalte":  "aw_id", "wert": None,
        "felder":  ["aw_id"],
        "iri":     "kandidatur/{aw_id}",
    },


    "R1": {


        "tabelle": """(SELECT indikator_id, ags, wahl
                         FROM strukturdaten.gemeinde_regional_wahltag
                        WHERE herkunft = 'vorjahr_gebietsaenderung'
                          AND wert IS NOT NULL) x""",
        "spalte":  "ags", "wert": None,
        "felder":  ["indikator_id", "ags", "wahl"],
        "iri":     "beobachtung/regional_{indikator_id}/{ags}_{wahl}",
    },


    "P1": {
        "quelle":  "korrekturen",
        "auswahl": "kennung_ersetzt",
        "iri":     "rede/{rede_id}",
    },
    "P2": {
        "quelle":  "korrekturen",
        "auswahl": "kennung_ergaenzt",
        "iri":     "rede/{rede_id}",
    },
    "P3": {
        "quelle":  "korrekturen",
        "auswahl": "interne_kennung",
        "iri":     "rede/{rede_id}",
    },
    "P4": {
        "quelle":  "korrekturen",
        "auswahl": "name",
        "iri":     "rede/{rede_id}",
    },
    "P5": {
        "quelle":  "korrekturen",
        "auswahl": "behelfskennung",
        "iri":     "rede/{rede_id}",
    },


    "E10": {
        "tabelle": """(SELECT g.wahljahr, g.ags, g.wkr_nr
                         FROM raum.gemeinde_wahlkreis_wahltag g
                         JOIN raum.gemeinde_aufnahme a
                           ON a.ags = g.ags AND a.wahljahr = g.wahljahr
                        WHERE g.herkunft = 'aufnahme'
                          AND a.herkunft LIKE 'Zusammenlegung ganzer%') x""",
        "spalte":  "ags",
        "wert":    None,
        "felder":  ["wahljahr", "ags", "wkr_nr"],
        "iri":     "zugehoerigkeit/gemeinde_wahlkreis/{wahljahr}_{ags}_{wkr_nr}",
    },
    "E11a": {
        "tabelle": """(SELECT wahljahr, ags, wkr_nr
                         FROM raum.gemeinde_wahlkreis_wahltag
                        WHERE herkunft = 'aufnahme' AND wahljahr = 2013) x""",
        "spalte":  "ags", "wert": None,
        "felder":  ["wahljahr", "ags", "wkr_nr"],
        "iri":     "zugehoerigkeit/gemeinde_wahlkreis/{wahljahr}_{ags}_{wkr_nr}",
    },
    "E11b": {
        "tabelle": """(SELECT wahljahr, ags, wkr_nr
                         FROM raum.gemeinde_wahlkreis_wahltag
                        WHERE herkunft = 'aufnahme' AND wahljahr = 2017) x""",
        "spalte":  "ags", "wert": None,
        "felder":  ["wahljahr", "ags", "wkr_nr"],
        "iri":     "zugehoerigkeit/gemeinde_wahlkreis/{wahljahr}_{ags}_{wkr_nr}",
    },
    "E11c": {
        "tabelle": """(SELECT g.wahljahr, g.ags, g.wkr_nr
                         FROM raum.gemeinde_wahlkreis_wahltag g
                         LEFT JOIN raum.gemeinde_aufnahme a
                           ON a.ags = g.ags AND a.wahljahr = g.wahljahr
                          AND a.herkunft LIKE 'Zusammenlegung ganzer%'
                        WHERE g.herkunft = 'aufnahme' AND g.wahljahr = 2021
                          AND a.ags IS NULL) x""",
        "spalte":  "ags", "wert": None,
        "felder":  ["wahljahr", "ags", "wkr_nr"],
        "iri":     "zugehoerigkeit/gemeinde_wahlkreis/{wahljahr}_{ags}_{wkr_nr}",
    },
    "E12": {


        "tabelle": """(SELECT wahljahr, ags, wkr_nr
                         FROM raum.gemeinde_wahlkreis_wahltag
                        WHERE herkunft = 'aufnahme' AND wahljahr = 2021
                          AND ags IN ('01054039','07232117','07232121')) x""",
        "spalte":  "ags", "wert": None,
        "felder":  ["wahljahr", "ags", "wkr_nr"],
        "iri":     "zugehoerigkeit/gemeinde_wahlkreis/{wahljahr}_{ags}_{wkr_nr}",
    },
    "G1": {
        "tabelle": "raum.gemeinde_wahlkreis_wahltag",
        "spalte":  "herkunft",
        "wert":    "eingriff_vg1000",
        "felder":  ["wahljahr", "ags", "wkr_nr"],
        "iri":     "zugehoerigkeit/gemeinde_wahlkreis/{wahljahr}_{ags}_{wkr_nr}",
    },
}


KEIN_KNOTEN = {
    "E2c": "entfernte Zeile -- steht nicht im Graphen",
    "E3":  "entfernte/ersetzte Zeile -- Rieder 2013 geht in Ballenstedt auf",
    "E4":  "ersetzte Zeile -- Langelsheim 2021 aus vier Vorgaengern",
    "E5":  "entfernte Zeile -- Fusionsschluessel ist keine Gemeinde des Wahltags",
    "E7b": "entfernte Zeilen -- drei Kandidaturen, die es so nicht gab",
    "I1":  "geleerte Werte -- die Zeilen fehlen, es gibt keinen Knoten",
}

ZUORDNUNG_OFFEN = {
}


def iri(pfad):
    return "<" + BASIS + pfad + ">"


def lieferung_je_eingriff():
    return {e["eingriff_id"]: e["lieferung_id"] for e in EINGRIFFE}


def faelle_je_eingriff():
    return {e["eingriff_id"]: e.get("faelle") for e in EINGRIFFE}


def rede_ids(auswahl):
    sys.path.insert(0, str(REPO / "lib"))
    import korrekturen as K

    if auswahl == "kennung_ersetzt":


        return [r for r, w in K.KENNUNG_KORREKTUR.items() if str(w[0]).strip()]
    if auswahl == "kennung_ergaenzt":

        return [r for r, w in K.KENNUNG_KORREKTUR.items() if not str(w[0]).strip()]
    if auswahl == "interne_kennung":
        return list(K.INTERNE_KENNUNG)
    if auswahl == "name":
        return list(K.NAME_KORREKTUR) + list(K.NAME_VERSCHMOLZEN)
    if auswahl == "behelfskennung":


        alle = list(K.BEHELFSKENNUNG) + list(K.BEHELFSKENNUNG_REGIERUNG)
        liste = ",".join("'%s'" % k for k in alle)
        return [z[0] for z in query(
            "SELECT rede_id FROM parlamentsarbeit.rede " "WHERE redner_id IN (%s) ORDER BY rede_id" % liste)]
    raise ValueError(f"unbekannte Auswahl {auswahl!r}")


def hole_knoten(kennung, regel):
    if regel.get("quelle") == "korrekturen":
        return [iri(regel["iri"].format(rede_id=r))
                for r in sorted(rede_ids(regel["auswahl"]))]
    felder = ", ".join(regel["felder"])
    if regel["wert"] is None:
        sql = "SELECT %s FROM %s ORDER BY %s" % (felder, regel["tabelle"], felder)
    else:
        sql = ("SELECT %s FROM %s WHERE %s = '%s' ORDER BY %s"
               % (felder, regel["tabelle"], regel["spalte"],
                  regel["wert"].replace("'", "''"), felder))
    knoten = []
    for zeile in query(sql):
        werte = {}
        for name, wert in zip(regel["felder"], zeile):


            werte[name] = str(wert)
        knoten.append(iri(regel["iri"].format(**werte)))
    return knoten


def schreibe_update(gefunden):
    lieferung = lieferung_je_eingriff()
    zeilen = [f"PREFIX {p}: <{u}>" for p, u in PRAEFIXE] + [""]

    for kennung, knoten in gefunden.items():
        graph = iri("lieferung/" + lieferung[kennung])
        subjekt = iri("eingriff/" + kennung)
        zeilen += [
            f"# {'=' * 66}",
            f"# {kennung} -- {len(knoten)} betroffene Knoten",
            f"# {'=' * 66}",
            "",
            f"DELETE {{ GRAPH {graph} {{ {subjekt} stkg:betrifftKnoten ?o }} }}",
            f"WHERE  {{ GRAPH {graph} {{ {subjekt} stkg:betrifftKnoten ?o }} }} ;",
            "",
            f"INSERT DATA {{ GRAPH {graph} {{",
        ]
        for ziel in knoten:
            zeilen.append(f"    {subjekt} stkg:betrifftKnoten {ziel} .")
        zeilen += ["} } ;", ""]

    pfade.pruefe(pfade.METADATEN)
    UPDATE.write_text("\n".join(zeilen), encoding="utf-8")


def schreibe_trig(gefunden):
    lieferung = lieferung_je_eingriff()
    zeilen = [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE] + [""]

    for kennung, knoten in gefunden.items():
        graph = iri("lieferung/" + lieferung[kennung])
        subjekt = iri("eingriff/" + kennung)
        zeilen += [
            f"# {'=' * 66}",
            f"# {kennung} -- {len(knoten)} betroffene Knoten",
            f"# {'=' * 66}",
            "",
            f"{graph} {{",
        ]
        for ziel in knoten:
            zeilen.append(f"    {subjekt} stkg:betrifftKnoten {ziel} .")
        zeilen += ["}", ""]

    pfade.pruefe(pfade.METADATEN)
    TRIG.write_text("\n".join(zeilen), encoding="utf-8")


def main():
    soll = faelle_je_eingriff()
    gefunden = OrderedDict()
    abweichung = []

    print("Betroffene Knoten je Eingriff\n")
    for kennung in sorted(AUFLOESBAR):
        knoten = hole_knoten(kennung, AUFLOESBAR[kennung])
        gefunden[kennung] = knoten
        erwartet = soll.get(kennung)
        mark = ""
        if erwartet is not None and erwartet != len(knoten):
            mark = f"   <== Register nennt {erwartet}"
            abweichung.append((kennung, erwartet, len(knoten)))
        regel = AUFLOESBAR[kennung]


        if regel.get("quelle") == "korrekturen":
            woher = f"lib/korrekturen.py -- {regel['auswahl']}"
        elif regel["wert"] is not None:
            woher = f"{regel['tabelle']}.{regel['spalte']} = '{regel['wert']}'"
        else:
            woher = f"Join auf {regel['spalte']}"
        print("    %-5s %6d Knoten   %s%s"
              % (kennung, len(knoten), woher, mark))

    schreibe_update(gefunden)
    schreibe_trig(gefunden)
    gesamt = sum(len(k) for k in gefunden.values())
    print(f"\n{gesamt} Kanten stkg:betrifftKnoten fuer {len(gefunden)} "
          f"Eingriffe")
    print(f"  {UPDATE.name} ({UPDATE.stat().st_size/1024:.1f} kB)")
    print(f"  {TRIG.name} ({TRIG.stat().st_size/1024:.1f} kB)")

    if abweichung:
        print(f"\n{len(abweichung)} Eingriffe weichen von der Registerzahl ab "
              f"-- geschrieben ist die gemessene Zahl, das Register ist die "
              f"Behauptung:")
        for kennung, erwartet, ist in abweichung:
            print(f"    {kennung}: Register {erwartet}, im Bestand {ist}")

    print(f"\n{len(KEIN_KNOTEN)} Eingriffe brauchen keinen Knoten -- die "
          f"Zeile steht nicht im Graphen:")
    for kennung, grund in sorted(KEIN_KNOTEN.items()):
        print(f"    {kennung:<5} {grund}")

    print(f"\n{len(ZUORDNUNG_OFFEN)} Eingriffe bleiben OFFEN -- der Bestand "
          f"sagt nicht, welche Zeile zu welchem gehoert:")
    for kennung, grund in sorted(ZUORDNUNG_OFFEN.items()):
        print(f"    {kennung:<5} {grund}")

    print("\nLaden ZULETZT, nach eingriff_update.ru.")


if __name__ == "__main__":
    main()
