#!/usr/bin/env bash
# =============================================================================
#  Flight display - installation interactive pour Raspberry Pi OS Lite (32 bits)
#
#  Usage :  bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh)
#      ou   git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay && bash ~/flightdisplay/install.sh
#
#  Options : --help   --dry-run (simulation, rien n'est installe)
#  Relancer le script met a jour le logiciel et conserve votre configuration.
# =============================================================================
set -uo pipefail

REPO_URL="${FD_REPO_URL:-https://github.com/arcalulu/flightdisplay.git}"
BRANCH="${FD_BRANCH:-main}"
DRY="${FD_DRY_RUN:-}"
INPUT="${FD_INPUT:-/dev/tty}"
LOG="${FD_LOG:-$HOME/flightdisplay-install.log}"
SERVICE="flightdisplay"
TOTAL=12
CUR=0
SOFT=""
KEEPALIVE=""
NEED_REBOOT=""
MAP_OK=""
WARNINGS=()

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    -h|--help)
      sed -n '2,10p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'
      exit 0 ;;
  esac
done

# ------------------------------------------------------------------ affichage
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != "dumb" ]; then
  UI=1
  R=$'\033[0m'; B=$'\033[1m'; DIM=$'\033[2m'
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[34m'; MAG=$'\033[35m'; CYN=$'\033[36m'
else
  UI=""; R=""; B=""; DIM=""; RED=""; GRN=""; YEL=""; BLU=""; MAG=""; CYN=""
fi
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
  *UTF-8*|*utf8*|*UTF8*) FULL="█"; EMPTY="░"; OKC="✔"; KOC="✖"; WRN="⚠"; SP=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏) ;;
  *) FULL="#"; EMPTY="-"; OKC="OK"; KOC="!!"; WRN="!"; SP=('|' '/' '-' '\\') ;;
esac

cols() { tput cols 2>/dev/null || echo 80; }

bar() {  # pourcentage largeur
  local p=$1 w=${2:-30} f e i
  [ "$p" -lt 0 ] && p=0
  [ "$p" -gt 100 ] && p=100
  f=$((p * w / 100)); e=$((w - f))
  printf '%s' "$GRN"
  for ((i = 0; i < f; i++)); do printf '%s' "$FULL"; done
  printf '%s%s' "$R" "$DIM"
  for ((i = 0; i < e; i++)); do printf '%s' "$EMPTY"; done
  printf '%s %3d%%' "$R" "$p"
}

banner() {
  printf '\n%s' "$CYN"
  cat <<'EOF'
  _____ _ _       _     _       _ _           _
 |  ___| (_) __ _| |__ | |_  __| (_)___ _ __ | | __ _ _   _
 | |_  | | |/ _` | '_ \| __|/ _` | / __| '_ \| |/ _` | | | |
 |  _| | | | (_| | | | | |_| (_| | \__ \ |_) | | (_| | |_| |
 |_|   |_|_|\__, |_| |_|\__|\__,_|_|___/ .__/|_|\__,_|\__, |
            |___/                      |_|            |___/
EOF
  printf '%s\n  %sInstallation automatique pour Raspberry Pi%s\n' "$R" "$B" "$R"
  if [ -n "$DRY" ]; then printf '  %s*** MODE SIMULATION : rien ne sera installé ***%s\n' "$YEL" "$R"; fi
  printf '\n'
}

title() { printf '\n%s%s== %s ==%s\n\n' "$B" "$MAG" "$1" "$R"; }
info()  { printf '  %s•%s %s\n' "$BLU" "$R" "$1"; }
ok()    { printf '  %s%s%s %s\n' "$GRN" "$OKC" "$R" "$1"; }
warn()  { printf '  %s%s%s %s\n' "$YEL" "$WRN" "$R" "$1"; WARNINGS+=("$1"); }
die()   { printf '\n  %s%s %s%s\n' "$RED" "$KOC" "$1" "$R"; printf '  %sJournal détaillé : %s%s\n\n' "$DIM" "$LOG" "$R"; exit 1; }

step() {
  CUR=$((CUR + 1))
  printf '\n%s%s[%d/%d]%s %s%s%s\n  ' "$B" "$CYN" "$CUR" "$TOTAL" "$R" "$B" "$1" "$R"
  bar $(((CUR - 1) * 100 / TOTAL)) 40
  printf '\n\n'
}

cleanup() {
  if [ -n "$KEEPALIVE" ]; then kill "$KEEPALIVE" 2>/dev/null; fi
  if [ -n "$UI" ]; then tput cnorm 2>/dev/null; fi
  return 0
}
trap cleanup EXIT
trap 'printf "\n  %sInstallation interrompue.%s\n" "$YEL" "$R"; exit 130' INT TERM

# ------------------------------------------------------------------ execution avec progression
LOGPOS=0
progress_pct() {
  local chunk p
  chunk=$(tail -c +$((LOGPOS + 1)) "$LOG" 2>/dev/null | tail -c 600 | tr '\r' '\n')
  p=$(printf '%s\n' "$chunk" | grep -E '^(dlstatus|pmstatus):' | tail -n1 | awk -F: '{printf "%d", $3}')
  if [ -z "$p" ]; then
    p=$(printf '%s\n' "$chunk" | grep -oE '[0-9]{1,3}%' | tail -n1 | tr -d '%')
  fi
  echo "${p:--1}"
}

last_line() {
  tail -c +$((LOGPOS + 1)) "$LOG" 2>/dev/null | tail -c 400 | tr '\r' '\n' \
    | grep -vE '^\s*$|^(dlstatus|pmstatus):' | tail -n1 | tr -d '\033' | cut -c1-"$1"
}

run_step() {  # libelle commande...
  local label="$1"; shift
  local start=$SECONDS pid rc i=0 pct line room c
  printf '\n### %s\n' "$label" >>"$LOG"
  LOGPOS=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
  ( "$@" ) </dev/null >>"$LOG" 2>&1 &
  pid=$!
  if [ -n "$UI" ]; then
    tput civis 2>/dev/null
    while kill -0 "$pid" 2>/dev/null; do
      c=$(cols)
      pct=$(progress_pct)
      printf '\r\033[K  %s%s%s %s %s(%ds)%s' "$CYN" "${SP[i % ${#SP[@]}]}" "$R" "$label" "$DIM" "$((SECONDS - start))" "$R"
      if [ "$pct" -ge 0 ] 2>/dev/null; then printf '  '; bar "$pct" 18; fi
      room=$((c - ${#label} - 36))
      if [ "$room" -gt 12 ]; then
        line=$(last_line "$room")
        if [ -n "$line" ]; then printf '  %s%s%s' "$DIM" "$line" "$R"; fi
      fi
      i=$((i + 1))
      sleep 0.12
    done
    tput cnorm 2>/dev/null
  fi
  wait "$pid"; rc=$?
  if [ $rc -eq 0 ]; then
    if [ -n "$UI" ]; then printf '\r\033[K'; fi
    printf '  %s%s%s %s %s(%ds)%s\n' "$GRN" "$OKC" "$R" "$label" "$DIM" "$((SECONDS - start))" "$R"
    return 0
  fi
  if [ -n "$UI" ]; then printf '\r\033[K'; fi
  printf '  %s%s %s%s\n' "$RED" "$KOC" "$label" "$R"
  printf '%s' "$DIM"; tail -n 12 "$LOG" | sed 's/^/      /'; printf '%s\n' "$R"
  if [ -n "$SOFT" ]; then return $rc; fi
  die "Échec de l'étape : $label"
}
soft() { SOFT=1 run_step "$@"; local rc=$?; SOFT=""; return $rc; }

# ------------------------------------------------------------------ questions
{ exec 3<"$INPUT"; } 2>/dev/null || die "Aucun terminal interactif disponible (lancez la commande depuis une session SSH)."

ask() {  # variable "question" "defaut" [secret]
  local var="$1" q="$2" def="${3:-}" secret="${4:-}" ans
  if [ -n "$def" ]; then printf '  %s%s%s %s[%s]%s : ' "$B" "$q" "$R" "$DIM" "$def" "$R"
  else printf '  %s%s%s : ' "$B" "$q" "$R"; fi
  if [ -n "$secret" ]; then IFS= read -r -s ans <&3 || ans=""; printf '\n'
  else IFS= read -r ans <&3 || ans=""; fi
  printf -v "$var" '%s' "${ans:-$def}"
}

yesno() {  # "question" defaut(o|n) -> 0 si oui
  local q="$1" def="${2:-o}" ans hint="O/n"
  [ "$def" = "n" ] && hint="o/N"
  printf '  %s%s%s %s[%s]%s : ' "$B" "$q" "$R" "$DIM" "$hint" "$R"
  IFS= read -r ans <&3 || ans=""
  ans="${ans:-$def}"
  case "$ans" in o|O|y|Y|oui|OUI|yes|YES) return 0 ;; *) return 1 ;; esac
}

num_in_range() {  # valeur min max
  awk -v x="$1" -v lo="$2" -v hi="$3" 'BEGIN{exit !(x ~ /^-?[0-9]+([.][0-9]+)?$/ && x+0>=lo && x+0<=hi)}'
}

geocode() {
  curl -fsS --max-time 15 -A "flightdisplay-installer/1.0 (github.com/arcalulu/flightdisplay)" \
    -G "https://nominatim.openstreetmap.org/search" --data-urlencode "q=$1" -d "format=json" -d "limit=1" 2>/dev/null \
    | python3 -c 'import sys,json
d=json.load(sys.stdin)
if not d: sys.exit(1)
print("%s|%s|%s" % (d[0]["lat"], d[0]["lon"], d[0]["display_name"]))'
}

gen_password() {
  python3 -c 'import secrets,string
a=string.ascii_letters+string.digits
print("".join(secrets.choice(a) for _ in range(12)))'
}

ini_set() {  # fichier section cle valeur
  FD_V="$4" python3 - "$1" "$2" "$3" <<'PY'
import os, re, sys
path, sec, key = sys.argv[1:4]
val = os.environ["FD_V"]
lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
cur, last, found = None, {}, None
for i, l in enumerate(lines):
    s = l.strip()
    m = re.match(r"^\[([^\]]+)\]$", s)
    if m:
        cur = m.group(1); last[cur] = i; continue
    if cur and s and s[0] not in "#;":
        m = re.match(r"^(\s*)([^\s#;=:][^=:]*?)\s*[=:]", l)
        if m:
            last[cur] = i
            if cur == sec and m.group(2).lower() == key.lower() and found is None:
                found = i
if found is not None:
    lines[found] = "%s = %s" % (key, val)
elif sec in last:
    lines.insert(last[sec] + 1, "%s = %s" % (key, val))
else:
    if lines and lines[-1].strip():
        lines.append("")
    lines += ["[%s]" % sec, "%s = %s" % (key, val)]
open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
}

collect_answers() {
  title "Vos informations"
  printf '  %sQuelques questions, puis l'"'"'installation se déroule seule (plusieurs minutes, selon votre Pi et votre connexion).%s\n\n' "$DIM" "$R"

  printf '  %s1. Votre position%s\n' "$B$BLU" "$R"
  printf '  %sSaisissez votre adresse (elle est envoyée une seule fois au service OpenStreetMap Nominatim\n  pour trouver les coordonnées), ou appuyez sur Entrée pour saisir les coordonnées.%s\n' "$DIM" "$R"
  LAT=""; LON=""
  local addr res
  while [ -z "$LAT" ]; do
    ask addr "Adresse (ou Entrée)" ""
    if [ -n "$addr" ]; then
      printf '  %sRecherche...%s\r' "$DIM" "$R"
      res=$(geocode "$addr") || res=""
      if [ -n "$res" ]; then
        IFS='|' read -r LAT LON NAME <<<"$res"
        LAT=$(printf '%.4f' "$LAT"); LON=$(printf '%.4f' "$LON")
        printf '\033[K  %sTrouvé :%s %s\n  %s(latitude %s, longitude %s, arrondies à 11 m)%s\n' "$GRN" "$R" "$NAME" "$DIM" "$LAT" "$LON" "$R"
        yesno "C'est bien là ?" o || { LAT=""; LON=""; }
      else
        printf '\033[K'; warn "Adresse introuvable. Réessayez ou saisissez les coordonnées."
      fi
    else
      printf '  %sAstuce : clic droit sur votre maison dans Google Maps ou OpenStreetMap, puis copier les coordonnées.%s\n' "$DIM" "$R"
      local la lo
      while true; do ask la "Latitude (ex. 48.8566)" ""; la=${la//,/.}; num_in_range "$la" -90 90 && break; warn "Latitude invalide (-90 à 90)."; done
      while true; do ask lo "Longitude (ex. 2.3522)" ""; lo=${lo//,/.}; num_in_range "$lo" -180 180 && break; warn "Longitude invalide (-180 à 180)."; done
      LAT="$la"; LON="$lo"
    fi
  done

  while true; do
    ask RADIUS "Rayon de la carte en km (1 à 200)" "20"; RADIUS=${RADIUS//,/.}
    num_in_range "$RADIUS" 1 200 && break; warn "Valeur invalide."
  done

  printf '\n  %s2. Résolution de la carte%s\n' "$B$BLU" "$R"
  printf '  %s1) 1920x1080   2) 1280x720 (recommandé sur Pi Zero : moins de charge)   3) autre%s\n' "$DIM" "$R"
  local rc; ask rc "Votre choix" "2"
  case "$rc" in
    1) MAPW=1920; MAPH=1080 ;;
    3) while true; do ask MAPW "Largeur en pixels" "1280"; [[ "$MAPW" =~ ^[0-9]{3,5}$ ]] && break; warn "Nombre invalide."; done
       while true; do ask MAPH "Hauteur en pixels" "720"; [[ "$MAPH" =~ ^[0-9]{3,5}$ ]] && break; warn "Nombre invalide."; done ;;
    *) MAPW=1280; MAPH=720 ;;
  esac

  printf '\n  %s3. Aéroport proche (facultatif)%s\n' "$B$BLU" "$R"
  while true; do
    ask AIRPORT "Code IATA à 3 lettres (ex. CDG), ou Entrée" ""; AIRPORT=$(printf '%s' "$AIRPORT" | tr '[:lower:]' '[:upper:]')
    if [ -z "$AIRPORT" ] || [[ "$AIRPORT" =~ ^[A-Z]{3}$ ]]; then break; fi
    warn "Code invalide."
  done

  printf '\n  %s4. Clé API CARTO%s\n' "$B$BLU" "$R"
  printf '  %sNécessaire pour construire la carte. Elle se crée sur votre compte CARTO. La saisie est masquée.%s\n' "$DIM" "$R"
  ask CARTO_KEY "Clé API CARTO (Entrée pour passer)" "" secret
  if [ -z "$CARTO_KEY" ]; then
    warn "Pas de clé : la carte ne sera pas construite maintenant (possible plus tard depuis webadmin)."
  fi

  printf '\n  %s5. Mot de passe de l'"'"'interface web%s\n' "$B$BLU" "$R"
  printf '  %sProtège l'"'"'accès à webadmin depuis votre réseau. Entrée = en générer un automatiquement.%s\n' "$DIM" "$R"
  WEBPW=""
  while [ -z "$WEBPW" ]; do
    local p1 p2
    ask p1 "Mot de passe (6 caractères minimum, Entrée = automatique)" "" secret
    if [ -z "$p1" ]; then WEBPW=$(gen_password); GENPW=1; ok "Mot de passe généré (affiché à la fin)."
    elif [ "${#p1}" -lt 6 ]; then warn "Trop court."
    else
      ask p2 "Confirmez le mot de passe" "" secret
      if [ "$p1" = "$p2" ]; then WEBPW="$p1"; else warn "Les deux saisies diffèrent."; fi
    fi
  done

  printf '\n  %s6. Home Assistant / MQTT (facultatif)%s\n' "$B$BLU" "$R"
  MQTT_ON=""
  if yesno "Configurer MQTT maintenant ?" n; then
    MQTT_ON=1
    ask MQTT_HOST "Adresse du serveur MQTT" ""
    ask MQTT_PORT "Port" "1883"
    ask MQTT_USER "Identifiant (Entrée si aucun)" ""
    ask MQTT_PASS "Mot de passe MQTT (Entrée si aucun)" "" secret
  fi

  printf '\n  %s7. Veille d'"'"'écran fiable%s\n' "$B$BLU" "$R"
  printf '  %sCorrectif qui empêche certains moniteurs de se rallumer seuls en veille (redémarrage conseillé).%s\n' "$DIM" "$R"
  HDMI_FIX=""; if yesno "Appliquer le correctif ?" o; then HDMI_FIX=1; fi

  printf '\n  %sRécapitulatif%s\n' "$B$BLU" "$R"
  printf '    Position : %s, %s   Rayon : %s km   Carte : %sx%s\n' "$LAT" "$LON" "$RADIUS" "$MAPW" "$MAPH"
  printf '    Aéroport : %s   Clé CARTO : %s\n' "${AIRPORT:-aucun}" "$([ -n "$CARTO_KEY" ] && echo fournie || echo non fournie)"
  printf '    MQTT : %s   Correctif écran : %s\n\n' "$([ -n "$MQTT_ON" ] && echo "$MQTT_HOST" || echo non)" "$([ -n "$HDMI_FIX" ] && echo oui || echo non)"
  yesno "Lancer l'installation ?" o || { printf '\n  Installation annulée.\n\n'; exit 0; }
}

# ------------------------------------------------------------------ verifications
preflight() {
  [ "$(id -u)" -ne 0 ] || [ -n "$DRY" ] || die "Ne lancez pas ce script avec sudo ni en root : utilisez votre utilisateur normal (il demandera sudo si besoin)."
  [ -r /etc/os-release ] && . /etc/os-release
  case "${ID:-}${ID_LIKE:-}" in *debian*|*raspbian*) ok "Système : ${PRETTY_NAME:-Debian}" ;; *) warn "Système non Debian/Raspberry Pi OS : l'installation peut échouer." ;; esac
  local model="" mem free arch
  [ -r /proc/device-tree/model ] && model=$(tr -d '\0' </proc/device-tree/model)
  if [ -n "$model" ]; then ok "Matériel : $model"; else warn "Matériel non identifié comme un Raspberry Pi."; fi
  arch=$(uname -m); info "Architecture : $arch"
  mem=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
  if [ "$mem" -ge 350 ]; then ok "Mémoire : ${mem} Mo"; else warn "Mémoire faible (${mem} Mo)."; fi
  free=$(df -Pm "$HOME" | awk 'NR==2 {print $4}')
  if [ "${free:-0}" -ge 1500 ]; then ok "Espace disque libre : ${free} Mo"; else warn "Espace disque limité (${free} Mo) : 1,5 Go conseillés."; fi
  command -v systemctl >/dev/null || die "systemd est requis."
  if [ -z "$DRY" ]; then
    if curl -fsI --max-time 15 https://github.com >/dev/null 2>&1; then ok "Connexion Internet"; else die "Pas de connexion Internet (vérifiez le Wi-Fi)."; fi
  fi
  case "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" in yes) ok "Horloge synchronisée" ;; *) warn "Horloge non synchronisée (NTP) : l'heure doit être exacte pour Flightradar24." ;; esac
}

need_sudo() {
  [ -n "$DRY" ] && return 0
  printf '  %sLe mot de passe sudo peut vous être demandé une fois.%s\n' "$DIM" "$R"
  sudo -v || die "sudo est nécessaire."
  ( while true; do sudo -n true 2>/dev/null; sleep 45; kill -0 "$$" 2>/dev/null || exit; done ) &
  KEEPALIVE=$!
}

# ------------------------------------------------------------------ etapes
if [ -n "$DRY" ]; then
  sudo() { echo "[simulation] sudo $*"; }
fi

apt_update()  { sudo DEBIAN_FRONTEND=noninteractive apt-get update -o APT::Status-Fd=1; }
apt_install() { sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -o APT::Status-Fd=1 -o Dpkg::Options::=--force-confold "$@"; }

fetch_project() {
  if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only --progress
  elif [ -e "$APP_DIR" ] && [ -n "$(ls -A "$APP_DIR" 2>/dev/null)" ]; then
    echo "Le dossier $APP_DIR existe et n'est pas un dépôt Git" >&2; return 1
  else
    git clone --progress --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
}

make_venv() {
  [ -x "$APP_DIR/venv/bin/python" ] || python3 -m venv --system-site-packages "$APP_DIR/venv"
  if [ -n "$DRY" ]; then echo "[simulation] pip install -r requirements.txt"; return 0; fi
  "$APP_DIR/venv/bin/python" -m pip install --upgrade pip --quiet
  "$APP_DIR/venv/bin/python" -m pip install --prefer-binary -r "$APP_DIR/requirements.txt"
  "$APP_DIR/venv/bin/python" -c "import pygame, requests, FlightRadarAPI; print('modules ok')"
}

map_deps() {
  local py="$APP_DIR/venv/bin/python" list name pipn
  [ -f "$APP_DIR/build_map_vector.py" ] || return 0
  list=$("$py" - "$APP_DIR" <<'PY'
import ast, importlib.util, os, sys
root = sys.argv[1]
tree = ast.parse(open(os.path.join(root, "build_map_vector.py"), encoding="utf-8").read())
names = set()
for n in ast.walk(tree):
    if isinstance(n, ast.Import):
        names |= {a.name.split(".")[0] for a in n.names}
    elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
        names.add(n.module.split(".")[0])
alias = {"PIL": "pillow", "yaml": "pyyaml", "cv2": "opencv-python-headless", "sklearn": "scikit-learn",
         "skimage": "scikit-image", "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "OpenSSL": "pyOpenSSL"}
for name in sorted(names):
    if name in sys.stdlib_module_names:
        continue
    if os.path.exists(os.path.join(root, name + ".py")) or os.path.isdir(os.path.join(root, name)):
        continue
    if importlib.util.find_spec(name) is None:
        print(name, alias.get(name, name))
PY
  )
  if [ -z "$list" ]; then echo "Aucune dépendance supplémentaire"; return 0; fi
  if [ -n "$DRY" ]; then echo "[simulation] pip install : $list"; return 0; fi
  while read -r name pipn; do
    [ -z "$name" ] && continue
    echo "Installation de $pipn"
    "$py" -m pip install --prefer-binary "$pipn" || return 1
  done <<<"$list"
}

write_configs() {
  cd "$APP_DIR" || return 1
  [ -f config.ini ] || cp config.ini.example config.ini
  ini_set config.ini position latitude "$LAT"
  ini_set config.ini position longitude "$LON"
  ini_set config.ini position radius_km "$RADIUS"
  ini_set config.ini display fullscreen true
  ini_set config.ini display width "$MAPW"
  ini_set config.ini display height "$MAPH"
  ini_set config.ini ground airport_iata "$AIRPORT"
  ini_set config.ini map carto_key "$CARTO_KEY"
  chmod 600 config.ini
  [ -f webadmin.ini ] || cp webadmin.ini.example webadmin.ini
  ini_set webadmin.ini server password "$WEBPW"
  if [ -n "$MQTT_ON" ]; then
    ini_set webadmin.ini mqtt enabled true
    ini_set webadmin.ini mqtt host "$MQTT_HOST"
    ini_set webadmin.ini mqtt port "$MQTT_PORT"
    ini_set webadmin.ini mqtt user "$MQTT_USER"
    ini_set webadmin.ini mqtt password "$MQTT_PASS"
  fi
  chmod 600 webadmin.ini
}

build_map() {
  cd "$APP_DIR" || return 1
  if [ -n "$DRY" ]; then echo "[simulation] construction de la carte"; sleep 2; touch background.png map_meta.json; return 0; fi
  "$APP_DIR/venv/bin/python" -u build_map_vector.py
}

install_services() {
  local user; user=$(id -un)
  sudo usermod -aG video,render,input,audio "$user"
  sudo tee /etc/systemd/system/$SERVICE.service >/dev/null <<EOF
[Unit]
Description=Flight display
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
User=$user
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/main.py
SupplementaryGroups=video render input audio
Environment=PYGAME_HIDE_SUPPORT_PROMPT=1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo tee /usr/local/bin/fd >/dev/null <<'EOF'
#!/bin/sh
SVC=flightdisplay
case "$1" in
  logs)    journalctl -u "$SVC" -f -n 50 --no-pager ;;
  status)  systemctl status "$SVC" --no-pager ;;
  start|stop|restart) sudo /usr/bin/systemctl "$1" "$SVC" ;;
  *) echo "usage : fd logs|status|start|stop|restart" >&2; exit 2 ;;
esac
EOF
  sudo chmod 755 /usr/local/bin/fd
  sudo systemctl daemon-reload
}

install_webadmin() {
  cd "$APP_DIR" || return 1
  sudo bash "$APP_DIR/install_webadmin.sh"
}

hdmi_fix() {
  local f=/boot/firmware/cmdline.txt
  [ -f "$f" ] || f=/boot/cmdline.txt
  [ -f "$f" ] || { echo "cmdline.txt introuvable"; return 1; }
  if grep -q 'vc4.force_hotplug' "$f"; then echo "Correctif déjà présent"; return 0; fi
  sudo cp "$f" "$f.bak"
  sudo sed -i '1 s/$/ vc4.force_hotplug=1/' "$f"
}

start_all() {
  if [ -n "$MAP_OK" ]; then
    sudo systemctl enable --now $SERVICE
    sleep 6
    [ -n "$DRY" ] || systemctl is-active --quiet $SERVICE
  else
    sudo systemctl enable $SERVICE
    echo "Carte absente : le programme d'affichage démarrera après la construction de la carte"
  fi
}

check_web() {
  if [ -n "$DRY" ]; then echo "[simulation] test de webadmin"; return 0; fi
  local port i
  port=$(sed -n 's/^port[[:space:]]*=[[:space:]]*//p' "$APP_DIR/webadmin.ini" | head -n1); port="${port:-8080}"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    curl -fs --max-time 5 -u "admin:$WEBPW" "http://127.0.0.1:$port/api/status" >/dev/null && return 0
    sleep 2
  done
  return 1
}

# ------------------------------------------------------------------ programme principal
: >"$LOG" 2>/dev/null || LOG=/tmp/flightdisplay-install.log
if [ -n "$UI" ]; then clear; fi
banner

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
if [ -f "$SCRIPT_DIR/main.py" ] && [ -f "$SCRIPT_DIR/build_map_vector.py" ]; then
  APP_DIR="$SCRIPT_DIR"
else
  APP_DIR="${FD_DIR:-$HOME/flightdisplay}"
fi

title "Vérification de votre Raspberry Pi"
preflight
info "Dossier d'installation : $APP_DIR"
info "Journal détaillé : $LOG"

KEEP=""
if [ -f "$APP_DIR/config.ini" ]; then
  printf '\n'; warn "Une configuration existe déjà dans $APP_DIR."
  if yesno "La conserver et ne mettre à jour que le logiciel ?" o; then KEEP=1; fi
fi
GENPW=""; LAT=""; LON=""; RADIUS=""; MAPW=""; MAPH=""; AIRPORT=""; CARTO_KEY=""; WEBPW=""; MQTT_ON=""; HDMI_FIX=""; NAME=""
MQTT_HOST=""; MQTT_PORT=""; MQTT_USER=""; MQTT_PASS=""
if [ -z "$KEEP" ]; then collect_answers; fi
CUR=1

title "Installation"
need_sudo

step "Mise à jour de la liste des paquets"
run_step "Téléchargement de la liste des paquets" apt_update

step "Installation des paquets système"
run_step "Installation de Python, pygame, git, audio, MQTT" apt_install git curl python3-venv python3-pygame python3-requests python3-paho-mqtt fonts-dejavu-core alsa-utils kbd

step "Téléchargement de Flight display"
if [ "$APP_DIR" = "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/main.py" ]; then ok "Projet déjà présent dans $APP_DIR"; else run_step "Récupération du projet depuis GitHub" fetch_project; fi

step "Environnement Python"
run_step "Création de l'environnement et installation des bibliothèques" make_venv

step "Dépendances de la carte"
if soft "Analyse et installation des dépendances de build_map_vector.py" map_deps; then :; else warn "Dépendances de la carte incomplètes (voir le journal)."; fi

step "Configuration"
if [ -n "$KEEP" ]; then
  ok "Configuration existante conservée"
else
  run_step "Écriture de config.ini et webadmin.ini" write_configs
  if [ -n "$CARTO_KEY" ]; then info "Clé CARTO enregistrée dans config.ini (section [map], clé carto_key)"; fi
fi

step "Construction de la carte"
if [ -f "$APP_DIR/background.png" ] && [ -f "$APP_DIR/map_meta.json" ] && [ -n "$KEEP" ]; then
  ok "Carte déjà construite"; MAP_OK=1
elif [ -z "$KEEP" ] && [ -z "$CARTO_KEY" ]; then
  warn "Clé CARTO absente : étape ignorée. Construisez la carte plus tard depuis webadmin (onglet Carte)."
else
  if soft "Génération de la carte (plusieurs minutes sur un Pi Zero)" build_map; then
    if [ -f "$APP_DIR/background.png" ] && [ -f "$APP_DIR/map_meta.json" ]; then MAP_OK=1; else warn "Le script s'est terminé sans produire la carte."; fi
  else
    warn "La construction de la carte a échoué : corrigez la clé ou les réglages, puis relancez-la depuis webadmin."
  fi
fi

step "Service d'affichage"
run_step "Création du service $SERVICE et de la commande fd" install_services

step "Interface web d'administration"
run_step "Installation de webadmin, des droits et du script de veille" install_webadmin

step "Correctif de veille d'écran"
if [ -n "$HDMI_FIX" ]; then
  if soft "Ajout de vc4.force_hotplug=1 au démarrage" hdmi_fix; then NEED_REBOOT=1; else warn "Correctif non appliqué (voir le journal)."; fi
else
  ok "Correctif ignoré"
fi

step "Démarrage et vérifications"
if soft "Démarrage du programme d'affichage" start_all; then :; else warn "Le programme d'affichage ne reste pas actif : consultez « fd logs »."; fi
if soft "Test de l'interface web" check_web; then :; else warn "webadmin ne répond pas encore : consultez « journalctl -u flightadmin »."; fi

# ------------------------------------------------------------------ resume
printf '\n  '; bar 100 40; printf '\n'
HOST=$(hostname)
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
PORT=$(sed -n 's/^port[[:space:]]*=[[:space:]]*//p' "$APP_DIR/webadmin.ini" 2>/dev/null | head -n1); PORT="${PORT:-8080}"
printf '\n%s%s' "$B" "$GRN"
printf '  ╔══════════════════════════════════════════════════════════╗\n'
printf '  ║            Installation terminée                         ║\n'
printf '  ╚══════════════════════════════════════════════════════════╝%s\n\n' "$R"
printf '  %sInterface web%s  http://%s.local:%s   ou   http://%s:%s\n' "$B" "$R" "$HOST" "$PORT" "${IP:-adresse-ip}" "$PORT"
printf '  %sIdentifiant%s    admin\n' "$B" "$R"
if [ -n "$WEBPW" ]; then
  if [ -n "$GENPW" ]; then printf '  %sMot de passe%s   %s%s%s   (notez-le, il ne sera plus affiché)\n' "$B" "$R" "$YEL" "$WEBPW" "$R"
  else printf '  %sMot de passe%s   celui que vous avez saisi\n' "$B" "$R"; fi
fi
printf '\n  %sCommandes utiles%s  fd logs   fd status   fd restart\n' "$B" "$R"
printf '  %sRéglages%s          tout se règle depuis l'"'"'interface web (onglet Réglages)\n' "$B" "$R"
printf '  %sDocumentation%s     %s/docs/FLIGHT_DISPLAY_DOCUMENTATION.md\n' "$B" "$R" "$APP_DIR"
if [ -z "$MAP_OK" ]; then
  printf '\n  %s%s La carte n'"'"'est pas construite : ouvrez webadmin, onglet Carte, puis « Reconstruire la carte ».%s\n' "$YEL" "$WRN" "$R"
fi
if [ "${#WARNINGS[@]}" -gt 0 ]; then
  printf '\n  %sPoints d'"'"'attention%s\n' "$B$YEL" "$R"
  for w in "${WARNINGS[@]}"; do printf '    %s•%s %s\n' "$YEL" "$R" "$w"; done
fi
printf '\n'
if [ -n "$NEED_REBOOT" ]; then
  if yesno "Un redémarrage est nécessaire pour finaliser. Redémarrer maintenant ?" o; then
    if [ -n "$DRY" ]; then echo "[simulation] sudo reboot"; else sudo reboot; fi
  fi
fi
printf '\n'
