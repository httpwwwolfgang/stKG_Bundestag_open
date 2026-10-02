import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "lib"))
sys.path.insert(0, str(REPO / "03_load_db" / "meta"))

from load_datenlieferung import LIEFERUNGEN

ZIEL = Path(__file__).resolve().parent / "raum_lieferungen.md"


FELDER = [
    ("bezeichnung",          "Bez"),
    ("beschreibung",         "Beschr"),
    ("herausgeber",          "Hrsg"),
    ("urheber",              "Urh"),
    ("zitat",                "Zitat"),
    ("lizenz",               "Lizenz"),
    ("datei",                "Quelle"),
    ("stand_quelle",         "Stand"),
    ("geaendert_quelle",     "Geaend"),
    ("gebietsstand",         "Bezugszp"),
    ("wahljahr",             "Zeitraum"),
    ("uebernahme_zeitpunkt", "UebZeit"),
    ("uebernahme_verfahren", "UebVerf"),
    ("art",                  "Art"),
    ("basis",                "Basis"),
    ("eingriffe",            "Eingr"),
    ("limitierungen",        "Limit"),
]


PFLICHT = {"bezeichnung", "herausgeber", "zitat"}


ZUORDNUNG = [
    ("gemeindestand",               135404, "Gemeindestand",           ["bkg_vg250"]),
    ("gemeindestand_stichtag",       81119, "Gemeindestand",           ["bkg_vg250"]),
    ("kreisstand",                    4827, "Kreisstand",              ["bkg_vg250"]),
    ("kreisstand_stichtag",           3247, "Kreisstand",              ["bkg_vg250"]),
    ("landstand",                       16, "Bundesland",              ["bkg_vg250"]),
    ("landstand_stichtag",             193, "Bundesland",              ["bkg_vg250"]),
    ("wahlkreis",                      897, "Wahlkreisstand",          ["bwl_wahlkreisgeometrie"]),
    ("kleinst_100_amtlich",          17453, "Auszaehleinheit",          ["bwl_wahlbezirke_2013", "bwl_wahlbezirke_2017", "bwl_wahlbezirke_2021"]),
    ("kleinst_100_geteilt",            167, "Auszaehleinheit",          ["grossstadt_wkr_2013", "grossstadt_wkr_2017", "grossstadt_wkr_2021"]),
    ("kreis_wahlkreis",               1636, "KreisWahlkreisZuschnitt", ["kreis_wahlkreis_zuschnitt"]),
    ("hexkarte",                       897, "KartogrammGeometrie",     ["hexkarte_wahlkreis"]),
    ("gemeinde_wahlkreis_wahltag",   33792, "Zugehoerigkeit",          ["gv100ad_2013", "bwl_zuordnung_2017", "bwl_zuordnung_2021"]),
    ("gemeinde_kreis",               33039, "Zugehoerigkeit",          ["bkg_vg250"]),
    ("gemeinde_land",                33680, "Zugehoerigkeit",          ["bkg_vg250"]),
    ("kreis_land",                    1203, "Zugehoerigkeit",          ["bkg_vg250"]),


    ("wahlkreis_land",                 897, "Zugehoerigkeit",          ["bwl_wahlkreisgeometrie"]),
    ("gemeinde_kleinst_100",         35231, "Zugehoerigkeit",          ["bwl_wahlbezirke_2013", "bwl_wahlbezirke_2017", "bwl_wahlbezirke_2021", "grossstadt_wkr_2013", "grossstadt_wkr_2017", "grossstadt_wkr_2021"]),
    ("gebietsuebergang",              3562, "Filiation",               ["destatis_gebietsaenderungen"]),
    ("wahlkreisuebergang",             598, "Filiation",               ["wahlkreisuebergang"]),
    ("wahlkreisuebergang_gemeinde",    480, "Filiation/betrifftEinheit", ["wahlkreisuebergang"]),
    ("einheitsuebergang",            12101, "Filiation",               ["einheitsuebergang"]),
    ("gemeindestand_crosswalk",     135496, "Umrechnung",              ["bbsr_ags_crosswalk"]),
    ("kreisstand_crosswalk",          4861, "Umrechnung",              ["bbsr_cty_crosswalk"]),
    ("nachbarschaft",                 4908, "Nachbarschaft",           ["nachbarschaft_wahlkreis"]),
    ("gemeinde_gerda",               99507, "Zugehoerigkeit",          ["gemeinde_gerda_zuordnung"]),
]


GERECHNET_AUS = {
    "kreis_wahlkreis":            "Verschneidung Kreisstand x Wahlkreisstand",
    "hexkarte":                   "Hexagonberechnung ueber den Wahlkreisstaenden, mit Handarbeit",
    "wahlkreisuebergang":          "Mengenvergleich der zugeordneten Gemeinden",
    "wahlkreisuebergang_gemeinde": "Mengenvergleich der zugeordneten Gemeinden",
    "einheitsuebergang":           "Mitgliedermengen der Auswertungseinheiten je Wahl",
    "nachbarschaft":               "Geometrien der Wahlkreisstaende",
    "gemeinde_gerda":              "GERDA-Schluessel gegen die Gebietsstaende",
}


def tausender(n):
    return f"{n:,}".replace(",", ".")


def baue():
    bekannt = {e["lieferung_id"]: e for e in LIEFERUNGEN}
    benutzt, ohne = [], []

    for tabelle, zeilen, klasse, lieferungen in ZUORDNUNG:
        if lieferungen is None:
            ohne.append((tabelle, zeilen, klasse))
        else:
            for k in lieferungen:
                if k not in benutzt:
                    benutzt.append(k)

    t = [
        "# Modul 03 · Raum — die Datenlieferungen dahinter",
        "",
        "ERZEUGT von `raum_lieferungen.py`, nicht von Hand pflegen.",
        "",
        "Zu jedem Raumbestand, der dem Schema zugeordnet ist: aus welcher " "Datenlieferung er stammt, und was über diese Lieferung bekannt ist. " "Modul 02 verlangt achtzehn Angaben je Lieferung; was hier leer " "steht, ist nachzuarbeiten — zu beschaffen oder als nicht vorhanden " "zu belegen.",
        "",
        "**Die Zuordnung ist Handarbeit aus den Skriptköpfen** " "(`raum_ladevorschrift.md`) und nicht aus den Daten erschlossen: Nur " "drei Raumtabellen führen eine Spalte `lieferung_id`. Wo die Herkunft " "im Skriptkopf nicht eindeutig hervorgeht, steht sie als fehlend und " "wird nicht geraten.",
        "",
        "---",
        "",
        "## 1 · Bestand → Lieferung",
        "",
        "| Bestand | Zeilen | Klasse | Lieferung |",
        "|---|---:|---|---|",
    ]
    for tabelle, zeilen, klasse, lieferungen in ZUORDNUNG:
        wert = ", ".join(f"`{k}`" for k in lieferungen) if lieferungen \
            else "**fehlt — abgeleitet**"
        t.append(f"| `{tabelle}` | {tausender(zeilen)} | {klasse} | {wert} |")

    t += [
        "",
        "---",
        "",
        "## 2 · Was über diese Lieferungen bekannt ist",
        "",
        f"Die {len(benutzt)} Lieferungen, auf die der Raumbestand zeigt. " "`+` heißt: Angabe vorhanden. Leer heißt: fehlt.",
        "",
        "| Lieferung | " + " | ".join(k for _, k in FELDER) + " |",
        "|---" * (len(FELDER) + 1) + "|",
    ]
    for kennung in benutzt:
        e = bekannt.get(kennung)
        if e is None:
            zellen = ["?"] * len(FELDER)
        else:
            zellen = ["+" if e.get(f) is not None else " " for f, _ in FELDER]
        t.append(f"| `{kennung}` | " + " | ".join(zellen) + " |")

    t += ["", "### Was je Lieferung fehlt", ""]
    for kennung in benutzt:
        e = bekannt.get(kennung)
        if e is None:
            t.append(f"- **`{kennung}`** — steht nicht in `load_datenlieferung.py`")
            continue
        fehlend = [name for f, name in FELDER if e.get(f) is None]
        pflicht = [f for f in PFLICHT if not e.get(f)]
        marke = " · **Pflichtangabe fehlt: " + ", ".join(sorted(pflicht)) + "**" if pflicht else ""
        t.append(f"- **`{kennung}`** — fehlt: {', '.join(fehlend) or 'nichts'}{marke}")

    t += ["", "---", "", "## 3 · Bestände ohne Lieferung", ""]
    if ohne:
        t += [
            "Diese Bestände sind gerechnet, nicht geliefert. Für jeden ist eine " "abgeleitete Lieferung anzulegen: mit `art = 'abgeleitet'`, " "`prov:wasDerivedFrom` auf die Ausgangslieferungen, dem Zitat der " "Ausgangsquelle und der Kennzeichnung der Veränderung (mod:2.4).",
            "",
            "| Bestand | Zeilen | gerechnet aus |",
            "|---|---:|---|",
        ]
        for tabelle, zeilen, _ in ohne:
            t.append(f"| `{tabelle}` | {tausender(zeilen)} | "
                     f"{GERECHNET_AUS.get(tabelle, '—')} |")
        summe = sum(z for _, z, _ in ohne)
        t += ["",
              f"Zusammen {tausender(summe)} Zeilen in {len(ohne)} Beständen " "ohne Herkunftsangabe.", ""]
    else:
        t += ["Keiner mehr — jeder Raumbestand ist einer Lieferung zugeordnet. " "Die gerechneten Bestände tragen eine eigene abgeleitete " "Lieferung mit `basis` auf ihre Ausgangslieferungen:", ""]
        for tabelle, _, _, lieferungen in ZUORDNUNG:
            if tabelle in GERECHNET_AUS:
                t.append(f"- `{tabelle}` → `{lieferungen[0]}` — "
                         f"{GERECHNET_AUS[tabelle]}")
        t.append("")

    ZIEL.write_text("\n".join(t) + "\n", encoding="utf-8")
    print(f"geschrieben: {ZIEL}")
    print(f"  {len(ZUORDNUNG)} Bestaende, {len(benutzt)} Lieferungen benutzt, "
          f"{len(ohne)} ohne Lieferung")


if __name__ == "__main__":
    baue()
