import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

REPO = Path(__file__).resolve().parents[1]
from db import run_copy

BASIS = "https://skg-bundestag.de/"


LIEFERUNG = "bbsr_raumgliederung"
LIEFERUNG_INKAR = "bbsr_inkar_2024"
AUSGABE   = pfade.BEOBACHTUNGEN


STAND = "2021-12-31"


WAHLJAHRE = (2013, 2017, 2021)


AGGREGATIONSART = {
    "VWG": "stkg:aggregation_gemeindeverband",
    "GMB": "stkg:aggregation_mittelbereich",
    "KKR": "stkg:aggregation_kreisregion",
    "GSL": "stkg:aggregation_stadt_land_region",
    "KAM": "stkg:aggregation_arbeitsmarktregion",
    "KRO": "stkg:aggregation_raumordnungsregion",
    "GIB": "stkg:aggregation_ihk_bezirk",
    "GSR": "stkg:aggregation_regiostar_stadtregion",
    "GGR": "stkg:aggregation_grossstadtregion",
    "GVR": "stkg:aggregation_verdichtungsraum",
    "KBN": "stkg:aggregation_braunkohlerevier",
}


BEZUGSRAUM = {
    "DUV": "VWG",
    "RBV": "VWG",
    "RLV": "VWG",
    "SAM": "KAM",
    "WSA": "KAM",
    "SSL": "GSL",
    "WSL": "GSL",
}


NUR_AUF_KREISEBENE = {"KGN", "KSU", "KTU", "RLK", "RTU", "SLT"}


GESCHRIEBEN = set()


OHNE_BEZUGSRAUM = set()

PRAEFIXE = [
    ("stkg", "https://skg-bundestag.de/schema#"),
    ("xsd",  "http://www.w3.org/2001/XMLSchema#"),
]

BESTAENDE = [
    {
        "name": "typisierung_gemeinde",
        "tabelle": "strukturdaten.gemeinde_typisierung",
        "schluessel": "ags",
        "raumbezug": "gemeindestand/{schluessel}_" + STAND,
        "ebene": "Gemeinde",
    },
    {
        "name": "indikator_gemeinde",
        "art": "indikator",
        "lieferung": LIEFERUNG_INKAR,
        "tabelle": "strukturdaten.gemeinde_indikator",
        "schluessel": "ags",
        "raumbezug": "gemeindestand/{schluessel}_" + STAND,
        "ebene": "Gemeinde",
    },
    {
        "name": "typisierung_kreis",
        "tabelle": "strukturdaten.kreis_typisierung",
        "schluessel": "kreis",
        "raumbezug": "kreisstand/{schluessel}_" + STAND,
        "ebene": "Kreis",
    },
    {


        "name": "indikator_kreis",
        "art": "indikator",
        "lieferung": LIEFERUNG_INKAR,
        "tabelle": "strukturdaten.kreis_indikator",
        "schluessel": "kreis",
        "raumbezug": "kreisstand/{schluessel}_" + STAND,
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


def sql(bestand):
    s = bestand["schluessel"]
    if bestand.get("art") == "indikator":


        return f"""
        SELECT g.{s}::text AS schluessel, g.indikator_id::text AS merkmal,
               g.jahr::text AS jahr, g.wert::text AS wert,
               i.indikator::text AS bezeichnung, i.bereich::text AS bereich
        FROM {bestand['tabelle']} g
        JOIN strukturdaten.indikator i USING (indikator_id)
        WHERE g.wert IS NOT NULL
          AND g.jahr IN ({", ".join(str(j) for j in WAHLJAHRE)})
        """


    zuordnung = ", ".join(f"('{typ}','{glied}')"
                          for typ, glied in sorted(BEZUGSRAUM.items()))
    bezug = ""
    if bestand["schluessel"] == "ags":
        bezug = f"""
    LEFT JOIN (VALUES {zuordnung}) AS zu(typ, glied)
           ON zu.typ = t.gliederung
    LEFT JOIN strukturdaten.gemeinde_raumgliederung b
           ON  b.gebietsstand = t.gebietsstand
           AND b.ags          = t.ags
           AND b.gliederung   = zu.glied"""
    spalte = ("b.gliederung::text AS bezugsgliederung, b.typ_id::text AS bezugsraum"
              if bestand["schluessel"] == "ags"
              else "NULL::text AS bezugsgliederung, NULL::text AS bezugsraum")
    return f"""
    SELECT t.{s}::text AS schluessel, t.gliederung::text AS merkmal,
           t.typ_id::text AS typ_id, r.typ_name::text AS wert,
           r.bezeichnung::text AS bezeichnung,
           {spalte}
    FROM {bestand['tabelle']} t
    JOIN strukturdaten.raumtyp r
      ON  r.gebietsstand = t.gebietsstand
      AND r.gliederung   = t.gliederung
      AND r.typ_id       = t.typ_id{bezug}
    WHERE t.gebietsstand = DATE '{STAND}'
      AND r.typ_name IS NOT NULL
      {"AND t.gliederung NOT IN (%s)"
       % ", ".join("'%s'" % g for g in sorted(NUR_AUF_KREISEBENE))
       if bestand["schluessel"] == "ags" else ""}
    """


def kopf(lieferung=None):
    zeilen = [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE]
    zeilen += ["", f"{iri('lieferung/' + (lieferung or LIEFERUNG))} {{", ""]
    return "\n".join(zeilen)


def bezeichnung_putzen(roh):
    s = str(roh).strip()
    for endung in (" Kennziffer", " Kennziffern"):
        if s.endswith(endung):
            s = s[: -len(endung)].strip()
    return re.sub(r"\s*\(20\d\d\)\s*$", "", s).strip()


def merkmalsblock_indikator(merkmal, bezeichnung, bereich):
    definition = (
        "%s nach der laufenden Raumbeobachtung des Bundesinstituts fuer " "Bau-, Stadt- und Raumforschung, Bereich %s, Ausgabe 2024. " "Zeitreihenbereinigt: Auch die alten Jahrgaenge stehen im " "Gebietszuschnitt von 2022, nicht in dem ihres eigenen Jahres. " "Ein Wert von 1995 gilt damit fuer das Gebiet, das die Gemeinde " "heute hat." % (bezeichnung, bereich))
    return "\n".join([
        "    %s" % iri("merkmal/%s/%s" % (LIEFERUNG_INKAR, merkmal)),
        "        a                        stkg:Merkmal ;",
        "        stkg:merkmalsbezeichnung %s ;" % txt(bezeichnung),
        "        stkg:merkmalsdefinition  %s ." % txt(definition),
        "",
    ])


def merkmalsblock(gliederung, bezeichnung, ebene):
    return "\n".join([
        f"    {iri('merkmal/' + LIEFERUNG + '/typ_' + gliederung)}",
        "        a                        stkg:Merkmal ;",
        f"        stkg:merkmalsbezeichnung {txt(bezeichnung)} ;",
        f"        stkg:merkmalsdefinition  "
        f"{txt(f'Einstufung der {ebene} nach der Gliederung {bezeichnung} '
              f'des Bundesinstituts fuer Bau-, Stadt- und Raumforschung, '
              f'Gebietsstand {STAND}. Der Wert ist die Bezeichnung des Typs, '
              f'nicht eine gemessene Groesse; die Kennziffer der Quelle '
              f'ordnet nur und wird nicht mitgefuehrt.')} .",
        "",
    ])


def tripel(z, bestand):
    raum = bestand["raumbezug"].format(schluessel=z["schluessel"])

    if bestand.get("art") == "indikator":


        kennung = iri("beobachtung/%s/%s_%s"
                      % (z["merkmal"], z["schluessel"], z["jahr"]))

        merkmal = iri("merkmal/%s/%s" % (LIEFERUNG_INKAR, z["merkmal"]))
        return "\n".join([
            "    %s" % kennung,
            "        a                   stkg:Beobachtung ;",
            "        stkg:hatMerkmal     %s ;" % merkmal,
            "        stkg:hatRaumbezug   %s ;" % iri(raum),
            '        stkg:wert           "%s"^^xsd:decimal ;' % z["wert"],


            '        stkg:erhebungsjahr  "%s"^^xsd:gYear .' % z["jahr"],
            "",
        ])


    schluessel = z["schluessel"]
    if z["merkmal"] in BEZUGSRAUM and z.get("bezugsraum"):
        schluessel = z["bezugsraum"]
        raum = "aggregationsraum/%s_%s" % (z["bezugsgliederung"], schluessel)
    elif z["merkmal"] in BEZUGSRAUM:


        OHNE_BEZUGSRAUM.add((z["merkmal"], z["schluessel"]))
        return ""

    kennung = iri("beobachtung/typ_%s/%s_%s" % (z["merkmal"], schluessel, STAND))
    merkmal = iri("merkmal/%s/typ_%s" % (LIEFERUNG, z["merkmal"]))
    return "\n".join([
        "    %s" % kennung,
        "        a                       stkg:Beobachtung ;",
        "        stkg:hatMerkmal         %s ;" % merkmal,
        "        stkg:hatRaumbezug       %s ;" % iri(raum),
        "        stkg:wert               %s ;" % txt(z["wert"]),
        '        stkg:erhebungszeitpunkt "%s"^^xsd:date .' % STAND,
        "",
    ])


def sql_raumgliederung(tabelle, schluessel):
    arten = ", ".join("'%s'" % g for g in sorted(AGGREGATIONSART))
    return f"""
    SELECT g.{schluessel}::text AS schluessel, g.gliederung::text AS gliederung,
           g.typ_id::text AS typ_id, r.typ_name::text AS raumname
    FROM {tabelle} g
    JOIN strukturdaten.raumtyp r
      ON  r.gebietsstand = g.gebietsstand
      AND r.gliederung   = g.gliederung
      AND r.typ_id       = g.typ_id
    WHERE g.gebietsstand = DATE '{STAND}'
      AND g.gliederung IN ({arten})
    """


def baue_raumgliederung():
    ziel = pfade.RAUM / f"{LIEFERUNG}_mod03.trig"
    tmp = pfade.RAUM / "_gliederung.csv"
    raeume = {}
    zugehoerig = 0

    with ziel.open("w", encoding="utf-8") as aus:
        aus.write(kopf())
        for tabelle, schluessel, ebene in (
                ("strukturdaten.gemeinde_raumgliederung", "ags", "gemeindestand"),
                ("strukturdaten.kreis_raumgliederung", "kreis", "kreisstand")):
            hier = 0
            run_copy(sql_raumgliederung(tabelle, schluessel), tmp, tabelle)
            with tmp.open(encoding="utf-8", newline="") as fh:
                for z in csv.DictReader(fh):
                    raum = "aggregationsraum/%s_%s" % (z["gliederung"], z["typ_id"])
                    raeume.setdefault(raum, (z["gliederung"], z["raumname"]))
                    mitglied = "%s/%s_%s" % (ebene, z["schluessel"], STAND)
                    kennung = iri("zugehoerigkeit/gemeinde_aggregationsraum/" "%s_%s_%s" % (z["schluessel"], z["gliederung"],
                                                z["typ_id"]))
                    aus.write("\n".join([
                        "    %s" % kennung,
                        "        a                 stkg:Zugehoerigkeit ;",
                        "        stkg:hatMitglied  %s ;" % iri(mitglied),
                        "        stkg:gehoertZu    %s ;" % iri(raum),
                        '        stkg:gueltigVon   "%s"^^xsd:date .' % STAND,
                        "", ""]))
                    zugehoerig += 1
                    hier += 1
            print(f"  {tabelle.split('.')[1]:<28} {hier:>8} Zuordnungen",
                  flush=True)
        for raum, (gliederung, name) in sorted(raeume.items()):
            aus.write("\n".join([
                "    %s" % iri(raum),
                "        a                       stkg:Aggregationsraum ;",
                "        stkg:hatAggregationsart %s ;" % AGGREGATIONSART[gliederung],
                "        stkg:raumbezeichnung    %s ;" % txt(name),
                '        stkg:gueltigVon         "%s"^^xsd:date .' % STAND,
                "", ""]))
        aus.write("}\n")

    if tmp.exists():
        tmp.unlink()
    mb = ziel.stat().st_size / 1024 / 1024
    print(f"\n  -> {ziel.name:<34} {mb:>7.1f} MB")
    print(f"  {len(raeume)} Aggregationsraeume, {zugehoerig} Zugehoerigkeiten")


def baue(namen, max_mb=200):
    pfade.pruefe(AUSGABE)
    tmp = AUSGABE / "_inkar.csv"
    grenze = max_mb * 1024 * 1024 if max_mb else 0
    merkmale = {}
    anzahl = defaultdict(int)
    teile = []


    for alt in list(AUSGABE.glob(f"{LIEFERUNG}.trig")) + \
               list(AUSGABE.glob(f"{LIEFERUNG}_[0-9][0-9].trig")):
        alt.unlink()

    def dateiname(nr, lief):
        return AUSGABE / (f"{lief}.trig" if nr == 1
                          else f"{lief}_{nr:02d}.trig")


    zustand = {"nr": 1, "fh": None, "gross": 0, "lief": None}

    def oeffne():
        pfad = dateiname(zustand["nr"], zustand["lief"])
        fh = pfad.open("w", encoding="utf-8")
        fh.write(kopf(zustand["lief"]))
        teile.append(pfad)
        return fh

    def schliesse(fh):
        for schluessel, angabe in sorted(merkmale.items()):
            if angabe[0] == "indikator":
                fh.write(merkmalsblock_indikator(schluessel, angabe[1],
                                                 angabe[2]))
            else:
                fh.write(merkmalsblock(schluessel,
                                       bezeichnung_putzen(angabe[1]),
                                       angabe[2]))
        fh.write("}\n")
        fh.close()

    def wechsle(lief):
        if zustand["lief"] == lief:
            return
        if zustand["fh"] is not None:
            schliesse(zustand["fh"])
            zustand["fh"] = None
        merkmale.clear()
        zustand.update(nr=1, gross=0, lief=lief)

    def schreibe(text):
        if zustand["fh"] is None:
            zustand["fh"] = oeffne()
        if grenze and zustand["gross"] + len(text) > grenze:
            schliesse(zustand["fh"])
            if zustand["nr"] == 1:
                erst = teile[-1]
                neu = erst.with_name(f"{zustand['lief']}_01.trig")
                erst.replace(neu)
                teile[-1] = neu
            zustand["nr"] += 1
            zustand["fh"] = oeffne()
            zustand["gross"] = 0
        zustand["fh"].write(text)
        zustand["gross"] += len(text)

    try:


        for bestand in sorted(BESTAENDE,
                              key=lambda b: b.get("lieferung", LIEFERUNG)):
            if namen and bestand["name"] not in namen:
                continue
            wechsle(bestand.get("lieferung", LIEFERUNG))
            run_copy(sql(bestand), tmp, bestand["name"])
            with tmp.open(encoding="utf-8", newline="") as fh:
                for z in csv.DictReader(fh):
                    if bestand.get("art") == "indikator":
                        merkmale.setdefault(z["merkmal"],
                                            ("indikator", z["bezeichnung"],
                                             z["bereich"]))
                    else:
                        merkmale.setdefault(z["merkmal"],
                                            ("typisierung", z["bezeichnung"],
                                             bestand["ebene"]))


                    if z["merkmal"] in BEZUGSRAUM:
                        paar = (z["merkmal"], z.get("bezugsraum"))
                        if paar in GESCHRIEBEN:
                            continue
                        GESCHRIEBEN.add(paar)
                    text = tripel(z, bestand)
                    if not text:
                        continue
                    schreibe(text)
                    anzahl[bestand["name"]] += 1
            print(f"  {bestand['name']:<26} "
                  f"{anzahl[bestand['name']]:>9} Zeilen", flush=True)
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
        if GESCHRIEBEN:
            je = defaultdict(int)
            for gl, _ in GESCHRIEBEN:
                je[gl] += 1
            print("\n  Einstufungen an ihrem Bezugsraum statt an der Gemeinde:")
            for gl, n in sorted(je.items()):
                print(f"    {gl:<5} {n:>6} Raeume")
        if OHNE_BEZUGSRAUM:
            je = defaultdict(int)
            for gl, _ in OHNE_BEZUGSRAUM:
                je[gl] += 1
            print("\n  OHNE BEZUGSRAUM -- Einstufung faellt weg, weil die " "Referenzmappe\n  fuer diese Gemeinden keinen Raum nennt:")
            for gl, n in sorted(je.items()):
                print(f"    {gl:<5} {n:>6} Gemeinden")
        print(f"  {len(merkmale)} Merkmale, "
              f"{sum(anzahl.values())} Beobachtungen")
        if namen:
            print("\nTEILLAUF - die Dateien enthalten NICHT alles, was in " "diesen Graphen gehoert. Beim Laden wuerde der Rest fehlen.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("bestand", nargs="*", help="nur diese Bestaende")
    p.add_argument("--liste", action="store_true")
    p.add_argument("--max-mb", type=int, default=200,
                   help="Umbruch in Teildateien ab dieser Groesse")
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
