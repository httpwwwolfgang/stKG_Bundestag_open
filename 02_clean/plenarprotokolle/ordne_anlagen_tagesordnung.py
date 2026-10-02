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
ZIEL = zwischenstand.fuer(__file__)
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"


VARIANTEN = [
    ("Tagesordnungs- punkt", "Tagesordnungspunkt"),
    ("Tagesordnungs-punkt", "Tagesordnungspunkt"),
    ("Tagesordnungs punkt", "Tagesordnungspunkt"),
    ("Tagesord- nungspunkt", "Tagesordnungspunkt"),
    ("Tagesord nungspunkt", "Tagesordnungspunkt"),
    ("Tagesordungspunkt", "Tagesordnungspunkt"),
    ("Tagespunkt", "Tagesordnungspunkt"),
    ("Zusatzordnungspunkt", "Zusatztagesordnungspunkt"),
]


NENNUNG = re.compile(
    r"\b(Zusatztagesordnungspunkt|Zusatzpunkt|Tagesordnungspunkt|ZP)e?"
    r"\s*(\d+|[IVX]+)\b\s*([a-z](?![a-z]))?",
    re.IGNORECASE)


BLOCK = re.compile(
    r"^(Zusatztagesordnungspunkt|Zusatzpunkte?|Tagesordnungspunkte?|Einzelplan)"
    r"\s*(\d+|[IVX]+)",
    re.IGNORECASE)

SPALTEN = ["rede_id", "protokoll_nr", "wahlperiode", "anlage", "anlagen_typ",
           "top_nummer", "top_art", "nennung_roh", "im_verzeichnis",
           "herkunft", "anlagenkopf"]


def neueste_datei(muster):
    treffer = sorted(ZIEL.glob(muster))
    if not treffer:
        raise SystemExit(f"Keine Datei zu {muster} in {ZIEL} — erst "
                         f"baue_tagesordnung.py laufen lassen.")
    return treffer[-1]


def lies_csv(pfad):
    with open(pfad, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def normal(text):
    s = str(text or "").replace("­", "").replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def text_von(element):
    return normal("".join(element.itertext()))


def entzerre(text):
    for falsch, richtig in VARIANTEN:
        text = re.sub(re.escape(falsch), richtig, text, flags=re.IGNORECASE)
    return text


def punkte_der_sitzung(wurzel):
    punkte = {}
    verzeichnis = wurzel.find("vorspann/inhaltsverzeichnis")
    if verzeichnis is None:
        return punkte
    for block in verzeichnis.iter("ivz-block"):
        kopf = block.find("ivz-block-titel")
        if kopf is None:
            continue
        titel = normal(text_von(kopf))
        treffer = BLOCK.match(titel)
        if not treffer:
            continue
        art = ("zusatzpunkt" if treffer.group(1).lower().startswith("zusatz")
               else "einzelplan" if treffer.group(1).lower() == "einzelplan"
               else "tagesordnungspunkt")


        eintraege = block.findall("ivz-eintrag")
        gegenstand = text_von(eintraege[0]) if eintraege else ""
        punkte.setdefault((art, treffer.group(2).upper()),
                          {"titel": titel, "gegenstand": gegenstand})
    return punkte


def werte_protokoll_aus(pfad):
    wurzel = ElementTree.parse(pfad).getroot()
    wp = wurzel.get("wahlperiode", "")
    protokoll = pfad.stem.split("_", 1)[1].replace("-", "/")
    punkte = punkte_der_sitzung(wurzel)
    zeilen, offen = [], []

    for anlage in wurzel.iter("anlage"):
        titel = anlage.find("anlagen-titel")
        nummer = text_von(titel) if titel is not None else ""

        for teil in anlage.findall("anlagen-text"):
            reden = list(teil.iter("rede"))
            if not reden:
                continue
            typ = normal(teil.get("anlagen-typ") or "")


            kopf = []
            for kind in list(teil):
                if kind.tag == "rede":
                    break
                kopf.append(text_von(kind))
            kopftext = entzerre(" ".join(kopf))

            gefunden, roh = [], []
            for art_wort, nr, buchstabe in NENNUNG.findall(kopftext):
                kurz = art_wort.lower()
                art = ("zusatzpunkt" if kurz.startswith("zusatz") or kurz == "zp"
                       else "tagesordnungspunkt")
                schluessel = (art, nr.upper())
                if schluessel not in gefunden:
                    gefunden.append(schluessel)
                roh.append(f"{art_wort} {nr}{' ' + buchstabe if buchstabe else ''}")

            if not gefunden:
                herkunft = "keine_nennung"
                offen.append((protokoll, nummer, typ, kopftext[:180]))
                im_verzeichnis = ""
            else:
                herkunft = "anlagenkopf"


                treffer = []
                for art, nr in gefunden:
                    kandidaten = ([("zusatzpunkt", nr)] if art == "zusatzpunkt"
                                  else [(art, nr)])
                    treffer.append(any(k in punkte for k in kandidaten))
                im_verzeichnis = ("ja" if all(treffer)
                                  else "teilweise" if any(treffer) else "nein")

            for rede in reden:
                zeilen.append({
                    "rede_id": rede.get("id", ""),
                    "protokoll_nr": protokoll,
                    "wahlperiode": wp,
                    "anlage": nummer,
                    "anlagen_typ": typ,
                    "top_nummer": ", ".join(nr for _, nr in gefunden),
                    "top_art": ", ".join(sorted({a for a, _ in gefunden})),
                    "nennung_roh": " | ".join(roh),
                    "im_verzeichnis": im_verzeichnis,
                    "herkunft": herkunft,
                    "anlagenkopf": kopftext[:400],
                })
    return zeilen, offen


def main():
    dateien = sorted(QUELLE.glob("*.xml"))
    print(f"{len(dateien)} Protokolle lesen aus {QUELLE}")

    alle, offen = [], []
    for pfad in dateien:
        z, o = werte_protokoll_aus(pfad)
        alle.extend(z)
        offen.extend(o)


    print(f"\n{'=' * 70}")
    print(f"{len(alle):,} Reden stehen im Protokollanhang\n")

    herkunft = Counter(z["herkunft"] for z in alle)
    zugeordnet = herkunft["anlagenkopf"]
    print(f"  {zugeordnet:>6,} nennen ihren Tagesordnungspunkt im Anlagenkopf")
    print(f"  {herkunft['keine_nennung']:>6,} nennen keinen — bleiben offen")

    verz = Counter(z["im_verzeichnis"] for z in alle if z["herkunft"] == "anlagenkopf")
    print(f"\n  Von den {zugeordnet:,} zugeordneten Reden fuehrt das "
          f"Inhaltsverzeichnis der Sitzung den genannten Punkt")
    print(f"    {verz.get('ja', 0):>6,} vollstaendig")
    print(f"    {verz.get('teilweise', 0):>6,} nur teilweise (mehrere genannt)")
    print(f"    {verz.get('nein', 0):>6,} gar nicht")

    mehrere = sum(1 for z in alle if "," in z["top_nummer"])
    print(f"\n  {mehrere:,} Reden gehoeren zu einer verbundenen Beratung "
          f"und tragen mehrere Punktnummern")

    print("\n  Je Wahlperiode:")
    for wp in sorted({z["wahlperiode"] for z in alle}):
        teil = [z for z in alle if z["wahlperiode"] == wp]
        mit = sum(1 for z in teil if z["herkunft"] == "anlagenkopf")
        print(f"    WP {wp}: {len(teil):>5,} Anlagen-Reden, "
              f"{mit:>5,} mit Tagesordnungspunkt, "
              f"{len(teil) - mit:>3} ohne")

    if offen:
        print(f"\n  {len(offen)} Anlagen-Abschnitte nennen keinen Punkt.")
        print("  Wenn hier eine neue Schreibweise auftaucht, gehoert sie in")
        print("  VARIANTEN — nicht in eine unscharfe Suche:")
        for protokoll, anlage, typ, kopf in offen:
            print(f"    {protokoll} {anlage or '(ohne Titel)'}: {kopf[:120]}")


    punkte = {}
    for t in lies_csv(neueste_datei("tagesordnungspunkt_*.csv")):
        punkte.setdefault((t["protokoll_nr"], t["top_id"]), t["lfd"])

    zuordnung, ohne_punkt = [], 0
    for z in alle:
        if not z["top_nummer"]:
            continue
        arten = [a.strip() for a in z["top_art"].split(",")]
        nummer = z["top_nummer"].split(",")[0].strip()
        formen = ([f"Zusatzpunkt {nummer}", f"Zusatztagesordnungspunkt {nummer}"]
                  if "zusatzpunkt" in arten
                  else [f"Tagesordnungspunkt {nummer}"])
        for form in formen:
            lfd = punkte.get((z["protokoll_nr"], form))
            if lfd is not None:
                zuordnung.append({
                    "rede_id": z["rede_id"], "protokoll_nr": z["protokoll_nr"],
                    "top_id": form, "lfd": lfd, "herkunft": "anlagenkopf"})
                break
        else:
            ohne_punkt += 1

    print(f"\n  {len(zuordnung):,} Anlagen-Reden lassen sich einem "
          f"Tagesordnungspunkt der Tabelle zuordnen")
    print(f"  {ohne_punkt:,} nennen einen Punkt, den der Sitzungsverlauf "
          f"nicht fuehrt")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad2 = ZIEL / f"anlage_rede_tagesordnungspunkt_{STEMPEL}.csv"
    with pfad2.open("w", encoding="utf-8", newline="") as f:
        s = csv.DictWriter(f, fieldnames=["rede_id", "protokoll_nr", "top_id",
                                          "lfd", "herkunft"], delimiter=";")
        s.writeheader()
        s.writerows(zuordnung)
    print(f"{len(zuordnung):,} Zeilen -> {pfad2}")

    pfad = ZIEL / f"anlage_tagesordnung_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        schreiber = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(alle)
    print(f"\n{len(alle):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
