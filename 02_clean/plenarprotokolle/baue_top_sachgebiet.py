import csv
import glob
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand
ZIEL = zwischenstand.fuer(__file__)
DIP = sorted((zwischenstand.ordner("01_fetch", "dip", "export"))
             .glob("dokumente_*"))[-1] if list(
    (HIER.parents[1] / "01_fetch" / "dip" / "export").glob("dokumente_*")
) else None
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"

SPALTEN = ["protokoll_nr", "top_id", "lfd", "sachgebiet", "drucksache",
           "vorgang_id", "vorgangstyp"]


def neueste(muster):
    treffer = sorted(ZIEL.glob(muster))
    if not treffer:
        raise SystemExit(f"Keine Datei zu {muster} in {ZIEL}")
    return treffer[-1]


def lies(pfad, trenner=","):
    with open(pfad, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=trenner))


def main():
    if DIP is None:
        raise SystemExit("Kein DIP-Dokumentenabzug gefunden.")
    print(f"DIP-Abzug: {DIP.name}")


    sachgebiet = defaultdict(set)
    for f in sorted(DIP.glob("vorgang_sachgebiet_wp*.csv")):
        for z in lies(f):
            sachgebiet[z["vorgang_id"].strip()].add(z["sachgebiet"])
    print(f"  {len(sachgebiet):,} Vorgaenge mit Sachgebiet")


    zu_vorgang = defaultdict(set)
    typ = {}
    for f in sorted(DIP.glob("vorgangsposition_wp*.csv")):
        for z in lies(f):
            nummer = str(z.get("dokumentnummer") or "").strip()
            vid = str(z.get("vorgang_id") or "").strip()
            if nummer and vid and str(z.get("dokumentart") or "") == "Drucksache":
                zu_vorgang[nummer].add(vid)
                typ[vid] = z.get("vorgangstyp", "")
    print(f"  {len(zu_vorgang):,} Drucksachennummern zeigen auf Vorgaenge")

    tops = lies(neueste("tagesordnungspunkt_2*.csv"), ";")
    zeilen, lage = [], Counter()
    for t in tops:
        nummern = [n.strip() for n in str(t.get("drucksachen") or "").split(",")
                   if n.strip()]
        if not nummern:
            lage["keine Drucksachennummer im Punkt"] += 1
            continue
        gefunden = False
        for nummer in nummern:
            for vid in sorted(zu_vorgang.get(nummer, ())):
                for sg in sorted(sachgebiet.get(vid, ())):
                    zeilen.append({
                        "protokoll_nr": t["protokoll_nr"], "top_id": t["top_id"],
                        "lfd": t["lfd"], "sachgebiet": sg, "drucksache": nummer,
                        "vorgang_id": vid, "vorgangstyp": typ.get(vid, ""),
                    })
                    gefunden = True
        lage["Sachgebiet gefunden" if gefunden
             else "Drucksache da, aber kein Sachgebiet"] += 1


    print(f"\n{'=' * 68}")
    print(f"{len(zeilen):,} Zeilen: je Tagesordnungspunkt ein Sachgebiet\n")
    for k, v in lage.most_common():
        print(f"  {v:>5,}  {k}")

    punkte = {(z["protokoll_nr"], z["top_id"], z["lfd"]) for z in zeilen}
    print(f"\n  {len(punkte):,} von {len(tops):,} Tagesordnungspunkten "
          f"haben ein Sachgebiet")

    je_punkt = Counter((z["protokoll_nr"], z["top_id"], z["lfd"])
                       for z in zeilen)
    anzahl = Counter(len({s for s in [z["sachgebiet"] for z in zeilen
                                      if (z["protokoll_nr"], z["top_id"],
                                          z["lfd"]) == p]})
                     for p in list(punkte)[:0]) or None
    verschiedene = defaultdict(set)
    for z in zeilen:
        verschiedene[(z["protokoll_nr"], z["top_id"], z["lfd"])].add(
            z["sachgebiet"])
    print("\n  Verschiedene Sachgebiete je Punkt:")
    for k, v in sorted(Counter(len(s) for s in verschiedene.values()).items())[:6]:
        print(f"    {v:>5,} Punkte haben {k}")
    mehr = sum(v for k, v in Counter(
        len(s) for s in verschiedene.values()).items() if k > 6)
    print(f"    {mehr:,} Punkte haben mehr als 6")


    zuordnung = (lies(neueste("rede_tagesordnungspunkt_2*.csv"), ";")
                 + lies(neueste("anlage_rede_tagesordnungspunkt_*.csv"), ";"))
    mit = sum(1 for z in zuordnung
              if (z["protokoll_nr"], z["top_id"], z["lfd"]) in verschiedene)
    print(f"\n  {mit:,} der {len(zuordnung):,} zugeordneten Reden erben "
          f"darueber ein Sachgebiet")

    print("\n  Haeufigste Sachgebiete:")
    for k, v in Counter(z["sachgebiet"] for z in zeilen).most_common(10):
        print(f"    {v:>6,}  {k}")


    vorgang_desk = defaultdict(list)
    for f in sorted(DIP.glob("vorgang_deskriptor_wp*.csv")):
        for z in lies(f):
            vorgang_desk[z["vorgang_id"].strip()].append(
                (z["name"], z["typ"]))
    print(f"\n  {len(vorgang_desk):,} Vorgaenge mit Deskriptoren")

    desk_zeilen, gesehen = [], set()
    for z in zeilen:
        schluessel = (z["protokoll_nr"], z["top_id"], z["lfd"])
        for name, typ in vorgang_desk.get(z["vorgang_id"], ()):
            if (schluessel, name, typ) in gesehen:
                continue
            gesehen.add((schluessel, name, typ))
            desk_zeilen.append({
                "protokoll_nr": z["protokoll_nr"], "top_id": z["top_id"],
                "lfd": z["lfd"], "deskriptor": name, "typ": typ,
                "vorgang_id": z["vorgang_id"],
            })

    punkte_desk = {(z["protokoll_nr"], z["top_id"], z["lfd"])
                   for z in desk_zeilen}
    print(f"  {len(desk_zeilen):,} Zeilen fuer {len(punkte_desk):,} Punkte")
    print("  Nach Typ:")
    for typ, v in Counter(z["typ"] for z in desk_zeilen).most_common():
        print(f"    {v:>7,}  {typ}")

    mit_desk = sum(1 for z in zuordnung
                   if (z["protokoll_nr"], z["top_id"], z["lfd"]) in punkte_desk)
    print(f"  {mit_desk:,} Reden erben darueber Deskriptoren")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"top_sachgebiet_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)
    print(f"\n{len(zeilen):,} Zeilen -> {pfad}")

    pfad = ZIEL / f"top_deskriptor_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(
            f, fieldnames=["protokoll_nr", "top_id", "lfd", "deskriptor",
                           "typ", "vorgang_id"], delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(desk_zeilen)
    print(f"{len(desk_zeilen):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
