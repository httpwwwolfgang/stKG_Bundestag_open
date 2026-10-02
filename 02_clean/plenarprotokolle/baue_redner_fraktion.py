import csv
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from korrekturen import (KENNUNG_KORREKTUR, INTERNE_KENNUNG, OHNE_SPRECHER,
                         korrigierte_kennung, korrigierter_name)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "Parlamentsarbeit"
          / "CPP-BT_2026-01-17_DE_PQT_Reden_Gesamt.parquet")
import zwischenstand


LIEFERUNG = "cpp_bt_fobbe"
ZIEL = zwischenstand.fuer(__file__)
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"
WAHLPERIODEN = (18, 19, 20)


NAMENSFELDER = [
    ("redner_titel", "titel"),
    ("redner_vorname", "vorname"),
    ("redner_nachname", "nachname"),
    ("redner_namenszusatz", "namenszusatz"),
    ("redner_ortszusatz", "ortszusatz"),
]


MERKMALE = [
    ("name", "name_kombi"),
    ("titel", "redner_titel"),
    ("namenszusatz", "redner_namenszusatz"),
    ("ortszusatz", "redner_ortszusatz"),
    ("fraktion", "redner_fraktion"),
    ("rolle_kurz", "redner_rolle_kurz"),
    ("rolle_lang", "redner_rolle_lang"),
]


PARTIKEL = {"von", "vom", "van", "de", "del", "der", "den", "dos", "du", "zu",
            "zur", "am", "an", "graf", "graefin", "freiherr", "freifrau",
            "ritter", "prinz", "prinzessin"}

SPALTEN_REDNER = (
    ["redner_id", "kennungsart"]
    + [z for _, z in NAMENSFELDER]
    + ["schreibweisen_anzahl", "merkmale_anzahl", "mehrdeutig",
       "personen_anzahl", "reden", "erste_rede", "letzte_rede",
       "wahlperioden"])

SPALTEN_MERKMAL = ["redner_id", "art", "wert", "reden", "erste_rede",
                   "letzte_rede", "wahlperioden"]

SPALTEN_FRAKTION = ["fraktion", "redner", "reden", "erste_rede",
                    "letzte_rede", "wahlperioden"]

SPALTEN_ROLLE = ["bezeichnung", "art", "ebene", "funktion", "ressort",
                 "rohformen", "rohformen_anzahl", "redner", "reden",
                 "erste_rede", "letzte_rede", "wahlperioden"]


RESSORT = re.compile(r"\b(BM[A-Z][A-Za-z]*|BKAmt|BPA|AA|BK)\s*$")

LAND = re.compile(r"^(?P<funktion>.*?)\s*\((?P<land>[^)]+)\)\s*$")

BUNDESTAG = re.compile(r"^(Alters|Vize)?[Pp]r.sident")


def glatt(text):
    s = str(text or "").replace("­", "").replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def kennungsart(k):
    if not k or k in ("None", "nan"):
        return "ohne_kennung"
    if re.fullmatch(r"11\d{6}", k):
        return "bundestagsverwaltung"
    if k.startswith("999"):
        return "behelfskennung"
    if k == "10000":
        return "mehrfach_vergeben"
    return "sonstige"


def personenschluessel(vorname, nachname):
    woerter = re.findall(r"[a-zA-ZaeoeueszAEOEUEáàéèíóúçğşıœæ]+",
                         f"{vorname} {nachname}".lower())
    return "".join(w for w in woerter if w not in PARTIKEL)


def zerlege_rolle(bezeichnung):
    b = bezeichnung.strip()
    treffer = LAND.match(b)
    if treffer:
        return treffer.group("funktion").strip(), treffer.group("land").strip(), "land"
    treffer = RESSORT.search(b)
    if treffer:
        return b[:treffer.start()].strip(), treffer.group(1), "bund"
    if BUNDESTAG.match(b):
        return b, "", "bundestag"
    return b, "", "sonstige"


def belegzeitraum(teil):
    return {"reden": len(teil),
            "erste_rede": str(teil.sitzung_datum.min()),
            "letzte_rede": str(teil.sitzung_datum.max()),
            "wahlperioden": " | ".join(str(w) for w
                                       in sorted(set(teil.wahlperiode)))}


def main():
    print(f"CPP-BT lesen: {QUELLE.name}")
    d = pd.read_parquet(QUELLE, columns=[
        "rede_id", "wahlperiode", "sitzung_datum", "redner_id",
        "redner_titel", "redner_vorname", "redner_nachname",
        "redner_namenszusatz", "redner_ortszusatz", "redner_fraktion",
        "redner_rolle_kurz", "redner_rolle_lang"])
    d = d[d.wahlperiode.isin(WAHLPERIODEN)].copy()


    d["roh_kurz"] = d.redner_rolle_kurz.fillna("")
    d["roh_lang"] = d.redner_rolle_lang.fillna("")
    for s in d.columns:
        if s.startswith("redner"):
            d[s] = d[s].fillna("").map(glatt)
    d["redner_id"] = d.redner_id.astype(str).str.strip()


    vorher = d.redner_id.copy()
    d["redner_id"] = [korrigierte_kennung(r, k)
                      for r, k in zip(d.rede_id, d.redner_id)]
    print(f"  Kennung korrigiert bei {int((vorher != d.redner_id).sum())} Reden"
          f" ({len(KENNUNG_KORREKTUR)} umgehaengt, {len(INTERNE_KENNUNG)} auf"
          f" eine eigene Kennung, {len(OHNE_SPRECHER)} auf UNBEKANNT)")


    vorher_name = d.redner_nachname.copy()
    berichtigt = [korrigierter_name(r, t, v, n) for r, t, v, n in
                  zip(d.rede_id, d.redner_titel, d.redner_vorname,
                      d.redner_nachname)]
    d["redner_titel"] = [x[0] for x in berichtigt]
    d["redner_vorname"] = [x[1] for x in berichtigt]
    d["redner_nachname"] = [x[2] for x in berichtigt]
    print(f"  Name korrigiert bei "
          f"{int((vorher_name != d.redner_nachname).sum())} Reden")
    d["name_kombi"] = (d.redner_vorname + " " + d.redner_nachname).map(glatt)
    print(f"  {len(d):,} Reden der Wahlperioden "
          f"{', '.join(str(w) for w in WAHLPERIODEN)}")

    zeilen, merkmale, mehrdeutige = [], [], []

    for kennung, g in d.groupby("redner_id", sort=True):
        zeile = {"redner_id": kennung, "kennungsart": kennungsart(kennung)}


        for quelle, ziel in NAMENSFELDER:
            zeile[ziel] = Counter(g[quelle]).most_common(1)[0][0]


        eigene = 0
        for art, spalte in MERKMALE:
            for wert, teil in g[g[spalte] != ""].groupby(spalte):
                merkmale.append({"redner_id": kennung, "art": art,
                                 "wert": wert, **belegzeitraum(teil)})
                eigene += 1
        zeile["merkmale_anzahl"] = eigene

        kombis = {tuple(getattr(r, q) for q, _ in NAMENSFELDER)
                  for r in g.itertuples(index=False)}
        zeile["schreibweisen_anzahl"] = len(kombis)


        personen = {personenschluessel(r.redner_vorname, r.redner_nachname)
                    for r in g.itertuples(index=False)}
        zeile["mehrdeutig"] = len(personen) > 1
        zeile["personen_anzahl"] = len(personen)
        if len(personen) > 1:
            mehrdeutige.append((kennung, len(g), sorted(set(g["name_kombi"]))))

        zeile.update(belegzeitraum(g))
        zeilen.append(zeile)

    fraktionen = []
    for name, g in d[d.redner_fraktion != ""].groupby("redner_fraktion"):
        fraktionen.append({"fraktion": name, "redner": g.redner_id.nunique(),
                           **belegzeitraum(g)})
    fraktionen.sort(key=lambda z: -z["reden"])


    rollen = []
    for art, spalte, rohspalte in [("kurz", "redner_rolle_kurz", "roh_kurz"),
                                   ("lang", "redner_rolle_lang", "roh_lang")]:
        for wert, g in d[d[spalte] != ""].groupby(spalte):
            funktion, ressort, ebene = zerlege_rolle(wert)
            rohformen = sorted({r for r in g[rohspalte] if r and r != wert})
            rollen.append({
                "bezeichnung": wert, "art": art, "ebene": ebene,
                "funktion": funktion, "ressort": ressort,
                "rohformen": " | ".join(rohformen),
                "rohformen_anzahl": len(rohformen) + 1,
                "redner": g.redner_id.nunique(), **belegzeitraum(g)})
    rollen.sort(key=lambda z: (z["art"], -z["reden"]))


    trenner = "=" * 70
    print(f"\n{trenner}")
    print(f"{len(zeilen):,} Redner-Kennungen, {len(merkmale):,} Merkmalszeilen\n")
    for art, n in Counter(z["kennungsart"] for z in zeilen).most_common():
        reden = sum(z["reden"] for z in zeilen if z["kennungsart"] == art)
        print(f"  {art:<24} {n:>6,} Kennungen  {reden:>7,} Reden")

    print("\nMerkmalszeilen je Art:")
    je_art = Counter(m["art"] for m in merkmale)
    mit_wechsel = Counter()
    for art in je_art:
        je_kennung = Counter(m["redner_id"] for m in merkmale
                             if m["art"] == art)
        mit_wechsel[art] = sum(1 for v in je_kennung.values() if v > 1)
    for art, n in je_art.most_common():
        print(f"  {art:<16} {n:>6,} Zeilen   davon {mit_wechsel[art]:>4} "
              f"Kennungen mit mehr als einem Wert")

    print(f"\n  {len(mehrdeutige)} Kennungen, bei denen Kennung und Name "
          f"auseinandergehen ({sum(n for _, n, _ in mehrdeutige):,} Reden) — "
          f"gekennzeichnet, nicht aufgeloest:")
    for kennung, n, namen in sorted(mehrdeutige, key=lambda x: -x[1])[:12]:
        print(f"    {kennung:<12} {n:>4} Reden  {' / '.join(namen)[:78]}")

    print(f"\n{len(fraktionen)} Fraktionen:")
    for f in fraktionen:
        print(f"  {f['reden']:>7,} Reden  {f['redner']:>4} Redner  "
              f"WP {f['wahlperioden']:<14} {f['fraktion']}")
    ohne = int((d.redner_fraktion == "").sum())
    print(f"\n  {ohne:,} Reden ohne Fraktionsangabe "
          f"({ohne / len(d) * 100:.1f} %) — Regierungsmitglieder und Gaeste, "
          f"die eine Rolle statt einer Fraktion tragen")


    ZIEL.mkdir(parents=True, exist_ok=True)
    for name, daten, spalten in [("redner", zeilen, SPALTEN_REDNER),
                                 ("redner_merkmal", merkmale, SPALTEN_MERKMAL),
                                 ("rolle", rollen, SPALTEN_ROLLE),
                                 ("fraktion", fraktionen, SPALTEN_FRAKTION)]:
        pfad = ZIEL / f"{name}_{STEMPEL}.csv"
        with pfad.open("w", encoding="utf-8", newline="") as f:
            schreiber = csv.DictWriter(f, fieldnames=spalten, delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(daten)
        print(f"{len(daten):>7,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
