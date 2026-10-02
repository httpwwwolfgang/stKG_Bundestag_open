import os
import sys
import subprocess
import logging
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from zugang import db_host, db_port, db_name, db_user, db_passwort


DB_HOST     = db_host()
DB_PORT     = int(db_port())
DB_NAME     = db_name()
DB_USER     = db_user()
DB_PASSWORD = db_passwort()
DB_SCHEMA  = "raum"
ROH_SCHEMA = "roh_wahlkreise"


PG_BIN = Path("PFAD_ZU_POSTGRESQL_BIN")


DATEN  = Path(__file__).resolve().parents[3] / "Daten"
WK_DIR = DATEN / "Wahlkreise"
DATEN_DIR  = WK_DIR / "WK_Bundeswahlleiterin"
ARCHIV_DIR = WK_DIR / "archiv" / "Bundeswahlleiterin"


logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("skg")


def _pg_env():
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASSWORD

    env["PGCLIENTENCODING"] = "UTF8"
    return env


def _psql_args():
    return [
        str(PG_BIN / "psql.exe"),
        "-h", DB_HOST, "-p", str(DB_PORT),
        "-U", DB_USER, "-d", DB_NAME,
        "-v", "ON_ERROR_STOP=1",
        "--quiet",
    ]


def run_sql(sql, label=""):
    proc = subprocess.run(
        _psql_args() + ["-c", sql],
        env=_pg_env(), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        log.error("SQL fehlgeschlagen%s:\n%s", f" ({label})" if label else "", proc.stderr.strip())
        raise SystemExit(1)
    return proc.stdout


def run_sql_file(pfad, label=""):
    proc = subprocess.run(
        _psql_args() + ["-f", str(pfad)],
        env=_pg_env(), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        log.error("SQL-Datei fehlgeschlagen%s:\n%s",
                  f" ({label})" if label else "", proc.stderr.strip())
        raise SystemExit(1)
    return proc.stdout


def run_copy(sql, zieldatei, label=""):
    with Path(zieldatei).open("wb") as fh:
        proc = subprocess.run(
            _psql_args() + ["-c", f"COPY ({sql}) TO STDOUT WITH CSV HEADER"],
            env=_pg_env(), stdout=fh, stderr=subprocess.PIPE,
        )
    if proc.returncode != 0:
        log.error("COPY fehlgeschlagen%s:\n%s", f" ({label})" if label else "",
                  proc.stderr.decode("utf-8", "replace").strip())
        raise SystemExit(1)
    return Path(zieldatei).stat().st_size


def query(sql):
    proc = subprocess.run(
        _psql_args() + ["-t", "-A", "-F", "\t", "-c", sql],
        env=_pg_env(), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        log.error("Abfrage fehlgeschlagen:\n%s", proc.stderr.strip())
        raise SystemExit(1)
    return [tuple(line.split("\t")) for line in proc.stdout.splitlines() if line.strip()]


def dbf_encoding(shp_path):
    for suffix in (".cpg", ".CPG"):
        cpg = shp_path.with_suffix(suffix)
        if cpg.exists():
            raw = cpg.read_text(encoding="ascii", errors="replace").strip().upper()
            if "UTF" in raw:
                return "UTF-8"
            if any(k in raw for k in ("1252", "ANSI")):
                return "WINDOWS-1252"
            if any(k in raw for k in ("8859", "LATIN")):
                return "LATIN1"
            log.warning("Unbekannter .cpg-Inhalt %r bei %s - nehme WINDOWS-1252",
                        raw, shp_path.name)
            break
    return "WINDOWS-1252"


def shp2pgsql_to_db(shp_path, table, srid, encoding, schema=DB_SCHEMA):
    run_sql(f"DROP TABLE IF EXISTS {schema}.{table} CASCADE;", f"drop {table}")

    dump = subprocess.Popen(
        [
            str(PG_BIN / "shp2pgsql.exe"),
            "-s", str(srid),
            "-c", "-I",
            "-g", "geom",
            "-W", encoding,
            str(shp_path),
            f"{schema}.{table}",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_pg_env(),
    )
    load = subprocess.Popen(
        _psql_args(), stdin=dump.stdout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_pg_env(),
    )
    dump.stdout.close()
    _, load_err = load.communicate()
    dump.wait()
    dump_err = dump.stderr.read().decode("utf-8", "replace")
    dump.stderr.close()

    if dump.returncode != 0:
        log.error("shp2pgsql fehlgeschlagen (%s):\n%s", shp_path.name, dump_err.strip())
        raise SystemExit(1)
    if load.returncode != 0:
        log.error("psql-Import fehlgeschlagen (%s):\n%s", table,
                  load_err.decode("utf-8", "replace").strip())
        raise SystemExit(1)
