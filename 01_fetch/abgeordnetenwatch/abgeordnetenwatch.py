import os
import math
import time
import logging
from collections import deque
from datetime import datetime, timezone

import requests
import psycopg2
from psycopg2.extras import Json, execute_values


DB_HOST     = "localhost"
DB_PORT     = 5432
DB_NAME     = "political_stKG"
DB_USER     = "postgres"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))
from zugang import db_passwort
DB_PASSWORD = db_passwort()
DB_SCHEMA   = "politiker_innen"

DB_DSN = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"


URI_BASE = "https://w.example.org/aw/"


PARLIAMENT_ID  = 5


ELECTION_YEARS = [2013, 2017, 2021]

PAGE_SIZE = 1000
DB_BATCH = 500


START_CALLS_PER_MIN   = 12
MIN_CALLS_PER_MIN     = 4
DECKEL_CALLS_PER_MIN  = 24
ERHOEHEN_NACH_ERFOLGEN = 60
ERHOEHEN_SCHRITT       = 2


MAX_CALLS_PER_MIN = START_CALLS_PER_MIN


TEST_LIMIT = None


VORSCHAU_ONLY = False


ENDPUNKT_CHECK = False


RESUME = True


REQUEST_TIMEOUT = 60
MAX_RETRY_429   = 5
MAX_RETRY_5XX   = 5
MAX_RETRY_NET   = 5


ABBRUCH_NACH_FEHLERN = 2

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aw-import")


class RateLimiter:

    def __init__(self, max_calls, period=60.0):
        self.max_calls = max_calls
        self.period = period
        self.min_spacing = period / max_calls
        self.deckel = DECKEL_CALLS_PER_MIN
        self._calls = deque()
        self._last = 0.0
        self._erfolge = 0
        self._zuletzt_gebremst = False
        self._gebremst_gesamt = 0
        self._anfragen_gesamt = 0

    def _tempo(self, neu, grund):
        neu = max(MIN_CALLS_PER_MIN, min(self.deckel, neu))
        if neu != self.max_calls:
            log.info("Tempo %s: %d -> %d Anfragen/min (Abstand %.1fs) - %s",
                     "hoch" if neu > self.max_calls else "runter",
                     self.max_calls, neu, self.period / neu, grund)
            self.max_calls = neu
            self.min_spacing = self.period / neu

    def erfolg(self):
        if not self._zuletzt_gebremst:
            return
        self._erfolge += 1
        if self._erfolge >= ERHOEHEN_NACH_ERFOLGEN and self.max_calls < self.deckel:
            self._erfolge = 0
            self._tempo(self.max_calls + ERHOEHEN_SCHRITT,
                        f"{ERHOEHEN_NACH_ERFOLGEN} gebremste Anfragen ohne 429")

    def bericht(self):
        anteil = (100.0 * self._gebremst_gesamt / self._anfragen_gesamt
                  if self._anfragen_gesamt else 0.0)
        return (f"{self.tatsaechliche_rate()} Anfragen in den letzten 60s, "
                f"Kontingent {self.max_calls}/min (Deckel {self.deckel}), "
                f"vom Limiter gebremst: {anteil:.0f} % der Anfragen")

    def tatsaechliche_rate(self):
        return len(self._calls)

    def acquire(self):


        wart = self.min_spacing - (time.monotonic() - self._last)
        self._zuletzt_gebremst = wart > 0
        self._anfragen_gesamt += 1
        if wart > 0:
            self._gebremst_gesamt += 1
            time.sleep(wart)

        now = time.monotonic()
        while self._calls and now - self._calls[0] > self.period:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            sleep_for = self.period - (now - self._calls[0]) + 0.2
            log.info("Rate-Limit erreicht - warte %.1fs ...", sleep_for)
            time.sleep(max(sleep_for, 0))
            now = time.monotonic()
            while self._calls and now - self._calls[0] > self.period:
                self._calls.popleft()
        self._last = time.monotonic()
        self._calls.append(self._last)

    def drosseln(self):
        self._erfolge = 0
        self.deckel = max(MIN_CALLS_PER_MIN, self.max_calls - ERHOEHEN_SCHRITT)
        log.warning("429 bei %d Anfragen/min - Deckel jetzt %d",
                    self.max_calls, self.deckel)
        self._tempo(self.max_calls // 2, "429 erhalten")


class AbgeordnetenwatchAPI:
    BASE = "https://www.abgeordnetenwatch.de/api/v2"

    def __init__(self, limiter):
        self.limiter = limiter
        self._limit_gemeldet = False
        self.letzte_dauer = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "wahlkreis-kg-import/1.0 (Forschungsprojekt)",
            "Accept": "application/json",
        })

    def _get(self, path, params):
        v_429 = v_5xx = v_net = 0
        while True:
            self.limiter.acquire()
            t0 = time.monotonic()
            try:
                resp = self.session.get(f"{self.BASE}/{path}", params=params,
                                        timeout=REQUEST_TIMEOUT)


                self.letzte_dauer = time.monotonic() - t0
            except (requests.Timeout, requests.ConnectionError) as e:
                v_net += 1
                if v_net > MAX_RETRY_NET:
                    raise
                back = min(2 ** v_net, 60)
                log.warning("Netzwerkfehler %s bei /%s (%d/%d) - warte %ds ...",
                            type(e).__name__, path, v_net, MAX_RETRY_NET, back)
                time.sleep(back)
                continue

            if resp.status_code == 429:
                v_429 += 1


                log.warning("429 bei /%s - Kopfzeilen zum Limit: %s",
                            path, self._limit_header(resp) or "keine")
                if v_429 > MAX_RETRY_429:
                    raise RuntimeError(
                        f"{MAX_RETRY_429}x 429 Too Many Requests bei /{path} - " "Abbruch. Nicht sofort neu starten: erst klären, ob das " "Kontingent nur erschöpft oder die Adresse gesperrt ist, " "und ggf. MAX_CALLS_PER_MIN senken.")
                self.limiter.drosseln()
                wait = int(resp.headers.get("Retry-After", "60"))
                log.warning("429 Too Many Requests (%d/%d) - warte %ds ...",
                            v_429, MAX_RETRY_429, wait)
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                v_5xx += 1
                if v_5xx > MAX_RETRY_5XX:
                    resp.raise_for_status()
                back = min(2 ** v_5xx, 60)
                log.warning("Serverfehler %s (%d/%d) - Backoff %ds ...",
                            resp.status_code, v_5xx, MAX_RETRY_5XX, back)
                time.sleep(back)
                continue

            resp.raise_for_status()
            self.limiter.erfolg()
            if not self._limit_gemeldet:


                self._limit_gemeldet = True
                log.info("Kopfzeilen zum Limit bei einer normalen Antwort: %s",
                         self._limit_header(resp) or "keine")
            return resp.json()

    @staticmethod
    def _limit_header(resp):
        return {k: v for k, v in resp.headers.items()
                if any(s in k.lower() for s in ("rate", "limit", "retry"))}

    def total_count(self, path, extra_params=None):
        params = {"page": 0, "pager_limit": 1}
        if extra_params:
            params.update(extra_params)
        payload = self._get(path, params)
        return (payload.get("meta", {}) or {}).get("result", {}).get("total")

    def fetch_all(self, path, extra_params=None, limit=None):
        page = 0
        seen = 0
        page_size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit)
        while True:
            params = {"page": page, "pager_limit": page_size}
            if extra_params:
                params.update(extra_params)

            payload = self._get(path, params)
            data = payload.get("data", []) or []
            if not data:
                break

            for item in data:
                yield item
                seen += 1
                if limit is not None and seen >= limit:
                    log.info("  %s: Test-Limit %d erreicht", path, limit)
                    return

            total = (payload.get("meta", {}) or {}).get("result", {}).get("total")
            log.info("  %s: Seite %d - %d/%s geladen", path, page, seen, total)

            if total is not None and seen >= total:
                break
            page += 1


def batched(iterable, n):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= n:
            yield batch
            batch = []
    if batch:
        yield batch


import re


def _period_year(p):
    for key in ("election_date", "start_date_period", "start_date"):
        v = p.get(key)
        if v:
            try:
                return int(str(v)[:4])
            except ValueError:
                pass
    m = re.search(r"(19|20)\d{2}", p.get("label") or "")
    return int(m.group(0)) if m else None


def resolve_period_ids(conn, parliament_id, years):
    want = set(years)
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM raw_parliament_periods;")
        rows = cur.fetchall()
    ids = []
    for (p,) in rows:
        if (p.get("parliament") or {}).get("id") != parliament_id:
            continue
        if _period_year(p) in want:
            ids.append(p["id"])
    return sorted(set(ids))


FULL_ENTITIES = [
    ("parliaments",           "raw_parliaments"),
    ("parties",               "raw_parties"),
    ("topics",                "raw_topics"),
    ("cities",                "raw_cities"),
    ("countries",             "raw_countries"),
    ("sidejob-organizations", "raw_sidejob_organizations"),
]


CURRENT_ON_ALL = {"current_on": "all"}


PERIOD_ENTITIES = [
    ("constituencies",        "raw_constituencies",      "parliament_period", None),
    ("candidacies-mandates",  "raw_candidacies_mandates", "parliament_period",
     CURRENT_ON_ALL),
    ("electoral-lists",       "raw_electoral_lists",     "parliament_period", None),
    ("committees",            "raw_committees",          "field_legislature", None),
    ("election-program",      "raw_election_programs",   "parliament_period", None),
    ("polls",                 "raw_polls",               "field_legislature", None),
    ("fractions",             "raw_fractions",           "legislature", None),


    ("sidejobs",              "raw_sidejobs",
     "mandates[entity.parliament_period]", None),
]


PARK_TABLES = {
    "raw_politicians": "raw_politicians_non_bundestag",
    "raw_sidejobs":    "raw_sidejobs_non_bundestag",
}


RAW_TABLES = (
    [t for (_, t) in FULL_ENTITIES]
    + [t for (_, t, _f, _e) in PERIOD_ENTITIES]
    + ["raw_parliament_periods", "raw_politicians",
       "raw_committee_memberships", "raw_votes"]
    + list(PARK_TABLES.values())
)


FETCH_STATE_DDL = """
CREATE TABLE IF NOT EXISTS fetch_state (
    scope      TEXT    NOT NULL,
    item_id    INTEGER NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, item_id)
);
"""


RAW_DDL = """
CREATE TABLE IF NOT EXISTS {t} (
    id                INTEGER PRIMARY KEY,
    label             TEXT,
    data              JSONB NOT NULL,
    abgefragt_periode INTEGER,
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE {t} ADD COLUMN IF NOT EXISTS abgefragt_periode INTEGER;
"""


CONSTITUENCY_DDL = f"""
CREATE TABLE IF NOT EXISTS constituency (
    aw_id                    INTEGER PRIMARY KEY,
    number                   INTEGER,
    name                     TEXT,
    parliament_period_id     INTEGER,
    parliament_period_label  TEXT,



    parliament_period_herkunft TEXT,
    lineage_id               TEXT,
    uri  TEXT GENERATED ALWAYS AS ('{URI_BASE}constituency/' || aw_id::text) STORED,
    geom geometry(MultiPolygon, 4326),
    raw  JSONB,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE constituency ADD COLUMN IF NOT EXISTS parliament_period_herkunft TEXT;
COMMENT ON COLUMN constituency.parliament_period_herkunft IS
 'abgeleitet = aus abgefragt_periode erschlossen, also aus der Abfrage, mit der '
 'die Zeile hereinkam - das Wahlkreisobjekt selbst nennt keine Wahlperiode '
 '(geprueft 23.08.2026 und 27.08.2026, 0 von 1.747 Zeilen tragen das Feld). '
 'unbestimmt = auch abgefragt_periode ist leer; das sind die drei Objekte aus '
 'fremden Wahlen, die einzeln nachgeladen wurden. '
 'geliefert kommt vor, falls die API das Feld eines Tages doch fuehrt UND '
 'bewusst entschieden wurde, es zu uebernehmen - bis dahin wird es nur '
 'protokolliert, nicht geschrieben.';
CREATE INDEX IF NOT EXISTS idx_constituency_number ON constituency (number);
CREATE INDEX IF NOT EXISTS idx_constituency_period ON constituency (parliament_period_id);
CREATE INDEX IF NOT EXISTS idx_constituency_geom   ON constituency USING GIST (geom);
"""


POLITICIAN_DDL = f"""
CREATE TABLE IF NOT EXISTS politician (
    aw_id               INTEGER PRIMARY KEY,
    first_name          TEXT,
    last_name           TEXT,
    birth_name          TEXT,
    sex                 TEXT,
    year_of_birth       INTEGER,
    title               TEXT,
    party_id            INTEGER,
    party_label         TEXT,
    education           TEXT,
    residence           TEXT,
    occupation          TEXT,
    questions_asked     INTEGER,
    questions_answered  INTEGER,








    qid_wikidata                TEXT,
    ext_id_bundestagsverwaltung TEXT,
    uri  TEXT GENERATED ALWAYS AS ('{URI_BASE}politician/' || aw_id::text) STORED,
    raw  JSONB,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE politician ADD COLUMN IF NOT EXISTS qid_wikidata TEXT;
ALTER TABLE politician ADD COLUMN IF NOT EXISTS ext_id_bundestagsverwaltung TEXT;
CREATE INDEX IF NOT EXISTS idx_politician_lastname ON politician (last_name);
CREATE INDEX IF NOT EXISTS idx_politician_party    ON politician (party_id);
CREATE INDEX IF NOT EXISTS idx_politician_wikidata ON politician (qid_wikidata);
CREATE INDEX IF NOT EXISTS idx_politician_extid    ON politician (ext_id_bundestagsverwaltung);
"""


MANDATE_DDL = f"""
CREATE TABLE IF NOT EXISTS candidacy_mandate (
    aw_id                     INTEGER PRIMARY KEY,
    type                      TEXT,
    politician_id             INTEGER,
    politician_label          TEXT,
    parliament_period_id      INTEGER,
    parliament_period_label   TEXT,
    party_id                  INTEGER,
    party_label               TEXT,
    start_date                DATE,
    end_date                  DATE,
    id_external_admin         TEXT,
    electoral_list_id         INTEGER,
    list_position             INTEGER,
    constituency_id           INTEGER,
    constituency_result       NUMERIC,
    constituency_result_count INTEGER,
    mandate_won               TEXT,
    fraction_id               INTEGER,
    fraction_label            TEXT,






    wkr_nr                    SMALLINT,
    wkr_wahljahr              SMALLINT,
    wkr_herkunft              TEXT,
    uri  TEXT GENERATED ALWAYS AS ('{URI_BASE}mandate/' || aw_id::text) STORED,
    raw  JSONB,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE candidacy_mandate ADD COLUMN IF NOT EXISTS wkr_nr       SMALLINT;
ALTER TABLE candidacy_mandate ADD COLUMN IF NOT EXISTS wkr_wahljahr SMALLINT;
ALTER TABLE candidacy_mandate ADD COLUMN IF NOT EXISTS wkr_herkunft TEXT;
CREATE INDEX IF NOT EXISTS idx_mandate_wkr ON candidacy_mandate (wkr_wahljahr, wkr_nr);
CREATE INDEX IF NOT EXISTS idx_mandate_politician   ON candidacy_mandate (politician_id);
CREATE INDEX IF NOT EXISTS idx_mandate_constituency ON candidacy_mandate (constituency_id);
CREATE INDEX IF NOT EXISTS idx_mandate_period       ON candidacy_mandate (parliament_period_id);
"""


SIDEJOB_DDL = f"""
CREATE TABLE IF NOT EXISTS sidejob (
    aw_id              INTEGER PRIMARY KEY,
    label              TEXT,
    income_level       TEXT,
    job_interval       TEXT,
    created            DATE,
    organization_id    INTEGER,
    organization_label TEXT,
    city_id            INTEGER,
    city_label         TEXT,
    country_id         INTEGER,
    country_label      TEXT,
    mandate_id         INTEGER,
    uri  TEXT GENERATED ALWAYS AS ('{URI_BASE}sidejob/' || aw_id::text) STORED,
    raw  JSONB,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sidejob_org     ON sidejob (organization_id);
CREATE INDEX IF NOT EXISTS idx_sidejob_mandate ON sidejob (mandate_id);
"""


def setup_db(conn):
    with conn.cursor() as cur:


        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";')
        cur.execute(f'SET search_path TO "{DB_SCHEMA}", public;')
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
        for t in RAW_TABLES:
            cur.execute(RAW_DDL.format(t=t))
        cur.execute(FETCH_STATE_DDL)
        cur.execute(CONSTITUENCY_DDL)
        cur.execute(POLITICIAN_DDL)
        cur.execute(MANDATE_DDL)
        cur.execute(SIDEJOB_DDL)
    conn.commit()
    log.info('Schema "%s" angelegt / geprüft.', DB_SCHEMA)


def upsert_raw(conn, table, rows, periode=None):
    values = [(r["id"], r.get("label"), Json(r), periode) for r in rows]
    sql = f"""
        INSERT INTO {table} (id, label, data, abgefragt_periode) VALUES %s
        ON CONFLICT (id) DO UPDATE SET
            label             = EXCLUDED.label,
            data              = EXCLUDED.data,
            abgefragt_periode = COALESCE(EXCLUDED.abgefragt_periode,
                                         {table}.abgefragt_periode),
            fetched_at        = now();
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, values)
    conn.commit()


FEHLENDE = []


def bereits_geladen(conn, scope):
    if not RESUME:
        return set()
    with conn.cursor() as cur:
        cur.execute("SELECT item_id FROM fetch_state WHERE scope = %s;", (scope,))
        return {r[0] for r in cur.fetchall()}


def merke_geladen(conn, scope, item_id):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO fetch_state (scope, item_id) VALUES (%s, %s)
            ON CONFLICT (scope, item_id) DO UPDATE SET fetched_at = now();
        """, (scope, item_id))
    conn.commit()


def sync_entity(api, conn, path, table, period_ids=None, extra=None,
                apply_test_limit=True, filter_name="parliament_period"):
    total = 0
    limit = TEST_LIMIT if apply_test_limit else None

    def run(params, periode=None):
        nonlocal total
        for batch in batched(api.fetch_all(path, extra_params=params, limit=limit), DB_BATCH):
            upsert_raw(conn, table, batch, periode)
            total += len(batch)

    if period_ids:
        fehler_in_folge = 0
        for i, pid in enumerate(period_ids):
            params = {filter_name: pid}
            if extra:
                params.update(extra)
            log.info("%s: Wahlperiode %s", path, pid)


            try:
                run(params, pid)
                fehler_in_folge = 0
            except requests.HTTPError as e:
                grund = str(e).split(" for url")[0]
                FEHLENDE.append((path, f"Wahlperiode {pid}", grund))
                log.error("%s, Wahlperiode %s: %s - übersprungen.",
                          path, pid, grund)
                fehler_in_folge += 1


                if fehler_in_folge >= ABBRUCH_NACH_FEHLERN:
                    rest = period_ids[i + 1:]
                    for p in rest:
                        FEHLENDE.append((path, f"Wahlperiode {p}",
                                         "nicht versucht, Endpunkt lieferte " "durchgehend Fehler"))
                    log.error("%s: %d Perioden in Folge fehlgeschlagen - die " "restlichen %d werden nicht mehr versucht.",
                              path, fehler_in_folge, len(rest))
                    break
    else:
        try:
            run(extra)
        except requests.HTTPError as e:
            grund = str(e).split(" for url")[0]
            FEHLENDE.append((path, "ohne Periodenfilter", grund))
            log.error("%s: %s - übersprungen.", path, grund)

    log.info("%s -> %s: %d Datensätze", path, table, total)
    return total


def load_clean_constituencies(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id, label FROM raw_parliament_periods;")
        perioden = dict(cur.fetchall())
        cur.execute("SELECT data, abgefragt_periode FROM raw_constituencies;")
        raw = cur.fetchall()

    records = []
    unerwartet = []
    for obj, periode in raw:
        pp = obj.get("parliament_period") or {}
        if pp.get("id") is not None:
            unerwartet.append((obj["id"], pp.get("id"), periode))


        records.append((
            obj["id"],
            obj.get("number"),
            obj.get("name") or obj.get("label"),
            periode,
            perioden.get(periode),


            "abgeleitet" if periode is not None else "unbestimmt",
            Json(obj),
        ))

    if unerwartet:
        log.warning(
            "Die API liefert bei %d von %d Wahlkreisen jetzt doch ein " "parliament_period. Geschrieben wird weiterhin abgefragt_periode. " "Erste Faelle (aw_id, api, abgefragt): %s",
            len(unerwartet), len(raw), unerwartet[:5])

    if not records:
        log.info("Keine Wahlkreise im Roh-Layer gefunden.")
        return

    sql = """
        INSERT INTO constituency
            (aw_id, number, name, parliament_period_id, parliament_period_label,
             parliament_period_herkunft, raw)
        VALUES %s
        ON CONFLICT (aw_id) DO UPDATE SET
            number                     = EXCLUDED.number,
            name                       = EXCLUDED.name,
            parliament_period_id       = EXCLUDED.parliament_period_id,
            parliament_period_label    = EXCLUDED.parliament_period_label,
            parliament_period_herkunft = EXCLUDED.parliament_period_herkunft,
            raw                        = EXCLUDED.raw,
            fetched_at                 = now();
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, records)
    conn.commit()
    log.info("Clean-Layer: %d Wahlkreis-Versionen geschrieben.", len(records))


def load_clean_politicians(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM raw_politicians;")
        raw = cur.fetchall()

    records = []
    for (obj,) in raw:
        party = obj.get("party") or {}
        records.append((
            obj["id"],
            obj.get("first_name"),
            obj.get("last_name"),
            obj.get("birth_name"),
            obj.get("sex"),
            obj.get("year_of_birth"),
            obj.get("field_title"),
            party.get("id"),
            party.get("label"),
            obj.get("education"),
            obj.get("residence"),
            obj.get("occupation"),
            obj.get("statistic_questions"),
            obj.get("statistic_questions_answered"),
            obj.get("qid_wikidata"),
            obj.get("ext_id_bundestagsverwaltung"),
            Json(obj),
        ))

    if not records:
        log.info("Keine Politiker:innen im Roh-Layer gefunden.")
        return

    sql = """
        INSERT INTO politician
            (aw_id, first_name, last_name, birth_name, sex, year_of_birth, title,
             party_id, party_label, education, residence, occupation,
             questions_asked, questions_answered,
             qid_wikidata, ext_id_bundestagsverwaltung, raw)
        VALUES %s
        ON CONFLICT (aw_id) DO UPDATE SET
            first_name         = EXCLUDED.first_name,
            last_name          = EXCLUDED.last_name,
            birth_name         = EXCLUDED.birth_name,
            sex                = EXCLUDED.sex,
            year_of_birth      = EXCLUDED.year_of_birth,
            title              = EXCLUDED.title,
            party_id           = EXCLUDED.party_id,
            party_label        = EXCLUDED.party_label,
            education          = EXCLUDED.education,
            residence          = EXCLUDED.residence,
            occupation         = EXCLUDED.occupation,
            questions_asked    = EXCLUDED.questions_asked,
            questions_answered = EXCLUDED.questions_answered,
            qid_wikidata       = EXCLUDED.qid_wikidata,
            ext_id_bundestagsverwaltung = EXCLUDED.ext_id_bundestagsverwaltung,
            raw                = EXCLUDED.raw,
            fetched_at         = now();
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, records)
    conn.commit()
    log.info("Clean-Layer: %d Politiker:innen geschrieben.", len(records))


def sync_votes_via_polls(api, conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM raw_polls;")
        poll_ids = [r[0] for r in cur.fetchall()]

    if TEST_LIMIT is not None:
        poll_ids = poll_ids[:TEST_LIMIT]

    if not poll_ids:
        log.info("Keine Polls vorhanden - überspringe votes.")
        return

    fertig = bereits_geladen(conn, "poll_votes")
    offen = [p for p in poll_ids if p not in fertig]
    log.info("votes: %d Abstimmungen, davon %d schon geladen, %d offen.",
             len(poll_ids), len(poll_ids) - len(offen), len(offen))

    total = 0
    for i, pid in enumerate(offen, 1):
        try:
            payload = api._get(f"polls/{pid}", {"related_data": "votes"})
        except requests.HTTPError as e:


            grund = str(e).split(" for url")[0]
            FEHLENDE.append(("votes", f"Abstimmung {pid}", grund))
            log.error("votes, Abstimmung %s: %s - übersprungen.", pid, grund)
            continue
        poll = payload.get("data", {}) or {}

        votes = (poll.get("related_data", {}) or {}).get("votes")
        if votes is None:
            votes = poll.get("votes", [])
        if votes:
            upsert_raw(conn, "raw_votes", votes)
            total += len(votes)


        merke_geladen(conn, "poll_votes", pid)
        if i % 25 == 0:
            log.info("  votes: %d/%d Abstimmungen", i, len(offen))
    log.info("votes -> raw_votes: %d Stimmen aus %d neu abgefragten Abstimmungen",
             total, len(offen))


def sync_committee_memberships(api, conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM raw_committees;")
        committee_ids = [r[0] for r in cur.fetchall()]

    if TEST_LIMIT is not None:
        committee_ids = committee_ids[:TEST_LIMIT]

    if not committee_ids:
        log.info("Keine Ausschüsse vorhanden - überspringe committee-memberships.")
        return

    fertig = bereits_geladen(conn, "committee_memberships")
    offen = [c for c in committee_ids if c not in fertig]
    log.info("committee-memberships: %d Ausschüsse, davon %d schon geladen, " "%d offen.", len(committee_ids), len(committee_ids) - len(offen),
             len(offen))

    total = 0
    for cid in offen:
        try:
            for batch in batched(api.fetch_all("committee-memberships",
                                               extra_params={"committee": cid},
                                               limit=TEST_LIMIT), DB_BATCH):
                upsert_raw(conn, "raw_committee_memberships", batch)
                total += len(batch)
        except requests.HTTPError as e:
            grund = str(e).split(" for url")[0]
            FEHLENDE.append(("committee-memberships", f"Ausschuss {cid}", grund))
            log.error("committee-memberships, Ausschuss %s: %s - übersprungen.",
                      cid, grund)
            continue
        merke_geladen(conn, "committee_memberships", cid)
    log.info("committee-memberships -> raw_committee_memberships: %d aus %d " "neu abgefragten Ausschüssen", total, len(offen))


ID_IN_BATCH = 100


def sync_politicians_gezielt(api, conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT (data -> 'politician' ->> 'id')::int AS pid
            FROM raw_candidacies_mandates
            WHERE data -> 'politician' ->> 'id' IS NOT NULL
            ORDER BY 1;
        """)
        ids = [r[0] for r in cur.fetchall()]

    if not ids:
        log.warning("Keine Politiker-Ids in den Mandaten - nichts zu laden.")
        return 0

    stapel = [ids[i:i + ID_IN_BATCH] for i in range(0, len(ids), ID_IN_BATCH)]
    log.info("politicians: %d Personen aus den Mandaten, %d Stapel à max. %d",
             len(ids), len(stapel), ID_IN_BATCH)

    total = 0
    for i, teil in enumerate(stapel, 1):
        wert = "[" + ",".join(str(x) for x in teil) + "]"
        try:
            payload = api._get("politicians",
                               {"id[in]": wert, "pager_limit": ID_IN_BATCH})
        except requests.HTTPError as e:
            grund = str(e).split(" for url")[0]
            FEHLENDE.append(("politicians", f"Stapel {i}", grund))
            log.error("politicians, Stapel %d: %s - übersprungen.", i, grund)
            continue
        daten = payload.get("data", []) or []
        if daten:
            upsert_raw(conn, "raw_politicians", daten)
            total += len(daten)
        if len(daten) != len(teil):


            FEHLENDE.append(("politicians", f"Stapel {i}",
                             f"{len(daten)} von {len(teil)} geliefert"))
            log.warning("politicians, Stapel %d: nur %d von %d geliefert.",
                        i, len(daten), len(teil))
        if i % 10 == 0:
            log.info("  politicians: %d/%d Stapel", i, len(stapel))

    log.info("politicians -> raw_politicians: %d von %d angeforderten Personen",
             total, len(ids))
    return total


def _park_ids(conn, quelle, ids):
    ziel = PARK_TABLES[quelle]
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH verschoben AS (
                DELETE FROM {quelle} WHERE id = ANY(%s)
                RETURNING id, label, data, fetched_at
            )
            INSERT INTO {ziel} (id, label, data, fetched_at)
            SELECT id, label, data, fetched_at FROM verschoben
            ON CONFLICT (id) DO UPDATE SET
                label      = EXCLUDED.label,
                data       = EXCLUDED.data,
                fetched_at = EXCLUDED.fetched_at;
        """, (list(ids),))
        n = cur.rowcount
    conn.commit()
    return n


def _mandat_ids(bezug):
    if isinstance(bezug, dict):
        bezug = [bezug]
    if not isinstance(bezug, list):
        return set()
    out = set()
    for e in bezug:
        if isinstance(e, dict) and e.get("id") is not None:
            try:
                out.add(int(e["id"]))
            except (TypeError, ValueError):
                pass
    return out


def parke_fremdparlamente(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw_candidacies_mandates;")
        n_mandate = cur.fetchone()[0]
    if n_mandate == 0:
        log.warning("raw_candidacies_mandates ist leer - ohne Mandate lässt " "sich kein Bundestagsbezug prüfen. Parken übersprungen.")
        return


    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw_politicians;")
        gesamt = cur.fetchone()[0]
        cur.execute("""
            SELECT p.id FROM raw_politicians p
            WHERE NOT EXISTS (
                SELECT 1 FROM raw_candidacies_mandates m
                WHERE (m.data -> 'politician' ->> 'id')::int = p.id
            );
        """)
        fremd = [r[0] for r in cur.fetchall()]

    if gesamt and len(fremd) == gesamt:
        log.warning("Alle %d Politiker:innen hätten keinen Mandatsbezug - das " "ist unplausibel. Parken übersprungen, bitte " "raw_candidacies_mandates prüfen.", gesamt)
    elif fremd:
        n = _park_ids(conn, "raw_politicians", fremd)
        log.info("Politiker:innen: %d von %d ohne Bundestags-Mandat -> %s",
                 n, gesamt, PARK_TABLES["raw_politicians"])
    else:
        log.info("Politiker:innen: alle %d haben einen Bundestags-Mandatsbezug.",
                 gesamt)


    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*)                                        AS gesamt,
                   count(*) FILTER (WHERE data ? 'mandates')       AS k_mandates,
                   count(*) FILTER (WHERE data ? 'candidacy_mandate') AS k_cm,
                   count(*) FILTER (WHERE data ? 'mandate')        AS k_mandate
            FROM raw_sidejobs;
        """)
        gesamt, k_mandates, k_cm, k_mandate = cur.fetchone()
    log.info("Nebentätigkeiten: %d Zeilen, Mandats-Schlüssel vorhanden bei " "mandates=%d, candidacy_mandate=%d, mandate=%d",
             gesamt, k_mandates, k_cm, k_mandate)

    if gesamt == 0:
        return
    if k_mandates == k_cm == k_mandate == 0:
        log.warning("Keine der drei Schreibweisen kommt vor - der Mandatsbezug " "der Nebentätigkeiten heißt anders. Parken übersprungen, " "bitte SELECT data FROM raw_sidejobs LIMIT 1 ansehen.")
        return

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM raw_candidacies_mandates;")
        mandat_ids = {r[0] for r in cur.fetchall()}
        cur.execute("""
            SELECT id, COALESCE(data -> 'mandates',
                                data -> 'candidacy_mandate',
                                data -> 'mandate') AS bezug
            FROM raw_sidejobs;
        """)
        zeilen = cur.fetchall()

    fremd, ohne_bezug = [], 0
    for sid, bezug in zeilen:
        ids = _mandat_ids(bezug)
        if not ids:
            ohne_bezug += 1
        if not (ids & mandat_ids):
            fremd.append(sid)

    if ohne_bezug:
        log.info("Nebentätigkeiten: %d Zeilen ohne auslesbare Mandats-ID.",
                 ohne_bezug)

    if len(fremd) == gesamt:
        log.warning("Alle %d Nebentätigkeiten hätten keinen Bezug zu den " "geladenen Mandaten - unplausibel. Parken übersprungen.",
                    gesamt)
    elif fremd:
        n = _park_ids(conn, "raw_sidejobs", fremd)
        log.info("Nebentätigkeiten: %d von %d ohne Bundestags-Mandat -> %s",
                 n, gesamt, PARK_TABLES["raw_sidejobs"])
    else:
        log.info("Nebentätigkeiten: alle %d haben einen Bundestags-Mandatsbezug.",
                 gesamt)


def _ref(obj, *keys):
    for k in keys:
        v = obj.get(k)
        if isinstance(v, dict):
            return v
    return {}


def _first_ref(obj, *keys):
    for k in keys:
        v = obj.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v[0]
        if isinstance(v, dict):
            return v
    return {}


def _date(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc).date()
    return v


def load_clean_mandates(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM raw_candidacies_mandates;")
        raw = cur.fetchall()

    records = []
    for (obj,) in raw:
        pol   = _ref(obj, "politician")
        pp    = _ref(obj, "parliament_period")
        party = _ref(obj, "party")
        ed    = obj.get("electoral_data") or {}
        el    = _ref(ed, "electoral_list")
        con   = _ref(ed, "constituency")
        fms   = obj.get("fraction_membership") or []
        fr    = _ref(fms[0], "fraction") if fms else {}

        records.append((
            obj["id"],
            obj.get("type"),
            pol.get("id"), pol.get("label"),
            pp.get("id"), pp.get("label"),
            party.get("id"), party.get("label"),
            _date(obj.get("start_date")),
            _date(obj.get("end_date")),
            obj.get("id_external_administration"),
            el.get("id"),
            ed.get("list_position"),
            con.get("id"),
            ed.get("constituency_result"),
            ed.get("constituency_result_count"),
            ed.get("mandate_won"),
            fr.get("id"), fr.get("label"),
            Json(obj),
        ))

    if not records:
        log.info("Keine Mandate/Kandidaturen im Roh-Layer gefunden.")
        return

    sql = """
        INSERT INTO candidacy_mandate
            (aw_id, type, politician_id, politician_label,
             parliament_period_id, parliament_period_label, party_id, party_label,
             start_date, end_date, id_external_admin,
             electoral_list_id, list_position, constituency_id,
             constituency_result, constituency_result_count, mandate_won,
             fraction_id, fraction_label, raw)
        VALUES %s
        ON CONFLICT (aw_id) DO UPDATE SET
            type                      = EXCLUDED.type,
            politician_id             = EXCLUDED.politician_id,
            politician_label          = EXCLUDED.politician_label,
            parliament_period_id      = EXCLUDED.parliament_period_id,
            parliament_period_label   = EXCLUDED.parliament_period_label,
            party_id                  = EXCLUDED.party_id,
            party_label               = EXCLUDED.party_label,
            start_date                = EXCLUDED.start_date,
            end_date                  = EXCLUDED.end_date,
            id_external_admin         = EXCLUDED.id_external_admin,
            electoral_list_id         = EXCLUDED.electoral_list_id,
            list_position             = EXCLUDED.list_position,
            constituency_id           = EXCLUDED.constituency_id,
            constituency_result       = EXCLUDED.constituency_result,
            constituency_result_count = EXCLUDED.constituency_result_count,
            mandate_won               = EXCLUDED.mandate_won,
            fraction_id               = EXCLUDED.fraction_id,
            fraction_label            = EXCLUDED.fraction_label,
            raw                       = EXCLUDED.raw,
            fetched_at                = now();
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, records)
    conn.commit()
    log.info("Clean-Layer: %d Mandate/Kandidaturen geschrieben.", len(records))


PERIODE_WAHLJAHR_SQL = """
    SELECT id,
           CASE WHEN data ->> 'type' = 'election'
                THEN left(data ->> 'election_date', 4)::int
                ELSE left(data ->> 'start_date_period', 4)::int END AS wahljahr
      FROM raw_parliament_periods
     WHERE coalesce(data ->> 'election_date', data ->> 'start_date_period') IS NOT NULL
"""


def setze_wahlkreisnummer(conn):
    with conn.cursor() as cur:

        cur.execute(f"""
            WITH periode_jahr AS ({PERIODE_WAHLJAHR_SQL})
            UPDATE candidacy_mandate m
               SET wkr_nr       = c.number,
                   wkr_wahljahr = pj.wahljahr,
                   wkr_herkunft = 'geliefert'
              FROM constituency c, periode_jahr pj
             WHERE c.aw_id = m.constituency_id
               AND pj.id   = m.parliament_period_id
               AND c.number IS NOT NULL;""")
        geliefert = cur.rowcount


        cur.execute(f"""
            WITH periode_jahr AS ({PERIODE_WAHLJAHR_SQL}),
                 kandidatur AS (
                     SELECT k.politician_id, pj.wahljahr,
                            min(c.number) AS number
                       FROM candidacy_mandate k
                       JOIN periode_jahr pj ON pj.id = k.parliament_period_id
                       JOIN constituency  c ON c.aw_id = k.constituency_id
                      WHERE k.type = 'candidacy' AND c.number IS NOT NULL
                      GROUP BY 1, 2
                     HAVING count(DISTINCT c.number) = 1)
            UPDATE candidacy_mandate m
               SET wkr_nr       = ka.number,
                   wkr_wahljahr = ka.wahljahr,
                   wkr_herkunft = 'abgeleitet'
              FROM periode_jahr pj, kandidatur ka
             WHERE pj.id = m.parliament_period_id
               AND ka.politician_id = m.politician_id
               AND ka.wahljahr = pj.wahljahr
               AND m.type = 'mandate'
               AND m.wkr_nr IS NULL;""")
        abgeleitet = cur.rowcount


        cur.execute("""UPDATE candidacy_mandate
                          SET wkr_herkunft = 'ohne'
                        WHERE wkr_nr IS NULL;""")
        ohne = cur.rowcount


        cur.execute(f"""
            WITH periode_jahr AS ({PERIODE_WAHLJAHR_SQL})
            SELECT count(*) FROM (
                SELECT k.politician_id, pj.wahljahr
                  FROM candidacy_mandate k
                  JOIN periode_jahr pj ON pj.id = k.parliament_period_id
                  JOIN constituency  c ON c.aw_id = k.constituency_id
                 WHERE k.type = 'candidacy'
                 GROUP BY 1, 2 HAVING count(DISTINCT c.number) > 1) x;""")
        mehrdeutig = cur.fetchone()[0]
    conn.commit()

    log.info("Wahlkreisnummer gesetzt: %d geliefert, %d abgeleitet, %d ohne",
             geliefert, abgeleitet, ohne)
    if mehrdeutig:
        log.warning("%d Person-Wahljahr-Paare haben mehrere Wahlkreise - dort " "wurde NICHTS abgeleitet.", mehrdeutig)
    return geliefert, abgeleitet, ohne


def pruefe_wahlkreisnummer(conn):
    print("\n  Wahlkreisnummer (Eingriff E1)")
    with conn.cursor() as cur:
        cur.execute("""SELECT coalesce(wkr_herkunft,'(nicht gesetzt)'), count(*)
                         FROM candidacy_mandate GROUP BY 1 ORDER BY 2 DESC;""")
        for h, n in cur.fetchall():
            print(f"    {h:<16} {n:>6}")


        cur.execute("""SELECT count(*) FROM candidacy_mandate
                        WHERE type='mandate' AND mandate_won='constituency'
                          AND wkr_nr IS NULL;""")
        a = cur.fetchone()[0]
        print(f"    Direktgewaehlte ohne Nummer          {a:>6}"
              + ("   <-- unmoeglich, pruefen" if a else ""))


        cur.execute("""SELECT count(*) FROM candidacy_mandate m
                        WHERE m.wkr_nr IS NOT NULL
                          AND NOT EXISTS (SELECT 1 FROM raum.wahlkreis w
                                          WHERE w.wahljahr = m.wkr_wahljahr
                                            AND w.wkr_nr   = m.wkr_nr);""")
        b = cur.fetchone()[0]
        print(f"    Nummern ohne Wahlkreis in raum       {b:>6}"
              + ("   <-- zeigt ins Leere" if b else ""))


        cur.execute("""SELECT count(*) FROM candidacy_mandate m
                        JOIN constituency c ON c.aw_id = m.constituency_id
                       WHERE m.wkr_herkunft = 'geliefert'
                         AND c.parliament_period_id IS DISTINCT FROM
                             m.parliament_period_id;""")
        d = cur.fetchone()[0]
        print(f"    Nummer aus einer fremden Wahl        {d:>6}"
              + ("   <--" if d else ""))


def load_clean_sidejobs(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT data FROM raw_sidejobs;")
        raw = cur.fetchall()

    records = []
    for (obj,) in raw:
        org     = _ref(obj, "sidejob_organization")
        city    = _ref(obj, "city", "field_city")
        country = _ref(obj, "country", "field_country")
        mandate = _first_ref(obj, "mandates", "candidacy_mandate", "mandate")

        records.append((
            obj["id"],
            obj.get("label"),
            obj.get("income_level"),
            obj.get("interval"),
            _date(obj.get("created")),
            org.get("id"), org.get("label"),
            city.get("id"), city.get("label"),
            country.get("id"), country.get("label"),
            mandate.get("id"),
            Json(obj),
        ))

    if not records:
        log.info("Keine Nebentätigkeiten im Roh-Layer gefunden.")
        return

    sql = """
        INSERT INTO sidejob
            (aw_id, label, income_level, job_interval, created,
             organization_id, organization_label, city_id, city_label,
             country_id, country_label, mandate_id, raw)
        VALUES %s
        ON CONFLICT (aw_id) DO UPDATE SET
            label              = EXCLUDED.label,
            income_level       = EXCLUDED.income_level,
            job_interval       = EXCLUDED.job_interval,
            created            = EXCLUDED.created,
            organization_id    = EXCLUDED.organization_id,
            organization_label = EXCLUDED.organization_label,
            city_id            = EXCLUDED.city_id,
            city_label         = EXCLUDED.city_label,
            country_id         = EXCLUDED.country_id,
            country_label      = EXCLUDED.country_label,
            mandate_id         = EXCLUDED.mandate_id,
            raw                = EXCLUDED.raw,
            fetched_at         = now();
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, records)
    conn.commit()
    log.info("Clean-Layer: %d Nebentätigkeiten geschrieben.", len(records))


def _gezogene_endpunkte():
    wie = {p: "vollständig (alle Parlamente)" for (p, _) in FULL_ENTITIES}
    wie.update({p: f"je Wahlperiode (Filter {f})" for (p, _, f, _e) in PERIOD_ENTITIES})
    wie["parliament-periods"]   = "gefiltert auf Bundestag"
    wie["politicians"]          = "vollständig, danach Fremdparlamente geparkt"
    wie["committee-memberships"] = "eine Anfrage je Ausschuss"
    wie["votes"]                = "eingebettet über polls/{id}?related_data=votes"
    return wie


def pruefe_endpunkte(api):
    try:
        payload = api._get("", {})
    except Exception as e:
        log.warning("Endpunktliste nicht abrufbar (%s) - " "Abdeckungsprüfung übersprungen.", e)
        return

    daten = payload.get("data", payload) if isinstance(payload, dict) else payload
    verfuegbar = set()
    if isinstance(daten, dict):
        verfuegbar = set(daten.keys())
    elif isinstance(daten, list):
        for e in daten:
            if isinstance(e, str):
                verfuegbar.add(e.rstrip("/").rsplit("/", 1)[-1])
            elif isinstance(e, dict):
                url = e.get("api_url") or e.get("url") or ""
                name = url.rstrip("/").rsplit("/", 1)[-1] if url else e.get("label")
                if name:
                    verfuegbar.add(name)

    if not verfuegbar:
        log.warning("Struktur der Endpunktliste nicht erkannt. Rohantwort: %s",
                    str(payload)[:600])
        return

    wie = _gezogene_endpunkte()
    print()
    print("Abdeckung der API-Endpunkte")
    print("-" * 74)
    for name in sorted(verfuegbar):
        if name in wie:
            print(f"  [x] {name:<26} {wie[name]}")
        else:
            print(f"  [ ] {name:<26} wird NICHT geladen")
    unbekannt = sorted(set(wie) - verfuegbar)
    if unbekannt:
        print(f"  im Skript, aber nicht in der Endpunktliste: {', '.join(unbekannt)}")
    print(f"  {len(verfuegbar & set(wie))} von {len(verfuegbar)} Endpunkten "
          f"werden geladen.")
    print()


def vorschau(api, conn, period_ids):
    zeilen = []
    kosten = 0

    def zaehle(path, extra=None):
        nonlocal kosten
        kosten += 1
        return api.total_count(path, extra)

    def seiten(total):
        return max(1, math.ceil((total or 0) / PAGE_SIZE))

    for path, _ in FULL_ENTITIES:
        total = zaehle(path)
        zeilen.append((path, total, seiten(total), "alle Parlamente"))

    perioden = period_ids or []
    n_polls = n_committees = n_mandate = 0
    for path, _, filter_name, extra_p in PERIOD_ENTITIES:
        summe = anfragen = 0
        for pid in (perioden or [None]):
            total = zaehle(path, {**(extra_p or {}), filter_name: pid} if pid else None)
            summe += total or 0
            anfragen += seiten(total)
        zeilen.append((path, summe, anfragen,
                       f"{len(perioden) or 1} Wahlperiode(n)"))
        if path == "polls":
            n_polls = summe
        elif path == "committees":
            n_committees = summe
        elif path == "candidacies-mandates":
            n_mandate = summe


    zeilen.append(("politicians", None, math.ceil(n_mandate / ID_IN_BATCH),
                   f"gezielt, hoechstens {n_mandate} Personen, "
                   f"{ID_IN_BATCH} je Anfrage"))

    fertig_v = len(bereits_geladen(conn, "poll_votes"))
    fertig_c = len(bereits_geladen(conn, "committee_memberships"))
    zeilen.append(("votes", None, max(0, n_polls - fertig_v),
                   f"1 Anfrage je Abstimmung, {fertig_v} erledigt"))
    zeilen.append(("committee-memberships", None, max(0, n_committees - fertig_c),
                   f"mind. 1 je Ausschuss, {fertig_c} erledigt"))


    api._get("politicians", {"page": 0, "pager_limit": PAGE_SIZE})
    kosten += 1
    antwortzeit = api.letzte_dauer
    abstand = 60.0 / MAX_CALLS_PER_MIN


    pro_anfrage = max(abstand, antwortzeit)

    breite = max(len(z[0]) for z in zeilen)
    gesamt = sum(z[2] for z in zeilen)
    minuten = gesamt * pro_anfrage / 60.0

    print()
    print(f"Vorschau Vollabzug - Wahljahre {ELECTION_YEARS}, "
          f"{len(perioden)} aufgelöste Perioden")
    print("-" * (breite + 48))
    print(f"{'Endpunkt':<{breite}}  {'Datensaetze':>12}  {'Anfragen':>9}  Bemerkung")
    for name, total, anfragen, bem in zeilen:
        t = f"{total:,}".replace(",", ".") if total is not None else "-"
        print(f"{name:<{breite}}  {t:>12}  {anfragen:>9}  {bem}")
    print("-" * (breite + 48))
    print(f"{'Summe':<{breite}}  {'':>12}  {gesamt:>9}")
    print()
    print(f"  Mindestabstand beim Starttempo  : {abstand:.1f} s "
          f"({START_CALLS_PER_MIN} Anfragen/min)")
    print(f"  Gemessene Antwortzeit bei {PAGE_SIZE} Datensaetzen/Seite: "
          f"{antwortzeit:.1f} s")
    print(f"  Wirksam je Anfrage (der groessere Wert): {pro_anfrage:.1f} s")
    print(f"  -> Vollabzug hoechstens {minuten:.0f} min = {minuten / 60:.1f} h")
    if antwortzeit >= abstand:
        print("  Hinweis: die Antwortzeit liegt ueber dem Mindestabstand - " "nicht das Kontingent bremst, sondern die API. Ein hoeheres " "Tempo wuerde nichts aendern.")
    else:
        schnell = gesamt * max(60.0 / DECKEL_CALLS_PER_MIN, antwortzeit) / 60.0
        print(f"  Regelt sich das Tempo auf {DECKEL_CALLS_PER_MIN}/min hoch, "
              f"sind es {schnell:.0f} min = {schnell / 60:.1f} h.")
    print(f"  Die Vorschau selbst hat {kosten} Anfragen gekostet.")
    print()


NULL_CHECK = {
    "constituency": ["number", "name", "parliament_period_id"],
    "politician": ["first_name", "last_name", "sex", "year_of_birth", "title",
                   "party_id", "education", "residence", "occupation",
                   "questions_asked", "questions_answered",
                   "qid_wikidata", "ext_id_bundestagsverwaltung"],
    "candidacy_mandate": ["type", "politician_id", "parliament_period_id",
                          "party_id", "start_date", "end_date",
                          "id_external_admin", "electoral_list_id",
                          "list_position", "constituency_id",
                          "constituency_result", "constituency_result_count",
                          "mandate_won", "fraction_id"],
    "sidejob": ["label", "income_level", "job_interval", "created",
                "organization_id", "city_id", "country_id", "mandate_id"],
}


def pruefe_referenzen(conn):
    print("\n  Referenzen")
    kanten = [
        ("mandat -> politiker", "candidacy_mandate", "politician_id",
         "politician", "aw_id"),
        ("mandat -> wahlkreis", "candidacy_mandate", "constituency_id",
         "constituency", "aw_id"),
        ("mandat -> partei", "candidacy_mandate", "party_id", "raw_parties", "id"),
        ("mandat -> landesliste", "candidacy_mandate", "electoral_list_id",
         "raw_electoral_lists", "id"),
        ("mandat -> fraktion", "candidacy_mandate", "fraction_id",
         "raw_fractions", "id"),
        ("nebentaetigkeit -> mandat", "sidejob", "mandate_id",
         "candidacy_mandate", "aw_id"),
    ]
    with conn.cursor() as cur:
        for name, tab, spalte, ziel, zielspalte in kanten:
            cur.execute(f"""SELECT count(*) FROM {tab} q WHERE q.{spalte} IS NOT NULL
                            AND NOT EXISTS (SELECT 1 FROM {ziel} z
                                            WHERE z.{zielspalte} = q.{spalte});""")
            n = cur.fetchone()[0]
            marke = "   <-- zeigt ins Leere" if n else ""
            print(f"    {name:<30} {n:>5}{marke}")


        for name, sql in [
            ("wahlkreis aus anderer Wahl", """
                SELECT count(*) FROM candidacy_mandate m
                JOIN constituency c ON c.aw_id = m.constituency_id
                WHERE c.parliament_period_id IS NOT NULL
                  AND c.parliament_period_id <> m.parliament_period_id"""),
            ("landesliste aus anderer Wahl", """
                SELECT count(*) FROM candidacy_mandate m
                JOIN raw_electoral_lists e ON e.id = m.electoral_list_id
                WHERE e.abgefragt_periode IS NOT NULL
                  AND e.abgefragt_periode <> m.parliament_period_id"""),


            ("wahlkreis ohne Wahlperiode", """
                SELECT count(*) FROM candidacy_mandate m
                JOIN constituency c ON c.aw_id = m.constituency_id
                WHERE c.parliament_period_id IS NULL"""),
        ]:
            cur.execute(sql + ";")
            n = cur.fetchone()[0]
            marke = "   <-- nicht vergleichbar," if n else ""
            print(f"    {name:<30} {n:>5}{marke}")


def pruefe_bestand(conn):
    tabellen = RAW_TABLES + ["fetch_state", "constituency", "politician",
                             "candidacy_mandate", "sidejob"]
    breite = max(len(t) for t in tabellen)

    print()
    print("Bestand je Tabelle")
    print("-" * (breite + 14))
    with conn.cursor() as cur:
        for t in tabellen:
            cur.execute(f"SELECT count(*) FROM {t};")
            n = f"{cur.fetchone()[0]:,}".replace(",", ".")
            print(f"  {t:<{breite}}  {n:>10}")

    for tabelle, spalten in NULL_CHECK.items():
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {tabelle};")
            n = cur.fetchone()[0]
            if not n:
                continue
            cur.execute("SELECT " + ", ".join(f"count({s})" for s in spalten)
                        + f" FROM {tabelle};")
            gefuellt = cur.fetchone()
        print(f"\n  {tabelle} ({n} Zeilen) - Anteil NULL je Spalte:")
        for s, g in zip(spalten, gefuellt):
            marke = "   <-- komplett leer, Mapping pruefen" if g == 0 else ""
            print(f"    {s:<28} {100.0 * (n - g) / n:5.1f} %{marke}")

    pruefe_referenzen(conn)
    pruefe_wahlkreisnummer(conn)

    if FEHLENDE:
        print(f"\n  NICHT geladen ({len(FEHLENDE)} Faelle) - der Bestand ist "
              f"insoweit unvollstaendig:")
        for endpunkt, bezug, grund in FEHLENDE:
            print(f"    {endpunkt:<24} {bezug:<22} {grund}")
    else:
        print("\n  Keine uebersprungenen Abfragen.")
    print()


def main():
    limiter = RateLimiter(START_CALLS_PER_MIN)
    api = AbgeordnetenwatchAPI(limiter)
    conn = psycopg2.connect(DB_DSN)


    with conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{DB_SCHEMA}";')
    conn.commit()
    conn.cursor().execute(f'SET search_path TO "{DB_SCHEMA}", public;')
    conn.commit()
    try:
        setup_db(conn)


        if ENDPUNKT_CHECK:
            pruefe_endpunkte(api)


        sync_entity(api, conn, "parliament-periods", "raw_parliament_periods",
                    extra={"parliament": PARLIAMENT_ID}, apply_test_limit=False)


        period_ids = None
        if ELECTION_YEARS:
            period_ids = resolve_period_ids(conn, PARLIAMENT_ID, ELECTION_YEARS)
            log.info("Gefilterte Perioden-IDs (%s): %s", ELECTION_YEARS, period_ids)
            if not period_ids:
                log.warning("Keine passenden Perioden gefunden - ziehe ungefiltert.")


        if VORSCHAU_ONLY:
            vorschau(api, conn, period_ids)
            return


        for path, table in FULL_ENTITIES:
            sync_entity(api, conn, path, table)


        for path, table, filter_name, extra_p in PERIOD_ENTITIES:
            sync_entity(api, conn, path, table, period_ids, extra=extra_p,
                        filter_name=filter_name)
            log.info("Limiter: %s", limiter.bericht())


        sync_committee_memberships(api, conn)


        sync_votes_via_polls(api, conn)


        sync_politicians_gezielt(api, conn)
        log.info("Limiter: %s", limiter.bericht())


        if TEST_LIMIT is None:
            parke_fremdparlamente(conn)
        else:
            log.info("Test-Modus: Kontrolle auf Fremdparlamente übersprungen.")


        try:
            load_clean_constituencies(conn)
            load_clean_politicians(conn)
            load_clean_mandates(conn)


            setze_wahlkreisnummer(conn)
            load_clean_sidejobs(conn)
            log.info("Fertig.")
        finally:


            conn.rollback()
            pruefe_bestand(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
