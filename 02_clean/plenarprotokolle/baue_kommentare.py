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


LIEFERUNG = "dip_plenarprotokolle"
ZIEL = zwischenstand.fuer(__file__)
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"


BEGINN = (r"(?:(?:[A-Za-zäöüß]+e[rn]?\s+)?(?:Beifall|Zurufe?|Gegenrufe?|Rufe?|"
          r"Heiterkeit|Lachen|Widerspruch|Unruhe|Unterbrechung|Zustimmung|"
          r"Glocke|Klopfzeichen|Abg\.)\b"
          r"|(?:Der|Die|Das)\s+(?:Redner|Rednerin|Abgeordnete|Anwesenden|"
          r"Mitglieder|Mikrofon|Fraktion)"
          r"|[^:–—]{2,200}:\s)")
TRENNER = re.compile(rf"\s+[–—-]\s+(?={BEGINN})")

SPALTEN = ["kommentar_id", "protokoll_nr", "wahlperiode", "kontext",
           "rede_id", "top_id", "lfd", "nach_absatz", "absaetze_gesamt",
           "ereignisse", "text", "doppelt"]

SPALTEN_EREIGNIS = ["kommentar_id", "lfd_ereignis", "rede_id", "text"]


def text_von(element):
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def werte_protokoll_aus(pfad, zaehler):
    wurzel = ElementTree.parse(pfad).getroot()
    wp = wurzel.get("wahlperiode", "")
    protokoll = pfad.stem.split("_", 1)[1].replace("-", "/")
    zeilen, ereignisse = [], []

    def sammle(behaelter, kontext, rede_id="", top_id="", lfd=""):
        absaetze = [k for k in behaelter if k.tag == "p"]
        gesehen = 0
        for kind in behaelter:
            if kind.tag == "p":
                gesehen += 1
            elif kind.tag == "kommentar":
                zaehler[0] += 1
                roh = text_von(kind).strip()


                if roh.startswith("("):
                    roh = roh[1:].strip()
                if roh.endswith(")"):
                    roh = roh[:-1].strip()
                teile = [t.strip() for t in TRENNER.split(roh) if t.strip()]
                kid = f"K{zaehler[0]:07d}"
                zeilen.append({
                    "kommentar_id": kid, "protokoll_nr": protokoll,
                    "wahlperiode": wp, "kontext": kontext,
                    "rede_id": rede_id, "top_id": top_id, "lfd": lfd,
                    "nach_absatz": gesehen, "absaetze_gesamt": len(absaetze),
                    "ereignisse": len(teile), "text": roh, "doppelt": "",
                })
                for i, t in enumerate(teile, 1):
                    ereignisse.append({"kommentar_id": kid, "lfd_ereignis": i,
                                       "rede_id": rede_id, "text": t})

    verlauf = wurzel.find("sitzungsverlauf")
    if verlauf is not None:
        beginn = verlauf.find("sitzungsbeginn")
        if beginn is not None:
            sammle(beginn, "sitzungsbeginn")
            for rede in beginn.findall("rede"):
                sammle(rede, "rede", rede_id=rede.get("id", ""))
        for rede in verlauf.findall("rede"):
            sammle(rede, "rede", rede_id=rede.get("id", ""))

        gesehen = Counter()
        for top in verlauf.findall("tagesordnungspunkt"):
            top_id = top.get("top-id", "")
            gesehen[top_id] += 1

            sammle(top, "tagesordnungspunkt", top_id=top_id,
                   lfd=str(gesehen[top_id]))
            for rede in top.findall("rede"):
                sammle(rede, "rede", rede_id=rede.get("id", ""),
                       top_id=top_id, lfd=str(gesehen[top_id]))

    for anlage in wurzel.iter("anlagen-text"):
        sammle(anlage, "anlage")
        for rede in anlage.findall("rede"):
            sammle(rede, "rede", rede_id=rede.get("id", ""))

    return zeilen, ereignisse


def main():
    dateien = sorted(QUELLE.glob("wp*_*.xml"))
    print(f"{len(dateien)} Protokolle lesen aus {QUELLE}")

    alle, alle_ereignisse, zaehler = [], [], [0]
    for pfad in dateien:
        z, e = werte_protokoll_aus(pfad, zaehler)
        alle.extend(z)
        alle_ereignisse.extend(e)


    gesehen = set()
    for z in alle:
        if z["rede_id"]:
            if z["rede_id"] in gesehen and z["protokoll_nr"] == "18/20":
                z["doppelt"] = "ja"
            gesehen.add(z["rede_id"])


    print(f"\n{'=' * 68}")
    print(f"{len(alle):,} Kommentare, {len(alle_ereignisse):,} Einzelereignisse\n")

    print("  Wo sie stehen:")
    for k, v in Counter(z["kontext"] for z in alle).most_common():
        print(f"    {v:>8,}  {k}")

    print("\n  Ereignisse je Kommentar:")
    for k, v in sorted(Counter(z["ereignisse"] for z in alle).items())[:6]:
        print(f"    {v:>8,} Kommentare haben {k}")
    mehr = sum(v for k, v in Counter(z["ereignisse"] for z in alle).items()
               if k > 6)
    print(f"    {mehr:>8,} Kommentare haben mehr als 6")

    mit = {z["rede_id"] for z in alle if z["rede_id"]}
    print(f"\n  {len(mit):,} Reden tragen mindestens einen Kommentar")

    print("\n  Je Wahlperiode:")
    for wp in sorted({z["wahlperiode"] for z in alle}):
        teil = [z for z in alle if z["wahlperiode"] == wp]
        print(f"    WP {wp}: {len(teil):>8,} Kommentare")

    print("\n  Haeufigste Einzelereignisse:")
    for k, v in Counter(e["text"][:56] for e in alle_ereignisse).most_common(8):
        print(f"    {v:>7,}  {k}")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"kommentar_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        s = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        s.writeheader()
        s.writerows(alle)
    print(f"\n{len(alle):,} Zeilen -> {pfad}")

    pfad = ZIEL / f"kommentar_ereignis_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        s = csv.DictWriter(f, fieldnames=SPALTEN_EREIGNIS, delimiter=";")
        s.writeheader()
        s.writerows(alle_ereignisse)
    print(f"{len(alle_ereignisse):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
