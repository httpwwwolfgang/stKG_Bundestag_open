import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from korrekturen import (KENNUNG_KORREKTUR, INTERNE_KENNUNG, OHNE_SPRECHER,
                         korrigierte_kennung)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUELLE = (Path(__file__).resolve().parents[4] / "Daten" / "Parlamentsarbeit"
          / "CPP-BT_2026-01-17_DE_PQT_Reden_Gesamt.parquet")
import zwischenstand


LIEFERUNG = "cpp_bt_fobbe"
ZIEL = zwischenstand.fuer(__file__)
STEMPEL = f"{datetime.now():%Y%m%d_%H%M%S}"
WAHLPERIODEN = (18, 19, 20)


UEBERNAHME = [
    ("rede_id", "rede_id"),
    ("redner_id", "redner_id"),
    ("redner_fraktion", "fraktion"),
    ("redner_rolle_kurz", "rolle_kurz"),
    ("redner_rolle_lang", "rolle_lang"),
    ("wahlperiode", "wahlperiode"),
    ("sitzung_nr", "sitzung_nr"),
    ("sitzung_datum", "sitzung_datum"),
    ("sitzung_jahr", "sitzung_jahr"),
    ("protokoll_nr", "protokoll_nr"),
    ("protokoll_seite", "protokoll_seite"),
    ("doc_id", "doc_id"),
    ("zeichen", "zeichen"),
    ("tokens", "tokens"),
    ("typen", "typen"),
    ("saetze", "saetze"),
    ("rede_text", "text"),
]


def main():
    print(f"CPP-BT lesen: {QUELLE.name}")
    d = pd.read_parquet(QUELLE, columns=[
        q for q, _ in UEBERNAHME] + ["rede_kommentare", "rede_zitate"])
    d = d[d.wahlperiode.isin(WAHLPERIODEN)].copy()
    print(f"  {len(d):,} Reden der Wahlperioden "
          f"{', '.join(str(w) for w in WAHLPERIODEN)}")


    def zaehle(spalte):
        return (d[spalte].fillna("").astype(str)
                .map(lambda s: len([x for x in s.split("|") if x.strip()])))

    d["kommentare_anzahl"] = zaehle("rede_kommentare")
    d["zitate_anzahl"] = zaehle("rede_zitate")

    reden = d[[q for q, _ in UEBERNAHME]].rename(
        columns=dict(UEBERNAHME))
    reden["kommentare_anzahl"] = d.kommentare_anzahl.values
    reden["zitate_anzahl"] = d.zitate_anzahl.values
    reden["redner_id"] = reden.redner_id.astype(str).str.strip()


    vorher = reden.redner_id.copy()
    reden["redner_id"] = [korrigierte_kennung(r, k)
                          for r, k in zip(reden.rede_id, reden.redner_id)]
    geaendert = int((vorher != reden.redner_id).sum())
    print(f"  Kennung korrigiert bei {geaendert} Reden "
          f"({len(KENNUNG_KORREKTUR)} umgehaengt, {len(INTERNE_KENNUNG)} auf "
          f"eine eigene Kennung, {len(OHNE_SPRECHER)} auf UNBEKANNT)")


    print(f"\n{'=' * 68}")
    print(f"{len(reden):,} Reden, {len(reden.columns)} Spalten\n")
    for wp in sorted(reden.wahlperiode.unique()):
        teil = reden[reden.wahlperiode == wp]
        print(f"  WP {wp}: {len(teil):>7,} Reden, "
              f"{teil.protokoll_nr.nunique():>3} Protokolle, "
              f"{teil.redner_id.nunique():>4} Sprecher-Kennungen, "
              f"{teil.text.str.len().sum() / 1e6:>6.1f} Mio Zeichen Text")

    print(f"\n  Zeitraum: {reden.sitzung_datum.min()} bis "
          f"{reden.sitzung_datum.max()}")
    print(f"  Text gesamt: {reden.text.str.len().sum():,} Zeichen")
    print(f"  Kommentare:  {int(reden.kommentare_anzahl.sum()):,} "
          f"(in {int((reden.kommentare_anzahl > 0).sum()):,} Reden)")
    print(f"  Zitate:      {int(reden.zitate_anzahl.sum()):,} "
          f"(in {int((reden.zitate_anzahl > 0).sum()):,} Reden)")

    leer = int((reden.text.fillna("").str.strip() == "").sum())
    print(f"  Reden ohne Text: {leer:,}")

    ohne_kennung = int((reden.redner_id.isin(["", "None", "nan"])).sum())
    print(f"  Reden ohne Sprecher-Kennung: {ohne_kennung}")

    print(f"\n  Fraktion gesetzt bei {int((reden.fraktion.fillna('') != '').sum()):,} "
          f"Reden, Rolle bei "
          f"{int((reden.rolle_lang.fillna('') != '').sum()):,}")


    ZIEL.mkdir(parents=True, exist_ok=True)
    pfad = ZIEL / f"rede_{STEMPEL}.parquet"
    reden.to_parquet(pfad, index=False, compression="zstd")
    print(f"\n{len(reden):,} Zeilen -> {pfad} "
          f"({pfad.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
