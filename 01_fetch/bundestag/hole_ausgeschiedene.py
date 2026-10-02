import hashlib
import json
import logging
import time
from datetime import date
from pathlib import Path

import requests


ZIEL = (Path(__file__).resolve().parents[4] / "Daten" / "politiker_innen"
        / "bundestag_ausgeschiedene")

BASIS = "https://www.bundestag.de"


SEITEN = {
    "wp18": ("/webarchiv/abgeordnete/biografien18/ausgeschiedene", 18),
    "wp19": ("/webarchiv/ausgeschiedene-abgeordnete-532298", 19),
    "wp20": ("/webarchiv/ausgeschiedene-abgeordnete-inhalt-874188", 20),
    "wiederholungswahl_berlin":
        ("/abgeordnete/wiederholungswahl-inhalt-989560", None),
}

KOPF = {"User-Agent": "sKG-bundestag Masterarbeit (Forschung, einmaliger Abruf)"}
PAUSE_SEKUNDEN = 1.0

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ausgeschiedene")


def lies_manifest(pfad):
    if pfad.exists():
        return json.loads(pfad.read_text(encoding="utf-8"))
    return {}


def main():
    ZIEL.mkdir(parents=True, exist_ok=True)
    manifest_pfad = ZIEL / "abruf.json"
    manifest = lies_manifest(manifest_pfad)

    heute = date.today().isoformat()
    neu = 0
    for i, (schluessel, (pfad, wp)) in enumerate(SEITEN.items()):
        datei = ZIEL / f"{schluessel}.html"
        if datei.exists():
            log.info("%s liegt bereits vor - kein Request", datei.name)
            continue

        if neu and PAUSE_SEKUNDEN:
            time.sleep(PAUSE_SEKUNDEN)

        url = BASIS + pfad
        log.info("Hole %s", url)
        antwort = requests.get(url, headers=KOPF, timeout=30)
        antwort.raise_for_status()
        inhalt = antwort.content
        datei.write_bytes(inhalt)
        neu += 1

        manifest[schluessel] = {
            "url": url,
            "wahlperiode": wp,
            "datei": datei.name,
            "abgerufen_am": heute,
            "bytes": len(inhalt),
            "sha256": hashlib.sha256(inhalt).hexdigest(),
            "http_status": antwort.status_code,
        }
        log.info("   %d Bytes, sha256 %s", len(inhalt),
                 manifest[schluessel]["sha256"][:16])

    manifest_pfad.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Manifest: %s (%d Eintraege, %d neu geholt)",
             manifest_pfad, len(manifest), neu)


if __name__ == "__main__":
    main()
