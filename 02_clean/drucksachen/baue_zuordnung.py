import sys
from pathlib import Path

import pandas as pd

ABZUG = Path("../../01_fetch/dip/export/dokumente_20260829_114055")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
import zwischenstand


LIEFERUNG = "dip_dokumente"
AUSGABE = zwischenstand.fuer(__file__)
WAHLPERIODEN = (18, 19, 20)


def lies(ordner, name):
    pfad = ordner / f"{name}.csv"
    if not pfad.exists():
        return pd.DataFrame()
    return pd.read_csv(pfad, dtype=str, low_memory=False).fillna("")


def verdichte(df, schluessel, wert, name):
    if df.empty:
        return pd.DataFrame(columns=[schluessel, name, f"{name}_anzahl"])
    g = df.groupby(schluessel)[wert]
    return pd.DataFrame({
        name: g.apply(lambda s: "; ".join(dict.fromkeys(x for x in s if x))),
        f"{name}_anzahl": g.nunique(),
    }).reset_index()


def baue(ordner, wp):
    ds = lies(ordner, f"drucksache_wp{wp}")
    ak = lies(ordner, f"aktivitaet_wp{wp}")
    vp = lies(ordner, f"vorgangsposition_wp{wp}")
    sg = lies(ordner, f"vorgang_sachgebiet_wp{wp}")
    dk = lies(ordner, f"vorgang_deskriptor_wp{wp}")
    urh = lies(ordner, f"drucksache_urheber_wp{wp}")
    pe = lies(ordner, f"person_wp{wp}")
    if ds.empty:
        print(f"WP{wp}: kein Abzug gefunden")
        return

    print(f"\n########## Wahlperiode {wp} ##########")
    ds = ds.copy()
    ds["schluessel"] = ds["fundstelle_id"].where(ds["fundstelle_id"] != "",
                                                 ds["drucksache_id"])
    schl2id = dict(zip(ds["schluessel"], ds["drucksache_id"]))
    schl2nr = dict(zip(ds["schluessel"], ds["dokumentnummer"]))
    schl2typ = dict(zip(ds["schluessel"], ds["drucksachetyp"]))
    schl2datum = dict(zip(ds["schluessel"], ds["datum"]))


    ak_ds = ak[ak["fundstelle_dokumentart"] == "Drucksache"].copy()
    ak_ds = ak_ds[ak_ds["fundstelle_id"].isin(set(ds["schluessel"]))]


    namen = pe[["person_id", "vorname", "nachname", "titel",
                "namenszusatz"]].rename(columns={"titel": "person_titel"})
    person = ak_ds.merge(namen, on="person_id", how="left").fillna("")


    person["name"] = (person["vorname"] + " " + person["namenszusatz"] + " "
                      + person["nachname"]).str.replace(r"\s+", " ",
                                                        regex=True).str.strip()
    person_lang = pd.DataFrame({
        "wahlperiode": wp,
        "drucksache_id": person["fundstelle_id"].map(schl2id),
        "dokumentnummer": person["fundstelle_id"].map(schl2nr),
        "drucksachetyp": person["fundstelle_id"].map(schl2typ),
        "datum": person["fundstelle_id"].map(schl2datum),
        "person_id": person["person_id"],
        "name": person["name"],
        "anzeigeform_dip": person["person_titel"],
        "aktivitaet_id": person["aktivitaet_id"],
        "aktivitaetsart": person["aktivitaetsart"],
        "schluessel": person["fundstelle_id"],
    })


    vp_ds = vp[(vp["dokumentart"] == "Drucksache")
               & (vp["vorgang_id"] != "")].copy()
    ds_vorgang = vp_ds[["fundstelle_id", "vorgang_id",
                        "vorgangsposition", "vorgangstyp"]].drop_duplicates()
    ds_vorgang = ds_vorgang[ds_vorgang["fundstelle_id"].isin(
        set(ds["schluessel"]))]

    sach_lang = ds_vorgang.merge(sg, on="vorgang_id", how="inner")
    desk_lang = ds_vorgang.merge(dk, on="vorgang_id", how="inner")

    for frame in (sach_lang, desk_lang):
        frame.insert(0, "wahlperiode", wp)
        frame.insert(1, "drucksache_id",
                     frame["fundstelle_id"].map(schl2id))
        frame.insert(2, "dokumentnummer",
                     frame["fundstelle_id"].map(schl2nr))


    p_kurz = verdichte(person_lang, "schluessel", "name", "personen")
    p_kurz = p_kurz.drop(columns=["personen_anzahl"]).merge(
        person_lang.groupby("schluessel")["person_id"]
        .agg(personen_anzahl="nunique", beteiligungen_anzahl="size")
        .reset_index(),
        on="schluessel", how="left")
    v_kurz = verdichte(ds_vorgang, "fundstelle_id", "vorgang_id",
                       "vorgaenge").rename(
        columns={"fundstelle_id": "schluessel"})
    s_kurz = verdichte(sach_lang, "fundstelle_id", "sachgebiet",
                       "sachgebiete").rename(
        columns={"fundstelle_id": "schluessel"})
    d_kurz = verdichte(desk_lang, "fundstelle_id", "name",
                       "deskriptoren").rename(
        columns={"fundstelle_id": "schluessel"})
    u_kurz = verdichte(urh, "drucksache_id", "titel", "urheber")

    z = ds[["wahlperiode", "drucksache_id", "dokumentnummer", "drucksachetyp",
            "datum", "titel", "autoren_anzahl", "vorgangsbezug_anzahl",
            "pdf_url", "schluessel"]].copy()
    for teil in (p_kurz, v_kurz, s_kurz, d_kurz):
        z = z.merge(teil, on="schluessel", how="left")
    z = z.merge(u_kurz, on="drucksache_id", how="left")
    z = z.fillna({"personen": "", "personen_anzahl": 0,
                  "beteiligungen_anzahl": 0,
                  "vorgaenge": "", "vorgaenge_anzahl": 0,
                  "sachgebiete": "", "sachgebiete_anzahl": 0,
                  "deskriptoren": "", "deskriptoren_anzahl": 0,
                  "urheber": "", "urheber_anzahl": 0})


    soll = pd.to_numeric(z["autoren_anzahl"], errors="coerce")
    ist = z["beteiligungen_anzahl"].astype(int)
    z["status_person"] = [
        "keine Person und kein Urheber" if i == 0 and not u else
        "nur Urheber, keine Person" if i == 0 else
        "vollstaendig" if pd.notna(s) and s == i else
        "mehr als angekuendigt" if pd.notna(s) and i > s else
        "weniger als angekuendigt"
        for s, i, u in zip(soll, ist, z["urheber"])
    ]
    z["mehrfachbeteiligung"] = [
        "" if p == b else "eine Person mehrfach beteiligt"
        for p, b in zip(z["personen_anzahl"].astype(int), ist)
    ]
    z["status_thema"] = [
        "kein Vorgang" if v == 0 else
        "Sachgebiet vorhanden" if sa > 0 else
        "Vorgang ohne Sachgebiet, aber Deskriptoren" if de > 0 else
        "Vorgang ohne Sachgebiet und ohne Deskriptor"
        for v, sa, de in zip(z["vorgaenge_anzahl"].astype(int),
                             z["sachgebiete_anzahl"].astype(int),
                             z["deskriptoren_anzahl"].astype(int))
    ]
    z = z.drop(columns=["schluessel"])


    AUSGABE.mkdir(parents=True, exist_ok=True)
    for name, frame in (
        (f"zuordnung_wp{wp}", z),
        (f"drucksache_person_wp{wp}", person_lang.drop(columns=["schluessel"])),
        (f"drucksache_sachgebiet_wp{wp}",
         sach_lang.drop(columns=["fundstelle_id"])),
        (f"drucksache_deskriptor_wp{wp}",
         desk_lang.drop(columns=["fundstelle_id"])),
    ):
        frame.to_csv(AUSGABE / f"{name}.csv", index=False, encoding="utf-8")
        print(f"  {name}.csv: {len(frame)} Zeilen")


    print(f"\n  Dokumente gesamt: {len(z)}")
    print("  Zuordnung Person / Fraktion:")
    for wert, n in z["status_person"].value_counts().items():
        print(f"    {wert:34s} {n:7d}")
    print("  Zuordnung Thema:")
    for wert, n in z["status_thema"].value_counts().items():
        print(f"    {wert:44s} {n:7d}")
    print(f"  Dokumente mit mehrfach beteiligter Person: "
          f"{int((z['mehrfachbeteiligung'] != '').sum()):7d}")
    print(f"  mit mindestens einer Person   : "
          f"{int((z['personen_anzahl'].astype(int) > 0).sum()):7d}")
    print(f"  mit mindestens einem Urheber  : "
          f"{int((z['urheber_anzahl'].astype(int) > 0).sum()):7d}")
    print(f"  mit Person ODER Urheber       : "
          f"{int(((z['personen_anzahl'].astype(int) > 0) | (z['urheber_anzahl'].astype(int) > 0)).sum()):7d}")
    print(f"  mit mindestens einem Sachgebiet: "
          f"{int((z['sachgebiete_anzahl'].astype(int) > 0).sum()):7d}")
    print(f"  mit mindestens einem Deskriptor: "
          f"{int((z['deskriptoren_anzahl'].astype(int) > 0).sum()):7d}")
    print("  Dokumente ohne Sachgebiet nach Typ:")
    ohne = z[z["sachgebiete_anzahl"].astype(int) == 0]
    for typ, n in ohne["drucksachetyp"].value_counts().head(6).items():
        print(f"    {typ[:38]:38s} {n:7d}")


def main():
    ordner = Path(sys.argv[1]) if len(sys.argv) > 1 else ABZUG
    if not ordner.is_dir():
        raise SystemExit(f"Abzug nicht gefunden: {ordner.resolve()}")
    print(f"Abzug: {ordner.resolve()}")
    for wp in WAHLPERIODEN:
        baue(ordner, wp)


if __name__ == "__main__":
    main()
