import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand
ZIEL = zwischenstand.fuer(__file__)
ARCHIV = zwischenstand.ordner("01_fetch", "dip",
                              "aktivitaeten_20260828")
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"

SPALTEN = ["rede_id", "deskriptor", "typ", "ist_rede", "eindeutig", "belege"]


def neueste(muster):
    treffer = sorted(ZIEL.glob(muster))
    if not treffer:
        raise SystemExit(f"Keine Datei zu {muster} — erst "
                         f"ordne_rede_aktivitaet.py laufen lassen.")
    return treffer[-1]


def lies(pfad, trenner=";"):
    with open(pfad, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=trenner))


def main():
    zuordnung = neueste("rede_aktivitaet_*.csv")
    print(f"Zuordnung: {zuordnung.name}")
    zu = lies(zuordnung)

    desk = lies(ARCHIV / "aktivitaet_deskriptor_20260828_011252.csv")
    print(f"Deskriptoren: {len(desk):,} Zeilen")

    je_aktivitaet = defaultdict(list)
    for z in desk:
        je_aktivitaet[z["aktivitaet_id"].strip()].append((z["name"], z["typ"]))


    SICHER = {"fundstelle_und_person", "nur_person", "im_bereich",
              "dip_namensfehler"}
    treffer = defaultdict(lambda: {"belege": 0, "ist_rede": "",
                                   "eindeutig": ""})
    for z in zu:
        if z["zuordnung"] not in SICHER:
            continue
        for name, typ in je_aktivitaet.get(z["aktivitaet_id"].strip(), []):
            e = treffer[(z["rede_id"], name, typ)]
            e["belege"] += 1


            if z["ist_rede"] == "ja":
                e["ist_rede"] = "ja"
            if z["zuordnung"] in SICHER:
                e["eindeutig"] = "ja"

    zeilen = [{"rede_id": r, "deskriptor": n, "typ": t,
               "ist_rede": e["ist_rede"], "eindeutig": e["eindeutig"],
               "belege": e["belege"]}
              for (r, n, t), e in treffer.items()]
    zeilen.sort(key=lambda z: (z["rede_id"], z["typ"], z["deskriptor"]))


    print(f"\n{'=' * 70}")
    print(f"{len(zeilen):,} Zeilen: je Rede ein Deskriptor\n")

    reden = {z["rede_id"] for z in zeilen}
    nur_rede = {z["rede_id"] for z in zeilen if z["ist_rede"] == "ja"}
    print(f"  {len(reden):>7,} Reden haben mindestens einen Deskriptor")
    print(f"  {len(nur_rede):>7,} davon ueber eine Aktivitaet, die im DIP "
          f"als Rede gefuehrt ist")

    je_rede = Counter(z["rede_id"] for z in zeilen)
    werte = sorted(je_rede.values())
    print(f"\n  Deskriptoren je Rede: im Schnitt "
          f"{sum(werte) / len(werte):.1f}, Median {werte[len(werte) // 2]}, "
          f"hoechstens {max(werte)}")

    print("\n  Nach Typ:")
    for typ, v in Counter(z["typ"] for z in zeilen).most_common():
        n = len({z["rede_id"] for z in zeilen if z["typ"] == typ})
        print(f"    {v:>8,} Zeilen  {typ:<22} in {n:>6,} Reden")

    print("\n  Haeufigste Geographische Begriffe:")
    geo = Counter(z["deskriptor"] for z in zeilen
                  if z["typ"] == "Geograph. Begriffe")
    for k, v in geo.most_common(10):
        print(f"    {v:>6,}  {k}")

    print("\n  Haeufigste Sachbegriffe:")
    sach = Counter(z["deskriptor"] for z in zeilen
                   if z["typ"] == "Sachbegriffe")
    for k, v in sach.most_common(10):
        print(f"    {v:>6,}  {k}")

    unsicher = sum(1 for z in zeilen if z["eindeutig"] != "ja")
    print(f"\n  {unsicher:,} Zeilen stammen ausschliesslich aus einer "
          f"mehrdeutigen Fundstelle")
    print(f"    (zwei Reden im selben Seitenviertel — Kandidat, "
          f"keine gesicherte Zuordnung)")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"rede_deskriptor_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)
    print(f"\n{len(zeilen):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
