import hashlib
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

BASIS = "https://www.bundestag.de"
LISTE = (BASIS + "/ajax/filterlist/de/parlament/plenum/abstimmung/liste" "/462112-462112")
SEITE = 30
PAUSE = 1.0


ZIEL = (Path(__file__).resolve().parents[4] / "Daten" / "politiker_innen"
        / "bundestag_namentliche_abstimmungen")

WAHLPERIODEN = (
    (18, date(2013, 10, 22), date(2017, 10, 23)),
    (19, date(2017, 10, 24), date(2021, 10, 25)),
    (20, date(2021, 10, 26), date(2025, 3, 24)),
)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("namentliche")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "wahlkreis-kg-import/1.0 (Forschungsprojekt Masterarbeit)",
    "Accept": "text/html",
})


def hole(url, **params):
    for versuch in range(4):
        try:
            r = SESSION.get(url, params=params or None, timeout=60)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            wart = 2 ** versuch
            log.warning("   Abruf fehlgeschlagen (%s), warte %ds", e, wart)
            time.sleep(wart)
    raise SystemExit(f"Abruf endgueltig fehlgeschlagen: {url}")


def eintraege(html):
    treffer = []
    for zeile in re.split(r'<tr\b', html)[1:]:
        m = re.search(r'href="(https://www\.bundestag\.de/resource/blob/'
                      r'[^"]+?\.xlsx?)"', zeile)
        if not m:
            continue
        url = m.group(1)


        p = re.search(r'href="(https://www\.bundestag\.de/resource/blob/'
                      r'[^"]+?\.pdf)"', zeile)
        pdf = p.group(1) if p else None

        d = None
        aus_name = re.search(r"/(\d{8})[_-]", url)
        if aus_name:
            try:
                d = datetime.strptime(aus_name.group(1), "%Y%m%d").date()
            except ValueError:
                d = None
        if d is None:
            im_text = re.search(r"(\d{2}\.\d{2}\.\d{4})", zeile)
            if not im_text:
                continue
            d = datetime.strptime(im_text.group(1), "%d.%m.%Y").date()


        t = re.search(r"\d{2}\.\d{2}\.\d{4}\s*:\s*(?:</span>\s*)?"
                      r"<span[^>]*>(.*?)</span>", zeile, re.S)
        if not t:
            t = re.search(r"\d{2}\.\d{2}\.\d{4}\s*:\s*(.*?)</span>", zeile, re.S)
        titel = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t.group(1))).strip() if t else ""

        treffer.append((d, titel, url, pdf))

    gesehen, sauber = set(), []
    for e in treffer:
        if e[2] not in gesehen:
            gesehen.add(e[2])
            sauber.append(e)
    return sauber


def verzeichnis(bis=date(2013, 10, 1)):
    alle, offset = [], 0
    while True:
        r = hole(LISTE, limit=SEITE, noFilterSet="true", offset=offset)
        seite = eintraege(r.text)
        if not seite:
            log.info("   offset %d: leer, Ende", offset)
            break
        alle += seite
        aeltest = min(d for d, _, _, _ in seite)
        log.info("   offset %-5d %2d Eintraege, bis %s  (gesamt %d)",
                 offset, len(seite), aeltest, len(alle))
        if aeltest < bis:
            break
        offset += SEITE
        time.sleep(PAUSE)

    gesehen, sauber = set(), []
    for e in alle:
        if e[2] not in gesehen:
            gesehen.add(e[2])
            sauber.append(e)
    return sorted(sauber)


def bericht(eintr):
    log.info("--- Namentliche Abstimmungen je Wahlperiode ---")
    aw = {18: 121, 19: 176, 20: 162}
    for wp, von, bis in WAHLPERIODEN:
        n = [e for e in eintr if von <= e[0] <= bis]
        log.info("   WP %d  %s bis %s:  %3d Abstimmungen   " "(abgeordnetenwatch: %d, Differenz %+d)",
                 wp, von, bis, len(n), aw[wp], len(n) - aw[wp])
    frueh = [e for e in eintr if e[0] < WAHLPERIODEN[0][1]]
    spaet = [e for e in eintr if e[0] > WAHLPERIODEN[-1][2]]
    log.info("   ausserhalb: %d vor 2013, %d nach dem 24.03.2025",
             len(frueh), len(spaet))
    log.info("   Verzeichnis gesamt: %d Eintraege, %s bis %s",
             len(eintr), eintr[0][0], eintr[-1][0])


def speichere_verzeichnis(eintr):
    ZIEL.mkdir(parents=True, exist_ok=True)
    ablage = ZIEL / "verzeichnis.json"
    ablage.write_text(json.dumps(
        [{"datum": d.isoformat(), "titel": ti, "url": u, "pdf": pdf}
         for d, ti, u, pdf in eintr],
        ensure_ascii=False, indent=1), encoding="utf-8")
    ohne = sum(1 for e in eintr if not e[3])
    log.info("   Verzeichnis geschrieben: %s  (%d Eintraege, davon %d ohne PDF)",
             ablage, len(eintr), ohne)


def lade_dateien(eintr):
    ZIEL.mkdir(parents=True, exist_ok=True)
    protokoll = ZIEL / "abruf.json"
    schon = json.loads(protokoll.read_text(encoding="utf-8")) if protokoll.exists() else {}

    im_zeitraum = [e for e in eintr
                   if any(von <= e[0] <= bis for _, von, bis in WAHLPERIODEN)]
    log.info("--- %d Dateien fuer die Wahlperioden 18 bis 20 ---", len(im_zeitraum))

    neu_xlsx = neu_pdf = 0
    for i, (d, titel, url, pdf) in enumerate(im_zeitraum, 1):
        geholt = False
        name = f"{d.isoformat()}_{url.rsplit('/', 1)[-1]}"
        ziel = ZIEL / name
        eintrag = schon.get(url)
        if eintrag is None or not ziel.exists():
            r = hole(url)
            ziel.write_bytes(r.content)
            eintrag = {
                "datei": name, "datum": d.isoformat(), "titel": titel,
                "sha256": hashlib.sha256(r.content).hexdigest(),
                "bytes": len(r.content),
                "abgerufen_am": datetime.now().isoformat(timespec="seconds"),
            }
            schon[url] = eintrag
            neu_xlsx += 1
            geholt = True
            time.sleep(PAUSE)


        pziel = ZIEL / f"{d.isoformat()}_{pdf.rsplit('/', 1)[-1]}" if pdf else None
        if pdf and not pziel.exists():
            rp = hole(pdf)
            pziel.write_bytes(rp.content)
            eintrag["pdf_sha256"] = hashlib.sha256(rp.content).hexdigest()
            eintrag["pdf_bytes"] = len(rp.content)
            eintrag["pdf_abgerufen_am"] = datetime.now().isoformat(timespec="seconds")
            neu_pdf += 1
            geholt = True
            time.sleep(PAUSE)
        if pdf:
            eintrag["pdf_datei"] = pziel.name
            eintrag["pdf_url"] = pdf

        if geholt and (neu_xlsx + neu_pdf) % 25 == 0:
            log.info("   %d/%d durch, %d XLSX und %d PDF neu",
                     i, len(im_zeitraum), neu_xlsx, neu_pdf)
            protokoll.write_text(json.dumps(schon, ensure_ascii=False, indent=1),
                                 encoding="utf-8")

    protokoll.write_text(json.dumps(schon, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    ohne_pdf = [e["datei"] for e in schon.values() if not e.get("pdf_datei")]
    if ohne_pdf:
        log.warning("   %d Abstimmungen ohne PDF - Drucksachennummer und " "amtliches Ergebnis fehlen dort:", len(ohne_pdf))
        for n in ohne_pdf[:20]:
            log.warning("      %s", n)
    log.info("   %d XLSX und %d PDF neu geladen, %d Abstimmungen im Archiv",
             neu_xlsx, neu_pdf, len(schon))


def main():
    was = sys.argv[1] if len(sys.argv) > 1 else "liste"
    log.info("Verzeichnis wird ausgelesen ...")
    eintr = verzeichnis()
    speichere_verzeichnis(eintr)
    bericht(eintr)
    if was == "dateien":
        lade_dateien(eintr)
    else:
        log.info("Nur das Verzeichnis. Fuer die XLSX: " "python hole_namentliche_abstimmungen.py dateien")


if __name__ == "__main__":
    main()
