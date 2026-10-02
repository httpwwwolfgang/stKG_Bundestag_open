import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from korrekturen import korrigierter_vorname

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HIER = Path(__file__).resolve().parent
import zwischenstand
ZIEL = zwischenstand.fuer(__file__)
QUELLE = HIER.parents[3] / "Daten" / "Parlamentsarbeit"
ARCHIV = zwischenstand.ordner("01_fetch", "dip",
                              "aktivitaeten_20260828")
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"


DIP_SEITE = re.compile(r"^(\d+)\s*([A-D])$", re.IGNORECASE)


REDEARTEN = {"Rede", "Rede (zu Protokoll gegeben)", "Kurzintervention",
             "Erwiderung"}

ZUGEORDNET = {"fundstelle_und_person", "nur_person", "im_bereich",
              "dip_namensfehler"}


QUADRANT = {"A": 0, "B": 1, "C": 2, "D": 3}


GRADE = {"dr.", "dr", "prof.", "prof", "h.", "c.", "h.c.", "med.", "jur.",
         "rer.", "nat.", "phil.", "ing.", "dipl."}

SPALTEN = ["rede_id", "aktivitaet_id", "zuordnung", "protokoll_nr", "seite",
           "quadrant", "fundstelle", "aktivitaetsart", "ist_rede",
           "person_id", "redner_id", "kandidaten", "deskriptoren",
           "vorgang_ids", "vorgaenge_abgeschnitten"]


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


def position(seite, quadrant):
    try:
        return int(str(seite).strip()) * 4 + QUADRANT[str(quadrant).strip().upper()]
    except (ValueError, KeyError):
        return None


def passt_person_mit_alias(namen, aliase, titel):
    worte = set(schriftgleich(titel).replace(",", " ").split())
    if namen and namen <= worte:
        return True
    return any(a and a <= worte for a in aliase)


def passt_person(namen, titel):
    if not namen:
        return False
    return namen <= set(schriftgleich(titel).replace(",", " ").split())


def zeile(a, rede_id, kennung, zuordnung, kandidaten, seite, quadrant, desk):
    art = a["aktivitaetsart"] or ""
    vids = [x.strip() for x in
            str(a["vorgang_ids"] or "").replace("|", ",").split(",")
            if x.strip()]
    try:
        angekuendigt = int(a["vorgangsbezug_anzahl"] or 0)
    except ValueError:
        angekuendigt = 0
    return {
        "rede_id": rede_id, "aktivitaet_id": a["aktivitaet_id"],
        "zuordnung": zuordnung, "protokoll_nr": a["protokoll_nr"],
        "seite": seite, "quadrant": quadrant,
        "fundstelle": f"{seite} {quadrant}".strip(),
        "aktivitaetsart": art, "ist_rede": "ja" if art in REDEARTEN else "",
        "person_id": a["person_id"], "redner_id": kennung,
        "kandidaten": kandidaten,
        "deskriptoren": desk.get(a["aktivitaet_id"].strip(), 0),
        "vorgang_ids": ",".join(vids),
        "vorgaenge_abgeschnitten": "ja" if angekuendigt > len(vids) else "",
    }


def main():
    fund = lies(neueste("fundstelle_*.csv"))
    akt = lies(ARCHIV / "aktivitaet_20260828_011252.csv")
    akt_je_id = {a["aktivitaet_id"]: a for a in akt}
    desk = Counter(z["aktivitaet_id"].strip() for z in
                   lies(ARCHIV / "aktivitaet_deskriptor_20260828_011252.csv"))
    r = pd.read_parquet(neueste("rede_*.parquet"),
                        columns=["rede_id", "redner_id", "protokoll_nr"])
    prot_je_rede = dict(zip(r.rede_id, r.protokoll_nr))
    kennung_je_rede = {a: str(b).strip() for a, b in zip(r.rede_id, r.redner_id)}
    bestand = set(r.rede_id)


    korpus = sorted(QUELLE.glob("CPP-BT_*_Reden_Gesamt.parquet"))[-1]
    n = pd.read_parquet(korpus, columns=["rede_id", "redner_vorname",
                                         "redner_nachname"])
    name_je_rede = {
        rid: set(schriftgleich(
            f"{korrigierter_vorname(rid, v) or ''} {na or ''}"
        ).split()) - GRADE
        for rid, v, na in zip(n.rede_id, n.redner_vorname, n.redner_nachname)}


    alias_je_kennung = defaultdict(list)
    for x in lies(neueste("redner_merkmal_*.csv")):
        if x["art"] == "name" and x["redner_id"]:
            alias_je_kennung[x["redner_id"]].append(
                set(schriftgleich(x["wert"]).split()) - GRADE)

    bruecke = defaultdict(set)
    for z in lies(neueste("personenbruecke_*.csv")):
        if z["redner_id"]:
            bruecke[str(z["person_id"]).strip()].add(z["redner_id"])

    print(f"{len(fund):,} Fundstellen, {len(akt):,} Aktivitaeten, "
          f"{len(bruecke):,} Personen in der Bruecke")


    an_stelle = defaultdict(list)
    fund_je_rede = {z["rede_id"]: z for z in fund}


    stellen_je_protokoll = defaultdict(list)
    for z in fund:
        if z["rede_id"] not in bestand:
            continue
        lage = position(z.get("seite"), z.get("quadrant"))
        if lage is not None:
            stellen_je_protokoll[z["protokoll_nr"].strip()].append(
                (lage, z["rede_id"]))
    for z in fund:
        if z["rede_id"] not in bestand:
            continue
        kennung = kennung_je_rede.get(z["rede_id"], "")
        if z["seite"] and z["quadrant"]:
            an_stelle[(z["protokoll_nr"].strip(), z["seite"].strip(),
                       z["quadrant"].strip().upper())].append(z["rede_id"])


    akt_je_person = defaultdict(list)
    for a in akt:
        for kennung in bruecke.get(str(a["person_id"]).strip(), ()):
            akt_je_person[(a["protokoll_nr"].strip(), kennung)].append(a)


    zeilen = []
    verbraucht = set()
    for a in akt:
        treffer = DIP_SEITE.match(str(a["seite"] or "").strip())
        if not treffer:
            continue
        seite, quadrant = treffer.group(1), treffer.group(2).upper()
        kandidaten = an_stelle.get(
            (a["protokoll_nr"].strip(), seite, quadrant), [])
        if not kandidaten:
            continue


        passend = [k for k in kandidaten
                   if passt_person_mit_alias(
                       name_je_rede.get(k, set()),
                       alias_je_kennung.get(kennung_je_rede.get(k, ""), []),
                       a["titel"])]

        if len(passend) == 1:
            art, gewaehlt = "fundstelle_und_person", passend
        elif len(passend) > 1:
            art, gewaehlt = "offen", passend
        else:
            art, gewaehlt = "person_passt_nicht", kandidaten

        for rid in gewaehlt:
            zeilen.append(zeile(a, rid, kennung_je_rede.get(rid, ""), art,
                                len(kandidaten), seite, quadrant, desk))
            if art in ZUGEORDNET:
                verbraucht.add(rid)


    verbrauchte_akt = {z["aktivitaet_id"] for z in zeilen
                       if z["zuordnung"] in ZUGEORDNET}
    offen_je_person = defaultdict(list)
    for z in fund:
        rid = z["rede_id"]
        if rid not in bestand or rid in verbraucht:
            continue
        kennung = kennung_je_rede.get(rid, "")
        if kennung:
            offen_je_person[(z["protokoll_nr"].strip(), kennung)].append(rid)

    for schluessel, reden in offen_je_person.items():
        frei = [a for a in akt_je_person.get(schluessel, [])
                if a["aktivitaet_id"] not in verbrauchte_akt
                and passt_person_mit_alias(
                    name_je_rede.get(reden[0], set()),
                    alias_je_kennung.get(schluessel[1], []), a["titel"])]
        if len(reden) != 1 or len(frei) != 1:
            continue
        z = fund_je_rede.get(reden[0], {})
        zeilen.append(zeile(frei[0], reden[0], schluessel[1], "nur_person", 1,
                            z.get("seite", ""), z.get("quadrant", ""), desk))
        verbraucht.add(reden[0])
        verbrauchte_akt.add(frei[0]["aktivitaet_id"])


    im_bereich = 0
    for a in akt:
        von = position(a["anfangsseite"], a["anfangsquadrant"])
        bis = position(a["endseite"], a["endquadrant"])
        if von is None or bis is None or bis < von:
            continue
        for stelle, rid in stellen_je_protokoll.get(a["protokoll_nr"].strip(), ()):
            if not von <= stelle <= bis or rid in verbraucht:
                continue
            if not passt_person_mit_alias(
                    name_je_rede.get(rid, set()),
                    alias_je_kennung.get(kennung_je_rede.get(rid, ""), []),
                    a["titel"]):
                continue
            z = fund_je_rede.get(rid, {})
            zeilen.append(zeile(a, rid, kennung_je_rede.get(rid, ""),
                                "im_bereich", 1, z.get("seite", ""),
                                z.get("quadrant", ""), desk))
            verbraucht.add(rid)
            im_bereich += 1
    print(f"  {im_bereich:,} Reden ueber den Bereich der Aktivitaet zugeordnet "
          f"(Befragung: eine Aktivitaet, viele Antworten)")


    reden_je_person = Counter()
    for rid, kennung in kennung_je_rede.items():
        if rid in bestand:
            reden_je_person[(str(prot_je_rede.get(rid, "")).strip(), kennung)] += 1
    akt_je_dip = Counter()
    for a in akt:
        akt_je_dip[(a["protokoll_nr"].strip(), str(a["person_id"]).strip())] += 1

    namensfehler = 0
    for z in zeilen:
        if z["zuordnung"] != "person_passt_nicht" or z["rede_id"] in verbraucht:
            continue
        a = akt_je_id.get(z["aktivitaet_id"])
        if a is None or z["aktivitaet_id"] in verbrauchte_akt:
            continue

        person = str(a["person_id"]).strip()
        protokoll = a["protokoll_nr"].strip()
        ihre_kennungen = bruecke.get(person, set())
        ihre_reden = sum(reden_je_person.get((protokoll, k), 0)
                         for k in ihre_kennungen)
        if akt_je_dip[(protokoll, person)] <= ihre_reden:
            continue
        z["zuordnung"] = "dip_namensfehler"
        verbraucht.add(z["rede_id"])
        verbrauchte_akt.add(z["aktivitaet_id"])
        namensfehler += 1
    print(f"  {namensfehler:,} Reden zugeordnet, wo das DIP den Namen "
          f"verwechselt hat (Bilanz aus Reden und Aktivitaeten)")


    RANG = {"fundstelle_und_person": 0, "nur_person": 1, "im_bereich": 2,
            "dip_namensfehler": 3, "person_passt_nicht": 4, "offen": 5}
    beste = {}
    for z in zeilen:
        schluessel = (z["rede_id"], z["aktivitaet_id"])
        alt = beste.get(schluessel)
        if alt is None or RANG.get(z["zuordnung"], 9) < RANG.get(alt["zuordnung"], 9):
            beste[schluessel] = z
    doppelt = len(zeilen) - len(beste)
    if doppelt:
        print(f"  {doppelt} doppelte Paare aufgeloest (erst offen, dann "
              f"zugeordnet)")
    zeilen = list(beste.values())


    vergeben = {z["rede_id"] for z in zeilen if z["zuordnung"] in ZUGEORDNET}
    for rid in sorted(bestand - vergeben):
        leer = {s: "" for s in SPALTEN}
        leer.update({"rede_id": rid, "aktivitaet_id": "",
                     "zuordnung": "unbekannt",
                     "protokoll_nr": prot_je_rede.get(rid, ""),
                     "redner_id": kennung_je_rede.get(rid, ""),
                     "kandidaten": 0, "deskriptoren": 0})
        zeilen.append(leer)
    print(f"  {len(bestand - vergeben):,} Reden ohne Aktivitaet als "
          f"`unbekannt` vermerkt")


    print(f"\n{'=' * 70}")
    print(f"{len(zeilen):,} Zuordnungszeilen\n")
    for k, v in Counter(z["zuordnung"] for z in zeilen).most_common():
        marke = "zugeordnet" if k in ZUGEORDNET else ""
        print(f"  {v:>7,}  {k:<22} {marke}")

    zugeordnet = {z["rede_id"] for z in zeilen if z["zuordnung"] in ZUGEORDNET}
    offen = {z["rede_id"] for z in zeilen
             if z["zuordnung"] == "offen"} - zugeordnet
    fremd = {z["rede_id"] for z in zeilen
             if z["zuordnung"] == "person_passt_nicht"} - zugeordnet - offen
    leer = bestand - zugeordnet - offen - fremd

    print(f"\n  Von den {len(bestand):,} Reden des Bestands:")
    print(f"    {len(zugeordnet):>7,}  ZUGEORDNET")
    print(f"    {len(offen):>7,}  OFFEN — mehrere Kandidaten")
    print(f"    {len(fremd):>7,}  nur Aktivitaeten fremder Personen")
    print(f"    {len(leer):>7,}  keine Aktivitaet an ihrer Fundstelle")
    print(f"    {len(zugeordnet) + len(offen) + len(fremd) + len(leer):>7,}  "
          f"Summe")

    print("\n  Wo es hakt — die nicht zugeordneten Reden nach Redeart:")
    art_je_rede = {z["rede_id"]: z["redeart"]
                   for z in lies(neueste("redeart_*.csv"))}
    for gruppe, name in [(offen, "OFFEN"), (fremd, "fremde Person"),
                         (leer, "keine Aktivitaet")]:
        c = Counter(art_je_rede.get(x, "?") for x in gruppe)
        teile = ", ".join(f"{v:,} {k}" for k, v in c.most_common(3))
        print(f"    {name:<18} {len(gruppe):>6,}  {teile}")

    print("\n  Je Aktivitaetsart, wie oft die Person passt:")
    je_art = defaultdict(Counter)
    for z in zeilen:
        je_art[z["aktivitaetsart"]][z["zuordnung"]] += 1
    for art, c in sorted(je_art.items(), key=lambda x: -sum(x[1].values()))[:12]:
        g = sum(c.values())
        print(f"    {art[:38]:<40} {g:>6,} Zeilen, "
              f"{c['fundstelle_und_person']:>6,} zugeordnet, "
              f"{c['person_passt_nicht']:>5,} fremde Person")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"rede_aktivitaet_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)
    print(f"\n{len(zeilen):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
