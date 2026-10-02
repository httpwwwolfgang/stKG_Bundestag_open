import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade


DIST = Path(os.environ["LOCALAPPDATA"]) / "GraphDB Desktop" / "app"
IMPORTRDF = DIST / "bin" / "importrdf.cmd"


JAVA = Path(os.environ["LOCALAPPDATA"]) / "GraphDB Desktop" / "runtime" / "bin" / "java.exe"
HAUPTKLASSE = "com.ontotext.graphdb.importrdf.ImportRDF"


HOME = Path("PFAD_ZU_GRAPHDB_DATEN")


ERLAUBT = Path("PFAD_ZU_DATEN")
BLOCKORDNER = ERLAUBT / "graphdb_preload_temp"


ZEITEN = pfade.WURZEL / "ladezeiten.txt"


ORDNER = [pfade.ZEIT, pfade.RAUM, pfade.BEOBACHTUNGEN, pfade.PERSONEN,
          pfade.ORGANISATIONEN, pfade.FUNKTIONEN, pfade.PARLAMENT]

ENDUNGEN = {".trig", ".ttl", ".nq", ".nt"}


def in_erlaubtem_bereich(pfad):
    try:
        pfad.resolve().relative_to(ERLAUBT.resolve())
        return True
    except ValueError:
        return False


def graphdb_laeuft():
    gruende = []
    with socket.socket() as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", 7200)) == 0:
            gruende.append("Port 7200 antwortet")
    namen = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True,
                           check=False).stdout.lower()
    if "graphdb" in namen:
        gruende.append("ein Prozess mit 'graphdb' im Namen laeuft")
    return gruende


def dateien():
    gefunden = []
    for ordner in ORDNER:
        if ordner.is_dir():
            gefunden += sorted(p for p in ordner.glob("*")
                               if p.suffix in ENDUNGEN and p.is_file())
    return gefunden


def tripel_in_datei(pfad):
    n = 0
    with pfad.open(encoding="utf-8") as fh:
        for zeile in fh:
            s = zeile.strip()
            if s and s[-1] in ";." and not s.startswith(("@", "#")):
                n += 1
    return n


def dauer(sekunden):
    st, rest = divmod(int(sekunden), 3600)
    mi, se = divmod(rest, 60)
    return f"{st}h {mi:02d}m {se:02d}s" if st else f"{mi}m {se:02d}s"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True,
                   help="Ziel-Repository. Wird VOLLSTAENDIG ersetzt.")
    p.add_argument("--pruefen", action="store_true",
                   help="nur zeigen, was geschehen wuerde")
    p.add_argument("--ja", action="store_true",
                   help="ohne Rueckfrage ausfuehren")
    p.add_argument("--parsing-tasks", type=int, default=None,
                   dest="parsing_tasks",
                   help="Zahl der parallelen Parser (-t). Vorgabe: was " "importrdf selbst waehlt.")
    p.add_argument("--zaehlen", action="store_true",
                   help="vorher die Tripel in allen Dateien zaehlen, um " "eine Sollzahl zum Vergleichen zu haben. Liest " "den GESAMTEN Bestand zeilenweise durch und " "dauert bei 16 GB entsprechend -- ohne die " "Option zeigt die Workbench die Zahl nach dem " "Lauf ohnehin.")
    a = p.parse_args()

    for was, pfad in (("importrdf", IMPORTRDF), ("Java-Laufzeit", JAVA),
                      ("lib-Ordner", DIST / "lib")):
        if not pfad.exists():
            raise SystemExit(f"{was} nicht gefunden: {pfad}\n" "GraphDB Desktop woanders installiert?")


    ziel = HOME / "data" / "repositories" / a.repo
    if not (ziel / "config.ttl").is_file():
        vorhanden = sorted(p.name for p in (HOME / "data" / "repositories").glob("*")
                           if (p / "config.ttl").is_file())
        raise SystemExit(
            f"Repository '{a.repo}' gibt es nicht unter {HOME}.\n"
            f"Dort liegen: {', '.join(vorhanden) or '(keines)'}\n" "Anlegen geschieht in der Workbench, nicht hier: Dabei wird " "ueber\nRegelsatz und Indizes entschieden.")

    pfade.pruefe()
    liste = dateien()
    if not liste:
        raise SystemExit(f"Keine Exportdateien unter {pfade.WURZEL}")

    gesamt = sum(d.stat().st_size for d in liste)
    print(f"\n  Ziel          {a.repo}  (wird VOLLSTAENDIG ersetzt)")
    print(f"  Dateien       {len(liste)} in {len(ORDNER)} Modulordnern")
    print(f"  Groesse       {gesamt/1024**3:.2f} GB")
    print(f"  Bloecke       {BLOCKORDNER}")

    if not in_erlaubtem_bereich(BLOCKORDNER):
        raise SystemExit(
            f"Blockordner liegt ausserhalb von {ERLAUBT}: {BLOCKORDNER}\n" "Auf D: wird allein unterhalb von Masterarbeit geschrieben.")
    if not ERLAUBT.is_dir():
        raise SystemExit(f"Gibt es nicht: {ERLAUBT}\nPlatte angeschlossen?")


    frei = shutil.disk_usage(str(ERLAUBT)).free
    print(f"  frei auf D:   {frei/1024**3:.1f} GB "
          f"(gebraucht: rund {gesamt*2/1024**3:.0f} GB)")
    if frei < gesamt * 2.5:
        raise SystemExit(
            f"\nZu wenig Platz: {frei/1024**3:.1f} GB frei, preload "
            f"braucht rund {gesamt*2/1024**3:.0f} GB Zwischenablage.")

    laeuft = graphdb_laeuft()
    if laeuft:
        raise SystemExit(
            "\nGraphDB laeuft:\n    " + "\n    ".join(laeuft) + "\n\n" "importrdf kann nicht gegen einen laufenden Server arbeiten.\n" "Erst die Desktop-Anwendung beenden. Ein Lauf waehrend des\n" "Betriebs beschaedigt das Repository.")
    print("  GraphDB       laeuft nicht -- Port 7200 stumm")

    if a.zaehlen:
        print("  zaehle Tripel in allen Dateien ...", flush=True)
        soll = sum(tripel_in_datei(d) for d in liste)
        print(f"  erwartet      rund {soll:,} Tripel".replace(",", "."))
    else:
        soll = None
        print("  erwartet      nicht gezaehlt (--zaehlen dafuer)")

    befehl = [str(JAVA),
              f"-Dgraphdb.dist={DIST}",
              f"-Dgraphdb.home={HOME}",
              "-Dfile.encoding=UTF-8",
              "-cp", f"{DIST / 'lib'}\\*",
              HAUPTKLASSE,
              "preload", "-f", "-i", a.repo,
              "-q", str(BLOCKORDNER)]
    if a.parsing_tasks:
        befehl += ["-t", str(a.parsing_tasks)]
    befehl += [str(o) for o in ORDNER if o.is_dir()]

    print(f"\n  Aufruf:\n    {' '.join(befehl)}\n")

    if a.pruefen:
        print("  --pruefen: nichts getan.\n")
        return


    if not a.repo.lower().endswith("_bulk"):
        print(f"  ACHTUNG: '{a.repo}' sieht nicht nach einem Testziel aus.")
        print("  preload ersetzt das Repository VOLLSTAENDIG, und ein " "Abbruch")
        print("  laesst es unbrauchbar zurueck.")
        if input(f"  Wirklich {a.repo} ersetzen? [tippen: ersetzen] "
                 ).strip().lower() != "ersetzen":
            raise SystemExit("  Abgebrochen.")
    elif not a.ja:
        if input("  Laden? [tippen: ja] ").strip().lower() != "ja":
            raise SystemExit("  Abgebrochen.")

    BLOCKORDNER.mkdir(parents=True, exist_ok=True)

    print(f"\n  laeuft seit {datetime.now():%H:%M:%S} ...\n")
    begonnen = time.monotonic()
    ergebnis = subprocess.run(befehl, check=False)
    gebraucht = time.monotonic() - begonnen

    if ergebnis.returncode != 0:
        raise SystemExit(
            f"\nimportrdf endete mit Rueckgabewert "
            f"{ergebnis.returncode} nach {dauer(gebraucht)}.\n"
            f"Das Repository '{a.repo}' ist jetzt moeglicherweise "
            f"unbrauchbar.\nDie Bloecke stehen noch in {BLOCKORDNER} -- "
            f"sie werden NICHT\nweggeraeumt, solange unklar ist, was "
            f"geschehen ist.")


    if BLOCKORDNER.exists():
        shutil.rmtree(BLOCKORDNER, ignore_errors=True)

    zeile = (f"{datetime.now():%Y-%m-%d %H:%M}  preload  {a.repo:<24} "
             f"{len(liste):>3} Dateien  {gesamt/1024**3:>6.2f} GB  "
             f"{dauer(gebraucht)}\n")
    with ZEITEN.open("a", encoding="utf-8") as fh:
        fh.write(zeile)

    erwartung = (f"rund {soll:,} Tripel haelt" if soll is not None
                 else "plausibel viele Tripel haelt")
    print(f"""
  DURCH in {dauer(gebraucht)}.
  Zeit fortgeschrieben nach {ZEITEN}

  WAS JETZT NOCH FEHLT

  1. GraphDB starten und nachsehen, ob '{a.repo}' {erwartung}.
     Erst das zeigt, ob alles angekommen ist
     es nicht.

  2. Metadaten und Eingriffe nachziehen. Sie liegen in denselben
     Named Graphs wie die Sachdaten und kommen nur ueber SPARQL Update
     hinein, also bei LAUFENDEM Server:

         python lade_in_graphdb.py --repo {a.repo} --metadaten --eingriffe

     Ohne diesen Schritt haengt kein Tripel an einer Herkunft, und das
     faellt beim Abfragen nicht auf.
""".replace(",", "."))


if __name__ == "__main__":
    main()
