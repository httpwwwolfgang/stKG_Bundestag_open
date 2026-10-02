import os
from pathlib import Path

WURZEL = Path(os.environ.get("SKG_EXPORT", "PFAD_ZU_TRIPELDATEIEN"))

ZEIT           = WURZEL / "01_zeit"
METADATEN      = WURZEL / "02_metadaten"
RAUM           = WURZEL / "03_raum"
BEOBACHTUNGEN  = WURZEL / "04_beobachtungen"
PERSONEN       = WURZEL / "05_personen"
ORGANISATIONEN = WURZEL / "06_organisationen"
FUNKTIONEN     = WURZEL / "07_funktionen"
PARLAMENT      = WURZEL / "08_parlament"

ALLE = [ZEIT, METADATEN, RAUM, BEOBACHTUNGEN,
        PERSONEN, ORGANISATIONEN, FUNKTIONEN, PARLAMENT]


def pruefe(*ordner):
    if not WURZEL.is_dir():
        raise SystemExit(
            f"Exportwurzel gibt es nicht: {WURZEL}\n" "Platte angeschlossen? Anderer Ort: SKG_EXPORT setzen.")
    for o in (ordner or ALLE):
        o.mkdir(parents=True, exist_ok=True)
