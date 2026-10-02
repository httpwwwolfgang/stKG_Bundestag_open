import csv
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path

FRAKTIONEN_ORDNER = (Path(__file__).resolve().parents[2] / "03_load_db"
                     / "fraktionen")
sys.path.insert(0, str(FRAKTIONEN_ORDNER))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import fraktionen as fr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "Parlamentsarbeit"
          / "dip_plenarprotokolle_xml")
import zwischenstand


LIEFERUNG = "dip_plenarprotokolle"
ZIEL = zwischenstand.fuer(__file__)
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"

UEBERSCHRIFT = ("liste der entschuldigten abgeordneten",
                "entschuldigte abgeordnete")


ANDERE_UEBERSCHRIFT = re.compile(
    r"(amtliche mitteilung|schriftliche antwort|erklaerung nach|"
    r"erkl.rung(?:en)? nach|anlage \d)", re.I)


KEIN_NAME = re.compile(r"^\s*(?:\*|Abgeordnete\s*[(/]r\)?|Abgeordnete\(r\)|"
                       r"entschuldigt bis)", re.I)


GRUENDE = ("gesetzlicher mutterschutz", "aufgrund gesetzlichen mutterschutzes",
           "teilnahme an einer parl. versammlung",
           "teilnahme an einer parlamentarischen versammlung")


FRAKTION_SATZFEHLER = re.compile(r"^[(\s]+|[)\s\d-]+$")


NUR_DATUM = re.compile(r"^\s*\d{1,2}\.\s*\d{1,2}\.\s*\d{4}\s*$")


GEBROCHEN = {
    ("18/138", "Dr. de Maizière,"): (
        "de Maizière", "Thomas", "CDU/CSU",
        "Name ueber zwei Tabellenzeilen gebrochen: 'Dr. de Maizière,' oben, " "'Thomas | CDU/CSU | 4.12.2014' darunter"),
    ("18/60", "Dr. Troost, Axel"): (
        "Troost", "Axel", "DIE LINKE",
        "Fraktionsspalte fehlt in dieser Zeile; Troost ist in WP 18 " "durchgehend DIE LINKE"),
    ("18/60", "Dr. Wadephul, Johann"): (
        "Wadephul", "Johann", "CDU/CSU",
        "Fraktionsspalte fehlt; Wadephul ist in WP 18 durchgehend CDU/CSU"),
    ("18/60", "Zimmermann (Zwickau), Sabine"): (
        "Zimmermann", "Sabine", "DIE LINKE",
        "Fraktionsspalte fehlt; Ortszusatz Zwickau, DIE LINKE"),
}

SPALTEN = ["protokoll_nr", "wahlperiode", "sitzung_nr", "sitzung_datum",
           "lfd", "titel", "nachname", "vorname", "ortszusatz", "grund",
           "entschuldigt_bis", "fraktion_roh", "fraktion_id", "anlagen_typ"]


DOPPELTE_DATEI = {
    "wp18_18-20.xml": "traegt sitzung-nr=21 und den Inhalt von 18/21 (PA1)",
}


BERICHTIGTE_LISTE = {
    "Liste der entschuldigten Abgeordneten  für Mittwoch, den 7. Mai 2014 " "(neu)": ("18/33", "18/32", "18", "32", "07.05.2014"),
}


def text_von(element):
    return " ".join("".join(element.itertext()).split())


def zerlege_namen(roh):
    roh = roh.strip()
    if not roh or KEIN_NAME.match(roh):
        return None


    grund = ""
    m = re.search(r"\s*\(([^()]+)\)\s*$", roh)
    if m and m.group(1).strip().lower() in GRUENDE:
        grund = m.group(1).strip()
        roh = roh[:m.start()].strip()


    titel = ""
    m = re.match(r"^((?:Dr\.|Prof\.|Dr\. h\. c\.|Prof\. Dr\.)\s+)+", roh)
    if m and "," in roh[m.end():]:
        titel = m.group(0).strip()
        roh = roh[m.end():]


    ortszusatz = ""
    m = re.search(r"\s*\(([^()]+)\)\s*(?=,)", roh)
    if m:
        ortszusatz = m.group(1).strip()
        roh = roh[:m.start()] + roh[m.end():]

    if "," in roh:
        nachname, vorname = [t.strip() for t in roh.split(",", 1)]
    else:

        teile = roh.split()
        if len(teile) < 2:
            return None
        vorname, nachname = " ".join(teile[:-1]), teile[-1]


    m = re.match(r"^((?:Dr\.|Prof\.|h\. c\.|Dr\. h\. c\.)\s+)+", vorname)
    if m:
        titel = (titel + " " + m.group(0).strip()).strip()
        vorname = vorname[m.end():].strip()


    vorname = re.sub(r"\s*\*+\s*$", "", vorname).strip()

    if not nachname or not vorname:
        return None
    return titel, nachname, vorname, ortszusatz, grund


def hat_zeilen(element):
    return any(True for _ in element.iter("tr"))


def ueberschrift_passt(at):
    typ = (at.get("anlagen-typ") or "").strip()
    kopf = text_von(at)[:60].strip().lower()
    return ("ntschuldig" in typ.lower()
            or any(kopf.startswith(u) for u in UEBERSCHRIFT)), typ


def anlagen_der_liste(baum):
    for anlagen in baum.iter("anlagen"):
        liste = list(anlagen.iter("anlage"))
        for i, anlage in enumerate(liste):
            typ_der_liste, sammeln, gefunden = "", False, False
            for at in anlage.iter("anlagen-text"):
                passt, typ = ueberschrift_passt(at)
                if passt:
                    sammeln, typ_der_liste = True, typ or typ_der_liste
                elif sammeln and (typ or ANDERE_UEBERSCHRIFT.match(
                        text_von(at)[:60].strip().lower())):
                    sammeln = False
                if sammeln and hat_zeilen(at):
                    gefunden = True
                    yield at, typ_der_liste


            if (typ_der_liste is not None and sammeln and not gefunden
                    and i + 1 < len(liste)):
                naechste = liste[i + 1]
                for at in naechste.iter("anlagen-text"):
                    eigene, typ = ueberschrift_passt(at)
                    kopf = text_von(at)[:60].strip().lower()
                    if typ and not eigene:
                        break
                    if ANDERE_UEBERSCHRIFT.match(kopf):
                        break
                    if hat_zeilen(at):
                        yield at, typ_der_liste


def raeume_auf(zeilen):

    for typ, (aus, nach, wp, nr, datum) in BERICHTIGTE_LISTE.items():
        umzug = [z for z in zeilen
                 if z["protokoll_nr"] == aus and z["anlagen_typ"] == typ]
        ueberholt = [z for z in zeilen
                     if z["protokoll_nr"] == nach and z not in umzug]
        if len(umzug) != len(ueberholt):
            raise SystemExit(
                f"  ! {nach}: berichtigte Liste hat {len(umzug)} Zeilen, "
                f"die ueberholte {len(ueberholt)} -- angesehen werden")
        for z in ueberholt:
            zeilen.remove(z)
        for z in umzug:
            z.update(protokoll_nr=nach, wahlperiode=wp, sitzung_nr=nr,
                     sitzung_datum=datum)
        print(f"\n  {len(umzug)} Zeilen von {aus} nach {nach} umgezogen "
              f"(berichtigte Liste), {len(ueberholt)} ueberholte entfernt")


    gesehen, entfernt, doppelt = set(), [], []
    for z in zeilen:
        schluessel = (z["protokoll_nr"], z["titel"], z["nachname"],
                      z["vorname"], z["ortszusatz"], z["anlagen_typ"])
        if schluessel in gesehen:
            entfernt.append(z)
            doppelt.append(f"{z['protokoll_nr']}: {z['vorname']} "
                           f"{z['nachname']}")
        gesehen.add(schluessel)
    for z in entfernt:
        zeilen.remove(z)
    print(f"  {len(entfernt)} doppelt gedruckte Zeilen auf eine reduziert "
          f"(erwartet: 3)")
    for d in doppelt:
        print(f"    {d}")
    if len(entfernt) != 3:
        raise SystemExit("  ! Zahl weicht ab -- die Faelle einzeln ansehen")


    lauf = Counter()
    for z in zeilen:
        lauf[z["protokoll_nr"]] += 1
        z["lfd"] = lauf[z["protokoll_nr"]]
    return zeilen


def main():
    dateien = sorted(QUELLE.glob("wp*.xml"))
    print(f"{len(dateien)} Protokolle lesen aus {QUELLE}")

    zeilen, uebersprungen, ohne_liste = [], Counter(), []
    korrigiert = 0
    zelle_fehlt = 0
    unverstanden = []
    for pfad in dateien:
        if pfad.name in DOPPELTE_DATEI:
            print(f"  uebersprungen: {pfad.name} -- {DOPPELTE_DATEI[pfad.name]}")
            continue
        try:
            baum = ET.parse(pfad)
        except ET.ParseError as e:
            print(f"  ! {pfad.name}: {e}")
            continue
        wurzel = baum.getroot()
        protokoll = (f"{wurzel.get('wahlperiode')}/"
                     f"{wurzel.get('sitzung-nr')}")
        gefunden = False
        for at, typ in anlagen_der_liste(baum):
            gefunden = True
            for tr in at.iter("tr"):
                tds = [text_von(td) for td in tr.iter("td")]
                if not tds:
                    continue
                if len(tds) == 1 and (protokoll, tds[0].strip()) in GEBROCHEN:
                    tds = list(tds) + ["", ""]
                if len(tds) not in (2, 3):


                    uebersprungen[f"{len(tds)} Spalten"] += 1
                    if len(tds) == 1 and not KEIN_NAME.match(tds[0]):
                        unverstanden.append((pfad.name, " | ".join(tds)))
                    continue


                if len(tds) == 2 and NUR_DATUM.match(tds[1]):
                    tds = [tds[0], "", tds[1]]
                    zelle_fehlt += 1


                fix = GEBROCHEN.get((protokoll, tds[0].strip()))
                if fix:
                    nachname, vorname, fraktion_roh, _ = fix
                    titel, ortszusatz, grund = "", "", ""
                    korrigiert += 1
                else:
                    teile = zerlege_namen(tds[0])
                    if teile is None:
                        uebersprungen["kein Name"] += 1
                        if not KEIN_NAME.match(tds[0]):
                            unverstanden.append((pfad.name, " | ".join(tds)))
                        continue
                    titel, nachname, vorname, ortszusatz, grund = teile
                    fraktion_roh = tds[1]
                zeilen.append({
                    "protokoll_nr": protokoll,
                    "wahlperiode": wurzel.get("wahlperiode"),
                    "sitzung_nr": wurzel.get("sitzung-nr"),
                    "sitzung_datum": wurzel.get("sitzung-datum"),
                    "lfd": len(zeilen) + 1,
                    "titel": titel, "nachname": nachname, "vorname": vorname,
                    "ortszusatz": ortszusatz, "grund": grund,


                    "entschuldigt_bis": (
                        re.sub(r"(?<=\.)\s+(?=\d)", "", tds[2])
                        if len(tds) == 3 else ""),
                    "fraktion_roh": fraktion_roh,


                    "fraktion_id": fr.zu_id(
                        FRAKTION_SATZFEHLER.sub("", fraktion_roh)) or "",
                    "anlagen_typ": typ,
                })
        if not gefunden:
            ohne_liste.append(pfad.name)

    zeilen = raeume_auf(zeilen)


    print(f"\n{'=' * 70}")
    print(f"{len(zeilen):,} Eintraege in "
          f"{len({z['protokoll_nr'] for z in zeilen}):,} Sitzungen\n")

    for wp in sorted({z["wahlperiode"] for z in zeilen}):
        t = [z for z in zeilen if z["wahlperiode"] == wp]
        print(f"  WP {wp}: {len(t):>6,} Eintraege in "
              f"{len({z['protokoll_nr'] for z in t}):>3} Sitzungen")

    print(f"\n  {len(ohne_liste)} Protokolle ohne Liste: "
          f"{', '.join(ohne_liste)}")

    print("\n  Fraktionen:")
    for k, v in Counter(z["fraktion_id"] or "(nicht zugeordnet)"
                        for z in zeilen).most_common():
        print(f"    {v:>7,}  {k}")

    print(f"\n  {korrigiert} gebrochene Zeilen aus GEBROCHEN ergaenzt")
    print(f"  {zelle_fehlt} Zeilen ohne Fraktionszelle: Datum aus der "
          f"zweiten Zelle\n    nach entschuldigt_bis gelesen "
          f"(erwartet: 2, beide in 18/31)")
    if zelle_fehlt != 2:
        print("    ! Zahl weicht ab -- pruefen, ob eine neue Tabellenform " "dazugekommen ist")

    print("\n  Fraktionsangaben ohne Zuordnung:")
    for k, v in Counter(z["fraktion_roh"] for z in zeilen
                        if not z["fraktion_id"]).most_common():
        print(f"    {v:>7,}  {k!r}")

    print("\n  Uebersprungene Zeilen:")
    for k, v in uebersprungen.most_common():
        print(f"    {v:>7,}  {k}")

    if unverstanden:
        print(f"\n  {len(unverstanden)} Zeilen NICHT verstanden — jede einzeln:")
        for datei, inhalt in unverstanden[:40]:
            print(f"    {datei}: {inhalt[:90]}")
    else:
        print("\n  Keine unverstandene Zeile.")

    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"entschuldigt_{STEMPEL}.csv"
    with pfad.open("w", encoding="utf-8", newline="") as f:
        s = csv.DictWriter(f, fieldnames=SPALTEN, delimiter=";")
        s.writeheader()
        s.writerows(zeilen)
    print(f"\n{len(zeilen):,} Zeilen -> {pfad}")


if __name__ == "__main__":
    main()
