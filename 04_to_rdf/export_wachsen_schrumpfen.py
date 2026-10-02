import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

REPO = Path(__file__).resolve().parents[1]
from db import query

BASIS     = "https://skg-bundestag.de/"
LIEFERUNG = "bbsr_wachsen_schrumpfen_2021"
AUSGABE   = pfade.BEOBACHTUNGEN

STAND     = "2021-12-31"
INTERVALL = "2016-2021"


SPALTE_KENNZIFFER = 0
SPALTE_ERGEBNIS   = 33
KOPFZEILEN        = 5

DATEI_BBSR = Path("PFAD_ZU_DATEN"
                  r"\bbsr_wachsen_schrumpfen\zeitlicher-verlauf-ws-1924.xlsx")
DATEI_REF  = (REPO.parents[1] / "Daten" / "Strukturdaten"
              / "raumgliederungen-referenzen-2021.xlsx")

PRAEFIXE = [
    ("stkg", "https://skg-bundestag.de/schema#"),
    ("xsd",  "http://www.w3.org/2001/XMLSchema#"),
]


KLASSEN = {
    "überdurchschnittlich schrumpfend",
    "schrumpfend",
    "keine eindeutige Entwicklungsrichtung",
    "wachsend",
    "überdurchschnittlich wachsend",
}


UNBEKANNT = "unbekannt"


def txt(wert):
    s = str(wert)
    for such, ersatz in (("\\", "\\\\"), ('"', '\\"'),
                         ("\n", "\\n"), ("\r", ""), ("\t", "\\t")):
        s = s.replace(such, ersatz)
    return f'"{s}"'


def iri(pfad):
    return f"<{BASIS}{pfad}>"


def lies_zuordnung():
    ref = pd.read_excel(DATEI_REF, sheet_name="Gemeindereferenz (inkl. Kreise)",
                        dtype=str, skiprows=[1])
    ref = ref[ref["GEM2021"].str.match(r"^\d+$", na=False)].copy()
    ref["ags"] = ref["GEM2021"].str.zfill(8)
    ref["vwg"] = ref["VWG2021"].str.zfill(9)
    return ref[["ags", "GEM_NAME", "vwg"]]


def lies_klassifikation():
    bb = pd.read_excel(DATEI_BBSR, sheet_name=0, header=None,
                       skiprows=KOPFZEILEN,
                       usecols=[SPALTE_KENNZIFFER, SPALTE_ERGEBNIS],
                       names=["kz", "ergebnis"], dtype={0: str})
    return bb[bb["kz"].str.match(r"^\d{9}$", na=False)].copy()


def gemeinden_im_stand():
    zeilen = query("SELECT ags FROM raum.gemeindestand "
                   f"WHERE stichtag = '{STAND}' ORDER BY ags")
    return [z[0] for z in zeilen]


def kopf():
    zeilen = [f"@prefix {p}: <{u}> ." for p, u in PRAEFIXE]
    zeilen += ["", f"{iri('lieferung/' + LIEFERUNG)} {{", ""]
    return "\n".join(zeilen)


def merkmalsblock():
    definition = (
        "Einstufung einer Gemeinde als wachsend oder schrumpfend im "
        f"bundesweiten Vergleich, Zeitintervall {INTERVALL}. Der Wert ist ein " "Index aus sechs Indikatoren -- Bevoelkerungsentwicklung, " "Wanderungssaldo, Entwicklung der Erwerbsfaehigen, Beschaeftigte am " "Arbeitsort, Arbeitslosenquote und Gewerbesteuergrundaufkommen --, " "je Quintil mit 0 bis 4 Punkten bewertet, die drei demografischen " "doppelt gewichtet. Keine gemessene Groesse: 'schrumpfend' heisst " "nicht, dass die Bevoelkerung sinkt. Berechnet fuer Einheitsgemeinden " "und Gemeindeverbaende; Gemeinden eines Verbands tragen dessen Wert."
    )
    return "\n".join([
        f"    {iri('merkmal/' + LIEFERUNG + '/wachsen_schrumpfen')}",
        "        a                        stkg:Merkmal ;",
        f"        stkg:merkmalsbezeichnung "
        f"{txt('Wachsen und Schrumpfen im bundesweiten Vergleich ' + INTERVALL)} ;",
        f"        stkg:merkmalsdefinition  {txt(definition)} .",
        "",
    ])


def tripel(ags, klasse, einheit):
    return "\n".join([
        "    %s" % iri(f"beobachtung/wachsen_schrumpfen/{ags}_{INTERVALL}"),
        "        a                        stkg:Beobachtung ;",
        "        stkg:hatMerkmal          %s ;"
        % iri(f"merkmal/{LIEFERUNG}/wachsen_schrumpfen"),
        "        stkg:hatRaumbezug        %s ;"
        % iri(f"gemeindestand/{ags}_{STAND}"),
        "        stkg:wert                %s ;" % txt(klasse),


        '        stkg:erhebungszeitpunkt  "%s"^^xsd:date .' % STAND,
        "",
    ])


def baue():
    zuordnung = lies_zuordnung()
    klassifikation = lies_klassifikation()
    ags_liste = gemeinden_im_stand()

    verband = dict(zip(zuordnung["ags"], zuordnung["vwg"]))
    klasse_je_verband = dict(zip(klassifikation["kz"], klassifikation["ergebnis"]))

    zeilen = []
    zaehler = {"gesetzt": 0, "ohne_wert": 0, "ohne_verband": 0, "nicht_in_referenz": 0}
    unbekannte_klassen = set()

    for ags in ags_liste:
        vwg = verband.get(ags)
        if vwg is None:
            zaehler["nicht_in_referenz"] += 1
            zeilen.append(tripel(ags, UNBEKANNT, "nicht in der Referenzmappe"))
            continue

        roh = klasse_je_verband.get(vwg)
        if vwg not in klasse_je_verband:
            zaehler["ohne_verband"] += 1
            zeilen.append(tripel(ags, UNBEKANNT, vwg))
            continue

        if pd.isna(roh):
            zaehler["ohne_wert"] += 1
            zeilen.append(tripel(ags, UNBEKANNT, vwg))
            continue

        klasse = str(roh).strip()
        if klasse not in KLASSEN:
            unbekannte_klassen.add(klasse)
            continue

        zaehler["gesetzt"] += 1
        zeilen.append(tripel(ags, klasse, vwg))

    if unbekannte_klassen:
        print("ABBRUCH: unbekannte Klartexte in der Quelle:", file=sys.stderr)
        for k in sorted(unbekannte_klassen):
            print("   %r" % k, file=sys.stderr)
        raise SystemExit(1)

    return zeilen, zaehler, len(ags_liste)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pruefen", action="store_true",
                   help="nur zaehlen, keine Datei schreiben")
    a = p.parse_args()

    for datei in (DATEI_BBSR, DATEI_REF):
        if not datei.exists():
            print(f"FEHLT: {datei}", file=sys.stderr)
            raise SystemExit(1)

    zeilen, z, gesamt = baue()

    unbekannt = z["ohne_wert"] + z["ohne_verband"] + z["nicht_in_referenz"]
    print(f"Gemeinden im Gebietsstand {STAND}: {gesamt}")
    print(f"   mit Einstufung          : {z['gesetzt']}")
    print(f"   unbekannt               : {unbekannt}")
    print(f"      ohne Wert beim BBSR  : {z['ohne_wert']}")
    print(f"      Verband fehlt        : {z['ohne_verband']}")
    print(f"      nicht in Referenz    : {z['nicht_in_referenz']}")
    print(f"   Beobachtungen insgesamt : {len(zeilen)}")

    if a.pruefen:
        return

    AUSGABE.mkdir(parents=True, exist_ok=True)
    ziel = AUSGABE / f"{LIEFERUNG}.trig"
    with ziel.open("w", encoding="utf-8", newline="\n") as f:
        f.write(kopf())
        f.write(merkmalsblock())
        for zeile in zeilen:
            f.write(zeile)
        f.write("}\n")
    print(f"geschrieben: {ziel}  ({ziel.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
