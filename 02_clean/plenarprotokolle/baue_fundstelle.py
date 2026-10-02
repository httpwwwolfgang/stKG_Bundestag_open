import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "Parlamentsarbeit"
          / "dip_plenarprotokolle_xml")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand


LIEFERUNG = "dip_plenarprotokolle"
ZIEL = zwischenstand.fuer(__file__)
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"

QUADRANT = re.compile(r"^[A-D]$")

SPALTEN = ["rede_id", "protokoll_nr", "wahlperiode", "seite", "quadrant",
           "fundstelle", "quadrant_unklar", "verweise", "im_protokoll"]


def normal(text):
    s = str(text or "").replace("­", "").replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def werte_protokoll_aus(pfad):
    wurzel = ElementTree.parse(pfad).getroot()
    wp = wurzel.get("wahlperiode", "")
    protokoll = pfad.stem.split("_", 1)[1].replace("-", "/")


    vorhanden = {r.get("id") for r in wurzel.iter("rede")}

    verweise = defaultdict(list)
    verzeichnis = wurzel.find("vorspann/inhaltsverzeichnis")
    if verzeichnis is not None:
        for x in verzeichnis.iter("xref"):
            if x.get("ref-type") != "rede":
                continue
            verweise[x.get("rid")].append(
                (normal(x.get("pnr")), normal(x.get("div"))))

    zeilen = []
    for rid, stellen in verweise.items():
        eindeutig = sorted(set(stellen))
        seite, div = eindeutig[0]
        unklar = bool(div) and not QUADRANT.match(div)
        zeilen.append({
            "rede_id": rid,
            "protokoll_nr": protokoll,
            "wahlperiode": wp,
            "seite": seite,
            "quadrant": div,
            "fundstelle": f"{seite} {div}".strip() if seite else "",
            "quadrant_unklar": "ja" if unklar else "",
            "verweise": len(stellen),
            "im_protokoll": "ja" if rid in vorhanden else "nein",
        })
    return zeilen, vorhanden - set(verweise), len(eindeutig) if zeilen else 0


def main():
    dateien = sorted(QUELLE.glob("wp*_*.xml"))
    print(f"{len(dateien)} Protokolle lesen aus {QUELLE}")

    alle, ohne_verweis = [], []
    for pfad in dateien:
        zeilen, fehlend, _ = werte_protokoll_aus(pfad)
        alle.extend(zeilen)
        protokoll = pfad.stem.split("_", 1)[1].replace("-", "/")
        ohne_verweis.extend((protokoll, rid) for rid in sorted(fehlend))


    print(f"\n{'=' * 70}")
    print(f"{len(alle):,} Verweise auf Reden im Inhaltsverzeichnis\n")

    mit_seite = [z for z in alle if z["seite"]]
    print(f"  {len(mit_seite):>7,} tragen eine Druckseite")
    print(f"  {len(alle) - len(mit_seite):>7,} tragen keine")

    ins_leere = [z for z in alle if z["im_protokoll"] == "nein"]
    print(f"\n  {len(ins_leere):>7,} Verweise zeigen auf eine `rede_id`, "
          f"die es im Protokoll nicht gibt")
    print(f"  {len(ohne_verweis):>7,} Reden im Protokoll haben keinen Verweis")

    mehrfach = [z for z in alle if z["verweise"] > 1]
    if mehrfach:
        print(f"\n  {len(mehrfach):>7,} Reden tragen mehr als einen Verweis "
              f"— PRUEFEN, ob sie dieselbe Fundstelle nennen")
    else:
        print(f"\n  Keine Rede traegt zwei Verweise: die Fundstelle ist je "
              f"Rede eindeutig, es ist keine Auswahl noetig")

    print("\n  Quadranten:")
    for q, v in Counter(z["quadrant"] for z in alle).most_common():
        wie = {"A": "linke Spalte oben", "B": "linke Spalte unten",
               "C": "rechte Spalte oben", "D": "rechte Spalte unten",
               "": "nicht gesetzt"}.get(q, "KEIN QUADRANT — siehe unten")
        print(f"    {v:>7,}  {q or '(leer)':<8} {wie}")

    unklar = [z for z in alle if z["quadrant_unklar"]]
    if unklar:
        print(f"\n  {len(unklar)} Verweise mit einem `div`, der kein Quadrant "
              f"ist — Wert bleibt stehen:")
        for z in unklar:
            print(f"    {z['protokoll_nr']} {z['rede_id']}  "
                  f"pnr={z['seite']!r} div={z['quadrant']!r}")

    if ohne_verweis:
        print(f"\n  Reden ohne Verweis im Inhaltsverzeichnis "
              f"({len(ohne_verweis)}):")
        for protokoll, rid in ohne_verweis[:25]:
            print(f"    {protokoll}  {rid}")
        if len(ohne_verweis) > 25:
            print(f"    ... und {len(ohne_verweis) - 25} weitere")

    print("\n  Je Wahlperiode:")
    for wp in sorted({z["wahlperiode"] for z in alle}):
        teil = [z for z in alle if z["wahlperiode"] == wp]
        mit = sum(1 for z in teil if z["seite"])
        seiten = [int(z["seite"]) for z in teil if z["seite"].isdigit()]
        print(f"    WP {wp}: {len(teil):>6,} Verweise, {mit:>6,} mit Seite, "
              f"Seiten {min(seiten):,} bis {max(seiten):,}")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"fundstelle_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(alle)
    print(f"\n{len(alle):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
