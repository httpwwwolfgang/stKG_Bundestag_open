import csv
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import query

S = "parlamentsarbeit"
PERSONEN = Path(__file__).resolve().parents[1] / "personen" / "export"
import zwischenstand
AUSGABE = zwischenstand.fuer(__file__)
ZAHLWORT = {"eines": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4,
            "fuenf": 5, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8,
            "neun": 9, "zehn": 10}


NAMENSKORREKTUR = {"Lars Hermann": "Lars Herrmann"}


PROTOKOLLFAELLE = [
    {"wahlperiode": "18", "datum": "2015-03-05", "protokoll": "18/91",
     "erteilt_von": "Vizepraesidentin Edelgard Bulmahn",
     "empfaenger": ["van Aken"], "fraktion": "",
     "zitat": "Herr van Aken, ich erteile Ihnen hiermit offiziell einen " "Ordnungsruf. Es ist nicht zulaessig, dass Sie hier Symbole " "verbotener Organisationen zeigen."},
    {"wahlperiode": "18", "datum": "2017-04-27", "protokoll": "18/231",
     "erteilt_von": "Vizepraesident Johannes Singhammer",
     "empfaenger": ["Leidig"], "fraktion": "",
     "zitat": "Frau Kollegin Leidig, das, was Sie sich jetzt hier zu eigen " "gemacht haben, ist nicht parlamentarisch. Ich erteile Ihnen " "deshalb einen Ordnungsruf."},
]


BSW_ACHT = ["Al-Dailami", "Dağdelen", "Ernst", "Hunko", "Leye",
            "Mohamed Ali", "Tatti", "Wagenknecht"]


def norm(s):
    s = (s or "").strip().lower().replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", "", s).strip()


def lies_titel(titel):
    rufe = 1
    m = re.search(r"von (\w+) Ordnungsrufen", titel, re.I)
    if m:
        rufe = ZAHLWORT.get(m.group(1).lower(), 1)


    m = re.search(r"an (\w+) Abgeordnete\b(?!n)\s*\(([^)]*)\)", titel, re.I)
    if m and m.group(1).lower() in ZAHLWORT:
        n = ZAHLWORT[m.group(1).lower()]
        return n, "", m.group(2).strip(), n, "mehrere ohne Namen"


    m = re.search(r"an (?:den|die|das) (?:Abg\.?|Abgeordneten?|Abgeordnete)\s+"
                  r"(.+?)\s*\(([^)]*)\)\s*$", titel, re.I)
    if m:
        return rufe, m.group(1).strip(), m.group(2).strip(), 1, "Name im Titel"


    m = re.search(r"Fraktion (?:der |des )?(.+?)\s*$", titel, re.I)
    if m:
        return rufe, "", m.group(1).strip(), 1, "kein Name im Titel"
    return rufe, "", "", 1, "Titel nicht erkannt"


TITELWORT = {"dr", "prof", "hc", "med", "rer", "nat", "jur", "iur", "phil",
             "ing", "habil", "freiherr", "freifrau", "graf", "graefin"}


def ohne_titel(s):
    return " ".join(w for w in norm(s).split() if w not in TITELWORT)


def fraktionskarte():
    karte = {norm(z[0]): z[1] for z in
             query("SELECT schreibweise, fraktion_id " "FROM politiker_innen.fraktion_alias;")}
    return karte


def personenverzeichnis(karte):
    alias = pd.read_csv(PERSONEN / "person_alias.csv", dtype=str).fillna("")
    frakt = pd.read_csv(PERSONEN / "person_fraktion.csv", dtype=str).fillna("")
    voll, nach = {}, {}
    for _, z in alias.iterrows():
        if z["nachname"]:
            nach.setdefault(ohne_titel(z["nachname"]), set()).add(z["person"])
            if z["vorname"]:
                voll.setdefault(
                    ohne_titel(f"{z['vorname']} {z['nachname']}"),
                    set()).add(z["person"])
    fr = {}
    for _, z in frakt.iterrows():
        if z["wahlperiode"]:
            fr.setdefault((z["person"], z["wahlperiode"]), set()).add(
                karte.get(norm(z["fraktion"]), norm(z["fraktion"])))
    return voll, nach, fr


def main():
    karte = fraktionskarte()
    voll_index, nach_index, frakt_index = personenverzeichnis(karte)

    roh = query(f"""
        SELECT v.vorgang_id, v.wahlperiode::text, v.titel, v.datum::text,
               vp.dokumentnummer, coalesce(vp.anfangsseite::text,''),
               vp.position_id
        FROM {S}.vorgang v
        JOIN {S}.vorgangsposition vp USING (vorgang_id)
        WHERE vp.vorgangsposition = 'Ordnungsruf'
        ORDER BY v.datum;""")


    akt = {}
    for aid, pid, titel, art, vids in query(f"""
            SELECT aktivitaet_id, person_id, titel, aktivitaetsart, vorgang_ids
            FROM {S}.aktivitaet
            WHERE vorgang_ids IS NOT NULL AND vorgang_ids <> '';"""):
        for v in re.split(r"[;| ]+", vids or ""):
            if v:
                akt.setdefault(v, []).append((pid, titel, art))

    def zuordnen(name, fraktion, wp):
        name = NAMENSKORREKTUR.get(name, name)
        rein = ohne_titel(re.sub(r"\(.*?\)", "", name))
        if not rein:
            return "", "kein Name"
        fr_soll = karte.get(norm(fraktion), norm(fraktion)) if fraktion else ""


        for kandidaten, wie in ((voll_index.get(rein, set()), "Vollname"),
                                (nach_index.get(rein, set()),
                                 "mehrteiliger Nachname"),
                                (nach_index.get(rein.split()[-1], set()),
                                 "Nachname")):
            if not kandidaten:
                continue
            if fr_soll:
                passend = [p for p in kandidaten
                           if fr_soll in frakt_index.get((p, wp), set())]
                probe = f"{wie}, Fraktion und Wahlperiode"
            else:
                passend = [p for p in kandidaten
                           if frakt_index.get((p, wp))]
                probe = f"{wie} und Wahlperiode"
            if len(passend) == 1:
                return passend[0], probe
            if len(passend) > 1:
                return "", f"mehrdeutig ueber {wie} ({len(passend)})"
            return "", (f"{wie} gefunden, Fraktion passt nicht" if fr_soll
                        else f"{wie} gefunden, nicht in dieser Wahlperiode")
        return "", "Name nicht im Verzeichnis"

    zeilen = []
    for vid, wp, titel, datum, protokoll, seite, pos in roh:
        rufe, name, fraktion, n_pers, form = lies_titel(titel)


        person, status = ("", form)
        if name:
            person, status = zuordnen(name, fraktion, wp)
        erteiler = akt.get(vid, [])
        zeilen.append({
            "wahlperiode": wp, "datum": datum, "protokoll": protokoll,
            "seite": seite, "vorgang_id": vid, "position_id": pos,
            "anzahl_rufe": rufe, "empfaenger_anzahl": n_pers,
            "empfaenger_name": name, "empfaenger_fraktion": fraktion,
            "empfaenger_person": person, "empfaenger_status": status,
            "erteilt_von_person_id": "; ".join(p for p, _, _ in erteiler),
            "erteilt_von": "; ".join(t for _, t, _ in erteiler),
            "titel": titel, "quelle": "DIP",
        })


    ersetzt = []
    for z in zeilen:
        if z["empfaenger_status"] == "mehrere ohne Namen" and z["wahlperiode"] == "20":
            for nachname in BSW_ACHT:
                person, status = zuordnen(nachname, "Gruppe BSW", "20")
                neu_z = dict(z)
                neu_z.update({"anzahl_rufe": 1, "empfaenger_anzahl": 1,
                              "empfaenger_name": nachname,
                              "empfaenger_person": person,
                              "empfaenger_status": status,
                              "quelle": "DIP + Protokolltext"})
                ersetzt.append(neu_z)
        else:
            ersetzt.append(z)
    zeilen = ersetzt


    for f in PROTOKOLLFAELLE:
        for nachname in f["empfaenger"]:
            person, status = zuordnen(nachname, f["fraktion"], f["wahlperiode"])
            zeilen.append({
                "wahlperiode": f["wahlperiode"], "datum": f["datum"],
                "protokoll": f["protokoll"], "seite": "",
                "vorgang_id": "", "position_id":
                    f"protokoll:{f['protokoll']}:{nachname}",
                "anzahl_rufe": 1, "empfaenger_anzahl": 1,
                "empfaenger_name": nachname, "empfaenger_fraktion": "",
                "empfaenger_person": person, "empfaenger_status": status,
                "erteilt_von_person_id": "", "erteilt_von": f["erteilt_von"],
                "titel": f["zitat"], "quelle": "Protokolltext",
            })


    for z in zeilen:
        roh = z["empfaenger_fraktion"]
        if roh:
            z["empfaenger_fraktion_id"] = karte.get(norm(roh), norm(roh))
            z["fraktion_herkunft"] = "Titel"
        elif z["empfaenger_person"]:
            frs = frakt_index.get((z["empfaenger_person"], z["wahlperiode"]),
                                  set())
            z["empfaenger_fraktion_id"] = "; ".join(sorted(frs))
            z["fraktion_herkunft"] = "Person" if frs else ""
        else:
            z["empfaenger_fraktion_id"] = ""
            z["fraktion_herkunft"] = ""

    zaehler = {}
    for z in zeilen:
        pid = z["position_id"]
        zaehler[pid] = zaehler.get(pid, 0) + 1
        z["ordnungsruf_id"] = (pid if zaehler[pid] == 1 and
                               sum(1 for y in zeilen
                                   if y["position_id"] == pid) == 1
                               else f"{pid}-{zaehler[pid]}")

    AUSGABE.mkdir(parents=True, exist_ok=True)
    with open(AUSGABE / "ordnungsruf.csv", "w", newline="",
              encoding="utf-8") as fh:
        spalten = ["ordnungsruf_id"] + [k for k in zeilen[0]
                                         if k != "ordnungsruf_id"]
        w = csv.DictWriter(fh, fieldnames=spalten)
        w.writeheader()
        w.writerows(zeilen)

    d = pd.DataFrame(zeilen)
    print(f"ordnungsruf.csv: {len(d)} Positionen, "
          f"{d['anzahl_rufe'].sum()} erteilte Ordnungsrufe")
    print(f"\nJe Wahlperiode:")
    print(d.groupby("wahlperiode")[["anzahl_rufe"]].agg(
        positionen=("anzahl_rufe", "size"), rufe=("anzahl_rufe", "sum")
    ).to_string())
    print(f"\nEmpfaenger aufgeloest:")
    print(d["empfaenger_status"].value_counts().to_string())
    print(f"\nErteiler bekannt: "
          f"{(d['erteilt_von_person_id'] != '').sum()} von {len(d)}")
    top = d[d["empfaenger_person"] != ""].groupby(
        ["empfaenger_name", "empfaenger_fraktion"])["anzahl_rufe"].sum()
    print(f"\nMeiste Ordnungsrufe:")
    print(top.sort_values(ascending=False).head(10).to_string())
    print(f"\nAusgabe in: {AUSGABE.resolve()}")


if __name__ == "__main__":
    main()
