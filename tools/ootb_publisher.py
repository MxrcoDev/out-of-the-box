#!/usr/bin/env python3
"""
OOTB Publisher – crea articoli, comunicazioni ed eventi del calendario da remoto.

Non serve git né un clone del repository: parla direttamente con l'API di GitHub
(solo libreria standard di Python 3.8+, nessuna installazione) e fa UN commit atomico
su `main`. Il workflow GitHub genera poi la pagina HTML di articoli/comunicazioni.

Uso:
    python3 ootb_publisher.py
    python3 ootb_publisher.py --repo MxrcoDev/out-of-the-box --branch main

Autenticazione: il token GitHub viene chiesto all'avvio (input nascosto) oppure letto dalla
variabile d'ambiente GITHUB_TOKEN. Non viene mai salvato su disco né stampato.
  - Fine-grained token: repository "out-of-the-box" -> permesso "Contents: Read and write"
  - Token classico: scope "repo"
"""
import argparse
import base64
import datetime as dt
import getpass
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request

DEFAULT_REPO = "MxrcoDev/out-of-the-box"
DEFAULT_BRANCH = "main"
API = os.environ.get("OOTB_API_URL", "https://api.github.com").rstrip("/")

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})(?:\s*[-–—]\s*(\d{1,2})[:.](\d{2}))?$")

KINDS = {
    "articolo": {"json": "src/storage/articles.json", "page": "docs/articles/{id}.html"},
    "comunicazione": {"json": "src/storage/communications.json", "page": "docs/communications/{id}.html"},
}
EVENTS_JSON = "src/storage/activities.json"
MD_DIR = "docs/markdown/"
FILES_DIR = "docs/files/"


class Abort(Exception):
    pass


# ───────────────────────── GitHub API ─────────────────────────
class GitHub:
    def __init__(self, token, repo, branch):
        self.token, self.repo, self.branch = token, repo, branch

    def call(self, method, path, body=None):
        url = f"{API}/repos/{self.repo}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ootb-publisher",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = ""
            try:
                msg = json.loads(e.read().decode()).get("message", "")
            except Exception:
                pass
            hint = {
                401: "token non valido o scaduto",
                403: "il token non ha i permessi (serve Contents: Read and write) oppure rate limit",
                404: "repository o branch non trovato, oppure il token non ha accesso a questo repository",
                409: "conflitto: il branch è cambiato nel frattempo",
                422: "richiesta rifiutata da GitHub",
            }.get(e.code, "errore")
            raise Abort(f"GitHub {e.code} ({hint}){': ' + msg if msg else ''}") from None
        except urllib.error.URLError as e:
            raise Abort(f"Connessione a GitHub non riuscita: {e.reason}") from None

    def head(self):
        ref = self.call("GET", f"/git/ref/heads/{self.branch}")
        commit_sha = ref["object"]["sha"]
        commit = self.call("GET", f"/git/commits/{commit_sha}")
        tree = self.call("GET", f"/git/trees/{commit['tree']['sha']}?recursive=1")
        files = {t["path"]: t["sha"] for t in tree.get("tree", []) if t["type"] == "blob"}
        return commit_sha, commit["tree"]["sha"], files

    def read_text(self, sha):
        b = self.call("GET", f"/git/blobs/{sha}")
        return base64.b64decode(b["content"]).decode("utf-8")

    def commit(self, parent_sha, base_tree, changes, message):
        """changes: {path: bytes}. Un solo commit, aggiornamento non forzato del branch."""
        entries = []
        for path, content in changes.items():
            blob = self.call("POST", "/git/blobs", {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self.call("POST", "/git/trees", {"base_tree": base_tree, "tree": entries})
        c = self.call("POST", "/git/commits", {"message": message, "tree": tree["sha"], "parents": [parent_sha]})
        self.call("PATCH", f"/git/refs/heads/{self.branch}", {"sha": c["sha"], "force": False})
        return c["sha"]


# ───────────────────────── input ─────────────────────────
def ask(label, default=None, required=True, validate=None):
    while True:
        suffix = f" [{default}]" if default else ("" if required else " (invio per saltare)")
        v = input(f"{label}{suffix}: ").strip()
        if not v and default is not None:
            v = default
        if not v:
            if required:
                print("  ✖ campo obbligatorio")
                continue
            return None
        if validate:
            err = validate(v)
            if err:
                print(f"  ✖ {err}")
                continue
        return v


def yes(label, default=False):
    v = input(f"{label} [{'S/n' if default else 's/N'}]: ").strip().lower()
    return default if not v else v in ("s", "si", "sì", "y", "yes")


def v_id(v):
    return None if ID_RE.match(v) else "solo lettere, numeri, '-' e '_' (niente spazi)"


def v_date(v):
    try:
        dt.datetime.strptime(v, "%Y-%m-%d")
        return None
    except ValueError:
        return "formato AAAA-MM-GG, data valida"


def v_time(v):
    if re.match(r"^all[ -]?day$", v, re.I):
        return None
    m = TIME_RE.match(v)
    if not m:
        return 'usa "all day", "HH:MM" oppure "HH:MM-HH:MM"'
    h1, m1 = int(m[1]), int(m[2])
    if h1 > 23 or m1 > 59:
        return "orario non valido"
    if m[3]:
        h2, m2 = int(m[3]), int(m[4])
        if h2 > 23 or m2 > 59 or h2 * 60 + m2 <= h1 * 60 + m1:
            return "l'orario di fine deve essere dopo l'inizio"
    return None


def v_url(v):
    return None if re.match(r"^https?://\S+$", v, re.I) else "deve iniziare con http:// o https://"


def today():
    return dt.date.today().isoformat()


def read_multiline():
    print("Scrivi il testo in Markdown (solo il corpo). Termina con una riga contenente solo '.' (punto).")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def slug_filename(name):
    base = os.path.basename(name.replace("\\", "/"))
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.")
    return base


def expand(path):
    return os.path.abspath(os.path.expanduser(path.strip().strip('"').strip("'")))


# ───────────────────────── creazione ─────────────────────────
def load_json_list(gh, files, path):
    sha = files.get(path)
    if not sha:
        return []
    raw = gh.read_text(sha).lstrip("﻿").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if not isinstance(data, list):
        raise Abort(f"{path} non contiene un array")
    return data


def dump_json(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def create_post(gh, kind):
    cfg = KINDS[kind]
    commit_sha, base_tree, files = gh.head()
    entries = load_json_list(gh, files, cfg["json"])
    used = {e.get("id") for e in entries if isinstance(e, dict)}

    print(f"\n── Nuovo {kind} ──")
    pid = ask("ID (nome del file della pagina, es. festa-di-istituto)", validate=lambda v: v_id(v) or ("ID già usato" if v in used else None))
    title = ask("Titolo")
    subtitle = ask("Sottotitolo", required=False)
    author = ask("Autore")
    date = ask("Data", default=today(), validate=v_date)

    changes = {}
    # corpo markdown
    if yes("Vuoi usare un file .md che hai sul dispositivo (invece di scrivere qui)?", False):
        while True:
            p = expand(ask("Percorso del file .md"))
            if os.path.isfile(p) and p.lower().endswith(".md"):
                with open(p, encoding="utf-8-sig") as f:
                    body = f.read()
                break
            print("  ✖ file non trovato o non .md")
    else:
        body = read_multiline()
    if not body.strip():
        raise Abort("il testo è vuoto")
    md_name = f"{pid}.md"
    while MD_DIR + md_name in files:
        print(f"  ! {MD_DIR}{md_name} esiste già nel repository.")
        md_name = ask("Scegli un altro nome per il file markdown", validate=lambda v: None if re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*(\.md)?$", v) else "nome non valido")
        md_name = md_name if md_name.lower().endswith(".md") else md_name + ".md"
    changes[MD_DIR + md_name] = body.encode("utf-8")

    # link finali
    links = []
    while yes("Aggiungere un link di fine pagina?", False):
        t = ask("Tipo: 1 = redirect (link), 2 = download (file)", validate=lambda v: None if v in ("1", "2") else "scrivi 1 oppure 2")
        if t == "1":
            uri = ask("URL (https://…) oppure pagina interna (es. src/html/proposte.html)")
            if SCHEME_RE.match(uri):
                err = v_url(uri)
                if err:
                    print(f"  ✖ {err}")
                    continue
            elif ".." in uri.replace("\\", "/").split("/") or uri.startswith("/"):
                print("  ✖ percorso interno non valido")
                continue
            link = {"type": "redirect", "uri": uri}
        else:
            p = expand(ask("Percorso del file da caricare"))
            if not os.path.isfile(p):
                print("  ✖ file non trovato")
                continue
            name = slug_filename(p)
            if not name:
                print("  ✖ nome file non valido")
                continue
            dest = FILES_DIR + name
            if dest in files or dest in changes:
                if not yes(f"  ! {dest} esiste già. Sostituirlo?", False):
                    print("  (link saltato)")
                    continue
            with open(p, "rb") as f:
                changes[dest] = f.read()
            link = {"type": "download", "uri": name}
        label = ask("Testo del pulsante", required=False)
        if label:
            link["label"] = label
        links.append(link)

    entry = {"id": pid, "title": title, "subtitle": subtitle, "author": author, "date": date, "content": md_name, "links": links}
    entries.append(entry)
    changes[cfg["json"]] = dump_json(entries)

    summary = [f"{kind.capitalize()} «{title}» ({pid})"] + [f"  + {p}" for p in changes if p != cfg["json"]] + [f"  ~ {cfg['json']}"]
    return gh, commit_sha, base_tree, changes, f"Aggiunge {kind}: {pid}", summary, cfg["page"].format(id=pid)


def create_event(gh):
    commit_sha, base_tree, files = gh.head()
    entries = load_json_list(gh, files, EVENTS_JSON)
    used = {str(e.get("id")) for e in entries if isinstance(e, dict)}
    print("\n── Nuovo evento del calendario ──")
    eid = ask("ID evento (es. assemblea-ottobre)", validate=lambda v: v_id(v) or ("ID già usato" if v in used else None))
    title = ask("Titolo")
    date = ask("Data", default=today(), validate=v_date)
    time = ask('Orario ("all day", "HH:MM" oppure "HH:MM-HH:MM")', default="all day", validate=v_time)
    desc = ask("Descrizione", required=False)
    entry = {"id": eid, "date": date, "time": time, "title": title}
    if desc:
        entry["description"] = desc
    entries.append(entry)
    changes = {EVENTS_JSON: dump_json(entries)}
    return gh, commit_sha, base_tree, changes, f"Aggiunge evento: {eid}", [f"Evento «{title}» il {date} ({time})", f"  ~ {EVENTS_JSON}"], None


# ───────────────────────── main ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Crea articoli, comunicazioni ed eventi del sito OOTB.")
    ap.add_argument("--repo", default=os.environ.get("OOTB_REPO", DEFAULT_REPO), help="owner/repo")
    ap.add_argument("--branch", default=os.environ.get("OOTB_BRANCH", DEFAULT_BRANCH))
    args = ap.parse_args()
    if not re.match(r"^[\w.-]+/[\w.-]+$", args.repo):
        sys.exit("--repo deve essere nel formato owner/repo")

    token = os.environ.get("GITHUB_TOKEN") or getpass.getpass("Token GitHub (input nascosto): ").strip()
    if not token:
        sys.exit("Token mancante.")
    gh = GitHub(token, args.repo, args.branch)
    try:
        gh.head()  # verifica subito token e accesso
    except Abort as e:
        sys.exit(f"✖ {e}")
    print(f"✔ Connesso a {args.repo} ({args.branch})")

    while True:
        print("\nCosa vuoi creare?\n  1) Articolo\n  2) Comunicazione\n  3) Evento del calendario\n  q) Esci")
        choice = input("> ").strip().lower()
        if choice in ("q", ""):
            break
        try:
            if choice == "1":
                job = create_post(gh, "articolo")
            elif choice == "2":
                job = create_post(gh, "comunicazione")
            elif choice == "3":
                job = create_event(gh)
            else:
                continue
            gh, parent, base_tree, changes, message, summary, page = job
            print("\nRiepilogo:")
            print("\n".join(summary))
            if not yes("\nFare commit e push su GitHub?", True):
                print("Annullato, nulla è stato inviato.")
                continue
            # push non forzato: se nel frattempo qualcuno ha pushato, GitHub rifiuta e non si sovrascrive nulla
            try:
                sha = gh.commit(parent, base_tree, changes, message)
            except Abort as e:
                if "409" in str(e) or "422" in str(e):
                    raise Abort("il repository è cambiato mentre inserivi i dati: nulla è stato inviato, rifai l'operazione") from None
                raise
            print(f"✔ Pubblicato (commit {sha[:7]}).")
            if page:
                print(f"  La pagina {page} sarà creata dal workflow entro circa un minuto.")
        except Abort as e:
            print(f"✖ {e}")
        except (KeyboardInterrupt, EOFError):
            print("\nOperazione interrotta.")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
