import os
from pathlib import Path

WURZEL = Path(os.environ.get(
    "SKG_ZWISCHEN",
    "PFAD_ZU_ZWISCHENSTAENDEN"))


def ordner(*teile):
    if not WURZEL.is_dir():
        raise SystemExit(
            f"Ablage der Zwischenstaende gibt es nicht: {WURZEL}\n" "Anderer Ort: SKG_ZWISCHEN setzen.")
    z = WURZEL / "_".join(teile)
    z.mkdir(parents=True, exist_ok=True)
    return z


def fuer(datei, name="export"):
    REPO = Path(__file__).resolve().parents[1]
    p = Path(datei).resolve()
    try:
        teile = p.relative_to(REPO).parts[:-1]
    except ValueError:
        raise SystemExit(f"Datei liegt ausserhalb des Repositoriums: {p}")
    return ordner(*teile, name)
