import ctypes
import glob
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import zipfile

REPO = os.path.dirname(os.path.abspath(__file__))
VENV = os.environ.get("HEMO_VENV") or os.path.join(REPO, ".venv")
VENV_PY = os.path.join(VENV, "Scripts", "python.exe")
TOOLS = os.environ.get("HEMO_TOOLS") or ("N:\\Tools" if os.path.isdir("N:\\") else os.path.join(os.environ.get("LOCALAPPDATA", REPO), "HemoGrid", "tools"))
PG_ROOT = os.path.join(TOOLS, "pg", "pgsql")
PG_BIN = os.path.join(PG_ROOT, "bin")
PG_DATA = os.path.join(TOOLS, "pgdata")
MONGO_DIR = os.path.join(TOOLS, "mongo")
MONGO_DATA = os.path.join(TOOLS, "mongodata")
PROFILE = os.path.join(TOOLS, "edge-profile")
LOGS = os.path.join(TOOLS, "logs")
PG_PORT, MONGO_PORT, APP_PORT = 54329, 27018, 5057
APP_URL = f"http://127.0.0.1:{APP_PORT}/"
PG_URL = "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64-binaries.zip"
MONGO_URL = "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.14.zip"
ICON = os.path.join(REPO, "assets", "hemogrid.ico")
NOWIN = 0x08000000
DETACHED = 0x00000008 | 0x00000200
VENV_PYW = os.path.join(VENV, "Scripts", "pythonw.exe")
PAPER, PAPER2, PAPER3, INK, INK2, BLOOD, COLD = "#F3F0E8", "#EAE6DA", "#E0DACA", "#1A1D21", "#4A5159", "#A3132A", "#0E5A66"

STEPS = ["Python environment", "Application packages", "PostgreSQL 16", "MongoDB 7", "Database servers", "Sample data", "Web application"]


def log(msg):
    os.makedirs(LOGS, exist_ok=True)
    with open(os.path.join(LOGS, "launcher.log"), "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def http_ok(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def wait_for(test, seconds, what):
    end = time.time() + seconds
    while time.time() < end:
        if test():
            return
        time.sleep(0.4)
    raise RuntimeError(f"{what} did not become ready in {seconds} seconds")


def quiet(cmd, **kw):
    return subprocess.run(cmd, creationflags=NOWIN, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


def find_mongod():
    hits = glob.glob(os.path.join(MONGO_DIR, "*", "bin", "mongod.exe"))
    return hits[0] if hits else None


def find_edge():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    return None


def app_window_cmd():
    edge = find_edge()
    if not edge:
        return None
    cmd = [edge, f"--app={APP_URL}", f"--user-data-dir={PROFILE}", "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-extensions",
           "--disable-background-mode", "--window-size=1440,900"]
    if os.environ.get("HEMO_WINDOW_POS"):
        cmd.append(f"--window-position={os.environ['HEMO_WINDOW_POS']}")
    return cmd


class Services:
    def __init__(self):
        self.pg = None
        self.mongo = None
        self.flask = None
        self.started = set()

    def start_postgres(self):
        if port_open(PG_PORT):
            return
        os.makedirs(LOGS, exist_ok=True)
        out = open(os.path.join(LOGS, "postgres.log"), "ab")
        self.pg = subprocess.Popen([os.path.join(PG_BIN, "postgres.exe"), "-D", PG_DATA, "-p", str(PG_PORT)], creationflags=NOWIN,
                                   stdin=subprocess.DEVNULL, stdout=out, stderr=out)
        wait_for(lambda: port_open(PG_PORT), 60, "PostgreSQL")
        self.started.add("pg")

    def start_mongo(self):
        if port_open(MONGO_PORT):
            return
        os.makedirs(MONGO_DATA, exist_ok=True)
        self.mongo = subprocess.Popen([find_mongod(), "--dbpath", MONGO_DATA, "--port", str(MONGO_PORT), "--bind_ip", "127.0.0.1",
                                       "--logpath", os.path.join(LOGS, "mongod.log")],
                                      creationflags=DETACHED, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_for(lambda: port_open(MONGO_PORT), 60, "MongoDB")
        self.started.add("mongo")

    def start_app(self):
        if http_ok(APP_URL):
            return
        out = open(os.path.join(LOGS, "app.log"), "ab")
        self.flask = subprocess.Popen([VENV_PYW if os.path.exists(VENV_PYW) else VENV_PY, os.path.join(REPO, "app", "app.py")], cwd=os.path.join(REPO, "app"), creationflags=NOWIN,
                                      stdin=subprocess.DEVNULL, stdout=out, stderr=out)
        wait_for(lambda: http_ok(APP_URL), 40, "the web application")
        self.started.add("app")

    def stop_all(self, force=False):
        if self.flask and self.flask.poll() is None:
            self.flask.terminate()
        if force or "app" in self.started:
            kill_app_processes()
        if "pg" in self.started or force:
            quiet([os.path.join(PG_BIN, "pg_ctl.exe"), "-D", PG_DATA, "stop", "-m", "fast"], timeout=60)
            if self.pg:
                try:
                    self.pg.wait(15)
                except subprocess.TimeoutExpired:
                    pass
        if "mongo" in self.started or force:
            quiet([VENV_PY, "-c", f"from pymongo import MongoClient; MongoClient('mongodb://127.0.0.1:{MONGO_PORT}', serverSelectionTimeoutMS=2000).admin.command('shutdown')"], timeout=30)
            if self.mongo and self.mongo.poll() is None:
                try:
                    self.mongo.wait(10)
                except subprocess.TimeoutExpired:
                    self.mongo.terminate()


def app_windows():
    user32 = ctypes.windll.user32
    found = []
    enum = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value == "Chrome_WidgetWin_1":
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title, 256)
                if "HemoGrid" in title.value:
                    found.append(hwnd)
        return True

    user32.EnumWindows(enum(visit), 0)
    return found


def kill_app_processes():
    target = os.path.join(REPO, "app", "app.py").replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*" + target + "*' } "
          "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    quiet(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], timeout=30)


def download(url, dest, ui, label):
    part = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last = None
    for attempt in range(1, 6):
        try:
            have = os.path.getsize(part) if os.path.exists(part) else 0
            req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
            with urllib.request.urlopen(req, timeout=60) as r:
                resumed = have and r.status == 206
                if not resumed:
                    have = 0
                total = have + int(r.headers.get("Content-Length") or 0)
                with open(part, "ab" if resumed else "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        have += len(chunk)
                        ui.detail(f"Downloading {label}: {have / 1e6:.0f} of {total / 1e6:.0f} MB")
                        ui.progress(have / total if total else 0)
            os.replace(part, dest)
            return
        except Exception as e:
            last = e
            log(f"download attempt {attempt} failed: {e}")
            ui.detail(f"Connection problem, retrying ({attempt} of 5)")
            time.sleep(3)
    raise RuntimeError(f"Could not download {label}: {last}")


def extract(zip_path, target, ui, label):
    with zipfile.ZipFile(zip_path) as z:
        items = z.infolist()
        for i, m in enumerate(items):
            z.extract(m, target)
            if i % 50 == 0:
                ui.detail(f"Unpacking {label}: {i * 100 // len(items)} percent")
                ui.progress(i / len(items))
    os.remove(zip_path)


def step_python(ui, svc):
    if os.path.exists(VENV_PY):
        return "found"
    base = os.path.join(sys.base_prefix, "python.exe")
    if not os.path.exists(base):
        base = shutil.which("python")
    if not base:
        raise RuntimeError("Python 3 was not found. Install Python 3.12 or newer from python.org and start HemoGrid again.")
    ui.detail("Creating the private Python environment")
    r = subprocess.run([base, "-m", "venv", VENV], creationflags=NOWIN, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Could not create the Python environment: " + r.stderr[-300:])
    return "created"


def step_packages(ui, svc):
    check = [VENV_PY, "-c", "import flask, markdown, psycopg, pymongo"]
    if quiet(check).returncode == 0:
        return "found"
    env = dict(os.environ, PIP_CACHE_DIR=os.path.join(TOOLS, "pipcache"), PIP_DISABLE_PIP_VERSION_CHECK="1")
    p = subprocess.Popen([VENV_PY, "-m", "pip", "install", "-r", os.path.join(REPO, "requirements-app.txt")], creationflags=NOWIN, env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tail = []
    for line in p.stdout:
        tail.append(line.strip())
        if line.startswith(("Collecting", "Downloading", "Installing")):
            ui.detail(line.strip()[:90])
    p.wait()
    if p.returncode or quiet(check).returncode:
        raise RuntimeError("Package installation failed: " + " ".join(tail[-3:])[:300])
    return "installed"


def step_postgres(ui, svc):
    if os.path.exists(os.path.join(PG_BIN, "postgres.exe")):
        return "found"
    zp = os.path.join(TOOLS, "downloads", "postgresql.zip")
    download(PG_URL, zp, ui, "PostgreSQL 16")
    extract(zp, os.path.join(TOOLS, "pg"), ui, "PostgreSQL")
    if not os.path.exists(os.path.join(PG_BIN, "postgres.exe")):
        raise RuntimeError("PostgreSQL files are missing after unpacking")
    return "installed"


def step_mongo(ui, svc):
    if find_mongod():
        return "found"
    zp = os.path.join(TOOLS, "downloads", "mongodb.zip")
    download(MONGO_URL, zp, ui, "MongoDB 7")
    extract(zp, MONGO_DIR, ui, "MongoDB")
    if not find_mongod():
        raise RuntimeError("MongoDB files are missing after unpacking")
    return "installed"


def step_servers(ui, svc):
    if not os.path.exists(os.path.join(PG_DATA, "PG_VERSION")):
        ui.detail("Creating the database cluster")
        r = subprocess.run([os.path.join(PG_BIN, "initdb.exe"), "-D", PG_DATA, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--locale=C"],
                           creationflags=NOWIN, stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError("Could not create the database cluster: " + r.stderr[-300:])
    ui.detail("Starting PostgreSQL")
    svc.start_postgres()
    ui.detail("Starting MongoDB")
    svc.start_mongo()
    return "running"


def psql(*args):
    r = subprocess.run([os.path.join(PG_BIN, "psql.exe"), "-p", str(PG_PORT), "-U", "postgres", "-tA", *args], creationflags=NOWIN,
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    return r.stdout.strip()


def step_data(ui, svc):
    if psql("-c", "select count(*) from pg_database where datname='hemogrid'") != "1":
        psql("-c", "create database hemogrid")
    if psql("-d", "hemogrid", "-c", "select to_regclass('hemo.blood_unit') is not null") == "t":
        return "ready"
    ui.detail("Building the schema and loading sample data")
    out = open(os.path.join(LOGS, "seed.log"), "ab")
    r = subprocess.run([VENV_PY, os.path.join(REPO, "scripts", "seed.py")], creationflags=NOWIN, stdin=subprocess.DEVNULL, stdout=out, stderr=out)
    if r.returncode:
        raise RuntimeError("Loading sample data failed. See seed.log in the logs folder.")
    return "loaded"


def step_app(ui, svc):
    ui.detail("Starting the web application")
    svc.start_app()
    return "running"


PIPELINE = [step_python, step_packages, step_postgres, step_mongo, step_servers, step_data, step_app]


def ensure_shortcuts():
    desktop = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "HemoGrid.lnk")
    menu = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "HemoGrid.lnk")
    pythonw = os.path.join(sys.base_prefix, "pythonw.exe")
    script = os.path.join(REPO, "HemoGrid.pyw")
    marker = os.path.join(TOOLS, "shortcuts.json")
    signature = json.dumps({"pythonw": pythonw, "script": script})
    try:
        current = open(marker, encoding="utf-8").read()
    except OSError:
        current = ""
    for path in (desktop, menu):
        if not path or (current == signature and os.path.exists(path)):
            continue
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{path}');$s.TargetPath='{pythonw}';"
              f"$s.Arguments='\"{script}\"';$s.WorkingDirectory='{REPO}';$s.IconLocation='{ICON}';$s.Description='HemoGrid blood bank database';$s.Save()")
        quiet(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], timeout=30)
    os.makedirs(TOOLS, exist_ok=True)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(signature)


class Ui:
    def __init__(self, root):
        self.q = queue.Queue()
        self.root = root
        root.title("HemoGrid")
        root.configure(bg=PAPER)
        w, h = 580, 520
        pos = os.environ.get("HEMO_LAUNCHER_POS")
        x, y = (int(v) for v in pos.split(",")) if pos else ((root.winfo_screenwidth() - w) // 2, (root.winfo_screenheight() - h) // 3)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.resizable(False, False)
        try:
            root.iconbitmap(ICON)
        except tk.TclError:
            pass
        head = tk.Canvas(root, width=w, height=100, bg=PAPER, highlightthickness=0)
        head.pack(fill="x")
        head.create_oval(40, 38, 76, 74, fill=BLOOD, outline=BLOOD)
        head.create_polygon(58, 14, 41, 52, 75, 52, fill=BLOOD, outline=BLOOD)
        head.create_rectangle(51, 52, 65, 57, fill=PAPER, outline=PAPER)
        head.create_rectangle(55, 47, 61, 62, fill=PAPER, outline=PAPER)
        head.create_text(96, 32, text="HemoGrid", anchor="w", font=("Segoe UI Semibold", 22), fill=INK)
        head.create_text(97, 62, text="Blood bank ledger", anchor="w", font=("Segoe UI", 10), fill=INK2)
        tk.Frame(root, bg=INK, height=2).pack(fill="x", padx=40)
        self.rows = []
        body = tk.Frame(root, bg=PAPER)
        body.pack(fill="x", padx=40, pady=(18, 4))
        for name in STEPS:
            row = tk.Frame(body, bg=PAPER)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=name, bg=PAPER, fg=INK, font=("Segoe UI", 11), anchor="w").pack(side="left")
            status = tk.Label(row, text="waiting", bg=PAPER, fg=INK2, font=("Consolas", 10), anchor="e", width=12)
            status.pack(side="right")
            self.rows.append(status)
        self.bar = tk.Canvas(root, width=w - 80, height=6, bg=PAPER3, highlightthickness=0)
        self.bar.pack(padx=40, pady=(16, 6))
        self.fill = self.bar.create_rectangle(0, 0, 0, 6, fill=BLOOD, outline=BLOOD)
        self.detail_var = tk.StringVar(value="Starting")
        tk.Label(root, textvariable=self.detail_var, bg=PAPER, fg=INK2, font=("Consolas", 9), anchor="w", justify="left", wraplength=w - 80).pack(fill="x", padx=40)
        self.buttons = tk.Frame(root, bg=PAPER)
        self.buttons.pack(pady=14)
        self.idx, self.frac, self.width = 0, 0.0, w - 80
        root.after(80, self.pump)

    def detail(self, text):
        self.q.put(("detail", text))

    def progress(self, frac):
        self.q.put(("frac", frac))

    def post(self, *item):
        self.q.put(item)

    def draw_bar(self):
        total = (self.idx + self.frac) / len(STEPS)
        self.bar.coords(self.fill, 0, 0, self.width * min(total, 1), 6)

    def pump(self):
        while True:
            try:
                item = self.q.get_nowait()
            except queue.Empty:
                break
            try:
                self.handle(item)
            except Exception as e:
                log(f"ui event {item[0]} failed: {e!r}")
        self.root.after(80, self.pump)

    def handle(self, item):
        kind = item[0]
        if kind == "detail":
            self.detail_var.set(item[1])
        elif kind == "frac":
            self.frac = item[1]
            self.draw_bar()
        elif kind == "step":
            _, i, state, text = item
            self.idx, self.frac = (i + (1 if state == "ok" else 0)), 0.0
            self.rows[i].config(text=text, fg={"ok": COLD, "fail": BLOOD}.get(state, INK))
            self.draw_bar()
        elif kind == "fail":
            self.detail_var.set(item[1])
            for text, cmd in (("Try again", item[2]), ("Open log folder", lambda: os.startfile(LOGS))):
                tk.Button(self.buttons, text=text, command=cmd, font=("Segoe UI", 10), bg=INK, fg=PAPER, activebackground=BLOOD, activeforeground="#FFFFFF",
                          relief="flat", padx=16, pady=6, cursor="hand2").pack(side="left", padx=6)
        elif kind == "call":
            item[1]()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.ui = Ui(self.root)
        self.svc = Services()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.run_pipeline()

    def run_pipeline(self):
        for child in self.ui.buttons.winfo_children():
            child.destroy()
        threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        ui = self.ui
        i = 0
        try:
            for i, fn in enumerate(PIPELINE):
                ui.post("step", i, "active", "checking")
                result = fn(ui, self.svc)
                ui.post("step", i, "ok", result)
            ui.detail("Opening HemoGrid")
            cmd = app_window_cmd()
            if cmd:
                subprocess.Popen(cmd)
            else:
                os.startfile(APP_URL)
            threading.Thread(target=ensure_shortcuts, daemon=True).start()
            time.sleep(1.5)
            ui.post("call", self.hide_and_watch)
        except Exception as e:
            log("pipeline failed: " + repr(e))
            ui.post("step", i, "fail", "failed")
            ui.post("fail", str(e), self.run_pipeline)

    def hide_and_watch(self):
        log("app window opened, hiding launcher and watching it")
        self.root.withdraw()
        self.opened_at, self.seen, self.gone = time.time(), False, 0
        self.watch()

    def watch(self):
        if app_windows():
            self.seen, self.gone = True, 0
        else:
            self.gone += 1
            if (self.seen and self.gone >= 3) or (not self.seen and time.time() - self.opened_at > 90):
                self.shutdown()
                return
        self.root.after(1000, self.watch)

    def shutdown(self):
        log("app window closed, stopping services")
        try:
            self.svc.stop_all()
        finally:
            self.root.destroy()

    def close(self):
        self.svc.stop_all()
        self.root.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    if "--stop" in sys.argv:
        Services().stop_all(force=True)
        return
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\HemoGridLauncher")
    if ctypes.windll.kernel32.GetLastError() == 183:
        cmd = app_window_cmd()
        if cmd:
            subprocess.Popen(cmd)
        return
    App().root.mainloop()
    ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
