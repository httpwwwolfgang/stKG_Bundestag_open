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


KOPFKLASSEN = {


    "T_NaS": "titel",
    "T_ohne_NaS": "titel",
    "T_ZP_NaS": "titel",
    "T_NaS_NaS": "titel",
    "T_ohne_NaS_NaS": "titel",
    "T_ZP_NaS_NaS": "titel",
    "T_NaS_NaS_Strich": "titel",
    "T_ohne_NaS_NaS_Strich": "titel",

    "T_fett": "zusatztitel",
    "T_E_fett": "zusatztitel",


    "T_Drs": "drucksachen_text",
    "T_E_Drs": "drucksachen_text",
    "T_E_E_Drs": "drucksachen_text",
    "T_Ber.+Drs.": "drucksachen_text",
    "T_Ueberweisung": "ueberweisung",
    "T_Beratung": "beratung",
    "T-Beratung": "beratung",


    "T": "aufruf",
}


DRUCKSACHE = re.compile(r"\b(1[89]|20)/(\d{1,6})\b")

SPALTEN_TOP = ["protokoll_nr", "wahlperiode", "top_id", "lfd", "titel",
               "titel_quelle", "titel_anzahl", "zusatztitel", "drucksachen",
               "drucksachen_anzahl", "ueberweisung", "beratung", "aufruf",
               "weitere", "reden", "erste_rede_id"]

SPALTEN_ZUORDNUNG = ["rede_id", "protokoll_nr", "top_id", "lfd", "doppelt"]


def text_von(element):
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def werte_protokoll_aus(pfad, unbekannte):
    wurzel = ElementTree.parse(pfad).getroot()
    wp = wurzel.get("wahlperiode", "")
    protokoll = pfad.stem.split("_", 1)[1].replace("-", "/")
    verlauf = wurzel.find("sitzungsverlauf")
    if verlauf is None:
        return [], []

    tops, zuordnung = [], []
    gesehen = Counter()

    for top in verlauf.findall("tagesordnungspunkt"):
        top_id = top.get("top-id", "")
        gesehen[top_id] += 1
        lfd = gesehen[top_id]

        teile = defaultdict(list)
        for kind in top:
            if kind.tag == "rede":
                break
            if kind.tag != "p":
                continue
            klasse = kind.get("klasse") or ""
            if not (klasse.startswith("T_") or klasse.startswith("T-")
                    or klasse == "T"):
                continue
            ziel = KOPFKLASSEN.get(klasse)
            if ziel is None:
                unbekannte[klasse] += 1
                teile["weitere"].append(f"{klasse}: {text_von(kind)}")
            else:
                teile[ziel].append(text_von(kind))

        drs_text = " ".join(teile.get("drucksachen_text", []))
        nummern = [f"{a}/{b}" for a, b in DRUCKSACHE.findall(drs_text)]

        reden = top.findall("rede")


        titel = " | ".join(teile.get("titel", []))
        zusatz = " | ".join(teile.get("zusatztitel", []))
        aufruf = " ".join(teile.get("aufruf", []))
        if titel:
            quelle = "T_NaS"
        elif zusatz:
            titel, quelle = zusatz, "T_fett"
        elif aufruf:
            titel, quelle = aufruf, "T"
        else:
            quelle = ""

        tops.append({
            "protokoll_nr": protokoll, "wahlperiode": wp,
            "top_id": top_id, "lfd": lfd,
            "titel": titel,
            "titel_quelle": quelle,
            "titel_anzahl": len(teile.get("titel", [])),
            "aufruf": " ".join(teile.get("aufruf", [])),
            "zusatztitel": " | ".join(teile.get("zusatztitel", [])),
            "drucksachen": ", ".join(nummern),
            "drucksachen_anzahl": len(nummern),
            "ueberweisung": " ".join(teile.get("ueberweisung", [])),
            "beratung": " ".join(teile.get("beratung", [])),
            "weitere": " | ".join(teile.get("weitere", [])),
            "reden": len(reden),
            "erste_rede_id": reden[0].get("id", "") if reden else "",
        })
        for rede in reden:
            zuordnung.append({"rede_id": rede.get("id", ""),
                              "protokoll_nr": protokoll,
                              "top_id": top_id, "lfd": lfd})
    return tops, zuordnung


def main():
    dateien = sorted(QUELLE.glob("wp*_*.xml"))
    print(f"{len(dateien)} Protokolldateien in {QUELLE}\n")

    alle_tops, alle_zuordnungen, unbekannte = [], {}, Counter()
    doppelt = 0
    for pfad in dateien:
        tops, zuordnung = werte_protokoll_aus(pfad, unbekannte)
        alle_tops.extend(tops)
        for z in zuordnung:
            rid = z["rede_id"]
            if not rid:
                continue
            if rid in alle_zuordnungen:
                alle_zuordnungen[rid]["doppelt"] = True
                doppelt += 1
                continue
            z["doppelt"] = False
            alle_zuordnungen[rid] = z

    zuordnungen = list(alle_zuordnungen.values())


    n = len(alle_tops)
    print(f"{'=' * 70}")
    print(f"{n:,} Tagesordnungspunkte, "
          f"{len(zuordnungen):,} Reden zugeordnet\n")

    print("\n  Woher der Titel stammt:")
    for q, v in Counter(t["titel_quelle"] for t in alle_tops).most_common():
        wie = {"T_NaS": "Titelzeile des Punktes",
               "T_fett": "aus dem Kurztitel nachgezogen (sonst leer)",
               "T": "aus dem Aufruf der Sitzungsleitung nachgezogen",
               "": "kein Titel im Protokoll"}.get(q, q)
        reden = sum(t["reden"] for t in alle_tops if t["titel_quelle"] == q)
        print(f"    {v:>5} Punkte, {reden:>6,} Reden  {q or '(kein)':<8} {wie}")

    mit_titel = sum(1 for t in alle_tops if t["titel"])
    mit_zusatz = sum(1 for t in alle_tops if t["zusatztitel"])
    mit_drs = sum(1 for t in alle_tops if t["drucksachen"])
    mit_ueb = sum(1 for t in alle_tops if t["ueberweisung"])
    for was, v in [("mit Titel (T_NaS)", mit_titel),
                   ("mit Zusatztitel (T_fett)", mit_zusatz),
                   ("mit Drucksachennummer", mit_drs),
                   ("mit Ueberweisungsvorschlag", mit_ueb)]:
        print(f"  {was:<32} {v:>6,}  ({v / n * 100:5.1f} %)")

    ohne_titel = [t for t in alle_tops if not t["titel"]]
    print(f"\n  {len(ohne_titel):,} Tagesordnungspunkte ohne Titel — "
          f"kein Titel wird geraten")
    if ohne_titel:
        print("  Beispiele:")
        for t in ohne_titel[:4]:
            print(f"    {t['protokoll_nr']:<8} {t['top_id']:<28} "
                  f"{t['reden']:>3} Reden  weitere: {t['weitere'][:50]}")

    nummern = [x for t in alle_tops for x in t["drucksachen"].split(", ") if x]
    print(f"\n  {len(nummern):,} Drucksachennennungen, "
          f"{len(set(nummern)):,} verschiedene Drucksachen")
    mehrere = sum(1 for t in alle_tops if t["drucksachen_anzahl"] > 1)
    print(f"  {mehrere:,} Tagesordnungspunkte nennen mehr als eine")

    reden_mit_drs = sum(t["reden"] for t in alle_tops if t["drucksachen"])
    reden_ges = sum(t["reden"] for t in alle_tops)
    print(f"\n  {reden_mit_drs:,} von {reden_ges:,} Reden in einem "
          f"Tagesordnungspunkt mit Drucksachennummer "
          f"({reden_mit_drs / reden_ges * 100:.1f} %)")

    if unbekannte:
        print(f"\n  Absatzklassen im Tagesordnungskopf, die keiner Spalte "
              f"zugeordnet sind (stehen in `weitere`):")
        for k, v in unbekannte.most_common():
            print(f"    {v:>6,}x  {k}")

    if doppelt:
        print(f"\n  {doppelt} Reden in zwei Protokollen "
              f"— markiert")

    print(f"\nJe Wahlperiode:")
    for wp in sorted({t["wahlperiode"] for t in alle_tops}):
        teil = [t for t in alle_tops if t["wahlperiode"] == wp]
        drs = sum(1 for t in teil if t["drucksachen"])
        print(f"  WP {wp}: {len(teil):>5,} Punkte, {drs:>5,} mit Drucksache "
              f"({drs / len(teil) * 100:5.1f} %), "
              f"{sum(t['reden'] for t in teil):>7,} Reden")

    print(f"\nGroesste Debatten:")
    for t in sorted(alle_tops, key=lambda x: -x["reden"])[:5]:
        print(f"  {t['reden']:>3} Reden  {t['protokoll_nr']:<8} "
              f"{t['top_id']:<24} {(t['zusatztitel'] or t['titel'])[:52]}")


    ZIEL.mkdir(parents=True, exist_ok=True)
    for name, daten, spalten in [
            ("tagesordnungspunkt", alle_tops, SPALTEN_TOP),
            ("rede_tagesordnungspunkt", zuordnungen, SPALTEN_ZUORDNUNG)]:
        pfad = ZIEL / f"{name}_{STEMPEL}.csv"
        with pfad.open("w", encoding="utf-8", newline="") as f:
            schreiber = csv.DictWriter(f, fieldnames=spalten, delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(daten)
        print(f"\n{len(daten):>7,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
