import csv
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "Parlamentsarbeit"
          / "dip_plenarprotokolle_xml")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand
ZIEL = zwischenstand.fuer(__file__)
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"


ZU_PROTOKOLL = re.compile(r"^zu\s+protokoll\s+gegebene", re.IGNORECASE)
ERKLAERUNG = re.compile(r"^erkl.rung(en)?\s+nach\s*§?\s*31\s*GO", re.IGNORECASE)


KOPF_ART = "Anlage_2"
KOPF_GEGENSTAND = "Anlage_3"

SPALTEN = ["rede_id", "redeart", "redeart_quelle", "protokoll_nr",
           "wahlperiode", "anlage", "anlagen_typ", "beratungsgegenstand",
           "doppelt"]


def text_von(element):
    return normal("".join(element.itertext()))


def normal(text):
    s = str(text or "").replace("­", "").replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def kopfabsaetze(teil):
    kopf = []
    for kind in list(teil):
        if kind.tag == "rede":
            break
        if kind.tag == "p":
            kopf.append((kind.get("klasse") or "", text_von(kind)))
    return kopf


def bestimme_art(typ, kopf, ueberschrift=""):
    kandidaten = [(typ, "anlagen_typ")]
    kandidaten += [(text, "absatz_anlage_3")
                   for klasse, text in kopf if klasse == KOPF_GEGENSTAND]
    if ueberschrift:
        kandidaten.append((ueberschrift, "ueberschrift_der_anlage"))
    for wert, quelle in kandidaten:
        if ZU_PROTOKOLL.match(wert):
            return "zu_protokoll", quelle
        if ERKLAERUNG.match(wert):
            return "erklaerung_31go", quelle
    return "anlage_unbekannt", ""


def werte_protokoll_aus(pfad):
    wurzel = ElementTree.parse(pfad).getroot()
    wp = wurzel.get("wahlperiode", "")
    protokoll = pfad.stem.split("_", 1)[1].replace("-", "/")
    zeilen = []

    verlauf = wurzel.find("sitzungsverlauf")
    if verlauf is not None:

        for rede in verlauf.findall("rede"):
            zeilen.append({"rede_id": rede.get("id", ""),
                           "redeart": "sitzungsbeginn",
                           "redeart_quelle": "struktur", "anlage": "",
                           "anlagen_typ": "", "beratungsgegenstand": ""})
        for top in verlauf.findall("tagesordnungspunkt"):
            for rede in top.findall("rede"):
                zeilen.append({"rede_id": rede.get("id", ""),
                               "redeart": "plenum",
                               "redeart_quelle": "struktur", "anlage": "",
                               "anlagen_typ": "", "beratungsgegenstand": ""})

    for anlagen in wurzel.iter("anlagen"):
        for anlage in anlagen.iter("anlage"):
            titel = anlage.find("anlagen-titel")
            nummer = text_von(titel) if titel is not None else ""


            ueberschrift = ""
            for teil in anlage.findall("anlagen-text"):
                reden = list(teil.iter("rede"))
                typ = normal(teil.get("anlagen-typ") or "")
                if not reden:
                    ueberschrift = typ
                    continue
                kopf = kopfabsaetze(teil)
                art, quelle = bestimme_art(typ, kopf, ueberschrift)


                gegenstand = " ".join(
                    text for klasse, text in kopf if klasse != KOPF_ART)

                for rede in reden:
                    zeilen.append({"rede_id": rede.get("id", ""),
                                   "redeart": art, "redeart_quelle": quelle,
                                   "anlage": nummer, "anlagen_typ": typ,
                                   "beratungsgegenstand": gegenstand})

    for z in zeilen:
        z["protokoll_nr"] = protokoll
        z["wahlperiode"] = wp
    return zeilen


def main():
    dateien = sorted(QUELLE.glob("wp*_*.xml"))
    print(f"{len(dateien)} Protokolldateien in {QUELLE}\n")

    je_rede, doppelt = {}, Counter()
    for pfad in dateien:
        for z in werte_protokoll_aus(pfad):
            rid = z["rede_id"]
            if not rid:
                continue
            if rid in je_rede:

                doppelt[rid] += 1
                je_rede[rid]["doppelt"] = True
                continue
            z["doppelt"] = False
            je_rede[rid] = z

    zeilen = list(je_rede.values())


    n = len(zeilen)
    print(f"{'=' * 68}")
    print(f"{n:,} Reden\n")
    erklaerung = {
        "plenum": "im Tagesordnungspunkt — gesprochen, mit Publikum",
        "zu_protokoll": "Anlage, nie gehalten (Aussprache verkuerzt)",
        "erklaerung_31go": "Erklaerung zur Abstimmung, keine Rede",
        "sitzungsbeginn": "vor dem ersten Tagesordnungspunkt",
        "anlage_unbekannt": "Anlage mit unbekanntem Text — PRUEFEN",
    }
    for art, v in Counter(z["redeart"] for z in zeilen).most_common():
        print(f"  {art:<18} {v:>7,}  ({v / n * 100:5.2f} %)  "
              f"{erklaerung.get(art, '')}")

    gehalten = sum(1 for z in zeilen if z["redeart"] in ("plenum",
                                                         "sitzungsbeginn"))
    print(f"\n  {gehalten:,} Reden wurden tatsaechlich gehalten "
          f"({gehalten / n * 100:.1f} %)")
    print(f"  {n - gehalten:,} stehen im Anhang und wurden nie gesprochen "
          f"({(n - gehalten) / n * 100:.1f} %)")

    if doppelt:
        print(f"\n  {len(doppelt)} rede_id kommen in zwei Dateien vor "
              f" — als `doppelt` markiert")

    unbekannt = [z for z in zeilen if z["redeart"] == "anlage_unbekannt"]
    if unbekannt:
        print(f"\n  {len(unbekannt)} Reden in Anlagen, deren Text weder "
              f"'Zu Protokoll gegebene' noch 'Erklaerungen nach § 31 GO' "
              f"lautet:")
        for typ, v in Counter(z["anlagen_typ"][:60]
                              for z in unbekannt).most_common(8):
            print(f"    {v:>4}x  anlagen-typ = {typ or '(nicht gesetzt)'}")

    print("\n  Woher die Angabe stammt:")
    for q, v in Counter(z["redeart_quelle"] for z in zeilen).most_common():
        wie = {"struktur": "Ort im Dokument (gesprochene Reden)",
               "anlagen_typ": "Attribut anlagen-typ = Absatz Anlage_2",
               "absatz_anlage_3": "Absatz Anlage_3, weil Anlage_2 ausfiel",
               "ueberschrift_der_anlage": "Kopfsatz auf zwei <anlagen-text> verteilt",
               "": "keine Angabe im Kopf — bleibt offen"}.get(q, q)
        print(f"    {v:>7,}  {q or '(offen)':<16} {wie}")

    print(f"\nJe Wahlperiode:")
    for wp in sorted({z["wahlperiode"] for z in zeilen}):
        teil = [z for z in zeilen if z["wahlperiode"] == wp]
        zp = sum(1 for z in teil if z["redeart"] == "zu_protokoll")
        er = sum(1 for z in teil if z["redeart"] == "erklaerung_31go")
        print(f"  WP {wp}: {len(teil):>7,} Reden, {zp:>5,} zu Protokoll "
              f"({zp / len(teil) * 100:4.1f} %), {er:>5,} Erklaerungen "
              f"({er / len(teil) * 100:4.1f} %)")

    mit_gegenstand = [z for z in zeilen if z["beratungsgegenstand"]]
    print(f"\n  {len(mit_gegenstand):,} Reden tragen einen "
          f"Beratungsgegenstand aus dem <anlagen-text>")

    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"redeart_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        s = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        s.writeheader()
        s.writerows(zeilen)
    print(f"\n{len(zeilen):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
