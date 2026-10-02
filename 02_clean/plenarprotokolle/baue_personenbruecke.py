import csv
import re
import sys
import unicodedata
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


TITEL = {"dr.", "dr", "prof.", "prof", "h.", "c.", "h.c.", "med.", "jur.",
         "rer.", "nat.", "phil.", "ing.", "dipl.", "alterspraesident",
         "alterspräsident"}

SPALTEN = ["person_id", "redner_id", "dip_titel", "protokoll_name",
           "aktivitaeten", "reden", "lage"]

PERSON_SPALTEN = ["redner_id", "person_id", "name", "kennungsart",
                  "rolle_dip", "dip_titel", "reden", "aktivitaeten", "lage"]


def neueste(muster):
    treffer = sorted(ZIEL.glob(muster))
    if not treffer:
        raise SystemExit(f"Keine Datei zu {muster} in {ZIEL}")
    return treffer[-1]


def lies(pfad, trenner=";"):
    with open(pfad, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=trenner))


def schriftgleich(text):
    zerlegt = unicodedata.normalize("NFD", str(text or ""))
    ohne = "".join(z for z in zerlegt
                   if unicodedata.category(z) != "Mn" or z in "̈")
    return re.sub(r"\s+", " ",
                  unicodedata.normalize("NFC", ohne)).strip().lower()


def rolle_aus(titel):
    t = str(titel or "")
    if "," not in t:
        return ""
    return t.split(",", 1)[1].split(",")[0].strip()


def main():
    verzeichnis = lies(neueste("redner_2*.csv"))
    akt = lies(ARCHIV / "aktivitaet_20260828_011252.csv")
    print(f"Rednerverzeichnis: {len(verzeichnis):,} Kennungen")
    print(f"Aktivitaeten:      {len(akt):,}")


    reden_je_kennung = Counter()
    for x in verzeichnis:
        reden_je_kennung[x["redner_id"]] = int(x.get("reden") or 0)
    akt_je_person = Counter(str(a["person_id"]).strip() for a in akt)


    schreibungen = defaultdict(set)
    for x in lies(neueste("redner_merkmal_*.csv")):
        if x["art"] == "name" and x["redner_id"]:
            schreibungen[x["redner_id"]].add(x["wert"])


    unbrauchbar = set()
    for kennung, werte in schreibungen.items():
        if len(werte) < 2:
            continue
        mengen = [set(schriftgleich(w).split()) - TITEL for w in werte]
        if not set.intersection(*mengen):
            unbrauchbar.add(kennung)
    print(f"\n{len(unbrauchbar)} Kennungen tragen mehrere Personen und werden "
          f"nicht verwendet:")
    for k in sorted(unbrauchbar):
        print(f"    {k}: {sorted(schreibungen[k])}")


    namen = defaultdict(list)
    ohne_namen = 0
    eintrag = {x["redner_id"]: x for x in verzeichnis}
    for kennung, werte in schreibungen.items():
        if kennung in unbrauchbar or kennung not in eintrag:
            ohne_namen += 1
            continue
        for w in werte:
            wörter = tuple(sorted(set(schriftgleich(w).split()) - TITEL))
            if wörter:
                namen[wörter].append(eintrag[kennung])
    mehrfach = {k: v for k, v in namen.items()
                if len({e["redner_id"] for e in v}) > 1}
    print(f"\n{len(namen):,} verschiedene Vor+Nachname-Kombinationen")
    print(f"  {len(mehrfach)} davon bei mehreren Kennungen — dort wird nicht "
          f"zugeordnet:")
    for (nach, vor), eintraege in list(mehrfach.items())[:8]:
        print(f"    {vor} {nach}: {', '.join(e['redner_id'] for e in eintraege)}")
    print(f"  {ohne_namen} Kennungen ohne verwertbaren Namen oder mit "
          f"Behelfskennung 999xxxxxx")


    dip = {}
    for a in akt:
        dip.setdefault(str(a["person_id"]).strip(), a["titel"])

    zeilen = []
    lage = Counter()
    for person, titel in sorted(dip.items(), key=lambda x: int(x[0] or 0)):
        t = schriftgleich(titel)
        worte = set(t.replace(",", " ").split()) - TITEL
        treffer = [e for schreibung, eintraege in namen.items()
                   if set(schreibung) <= worte for e in eintraege]
        kennungen = {e["redner_id"] for e in treffer}

        if not kennungen:
            lage["kein Namenstreffer im Rednerverzeichnis"] += 1
            zeilen.append({
                "person_id": person, "redner_id": "", "dip_titel": titel,
                "protokoll_name": "", "aktivitaeten": akt_je_person[person],
                "reden": "", "lage": "kein Namenstreffer im Rednerverzeichnis",
            })
            continue


        status = ("eindeutig" if len(kennungen) == 1
                  else "dieselbe Person in mehreren Rollen")
        for e in {e["redner_id"]: e for e in treffer}.values():
            zeilen.append({
                "person_id": person, "redner_id": e["redner_id"],
                "dip_titel": titel,
                "protokoll_name": f"{e['vorname']} {e['nachname']}".strip(),
                "aktivitaeten": akt_je_person[person],
                "reden": reden_je_kennung.get(e["redner_id"], 0),
                "lage": status,
            })
        lage[status] += 1


    print(f"\n{'=' * 70}")
    print(f"{len(zeilen):,} DIP-person_id geprueft\n")
    for k, v in lage.most_common():
        print(f"  {v:>6,}  {k}")

    SICHER = {"eindeutig", "dieselbe Person in mehreren Rollen"}
    verbunden = [z for z in zeilen if z["lage"] in SICHER]
    print(f"\n  Die {len({z["person_id"] for z in verbunden}):,} verbundenen person_id decken "
          f"{sum(z['aktivitaeten'] for z in {v['person_id']: v for v in verbunden}.values()):,} der {len(akt):,} "
          f"Aktivitaeten ab")

    offen = [z for z in zeilen if z["lage"] not in SICHER]
    print(f"  Die {len(offen)} offenen betreffen "
          f"{sum(z['aktivitaeten'] for z in offen):,} Aktivitaeten")

    print("\n  Offene Faelle im einzelnen:")
    for z in sorted(offen, key=lambda x: -x["aktivitaeten"])[:20]:
        print(f"    person_id {z['person_id']:>5}  "
              f"{z['aktivitaeten']:>4} Aktivitaeten  {z['dip_titel'][:44]:<46}"
              f"  {z['lage'][:34]}")
    if len(offen) > 20:
        print(f"    ... und {len(offen) - 20} weitere in der CSV")


    gedeckt = {z["redner_id"] for z in verbunden}
    fehlend = [x for x in verzeichnis
               if x["redner_id"] not in gedeckt
               and not str(x["redner_id"]).startswith("999")]
    print(f"\n  Gegenprobe: {len(fehlend):,} der {len(verzeichnis):,} "
          f"Protokoll-Kennungen haben kein DIP-Gegenstueck")
    print(f"    zusammen {sum(int(x.get('reden') or 0) for x in fehlend):,} Reden")
    for x in sorted(fehlend, key=lambda y: -int(y.get("reden") or 0))[:8]:
        print(f"      {x['redner_id']}  {x['reden']:>4} Reden  "
              f"{x['vorname']} {x['nachname']}")


    je_kennung = defaultdict(list)
    for z in zeilen:
        if z["redner_id"]:
            je_kennung[z["redner_id"]].append(z)

    personen = []
    for x in verzeichnis:
        treffer = je_kennung.get(x["redner_id"], [])
        dip = treffer[0] if treffer else {}
        personen.append({
            "redner_id": x["redner_id"],
            "person_id": ", ".join(sorted({t["person_id"] for t in treffer})),
            "name": f"{x['vorname']} {x['nachname']}".strip(),
            "kennungsart": x["kennungsart"],
            "rolle_dip": rolle_aus(dip.get("dip_titel", "")),
            "dip_titel": dip.get("dip_titel", ""),
            "reden": x["reden"],
            "aktivitaeten": dip.get("aktivitaeten", 0),
            "lage": ("beide Seiten" if treffer
                     else "nur im Protokoll — keine DIP-Aktivitaet"),
        })

    verbundene_ids = {t["person_id"] for t in zeilen if t["redner_id"]}
    for z in zeilen:
        if z["redner_id"] or z["person_id"] in verbundene_ids:
            continue
        personen.append({
            "redner_id": "", "person_id": z["person_id"],
            "name": str(z["dip_titel"]).split(",")[0].strip(),
            "kennungsart": "nur_dip",
            "rolle_dip": rolle_aus(z["dip_titel"]),
            "dip_titel": z["dip_titel"], "reden": 0,
            "aktivitaeten": z["aktivitaeten"],
            "lage": "nur im DIP — im Plenum nie als Redner gefuehrt",
        })

    print(f"\n{'=' * 70}")
    print(f"Personenliste: {len(personen):,} Zeilen\n")
    for k, v in Counter(p["lage"] for p in personen).most_common():
        print(f"  {v:>6,}  {k}")
    print("\n  Nach Rolle laut DIP:")
    for k, v in Counter(p["rolle_dip"] for p in personen).most_common(12):
        print(f"    {v:>5,}  {k or '(keine Angabe)'}")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"personenbruecke_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)
    print(f"\n{len(zeilen):,} Zeilen -> {pfad}")

    pfad = ZIEL / f"person_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=PERSON_SPALTEN, delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(personen)
    print(f"{len(personen):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
