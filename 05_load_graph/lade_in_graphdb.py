import argparse
import atexit
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import pfade

HIER      = Path(__file__).resolve().parent
BASIS     = "https://skg-bundestag.de/"


SCHEMA    = HIER.parents[0] / "schema" / "stkg-schema.ttl"
SCHEMAGRAPH = f"{BASIS}schema"


ORDNER = [pfade.ZEIT, pfade.RAUM, pfade.BEOBACHTUNGEN, pfade.PERSONEN,
          pfade.ORGANISATIONEN, pfade.FUNKTIONEN, pfade.PARLAMENT]


METADATEN_TRIG   = pfade.METADATEN / "datenlieferung.trig"
METADATEN_UPDATE = pfade.METADATEN / "datenlieferung_update.ru"


EINGRIFF_UPDATE = pfade.METADATEN / "eingriff_update.ru"

TYPEN = {".trig": "application/trig", ".ttl": "text/turtle",
         ".nq": "application/n-quads", ".nt": "application/n-triples"}


SPERRE = pfade.WURZEL / ".ladelauf_laeuft.json"


def sperre_pruefen(brechen):
    if not SPERRE.exists():
        return
    try:
        alt = json.loads(SPERRE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        alt = {}
    seit = alt.get("beginn", "unbekannt")
    pid = alt.get("pid", "unbekannt")
    wen = ", ".join(alt.get("lieferungen", [])) or "unbekannt"
    if brechen:
        print(f"  Sperre von {seit} (PID {pid}) wird auf Ansage "
              f"uebergangen.")
        return
    raise SystemExit(
        f"Es laeuft bereits ein Ladelauf.\n"
        f"    seit         {seit}\n"
        f"    Prozess      {pid}\n"
        f"    Lieferungen  {wen}\n"
        f"    Sperrdatei   {SPERRE}\n\n"
        f"Zwei Laeufe leeren einander die Lieferungen. Warten, bis der "
        f"andere durch ist.\nIst er abgestuerzt und die Sperre "
        f"liegengeblieben: mit --sperre-brechen starten.")


def sperre_setzen(lieferungen):
    SPERRE.write_text(json.dumps({
        "beginn": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "pid": os.getpid(),
        "lieferungen": sorted(lieferungen),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def sperre_loesen():
    try:
        SPERRE.unlink()
    except OSError:
        pass


def lieferung_von(pfad):
    stem = re.sub(r"_mod\d{2}(_\d{2})?$", r"\1", pfad.stem)
    return re.sub(r"_\d{2}$", "", stem)


def dateien():
    gefunden = []
    for ordner in ORDNER:
        if ordner.is_dir():
            gefunden += sorted(p for p in ordner.glob("*")
                               if p.suffix in TYPEN and p.is_file())
    return gefunden


def endpunkt(url, repo):
    return f"{url.rstrip('/')}/repositories/{repo}"


def leere_graph(url, repo, graph):
    try:
        antwort = requests.post(
            f"{endpunkt(url, repo)}/statements",
            data={"update": f"DROP SILENT GRAPH <{graph}>"},
            timeout=7200)
        antwort.raise_for_status()
    except requests.exceptions.Timeout:


        raise SystemExit(
            f"\nZEITRAHMEN UEBERSCHRITTEN beim Leeren von <{graph}>.\n" "Der Server loescht moeglicherweise WEITER. Nicht sofort\n" "nachmessen und nicht weiterladen: Warten, bis GraphDB ruhig\n" "ist (Workbench -> Monitor -> Queries), dann den Stand pruefen\n" "und neu entscheiden.\n" "Am 08.09.2026 ist genau hier ein Bestand von 96 Millionen\n" "Tripeln verlorengegangen, weil eine Messung unmittelbar nach\n" "dem Timeout den alten Stand zeigte.")


def lade(url, repo, pfad):
    with pfad.open("rb") as fh:
        antwort = requests.post(
            f"{endpunkt(url, repo)}/statements",
            data=fh,
            headers={"Content-Type": TYPEN[pfad.suffix]},
            timeout=3600)
    if antwort.status_code >= 400:
        raise SystemExit(f"\nFEHLER bei {pfad.name}: "
                         f"{antwort.status_code} {antwort.text[:400]}")


def zaehle(url, repo):
    antwort = requests.get(f"{endpunkt(url, repo)}/size", timeout=60)
    antwort.raise_for_status()
    return int(antwort.text.strip())


def wenige_tripel(url, repo, graph, grenze=21):
    antwort = requests.get(
        endpunkt(url, repo),
        params={"query": f"SELECT ?s WHERE {{ GRAPH <{graph}> "
                         f"{{ ?s ?p ?o }} }} LIMIT {grenze}"},
        headers={"Accept": "application/sparql-results+json"}, timeout=60)
    antwort.raise_for_status()
    return len(antwort.json()["results"]["bindings"])


def zaehle_graph(url, repo, graph):
    antwort = requests.get(
        endpunkt(url, repo),
        params={"query": f"SELECT (COUNT(*) AS ?n) WHERE "
                         f"{{ GRAPH <{graph}> {{ ?s ?p ?o }} }}"},
        headers={"Accept": "application/sparql-results+json"}, timeout=3600)
    antwort.raise_for_status()
    return int(antwort.json()["results"]["bindings"][0]["n"]["value"])


def tripel_in_datei(pfad):
    n = 0
    with pfad.open(encoding="utf-8") as fh:
        for zeile in fh:
            s = zeile.strip()
            if s and s[-1] in ";." and not s.startswith(("@", "#")):
                n += 1
    return n


def pruefe_lieferung(url, repo, graph, teile):
    soll = sum(tripel_in_datei(p) for p in teile)
    ist = zaehle_graph(url, repo, graph)
    if ist < soll * 0.95:
        print(f"      NICHT VOLLSTAENDIG: {ist:,} von rund {soll:,} Tripeln"
              .replace(",", "."))
        return (graph.rsplit("/", 1)[1], ist, soll)
    print(f"      geprueft: {ist:,} Tripel".replace(",", "."))
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:7200")
    p.add_argument("--repo", required=True)
    p.add_argument("--nur", nargs="*", default=[],
                   help="nur die SACHDATEIEN dieser Lieferungen laden. " "Betrifft NICHT --metadaten und --eingriffe: die " "schreiben immer fuer alle Lieferungen. Wer eine " "Lieferung nur wegen ihrer Eingriffe hier " "auffuehrt, laedt ihre Sachdaten gleich mit.")
    p.add_argument("--ja", action="store_true",
                   help="grosse Ladelaeufe ohne Rueckfrage ausfuehren")
    p.add_argument("--anhaengen", action="store_true",
                   help="den Graphen NICHT leeren, sondern die Dateien " "dazuladen. Fuer den Fall, dass eine einzelne " "Datei zu einer Lieferung hinzukommt, deren " "uebrige Teile schon im Store stehen -- ein " "DROP wuerde die dann mitreissen. Nur zulaessig, " "wenn die Datei Subjekte bringt, die es im " "Graphen noch nicht gibt; sonst stehen alte und " "neue Fassung nebeneinander.")
    p.add_argument("--alles", action="store_true",
                   help="ALLE Sachdaten laden, die in den Ausgabeordnern " "liegen -- rund sechs Gigabyte. Ohne --alles oder " "--nur werden keine Sachdaten geladen.")
    p.add_argument("--schema", action="store_true",
                   help="auch stkg-schema.ttl laden")
    p.add_argument("--metadaten", action="store_true",
                   help="die Lieferungsmetadaten auffrischen (SPARQL Update)")
    p.add_argument("--eingriffe", action="store_true",
                   help="das Eingriffsregister laden (eigener Graph)")
    p.add_argument("--pruefen", action="store_true",
                   help="nur zeigen, was geschehen wuerde")
    p.add_argument("--wirklich-alles", action="store_true",
                   dest="wirklich_alles",
                   help="zweite Bestaetigung fuer --alles. Ohne sie " "laedt --alles nicht, auch nicht mit --ja.")
    p.add_argument("--sperre-brechen", action="store_true",
                   dest="sperre_brechen",
                   help="eine liegengebliebene Sperrdatei uebergehen. Nur " "wenn sicher KEIN zweiter Lauf laeuft.")
    a = p.parse_args()


    if a.alles and not (a.wirklich_alles or a.pruefen):
        raise SystemExit(
            "--alles ersetzt ALLE Lieferungen in den Ausgabeordnern, " "nicht nur die\ngewuenschten. Wer das will, sagt zusaetzlich " "--wirklich-alles.\nWer einzelne Lieferungen meint: " "--nur <lieferung> [<lieferung> ...]")


    if a.nur:
        liste = [d for d in dateien() if lieferung_von(d) in a.nur]
    elif a.alles:
        liste = dateien()
    else:
        liste = []
        if not (a.schema or a.metadaten or a.eingriffe or a.pruefen):
            raise SystemExit(
                "Nichts zu tun: --nur <lieferung> ... fuer eine Auswahl, " "--alles fuer alle Sachdaten, oder --schema / --metadaten " "/ --eingriffe.")
        if a.pruefen:
            liste = dateien()


    if not liste and a.nur and not (a.schema or a.metadaten or a.eingriffe):
        raise SystemExit("keine Dateien zu den genannten Lieferungen gefunden")


    nach_lieferung = {}
    for d in liste:
        nach_lieferung.setdefault(lieferung_von(d), []).append(d)

    gesamt = sum(d.stat().st_size for d in liste)
    print(f"{len(liste)} Dateien in {len(nach_lieferung)} Lieferungen, "
          f"{gesamt/1024/1024:.1f} MB")
    if a.schema:
        print(f"  dazu das Schema nach <{SCHEMAGRAPH}>")


    if True:
        neu = []
        for lieferung, teile in sorted(nach_lieferung.items()):
            mb = sum(x.stat().st_size for x in teile) / 1024 / 1024
            if mb < 1:
                continue
            graph = f"{BASIS}lieferung/{lieferung}"
            try:
                vorher = wenige_tripel(a.url, a.repo, graph)
            except Exception as e:


                print(f"     {lieferung}: Stand nicht feststellbar "
                      f"({str(e)[:50]})")
                vorher = 0
            if vorher <= 20:
                neu.append((lieferung, mb))
        if neu:
            print()
            print("  NEU -- diese Lieferungen haben bisher keine Sachdaten " "im Store:")
            for lieferung, mb in neu:
                print(f"     {lieferung:<34} {mb:>9.1f} MB")
            zusatz = sum(mb for _, mb in neu)
            if zusatz > 100 and not a.ja and not a.pruefen:
                print()
                print(f"  Das sind {zusatz:.0f} MB, die zum ersten Mal "
                      f"geladen wuerden.")
                print("  Mit --ja ausfuehren, wenn das so gewollt ist, " "oder --nur enger fassen.")
                print("  Hinweis: --metadaten und --eingriffe brauchen die " "Lieferung NICHT in --nur.")
                raise SystemExit("abgebrochen -- nichts geladen.")

    if a.pruefen:


        for lieferung, teile in sorted(nach_lieferung.items()):
            mb = sum(t.stat().st_size for t in teile) / 1024 / 1024
            print(f"  {lieferung:<28} {len(teile):>2} Teil(e), {mb:>8.1f} MB")
            for t in teile:
                print(f"        {t.parent.name}/{t.name}")
        return

    try:
        vorher = zaehle(a.url, a.repo)
    except Exception as fehler:
        raise SystemExit(
            f"Repository '{a.repo}' unter {a.url} nicht erreichbar: {fehler}\n" "Laeuft GraphDB, und gibt es das Repository schon?")
    print(f"Repository haelt {vorher:,} Statements".replace(",", "."))

    if a.schema:
        leere_graph(a.url, a.repo, SCHEMAGRAPH)

        with SCHEMA.open("rb") as fh:
            antwort = requests.post(
                f"{endpunkt(a.url, a.repo)}/statements",
                params={"context": f"<{SCHEMAGRAPH}>"},
                data=fh, headers={"Content-Type": "text/turtle"},
                timeout=600)
        antwort.raise_for_status()
        print(f"  Schema geladen")


    if not a.anhaengen:
        gross = []
        for lieferung in sorted(nach_lieferung):
            graph = f"{BASIS}lieferung/{lieferung}"
            try:
                if wenige_tripel(a.url, a.repo, graph, grenze=1000) >= 1000:
                    gross.append(lieferung)
            except Exception:
                pass
        if gross:
            print()
            print("  ACHTUNG -- diese Graphen enthalten schon Daten und " "werden VOR dem Laden geleert:")
            for lieferung in gross:
                teile = nach_lieferung[lieferung]
                mb = sum(x.stat().st_size for x in teile) / 1024 / 1024
                print(f"     {lieferung:<30} wird ersetzt durch "
                      f"{len(teile)} Datei(en), {mb:.0f} MB")
            if not a.ja:
                print()
                print("  Wenn nur eine einzelne Datei dazukommen soll, ist " "--anhaengen richtig:")
                print("  Sie laedt dazu, ohne den Graphen zu leeren.")
                print("  Mit --ja ausfuehren, wenn wirklich ersetzt werden " "soll.")
                raise SystemExit("abgebrochen -- nichts geladen.")


    if not a.pruefen:
        sperre_pruefen(a.sperre_brechen)
        sperre_setzen(nach_lieferung.keys())
        atexit.register(sperre_loesen)

    unvollstaendig = []
    for lieferung, teile in sorted(nach_lieferung.items()):
        graph = f"{BASIS}lieferung/{lieferung}"
        if not a.anhaengen:
            leere_graph(a.url, a.repo, graph)
        for nr, pfad in enumerate(teile, 1):
            mb = pfad.stat().st_size / 1024 / 1024
            zusatz = f" (Teil {nr}/{len(teile)})" if len(teile) > 1 else ""
            print(f"  {pfad.name:<34} {mb:>7.1f} MB{zusatz}", flush=True)
            lade(a.url, a.repo, pfad)
        fehlt = pruefe_lieferung(a.url, a.repo, graph, teile)
        if fehlt:
            unvollstaendig.append(fehlt)


    if a.metadaten:
        if not METADATEN_UPDATE.exists():
            raise SystemExit("datenlieferung_update.ru fehlt -- erst " "export_datenlieferung.py laufen lassen")
        antwort = requests.post(
            f"{endpunkt(a.url, a.repo)}/statements",
            data={"update": METADATEN_UPDATE.read_text(encoding="utf-8")},
            timeout=600)
        antwort.raise_for_status()
        print("  Lieferungsmetadaten aufgefrischt")

    if a.eingriffe:
        if not EINGRIFF_UPDATE.exists():
            raise SystemExit("eingriff_update.ru fehlt -- erst " "export_eingriff.py laufen lassen")
        antwort = requests.post(
            f"{endpunkt(a.url, a.repo)}/statements",
            data={"update": EINGRIFF_UPDATE.read_text(encoding="utf-8")},
            timeout=600)
        antwort.raise_for_status()
        print("  Eingriffsregister in die Lieferungsgraphen gesetzt")

    nachher = zaehle(a.url, a.repo)
    print(f"\nRepository haelt {nachher:,} Statements "
          f"({nachher - vorher:+,})".replace(",", "."))

    if unvollstaendig:
        print(f"\n{len(unvollstaendig)} Lieferung(en) UNVOLLSTAENDIG im "
              f"Store -- der Ladevorgang ist abgebrochen:")
        for name, ist, soll in unvollstaendig:
            print(f"    {name:<30} {ist:,} von rund {soll:,}"
                  .replace(",", "."))
        raise SystemExit("\nDiese Lieferungen erneut laden. Ein halb " "geladener Graph sieht vollstaendig aus.")


if __name__ == "__main__":
    main()
