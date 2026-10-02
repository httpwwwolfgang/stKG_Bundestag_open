import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd


FRAKTIONEN_ORDNER = (Path(__file__).resolve().parents[2] / "03_load_db"
                     / "fraktionen")
sys.path.insert(0, str(FRAKTIONEN_ORDNER))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import fraktionen as fr
import korrekturen

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import zwischenstand

ZIEL = zwischenstand.fuer(__file__)
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"


ARTEN = [
    ("beifall",       r"^(?:[A-Za-zäöüß]+e[rn]?\s+)?Beifall\b"),
    ("zuruf",         r"^(?:[A-Za-zäöüß]+e[rn]?\s+)?(?:Zurufe?|Gegenrufe?|Rufe?)\b"),
    ("heiterkeit",    r"^(?:[A-Za-zäöüß]+e[rn]?\s+)?Heiterkeit\b"),
    ("lachen",        r"^(?:[A-Za-zäöüß]+e[rn]?\s+)?Lachen\b"),
    ("widerspruch",   r"^(?:[A-Za-zäöüß]+e[rn]?\s+)?Widerspruch\b"),
    ("unruhe",        r"^(?:[A-Za-zäöüß]+e[rn]?\s+)?Unruhe\b"),
    ("zustimmung",    r"^(?:[A-Za-zäöüß]+e[rn]?\s+)?(?:Zustimmung|Sehr richtig|"
                      r"Sehr wahr|Sehr gut|Bravo)"),
    ("unterbrechung", r"^Unterbrechung\b"),

    ("abgeordneter",  r"^Abg\.?\s"),
    ("glocke",        r"^(?:Glocke|Klopfzeichen)\b"),
    ("handlung",      r"^(?:Der|Die|Das)\s+(?:Redner|Rednerin|Abgeordnete|"
                      r"Anwesenden|Mitglieder|Mikrofon|Fraktion|Präsident)"),
    ("person_wortlaut", r"^[^:]{2,200}:\s"),
]


UMFANG = [
    ("abgeordnete", r"bei\s+Abgeordneten\s+(?:der|des|von|vom|dem)?\s*"),
    ("abgeordnete", r"(?:der|des|von)\s+Abg\.\s*"),
    ("haus",        r"im\s+ganzen\s+Haus(?:e)?"),
    ("fraktion",    r"(?:bei|beim|von|der|des|dem|den)\s+"),
]

SPALTEN = ["kommentar_id", "lfd_ereignis", "rede_id", "art", "urheber_anzahl",
           "text"]
SPALTEN_URHEBER = ["kommentar_id", "lfd_ereignis", "lfd_urheber",
                   "urheber_art", "fraktion_id", "urheber_name",
                   "urheber_redner_id", "namenslage",
                   "schreibweise", "umfang", "fundstelle_im_text"]


ART_UND_UMFANG = {
    "fraktion":    ("fraktion", "ganz"),
    "abgeordnete": ("fraktion", "teilweise"),
    "person":      ("person",   ""),
    "haus":        ("haus",     ""),
    "haus_offen":  ("haus",     ""),
}


def neueste(muster):
    treffer = sorted(ZIEL.glob(muster))
    if not treffer:
        raise SystemExit(f"Keine Datei zu {muster} in {ZIEL}")
    return treffer[-1]


def lies(pfad):
    with open(pfad, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def bestimme_art(text):
    for name, muster in ARTEN:
        if re.match(muster, text):
            return name
    return "sonstiges"


GRADE = {"dr", "prof", "h", "c", "med", "jur", "rer", "nat", "phil", "ing",
         "dipl", "dr.", "prof."}


def namensworte(wert):
    s = unicodedata.normalize("NFKC", str(wert or ""))
    s = s.replace(fr.WEICHES_TRENNZEICHEN, "")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"[^\w\s-]", " ", s)
    return {w for w in s.lower().split() if w not in GRADE and len(w) > 1}


def rednerverzeichnis():
    namen, fraktionen = defaultdict(set), defaultdict(set)
    d = pd.read_csv(neueste("redner_2*.csv"), sep=";", dtype=str,
                    keep_default_na=False)
    for _, z in d.iterrows():
        w = namensworte(f"{z['vorname']} {z['nachname']}")
        if w:
            namen[z["redner_id"]].add(frozenset(w))
    m = pd.read_csv(neueste("redner_merkmal_2*.csv"), sep=";", dtype=str,
                    keep_default_na=False)
    for _, z in m.iterrows():
        if z["art"] == "name":
            w = namensworte(z["wert"])
            if w:
                namen[z["redner_id"]].add(frozenset(w))
        elif z["art"] == "fraktion":
            fid = fr.zu_id(z["wert"])
            if fid:
                fraktionen[z["redner_id"]].add(fid)
    return namen, fraktionen


def loese_namen_auf(urheber):
    namen, fraktionen = rednerverzeichnis()
    zwischenspeicher = {}
    zaehler = Counter()
    for u in urheber:
        if u["urheber_art"] != "person":
            u["urheber_redner_id"], u["namenslage"] = "", ""
            continue
        schluessel = (u["urheber_name"], u["fraktion_id"])
        if schluessel not in zwischenspeicher:
            w = namensworte(u["urheber_name"])
            kand = [rid for rid, formen in namen.items()
                    if any(f <= w or w <= f for f in formen)]
            mit_fraktion = [rid for rid in kand
                            if u["fraktion_id"] in fraktionen.get(rid, set())]
            eng = mit_fraktion or kand


            if len(eng) > 1:
                echte = {korrekturen.mdb_kennung(rid) or rid for rid in eng}
                if len(echte) == 1:
                    ziel = echte.pop()
                    eng = [ziel] if ziel in namen else [eng[0]]
            if len(eng) == 1:
                zwischenspeicher[schluessel] = (
                    eng[0], "eindeutig" if mit_fraktion else "nur_name")
            elif len(eng) > 1:
                zwischenspeicher[schluessel] = ("", "mehrdeutig")
            else:
                zwischenspeicher[schluessel] = ("", "kein_treffer")
        u["urheber_redner_id"], u["namenslage"] = zwischenspeicher[schluessel]
        zaehler[u["namenslage"]] += 1
    print("\n  Namensaufloesung der Urheber:")
    for k, v in zaehler.most_common():
        print(f"    {v:>7,}  {k}")
    return urheber


def name_vor(text, pos):
    klammer = text.rfind("[", 0, pos)
    innerhalb = klammer >= 0 and text.rfind("]", klammer, pos) < 0
    if not innerhalb:


        davor = text[text.rfind("]", 0, pos) + 1:pos]
        if re.search(r",\s*(?:an|auf|zu|in Richtung)\s", davor):
            return None
        return ""
    vorher = text.rfind("]", 0, klammer)
    roh = text[vorher + 1:klammer]


    if re.match(r"\s*,?\s*an\s", roh) or "gewandt" in roh:
        return None

    roh = re.split(r"\s*(?:–|—|;|,\s*(?=[A-ZÄÖÜ])|\bund\b|\bsowie\b)\s*",
                   roh)[-1]

    roh = roh.strip()
    for _ in range(4):
        neu = re.sub(r"^\s*(?:Abg\.?|Gegenrufe?|Zurufe?|Rufe?|Heiterkeit|"
                     r"Lachen|Beifall|des|der|von|beim?|bei)\s+", "", roh)
        if neu == roh:
            break
        roh = neu
    roh = roh.strip(" .,-–—")


    if len(roh) < 3 or not re.search(r"[A-ZÄÖÜ]", roh):
        return ""
    return roh


def finde_urheber(text, art):


    kopf_ende = text.index(":") if ":" in text else len(text)
    ist_person = (art in ("person_wortlaut", "abgeordneter")
                  or "[" in text[:kopf_ende])
    if ist_person and ":" in text:
        text = text[:kopf_ende]
    treffer = []
    if re.search(r"im\s+ganzen\s+Haus(?:e)?", text):
        treffer.append(("", "im ganzen Hause", "haus", 0, ""))
    for fid, muster in fr.MUSTER:
        for m in re.finditer(muster, text):
            davor = text[max(0, m.start() - 40):m.start()]
            umfang, name = "fraktion", ""
            if ist_person:


                name = name_vor(text, m.start())
                if name is None:
                    continue
                if name:
                    umfang = "person"
            if umfang == "fraktion":
                for u, vor in UMFANG:
                    if re.search(vor + r"$", davor):
                        umfang = u
                        break
            treffer.append((fid, m.group(0), umfang, m.start(), name))


    gesehen, belegt, sauber = set(), set(), []
    for fid, wort, umfang, pos, name in sorted(treffer, key=lambda x: x[3]):
        if (fid, umfang, name) in gesehen or any(pos < e and pos >= a
                                                 for a, e in belegt):
            continue
        gesehen.add((fid, umfang, name))
        belegt.add((pos, pos + len(wort)))
        sauber.append((fid, wort, umfang, pos, name))
    return sauber


def fraktionen_am_tag():
    treffer = sorted(FRAKTIONEN_ORDNER.glob("export/fraktion_zeitraum_*.csv"))
    if not treffer:
        raise SystemExit(
            "Kein fraktion_zeitraum_*.csv gefunden. Erst " "03_load_db/fraktionen/lade_fraktionen.py laufen lassen.")
    d = pd.read_csv(treffer[-1], sep=";", dtype=str, keep_default_na=False)
    return [(z["von"], z["bis"] or None, z["fraktion_id"])
            for _, z in d.iterrows() if z["art"] != "fraktionslos"]


def haus_am_tag(bestand, datum):
    if not datum:
        return []
    return sorted({fid for von, bis, fid in bestand
                   if von <= datum and (bis is None or datum <= bis)})


def datum_je_kommentar(kommentare):
    reden = pd.read_parquet(neueste("rede_*.parquet"),
                            columns=["rede_id", "protokoll_nr",
                                     "sitzung_datum"])
    je_rede = {str(r): str(d)[:10]
               for r, d in zip(reden.rede_id, reden.sitzung_datum)}
    je_protokoll = {str(p): str(d)[:10]
                    for p, d in zip(reden.protokoll_nr, reden.sitzung_datum)}
    ergebnis, ueber_rede, ueber_protokoll, ohne = {}, 0, 0, []
    for k in kommentare:
        if k["rede_id"] in je_rede:
            ergebnis[k["kommentar_id"]] = je_rede[k["rede_id"]]
            ueber_rede += 1
        elif k["protokoll_nr"] in je_protokoll:
            ergebnis[k["kommentar_id"]] = je_protokoll[k["protokoll_nr"]]
            ueber_protokoll += 1
        else:
            ergebnis[k["kommentar_id"]] = ""
            ohne.append(k["protokoll_nr"])
    print(f"  Sitzungsdatum: {ueber_rede:,} ueber die Rede, "
          f"{ueber_protokoll:,} ueber die Protokollnummer, "
          f"{len(ohne):,} ohne")
    if ohne:
        print(f"    betroffene Protokolle: "
              f"{', '.join(sorted(set(ohne)))}")
    return ergebnis


def main():
    ereignisse = lies(neueste("kommentar_ereignis_*.csv"))
    kommentare = lies(neueste("kommentar_2*.csv"))
    tag_je_kommentar = datum_je_kommentar(kommentare)
    print(f"{len(ereignisse):,} Einzelereignisse")

    bestand = fraktionen_am_tag()
    print("\nBestand fuer \"im ganzen Hause\" (amtliche Stammdaten):")
    for von, bis, fid in sorted(bestand, key=lambda z: (z[0], z[2])):
        print(f"  {fid:<13} {von} bis {bis or 'offen'}")

    zeilen, urheber = [], []
    for e in ereignisse:
        text = e["text"].strip()
        art = bestimme_art(text)
        gefunden = finde_urheber(text, art)


        if any(u == "haus" for _, _, u, _, _ in gefunden):
            datum = tag_je_kommentar.get(e["kommentar_id"], "")
            aufgeloest = haus_am_tag(bestand, datum)
            gefunden = [g for g in gefunden if g[2] != "haus"]
            if aufgeloest:
                gefunden += [(f, "im ganzen Hause", "haus", 0, "")
                             for f in aufgeloest]
            else:


                gefunden.append(("", "im ganzen Hause", "haus_offen", 0, ""))
        zeilen.append({
            "kommentar_id": e["kommentar_id"],
            "lfd_ereignis": e["lfd_ereignis"], "rede_id": e["rede_id"],
            "art": art, "urheber_anzahl": len(gefunden), "text": text,
        })
        for i, (fid, wort, umfang, pos, name) in enumerate(gefunden, 1):
            urheber.append({
                "kommentar_id": e["kommentar_id"],
                "lfd_ereignis": e["lfd_ereignis"], "lfd_urheber": i,
                "urheber_art": ART_UND_UMFANG[umfang][0],
                "fraktion_id": fid, "urheber_name": name,
                "schreibweise": wort,
                "umfang": ART_UND_UMFANG[umfang][1],
                "fundstelle_im_text": pos,
            })

    urheber = loese_namen_auf(urheber)


    print(f"\n{'=' * 68}")
    print("Art des Ereignisses:")
    for k, v in Counter(z["art"] for z in zeilen).most_common():
        marke = "" if k in {"abgeordneter", "glocke", "handlung", "sonstiges",
                            "person_wortlaut"} else "(Open Discourse)"
        print(f"  {v:>7,}  {k:<16} {100*v/len(zeilen):>5.2f} %  {marke}")

    print(f"\n  {len(urheber):,} Urheber-Nennungen in "
          f"{len({(u['kommentar_id'], u['lfd_ereignis']) for u in urheber}):,} "
          f"Ereignissen")

    print("\n  Nach Fraktion:")
    for k, v in Counter(u["fraktion_id"] for u in urheber).most_common():
        print(f"    {v:>7,}  {k}")

    print("\n  Schreibweisen im Protokolltext:")
    for k, v in Counter(u["schreibweise"] for u in urheber
                        if u["urheber_art"] != "haus").most_common():
        print(f"    {v:>7,}  {k!r}")

    print("\n  Nach Art des Urhebers:")
    for k, v in Counter(u["urheber_art"] for u in urheber).most_common():
        print(f"    {v:>7,}  {k}")

    print("\n  Fraktionen: ganz oder teilweise?")
    for k, v in Counter(u["umfang"] for u in urheber
                        if u["urheber_art"] == "fraktion").most_common():
        print(f"    {v:>7,}  {k}")

    ohne = [z for z in zeilen if z["urheber_anzahl"] == 0]
    print(f"\n  {len(ohne):,} Ereignisse ohne erkannten Urheber")
    for k, v in Counter(z["art"] for z in ohne).most_common(6):
        print(f"    {v:>7,}  {k}")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"kommentar_art_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        s = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        s.writeheader()
        s.writerows(zeilen)
    print(f"\n{len(zeilen):,} Zeilen -> {pfad}")

    pfad = ZIEL / f"kommentar_urheber_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        s = csv.DictWriter(f, fieldnames=SPALTEN_URHEBER, delimiter=";")
        s.writeheader()
        s.writerows(urheber)
    print(f"{len(urheber):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
