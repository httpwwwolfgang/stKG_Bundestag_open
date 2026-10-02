import csv
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from db import (run_sql, run_sql_file, query,
                             _psql_args, _pg_env)

SCHEMA = "parlamentsarbeit"
HIER = Path(__file__).resolve().parent
import zwischenstand


import lieferung
LIEFERUNG = "dip_dokumente"
ZWISCHEN = zwischenstand.fuer(__file__, "zwischen")
DIP = zwischenstand.ordner("01_fetch", "dip", "export")
ZUORDNUNG = zwischenstand.ordner("02_clean", "drucksachen", "export")
WAHLPERIODEN = (18, 19, 20)


def neuester(praefix):
    treffer = sorted(p for p in DIP.glob(f"{praefix}_*") if p.is_dir())
    if not treffer:
        raise SystemExit(f"Kein Ordner {praefix}_* in {DIP}")
    return treffer[-1]


def sammle(ordner, muster):
    teile = []
    for wp in WAHLPERIODEN:
        pfad = ordner / muster.format(wp=wp)
        if not pfad.exists():
            print(f"    Hinweis: {pfad.name} fehlt")
            continue
        teile.append(pd.read_csv(pfad, dtype=str, keep_default_na=False,
                                 low_memory=False))
    if not teile:
        raise SystemExit(f"Keine Datei zu {muster} in {ordner}")
    return pd.concat(teile, ignore_index=True)


def sammle_jsonl(ordner, muster):
    zeilen = []
    for wp in WAHLPERIODEN:
        pfad = ordner / muster.format(wp=wp)
        if not pfad.exists():
            print(f"    Hinweis: {pfad.name} fehlt")
            continue
        with open(pfad, encoding="utf-8") as fh:
            for z in fh:
                zeilen.append(json.loads(z))
    return pd.DataFrame(zeilen).astype(str)


def leer_zu_null(d, spalten):
    for s in spalten:
        if s in d.columns:
            d[s] = d[s].replace("", None)
    return d


def lade(tabelle, rahmen, spalten, null_spalten=(), entdoppeln=False):
    fehlend = [s for s in spalten if s not in rahmen.columns]
    if fehlend:
        raise SystemExit(f"{tabelle}: Spalten fehlen: {fehlend}")
    d = leer_zu_null(rahmen[spalten].copy(), null_spalten or spalten)
    if entdoppeln:
        vorher = len(d)
        d = d.drop_duplicates()
        if vorher != len(d):
            print(f"  {tabelle}: {vorher} Zeilen entdoppelt auf {len(d)}")

    ZWISCHEN.mkdir(parents=True, exist_ok=True)
    tmp = ZWISCHEN / f"{tabelle}.tsv"
    d.to_csv(tmp, index=False, sep="\t", na_rep="",
             quoting=csv.QUOTE_MINIMAL, encoding="utf-8")

    befehl = (fr"\copy {SCHEMA}.{tabelle} ({', '.join(spalten)}) "
              fr"FROM '{tmp.as_posix()}' WITH (FORMAT csv, HEADER true, "
              fr"DELIMITER E'\t')")
    run_sql(f"TRUNCATE {SCHEMA}.{tabelle} CASCADE;", tabelle)
    proc = subprocess.run(_psql_args() + ["-c", befehl], env=_pg_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"{tabelle} laden fehlgeschlagen:\n{proc.stderr}")

    n = int(query(f"SELECT count(*) FROM {SCHEMA}.{tabelle};")[0][0])
    zeichen = "ok " if n == len(d) else "!! "
    print(f"  {zeichen}{n:>9,}  {tabelle:<28} erwartet {len(d):>9,}")
    return n, len(d)


def main():
    lieferung.merke(LIEFERUNG)
    dok = neuester("dokumente")
    pos = neuester("vorgangspositionen")
    txt = neuester("anfragetexte")
    print(f"Metadaten          : {dok.name}")
    print(f"Vorgangspositionen : {pos.name}")
    print(f"Anfragetexte       : {txt.name}")
    print(f"Zuordnung          : {ZUORDNUNG}")

    print("\nSchema anlegen ...")
    run_sql_file(HIER / "schema.sql")

    print("\nLaden ...")
    bilanz = []


    ds = sammle(dok, "drucksache_wp{wp}.csv")
    bilanz.append(lade("drucksache", ds, [
        "drucksache_id", "wahlperiode", "dokumentnummer", "dokumentart",
        "drucksachetyp", "datum", "verteildatum", "titel", "herausgeber",
        "pdf_url", "fundstelle_id", "autoren_anzahl", "vorgangsbezug_anzahl",
        "aktualisiert"]))

    bilanz.append(lade("drucksache_urheber",
                       sammle(dok, "drucksache_urheber_wp{wp}.csv"),
                       ["drucksache_id", "dokumentnummer", "bezeichnung",
                        "titel", "einbringer"]))
    bilanz.append(lade("drucksache_ressort",
                       sammle(dok, "drucksache_ressort_wp{wp}.csv"),
                       ["drucksache_id", "dokumentnummer", "titel",
                        "federfuehrend"]))

    bilanz.append(lade("drucksache_person",
                       sammle(ZUORDNUNG, "drucksache_person_wp{wp}.csv"),
                       ["aktivitaet_id", "drucksache_id", "dokumentnummer",
                        "drucksachetyp", "datum", "person_id", "name",
                        "anzeigeform_dip", "aktivitaetsart", "wahlperiode"]))

    texte = sammle_jsonl(txt, "anfragetext_wp{wp}.jsonl")
    bilanz.append(lade("anfragetext", texte,
                       ["drucksache_id", "zeichen", "text"],
                       null_spalten=["zeichen"]))


    stamm = sammle(dok, "person_wp{wp}.csv").rename(
        columns={"fraktion": "fraktion_abzugsstand"})
    bilanz.append(lade("dip_person", stamm, [
        "person_id", "abgefragt_wahlperiode", "nachname", "vorname",
        "namenszusatz", "titel", "typ", "fraktion_abzugsstand", "funktion",
        "funktionszusatz", "bundesland", "ressort", "wahlkreiszusatz",
        "wahlperioden", "basisdatum", "datum", "aktualisiert",
        "rollen_anzahl"]))


    bilanz.append(lade("dip_person_rolle",
                       sammle(dok, "person_rolle_wp{wp}.csv"),
                       ["person_id", "fraktion", "funktionszusatz",
                        "ressort_titel", "bundesland", "wahlkreiszusatz",
                        "nachname", "vorname", "namenszusatz",
                        "wahlperiode_nummer"], entdoppeln=True))


    bilanz.append(lade("vorgang", sammle(dok, "vorgang_wp{wp}.csv"), [
        "vorgang_id", "wahlperiode", "vorgangstyp", "titel", "abstract",
        "datum", "beratungsstand", "gesta", "kom", "ratsdok", "archiv",
        "zustimmungsbeduerftigkeit", "aktualisiert"]))
    bilanz.append(lade("vorgang_sachgebiet",
                       sammle(dok, "vorgang_sachgebiet_wp{wp}.csv"),
                       ["vorgang_id", "sachgebiet"]))
    bilanz.append(lade("vorgang_deskriptor",
                       sammle(dok, "vorgang_deskriptor_wp{wp}.csv"),
                       ["vorgang_id", "name", "typ", "fundstelle"]))
    bilanz.append(lade("vorgang_initiative",
                       sammle(dok, "vorgang_initiative_wp{wp}.csv"),
                       ["vorgang_id", "initiative"]))
    verl = sammle(dok, "vorgang_verlinkung_wp{wp}.csv").rename(
        columns={"id": "ziel_vorgang_id"})
    bilanz.append(lade("vorgang_verlinkung", verl,
                       ["vorgang_id", "verweisung", "titel",
                        "ziel_vorgang_id", "wahlperiode", "gesta"]))


    bilanz.append(lade("vorgangsposition",
                       sammle(pos, "vorgangsposition_wp{wp}.csv"), [
        "position_id", "wahlperiode", "vorgang_id", "vorgangsposition",
        "vorgangstyp", "titel", "abstract", "datum", "dokumentart",
        "dokumentnummer", "drucksachetyp", "fundstelle_id",
        "fundstelle_datum", "verteildatum", "herausgeber", "seite",
        "anfangsseite", "endseite", "anfangsquadrant", "endquadrant",
        "pdf_url", "xml_url", "zuordnung", "gang", "fortsetzung",
        "nachtrag", "aktivitaet_anzahl", "aktualisiert"]))
    bilanz.append(lade("vorgangsposition_urheber",
                       sammle(pos, "vorgangsposition_urheber_wp{wp}.csv"),
                       ["position_id", "bezeichnung", "titel", "einbringer"]))


    print("\n----- Bilanz -----")
    abweichung = [(t, n, s) for (n, s), t in zip(bilanz, [
        "drucksache", "drucksache_urheber", "drucksache_ressort",
        "drucksache_person", "anfragetext", "dip_person", "dip_person_rolle",
        "vorgang", "vorgang_sachgebiet", "vorgang_deskriptor",
        "vorgang_initiative", "vorgang_verlinkung", "vorgangsposition",
        "vorgangsposition_urheber"]) if n != s]
    if abweichung:
        for t, n, s in abweichung:
            print(f"  ABWEICHUNG {t}: geladen {n}, erwartet {s}")
    else:
        print("  Alle Tabellen: geladene Zeilen gleich erwartete Zeilen.")

    print("\n----- Gegenprobe ueber die Sichten -----")
    for frage, sql in (
        ("Drucksachen",
         f"SELECT count(*) FROM {SCHEMA}.drucksache"),
        ("Drucksachen mit Urheber",
         f"SELECT count(DISTINCT drucksache_id) FROM {SCHEMA}.drucksache_urheber"),
        ("Drucksachen mit Person",
         f"SELECT count(DISTINCT drucksache_id) FROM {SCHEMA}.drucksache_person"),
        ("Drucksachen mit Vorgang",
         f"SELECT count(DISTINCT drucksache_id) FROM {SCHEMA}.drucksache_vorgang"),
        ("Drucksachen mit Sachgebiet",
         f"SELECT count(DISTINCT drucksache_id) FROM {SCHEMA}.drucksache_sachgebiet"),
        ("Drucksachen mit Deskriptor",
         f"SELECT count(DISTINCT drucksache_id) FROM {SCHEMA}.drucksache_deskriptor"),
        ("Anfragen mit Volltext",
         f"SELECT count(*) FROM {SCHEMA}.anfragetext"),
        ("Positionen mit offenem Vorgang",
         f"SELECT count(*) FROM {SCHEMA}.vorgangsposition_ohne_vorgang"),
    ):
        print(f"  {frage:<32} {int(query(sql + ';')[0][0]):>9,}")


    print("\n----- Anschluss an die Personenbruecke -----")
    da = query(f"SELECT to_regclass('{SCHEMA}.personenbruecke') IS NOT NULL;")
    if da and da[0][0].strip() == "t":
        a, b = query(
            f"SELECT count(DISTINCT p.person_id), count(DISTINCT b.person_id) "
            f"FROM {SCHEMA}.drucksache_person p "
            f"LEFT JOIN {SCHEMA}.personenbruecke b USING (person_id);")[0]
        print(f"  Personen in drucksache_person   : {int(a):>9,}")
        print(f"  davon in der Personenbruecke    : {int(b):>9,}")
        print(f"  ohne Anschluss ans Mandat       : {int(a) - int(b):>9,}")
    else:
        print("  parlamentsarbeit.personenbruecke gibt es noch nicht — der " "Protokoll-Strang hat sie noch nicht geladen.")


if __name__ == "__main__":
    main()
