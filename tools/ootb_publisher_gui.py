#!/usr/bin/env python3
"""
OOTB Publisher GUI – editor grafico per creare articoli, comunicazioni ed eventi del sito.

Avvia un piccolo server SOLO sul tuo dispositivo (127.0.0.1) e apre l'editor nel browser:
barra degli strumenti in stile editor di testo, anteprima in tempo reale, caricamento di
immagini e file, e push automatico su GitHub tramite le API (nessun git richiesto).

    python3 ootb_publisher_gui.py            # apre il browser da solo
    python3 ootb_publisher_gui.py --no-browser --port 8765

Solo libreria standard di Python 3.8+. Va tenuto nella stessa cartella di ootb_publisher.py.
Il token GitHub si inserisce nella pagina e resta solo nella memoria del programma: non viene
salvato su disco. Fine-grained token con "Contents: Read and write" sul repository, oppure
token classico con scope "repo".
"""
import argparse
import base64
import binascii
import hmac
import json
import os
import re
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ootb_publisher as core  # noqa: E402  (GitHub, Abort, validatori, costanti)

MAX_BODY = 60 * 1024 * 1024
MAX_IMAGE = 10 * 1024 * 1024
IMAGES_DIR = "docs/images/"
IMG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(png|jpe?g|gif|webp)$", re.I)
IMG_REF_RE = re.compile(r"\(\s*docs/images/([^)\s\"]+)")

SESSION = secrets.token_urlsafe(32)
STATE = {"gh": None, "lock": threading.Lock(), "port": 0}


# ───────────────────────── logica lato server ─────────────────────────
def b64(s, what):
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise core.Abort(f"{what}: contenuto non valido") from None


def site_base(gh, files):
    sha = files.get("CNAME")
    if sha:
        host = gh.read_text(sha).strip()
        if re.match(r"^[A-Za-z0-9.-]+$", host):
            return f"https://{host}/"
    return ""


def api_login(d):
    repo = str(d.get("repo", "")).strip() or core.DEFAULT_REPO
    branch = str(d.get("branch", "")).strip() or core.DEFAULT_BRANCH
    token = str(d.get("token", "")).strip()
    if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        raise core.Abort("Repository non valido (formato owner/repo)")
    if not re.match(r"^[\w./-]+$", branch):
        raise core.Abort("Branch non valido")
    if not token:
        raise core.Abort("Inserisci il token GitHub")
    gh = core.GitHub(token, repo, branch)
    _, _, files = gh.head()  # verifica token e accesso
    STATE["gh"] = gh
    return {"repo": repo, "branch": branch, "base": site_base(gh, files)}


def need_gh():
    if not STATE["gh"]:
        raise core.Abort("Sessione scaduta: rifai l'accesso con il token")
    return STATE["gh"]


def api_state(_d):
    gh = need_gh()
    _, _, files = gh.head()
    ids = {}
    for kind, cfg in core.KINDS.items():
        ids[kind] = [e.get("id") for e in core.load_json_list(gh, files, cfg["json"]) if isinstance(e, dict)]
    ids["evento"] = [str(e.get("id")) for e in core.load_json_list(gh, files, core.EVENTS_JSON) if isinstance(e, dict)]
    return {
        "ids": ids,
        "images": sorted(p[len(IMAGES_DIR):] for p in files if p.startswith(IMAGES_DIR) and p != IMAGES_DIR + ".gitkeep"),
        "files": sorted(p[len(core.FILES_DIR):] for p in files if p.startswith(core.FILES_DIR) and not p.endswith(".gitkeep")),
    }


def clean_str(d, key, required=True, maxlen=500):
    v = d.get(key)
    v = v.strip() if isinstance(v, str) else ""
    if required and not v:
        raise core.Abort(f"Campo obbligatorio mancante: {key}")
    if len(v) > maxlen:
        raise core.Abort(f"{key}: troppo lungo (max {maxlen} caratteri)")
    return v or None


def api_publish(d):
    gh = need_gh()
    kind = d.get("kind")
    parent, base_tree, files = gh.head()
    changes, summary, page = {}, [], None

    if kind in core.KINDS:
        cfg = core.KINDS[kind]
        entries = core.load_json_list(gh, files, cfg["json"])
        pid = clean_str(d, "id", maxlen=80)
        if core.v_id(pid):
            raise core.Abort("ID non valido: " + core.v_id(pid))
        if pid in {e.get("id") for e in entries if isinstance(e, dict)}:
            raise core.Abort(f"L'ID «{pid}» è già usato")
        title, author = clean_str(d, "title", maxlen=200), clean_str(d, "author", maxlen=100)
        subtitle = clean_str(d, "subtitle", required=False, maxlen=300)
        date = clean_str(d, "date")
        if core.v_date(date):
            raise core.Abort("Data non valida (AAAA-MM-GG)")
        body = d.get("body")
        if not isinstance(body, str) or not body.strip():
            raise core.Abort("Il testo è vuoto")
        md_name = f"{pid}.md"
        if core.MD_DIR + md_name in files:
            raise core.Abort(f"{core.MD_DIR}{md_name} esiste già nel repository")
        changes[core.MD_DIR + md_name] = body.replace("\r\n", "\n").rstrip().encode("utf-8") + b"\n"

        # immagini inserite nell'editor: si caricano solo quelle davvero usate nel testo
        used = set(IMG_REF_RE.findall(body))
        total = 0
        for img in d.get("images") or []:
            name = img.get("name") if isinstance(img, dict) else None
            if not isinstance(name, str) or not IMG_NAME_RE.match(name):
                raise core.Abort(f"Nome immagine non valido: {name}")
            if name not in used:
                continue
            if IMAGES_DIR + name in files:
                raise core.Abort(f"L'immagine {name} esiste già in {IMAGES_DIR}")
            raw = b64(img.get("data"), f"immagine {name}")
            total += len(raw)
            if len(raw) > MAX_IMAGE:
                raise core.Abort(f"Immagine {name} troppo grande (max 10 MB)")
            changes[IMAGES_DIR + name] = raw
        for name in used:
            if IMAGES_DIR + name not in files and IMAGES_DIR + name not in changes:
                raise core.Abort(f"Il testo usa l'immagine docs/images/{name}, che non è stata caricata")

        links = []
        for i, l in enumerate(d.get("links") or []):
            if not isinstance(l, dict):
                raise core.Abort(f"Link {i + 1} non valido")
            label = clean_str(l, "label", required=False, maxlen=100)
            if l.get("type") == "redirect":
                uri = clean_str(l, "uri", maxlen=1000)
                if core.SCHEME_RE.match(uri):
                    if core.v_url(uri):
                        raise core.Abort(f"Link {i + 1}: URL non valido (serve http:// o https://)")
                elif ".." in uri.replace("\\", "/").split("/") or uri.startswith("/"):
                    raise core.Abort(f"Link {i + 1}: percorso interno non valido")
                link = {"type": "redirect", "uri": uri}
            elif l.get("type") == "download":
                f = l.get("file") or {}
                name = core.slug_filename(str(f.get("name", "")))
                if not name or name.startswith("."):
                    raise core.Abort(f"Link {i + 1}: nome file non valido")
                dest = core.FILES_DIR + name
                if dest in files or dest in changes:
                    raise core.Abort(f"Il file {name} esiste già in docs/files: rinominalo prima di caricarlo")
                raw = b64(f.get("data"), f"file {name}")
                total += len(raw)
                changes[dest] = raw
                link = {"type": "download", "uri": name}
            else:
                raise core.Abort(f"Link {i + 1}: tipo non valido")
            if label:
                link["label"] = label
            links.append(link)

        entries.append({"id": pid, "title": title, "subtitle": subtitle, "author": author, "date": date,
                        "content": md_name, "links": links})
        changes[cfg["json"]] = core.dump_json(entries)
        page = cfg["page"].format(id=pid)
        message = f"Aggiunge {kind}: {pid}"
        summary = [f"{kind.capitalize()} «{title}»"] + [p for p in changes if p != cfg["json"]]

    elif kind == "evento":
        entries = core.load_json_list(gh, files, core.EVENTS_JSON)
        eid = clean_str(d, "id", maxlen=80)
        if core.v_id(eid):
            raise core.Abort("ID non valido: " + core.v_id(eid))
        if eid in {str(e.get("id")) for e in entries if isinstance(e, dict)}:
            raise core.Abort(f"L'ID «{eid}» è già usato")
        title, date = clean_str(d, "title", maxlen=200), clean_str(d, "date")
        time = clean_str(d, "time", maxlen=20)
        if core.v_date(date):
            raise core.Abort("Data non valida (AAAA-MM-GG)")
        if core.v_time(time):
            raise core.Abort("Orario non valido: " + core.v_time(time))
        entry = {"id": eid, "date": date, "time": time, "title": title}
        desc = clean_str(d, "description", required=False, maxlen=1000)
        if desc:
            entry["description"] = desc
        entries.append(entry)
        changes[core.EVENTS_JSON] = core.dump_json(entries)
        message = f"Aggiunge evento: {eid}"
        summary = [f"Evento «{title}»"]
    else:
        raise core.Abort("Tipo di contenuto non valido")

    sha = gh.commit(parent, base_tree, changes, message)
    return {"sha": sha, "page": page, "files": list(changes)}


ROUTES = {"/api/login": api_login, "/api/state": api_state, "/api/publish": api_publish}


# ───────────────────────── server ─────────────────────────
class Handler(BaseHTTPRequestHandler):
    server_version = "OOTBPublisher"

    def log_message(self, *a):
        pass

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in (f"127.0.0.1:{STATE['port']}", f"localhost:{STATE['port']}")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "img-src 'self' blob: data: https:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "host non consentito"})
        if self.path.split("?")[0] != "/":
            return self._send(404, {"error": "non trovato"})
        page = PAGE.replace("__SESSION__", SESSION).replace("__REPO__", core.DEFAULT_REPO).replace("__BRANCH__", core.DEFAULT_BRANCH)
        self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "host non consentito"})
        if not hmac.compare_digest(self.headers.get("X-OOTB-Session", ""), SESSION):
            return self._send(403, {"error": "sessione non valida: ricarica la pagina"})
        fn = ROUTES.get(self.path)
        if not fn:
            return self._send(404, {"error": "non trovato"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n > MAX_BODY:
                return self._send(413, {"error": "contenuto troppo grande (max 60 MB)"})
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "richiesta non valida"})
        try:
            with STATE["lock"]:
                self._send(200, {"ok": True, **fn(data)})
        except core.Abort as e:
            self._send(200, {"ok": False, "error": str(e)})
        except Exception as e:  # non mostrare dettagli interni (potrebbero contenere dati sensibili)
            print("Errore interno:", type(e).__name__, file=sys.stderr)
            self._send(500, {"ok": False, "error": "errore interno del programma"})


def main():
    ap = argparse.ArgumentParser(description="Editor grafico per pubblicare sul sito OOTB.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="non aprire il browser automaticamente")
    args = ap.parse_args()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    STATE["port"] = srv.server_address[1]
    url = f"http://127.0.0.1:{STATE['port']}/"
    print(f"OOTB Publisher in ascolto su {url}\nPremi Ctrl+C per chiudere.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nChiuso.")


# ───────────────────────── interfaccia (HTML/CSS/JS) ─────────────────────────
PAGE = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OOTB Publisher</title>
<style>
:root{--w:#fff;--k:#171717;--r:#D92D25;--g:#EDEBE6;--d:Impact,'Arial Narrow Bold','Arial Narrow',sans-serif;--t:'Arial Narrow',Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--w);color:var(--k);font:16px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
[hidden]{display:none!important}
.top{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:4px solid var(--k);position:sticky;top:0;background:var(--w);z-index:5}
.top b{font:400 1.5rem/1 var(--d);letter-spacing:.02em;text-transform:uppercase}
.top span{background:var(--r);color:var(--w);font:700 .85rem/1 var(--t);text-transform:uppercase;padding:4px 7px 3px}
.top .sp{flex:1}
button,.btn{font:700 1rem/1 var(--t);text-transform:uppercase;letter-spacing:.02em;border:3px solid var(--k);background:var(--w);color:var(--k);padding:10px 14px 8px;cursor:pointer;box-shadow:4px 4px 0 var(--k);min-height:44px}
button:hover{background:var(--r);color:var(--w);transform:translate(4px,4px);box-shadow:none}
button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid var(--r);outline-offset:2px}
button.ghost{box-shadow:none;border-width:2px;padding:6px 10px 5px;min-height:36px}
button.ghost:hover{transform:none}
button:disabled{opacity:.5;cursor:progress;transform:none;box-shadow:none}
.wrap{max-width:1180px;margin:0 auto;padding:20px 16px 80px}
h1,h2{font:400 clamp(2rem,6vw,3.4rem)/.95 var(--d);text-transform:uppercase;margin:0 0 14px}
h2{font-size:1.8rem}
label{display:block;font:700 1.05rem/1 var(--t);text-transform:uppercase;margin:0 0 5px}
input,select,textarea{width:100%;border:3px solid var(--k);padding:10px;font:inherit;background:var(--w);color:var(--k);border-radius:0}
.req{color:var(--r)}
.hint{font-size:.85rem;opacity:.75;margin:4px 0 0}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{border:4px solid var(--k);padding:18px;margin:0 0 22px;box-shadow:6px 6px 0 var(--k)}
.login{max-width:520px;margin:6vh auto 0}
.login .card{display:grid;gap:14px}
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}
.tabs button[aria-selected=true]{background:var(--k);color:var(--w)}
.tabs button[aria-selected=true]:hover{background:var(--r)}
#status{border:3px solid var(--k);padding:10px 14px;margin:0 0 18px;font-weight:600}
#status.err{background:var(--r);color:var(--w);border-color:var(--k)}
#status.ok{background:var(--k);color:var(--w)}
#status a{color:inherit}
.toolbar{display:flex;flex-wrap:wrap;gap:6px;padding:8px;border:3px solid var(--k);border-bottom:0;background:var(--g)}
.toolbar button{box-shadow:none;border-width:2px;padding:6px 10px 5px;min-height:38px;min-width:38px;background:var(--w)}
.toolbar button:hover{transform:none}
.toolbar .sep{width:2px;background:var(--k);margin:0 4px;opacity:.35}
.split{display:grid;grid-template-columns:1fr 1fr;gap:0;border:3px solid var(--k)}
.split textarea{border:0;border-right:3px solid var(--k);min-height:420px;resize:vertical;font:1rem/1.5 ui-monospace,Menlo,Consolas,monospace}
.preview{padding:16px;overflow:auto;max-height:640px;min-height:420px;background:var(--w)}
.preview .ph{opacity:.5}
.viewtabs{display:none;gap:6px;margin:0 0 8px}
@media(max-width:800px){.split{grid-template-columns:1fr}.split textarea{border-right:0;border-bottom:3px solid var(--k);min-height:300px}.viewtabs{display:flex}.split[data-view=write] .preview{display:none}.split[data-view=preview] textarea{display:none}}
/* anteprima: stesso stile delle pagine del sito */
.preview h2{font:400 2rem/1 var(--d);text-transform:uppercase;margin:14px 0 8px}
.preview h3{font:400 1.5rem/1 var(--d);text-transform:uppercase;margin:12px 0 6px}
.preview h4,.preview h5,.preview h6{font:700 1.3rem/1 var(--t);text-transform:uppercase}
.preview p,.preview li{font-size:1.15rem;line-height:1.3;font-weight:500}
.preview a{text-decoration:underline;text-decoration-color:var(--r);text-decoration-thickness:3px}
.preview img{max-width:100%;border:4px solid var(--k);display:block}
.preview figcaption{font-size:.95rem;font-weight:600}
.preview figure{margin:12px 0}
.preview blockquote{border-left:8px solid var(--r);margin:10px 0;padding:2px 0 2px 14px;font-weight:600}
.preview pre{background:var(--k);color:var(--w);padding:12px;overflow:auto;border-left:8px solid var(--r)}
.preview code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em;background:var(--g);padding:1px 4px}
.preview pre code{background:none;padding:0}
.preview hr{border:0;border-top:4px solid var(--k)}
.links .row{display:grid;grid-template-columns:150px 1fr 1fr auto;gap:8px;align-items:end;margin:0 0 10px}
@media(max-width:700px){.links .row{grid-template-columns:1fr}}
dialog{border:4px solid var(--k);padding:18px;max-width:480px;width:calc(100% - 32px);box-shadow:8px 8px 0 var(--k)}
dialog::backdrop{background:rgba(0,0,0,.5)}
dialog form{display:grid;gap:12px}
dialog .acts{display:flex;gap:10px;justify-content:flex-end}
.actions{display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.small{font-size:.9rem}
</style>
</head>
<body>
<header class="top"><b>Out of the Box</b><span>Publisher</span><div class="sp"></div><button class="ghost" id="logout" hidden type="button">Esci</button></header>

<div class="wrap">
<div id="status" role="status" hidden></div>

<section id="login" class="login">
  <h1>Accedi</h1>
  <form class="card" id="loginForm" autocomplete="off">
    <div><label for="token">Token GitHub <span class="req">*</span></label>
      <input id="token" type="password" autocomplete="off" required>
      <p class="hint">Resta solo nella memoria di questo programma: non viene salvato né scritto su disco. Serve un token con permesso "Contents: Read and write" sul repository.</p></div>
    <div class="grid">
      <div><label for="repo">Repository</label><input id="repo" value="__REPO__"></div>
      <div><label for="branch">Branch</label><input id="branch" value="__BRANCH__"></div>
    </div>
    <button type="submit" id="loginBtn">Entra</button>
  </form>
</section>

<main id="app" hidden>
  <div class="tabs" role="tablist" aria-label="Cosa vuoi creare">
    <button type="button" role="tab" data-kind="articolo" aria-selected="true">Articolo</button>
    <button type="button" role="tab" data-kind="comunicazione" aria-selected="false">Comunicazione</button>
    <button type="button" role="tab" data-kind="evento" aria-selected="false">Evento calendario</button>
  </div>

  <form id="postForm" novalidate>
    <h2 id="postTitle">Nuovo articolo</h2>
    <div class="card">
      <div class="grid">
        <div><label for="f-title">Titolo <span class="req">*</span></label><input id="f-title" maxlength="200"></div>
        <div><label for="f-id">ID (nome della pagina) <span class="req">*</span></label><input id="f-id" maxlength="80" spellcheck="false"><p class="hint" id="idHint">Si genera dal titolo.</p></div>
      </div>
      <div class="grid" style="margin-top:14px">
        <div><label for="f-subtitle">Sottotitolo</label><input id="f-subtitle" maxlength="300"></div>
        <div><label for="f-author">Autore <span class="req">*</span></label><input id="f-author" maxlength="100"></div>
        <div><label for="f-date">Data <span class="req">*</span></label><input id="f-date" type="date"></div>
      </div>
    </div>

    <div class="card">
      <h2>Testo</h2>
      <div class="viewtabs"><button type="button" class="ghost" id="vWrite">Scrivi</button><button type="button" class="ghost" id="vPrev">Anteprima</button></div>
      <div class="toolbar" role="toolbar" aria-label="Formattazione">
        <button type="button" data-act="h2" title="Titolo di sezione">Titolo</button>
        <button type="button" data-act="h3" title="Sottotitolo di sezione">Sottotit.</button>
        <span class="sep"></span>
        <button type="button" data-act="bold" title="Grassetto (Ctrl+B)"><b>B</b></button>
        <button type="button" data-act="italic" title="Corsivo (Ctrl+I)"><i>I</i></button>
        <button type="button" data-act="strike" title="Barrato"><s>S</s></button>
        <span class="sep"></span>
        <button type="button" data-act="ul" title="Elenco puntato">• Elenco</button>
        <button type="button" data-act="ol" title="Elenco numerato">1. Elenco</button>
        <button type="button" data-act="quote" title="Citazione">“ Citazione</button>
        <span class="sep"></span>
        <button type="button" data-act="link" title="Link (Ctrl+K)">Link</button>
        <button type="button" data-act="image" title="Inserisci immagine">Immagine</button>
        <button type="button" data-act="code" title="Codice">&lt;/&gt;</button>
        <button type="button" data-act="hr" title="Linea separatrice">―</button>
      </div>
      <div class="split" id="split" data-view="write">
        <textarea id="f-body" aria-label="Testo in Markdown" placeholder="Scrivi qui il testo dell'articolo. Usa la barra degli strumenti per formattare." spellcheck="true"></textarea>
        <div class="preview" id="preview" aria-label="Anteprima"></div>
      </div>
      <p class="hint">Il titolo, l'autore e la data sono già nella pagina: nel testo scrivi solo il corpo.</p>
    </div>

    <div class="card links">
      <h2>Link e download di fine pagina</h2>
      <div id="linkRows"></div>
      <button type="button" class="ghost" id="addLink">+ Aggiungi link o file</button>
    </div>

    <div class="actions"><button type="submit" id="pubBtn">Pubblica su GitHub</button><span class="small" id="draftInfo"></span></div>
  </form>

  <form id="evForm" hidden novalidate>
    <h2>Nuovo evento</h2>
    <div class="card">
      <div class="grid">
        <div><label for="e-title">Titolo <span class="req">*</span></label><input id="e-title" maxlength="200"></div>
        <div><label for="e-id">ID <span class="req">*</span></label><input id="e-id" maxlength="80" spellcheck="false"></div>
      </div>
      <div class="grid" style="margin-top:14px">
        <div><label for="e-date">Data <span class="req">*</span></label><input id="e-date" type="date"></div>
        <div><label for="e-allday">Durata</label><select id="e-allday"><option value="all day">Tutto il giorno</option><option value="range">Con orario</option></select></div>
        <div id="timeBox" hidden><label for="e-start">Dalle</label><input id="e-start" type="time"></div>
        <div id="timeBox2" hidden><label for="e-end">Alle (facoltativo)</label><input id="e-end" type="time"></div>
      </div>
      <div style="margin-top:14px"><label for="e-desc">Descrizione</label><textarea id="e-desc" rows="3" maxlength="1000"></textarea></div>
    </div>
    <div class="actions"><button type="submit" id="evBtn">Pubblica su GitHub</button></div>
  </form>
</main>
</div>

<dialog id="dlgLink"><form method="dialog" id="fLink">
  <h2>Inserisci link</h2>
  <div><label for="l-text">Testo</label><input id="l-text"></div>
  <div><label for="l-url">Indirizzo (https://…)</label><input id="l-url" placeholder="https://"></div>
  <div class="acts"><button type="button" class="ghost" value="cancel" id="lCancel">Annulla</button><button type="submit">Inserisci</button></div>
</form></dialog>
<dialog id="dlgImg"><form method="dialog" id="fImg">
  <h2>Inserisci immagine</h2>
  <div><label for="i-file">Immagine (PNG, JPG, GIF, WebP – max 10 MB)</label><input id="i-file" type="file" accept="image/png,image/jpeg,image/gif,image/webp"></div>
  <div><label for="i-alt">Descrizione (per chi non vede l'immagine)</label><input id="i-alt"></div>
  <div><label for="i-cap">Didascalia (facoltativa)</label><input id="i-cap"></div>
  <div class="acts"><button type="button" class="ghost" id="iCancel">Annulla</button><button type="submit">Inserisci</button></div>
</form></dialog>

<script>
(() => {
'use strict';
const SESSION = '__SESSION__';
const $ = id => document.getElementById(id);
const state = { kind: 'articolo', base: '', ids: {}, images: [], files: [], pending: new Map(), links: [], repo: '' };
let idTouched = false;

/* ---------- utilità ---------- */
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} }
};
async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-OOTB-Session': SESSION }, body: JSON.stringify(body || {}) });
  let j; try { j = await r.json(); } catch { throw new Error('Risposta non valida dal programma (codice ' + r.status + ')'); }
  if (!j.ok) throw new Error(j.error || 'Errore');
  return j;
}
function status(msg, cls, html) {
  const s = $('status'); s.className = cls || ''; s.hidden = !msg;
  if (html) s.replaceChildren(html); else s.textContent = msg || '';
  if (msg || html) { s.scrollIntoView({ block: 'nearest' }); }
}
const slug = t => t.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
const today = () => { const d = new Date(), p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`; };
const readB64 = file => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(',')[1] || ''); r.onerror = () => rej(new Error('Lettura file non riuscita')); r.readAsDataURL(file); });
const fileSlug = n => n.replace(/\\/g, '/').split('/').pop().replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '');

/* ---------- anteprima markdown (semplice, per il solo controllo visivo) ---------- */
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const unesc = s => s.replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&');
function resolveSrc(u) {
  const m = /^docs\/images\/(.+)$/.exec(u);
  if (m && state.pending.has(m[1])) return state.pending.get(m[1]).url;
  if (/^https?:\/\//i.test(u)) return u;
  if (/^[a-z][a-z0-9+.-]*:/i.test(u) || u.startsWith('//')) return '';
  return state.base ? state.base + u.replace(/^\.?\//, '') : '';
}
function resolveHref(u) {
  if (/^(https?:|mailto:|#)/i.test(u)) return u;
  if (/^[a-z][a-z0-9+.-]*:/i.test(u) || u.startsWith('//')) return '#';
  return state.base ? state.base + u.replace(/^\.?\//, '') : '#';
}
function inline(src) {
  const codes = [];
  let s = src.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
  s = esc(s);
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;(.*?)&quot;)?\)/g, (_, alt, u) => `<img src="${esc(resolveSrc(unesc(u)))}" alt="${alt}">`);
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;(.*?)&quot;)?\)/g, (_, t, u) => `<a href="${esc(resolveHref(unesc(u)))}" target="_blank" rel="noopener">${t}</a>`);
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/~~(.+?)~~/g, '<s>$1</s>');
  s = s.replace(/(^|[^*\w])\*(?!\s)([^*]+?)\*(?!\*)/g, '$1<em>$2</em>').replace(/(^|[^\w])_(?!\s)([^_]+?)_(?!\w)/g, '$1<em>$2</em>');
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => '<code>' + esc(codes[+i]) + '</code>');
}
function render(md) {
  const L = md.replace(/\r\n/g, '\n').split('\n'); let out = '', i = 0;
  while (i < L.length) {
    const line = L[i];
    if (!line.trim()) { i++; continue; }
    let m;
    if (/^```/.test(line)) { const buf = []; i++; while (i < L.length && !/^```/.test(L[i])) buf.push(L[i++]); i++; out += `<pre><code>${esc(buf.join('\n'))}</code></pre>`; continue; }
    if ((m = /^(#{1,6})\s+(.*)$/.exec(line))) { const n = Math.min(m[1].length + 1, 6); out += `<h${n}>${inline(m[2])}</h${n}>`; i++; continue; }
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { out += '<hr>'; i++; continue; }
    if (/^>\s?/.test(line)) { const buf = []; while (i < L.length && /^>\s?/.test(L[i])) buf.push(L[i++].replace(/^>\s?/, '')); out += `<blockquote>${buf.map(inline).join('<br>')}</blockquote>`; continue; }
    if (/^\s*[-*+]\s+/.test(line)) { const buf = []; while (i < L.length && /^\s*[-*+]\s+/.test(L[i])) buf.push(L[i++].replace(/^\s*[-*+]\s+/, '')); out += '<ul>' + buf.map(x => `<li>${inline(x)}</li>`).join('') + '</ul>'; continue; }
    if (/^\s*\d+[.)]\s+/.test(line)) { const buf = []; while (i < L.length && /^\s*\d+[.)]\s+/.test(L[i])) buf.push(L[i++].replace(/^\s*\d+[.)]\s+/, '')); out += '<ol>' + buf.map(x => `<li>${inline(x)}</li>`).join('') + '</ol>'; continue; }
    const buf = [];
    while (i < L.length && L[i].trim() && !/^(#{1,6}\s|```|>|\s*[-*+]\s|\s*\d+[.)]\s|-{3,}\s*$)/.test(L[i])) buf.push(L[i++]);
    const para = buf.join(' ');
    const fig = /^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"(.*?)")?\)$/.exec(para.trim());
    if (fig) out += `<figure><img src="${esc(resolveSrc(fig[2]))}" alt="${esc(fig[1])}">${fig[3] ? `<figcaption>${esc(fig[3])}</figcaption>` : ''}</figure>`;
    else out += `<p>${inline(para)}</p>`;
  }
  return out;
}
function updatePreview() {
  const v = $('f-body').value;
  $('preview').innerHTML = v.trim() ? render(v) : '<p class="ph">L’anteprima appare qui mentre scrivi.</p>';
}

/* ---------- editor: azioni della barra ---------- */
const ta = () => $('f-body');
function insertText(text, selStart, selEnd) {
  const t = ta(); t.focus();
  let done = false;
  try { done = document.execCommand('insertText', false, text); } catch {}
  if (!done) { t.setRangeText(text, t.selectionStart, t.selectionEnd, 'end'); }
  if (selStart != null) t.setSelectionRange(selStart, selEnd);
  t.dispatchEvent(new Event('input'));
}
function wrap(pre, post, ph) {
  const t = ta(), a = t.selectionStart, b = t.selectionEnd, sel = t.value.slice(a, b) || ph;
  insertText(pre + sel + post, a + pre.length, a + pre.length + sel.length);
}
function linePrefix(fn) {
  const t = ta(), v = t.value; let a = t.selectionStart, b = t.selectionEnd;
  const s = v.lastIndexOf('\n', a - 1) + 1; let e = v.indexOf('\n', b); if (e < 0) e = v.length;
  t.setSelectionRange(s, e);
  const lines = v.slice(s, e).split('\n').map(fn).join('\n');
  insertText(lines, s, s + lines.length);
}
function block(text) {
  const t = ta(); t.focus(); t.setSelectionRange(t.selectionEnd, t.selectionEnd);
  const v = t.value, a = t.selectionStart;
  const pre = a === 0 || v.slice(a - 2, a) === '\n\n' ? '' : (v[a - 1] === '\n' ? '\n' : '\n\n');
  insertText(pre + text + '\n\n');
}
const actions = {
  h2: () => linePrefix(l => '## ' + l.replace(/^#{1,6}\s+/, '')),
  h3: () => linePrefix(l => '### ' + l.replace(/^#{1,6}\s+/, '')),
  bold: () => wrap('**', '**', 'grassetto'),
  italic: () => wrap('*', '*', 'corsivo'),
  strike: () => wrap('~~', '~~', 'barrato'),
  ul: () => linePrefix(l => '- ' + l.replace(/^\s*[-*+]\s+/, '')),
  ol: (n = 0) => linePrefix(l => (++n) + '. ' + l.replace(/^\s*\d+[.)]\s+/, '')),
  quote: () => linePrefix(l => '> ' + l.replace(/^>\s?/, '')),
  code: () => { const t = ta(), sel = t.value.slice(t.selectionStart, t.selectionEnd); sel.includes('\n') ? wrap('```\n', '\n```', 'codice') : wrap('`', '`', 'codice'); },
  hr: () => block('---'),
  link: () => { const t = ta(); $('l-text').value = t.value.slice(t.selectionStart, t.selectionEnd); $('l-url').value = 'https://'; $('dlgLink').showModal(); $('l-text').focus(); },
  image: () => { $('i-file').value = ''; $('i-alt').value = ''; $('i-cap').value = ''; $('dlgImg').showModal(); }
};
document.querySelector('.toolbar').addEventListener('click', e => { const b = e.target.closest('button[data-act]'); if (b) actions[b.dataset.act](); });
ta().addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 'b') { e.preventDefault(); actions.bold(); } else if (k === 'i') { e.preventDefault(); actions.italic(); } else if (k === 'k') { e.preventDefault(); actions.link(); }
});
ta().addEventListener('input', () => { updatePreview(); saveDraft(); });
$('lCancel').onclick = () => $('dlgLink').close();
$('iCancel').onclick = () => $('dlgImg').close();
$('fLink').addEventListener('submit', e => {
  e.preventDefault();
  const text = $('l-text').value.trim() || $('l-url').value.trim(), url = $('l-url').value.trim();
  if (!url || url === 'https://') { return; }
  if (/^\s*(javascript|data|vbscript):/i.test(url)) { status('Indirizzo non consentito.', 'err'); return; }
  $('dlgLink').close(); insertText(`[${text}](${url})`);
});
$('fImg').addEventListener('submit', async e => {
  e.preventDefault();
  const f = $('i-file').files[0]; if (!f) return;
  if (!/^image\/(png|jpeg|gif|webp)$/.test(f.type)) { status('Formato immagine non supportato (PNG, JPG, GIF, WebP).', 'err'); return; }
  if (f.size > 10 * 1024 * 1024) { status('Immagine troppo grande (max 10 MB).', 'err'); return; }
  const ext = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp' }[f.type];
  let base = fileSlug(f.name.replace(/\.[^.]+$/, '')).toLowerCase() || 'immagine';
  let name = `${base}.${ext}`, n = 2;
  while (state.images.includes(name) || state.pending.has(name)) name = `${base}-${n++}.${ext}`;
  const data = await readB64(f);
  state.pending.set(name, { data, url: URL.createObjectURL(f) });
  const alt = $('i-alt').value.trim().replace(/[\[\]]/g, ''), cap = $('i-cap').value.trim().replace(/"/g, "'");
  $('dlgImg').close();
  block(`![${alt}](docs/images/${name}${cap ? ` "${cap}"` : ''})`);
});

/* ---------- bozza automatica (solo testo, nel browser) ---------- */
function draftKey() { return 'ootb.draft.' + state.kind; }
function saveDraft() {
  if (state.kind === 'evento') return;
  store.set(draftKey(), JSON.stringify({ t: $('f-title').value, i: $('f-id').value, s: $('f-subtitle').value, d: $('f-date').value, b: ta().value }));
  $('draftInfo').textContent = 'Bozza salvata in questo browser';
}
function loadDraft() {
  let d = null; try { d = JSON.parse(store.get(draftKey()) || 'null'); } catch {}
  $('f-title').value = d?.t || ''; $('f-id').value = d?.i || ''; $('f-subtitle').value = d?.s || ''; $('f-date').value = d?.d || today(); ta().value = d?.b || '';
  idTouched = !!d?.i; $('draftInfo').textContent = d && (d.t || d.b) ? 'Bozza ripristinata' : '';
  updatePreview(); checkId();
}
$('f-author').value = store.get('ootb.author') || '';

/* ---------- ID ---------- */
function checkId() {
  const id = $('f-id').value.trim(), h = $('idHint');
  if (!id) { h.textContent = 'Si genera dal titolo.'; return; }
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(id)) { h.textContent = 'Solo lettere, numeri, "-" e "_".'; return; }
  h.textContent = (state.ids[state.kind] || []).includes(id) ? '⚠ ID già usato: scegline un altro.' : 'Pagina: ' + (state.kind === 'comunicazione' ? 'docs/communications/' : 'docs/articles/') + id + '.html';
}
$('f-title').addEventListener('input', () => { if (!idTouched) $('f-id').value = slug($('f-title').value); checkId(); saveDraft(); });
$('f-id').addEventListener('input', () => { idTouched = true; checkId(); saveDraft(); });
['f-subtitle', 'f-date'].forEach(i => $(i).addEventListener('input', saveDraft));
$('f-author').addEventListener('input', () => store.set('ootb.author', $('f-author').value));
$('e-title').addEventListener('input', () => { if (!$('e-id').dataset.t) $('e-id').value = slug($('e-title').value); });
$('e-id').addEventListener('input', () => { $('e-id').dataset.t = '1'; });
$('e-allday').addEventListener('change', () => { const r = $('e-allday').value === 'range'; $('timeBox').hidden = !r; $('timeBox2').hidden = !r; });

/* ---------- link e file ---------- */
function renderLinks() {
  const box = $('linkRows'); box.replaceChildren();
  state.links.forEach((l, i) => {
    const row = document.createElement('div'); row.className = 'row';
    const type = document.createElement('div'), sel = document.createElement('select');
    sel.setAttribute('aria-label', 'Tipo');
    [['redirect', 'Link'], ['download', 'Download']].forEach(([v, t]) => { const o = new Option(t, v); sel.add(o); });
    sel.value = l.type; sel.onchange = () => { l.type = sel.value; l.uri = ''; l.file = null; renderLinks(); };
    type.append(sel);
    const target = document.createElement('div');
    if (l.type === 'redirect') {
      const inp = document.createElement('input'); inp.placeholder = 'https://… oppure src/html/pagina.html'; inp.value = l.uri || ''; inp.setAttribute('aria-label', 'Indirizzo');
      inp.oninput = () => { l.uri = inp.value; }; target.append(inp);
    } else {
      const inp = document.createElement('input'); inp.type = 'file'; inp.setAttribute('aria-label', 'File da caricare');
      inp.onchange = async () => { const f = inp.files[0]; if (!f) { l.file = null; return; }
        if (f.size > 25 * 1024 * 1024) { status('File troppo grande (max 25 MB).', 'err'); inp.value = ''; return; }
        const name = fileSlug(f.name);
        if (state.files.includes(name)) { status(`Esiste già un file «${name}» in docs/files: rinominalo prima di caricarlo.`, 'err'); inp.value = ''; return; }
        l.file = { name, data: await readB64(f) }; status(''); };
      target.append(inp);
    }
    const lab = document.createElement('div'), li = document.createElement('input');
    li.placeholder = 'Testo del pulsante (facoltativo)'; li.value = l.label || ''; li.setAttribute('aria-label', 'Testo del pulsante'); li.oninput = () => { l.label = li.value; };
    lab.append(li);
    const rm = document.createElement('button'); rm.type = 'button'; rm.className = 'ghost'; rm.textContent = 'Rimuovi'; rm.onclick = () => { state.links.splice(i, 1); renderLinks(); };
    row.append(type, target, lab, rm); box.append(row);
  });
}
$('addLink').onclick = () => { state.links.push({ type: 'redirect', uri: '', label: '', file: null }); renderLinks(); };

/* ---------- schede ---------- */
function setKind(k) {
  state.kind = k;
  document.querySelectorAll('.tabs button').forEach(b => b.setAttribute('aria-selected', String(b.dataset.kind === k)));
  $('postForm').hidden = k === 'evento'; $('evForm').hidden = k !== 'evento';
  if (k !== 'evento') { $('postTitle').textContent = k === 'articolo' ? 'Nuovo articolo' : 'Nuova comunicazione'; loadDraft(); }
  status('');
}
document.querySelector('.tabs').addEventListener('click', e => { const b = e.target.closest('button[data-kind]'); if (b) setKind(b.dataset.kind); });
$('vWrite').onclick = () => $('split').dataset.view = 'write';
$('vPrev').onclick = () => { updatePreview(); $('split').dataset.view = 'preview'; };

/* ---------- accesso ---------- */
async function refreshState() { const s = await api('/api/state'); state.ids = s.ids; state.images = s.images; state.files = s.files; checkId(); }
$('loginForm').addEventListener('submit', async e => {
  e.preventDefault(); const btn = $('loginBtn'); btn.disabled = true; status('Connessione a GitHub…');
  try {
    const r = await api('/api/login', { token: $('token').value, repo: $('repo').value, branch: $('branch').value });
    $('token').value = ''; state.base = r.base; state.repo = r.repo;
    await refreshState();
    $('login').hidden = true; $('app').hidden = false; $('logout').hidden = false;
    setKind('articolo'); status('Connesso a ' + r.repo + ' (' + r.branch + ')', 'ok');
  } catch (err) { status(err.message, 'err'); } finally { btn.disabled = false; }
});
$('logout').onclick = () => location.reload();

/* ---------- pubblicazione ---------- */
function success(r, label) {
  const frag = document.createDocumentFragment();
  frag.append(`✔ Pubblicato (commit ${r.sha.slice(0, 7)}). `);
  if (r.page && state.base) { const a = document.createElement('a'); a.href = state.base + r.page; a.target = '_blank'; a.rel = 'noopener'; a.textContent = state.base + r.page; frag.append('La pagina sarà online tra circa un minuto: ', a); }
  else if (r.page) frag.append('La pagina ' + r.page + ' sarà creata tra circa un minuto.');
  status('ok', 'ok', frag);
}
$('postForm').addEventListener('submit', async e => {
  e.preventDefault(); const btn = $('pubBtn');
  const links = [];
  for (const l of state.links) {
    if (l.type === 'redirect') { if (!l.uri.trim()) { status('Un link non ha l’indirizzo: compilalo o rimuovilo.', 'err'); return; } links.push({ type: 'redirect', uri: l.uri.trim(), label: l.label || '' }); }
    else { if (!l.file) { status('Un download non ha il file: sceglilo o rimuovilo.', 'err'); return; } links.push({ type: 'download', file: l.file, label: l.label || '' }); }
  }
  const images = [...state.pending].map(([name, v]) => ({ name, data: v.data }));
  const payload = { kind: state.kind, id: $('f-id').value.trim(), title: $('f-title').value, subtitle: $('f-subtitle').value, author: $('f-author').value, date: $('f-date').value, body: ta().value, links, images };
  if (!payload.title.trim() || !payload.id || !payload.author.trim() || !payload.date || !payload.body.trim()) { status('Compila titolo, ID, autore, data e testo.', 'err'); return; }
  if (!confirm(`Pubblicare «${payload.title.trim()}» su GitHub?`)) return;
  btn.disabled = true; status('Pubblicazione in corso…');
  try {
    const r = await api('/api/publish', payload); success(r);
    store.del(draftKey()); state.links = []; state.pending.clear(); renderLinks();
    $('f-title').value = ''; $('f-id').value = ''; $('f-subtitle').value = ''; ta().value = ''; idTouched = false; $('draftInfo').textContent = ''; updatePreview();
    await refreshState();
  } catch (err) { status(err.message, 'err'); } finally { btn.disabled = false; }
});
$('evForm').addEventListener('submit', async e => {
  e.preventDefault(); const btn = $('evBtn');
  let time = 'all day';
  if ($('e-allday').value === 'range') { const s = $('e-start').value, en = $('e-end').value; if (!s) { status('Indica l’orario di inizio.', 'err'); return; } time = en ? `${s}-${en}` : s; }
  const payload = { kind: 'evento', id: $('e-id').value.trim(), title: $('e-title').value, date: $('e-date').value, time, description: $('e-desc').value };
  if (!payload.title.trim() || !payload.id || !payload.date) { status('Compila titolo, ID e data.', 'err'); return; }
  if (!confirm(`Pubblicare l’evento «${payload.title.trim()}» su GitHub?`)) return;
  btn.disabled = true; status('Pubblicazione in corso…');
  try {
    const r = await api('/api/publish', payload); success(r);
    ['e-title', 'e-id', 'e-desc'].forEach(i => $(i).value = ''); delete $('e-id').dataset.t; await refreshState();
  } catch (err) { status(err.message, 'err'); } finally { btn.disabled = false; }
});
$('e-date').value = today();
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
