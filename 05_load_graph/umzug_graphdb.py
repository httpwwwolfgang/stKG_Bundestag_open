import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ALT = Path(os.environ["APPDATA"]) / "GraphDB"
ERLAUBT = Path("PFAD_ZU_DATEN")
NEU = ERLAUBT / "graphdb_data"


ROBOCOPY = ["/E", "/COPY:DAT", "/DCOPY:DAT", "/MT:8",
            "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/NJH"]


def in_erlaubtem_bereich(pfad):
    try:
        pfad.resolve().relative_to(ERLAUBT.resolve())
        return True
    except ValueError:
        return False


def graphdb_laeuft():
    gruende = []

    namen = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False).stdout.lower()
    for muster in ("graphdb",):
        if muster in namen:
            gruende.append(f"Prozess mit '{muster}' im Namen laeuft")

    import socket
    with socket.socket() as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", 7200)) == 0:
            gruende.append("Port 7200 antwortet")

    return gruende


def bilanz(ordner):
    anzahl, summe = 0, 0
    for p in ordner.rglob("*"):
        if p.is_file():
            anzahl += 1
            summe += p.stat().st_size
    return anzahl, summe


def gb(bytes_):
    return f"{bytes_ / 1024**3:.2f} GB"


def platz_auf(laufwerk):
    return shutil.disk_usage(laufwerk).free


def kopiere(quelle, ziel):
    ergebnis = subprocess.run(
        ["robocopy", str(quelle), str(ziel), *ROBOCOPY],
        capture_output=True, text=True, check=False)
    if ergebnis.returncode >= 8:
        raise SystemExit(
            f"\nFEHLER beim Kopieren (robocopy {ergebnis.returncode}):\n"
            f"{ergebnis.stdout[-2000:]}")
    return ergebnis.returncode


def schreibe_properties():
    conf = NEU / "conf"
    conf.mkdir(parents=True, exist_ok=True)
    datei = conf / "graphdb.properties"

    if datei.exists():
        print(f"    graphdb.properties gibt es schon -- unveraendert "
              f"gelassen: {datei}")
        return


    ort = str(NEU / "data").replace("\\", "\\\\")
    datei.write_text(
        "# Datenverzeichnis von GraphDB -- verlegt am 26.09.2026 von\n" "# %APPDATA%\\GraphDB nach D:, weil auf C: nur noch 33 GB frei\n" "# waren und das Repository davon 13,92 GB belegt.\n" "#\n" "# Angelegt von 03_load_db/graph/umzug_graphdb.py.\n"
        f"graphdb.home.data = {ort}\n",
        encoding="utf-8")
    print(f"    angelegt: {datei}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pruefen", action="store_true",
                   help="nur zeigen, was geschehen wuerde")
    p.add_argument("--ja", action="store_true",
                   help="kopieren, ohne zu fragen")
    a = p.parse_args()

    print(f"\n  von  {ALT}")
    print(f"  nach {NEU}\n")

    if not ALT.is_dir():
        raise SystemExit(f"Alten Ordner gibt es nicht: {ALT}")

    if not in_erlaubtem_bereich(NEU):
        raise SystemExit(
            f"Ziel liegt ausserhalb von {ERLAUBT}: {NEU}\n" "Auf D: wird allein unterhalb von Masterarbeit geschrieben.")

    if not ERLAUBT.is_dir():
        raise SystemExit(
            f"Gibt es nicht: {ERLAUBT}\nPlatte angeschlossen?")

    laeuft = graphdb_laeuft()
    if laeuft:
        raise SystemExit(
            "GraphDB laeuft:\n    " + "\n    ".join(laeuft) + "\n\n" "Erst beenden. Wird waehrend des Kopierens geschrieben,\n" "entsteht ein Abbild aus zwei Zeitpunkten -- und dem sieht\n" "man nichts an.")
    print("  GraphDB laeuft nicht: kein Prozess, Port 7200 stumm.")

    anzahl, summe = bilanz(ALT)
    frei = platz_auf(NEU.drive + "\\")
    print(f"  zu kopieren  {anzahl:,} Dateien, {gb(summe)}"
          .replace(",", "."))
    print(f"  frei auf {NEU.drive}    {gb(frei)}")

    if frei < summe * 1.1:
        raise SystemExit(
            f"\nZu wenig Platz auf {NEU.drive}: {gb(frei)} frei fuer "
            f"{gb(summe)}.")

    if NEU.exists() and any(NEU.iterdir()):
        print(f"\n  ACHTUNG: {NEU} ist nicht leer. robocopy ergaenzt "
              f"und ueberschreibt darin.")

    if a.pruefen:
        print("\n  --pruefen: nichts getan.\n")
        return

    if not a.ja:
        antwort = input("\n  Kopieren? [tippen: ja] ")
        if antwort.strip().lower() != "ja":
            raise SystemExit("  Abgebrochen.")

    print("\n  kopiere ...")
    kopiere(ALT, NEU)

    neu_anzahl, neu_summe = bilanz(NEU)
    print(f"  angekommen   {neu_anzahl:,} Dateien, {gb(neu_summe)}"
          .replace(",", "."))

    if neu_anzahl != anzahl or neu_summe != summe:
        raise SystemExit(
            f"\nNICHT VOLLSTAENDIG: {neu_anzahl:,} von {anzahl:,} "
            f"Dateien, {gb(neu_summe)} von {gb(summe)}.\n" "Der alte Ordner steht unveraendert -- nichts ist verloren."
            .replace(",", "."))
    print("  vollstaendig: Dateizahl und Groesse stimmen ueberein.")

    schreibe_properties()

    print(f"""
  KOPIERT. Der alte Ordner steht noch:
      {ALT}

  WAS JETZT VON HAND ZU TUN IST

  1. GraphDB Desktop starten, Settings oeffnen und unter
     "Custom Java properties" eintragen:

         property name    graphdb.home
         property value   {NEU}

     Auf "Set", dann "Save and restart". Es gibt dafuer keine Datei --
     der Ort ist in der Anwendung eingebaut, deshalb haendisch.

     Nicht verwechseln mit "Open dist directory": Das zeigt auf die
     Programmdateien und bleibt richtigerweise auf C:.

  2. In der Workbench nachsehen, ob das Repository skg_bundestag
     dieselbe Zahl Statements haelt wie vorher. Erst dann ist der
     Umzug abgenommen.

  3. Wenn ja: den alten Ordner loeschen und damit 13,92 GB auf C:
     freigeben. Vorher NICHT
     Skript.
""")


if __name__ == "__main__":
    main()
