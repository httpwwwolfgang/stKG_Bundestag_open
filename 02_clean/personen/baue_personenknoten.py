import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import query


import zwischenstand
AUSGABE = zwischenstand.fuer(
    __file__, "export_pruef" if "--pruefen" in sys.argv else "export")


def bestehende_nummern():
    try:
        zeilen = query("SELECT system, kennung, person " "FROM parlamentsarbeit.person_kennung;")
    except Exception:
        print("  person_kennung nicht lesbar -- erster Lauf, alle Nummern neu")
        return {}, 0
    fest = {}
    for system, kennung, person in zeilen:
        fest[f"{str(system).strip()}:{str(kennung).strip()}"] = str(person).strip()
    hoechste = max((int(p[1:]) for p in set(fest.values())
                    if re.fullmatch(r"P\d+", p)), default=0)
    print(f"  {len(fest)} Kennungen tragen bereits eine Nummer, "
          f"hoechste P{hoechste:05d}")
    return fest, hoechste


def hole(sql, spalten):
    return pd.DataFrame(query(sql), columns=spalten).fillna("")


def norm(s):
    s = (s or "").strip().lower().replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", "", s).strip()


class Verbund:

    def __init__(self):
        self.vater = {}
        self.gruende = []

    def add(self, k):
        self.vater.setdefault(k, k)

    def find(self, k):
        self.add(k)
        while self.vater[k] != k:
            self.vater[k] = self.vater[self.vater[k]]
            k = self.vater[k]
        return k

    def union(self, a, b, grund):
        wa, wb = self.find(a), self.find(b)
        if wa != wb:
            self.vater[wb] = wa
            self.gruende.append((a, b, grund))
            return True
        return False

    def gruppen(self):
        g = defaultdict(list)
        for k in self.vater:
            g[self.find(k)].append(k)
        return list(g.values())


def lies_quellen():
    q = {}
    q["dip"] = hole(
        "SELECT person_id, vorname, nachname, namenszusatz, titel, funktion, " "fraktion_abzugsstand, ressort, bundesland, abgefragt_wahlperiode, " "coalesce(basisdatum::text,''), coalesce(wahlperioden,'') " "FROM parlamentsarbeit.dip_person ORDER BY person_id;",
        ["person_id", "vorname", "nachname", "namenszusatz", "titel",
         "funktion", "fraktion", "ressort", "bundesland", "wahlperiode",
         "basisdatum", "wahlperioden"])
    q["redner"] = hole(
        "SELECT redner_id, kennungsart, titel, vorname, nachname, " "namenszusatz, ortszusatz FROM parlamentsarbeit.redner;",
        ["redner_id", "kennungsart", "titel", "vorname", "nachname",
         "namenszusatz", "ortszusatz"])
    q["merkmal"] = hole(
        "SELECT redner_id, art, wert, coalesce(reden::text,''), " "coalesce(erste_rede::text,''), coalesce(letzte_rede::text,''), " "coalesce(wahlperioden,'') FROM parlamentsarbeit.redner_merkmal;",
        ["redner_id", "art", "wert", "reden", "erste_rede", "letzte_rede",
         "wahlperioden"])
    q["bruecke"] = hole(
        "SELECT person_id, redner_id, lage FROM parlamentsarbeit.personenbruecke " "WHERE redner_id IS NOT NULL AND redner_id <> '';",
        ["person_id", "redner_id", "lage"])


    q["politician"] = hole(
        "SELECT p.aw_id, p.first_name, p.last_name, p.birth_name, p.title, " "coalesce(p.ext_id_bundestagsverwaltung,'') " "FROM politiker_innen.politician p WHERE p.aw_id > 0;",
        ["aw_id", "vorname", "nachname", "geburtsname", "titel", "btv"])


    q["platzhalter"] = hole(
        "SELECT p.aw_id, p.last_name FROM politiker_innen.politician p " "WHERE p.aw_id < 0 ORDER BY p.aw_id DESC;",
        ["aw_id", "etikett"])
    q["mdb_zu_aw"] = hole(
        "SELECT mdb_id, aw_id, herkunft FROM politiker_innen.mdb_zu_aw;",
        ["mdb_id", "aw_id", "herkunft"])
    q["alias"] = hole(
        "SELECT mdb_id, nachname, vorname, ortszusatz, verfahren " "FROM politiker_innen.mdb_namensalias;",
        ["mdb_id", "nachname", "vorname", "ortszusatz", "verfahren"])
    q["mandat"] = hole(
        "SELECT politician_id, legislatur, mandatsart, fraction_label, " "coalesce(wkr_nr::text,''), coalesce(wkr_name,'') " "FROM politiker_innen.mandat;",
        ["aw_id", "legislatur", "mandatsart", "fraktion", "wkr_nr",
         "wkr_name"])
    return q


def baue(q):
    v = Verbund()


    for pid in q["dip"]["person_id"].unique():
        v.add(f"dip:{pid}")
    for rid in q["redner"]["redner_id"].unique():
        v.add(f"btv:{rid}")
    for aid in q["politician"]["aw_id"].unique():
        v.add(f"aw:{aid}")


    n_bruecke = n_btv = n_mdb = 0
    for _, z in q["bruecke"].iterrows():
        n_bruecke += v.union(f"dip:{z['person_id']}", f"btv:{z['redner_id']}",
                             f"personenbruecke ({z['lage']})")

    mdb2aw = dict(zip(q["mdb_zu_aw"]["mdb_id"], q["mdb_zu_aw"]["aw_id"]))
    echte = q["redner"][q["redner"]["kennungsart"] == "bundestagsverwaltung"]
    for rid in echte["redner_id"]:
        if rid in mdb2aw:
            n_mdb += v.union(f"btv:{rid}", f"aw:{mdb2aw[rid]}",
                             "mdb_zu_aw")
    for _, z in q["politician"].iterrows():
        if z["btv"]:
            n_btv += v.union(f"aw:{z['aw_id']}", f"btv:{z['btv']}",
                             "politician.ext_id_bundestagsverwaltung")


    n_basis = 0
    nach_basis = defaultdict(list)
    for _, z in q["dip"].drop_duplicates("person_id").iterrows():
        if z["basisdatum"]:
            nach_basis[(norm(z["vorname"]), norm(z["nachname"]),
                        z["basisdatum"])].append(z["person_id"])
    for schluessel, ids in nach_basis.items():
        for weitere in ids[1:]:
            n_basis += v.union(f"dip:{ids[0]}", f"dip:{weitere}",
                               "Name und basisdatum")


    def namensindex(rahmen, praefix, sp_vor, sp_nach):
        idx = defaultdict(set)
        for _, z in rahmen.iterrows():
            n = f"{norm(z[sp_vor])}|{norm(z[sp_nach])}"
            if n.strip("|"):
                idx[n].add(f"{praefix}:{z.iloc[0]}")
        return idx

    idx_dip = namensindex(q["dip"].drop_duplicates("person_id"), "dip",
                          "vorname", "nachname")
    idx_red = namensindex(q["redner"], "btv", "vorname", "nachname")
    idx_aw = namensindex(q["politician"], "aw", "vorname", "nachname")

    n_name, offen = 0, []
    for a_idx, b_idx, kennzeichen in ((idx_dip, idx_red, "dip~btv"),
                                      (idx_dip, idx_aw, "dip~aw"),
                                      (idx_red, idx_aw, "btv~aw")):
        for name, a_keys in a_idx.items():
            b_keys = b_idx.get(name)
            if not b_keys:
                continue
            if len(a_keys) == 1 and len(b_keys) == 1:
                a, b = next(iter(a_keys)), next(iter(b_keys))
                if v.find(a) != v.find(b):
                    n_name += v.union(a, b, f"Name eindeutig ({kennzeichen})")
            else:
                offen.append({"name": name, "seite": kennzeichen,
                              "kennungen_links": "; ".join(sorted(a_keys)),
                              "kennungen_rechts": "; ".join(sorted(b_keys))})

    return v, {"bruecke": n_bruecke, "mdb_zu_aw": n_mdb, "ext_id": n_btv,
               "basisdatum": n_basis, "name": n_name}, offen


def schreibe(v, q, zahlen, offen):
    dip = q["dip"].drop_duplicates("person_id").set_index("person_id")
    red = q["redner"].set_index("redner_id")
    pol = q["politician"].drop_duplicates("aw_id").set_index("aw_id")

    gruppen = v.gruppen()

    beschriftet = []
    for keys in gruppen:
        nach = vor = ""
        for k in sorted(keys):
            system, kenn = k.split(":", 1)
            if system == "aw" and kenn in pol.index:
                nach, vor = pol.loc[kenn, "nachname"], pol.loc[kenn, "vorname"]
            elif system == "btv" and kenn in red.index and not nach:
                nach, vor = red.loc[kenn, "nachname"], red.loc[kenn, "vorname"]
            elif system == "dip" and kenn in dip.index and not nach:
                nach, vor = dip.loc[kenn, "nachname"], dip.loc[kenn, "vorname"]
        beschriftet.append((norm(nach), norm(vor), sorted(keys)[0],
                            nach, vor, keys))
    beschriftet.sort()


    fest, hoechste = bestehende_nummern()
    zuteilung = []
    kollisionen = []
    for eintrag in beschriftet:
        keys = eintrag[5]
        alt = sorted({fest[k] for k in keys if k in fest})
        if len(alt) > 1:


            kollisionen.append((alt, sorted(keys)))
            zuteilung.append(None)
        else:
            zuteilung.append(alt[0] if alt else None)


    doppelt = defaultdict(list)
    for eintrag, pid in zip(beschriftet, zuteilung):
        if pid:
            doppelt[pid].append(sorted(eintrag[5]))
    zerfallen = {p: g for p, g in doppelt.items() if len(g) > 1}

    if kollisionen or zerfallen:
        print("\n  !!! Die Nummernvergabe ist nicht eindeutig -- " "nichts geschrieben.")
        for alt, keys in kollisionen[:20]:
            print(f"      verschmolzen: {' + '.join(alt)}  <- {'; '.join(keys)}")
        for pid, gruppen in list(zerfallen.items())[:20]:
            print(f"      zerfallen:    {pid} -> {len(gruppen)} Gruppen")
            for g in gruppen:
                print(f"                    {'; '.join(g)}")
        raise SystemExit(
            f"{len(kollisionen)} Verschmelzungen und {len(zerfallen)} Zerfaelle. " "Jeder Fall ist eine Entscheidung und wird vorgelegt, nicht geraten.")

    naechste = hoechste
    for i, pid in enumerate(zuteilung):
        if pid is None:
            naechste += 1
            zuteilung[i] = f"P{naechste:05d}"
    print(f"  {sum(1 for p in zuteilung if int(p[1:]) <= hoechste)} Nummern "
          f"uebernommen, {naechste - hoechste} neu vergeben "
          f"(P{hoechste + 1:05d} bis P{naechste:05d})")

    personen, kennungen, aliasse, rollen = [], [], [], []
    fraktionen = []
    for (_, _, _, nach, vor, keys), pid in zip(beschriftet, zuteilung):
        systeme = sorted({k.split(':', 1)[0] for k in keys})
        personen.append({
            "person": pid, "nachname": nach, "vorname": vor,
            "anzeige": f"{vor} {nach}".strip(),
            "kennungen_anzahl": len(keys),
            "systeme": "; ".join(systeme),
            "nur_eine_quelle": len(systeme) == 1,
        })
        for k in sorted(keys):
            system, kenn = k.split(":", 1)


            kennungen.append({"person": pid, "system": system,
                              "kennung": kenn,
                              "im_rednerverzeichnis":
                                  (kenn in red.index) if system == "btv"
                                  else ""})
            if system == "dip" and kenn in dip.index:
                z = dip.loc[kenn]
                aliasse.append({"person": pid, "quelle": "dip",
                                "nachname": z["nachname"],
                                "vorname": z["vorname"],
                                "namenszusatz": z["namenszusatz"],
                                "titel": z["titel"], "ortszusatz": ""})
            if system == "btv" and kenn in red.index:
                z = red.loc[kenn]
                aliasse.append({"person": pid, "quelle": "redner",
                                "nachname": z["nachname"],
                                "vorname": z["vorname"],
                                "namenszusatz": z["namenszusatz"],
                                "titel": z["titel"],
                                "ortszusatz": z["ortszusatz"]})
            if system == "aw" and kenn in pol.index:
                z = pol.loc[kenn]
                aliasse.append({"person": pid, "quelle": "abgeordnetenwatch",
                                "nachname": z["nachname"],
                                "vorname": z["vorname"],
                                "namenszusatz": z["geburtsname"],
                                "titel": z["titel"], "ortszusatz": ""})


    kenn2person = {(z["system"], z["kennung"]): z["person"] for z in kennungen}


    def wp_liste(s):
        return [t.strip() for t in re.split(r"[;|]", s or "") if t.strip()]


    LEGISLATUR = {"2009": "17", "2013": "18", "2017": "19", "2021": "20",
                  "2025": "21"}

    def wp_aus_legislatur(s):
        m = re.search(r"(\d{4})", s or "")
        return LEGISLATUR.get(m.group(1), "") if m else ""


    lookup = {}
    pfad = AUSGABE / "rollen_normalisierung.csv"
    if pfad.exists():
        for _, z in pd.read_csv(pfad, dtype=str).fillna("").iterrows():
            lookup[(z["quelle"], z["art"], z["wert"])] = (
                z["rolle_normalisiert"], z["ressort"], z["ebene"])
    else:
        print("  WARNUNG: rollen_normalisierung.csv fehlt, " "rolle_normalisiert bleibt leer")

    def rolle(p, system, kenn, quelle, art, wert, wps, wp_quelle, **rest):
        norm_rolle, norm_ressort, ebene = lookup.get((quelle, art, wert),
                                                     ("", "", ""))
        wps = wps or [""]
        for wp in wps:
            z = {"person": p, "system": system, "kennung": kenn,
                 "quelle": quelle, "art": art, "wert": wert,
                 "rolle_normalisiert": norm_rolle, "ebene": ebene,
                 "wahlperiode": wp, "wahlperiode_quelle": wp_quelle,
                 "fraktion": "", "ressort": norm_ressort, "bundesland": "",
                 "wahlkreis": "", "belege": "", "belege_gesamt": "",
                 "belege_zeitraum": ""}
            z.update(rest)


            if len(wps) > 1 and z["belege"]:
                z["belege_gesamt"] = z["belege"]
                z["belege_zeitraum"] = "; ".join(wps)
                z["belege"] = ""
            rollen.append(z)

    for _, z in q["dip"].iterrows():
        p = kenn2person.get(("dip", z["person_id"]))
        if p:


            rolle(p, "dip", z["person_id"], "dip_person", "funktion",
                  z["funktion"], [z["wahlperiode"]], "abgefragt",
                  ressort=z["ressort"], bundesland=z["bundesland"])


    for _, z in q["merkmal"].iterrows():
        if z["art"] != "rolle_lang":
            continue
        p = kenn2person.get(("btv", z["redner_id"]))
        if p:
            rolle(p, "btv", z["redner_id"], "redner_merkmal", z["art"],
                  z["wert"], wp_liste(z["wahlperioden"]), "beobachtet",
                  belege=z["reden"])

    for _, z in q["mandat"].iterrows():
        p = kenn2person.get(("aw", z["aw_id"]))
        if p:
            rolle(p, "aw", z["aw_id"], "mandat", "mandatsart",
                  z["mandatsart"], [wp_aus_legislatur(z["legislatur"])],
                  "legislatur", fraktion=z["fraktion"],
                  wahlkreis=f"{z['wkr_nr']} {z['wkr_name']}".strip())


    def fraktion(p, system, kenn, quelle, wert, wps, wp_quelle, zeitrichtig,
                 belege=""):
        wps = wps or [""]
        for wp in wps:
            z = {"person": p, "system": system, "kennung": kenn,
                 "quelle": quelle, "fraktion": wert, "wahlperiode": wp,
                 "wahlperiode_quelle": wp_quelle,
                 "zeitrichtig": zeitrichtig, "belege": belege,
                 "belege_gesamt": "", "belege_zeitraum": ""}
            if len(wps) > 1 and belege:
                z["belege_gesamt"] = belege
                z["belege_zeitraum"] = "; ".join(wps)
                z["belege"] = ""
            fraktionen.append(z)

    for _, z in q["merkmal"].iterrows():
        if z["art"] != "fraktion":
            continue
        p = kenn2person.get(("btv", z["redner_id"]))
        if p:
            fraktion(p, "btv", z["redner_id"], "redner_merkmal",
                     z["wert"], wp_liste(z["wahlperioden"]), "beobachtet",
                     True, belege=z["reden"])

    for _, z in q["mandat"].iterrows():
        p = kenn2person.get(("aw", z["aw_id"]))
        if p and z["fraktion"]:

            rein = re.sub(r"\s*\(.*\)\s*$", "", z["fraktion"]).strip()
            fraktion(p, "aw", z["aw_id"], "mandat", rein,
                     [wp_aus_legislatur(z["legislatur"])], "legislatur", True)


    for _, z in q["alias"].iterrows():
        p = kenn2person.get(("btv", z["mdb_id"]))
        if p:
            aliasse.append({"person": p, "quelle": f"mdb_namensalias/{z['verfahren']}",
                            "nachname": z["nachname"], "vorname": z["vorname"],
                            "namenszusatz": "", "titel": "",
                            "ortszusatz": z["ortszusatz"]})


    kenn2p = {(z["system"], z["kennung"]): z["person"] for z in kennungen}

    def knoten(s):
        aus = set()
        for x in s.split(";"):
            x = x.strip()
            if x:
                system, kenn = x.split(":", 1)
                aus.add(kenn2p.get((system, kenn)))
        return aus

    echt_offen = []
    for z in offen:
        beteiligt = knoten(z["kennungen_links"]) | knoten(z["kennungen_rechts"])
        if len(beteiligt) < 2:
            continue
        z = dict(z)
        z["knoten"] = "; ".join(sorted(x for x in beteiligt if x))
        z["knoten_anzahl"] = len(beteiligt)
        echt_offen.append(z)
    print(f"  offene Faelle: {len(offen)} notiert, davon {len(echt_offen)} "
          f"wirklich offen, {len(offen) - len(echt_offen)} laengst verschmolzen")
    offen = echt_offen


    if len(q["platzhalter"]):
        print(f"  {len(q['platzhalter'])} Platzhalter-Kandidaturen ohne "
              f"Personenknoten (Eingriff E13)")

    rollenliste = (pd.DataFrame(rollen)
                   .groupby(["quelle", "art", "wert"])
                   .agg(personen=("person", "nunique"),
                        zeilen=("person", "size"))
                   .reset_index()
                   .sort_values(["quelle", "personen"], ascending=[True, False]))

    AUSGABE.mkdir(parents=True, exist_ok=True)
    for name, zeilen in (("person", personen), ("person_kennung", kennungen),
                         ("person_alias", aliasse), ("person_rolle", rollen),
                         ("person_fraktion", fraktionen),
                         ("rolle", rollenliste.to_dict("records")),
                         ("offene_faelle", offen)):
        d = pd.DataFrame(zeilen).drop_duplicates()
        d.to_csv(AUSGABE / f"{name}.csv", index=False, encoding="utf-8")
        print(f"  {name}.csv: {len(d)} Zeilen")


    p = pd.DataFrame(personen)
    k = pd.DataFrame(kennungen)
    print(f"\n----- Bericht -----")
    print(f"Kennungen im Eingang : dip {q['dip']['person_id'].nunique()}, "
          f"redner {len(q['redner'])}, aw {len(q['politician'])} "
          f"= {q['dip']['person_id'].nunique() + len(q['redner']) + len(q['politician'])}")
    print(f"Personen im Ergebnis : {len(p)}")
    print(f"Zusammenlegungen     : Bruecke {zahlen['bruecke']}, "
          f"mdb_zu_aw {zahlen['mdb_zu_aw']}, ext_id {zahlen['ext_id']}, "
          f"Name+basisdatum {zahlen['basisdatum']}, "
          f"Name eindeutig {zahlen['name']}")
    print(f"\nPersonen nach Zahl der Kennungen:")
    print(p["kennungen_anzahl"].value_counts().sort_index().to_string())
    print(f"\nPersonen nach beteiligten Systemen:")
    print(p["systeme"].value_counts().to_string())
    print(f"\nOffene Faelle (Name passt, aber nicht eindeutig): {len(offen)}")


def main():
    print("Lese die drei Bestaende ...")
    q = lies_quellen()
    for name, rahmen in q.items():
        print(f"  {name:12s} {len(rahmen):6d} Zeilen")
    print("\nFuehre zusammen ...")
    v, zahlen, offen = baue(q)
    print("\nSchreibe ...")
    schreibe(v, q, zahlen, offen)
    print(f"\nAusgabe in: {AUSGABE.resolve()}")


if __name__ == "__main__":
    main()
