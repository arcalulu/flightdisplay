#!/usr/bin/env python3
"""Mises a jour de flightdisplay depuis GitHub (via git) avec suivi de progression pour webadmin.

Principe : le depot Git de l'installation est compare a origin/<branche>. La mise a jour recupere les
nouveaux commits (fast-forward uniquement), installe les bibliotheques si necessaire, controle le code,
relance l'affichage puis webadmin. En cas d'echec, la version precedente est restauree.
Bibliotheque standard uniquement.
"""
import collections, json, os, re, shutil, subprocess, sys, threading, time

STEPS = [  # (identifiant, libelle, poids dans la barre de progression)
    ("check", "Vérifications", 5),
    ("fetch", "Téléchargement depuis GitHub", 30),
    ("apply", "Application de la nouvelle version", 5),
    ("deps", "Bibliothèques Python", 30),
    ("verify", "Contrôle du code", 5),
    ("display", "Relance de l'affichage", 10),
    ("web", "Redémarrage de webadmin", 15),
]
CHECK_EVERY = 12 * 3600
MIN_FREE_MB = 100
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

# Dependances importees par build_map_vector.py et absentes du venv (meme analyse que install.sh).
MAP_DEPS_SCRIPT = r'''
import ast, importlib.util, os, sys
root = sys.argv[1]
tree = ast.parse(open(os.path.join(root, "build_map_vector.py"), encoding="utf-8-sig").read())
names = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        names |= {a.name.split(".")[0] for a in n.names}
    elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
        names.add(n.module.split(".")[0])
alias = {"PIL": "pillow", "yaml": "pyyaml", "cv2": "opencv-python-headless", "sklearn": "scikit-learn",
         "skimage": "scikit-image", "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "OpenSSL": "pyOpenSSL"}
for name in sorted(names):
    if name in getattr(sys, "stdlib_module_names", ()):
        continue
    if os.path.exists(os.path.join(root, name + ".py")) or os.path.isdir(os.path.join(root, name)):
        continue
    if importlib.util.find_spec(name) is None:
        print(name, alias.get(name, name))
'''


class UpdateError(ValueError):
    """Erreur affichable telle quelle a l'utilisateur."""


class Updater:
    def __init__(self, S, svc_state, screen_off, build_running, restart_web):
        self.S = S
        self.svc_state = svc_state
        self.screen_off = screen_off
        self.build_running = build_running
        self.restart_web = restart_web
        self.busy = threading.Lock()        # une seule operation git a la fois
        self.mu = threading.Lock()          # protege self.st
        self.frac = 0.0
        self.cur = -1
        self.t_step = 0.0
        self.st = self._fresh()
        self.hist = []
        self.current = None
        self._load()
        self._refresh_history()

    # ------------------------------------------------------------ etat
    def _fresh(self):
        return dict(running=False, ok=None, error="", done_msg="", started=None, finished=None, from_label="", to_label="",
                    steps=[dict(id=i, label=l, status="pending", detail="") for i, l, _ in STEPS],
                    lines=collections.deque(maxlen=600), live="", check=None, restarting=False)

    def _state_file(self):
        return os.path.join(self.S.APP_DIR, "cache", "update.json")

    def _save(self):
        with self.mu:
            d = dict(ok=self.st["ok"], error=self.st["error"], done_msg=self.st["done_msg"], started=self.st["started"],
                     finished=self.st["finished"], from_label=self.st["from_label"], to_label=self.st["to_label"],
                     steps=self.st["steps"], lines=list(self.st["lines"]), check=self.st["check"],
                     restarting=self.st["restarting"], running=self.st["running"])
        try:
            path = self._state_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(d, fh)
            os.replace(tmp, path)
        except OSError:
            pass

    def _load(self):
        """Relit le dernier etat : apres le redemarrage de webadmin, la mise a jour est consideree comme terminee."""
        try:
            with open(self._state_file(), encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            return
        if not isinstance(d, dict):
            return
        st = self.st
        for k in ("ok", "error", "done_msg", "started", "finished", "from_label", "to_label", "check"):
            if k in d:
                st[k] = d[k]
        if isinstance(d.get("steps"), list) and len(d["steps"]) == len(STEPS):
            st["steps"] = d["steps"]
        st["lines"].extend(d.get("lines") or [])
        if d.get("restarting"):
            st["steps"][-1].update(status="done", detail="")
            st["ok"], st["error"], st["finished"] = True, "", time.time()
            st["done_msg"] = "Mise à jour terminée : webadmin tourne maintenant en " + (st["to_label"] or "nouvelle version") + "."
            st["lines"].append("Webadmin redémarré : mise à jour terminée.")
            st["check"] = None  # l'etat des versions a change : une nouvelle verification s'impose
            self._save()
        elif d.get("running"):
            st["ok"], st["error"] = False, "La mise à jour a été interrompue (webadmin s'est arrêté pendant l'opération)."
            for s in st["steps"]:
                if s["status"] == "running":
                    s["status"] = "error"

    def running(self):
        return self.st["running"]

    def available(self):
        c = self.st.get("check")
        return bool(c and c.get("ok") and c.get("behind", 0) > 0)

    def state(self):
        with self.mu:
            st = self.st
            steps = [dict(s) for s in st["steps"]]
            if st["running"] and 0 <= self.cur < len(steps):
                steps[self.cur]["elapsed"] = int(time.time() - self.t_step)
            return dict(running=st["running"], ok=st["ok"], error=st["error"], done_msg=st["done_msg"], started=st["started"],
                        finished=st["finished"], from_label=st["from_label"], to_label=st["to_label"], steps=steps,
                        pct=self._pct(), lines=list(st["lines"])[-400:], live=st["live"], check=st["check"],
                        restarting=st["restarting"], auto=self.S.UPDATE_AUTO, history=self.hist, current=self.current)

    def _pct(self):
        total = sum(w for _, _, w in STEPS)
        done = 0.0
        for i, (_, _, w) in enumerate(STEPS):
            s = self.st["steps"][i]["status"]
            if s in ("done", "skipped"):
                done += w
            elif s == "running":
                done += w * self.frac
        if self.st["ok"]:
            return 100
        return int(done * 100 / total)

    def _log(self, msg):
        with self.mu:
            self.st["lines"].append(msg)
            self.st["live"] = ""

    def _begin(self, i, detail=""):
        with self.mu:
            self.cur, self.frac, self.t_step = i, 0.0, time.time()
            self.st["steps"][i].update(status="running", detail=detail)

    def _end(self, i, status="done", detail=""):
        with self.mu:
            self.st["steps"][i].update(status=status, detail=detail)
            self.st["live"] = ""
            self.frac = 0.0

    # ------------------------------------------------------------ git
    def _env(self):
        return dict(os.environ, GIT_TERMINAL_PROMPT="0", LC_ALL="C", GIT_PAGER="cat", GIT_OPTIONAL_LOCKS="0")

    def _git(self, *args, timeout=60):
        try:
            r = subprocess.run(["git", *args], cwd=self.S.APP_DIR, capture_output=True, text=True, timeout=timeout,
                               errors="replace", env=self._env())
        except FileNotFoundError:
            raise UpdateError("git n'est pas installé sur ce Raspberry Pi (sudo apt install git).")
        except subprocess.TimeoutExpired:
            raise UpdateError("git : délai dépassé (connexion à GitHub trop lente ?).")
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def _git_ok(self, *args, timeout=60):
        rc, out, err = self._git(*args, timeout=timeout)
        if rc != 0:
            raise UpdateError("git " + args[0] + " a échoué : " + (err or out or "erreur inconnue"))
        return out

    def _branch(self):
        rc, out, _ = self._git("rev-parse", "--abbrev-ref", "HEAD")
        b = out if rc == 0 and out and out != "HEAD" else "main"
        if not BRANCH_RE.match(b):
            raise UpdateError("nom de branche non pris en charge : " + b)
        return b

    def _require_repo(self):
        if not os.path.isdir(os.path.join(self.S.APP_DIR, ".git")):
            raise UpdateError("Cette installation n'est pas un dépôt Git (copie manuelle des fichiers ?). "
                              "Relancez l'installeur pour pouvoir utiliser les mises à jour.")
        rc, out, _ = self._git("remote", "get-url", "origin")
        if rc != 0 or not out:
            raise UpdateError("Le dépôt Git n'a pas de remote « origin » : impossible de joindre GitHub.")

    def _info(self, ref):
        out = self._git_ok("log", "-1", "--format=%H%x1f%h%x1f%cs%x1f%s", ref)
        h, short, date, subject = (out.split("\x1f") + ["", "", "", ""])[:4]
        rc, desc, _ = self._git("describe", "--tags", "--always", ref)
        return dict(hash=h, short=short, date=date, subject=subject, label=desc if rc == 0 and desc else short)

    def _dirty(self):
        out = self._git_ok("-c", "core.fileMode=false", "status", "--porcelain", "--untracked-files=no")
        return [l[3:] for l in out.splitlines() if l.strip()]

    # ------------------------------------------------------------ historique des versions (changelog)
    def _history(self, ref, new=0, n=30):
        """Derniers commits de ref ; les `new` premiers sont ceux qui ne sont pas encore installes."""
        out = self._git_ok("log", "-n", str(n), "--format=%h%x1f%cs%x1f%s%x1f%D", ref)
        total = int(self._git_ok("rev-list", "--count", ref))  # numero de version = rang du commit dans l'historique
        res = []
        for i, l in enumerate(out.splitlines()):
            p = (l.split("\x1f") + ["", "", "", ""])[:4]
            tag = next((t[5:] for t in p[3].split(", ") if t.startswith("tag: ")), "")
            res.append(dict(short=p[0], date=p[1], subject=p[2], tag=tag, new=i < new, num=total - i))
        return res

    def _refresh_history(self):
        try:
            if os.path.isdir(os.path.join(self.S.APP_DIR, ".git")):
                self.hist = self._history("HEAD")
                self.current = self._info("HEAD")
        except Exception:
            pass

    # ------------------------------------------------------------ verification de disponibilite
    def check(self):
        if not self.busy.acquire(blocking=False):
            raise UpdateError("Une opération est déjà en cours.")
        try:
            try:
                res = self._check()
            except UpdateError as e:
                res = dict(ok=False, error=str(e), checked_at=time.time())
            with self.mu:
                self.st["check"] = res
            self._save()
            return res
        finally:
            self.busy.release()

    def _check(self):
        self._require_repo()
        branch = self._branch()
        rc, out, err = self._git("fetch", "--quiet", "--force", "--tags", "origin",
                                 "+refs/heads/%s:refs/remotes/origin/%s" % (branch, branch), timeout=90)
        if rc != 0:
            raise UpdateError("Impossible de joindre GitHub : " + (err or out or "erreur inconnue"))
        remote_ref = "origin/" + branch
        cur, latest = self._info("HEAD"), self._info(remote_ref)
        behind = int(self._git_ok("rev-list", "--count", "HEAD.." + remote_ref))
        ahead = int(self._git_ok("rev-list", "--count", remote_ref + "..HEAD"))
        commits = []
        if behind:
            for l in self._git_ok("log", "-n", "40", "--format=%h%x1f%cs%x1f%s", "HEAD.." + remote_ref).splitlines():
                p = l.split("\x1f")
                if len(p) == 3:
                    commits.append(dict(short=p[0], date=p[1], subject=p[2]))
        files = self._git_ok("diff", "--name-only", "HEAD", remote_ref).splitlines() if behind else []
        dirty = self._dirty()
        self.hist = self._history(remote_ref, behind)
        self.current = cur
        return dict(ok=True, checked_at=time.time(), branch=branch, current=cur, latest=latest, behind=behind, ahead=ahead,
                    commits=commits, files=files[:60], dirty=dirty,
                    installer_changed="install.sh" in files,
                    can_update=behind > 0 and ahead == 0 and not dirty)

    def auto_loop(self):
        """Verification periodique en arriere-plan (desactivable dans les reglages)."""
        time.sleep(90)
        while True:
            try:
                if self.S.UPDATE_AUTO and not self.st["running"]:
                    self.check()
            except Exception:
                pass
            time.sleep(CHECK_EVERY)

    # ------------------------------------------------------------ execution d'une commande avec progression
    def _stream(self, cmd, timeout, git_progress=False):
        p = subprocess.Popen(cmd, cwd=self.S.APP_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self._env())
        timer = threading.Timer(timeout, p.kill)
        timer.start()
        buf = b""
        try:
            while True:
                chunk = os.read(p.stdout.fileno(), 2048)
                if not chunk:
                    break
                buf += chunk
                while True:
                    m = re.search(rb"[\r\n]", buf)
                    if not m:
                        break
                    seg, transient = buf[:m.start()], buf[m.start():m.end()] == b"\r"
                    buf = buf[m.end():]
                    self._line(seg.decode("utf-8", "replace").strip(), transient, git_progress)
            if buf.strip():
                self._line(buf.decode("utf-8", "replace").strip(), False, git_progress)
        finally:
            timer.cancel()
        rc = p.wait()
        with self.mu:
            self.st["live"] = ""
        return rc

    def _line(self, text, transient, git_progress):
        if not text:
            return
        if git_progress:
            m = re.search(r"(\d{1,3})%", text)
            if m:
                p = min(100, int(m.group(1))) / 100.0
                if text.startswith("Receiving objects"):
                    self.frac = max(self.frac, 0.8 * p)
                elif text.startswith("Resolving deltas"):
                    self.frac = max(self.frac, 0.8 + 0.2 * p)
        if transient:
            with self.mu:
                self.st["live"] = text
        else:
            self._log(text)

    # ------------------------------------------------------------ mise a jour
    def start(self):
        if self.build_running():
            raise UpdateError("Une reconstruction de la carte est en cours : attendez qu'elle se termine.")
        if not self.busy.acquire(blocking=False):
            raise UpdateError("Une opération est déjà en cours.")
        with self.mu:
            old = self.st["check"]
            self.st = self._fresh()
            self.st.update(running=True, started=time.time(), check=old)
            self.cur, self.frac = -1, 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def _fail(self, msg, old, applied):
        if applied and old:
            self._log("Retour à la version précédente (%s)..." % old[:7])
            rc, out, err = self._git("reset", "--hard", old, timeout=120)
            self._refresh_history()
            self._log("Version précédente restaurée." if rc == 0 else "ÉCHEC de la restauration : " + (err or out))
        with self.mu:
            st = self.st
            st.update(running=False, ok=False, error=msg, finished=time.time())
            for s in st["steps"]:
                if s["status"] == "running":
                    s["status"] = "error"
            st["lines"].append("ERREUR : " + msg)
            st["check"] = None
        self._save()

    def _run(self):
        old, applied, released = "", False, False
        try:
            # 1. verifications
            self._begin(0)
            self._require_repo()
            branch = self._branch()
            free = shutil.disk_usage(self.S.APP_DIR).free // (1024 * 1024)
            if free < MIN_FREE_MB:
                raise UpdateError("Espace disque insuffisant (%d Mo libres, %d Mo nécessaires)." % (free, MIN_FREE_MB))
            dirty = self._dirty()
            if dirty:
                raise UpdateError("Des fichiers du logiciel ont été modifiés localement (%s) : mise à jour refusée pour ne rien écraser."
                                  % ", ".join(dirty[:5]))
            cur = self._info("HEAD")
            old = cur["hash"]
            self.st["from_label"] = cur["label"]
            was_active = self.svc_state() == "active"
            self._log("Version actuelle : %s (%s) sur la branche %s" % (cur["label"], cur["date"], branch))
            self._end(0)

            # 2. telechargement
            self._begin(1)
            remote_ref = "origin/" + branch
            rc = self._stream(["git", "fetch", "--progress", "--force", "--tags", "origin",
                               "+refs/heads/%s:refs/remotes/origin/%s" % (branch, branch)], 600, git_progress=True)
            if rc != 0:
                raise UpdateError("Le téléchargement depuis GitHub a échoué (voir le journal ci-dessous).")
            latest = self._info(remote_ref)
            behind = int(self._git_ok("rev-list", "--count", "HEAD.." + remote_ref))
            ahead = int(self._git_ok("rev-list", "--count", remote_ref + "..HEAD"))
            if behind == 0:
                self._end(1)
                for i in range(2, len(STEPS)):
                    self._end(i, "skipped")
                with self.mu:
                    self.st.update(running=False, ok=True, finished=time.time(), to_label=cur["label"],
                                   done_msg="Aucune mise à jour : vous avez déjà la dernière version (%s)." % cur["label"])
                    self.st["lines"].append("Déjà à jour.")
                    self.st["check"] = None
                self._save()
                return
            if ahead:
                raise UpdateError("Cette installation contient des commits locaux absents de GitHub : mise à jour impossible sans conflit.")
            self.st["to_label"] = latest["label"]
            changed = self._git_ok("diff", "--name-only", old, remote_ref).splitlines()
            self._log("Nouvelle version : %s (%s) - %d fichier(s) modifié(s)" % (latest["label"], latest["date"], len(changed)))
            self._end(1)

            # 3. application
            self._begin(2)
            rc = self._stream(["git", "merge", "--ff-only", remote_ref], 120)
            if rc != 0:
                raise UpdateError("L'application de la nouvelle version a échoué.")
            applied = True
            self._end(2)

            # 4. bibliotheques
            self._begin(3)
            py = self.S.PYTHON
            pip = [py, "-m", "pip", "--disable-pip-version-check", "install", "--prefer-binary", "--progress-bar", "off"]
            todo = False
            if "requirements.txt" in changed and os.path.exists(os.path.join(self.S.APP_DIR, "requirements.txt")):
                todo = True
                self._log("requirements.txt a changé : installation des bibliothèques (peut être long sur un Pi Zero)...")
                if self._stream(pip + ["-r", "requirements.txt"], 1800) != 0:
                    raise UpdateError("L'installation des bibliothèques Python a échoué.")
            if "build_map_vector.py" in changed:
                out = subprocess.run([py, "-c", MAP_DEPS_SCRIPT, self.S.APP_DIR], capture_output=True, text=True, errors="replace",
                                     cwd=self.S.APP_DIR, timeout=60).stdout
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) == 2:
                        todo = True
                        self._log("Dépendance de la carte manquante : " + parts[1])
                        if self._stream(pip + [parts[1]], 1800) != 0:
                            raise UpdateError("L'installation de %s a échoué." % parts[1])
            self._end(3, "done" if todo else "skipped", "" if todo else "aucune nouvelle bibliothèque")

            # 5. controle du code
            self._begin(4)
            files = [f for f in ("main.py", "build_map_vector.py") if os.path.exists(os.path.join(self.S.APP_DIR, f))]
            if files and self._stream([py, "-m", "py_compile"] + files, 120) != 0:
                raise UpdateError("Le code du programme d'affichage de la nouvelle version contient une erreur.")
            env = dict(self._env(), WEBADMIN_INI=self.S.CONFIG)
            r = subprocess.run([sys.executable, "-c", "import webadmin"], cwd=self.S.APP_DIR, capture_output=True, text=True,
                               errors="replace", timeout=120, env=env)
            if r.returncode != 0:
                self._log((r.stderr or r.stdout).strip()[-600:])
                raise UpdateError("Le code de webadmin de la nouvelle version ne se charge pas.")
            self._log("Code contrôlé : aucune erreur.")
            self._end(4)

            # 6. affichage
            self._begin(5)
            if was_active and not self.screen_off():
                self._log("Relance du programme d'affichage...")
                ok, out = self._sudo_restart()
                if not ok:
                    raise UpdateError("Impossible de relancer le programme d'affichage : " + (out or "échec"))
                time.sleep(4)
                stable = True
                for _ in range(3):
                    if self.svc_state() != "active":
                        stable = False
                        break
                    time.sleep(2)
                if not stable:
                    self._log("Le programme d'affichage ne reste pas actif avec la nouvelle version.")
                    self._git("reset", "--hard", old, timeout=120)
                    applied = False
                    self._sudo_restart()
                    self._log("Version précédente restaurée et affichage relancé.")
                    raise UpdateError("La nouvelle version ne démarre pas : la version précédente a été restaurée.")
                self._end(5)
            else:
                self._end(5, "skipped", "affichage arrêté ou en veille : il utilisera la nouvelle version à son prochain démarrage")

            # 7. webadmin
            self._begin(6)
            self._log("Redémarrage de webadmin pour charger la nouvelle version...")
            with self.mu:
                self.st.update(running=False, restarting=True)
            self._save()
            released = True
            self.busy.release()
            threading.Timer(2.0, self._restart_web_safe).start()
        except UpdateError as e:
            self._fail(str(e), old, applied)
        except subprocess.TimeoutExpired as e:
            self._fail("Délai dépassé : " + str(e.cmd[0] if e.cmd else "commande"), old, applied)
        except Exception as e:
            self._fail(type(e).__name__ + " : " + str(e), old, applied)
        finally:
            if not released:
                try:
                    self.busy.release()
                except RuntimeError:
                    pass

    def _sudo_restart(self):
        try:
            r = subprocess.run(self.S.SUDO + [self.S.SYSTEMCTL, "restart", self.S.SERVICE], capture_output=True, text=True,
                               timeout=60, errors="replace")
            return r.returncode == 0, (r.stdout + r.stderr).strip()
        except Exception as e:
            return False, str(e)

    def _restart_web_safe(self):
        try:
            self.restart_web()
        except Exception as e:
            self._log("Le redémarrage automatique de webadmin a échoué (%s) : relancez-le manuellement." % e)
            with self.mu:
                self.st.update(restarting=False, ok=True, finished=time.time(),
                               done_msg="Mise à jour appliquée, mais webadmin doit être redémarré manuellement (sudo systemctl restart flightadmin).")
                self.st["steps"][-1].update(status="error")
            self._save()
