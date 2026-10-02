import json
import time
from datetime import datetime
from pathlib import Path

import certifi
import requests

BASE = "https://search.dip.bundestag.de/api/v1"
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import dip_schluessel
API_KEY = dip_schluessel()

WAHLPERIODEN = (18, 19, 20)
TYPEN = ("Kleine Anfrage", "Große Anfrage")
MAX_SEITEN = 0
import zwischenstand

AUSGABE = zwischenstand.fuer(__file__) / f"anfragetexte_{datetime.now():%Y%m%d_%H%M%S}"
ERWARTET = Path("../../02_clean/drucksachen/export")

_session = requests.Session()
_session.verify = certifi.where()
_session.headers.update({
    "Accept": "application/json",
    "Authorization": f"ApiKey {API_KEY}",
})


def api_get(path, params):
    for versuch in range(1, 6):
        try:
            resp = _session.get(f"{BASE}{path}", params=params, timeout=90)
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


def erwartete_ids():
    import csv as _csv
    erwartet = {}
    for wp in WAHLPERIODEN:
        pfad = ERWARTET / f"zuordnung_wp{wp}.csv"
        if not pfad.exists():
            print(f"  WARNUNG: {pfad} fehlt, keine Sollmenge fuer WP{wp}")
            continue
        with open(pfad, encoding="utf-8") as fh:
            for zeile in _csv.DictReader(fh):
                if zeile["drucksachetyp"] in TYPEN:
                    erwartet.setdefault(wp, set()).add(zeile["drucksache_id"])
    return erwartet


def hole(wp, typ, schreiber):
    params = {"f.wahlperiode": wp, "f.zuordnung": "BT",
              "f.drucksachetyp": typ}
    cursor, seiten, gefunden, geholt = None, 0, None, 0
    gesehen, ohne_text, fremde_typen = set(), 0, {}
    while True:
        p = dict(params)
        if cursor:
            p["cursor"] = cursor
        data = api_get("/drucksache-text", p)
        if data is None:
            break
        if gefunden is None:
            gefunden = data.get("numFound")
            print(f"  [{typ} WP{wp}] numFound = {gefunden}")
        neu = [d for d in data.get("documents", []) if d.get("id") not in gesehen]
        for d in neu:
            gesehen.add(d["id"])
            t = d.get("drucksachetyp", "")
            if t != typ:
                fremde_typen[t] = fremde_typen.get(t, 0) + 1
            if not d.get("text"):
                ohne_text += 1
            schreiber.write(json.dumps({
                "wahlperiode": wp,
                "drucksache_id": d.get("id", ""),
                "dokumentnummer": d.get("dokumentnummer", ""),
                "drucksachetyp": d.get("drucksachetyp", ""),
                "datum": d.get("datum", ""),
                "titel": d.get("titel", ""),
                "pdf_url": (d.get("fundstelle") or {}).get("pdf_url", ""),
                "zeichen": len(d.get("text") or ""),
                "text": d.get("text", ""),
            }, ensure_ascii=False) + "\n")
        geholt += len(neu)
        seiten += 1
        if seiten % 25 == 0 or not neu:
            print(f"  [{typ} WP{wp}] Seite {seiten}: {geholt} / {gefunden}")
        if fremde_typen:
            raise SystemExit(
                f"ABBRUCH: Filter f.drucksachetyp hat nicht gegriffen, "
                f"Antwort enthaelt {fremde_typen}. Kein Teilabzug.")
        neuer_cursor = data.get("cursor")
        if not neuer_cursor or neuer_cursor == cursor or not neu:
            break
        cursor = neuer_cursor
        if MAX_SEITEN and seiten >= MAX_SEITEN:
            print(f"  [{typ} WP{wp}] Halt bei MAX_SEITEN={MAX_SEITEN}")
            break
        time.sleep(0.3)
    return gesehen, gefunden, ohne_text


def main():
    AUSGABE.mkdir(parents=True, exist_ok=True)
    soll = erwartete_ids()
    bericht = []

    for wp in WAHLPERIODEN:
        pfad = AUSGABE / f"anfragetext_wp{wp}.jsonl"
        geholt_ids, leer_ges = set(), 0
        with open(pfad, "w", encoding="utf-8") as fh:
            for typ in TYPEN:
                ids, gefunden, ohne_text = hole(wp, typ, fh)
                geholt_ids |= ids
                leer_ges += ohne_text
        erwartet = soll.get(wp, set())
        fehlt = erwartet - geholt_ids
        ueberzaehlig = geholt_ids - erwartet
        groesse = pfad.stat().st_size / 1_000_000
        print(f"\n  WP{wp}: {len(geholt_ids)} Texte, {groesse:.1f} MB")
        print(f"    erwartet {len(erwartet)} | fehlt {len(fehlt)} | "
              f"nicht erwartet {len(ueberzaehlig)} | Textfeld leer {leer_ges}")
        if fehlt:
            print(f"    fehlende Ids (erste 10): {sorted(fehlt)[:10]}")
        bericht.append((wp, len(geholt_ids), len(erwartet), len(fehlt),
                        len(ueberzaehlig), leer_ges, groesse))

    print("\n----- Bericht -----")
    print(f"{'WP':>4} {'geholt':>8} {'erwartet':>9} {'fehlt':>7} "
          f"{'unerwartet':>11} {'ohne Text':>10} {'MB':>8}")
    for z in bericht:
        print(f"{z[0]:>4} {z[1]:>8} {z[2]:>9} {z[3]:>7} {z[4]:>11} "
              f"{z[5]:>10} {z[6]:>8.1f}")
    print(f"\nAusgabe in: {AUSGABE.resolve()}")


if __name__ == "__main__":
    main()
