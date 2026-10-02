import os
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
ENV = WURZEL / ".env"

_gelesen = False


def _lies_env():
    global _gelesen
    if _gelesen or not ENV.is_file():
        _gelesen = True
        return
    for zeile in ENV.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, wert = zeile.split("=", 1)
        schluessel, wert = schluessel.strip(), wert.strip().strip('"\'')
        os.environ.setdefault(schluessel, wert)
    _gelesen = True


def hole(schluessel, vorgabe=None):
    _lies_env()
    wert = os.environ.get(schluessel, vorgabe)
    if wert is None:
        raise SystemExit(
            f"Zugangsdatum fehlt: {schluessel}\n"
            f"In {ENV} eintragen oder als Umgebungsvariable setzen.\n"
            f"Welche Schluessel gebraucht werden, zeigt .env.beispiel.")
    return wert


def db_host():      return hole("SKG_DB_HOST", "localhost")
def db_port():      return hole("SKG_DB_PORT", "5432")
def db_name():      return hole("SKG_DB_NAME", "political_stKG")
def db_user():      return hole("SKG_DB_USER", "postgres")
def db_passwort():  return hole("SKG_DB_PASSWORT")


def dsn():
    return (f"host={db_host()} port={db_port()} dbname={db_name()} "
            f"user={db_user()} password={db_passwort()}")


def dip_schluessel():
    return hole("SKG_DIP_API_KEY")
