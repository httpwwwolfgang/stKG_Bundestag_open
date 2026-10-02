import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "lib"))
sys.path.insert(0, str(_REPO / "03_load_db" / "meta"))

from db import run_sql

_liste = None


def _eintraege():
    global _liste
    if _liste is None:
        from load_datenlieferung import LIEFERUNGEN
        _liste = {e["lieferung_id"]: e for e in LIEFERUNGEN}
    return _liste


def _text(wert):
    if wert is None or wert == "":
        return "NULL"
    return "'" + str(wert).replace("'", "''") + "'"


def merke(kennung, schema="meta"):
    alle = _eintraege()
    if kennung not in alle:
        raise SystemExit(
            f"Unbekannte Lieferung: {kennung}\n"
            f"Sie steht nicht in 03_load_db/meta/load_datenlieferung.py.")
    e = alle[kennung]

    gebietsstand = (f"DATE '{e['gebietsstand']}'"
                    if e.get("gebietsstand") else "NULL")
    wahljahr = str(e["wahljahr"]) if e.get("wahljahr") else "NULL"

    run_sql(f"""
    INSERT INTO {schema}.datenlieferung
        (lieferung_id, bezeichnung, herausgeber, datei, gebietsstand,
         lizenz, wahljahr, art)
    VALUES ({_text(kennung)},
            {_text(e.get('bezeichnung'))},
            {_text(e.get('herausgeber'))},
            {_text(e.get('datei'))},
            {gebietsstand},
            {_text(e.get('lizenz'))},
            {wahljahr},
            {_text(e.get('art'))})
    ON CONFLICT (lieferung_id) DO UPDATE SET
        bezeichnung  = EXCLUDED.bezeichnung,
        herausgeber  = EXCLUDED.herausgeber,
        datei        = EXCLUDED.datei,
        gebietsstand = EXCLUDED.gebietsstand,
        lizenz       = EXCLUDED.lizenz,
        wahljahr     = EXCLUDED.wahljahr,
        art          = EXCLUDED.art;
    """, f"lieferung {kennung}")
