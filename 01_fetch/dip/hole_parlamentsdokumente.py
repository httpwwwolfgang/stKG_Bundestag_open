import csv
import json
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import certifi
import requests

BASE = "https://search.dip.bundestag.de/api/v1"
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dip_schluessel
API_KEY = dip_schluessel()


WAHLPERIODEN = {
    18: ("", ""),
    19: ("", ""),
    20: ("", ""),
}
MAX_SEITEN = 0
import zwischenstand


LIEFERUNG = "dip_dokumente"

AUSGABE = zwischenstand.fuer(__file__) / f"dokumente_{datetime.now():%Y%m%d_%H%M%S}"


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


_session = requests.Session()
_session.verify = certifi.where()
_session.headers.update({
    "Accept": "application/json",
    "Authorization": f"ApiKey {API_KEY}",
})


def api_get(path, params):
    url = f"{BASE}{path}"
    for versuch in range(1, 6):
        try:
            resp = _session.get(url, params=params, timeout=60)
        except (requests.Timeout, requests.ConnectionError):
            if versuch < 5:
                time.sleep(2 ** versuch)
                continue
            raise
        if resp.status_code == 404:
            return None
        if resp.status_code in (429, 500, 502, 503, 504) and versuch < 5:
            time.sleep(2 ** versuch)
            continue
        resp.raise_for_status()
        return resp.json()


def hole_alle(path, params, name):
    docs, cursor, seiten, gefunden = [], None, 0, None
    gesehen = set()
    while True:
        p = dict(params)
        if cursor:
            p["cursor"] = cursor
        data = api_get(path, p)
        if data is None:
            break
        if gefunden is None:
            gefunden = data.get("numFound")
        neu = [d for d in data.get("documents", []) if d.get("id") not in gesehen]
        gesehen.update(d["id"] for d in neu if "id" in d)
        docs.extend(neu)
        seiten += 1
        print(f"  [{name}] Seite {seiten}: {len(docs)} / {gefunden}")
        neuer_cursor = data.get("cursor")
        if not neuer_cursor or neuer_cursor == cursor or not neu:
            break
        cursor = neuer_cursor
        if MAX_SEITEN and seiten >= MAX_SEITEN:
            print(f"  [{name}] ABBRUCH bei MAX_SEITEN={MAX_SEITEN} - "
                  f"Abzug ist NICHT vollstaendig")
            break
        time.sleep(0.3)
    return docs, gefunden


def basis_params(wp, **extra):
    p = {"f.wahlperiode": wp}
    start, ende = WAHLPERIODEN[wp]
    if start:
        p["f.datum.start"] = start
    if ende:
        p["f.datum.end"] = ende
    p.update(extra)
    return p


def vorschau_report(docs, entitaet):
    zeilen = []
    zaehlfelder = set()
    for d in docs:
        zaehlfelder.update(k for k in d if k.endswith("_anzahl"))
    for zf in sorted(zaehlfelder):
        stamm = zf[:-len("_anzahl")]
        for liste in (stamm, f"{stamm}_anzeige"):
            faelle = gekuerzt = maxlen = 0
            for d in docs:
                if zf not in d or not isinstance(d.get(liste), list):
                    continue
                n, g = d[zf], len(d[liste])
                faelle += 1
                maxlen = max(maxlen, g)
                if isinstance(n, int) and n > g:
                    gekuerzt += 1
            if faelle:
                zeilen.append({
                    "entitaet": entitaet,
                    "zaehlfeld": zf,
                    "listenfeld": liste,
                    "faelle": faelle,
                    "gekuerzt": gekuerzt,
                    "max_geliefert": maxlen,
                })
        if not any(z["zaehlfeld"] == zf and z["entitaet"] == entitaet
                   for z in zeilen):
            zeilen.append({
                "entitaet": entitaet,
                "zaehlfeld": zf,
                "listenfeld": "(keine Liste im Dokument)",
                "faelle": sum(1 for d in docs if zf in d),
                "gekuerzt": -1,
                "max_geliefert": -1,
            })
    return zeilen


def feldinventar(docs, entitaet):
    vorkommen = Counter()
    laengen = defaultdict(list)
    for d in docs:
        vorkommen.update(d.keys())
        for k, v in d.items():
            if isinstance(v, list):
                laengen[k].append(len(v))
    zeilen = []
    for feld, anzahl in sorted(vorkommen.items()):
        ll = laengen.get(feld)
        zeilen.append({
            "entitaet": entitaet,
            "feld": feld,
            "dokumente_mit_feld": anzahl,
            "dokumente_gesamt": len(docs),
            "ist_liste": bool(ll),
            "listenlaenge_min": min(ll) if ll else "",
            "listenlaenge_max": max(ll) if ll else "",
        })
    return zeilen


def zeilen_drucksache(docs, wp):
    haupt, urheber, ressort = [], [], []
    for d in docs:
        f = d.get("fundstelle") or {}
        haupt.append({
            "wahlperiode": wp,
            "drucksache_id": d.get("id", ""),
            "dokumentnummer": d.get("dokumentnummer", ""),
            "dokumentart": d.get("dokumentart", ""),
            "drucksachetyp": d.get("drucksachetyp", ""),
            "datum": d.get("datum", ""),
            "verteildatum": f.get("verteildatum", ""),
            "titel": clean(d.get("titel", "")),
            "herausgeber": d.get("herausgeber", ""),
            "pdf_url": f.get("pdf_url", ""),
            "fundstelle_id": f.get("id", ""),
            "autoren_anzahl": d.get("autoren_anzahl", ""),
            "vorgangsbezug_anzahl": d.get("vorgangsbezug_anzahl", ""),
            "aktualisiert": d.get("aktualisiert", ""),
        })
        for u in (d.get("urheber") or []):
            urheber.append({
                "drucksache_id": d.get("id", ""),
                "dokumentnummer": d.get("dokumentnummer", ""),
                "bezeichnung": u.get("bezeichnung", ""),
                "titel": clean(u.get("titel", "")),
                "einbringer": u.get("einbringer", ""),
            })
        for r in (d.get("ressort") or []):
            ressort.append({
                "drucksache_id": d.get("id", ""),
                "dokumentnummer": d.get("dokumentnummer", ""),
                "titel": clean(r.get("titel", "")),
                "federfuehrend": r.get("federfuehrend", ""),
            })
    return haupt, urheber, ressort


def zeilen_aktivitaet(docs, wp):
    haupt, deskriptoren, bezug = [], [], []
    for a in docs:
        f = a.get("fundstelle") or {}
        haupt.append({
            "wahlperiode": wp,
            "aktivitaet_id": a.get("id", ""),
            "aktivitaetsart": a.get("aktivitaetsart", ""),
            "person_id": a.get("person_id", ""),
            "titel": clean(a.get("titel", "")),
            "datum": a.get("datum", ""),
            "dokumentart": a.get("dokumentart", ""),
            "fundstelle_dokumentart": f.get("dokumentart", ""),
            "dokumentnummer": f.get("dokumentnummer", ""),
            "drucksachetyp": f.get("drucksachetyp", ""),
            "fundstelle_id": f.get("id", ""),
            "seite": f.get("seite", ""),
            "pdf_url": f.get("pdf_url", ""),
            "vorgangsbezug_anzahl": a.get("vorgangsbezug_anzahl", ""),
            "abstract": clean(a.get("abstract", "")),
        })
        for d in (a.get("deskriptor") or []):
            deskriptoren.append({
                "aktivitaet_id": a.get("id", ""),
                "name": clean(d.get("name", "")),
                "typ": d.get("typ", ""),
                "fundstelle": d.get("fundstelle", ""),
            })

        for v in (a.get("vorgangsbezug") or []):
            bezug.append({
                "aktivitaet_id": a.get("id", ""),
                "vorgang_id": v.get("id", ""),
                "vorgangstyp": v.get("vorgangstyp", ""),
                "quelle": "vorschau",
            })
    return haupt, deskriptoren, bezug


def zeilen_vorgangsposition(docs, wp):
    haupt, urheber = [], []
    for vp in docs:
        f = vp.get("fundstelle") or {}
        haupt.append({
            "wahlperiode": wp,
            "position_id": vp.get("id", ""),
            "vorgang_id": vp.get("vorgang_id", ""),
            "vorgangsposition": vp.get("vorgangsposition", ""),
            "vorgangstyp": vp.get("vorgangstyp", ""),
            "titel": clean(vp.get("titel", "")),
            "abstract": clean(vp.get("abstract", "")),
            "datum": vp.get("datum", ""),
            "dokumentart": vp.get("dokumentart", ""),
            "dokumentnummer": f.get("dokumentnummer", ""),
            "drucksachetyp": f.get("drucksachetyp", ""),
            "fundstelle_id": f.get("id", ""),
            "fundstelle_datum": f.get("datum", ""),
            "verteildatum": f.get("verteildatum", ""),
            "herausgeber": f.get("herausgeber", ""),
            "seite": f.get("seite", ""),
            "anfangsseite": f.get("anfangsseite", ""),
            "endseite": f.get("endseite", ""),
            "anfangsquadrant": f.get("anfangsquadrant", ""),
            "endquadrant": f.get("endquadrant", ""),
            "pdf_url": f.get("pdf_url", ""),
            "xml_url": f.get("xml_url", ""),
            "zuordnung": vp.get("zuordnung", ""),
            "gang": vp.get("gang", ""),
            "fortsetzung": vp.get("fortsetzung", ""),
            "nachtrag": vp.get("nachtrag", ""),
            "aktivitaet_anzahl": vp.get("aktivitaet_anzahl", ""),
            "aktualisiert": vp.get("aktualisiert", ""),
        })
        for u in (vp.get("urheber") or []):
            urheber.append({
                "position_id": vp.get("id", ""),
                "bezeichnung": u.get("bezeichnung", ""),
                "titel": clean(u.get("titel", "")),
                "einbringer": u.get("einbringer", ""),
            })
    return haupt, urheber


def zeilen_vorgang(docs, wp):
    haupt, sachgebiete, deskriptoren, initiative = [], [], [], []
    verlinkung = []
    for v in docs:
        haupt.append({
            "wahlperiode": wp,
            "vorgang_id": v.get("id", ""),
            "vorgangstyp": v.get("vorgangstyp", ""),
            "titel": clean(v.get("titel", "")),
            "datum": v.get("datum", ""),
            "beratungsstand": v.get("beratungsstand", ""),
            "abstract": clean(v.get("abstract", "")),
            "gesta": v.get("gesta", ""),
            "kom": v.get("kom", ""),
            "ratsdok": v.get("ratsdok", ""),
            "archiv": v.get("archiv", ""),
            "zustimmungsbeduerftigkeit": _liste(
                v.get("zustimmungsbeduerftigkeit")),
            "aktualisiert": v.get("aktualisiert", ""),
        })


        for vl in (v.get("vorgang_verlinkung") or []):
            zeile = {"vorgang_id": v.get("id", "")}
            for k, val in vl.items():
                zeile[k] = _liste(val)
            verlinkung.append(zeile)
        for s in (v.get("sachgebiet") or []):
            sachgebiete.append({"vorgang_id": v.get("id", ""),
                                "sachgebiet": clean(s)})
        for d in (v.get("deskriptor") or []):
            deskriptoren.append({
                "vorgang_id": v.get("id", ""),
                "name": clean(d.get("name", "")),
                "typ": d.get("typ", ""),
                "fundstelle": d.get("fundstelle", ""),
            })
        for i in (v.get("initiative") or []):
            initiative.append({"vorgang_id": v.get("id", ""),
                               "initiative": clean(i)})
    return haupt, sachgebiete, deskriptoren, initiative, verlinkung


def _liste(v):
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return clean(str(v)) if v is not None else ""


def zeilen_person(docs, wp):
    haupt, rollen = [], []
    for p in docs:
        haupt.append({
            "abgefragt_wahlperiode": wp,
            "person_id": p.get("id", ""),
            "nachname": clean(p.get("nachname", "")),
            "vorname": clean(p.get("vorname", "")),
            "namenszusatz": clean(p.get("namenszusatz", "")),
            "titel": clean(p.get("titel", "")),
            "typ": p.get("typ", ""),
            "fraktion": _liste(p.get("fraktion")),
            "funktion": _liste(p.get("funktion")),
            "funktionszusatz": _liste(p.get("funktionszusatz")),
            "bundesland": _liste(p.get("bundesland")),
            "ressort": _liste(p.get("ressort")),
            "wahlkreiszusatz": clean(p.get("wahlkreiszusatz", "")),
            "wahlperioden": _liste(p.get("wahlperiode")),
            "basisdatum": p.get("basisdatum", ""),
            "datum": p.get("datum", ""),
            "aktualisiert": p.get("aktualisiert", ""),
            "rollen_anzahl": len(p.get("person_roles") or []),
        })

        for r in (p.get("person_roles") or []):
            zeile = {"person_id": p.get("id", "")}
            for k, v in r.items():
                zeile[k] = _liste(v)
            rollen.append(zeile)
    return haupt, rollen


def pruefe(drucksachen, aktivitaeten, positionen, vorgaenge, personen,
           fenster):
    start, ende = fenster


    akt_je_ds = defaultdict(list)
    for a in aktivitaeten:
        if a["fundstelle_id"] and a["fundstelle_dokumentart"] == "Drucksache":
            akt_je_ds[a["fundstelle_id"]].append(a)

    vorgang_je_ds = defaultdict(set)
    for p in positionen:
        if (p["fundstelle_id"] and p["vorgang_id"]
                and p["dokumentart"] == "Drucksache"):
            vorgang_je_ds[p["fundstelle_id"]].add(p["vorgang_id"])

    befunde = []
    for d in drucksachen:
        nr = d["dokumentnummer"]
        schluessel = d["fundstelle_id"] or d["drucksache_id"]
        soll_a = d["autoren_anzahl"]
        ist_a = len(akt_je_ds.get(schluessel, []))
        soll_v = d["vorgangsbezug_anzahl"]
        ist_v = len(vorgang_je_ds.get(schluessel, set()))
        am_rand = bool(start) and d["datum"] in (start, ende)
        if isinstance(soll_a, int) and soll_a != ist_a:
            befunde.append({
                "pruefung": "autoren", "dokumentnummer": nr,
                "drucksachetyp": d["drucksachetyp"], "datum": d["datum"],
                "angekuendigt": soll_a, "gefunden": ist_a,
                "fensterrand": am_rand,
            })
        if isinstance(soll_v, int) and soll_v != ist_v:
            befunde.append({
                "pruefung": "vorgaenge", "dokumentnummer": nr,
                "drucksachetyp": d["drucksachetyp"], "datum": d["datum"],
                "angekuendigt": soll_v, "gefunden": ist_v,
                "fensterrand": am_rand,
            })


    person_ids = {p["person_id"] for p in personen}
    vorgang_ids = {v["vorgang_id"] for v in vorgaenge}
    ds_nummern = {d["dokumentnummer"] for d in drucksachen}

    offen = {
        "aktivitaeten_ohne_person_im_abzug": sum(
            1 for a in aktivitaeten
            if a["person_id"] and a["person_id"] not in person_ids),
        "aktivitaeten_ohne_drucksache_im_abzug": sum(
            1 for a in aktivitaeten
            if a["dokumentnummer"] and a["dokumentnummer"] not in ds_nummern),
        "positionen_ohne_vorgang_im_abzug": sum(
            1 for p in positionen
            if p["vorgang_id"] and p["vorgang_id"] not in vorgang_ids),
        "drucksachen_ohne_urheber": 0,
    }
    return befunde, offen


def schreibe(name, zeilen):
    if not zeilen:
        print(f"  {name}: 0 Zeilen - nicht geschrieben")
        return
    spalten = list(zeilen[0].keys())
    for z in zeilen:
        for k in z:
            if k not in spalten:
                spalten.append(k)
    AUSGABE.mkdir(parents=True, exist_ok=True)
    pfad = AUSGABE / f"{name}.csv"
    with open(pfad, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=spalten, restval="")
        w.writeheader()
        w.writerows(zeilen)
    print(f"  {name}.csv: {len(zeilen)} Zeilen, {len(spalten)} Spalten")


def main():
    inventar, vorschau = [], []
    alle_befunde = []

    for wp in WAHLPERIODEN:
        fenster = WAHLPERIODEN[wp]
        print(f"\n########## Wahlperiode {wp}  Fenster {fenster} ##########")

        print("Drucksachen ...")
        roh_ds, n_ds = hole_alle("/drucksache",
                                 basis_params(wp, **{"f.zuordnung": "BT"}),
                                 "drucksache")

        print("Aktivitaeten (Filter f.dokumentart=Drucksache) ...")
        roh_ak, n_ak = hole_alle(
            "/aktivitaet",
            basis_params(wp, **{"f.zuordnung": "BT",
                                "f.dokumentart": "Drucksache"}),
            "aktivitaet")
        arten = Counter((a.get("fundstelle") or {}).get("dokumentart", "")
                        for a in roh_ak)
        print(f"  Fundstellenart in der Antwort: {dict(arten)}")
        if len(arten) > 1 or "Drucksache" not in arten:
            print("  ACHTUNG: Filter hat nicht gegriffen oder liefert " "gemischte Arten - lokal ausgewertet wird " "fundstelle.dokumentart")

        print("Vorgangspositionen ...")
        roh_vp, n_vp = hole_alle("/vorgangsposition",
                                 basis_params(wp, **{"f.zuordnung": "BT"}),
                                 "vorgangsposition")

        print("Vorgaenge ...")
        roh_vg, n_vg = hole_alle("/vorgang", basis_params(wp), "vorgang")

        print("Personen ...")
        roh_pe, n_pe = hole_alle("/person", {"f.wahlperiode": wp}, "person")

        for docs, name in ((roh_ds, "drucksache"), (roh_ak, "aktivitaet"),
                           (roh_vp, "vorgangsposition"), (roh_vg, "vorgang"),
                           (roh_pe, "person")):
            inventar.extend(feldinventar(docs, name))
            vorschau.extend(vorschau_report(docs, name))

        ds, ds_urheber, ds_ressort = zeilen_drucksache(roh_ds, wp)
        ak, ak_desk, ak_bezug = zeilen_aktivitaet(roh_ak, wp)
        vp, vp_urheber = zeilen_vorgangsposition(roh_vp, wp)
        vg, vg_sach, vg_desk, vg_init, vg_link = zeilen_vorgang(roh_vg, wp)
        pe, pe_rollen = zeilen_person(roh_pe, wp)

        print("\nSchreibe CSV ...")
        for name, zeilen in (
            (f"drucksache_wp{wp}", ds),
            (f"drucksache_urheber_wp{wp}", ds_urheber),
            (f"drucksache_ressort_wp{wp}", ds_ressort),
            (f"aktivitaet_wp{wp}", ak),
            (f"aktivitaet_deskriptor_wp{wp}", ak_desk),
            (f"aktivitaet_vorgang_vorschau_wp{wp}", ak_bezug),
            (f"vorgangsposition_wp{wp}", vp),
            (f"vorgangsposition_urheber_wp{wp}", vp_urheber),
            (f"vorgang_wp{wp}", vg),
            (f"vorgang_sachgebiet_wp{wp}", vg_sach),
            (f"vorgang_deskriptor_wp{wp}", vg_desk),
            (f"vorgang_initiative_wp{wp}", vg_init),
            (f"vorgang_verlinkung_wp{wp}", vg_link),
            (f"person_wp{wp}", pe),
            (f"person_rolle_wp{wp}", pe_rollen),
        ):
            schreibe(name, zeilen)

        befunde, offen = pruefe(ds, ak, vp, vg, pe, fenster)
        for b in befunde:
            b["wahlperiode"] = wp
        alle_befunde.extend(befunde)


        mit_urheber = {u["dokumentnummer"] for u in ds_urheber}
        ohne_urheber = [d for d in ds if d["dokumentnummer"] not in mit_urheber]

        print(f"\n----- Bericht Wahlperiode {wp} -----")
        print(f"numFound laut API: drucksache={n_ds} aktivitaet={n_ak} "
              f"vorgangsposition={n_vp} vorgang={n_vg} person={n_pe}")
        print(f"geholt:            drucksache={len(ds)} aktivitaet={len(ak)} "
              f"vorgangsposition={len(vp)} vorgang={len(vg)} person={len(pe)}")
        print(f"Drucksachen ohne Urheber-Eintrag: {len(ohne_urheber)} von "
              f"{len(ds)}")

        mit_sach = {s["vorgang_id"] for s in vg_sach}
        mit_desk = {d["vorgang_id"] for d in vg_desk}
        frakt_pe = {p["person_id"] for p in pe if p["fraktion"]}
        vg_ohne_sach = Counter(v["vorgangstyp"] for v in vg
                               if v["vorgang_id"] not in mit_sach)
        print(f"Vorgaenge mit Sachgebiet : "
              f"{sum(1 for v in vg if v['vorgang_id'] in mit_sach)} von {len(vg)}")
        print(f"Vorgaenge mit Deskriptor : "
              f"{sum(1 for v in vg if v['vorgang_id'] in mit_desk)} von {len(vg)}")
        print(f"  Vorgangstypen ohne Sachgebiet: "
              f"{dict(vg_ohne_sach.most_common(6))}")
        print(f"Personen mit Fraktion    : {len(frakt_pe)} von {len(pe)}")
        print(f"Aktivitaeten mit Fraktion ueber person_id: "
              f"{sum(1 for a in ak if a['person_id'] in frakt_pe)} von {len(ak)}")
        print(f"Deskriptoren: {len(vg_desk)} am Vorgang, {len(ak_desk)} an "
              f"der Aktivitaet")
        for k, v in offen.items():
            if k != "drucksachen_ohne_urheber":
                print(f"{k}: {v}")
        autoren_fehl = [b for b in befunde if b["pruefung"] == "autoren"]
        vorgang_fehl = [b for b in befunde if b["pruefung"] == "vorgaenge"]
        print(f"Drucksachen mit abweichender Autorenzahl: {len(autoren_fehl)} "
              f"von {len(ds)}")
        print(f"Drucksachen mit abweichender Vorgangszahl: {len(vorgang_fehl)} "
              f"von {len(ds)}  (davon am Fensterrand: "
              f"{sum(1 for b in vorgang_fehl if b['fensterrand'])})")
        for b in autoren_fehl[:15]:
            print(f"   AUTOREN  {b['dokumentnummer']:>10s} "
                  f"{b['drucksachetyp'][:28]:28s} "
                  f"angekuendigt={b['angekuendigt']:>3} "
                  f"gefunden={b['gefunden']:>3}")
        for b in vorgang_fehl[:15]:
            print(f"   VORGANG  {b['dokumentnummer']:>10s} "
                  f"{b['drucksachetyp'][:28]:28s} "
                  f"angekuendigt={b['angekuendigt']:>3} "
                  f"gefunden={b['gefunden']:>3} "
                  f"rand={b['fensterrand']}")

    schreibe("pruefbefunde", alle_befunde)
    schreibe("feldinventar", inventar)
    schreibe("vorschau_report", vorschau)

    print("\n----- Vorschau-Felder (Zaehlfeld gegen gelieferte Liste) -----")
    for z in vorschau:
        print(f"  {z['entitaet']:18s} {z['zaehlfeld']:24s} "
              f"{z['listenfeld']:26s} faelle={z['faelle']:6d} "
              f"gekuerzt={z['gekuerzt']:6d} max={z['max_geliefert']}")

    print(f"\nAusgabe in: {AUSGABE.resolve()}")


if __name__ == "__main__":
    main()
