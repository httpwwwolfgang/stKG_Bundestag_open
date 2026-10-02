from datetime import datetime
from pathlib import Path

import hole_parlamentsdokumente as dip

WAHLPERIODEN = (18, 19, 20)
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand
AUSGABE = zwischenstand.fuer(__file__) / f"vorgangspositionen_{datetime.now():%Y%m%d_%H%M%S}"


def main():
    dip.MAX_SEITEN = 0
    dip.AUSGABE = AUSGABE
    dip.WAHLPERIODEN = {wp: ("", "") for wp in WAHLPERIODEN}

    bericht = []
    for wp in WAHLPERIODEN:
        print(f"\n########## Wahlperiode {wp} ##########")


        ohne_filter = dip.api_get("/vorgangsposition", {"f.wahlperiode": wp})
        n_ohne = (ohne_filter or {}).get("numFound")

        roh, n_mit = dip.hole_alle(
            "/vorgangsposition",
            dip.basis_params(wp, **{"f.zuordnung": "BT"}),
            "vorgangsposition")

        vp, urheber = dip.zeilen_vorgangsposition(roh, wp)
        dip.schreibe(f"vorgangsposition_wp{wp}", vp)
        dip.schreibe(f"vorgangsposition_urheber_wp{wp}", urheber)

        mit_abstract = sum(1 for z in vp if z["abstract"])
        mit_seite = sum(1 for z in vp if z["anfangsseite"] != "")
        arten = {}
        for z in vp:
            arten[z["dokumentart"]] = arten.get(z["dokumentart"], 0) + 1
        pp = [z for z in vp if z["dokumentart"] == "Plenarprotokoll"]
        pp_seite = sum(1 for z in pp if z["anfangsseite"] != "")

        print(f"  numFound mit f.zuordnung=BT : {n_mit}")
        print(f"  numFound ohne den Filter    : {n_ohne}")
        print(f"  geholt                      : {len(vp)}")
        print(f"  mit Inhaltsangabe (abstract): {mit_abstract}")
        print(f"  mit Anfangsseite            : {mit_seite}")
        print(f"  Dokumentarten               : {arten}")
        print(f"  Plenarprotokoll-Positionen  : {len(pp)}, "
              f"davon mit Seite: {pp_seite}")
        bericht.append((wp, n_mit, n_ohne, len(vp), mit_abstract, mit_seite,
                        len(pp), pp_seite))

    print("\n----- Bericht -----")
    print(f"{'WP':>4} {'BT':>8} {'ohne Filter':>12} {'geholt':>8} "
          f"{'Abstract':>9} {'m. Seite':>9} {'Protokoll':>10} {'dav. Seite':>11}")
    for z in bericht:
        print(f"{z[0]:>4} {z[1]:>8} {z[2]:>12} {z[3]:>8} {z[4]:>9} "
              f"{z[5]:>9} {z[6]:>10} {z[7]:>11}")
    print(f"\nAusgabe in: {AUSGABE.resolve()}")


if __name__ == "__main__":
    main()
