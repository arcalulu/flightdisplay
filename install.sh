#!/usr/bin/env bash
# =============================================================================
#  Flight display - installation pour Raspberry Pi OS Lite / installer for Raspberry Pi OS Lite
#
#  bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh)
#  ou / or : git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay && bash ~/flightdisplay/install.sh
#
#  Par defaut / by default : installation automatique apres 15 s (configuration par defaut) / automatic install after 15 s
#  Options : --help  --manual  --auto  --dry-run  --lang fr|en  --yes (sans questions / no questions)   (voir --help)
#  Relancer le script met a jour le logiciel et conserve votre configuration.
# =============================================================================
set -uo pipefail

REPO_URL="${FD_REPO_URL:-https://github.com/arcalulu/flightdisplay.git}"
BRANCH="${FD_BRANCH:-main}"
DRY="${FD_DRY_RUN:-}"
INPUT="${FD_INPUT:-/dev/tty}"
LOG="${FD_LOG:-$HOME/flightdisplay-install.log}"
CARTO_URL="https://carto.com/basemaps/apikey/"
SERVICE="flightdisplay"
TOTAL=11
MAIN_VT="${FD_MAIN_VT:-1}"
IDLE_VT="${FD_IDLE_VT:-7}"
HELPER=/usr/local/bin/flight-screen
GUARD=/usr/local/bin/flight-screen-guard
AUTO_REBOOT=""
CUR=0
SOFT=""
KEEPALIVE=""
NEED_REBOOT=""
MAP_OK=""
WARNINGS=()
YES="${FD_YES:-}"
LANG_UI="${FD_LANG:-}"
HELP=""
MANUAL="${FD_MANUAL:-}"     # installation classique : les questions sont posees
FORCE_AUTO="${FD_AUTO:-}"   # installation automatique tout de suite, sans le delai de 15 s
COUNTDOWN="${FD_COUNTDOWN:-15}"
AUTO=""                     # positionne plus bas : installation automatique avec la configuration par defaut
LANG_GUESS=""
HAVE_TTY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    -y|--yes|--non-interactive) YES=1 ;;
    --manual|--manuel) MANUAL=1 ;;
    --auto) FORCE_AUTO=1 ;;
    --lang) LANG_UI="${2:-}"; [ $# -gt 1 ] && shift ;;
    --lang=*) LANG_UI="${1#--lang=}" ;;
    -h|--help) HELP=1 ;;
  esac
  shift
done
case "$(printf '%s' "$LANG_UI" | tr '[:upper:]' '[:lower:]')" in
  en|en_*|english) LANG_UI=en ;;
  fr|fr_*|francais|français) LANG_UI=fr ;;
  *) LANG_UI="" ;;
esac

usage() {
  if [ "$LANG_UI" = en ]; then cat <<'USAGE_EN'
Flight display installer for Raspberry Pi OS Lite

  bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh) [options]

Options:
  --help              this help
  --dry-run           simulation: nothing is installed
  --manual            classic installation: the questions are asked one by one (position, map, CARTO key...)
  --auto              automatic installation right away, without the 15-second wait
  --lang fr|en        language of the installer, of webadmin and of the screen (default: the system language)
  --yes               no questions (also --non-interactive or FD_YES=1): answers come from the FD_* variables
                      and sudo must work without a password (sudo -n)

Default: AUTOMATIC installation, with no question. A 15-second countdown lets you press a key (or Ctrl+C)
to switch to the manual installation. Without a terminal (script), it starts immediately.
It uses the sample configuration (airport of Bordeaux-Merignac), the ready-made map, no MQTT and no
webadmin password. You then set everything from webadmin, and the program starts at the end.

Variables for --yes (first installation; all optional except the position):
  FD_ADDRESS          your address (converted to coordinates)       or  FD_LAT and FD_LON
  FD_RADIUS           map radius in km (1 to 200, default 20)
  FD_MAP_SIZE         map size, e.g. 1280x720 (default) or 1920x1080
  FD_AIRPORT          IATA code of a nearby airport (e.g. CDG)
  FD_CARTO_KEY        CARTO API key (without it, the map is built later from webadmin)
  FD_WEB_PASSWORD     webadmin password (6 characters minimum; generated and shown at the end if empty)
  FD_MQTT_HOST, FD_MQTT_PORT, FD_MQTT_USER, FD_MQTT_PASS   optional MQTT server
  FD_HDMI_FIX         1 (default) or 0: screen sleep fix      FD_AUTO_REBOOT   1 or 0 (default): reboot at the end
  FD_KEEP             1 (default) or 0: keep an existing config.ini
Other: FD_DIR (folder), FD_BRANCH, FD_REPO_URL, FD_LOG, FD_COUNTDOWN (seconds of the automatic mode wait, 0 = none), NO_COLOR=1.
Running the script again later updates the software and keeps your configuration.
USAGE_EN
  else cat <<'USAGE_FR'
Installeur de Flight display pour Raspberry Pi OS Lite

  bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh) [options]

Options :
  --help              cette aide
  --dry-run           simulation : rien n'est installé
  --manual            installation classique : les questions sont posées une à une (position, carte, clé CARTO...)
  --auto              installation automatique tout de suite, sans l'attente de 15 secondes
  --lang fr|en        langue de l'installeur, de webadmin et de l'écran (défaut : la langue du système)
  --yes               sans questions (aussi --non-interactive ou FD_YES=1) : les réponses viennent des variables FD_*
                      et sudo doit fonctionner sans mot de passe (sudo -n)

Par défaut : installation AUTOMATIQUE, sans aucune question. Un compte à rebours de 15 secondes permet
d'appuyer sur une touche (ou Ctrl+C) pour passer à l'installation manuelle. Sans terminal (script), elle
démarre tout de suite. Elle utilise la configuration d'exemple (aéroport de Bordeaux-Mérignac), la carte
fournie, sans MQTT et sans mot de passe webadmin. Vous réglez ensuite tout depuis webadmin, et le
programme démarre à la fin de l'installation.

Variables pour --yes (première installation ; toutes facultatives sauf la position) :
  FD_ADDRESS          votre adresse (convertie en coordonnées)       ou  FD_LAT et FD_LON
  FD_RADIUS           rayon de la carte en km (1 à 200, 20 par défaut)
  FD_MAP_SIZE         taille de la carte, ex. 1280x720 (défaut) ou 1920x1080
  FD_AIRPORT          code IATA d'un aéroport proche (ex. CDG)
  FD_CARTO_KEY        clé API CARTO (sans elle, la carte se construit plus tard depuis webadmin)
  FD_WEB_PASSWORD     mot de passe de webadmin (6 caractères minimum ; généré et affiché à la fin si vide)
  FD_MQTT_HOST, FD_MQTT_PORT, FD_MQTT_USER, FD_MQTT_PASS   serveur MQTT facultatif
  FD_HDMI_FIX         1 (défaut) ou 0 : correctif de veille d'écran      FD_AUTO_REBOOT   1 ou 0 (défaut) : redémarrer à la fin
  FD_KEEP             1 (défaut) ou 0 : conserver un config.ini existant
Autres : FD_DIR (dossier), FD_BRANCH, FD_REPO_URL, FD_LOG, FD_COUNTDOWN (secondes d'attente du mode automatique, 0 = aucune), NO_COLOR=1.
Relancer le script plus tard met à jour le logiciel et conserve votre configuration.
USAGE_FR
  fi
}
if [ -n "$HELP" ]; then usage; exit 0; fi

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

# ------------------------------------------------------------------ traduction (le francais est la langue source)
L() {  # texte -> traduction (si l'anglais est choisi et que le texte est connu)
  local k="$1"
  if [ -n "${FD_DUMP_KEYS:-}" ]; then printf '%s\n' "$k" >>"$FD_DUMP_KEYS"; fi
  if [ "$LANG_UI" = en ] && [ -n "${EN[$k]+x}" ]; then printf '%s' "${EN[$k]}"; else printf '%s' "$k"; fi
}
Lf() { local f; f=$(L "$1"); shift; printf "$f" "$@"; }  # modele printf traduit
pt() { local f; f=$(L "$1"); shift; printf "$f" "$@"; }  # printf dont le format est traduit
declare -A EN=()

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
  pt '%s\n  %sInstallation automatique pour Raspberry Pi%s\n' "$R" "$B" "$R"
  if [ -n "$DRY" ]; then pt '  %s*** MODE SIMULATION : rien ne sera installé ***%s\n' "$YEL" "$R"; fi
  printf '\n'
}

title() { printf '\n%s%s== %s ==%s\n\n' "$B" "$MAG" "$(L "$1")" "$R"; }
info()  { printf '  %s•%s %s\n' "$BLU" "$R" "$(L "$1")"; }
ok()    { printf '  %s%s%s %s\n' "$GRN" "$OKC" "$R" "$(L "$1")"; }
warn()  { local m; m=$(L "$1"); printf '  %s%s%s %s\n' "$YEL" "$WRN" "$R" "$m"; WARNINGS+=("$m"); }
die()   { printf '\n  %s%s %s%s\n' "$RED" "$KOC" "$(L "$1")" "$R"; printf '  %s%s%s%s\n\n' "$DIM" "$(L 'Journal détaillé : ')" "$LOG" "$R"; exit 1; }

step() {
  CUR=$((CUR + 1))
  printf '\n%s%s[%d/%d]%s %s%s%s\n  ' "$B" "$CYN" "$CUR" "$TOTAL" "$R" "$B" "$(L "$1")" "$R"
  bar $(((CUR - 1) * 100 / TOTAL)) 40
  printf '\n\n'
}

cleanup() {
  if [ -n "$KEEPALIVE" ]; then kill "$KEEPALIVE" 2>/dev/null; fi
  if [ -n "$UI" ]; then tput cnorm 2>/dev/null; fi
  return 0
}
trap cleanup EXIT
trap 'pt "\n  %sInstallation interrompue.%s\n" "$YEL" "$R"; exit 130' INT TERM

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

last_line() {  # largeur maximale
  local l
  l=$(tail -c +$((LOGPOS + 1)) "$LOG" 2>/dev/null | tail -c 6000 | tr '\r\t' '\n ' | tr -d '\033' \
    | grep -vE '^\s*$|^(dlstatus|pmstatus):' | awk '
        { last = $0 }
        /^(»|Collecting|Downloading|Using cached|Building wheel|Preparing metadata|Installing collected|Successfully|Get:|Hit:|Unpacking|Setting up|Preparing to unpack|Selecting)/ { stage = $0 }
        END { if (stage != "") print stage; else print last }')
  l="${l#"${l%%[![:space:]]*}"}"
  printf '%s' "${l:0:$1}"
}

run_step() {  # libelle commande...
  local label; label=$(L "$1"); shift
  local start=$SECONDS pid rc i=0 pct line room c plain
  printf '\n### %s\n' "$label" >>"$LOG"
  LOGPOS=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
  ( "$@" ) </dev/null >>"$LOG" 2>&1 &
  pid=$!
  if [ -n "$UI" ]; then
    tput civis 2>/dev/null
    while kill -0 "$pid" 2>/dev/null; do
      c=$(cols)
      pct=$(progress_pct)
      plain="  x $label ($((SECONDS - start))s)"
      printf '\r\033[K  %s%s%s %s %s(%ds)%s' "$CYN" "${SP[i % ${#SP[@]}]}" "$R" "$label" "$DIM" "$((SECONDS - start))" "$R"
      if [ "$pct" -ge 0 ] 2>/dev/null; then printf '  '; bar "$pct" 18; plain="$plain                         "; fi
      room=$((c - ${#plain} - 5))
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
  die "$(Lf "Échec de l'étape : %s" "$label")"
}
soft() { SOFT=1 run_step "$@"; local rc=$?; SOFT=""; return $rc; }

# ------------------------------------------------------------------ questions
if { exec 3<"$INPUT"; } 2>/dev/null; then HAVE_TTY=1; fi

sys_lang() {  # langue du systeme : fr si le Pi est en francais, sinon en
  case "$(printf '%s' "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" | tr '[:upper:]' '[:lower:]')" in fr*) echo fr ;; *) echo en ;; esac
}

countdown() {  # secondes : l'installation automatique demarre seule ; une touche ou Ctrl+C donne MANUAL=1
  local n="$1" i key old
  old=$(trap -p INT)
  trap 'MANUAL=1' INT
  pt '  %s%s%s\n' "$B" "$(L "Installation automatique : configuration par défaut (aéroport de Bordeaux-Mérignac, carte fournie, MQTT désactivé).")" "$R"
  pt '  %s%s%s\n\n' "$DIM" "$(L "Appuyez sur une touche (ou Ctrl+C) pour passer à l'installation manuelle ; sinon elle démarre toute seule.")" "$R"
  i="$n"
  while [ "$i" -gt 0 ] && [ -z "$MANUAL" ]; do
    printf '\r  %s%s%s' "$YEL" "$(Lf "Démarrage automatique dans %s s..." "$i")" "$R"
    if IFS= read -r -s -n 1 -t 1 key <&3 2>/dev/null; then MANUAL=1; fi
    i=$((i - 1))
  done
  eval "${old:-trap - INT}"
  printf '\r\033[K'
}

ask() {  # variable "question" "defaut" [secret]
  local var="$1" q def="${3:-}" secret="${4:-}" ans
  q=$(L "$2")
  if [ -n "$def" ]; then printf '  %s%s%s %s[%s]%s : ' "$B" "$q" "$R" "$DIM" "$def" "$R"
  else printf '  %s%s%s : ' "$B" "$q" "$R"; fi
  if [ -n "$secret" ]; then IFS= read -r -s ans <&3 || ans=""; printf '\n'
  else IFS= read -r ans <&3 || ans=""; fi
  printf -v "$var" '%s' "${ans:-$def}"
}

yesno() {  # "question" defaut(o|n) -> 0 si oui
  local q def="${2:-o}" ans hint="O/n"
  q=$(L "$1")
  if [ "$LANG_UI" = en ]; then hint="Y/n"; [ "$def" = "n" ] && hint="y/N"; else [ "$def" = "n" ] && hint="o/N"; fi
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
lines = open(path, encoding="utf-8-sig").read().splitlines() if os.path.exists(path) else []
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

ini_get() {  # fichier section cle -> valeur (vide si absente)
  python3 - "$1" "$2" "$3" 2>/dev/null <<'PY'
import configparser, sys
p, sec, key = sys.argv[1:4]
c = configparser.ConfigParser(interpolation=None, strict=False)
try:
    c.read(p, encoding="utf-8-sig")
    print(c.get(sec, key, fallback="").strip())
except Exception:
    pass
PY
}

ini_default() {  # fichier section cle valeur : n'écrit que si la clé est absente ou vide
  local cur; cur=$(ini_get "$1" "$2" "$3")
  [ -n "$cur" ] || ini_set "$1" "$2" "$3" "$4"
}

collect_env() {  # mode --yes : reponses depuis l'environnement
  local res sz
  title "Configuration depuis les variables FD_*"
  LAT="${FD_LAT:-}"; LON="${FD_LON:-}"
  if [ -z "$LAT" ] || [ -z "$LON" ]; then
    [ -n "${FD_ADDRESS:-}" ] || die "Mode sans questions : FD_ADDRESS (ou FD_LAT et FD_LON) est obligatoire pour une première installation."
    res=$(geocode "$FD_ADDRESS") || res=""
    [ -n "$res" ] || die "Adresse introuvable (FD_ADDRESS) : utilisez FD_LAT et FD_LON."
    IFS='|' read -r LAT LON NAME <<<"$res"
    LAT=$(printf '%.4f' "$LAT"); LON=$(printf '%.4f' "$LON")
    info "$(Lf 'Position trouvée : %s' "$NAME")"
  fi
  LAT=${LAT//,/.}; LON=${LON//,/.}
  num_in_range "$LAT" -90 90 || die "FD_LAT invalide (-90 à 90)."
  num_in_range "$LON" -180 180 || die "FD_LON invalide (-180 à 180)."
  RADIUS="${FD_RADIUS:-20}"; RADIUS=${RADIUS//,/.}
  num_in_range "$RADIUS" 1 200 || die "FD_RADIUS invalide (1 à 200)."
  sz="${FD_MAP_SIZE:-1280x720}"
  [[ "$sz" =~ ^([0-9]{3,5})x([0-9]{3,5})$ ]] || die "FD_MAP_SIZE invalide (exemple : 1280x720)."
  MAPW="${BASH_REMATCH[1]}"; MAPH="${BASH_REMATCH[2]}"
  AIRPORT=$(printf '%s' "${FD_AIRPORT:-}" | tr '[:lower:]' '[:upper:]')
  [ -z "$AIRPORT" ] || [[ "$AIRPORT" =~ ^[A-Z]{3}$ ]] || die "FD_AIRPORT invalide (3 lettres, ex. CDG)."
  CARTO_KEY="${FD_CARTO_KEY:-}"
  if [ -n "$CARTO_KEY" ]; then ok "$(Lf 'Clé enregistrée (%s caractères)' "${#CARTO_KEY}")"
  else warn "Pas de clé : la carte ne sera pas construite maintenant (possible plus tard depuis webadmin, Réglages, Carte et position)."; fi
  env_webpw
  MQTT_ON=""
  if [ -n "${FD_MQTT_HOST:-}" ]; then MQTT_ON=1; MQTT_HOST="$FD_MQTT_HOST"; MQTT_PORT="${FD_MQTT_PORT:-1883}"; MQTT_USER="${FD_MQTT_USER:-}"; MQTT_PASS="${FD_MQTT_PASS:-}"; fi
  HDMI_FIX=""; [ "${FD_HDMI_FIX:-1}" = 1 ] && HDMI_FIX=1
  AUTO_REBOOT=""; [ -n "$HDMI_FIX" ] && [ "${FD_AUTO_REBOOT:-0}" = 1 ] && AUTO_REBOOT=1
  return 0
}

env_webpw() {  # mot de passe de webadmin en mode --yes
  WEBPW="${FD_WEB_PASSWORD:-}"
  if [ -z "$WEBPW" ]; then WEBPW=$(gen_password); GENPW=1; ok "Mot de passe généré (affiché à la fin)."
  elif [ "${#WEBPW}" -lt 6 ]; then die "FD_WEB_PASSWORD est trop court (6 caractères minimum)."
  else ok "$(Lf 'Mot de passe retenu (%s caractères).' "${#WEBPW}")"; fi
}

ask_webpw() {
  pt '  %sProtège l'"'"'accès à webadmin depuis votre réseau. Entrée = en générer un automatiquement.\n  La saisie reste visible : vous voyez ce que vous tapez.%s\n' "$DIM" "$R"
  WEBPW=""
  while [ -z "$WEBPW" ]; do
    local p1 p2
    ask p1 "Mot de passe (6 caractères minimum, Entrée = automatique)" ""
    if [ -z "$p1" ]; then WEBPW=$(gen_password); GENPW=1; ok "Mot de passe généré (affiché à la fin)."
    elif [ "${#p1}" -lt 6 ]; then warn "Trop court."
    else
      ask p2 "Confirmez le mot de passe" ""
      if [ "$p1" = "$p2" ]; then WEBPW="$p1"; ok "$(Lf 'Mot de passe retenu (%s caractères).' "${#WEBPW}")"; else warn "Les deux saisies diffèrent."; fi
    fi
  done
}

collect_auto() {  # installation automatique : aucune question, configuration d'exemple (Bordeaux-Merignac)
  title "Installation automatique"
  WEBPW=""; MQTT_ON=""; AUTO_REBOOT=""; HDMI_FIX=1
  if [ -n "$KEEP" ]; then
    info "Votre configuration est conservée : seul le logiciel est mis à jour."
    return 0
  fi
  info "Position et réglages : configuration d'exemple (aéroport de Bordeaux-Mérignac)"
  info "Fond de carte : la carte fournie avec le logiciel (aucune clé CARTO nécessaire pour démarrer)"
  info "MQTT désactivé ; vous réglerez tout depuis webadmin à la fin de l'installation"
  warn "Aucun mot de passe n'est défini pour webadmin : toute personne de votre réseau local peut le piloter. Définissez-en un dans webadmin (Réglages, Serveur web)."
}

collect_keep() {  # configuration conservée : on ne demande que ce qui manque
  local cur
  cur=$(ini_get "$APP_DIR/config.ini" server password)
  [ -n "$cur" ] && return 0
  if [ -n "$YES" ]; then env_webpw; return 0; fi
  title "Mot de passe de l'interface web"
  pt '  %sAucun mot de passe n'"'"'est enregistré pour l'"'"'interface web.%s\n' "$DIM" "$R"
  ask_webpw
}

collect_answers() {
  title "Vos informations"
  pt '  %sToutes les saisies restent visibles, mots de passe compris : vérifiez-les avant de valider.%s\n' "$DIM" "$R"
  pt '  %sQuelques questions, puis l'"'"'installation se déroule seule, sans autre question (plusieurs minutes, selon votre Pi et votre connexion).%s\n' "$DIM" "$R"
  pt '  %sIl vous faut une clé API CARTO (gratuite, voir la question 4) : %s%s\n\n' "$DIM" "$CARTO_URL" "$R"

  pt '  %s1. Votre position%s\n' "$B$BLU" "$R"
  pt '  %sSaisissez votre adresse (elle est envoyée une seule fois au service OpenStreetMap Nominatim\n  pour trouver les coordonnées), ou appuyez sur Entrée pour saisir les coordonnées.%s\n' "$DIM" "$R"
  LAT=""; LON=""
  local addr res
  while [ -z "$LAT" ]; do
    ask addr "Adresse (ou Entrée)" ""
    if [ -n "$addr" ]; then
      pt '  %sRecherche...%s\r' "$DIM" "$R"
      res=$(geocode "$addr") || res=""
      if [ -n "$res" ]; then
        IFS='|' read -r LAT LON NAME <<<"$res"
        LAT=$(printf '%.4f' "$LAT"); LON=$(printf '%.4f' "$LON")
        pt '\033[K  %sTrouvé :%s %s\n  %s(latitude %s, longitude %s, arrondies à 11 m)%s\n' "$GRN" "$R" "$NAME" "$DIM" "$LAT" "$LON" "$R"
        yesno "C'est bien là ?" o || { LAT=""; LON=""; }
      else
        printf '\033[K'; warn "Adresse introuvable. Réessayez ou saisissez les coordonnées."
      fi
    else
      pt '  %sAstuce : clic droit sur votre maison dans Google Maps ou OpenStreetMap, puis copier les coordonnées.%s\n' "$DIM" "$R"
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

  pt '\n  %s2. Résolution de la carte%s\n' "$B$BLU" "$R"
  pt '  %s1) 1920x1080   2) 1280x720 (recommandé sur Pi Zero : moins de charge)   3) autre%s\n' "$DIM" "$R"
  local rc; ask rc "Votre choix" "2"
  case "$rc" in
    1) MAPW=1920; MAPH=1080 ;;
    3) while true; do ask MAPW "Largeur en pixels" "1280"; [[ "$MAPW" =~ ^[0-9]{3,5}$ ]] && break; warn "Nombre invalide."; done
       while true; do ask MAPH "Hauteur en pixels" "720"; [[ "$MAPH" =~ ^[0-9]{3,5}$ ]] && break; warn "Nombre invalide."; done ;;
    *) MAPW=1280; MAPH=720 ;;
  esac

  pt '\n  %s3. Aéroport proche (facultatif)%s\n' "$B$BLU" "$R"
  while true; do
    ask AIRPORT "Code IATA à 3 lettres (ex. CDG), ou Entrée" ""; AIRPORT=$(printf '%s' "$AIRPORT" | tr '[:lower:]' '[:upper:]')
    if [ -z "$AIRPORT" ] || [[ "$AIRPORT" =~ ^[A-Z]{3}$ ]]; then break; fi
    warn "Code invalide."
  done

  pt '\n  %s4. Clé API CARTO%s\n' "$B$BLU" "$R"
  pt '  %sLa carte est dessinée à partir du fond de carte CARTO, qui exige une clé API personnelle.\n' "$DIM"
  pt '  Elle est gratuite pour un usage non commercial (jusqu'"'"'à 5 millions de tuiles par mois : largement\n'
  pt '  suffisant ici, la carte n'"'"'est téléchargée qu'"'"'à sa construction) et ne demande pas de compte CARTO.%s\n' "$R"
  pt '  %sPour l'"'"'obtenir en une minute, depuis votre ordinateur ou votre téléphone :%s\n' "$B" "$R"
  pt '    1) ouvrez %s%s%s\n' "$CYN" "$CARTO_URL" "$R"
  pt '    2) saisissez votre adresse e-mail et acceptez les conditions (usage personnel, non commercial)\n'
  pt '    3) copiez la clé reçue par e-mail, puis collez-la ci-dessous (elle reste visible : vérifiez le collage)\n'
  pt '  %sGardez cette clé pour vous : elle est personnelle, ne la partagez pas.%s\n' "$DIM" "$R"
  pt '  %sL'"'"'installation attend : prenez le temps de la récupérer, puis revenez ici.%s\n' "$DIM" "$R"
  ask CARTO_KEY "Clé API CARTO (Entrée pour passer)" ""
  if [ -n "$CARTO_KEY" ]; then
    ok "$(Lf 'Clé enregistrée (%s caractères)' "${#CARTO_KEY}")"
  else
    warn "Pas de clé : la carte ne sera pas construite maintenant (possible plus tard depuis webadmin, Réglages, Carte et position)."
  fi

  pt '\n  %s5. Mot de passe de l'"'"'interface web%s\n' "$B$BLU" "$R"
  ask_webpw

  pt '\n  %s6. Home Assistant / MQTT (facultatif)%s\n' "$B$BLU" "$R"
  MQTT_ON=""
  if yesno "Configurer MQTT maintenant ?" n; then
    MQTT_ON=1
    ask MQTT_HOST "Adresse du serveur MQTT" ""
    ask MQTT_PORT "Port" "1883"
    ask MQTT_USER "Identifiant (Entrée si aucun)" ""
    ask MQTT_PASS "Mot de passe MQTT (Entrée si aucun)" ""
    if [ -n "$MQTT_PASS" ]; then ok "$(Lf 'Mot de passe MQTT retenu (%s caractères).' "${#MQTT_PASS}")"; fi
  fi

  pt '\n  %s7. Veille d'"'"'écran fiable%s\n' "$B$BLU" "$R"
  pt '  %sCorrectif qui empêche certains moniteurs de se rallumer seuls en veille (redémarrage conseillé).%s\n' "$DIM" "$R"
  HDMI_FIX=""; if yesno "Appliquer le correctif ?" o; then HDMI_FIX=1; fi
  AUTO_REBOOT=""
  if [ -n "$HDMI_FIX" ]; then
    if yesno "Redémarrer automatiquement à la fin de l'installation ?" o; then AUTO_REBOOT=1; fi
  fi

  pt '\n  %sRécapitulatif%s\n' "$B$BLU" "$R"
  pt '    Position : %s, %s   Rayon : %s km   Carte : %sx%s\n' "$LAT" "$LON" "$RADIUS" "$MAPW" "$MAPH"
  pt '    Aéroport : %s   Clé CARTO : %s\n' "${AIRPORT:-aucun}" "$([ -n "$CARTO_KEY" ] && echo fournie || echo non fournie)"
  pt '    MQTT : %s   Correctif écran : %s   Redémarrage auto : %s\n\n' "$([ -n "$MQTT_ON" ] && echo "$MQTT_HOST" || echo non)" "$([ -n "$HDMI_FIX" ] && echo oui || echo non)" "$([ -n "$AUTO_REBOOT" ] && echo oui || echo non)"
  yesno "Lancer l'installation ?" o || { pt '\n  Installation annulée.\n\n'; exit 0; }
}

# ------------------------------------------------------------------ table de traduction anglaise
load_en() {
  local k v
  while IFS=$'\t' read -r k v; do
    [ -n "$k" ] && EN[$k]="$v"
  done <<'EN_TABLE'
Adresse (ou Entrée)	Address (or Enter)
Adresse du serveur MQTT	MQTT server address
Appliquer le correctif ?	Apply the fix?
Clé API CARTO (Entrée pour passer)	CARTO API key (Enter to skip)
Code IATA à 3 lettres (ex. CDG), ou Entrée	3-letter IATA code (e.g. CDG), or Enter
Code invalide.	Invalid code.
Configurer MQTT maintenant ?	Configure MQTT now?
Confirmez le mot de passe	Confirm the password
Hauteur en pixels	Height in pixels
Largeur en pixels	Width in pixels
Identifiant (Entrée si aucun)	Username (Enter if none)
La conserver et ne mettre à jour que le logiciel ?	Keep it and only update the software?
Lancer l'installation ?	Start the installation?
Latitude (ex. 48.8566)	Latitude (e.g. 48.8566)
Latitude invalide (-90 à 90).	Invalid latitude (-90 to 90).
Longitude (ex. 2.3522)	Longitude (e.g. 2.3522)
Longitude invalide (-180 à 180).	Invalid longitude (-180 to 180).
Mot de passe (6 caractères minimum, Entrée = automatique)	Password (6 characters minimum, Enter = automatic)
Mot de passe MQTT (Entrée si aucun)	MQTT password (Enter if none)
Nombre invalide.	Invalid number.
Port	Port
Rayon de la carte en km (1 à 200)	Map radius in km (1 to 200)
Redémarrer automatiquement à la fin de l'installation ?	Reboot automatically at the end of the installation?
Trop court.	Too short.
Valeur invalide.	Invalid value.
Votre choix	Your choice
C'est bien là ?	Is this the right place?
Architecture : %s	Architecture: %s
Carte déjà construite	Map already built
Clé CARTO absente : étape ignorée. Construisez la carte plus tard depuis webadmin (Réglages, Carte et position).	CARTO key missing: step skipped. Build the map later from webadmin (Settings, Map and position).
Clé CARTO enregistrée dans config.ini (section [map], clé carto_key)	CARTO key saved in config.ini (section [map], key carto_key)
Clé enregistrée (%s caractères)	Key saved (%s characters)
Correctif ignoré	Fix skipped
Correctif non appliqué (voir le journal).	Fix not applied (see the log).
Dossier d'installation : %s	Installation folder: %s
Dépendances de la carte incomplètes (voir le journal).	Map dependencies incomplete (see the log).
Espace disque libre : %s Mo	Free disk space: %s MB
Espace disque limité (%s Mo) : 1,5 Go conseillés.	Limited disk space (%s MB): 1.5 GB recommended.
Horloge non synchronisée (NTP) : l'heure doit être exacte pour Flightradar24.	Clock not synchronized (NTP): the time must be accurate for Flightradar24.
Horloge synchronisée	Clock synchronized
Journal détaillé : 	Detailed log: 
Journal détaillé : %s	Detailed log: %s
Matériel : %s	Hardware: %s
Matériel non identifié comme un Raspberry Pi.	Hardware not recognized as a Raspberry Pi.
Mémoire : %s Mo	Memory: %s MB
Mémoire faible (%s Mo).	Low memory (%s MB).
Mot de passe MQTT retenu (%s caractères).	MQTT password kept (%s characters).
Mot de passe généré (affiché à la fin).	Password generated (shown at the end).
Mot de passe retenu (%s caractères).	Password kept (%s characters).
Pas de clé : la carte ne sera pas construite maintenant (possible plus tard depuis webadmin, Réglages, Carte et position).	No key: the map will not be built now (possible later from webadmin, Settings, Map and position).
Système : %s	System: %s
Système non Debian/Raspberry Pi OS : l'installation peut échouer.	System is not Debian/Raspberry Pi OS: the installation may fail.
Une configuration existe déjà dans %s.	A configuration already exists in %s.
Projet déjà présent dans %s	Project already present in %s
Position trouvée : %s	Position found: %s
Connexion Internet	Internet connection
Adresse introuvable. Réessayez ou saisissez les coordonnées.	Address not found. Try again or enter the coordinates.
Les deux saisies diffèrent.	The two entries differ.
La construction de la carte a échoué : vérifiez la clé CARTO (Réglages, Carte et position), puis relancez-la depuis webadmin.	Building the map failed: check the CARTO key (Settings, Map and position), then run it again from webadmin.
Le script s'est terminé sans produire la carte.	The script ended without producing the map.
webadmin ne répond pas encore : consultez « journalctl -u flightadmin ».	webadmin is not answering yet: check "journalctl -u flightadmin".
Échec de l'étape : %s	Step failed: %s
Aucun terminal interactif disponible (lancez la commande depuis une session SSH, ou utilisez --yes).	No interactive terminal available (run the command from an SSH session, or use --yes).
Ne lancez pas ce script avec sudo ni en root : utilisez votre utilisateur normal (il demandera sudo si besoin).	Do not run this script with sudo or as root: use your normal user (it will ask for sudo when needed).
Pas de connexion Internet (vérifiez le Wi-Fi).	No Internet connection (check the Wi-Fi).
sudo est nécessaire.	sudo is required.
systemd est requis.	systemd is required.
Mode sans questions : sudo doit fonctionner sans mot de passe (sudo -n).	No-questions mode: sudo must work without a password (sudo -n).
Mode sans questions : FD_ADDRESS (ou FD_LAT et FD_LON) est obligatoire pour une première installation.	No-questions mode: FD_ADDRESS (or FD_LAT and FD_LON) is required for a first installation.
Adresse introuvable (FD_ADDRESS) : utilisez FD_LAT et FD_LON.	Address not found (FD_ADDRESS): use FD_LAT and FD_LON.
FD_LAT invalide (-90 à 90).	Invalid FD_LAT (-90 to 90).
FD_LON invalide (-180 à 180).	Invalid FD_LON (-180 to 180).
FD_RADIUS invalide (1 à 200).	Invalid FD_RADIUS (1 to 200).
FD_MAP_SIZE invalide (exemple : 1280x720).	Invalid FD_MAP_SIZE (example: 1280x720).
FD_AIRPORT invalide (3 lettres, ex. CDG).	Invalid FD_AIRPORT (3 letters, e.g. CDG).
FD_WEB_PASSWORD est trop court (6 caractères minimum).	FD_WEB_PASSWORD is too short (6 characters minimum).
Configuration depuis les variables FD_*	Configuration from the FD_* variables
Vérification de votre Raspberry Pi	Checking your Raspberry Pi
Vos informations	Your information
Installation	Installation
Mot de passe de l'interface web	Web interface password
Mise à jour de la liste des paquets	Updating the package list
Téléchargement de la liste des paquets	Downloading the package list
Installation des paquets système	Installing system packages
Installation de Python, pygame, Pillow, EGL, git, audio, MQTT	Installing Python, pygame, Pillow, EGL, git, audio, MQTT
Téléchargement de Flight display	Downloading Flight display
Récupération du projet depuis GitHub	Fetching the project from GitHub
Environnement Python	Python environment
Création de l'environnement et installation des bibliothèques	Creating the environment and installing the libraries
Dépendances de la carte	Map dependencies
Analyse et installation des dépendances de build_map_vector.py	Analyzing and installing the dependencies of build_map_vector.py
Configuration	Configuration
Mise à jour de config.ini (vos réglages sont conservés)	Updating config.ini (your settings are kept)
Écriture de config.ini	Writing config.ini
Construction de la carte	Building the map
Génération de la carte (plusieurs minutes sur un Pi Zero)	Generating the map (several minutes on a Pi Zero)
Service d'affichage	Display service
Création du service %s et de la commande fd	Creating the %s service and the fd command
Interface web d'administration	Web administration interface
Installation de webadmin (service, droits sudo, script de veille)	Installing webadmin (service, sudo rights, sleep script)
Correctif de veille d'écran	Screen sleep fix
Ajout de vc4.force_hotplug=1 et video=HDMI-A-1:D au démarrage	Adding vc4.force_hotplug=1 and video=HDMI-A-1:D to the boot options
Démarrage et vérifications	Start and checks
Démarrage du programme d'affichage	Starting the display program
Test de l'interface web	Testing the web interface
Installation terminée	Installation complete
%s\n  %sInstallation automatique pour Raspberry Pi%s\n	%s\n  %sAutomatic installation for Raspberry Pi%s\n
  %s*** MODE SIMULATION : rien ne sera installé ***%s\n	  %s*** SIMULATION MODE: nothing will be installed ***%s\n
  %sToutes les saisies restent visibles, mots de passe compris : vérifiez-les avant de valider.%s\n	  %sEverything you type stays visible, passwords included: check it before confirming.%s\n
  %sQuelques questions, puis l'installation se déroule seule, sans autre question (plusieurs minutes, selon votre Pi et votre connexion).%s\n	  %sA few questions, then the installation runs by itself with no other question (several minutes, depending on your Pi and your connection).%s\n
  %sIl vous faut une clé API CARTO (gratuite, voir la question 4) : %s%s\n\n	  %sYou need a CARTO API key (free, see question 4): %s%s\n\n
  %s1. Votre position%s\n	  %s1. Your position%s\n
  %sSaisissez votre adresse (elle est envoyée une seule fois au service OpenStreetMap Nominatim\n  pour trouver les coordonnées), ou appuyez sur Entrée pour saisir les coordonnées.%s\n	  %sEnter your address (it is sent once to the OpenStreetMap Nominatim service\n  to find the coordinates), or press Enter to type the coordinates.%s\n
  %sRecherche...%s\r	  %sSearching...%s\r
\033[K  %sTrouvé :%s %s\n  %s(latitude %s, longitude %s, arrondies à 11 m)%s\n	\033[K  %sFound:%s %s\n  %s(latitude %s, longitude %s, rounded to 11 m)%s\n
  %sAstuce : clic droit sur votre maison dans Google Maps ou OpenStreetMap, puis copier les coordonnées.%s\n	  %sTip: right-click your house in Google Maps or OpenStreetMap, then copy the coordinates.%s\n
\n  %s2. Résolution de la carte%s\n	\n  %s2. Map resolution%s\n
  %s1) 1920x1080   2) 1280x720 (recommandé sur Pi Zero : moins de charge)   3) autre%s\n	  %s1) 1920x1080   2) 1280x720 (recommended on Pi Zero: lighter load)   3) other%s\n
\n  %s3. Aéroport proche (facultatif)%s\n	\n  %s3. Nearby airport (optional)%s\n
\n  %s4. Clé API CARTO%s\n	\n  %s4. CARTO API key%s\n
  %sLa carte est dessinée à partir du fond de carte CARTO, qui exige une clé API personnelle.\n	  %sThe map is drawn from the CARTO base map, which requires a personal API key.\n
  Elle est gratuite pour un usage non commercial (jusqu'à 5 millions de tuiles par mois : largement\n	  It is free for non-commercial use (up to 5 million tiles per month: more than\n
  suffisant ici, la carte n'est téléchargée qu'à sa construction) et ne demande pas de compte CARTO.%s\n	  enough here, the map is only downloaded when it is built) and needs no CARTO account.%s\n
  %sPour l'obtenir en une minute, depuis votre ordinateur ou votre téléphone :%s\n	  %sTo get it in one minute, from your computer or your phone:%s\n
    1) ouvrez %s%s%s\n	    1) open %s%s%s\n
    2) saisissez votre adresse e-mail et acceptez les conditions (usage personnel, non commercial)\n	    2) enter your e-mail address and accept the terms (personal, non-commercial use)\n
    3) copiez la clé reçue par e-mail, puis collez-la ci-dessous (elle reste visible : vérifiez le collage)\n	    3) copy the key received by e-mail, then paste it below (it stays visible: check the paste)\n
  %sGardez cette clé pour vous : elle est personnelle, ne la partagez pas.%s\n	  %sKeep this key to yourself: it is personal, do not share it.%s\n
  %sL'installation attend : prenez le temps de la récupérer, puis revenez ici.%s\n	  %sThe installation waits: take the time to get it, then come back here.%s\n
\n  %s5. Mot de passe de l'interface web%s\n	\n  %s5. Web interface password%s\n
  %sProtège l'accès à webadmin depuis votre réseau. Entrée = en générer un automatiquement.\n  La saisie reste visible : vous voyez ce que vous tapez.%s\n	  %sProtects access to webadmin from your network. Enter = generate one automatically.\n  The input stays visible: you can see what you type.%s\n
  %sAucun mot de passe n'est enregistré pour l'interface web.%s\n	  %sNo password is stored for the web interface.%s\n
\n  %s6. Home Assistant / MQTT (facultatif)%s\n	\n  %s6. Home Assistant / MQTT (optional)%s\n
\n  %s7. Veille d'écran fiable%s\n	\n  %s7. Reliable screen sleep%s\n
  %sCorrectif qui empêche certains moniteurs de se rallumer seuls en veille (redémarrage conseillé).%s\n	  %sFix that stops some monitors from waking up by themselves during sleep (a reboot is recommended).%s\n
\n  %sRécapitulatif%s\n	\n  %sSummary%s\n
    Position : %s, %s   Rayon : %s km   Carte : %sx%s\n	    Position: %s, %s   Radius: %s km   Map: %sx%s\n
    Aéroport : %s   Clé CARTO : %s\n	    Airport: %s   CARTO key: %s\n
    MQTT : %s   Correctif écran : %s   Redémarrage auto : %s\n\n	    MQTT: %s   Screen fix: %s   Auto reboot: %s\n\n
\n  Installation annulée.\n\n	\n  Installation cancelled.\n\n
  %sLe mot de passe sudo peut vous être demandé une fois.%s\n	  %sThe sudo password may be asked once.%s\n
  %sToutes les questions sont posées : l'installation se déroule maintenant sans intervention.%s\n	  %sAll the questions have been asked: the installation now runs unattended.%s\n
  %sInterface web%s  http://%s.local:%s   ou   http://%s:%s\n	  %sWeb interface%s  http://%s.local:%s   or   http://%s:%s\n
  %sIdentifiant%s    %s\n	  %sUsername%s       %s\n
  %sMot de passe%s   %s%s%s   (notez-le, il ne sera plus affiché)\n	  %sPassword%s       %s%s%s   (write it down, it will not be shown again)\n
  %sMot de passe%s   celui que vous avez saisi\n	  %sPassword%s       the one you entered\n
\n  %sCommandes utiles%s  fd logs   fd status   fd restart\n	\n  %sUseful commands%s  fd logs   fd status   fd restart\n
  %sRéglages%s          tout se règle depuis l'interface web (onglet Réglages)\n	  %sSettings%s          everything is set from the web interface (Settings tab)\n
  %sDocumentation%s     %s/docs/FLIGHT_DISPLAY_DOCUMENTATION.md\n	  %sDocumentation%s     %s/docs/FLIGHT_DISPLAY_DOCUMENTATION.en.md\n
\n  %s%s La carte n'est pas construite : obtenez une clé CARTO (%s), saisissez-la dans webadmin\n    (Réglages, Carte et position), puis « Reconstruire la carte » en bas de la page.%s\n	\n  %s%s The map is not built: get a CARTO key (%s), enter it in webadmin\n    (Settings, Map and position), then "Rebuild the map" at the bottom of the page.%s\n
\n  %sPoints d'attention%s\n	\n  %sPoints to note%s\n
  %sRedémarrage dans 10 secondes pour finaliser (Ctrl+C pour annuler)...%s\n	  %sRebooting in 10 seconds to finish (Ctrl+C to cancel)...%s\n
  %sUn redémarrage est nécessaire pour finaliser : sudo reboot%s\n	  %sA reboot is needed to finish: sudo reboot%s\n
== Script de mise en veille de l'écran	== Screen sleep script
== Garde de veille (remet l'écran en veille s'il se rallume tout seul)	== Sleep guard (puts the screen back to sleep if it wakes up by itself)
== Service systemd flightadmin	== flightadmin systemd service
Correctif déjà présent	Fix already present
cmdline.txt introuvable	cmdline.txt not found
Carte absente : le programme d'affichage démarrera après la construction de la carte	Map missing: the display program will start after the map is built
» 1/3 Mise à jour de pip	» 1/3 Updating pip
» 2/3 Installation des bibliothèques (peut être long sur un Pi Zero)	» 2/3 Installing the libraries (can take a while on a Pi Zero)
» 3/3 Vérification des modules	» 3/3 Checking the modules
Aucune dépendance supplémentaire	No additional dependency
Analyse de build_map_vector.py impossible (voir les lignes ci-dessus)	Analysis of build_map_vector.py impossible (see the lines above)
== Droits sudo limités pour %s	== Limited sudo rights for %s
Interface web installée (port %s)	Web interface installed (port %s)
» Installation de %s	» Installing %s
Le dossier %s existe et n'est pas un dépôt Git	The folder %s exists and is not a Git repository
adresse-ip	ip-address
webadmin.py introuvable dans %s	webadmin.py not found in %s
webadmin_mqtt.py introuvable dans %s	webadmin_mqtt.py not found in %s
webadmin_update.py introuvable dans %s	webadmin_update.py not found in %s
i18n.py introuvable dans %s	i18n.py not found in %s
Installation automatique : configuration par défaut (aéroport de Bordeaux-Mérignac, carte fournie, MQTT désactivé).	Automatic installation: default configuration (Bordeaux-Merignac airport, ready-made map, MQTT disabled).
Appuyez sur une touche (ou Ctrl+C) pour passer à l'installation manuelle ; sinon elle démarre toute seule.	Press a key (or Ctrl+C) to switch to the manual installation; otherwise it starts by itself.
Démarrage automatique dans %s s...	Automatic start in %s s...
Installation automatique sans terminal : sudo doit fonctionner sans mot de passe (sudo -n).	Automatic installation without a terminal: sudo must work without a password (sudo -n).
Installation automatique	Automatic installation
Votre configuration est conservée : seul le logiciel est mis à jour.	Your configuration is kept: only the software is updated.
Position et réglages : configuration d'exemple (aéroport de Bordeaux-Mérignac)	Position and settings: sample configuration (Bordeaux-Merignac airport)
Fond de carte : la carte fournie avec le logiciel (aucune clé CARTO nécessaire pour démarrer)	Base map: the map supplied with the software (no CARTO key needed to start)
MQTT désactivé ; vous réglerez tout depuis webadmin à la fin de l'installation	MQTT disabled; you will set everything from webadmin at the end of the installation
Aucun mot de passe n'est défini pour webadmin : toute personne de votre réseau local peut le piloter. Définissez-en un dans webadmin (Réglages, Serveur web).	No webadmin password is set: anyone on your local network can control it. Set one in webadmin (Settings, Web server).
Dossier defaults/ introuvable : la carte devra être construite depuis webadmin	defaults/ folder not found: the map will have to be built from webadmin
Carte de Bordeaux-Mérignac installée	Bordeaux-Merignac map installed
Règles de types d'avion installées	Aircraft type rules installed
  %sL'installation se déroule seule (plusieurs minutes, selon votre Pi et votre connexion).%s\n	  %sThe installation runs by itself (several minutes, depending on your Pi and your connection).%s\n
Carte fournie (aéroport de Bordeaux-Mérignac) : aucune construction nécessaire	Supplied map (Bordeaux-Merignac airport): no build needed
Carte fournie introuvable : construisez la carte depuis webadmin (Réglages, Carte et position) avec une clé CARTO.	Supplied map not found: build the map from webadmin (Settings, Map and position) with a CARTO key.
  %sMot de passe%s   aucun : définissez-en un dans webadmin (Réglages, Serveur web)\n	  %sPassword%s       none: set one in webadmin (Settings, Web server)\n
\n  %sPosition%s       aéroport de Bordeaux-Mérignac : réglez la vôtre dans webadmin (Réglages, Carte et position)\n	\n  %sPosition%s       Bordeaux-Merignac airport: set yours in webadmin (Settings, Map and position)\n
Cet utilisateur (%s) n'a pas les droits sudo : l'installation s'arrête ici.	This user (%s) does not have sudo rights: the installation stops here.
L'installeur a besoin de sudo pour installer les paquets, créer les services et régler la veille de l'écran.	The installer needs sudo to install the packages, create the services and set up the screen sleep.
Solutions possibles :	Possible solutions:
Reflashez la carte avec Raspberry Pi Imager en renseignant le nom d'utilisateur et le mot de passe : l'utilisateur créé par Imager a les droits sudo.	Re-flash the card with Raspberry Pi Imager, filling in the username and password: the user created by Imager has sudo rights.
Ou, depuis un compte administrateur : sudo usermod -aG sudo %s (puis déconnectez-vous et reconnectez-vous).	Or, from an administrator account: sudo usermod -aG sudo %s (then log out and log back in).
Sans autre compte administrateur : voir la documentation, section 0.5 (« Pas de droits sudo »).	With no other administrator account: see the documentation, section 0.5 ("No sudo rights").
Le mot de passe sudo est demandé maintenant, une seule fois : l'installation se déroule ensuite sans intervention.	The sudo password is asked now, once: the installation then runs without any intervention.
EN_TABLE
}

# ------------------------------------------------------------------ verifications
preflight() {
  [ "$(id -u)" -ne 0 ] || [ -n "$DRY" ] || die "Ne lancez pas ce script avec sudo ni en root : utilisez votre utilisateur normal (il demandera sudo si besoin)."
  [ -r /etc/os-release ] && . /etc/os-release
  case "${ID:-}${ID_LIKE:-}" in *debian*|*raspbian*) ok "$(Lf 'Système : %s' "${PRETTY_NAME:-Debian}")" ;; *) warn "Système non Debian/Raspberry Pi OS : l'installation peut échouer." ;; esac
  local model="" mem free arch
  [ -r /proc/device-tree/model ] && model=$(tr -d '\0' </proc/device-tree/model)
  if [ -n "$model" ]; then ok "$(Lf 'Matériel : %s' "$model")"; else warn "Matériel non identifié comme un Raspberry Pi."; fi
  arch=$(uname -m); info "$(Lf 'Architecture : %s' "$arch")"
  mem=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)
  if [ "$mem" -ge 350 ]; then ok "$(Lf 'Mémoire : %s Mo' "$mem")"; else warn "$(Lf 'Mémoire faible (%s Mo).' "$mem")"; fi
  free=$(df -Pm "$HOME" | awk 'NR==2 {print $4}')
  if [ "${free:-0}" -ge 1500 ]; then ok "$(Lf 'Espace disque libre : %s Mo' "$free")"; else warn "$(Lf 'Espace disque limité (%s Mo) : 1,5 Go conseillés.' "$free")"; fi
  command -v systemctl >/dev/null || die "systemd est requis."
  if [ -z "$DRY" ]; then
    if curl -fsI --max-time 15 https://github.com >/dev/null 2>&1; then ok "Connexion Internet"; else die "Pas de connexion Internet (vérifiez le Wi-Fi)."; fi
  fi
  case "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" in yes) ok "Horloge synchronisée" ;; *) warn "Horloge non synchronisée (NTP) : l'heure doit être exacte pour Flightradar24." ;; esac
}

need_sudo() {
  [ -n "$DRY" ] && return 0
  if [ -n "$YES" ]; then sudo -n true 2>/dev/null || die "Mode sans questions : sudo doit fonctionner sans mot de passe (sudo -n)."
  elif [ -n "$AUTO" ] && [ -z "$HAVE_TTY" ]; then sudo -n true 2>/dev/null || die "Installation automatique sans terminal : sudo doit fonctionner sans mot de passe (sudo -n)."
  else
  if ! sudo -n true 2>/dev/null; then
    pt '  %sLe mot de passe sudo peut vous être demandé une fois.%s\n' "$DIM" "$R"
    sudo -v || die "sudo est nécessaire."
  fi
  fi
  ( while true; do sudo -n true 2>/dev/null; sleep 45; kill -0 "$$" 2>/dev/null || exit; done ) &
  KEEPALIVE=$!
}

check_sudo() {  # l'installation s'arrete des le debut si l'utilisateur n'a pas les droits sudo
  [ -n "$DRY" ] && return 0
  local u; u=$(id -un)
  if command -v sudo >/dev/null 2>&1; then
    sudo -n true 2>/dev/null && return 0
    case " $(id -nG) " in *" sudo "*|*" wheel "*|*" admin "*) return 0 ;; esac
  fi
  printf '\n  %s%s %s%s\n\n' "$RED" "$KOC" "$(Lf "Cet utilisateur (%s) n'a pas les droits sudo : l'installation s'arrête ici." "$u")" "$R"
  printf '  %s\n\n' "$(L "L'installeur a besoin de sudo pour installer les paquets, créer les services et régler la veille de l'écran.")"
  printf '  %s%s%s\n' "$B" "$(L "Solutions possibles :")" "$R"
  printf '    • %s\n' "$(L "Reflashez la carte avec Raspberry Pi Imager en renseignant le nom d'utilisateur et le mot de passe : l'utilisateur créé par Imager a les droits sudo.")"
  printf '    • %s\n' "$(Lf "Ou, depuis un compte administrateur : sudo usermod -aG sudo %s (puis déconnectez-vous et reconnectez-vous)." "$u")"
  printf '    • %s\n\n' "$(L "Sans autre compte administrateur : voir la documentation, section 0.5 (« Pas de droits sudo »).")"
  exit 1
}

early_sudo() {  # mot de passe sudo demande tout de suite, une seule fois : le reste de l'installation se deroule sans intervention
  [ -n "$DRY" ] && return 0
  [ -n "$YES" ] && return 0
  [ -n "$HAVE_TTY" ] || return 0
  sudo -n true 2>/dev/null && return 0
  printf '  %s%s%s\n' "$DIM" "$(L "Le mot de passe sudo est demandé maintenant, une seule fois : l'installation se déroule ensuite sans intervention.")" "$R"
  sudo -v || die "sudo est nécessaire."
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
    echo "$(Lf "Le dossier %s existe et n'est pas un dépôt Git" "$APP_DIR")" >&2; return 1
  else
    git clone --progress --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
  fi
}

make_venv() {
  [ -x "$APP_DIR/venv/bin/python" ] || python3 -m venv --system-site-packages "$APP_DIR/venv"
  if [ -n "$DRY" ]; then echo "[simulation] pip install -r requirements.txt"; return 0; fi
  local pip=("$APP_DIR/venv/bin/python" -m pip --disable-pip-version-check)
  echo "$(L '» 1/3 Mise à jour de pip')"
  "${pip[@]}" install --upgrade pip --progress-bar off || return 1
  echo "$(L '» 2/3 Installation des bibliothèques (peut être long sur un Pi Zero)')"
  "${pip[@]}" install --prefer-binary --progress-bar off -r "$APP_DIR/requirements.txt" || return 1
  echo "$(L '» 3/3 Vérification des modules')"
  "$APP_DIR/venv/bin/python" -c "import pygame, requests, FlightRadarAPI; print('modules ok')"
}

map_deps() {
  local py="$APP_DIR/venv/bin/python" list name pipn
  [ -f "$APP_DIR/build_map_vector.py" ] || return 0
  list=$("$py" - "$APP_DIR" <<'PY'
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
    if name in sys.stdlib_module_names:
        continue
    if os.path.exists(os.path.join(root, name + ".py")) or os.path.isdir(os.path.join(root, name)):
        continue
    if importlib.util.find_spec(name) is None:
        print(name, alias.get(name, name))
PY
  ) || { echo "$(L 'Analyse de build_map_vector.py impossible (voir les lignes ci-dessus)')" >&2; return 1; }
  # Filet de sécurité : Pillow est indispensable à la carte
  if ! "$py" -c "import PIL" 2>/dev/null && ! printf '%s\n' "$list" | grep -q '^PIL '; then
    list="$list"$'\n'"PIL pillow"
  fi
  if [ -z "$(printf '%s' "$list" | tr -d '[:space:]')" ]; then echo "$(L 'Aucune dépendance supplémentaire')"; return 0; fi
  if [ -n "$DRY" ]; then echo "[simulation] pip install : $list"; return 0; fi
  while read -r name pipn; do
    [ -z "$name" ] && continue
    echo "$(Lf '» Installation de %s' "$pipn")"
    "$py" -m pip install --prefer-binary --progress-bar off "$pipn" || return 1
  done <<<"$list"
}

install_defaults() {  # carte et regles de types fournies (dossier defaults/) : copiees seulement si absentes
  local d="$APP_DIR/defaults"
  if [ ! -d "$d" ]; then echo "$(L 'Dossier defaults/ introuvable : la carte devra être construite depuis webadmin')"; return 0; fi
  if [ ! -f background.png ] && [ ! -f map_meta.json ] && [ -f "$d/background.png" ] && [ -f "$d/map_meta.json" ]; then
    cp "$d/background.png" "$d/map_meta.json" . && echo "$(L 'Carte de Bordeaux-Mérignac installée')"
  fi
  if [ ! -f types_extra.txt ] && [ -f "$d/types_extra.txt" ]; then
    cp "$d/types_extra.txt" . && echo "$(L "Règles de types d'avion installées")"
  fi
}

write_configs() {
  cd "$APP_DIR" || return 1
  [ -f config.ini ] || cp config.ini.example config.ini
  if [ -z "$KEEP" ] && [ -n "$AUTO" ]; then
    # installation automatique : on garde les valeurs du modele (position, rayon, taille...), seule la langue suit le systeme
    ini_set config.ini general language "${LANG_UI:-fr}"
    ini_set config.ini display fullscreen true
    install_defaults
  elif [ -z "$KEEP" ]; then
    ini_set config.ini position latitude "$LAT"
    ini_set config.ini position longitude "$LON"
    ini_set config.ini position radius_km "$RADIUS"
    ini_set config.ini display fullscreen true
    ini_set config.ini display width "$MAPW"
    ini_set config.ini display height "$MAPH"
    ini_set config.ini ground airport_iata "$AIRPORT"
    ini_set config.ini map carto_key "$CARTO_KEY"
    ini_set config.ini general language "${LANG_UI:-fr}"
  fi
  # Réglages de l'interface web (valeurs par défaut, sans écraser vos modifications)
  ini_default config.ini server host 0.0.0.0
  ini_default config.ini server port 8080
  ini_default config.ini server user admin
  ini_default config.ini app config config.ini
  ini_default config.ini app runtime cache/runtime.json
  ini_default config.ini app service "$SERVICE"
  ini_default config.ini app python "$(venv_python)"
  ini_default config.ini app build_script build_map_vector.py
  ini_default config.ini app sudo "sudo -n"
  ini_default config.ini screen helper "$HELPER"
  ini_default config.ini screen flag /run/flight-screen-off
  ini_default config.ini build stop_display true
  ini_default config.ini update auto_check true
  ini_default config.ini update check_hours 12
  ini_default config.ini update auto_install false
  ini_default config.ini update channel stable
  ini_default config.ini general language fr
  ini_default config.ini schedule enabled false
  ini_default config.ini storage warn_percent 90
  ini_default config.ini storage auto_clean false
  ini_default config.ini storage cache_max_mb 200
  ini_default config.ini mqtt enabled false
  ini_default config.ini mqtt port 1883
  ini_default config.ini mqtt tls false
  ini_default config.ini mqtt base_topic flightdisplay
  ini_default config.ini mqtt discovery_prefix homeassistant
  ini_default config.ini mqtt device_name "Flight display"
  ini_default config.ini mqtt interval 30
  if [ -n "$WEBPW" ]; then ini_set config.ini server password "$WEBPW"; fi
  if [ -n "$MQTT_ON" ]; then
    ini_set config.ini mqtt enabled true
    ini_set config.ini mqtt host "$MQTT_HOST"
    ini_set config.ini mqtt port "$MQTT_PORT"
    ini_set config.ini mqtt user "$MQTT_USER"
    ini_set config.ini mqtt password "$MQTT_PASS"
  fi
  chmod 600 config.ini
}

venv_python() {
  if [ -x "$APP_DIR/venv/bin/python" ]; then echo "$APP_DIR/venv/bin/python"
  elif [ -x "$APP_DIR/.venv/bin/python" ]; then echo "$APP_DIR/.venv/bin/python"
  else command -v python3; fi
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
  local user tmp systemctl_bin port
  user=$(id -un)
  cd "$APP_DIR" || return 1
  [ -f webadmin.py ] || { echo "$(Lf 'webadmin.py introuvable dans %s' "$APP_DIR")"; return 1; }
  [ -f webadmin_mqtt.py ] || { echo "$(Lf 'webadmin_mqtt.py introuvable dans %s' "$APP_DIR")"; return 1; }
  [ -f webadmin_update.py ] || { echo "$(Lf 'webadmin_update.py introuvable dans %s' "$APP_DIR")"; return 1; }
  [ -f i18n.py ] || { echo "$(Lf 'i18n.py introuvable dans %s' "$APP_DIR")"; return 1; }
  systemctl_bin=/usr/bin/systemctl
  [ -x "$systemctl_bin" ] || systemctl_bin=$(command -v systemctl)
  tmp=$(mktemp)

  echo "$(L '== Script de mise en veille de l'"'"'écran')"
  cat >"$tmp" <<'HELPER_EOF'
#!/bin/sh
# flight-screen on|off|version : veille / reveil de l'ecran (version 2).
# La veille NE ARRETE PLUS le programme d'affichage : des qu'il voit le fichier temoin, il cesse de dessiner ET ferme l'affichage
# (tant qu'il le garde, le signal ne peut pas etre coupe) mais continue de suivre les avions (historique, alertes). On bascule ensuite
# sur un terminal virtuel inutilise, puis la sortie video est coupee par le framebuffer (le signal HDMI est reellement coupe).
# Le reveil fait l'inverse : le programme rouvre l'affichage. Repli sur setterm si le framebuffer n'est pas disponible.
SVC=__SERVICE__
MAIN_VT=__MAIN_VT__
IDLE_VT=__IDLE_VT__
FLAG=/run/flight-screen-off
FB=/sys/class/graphics/fb0/blank

blank() {
  if [ -w "$FB" ]; then
    echo 4 > "$FB"
  else
    setterm --term linux --powersave powerdown --blank force < /dev/tty$IDLE_VT > /dev/tty$IDLE_VT 2>/dev/null || true
  fi
}
unblank() {
  if [ -w "$FB" ]; then
    echo 0 > "$FB"
  else
    setterm --term linux --powersave off --blank poke < /dev/tty$IDLE_VT > /dev/tty$IDLE_VT 2>/dev/null || true
  fi
}

case "$1" in
  version)
    echo 2
    ;;
  off)
    touch "$FLAG"
    sleep 2   # laisse le programme voir le fichier temoin et fermer l'affichage
    chvt "$IDLE_VT"
    sleep 1
    blank
    ;;
  on)
    rm -f "$FLAG"
    unblank
    chvt "$MAIN_VT"
    ;;
  *)
    echo "usage : flight-screen on|off|version" >&2
    exit 2
    ;;
esac
HELPER_EOF
  sed -i "s|__SERVICE__|$SERVICE|; s|__MAIN_VT__|$MAIN_VT|; s|__IDLE_VT__|$IDLE_VT|" "$tmp"
  sudo install -m 755 -o root -g root "$tmp" "$HELPER"

  echo "$(L '== Garde de veille (remet l'"'"'écran en veille s'"'"'il se rallume tout seul)')"
  cat >"$tmp" <<'GUARD_EOF'
#!/bin/sh
# Pendant une veille demandee (le programme tourne toujours, sans dessiner), verifie toutes les 20 s que la sortie video est bien eteinte.
# Sinon, la coupe a nouveau et note l'evenement : journalctl -t flight-screen-guard
SVC=__SERVICE__
FLAG=/run/flight-screen-off
FB=/sys/class/graphics/fb0/blank
IDLE_VT=__IDLE_VT__
while true; do
  if [ -f "$FLAG" ]; then
    if grep -q On /sys/class/drm/card*-HDMI-A-*/dpms 2>/dev/null; then
      if [ -w "$FB" ]; then
        echo 4 > "$FB"
      else
        setterm --term linux --powersave powerdown --blank force < /dev/tty$IDLE_VT > /dev/tty$IDLE_VT 2>/dev/null
      fi
      logger -t flight-screen-guard "écran rallumé pendant la veille : remis en veille"
    fi
  fi
  sleep 20
done
GUARD_EOF
  sed -i "s|__SERVICE__|$SERVICE|; s|__IDLE_VT__|$IDLE_VT|" "$tmp"
  sudo install -m 755 -o root -g root "$tmp" "$GUARD"
  cat >"$tmp" <<'SVC_EOF'
[Unit]
Description=Garde de la veille d'ecran Flight display

[Service]
ExecStart=/usr/local/bin/flight-screen-guard
Restart=always

[Install]
WantedBy=multi-user.target
SVC_EOF
  sudo install -m 644 -o root -g root "$tmp" /etc/systemd/system/flight-screen-guard.service

  echo "$(Lf '== Droits sudo limités pour %s' "$user")"
  pt '%s ALL=(root) NOPASSWD: %s start %s, %s stop %s, %s restart %s, %s reboot, %s poweroff, %s on, %s off\n' \
    "$user" "$systemctl_bin" "$SERVICE" "$systemctl_bin" "$SERVICE" "$systemctl_bin" "$SERVICE" \
    "$systemctl_bin" "$systemctl_bin" "$HELPER" "$HELPER" >"$tmp"
  sudo visudo -cf "$tmp" >/dev/null || { echo "Fichier sudoers invalide, abandon"; rm -f "$tmp"; return 1; }
  sudo install -m 440 -o root -g root "$tmp" /etc/sudoers.d/flightadmin

  echo "$(L '== Service systemd flightadmin')"
  cat >"$tmp" <<EOF
[Unit]
Description=Flight display - administration web
After=network-online.target
Wants=network-online.target

[Service]
User=$user
SupplementaryGroups=systemd-journal
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/webadmin.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  sudo install -m 644 -o root -g root "$tmp" /etc/systemd/system/flightadmin.service
  rm -f "$tmp"
  sudo systemctl daemon-reload
  sudo systemctl enable flightadmin.service flight-screen-guard.service
  sudo systemctl restart flightadmin.service
  sudo systemctl restart flight-screen-guard.service
  sleep 1
  port=$(ini_get "$APP_DIR/config.ini" server port)
  echo "$(Lf 'Interface web installée (port %s)' "${port:-8080}")"
}

hdmi_fix() {
  local f=/boot/firmware/cmdline.txt
  [ -f "$f" ] || f=/boot/cmdline.txt
  [ -f "$f" ] || { echo "$(L 'cmdline.txt introuvable')"; return 1; }
  # deux options : force_hotplug (ancien pilote) et video=HDMI-A-1:D (pilote KMS actuel, noyau 6.x) ; chacune n'est ajoutee que si elle manque
  local todo=""
  grep -q 'vc4.force_hotplug' "$f" || todo="$todo vc4.force_hotplug=1"
  grep -q 'video=HDMI-A-1' "$f" || todo="$todo video=HDMI-A-1:D"
  if [ -z "$todo" ]; then echo "$(L 'Correctif déjà présent')"; return 0; fi
  [ -f "$f.bak" ] || sudo cp "$f" "$f.bak"
  sudo sed -i "1 s/\$/$todo/" "$f"
}

start_all() {
  if [ -n "$MAP_OK" ]; then
    sudo systemctl enable --now $SERVICE
    sleep 6
    [ -n "$DRY" ] || systemctl is-active --quiet $SERVICE
  else
    sudo systemctl enable $SERVICE
    echo "$(L 'Carte absente : le programme d'"'"'affichage démarrera après la construction de la carte')"
  fi
}

check_web() {
  if [ -n "$DRY" ]; then echo "[simulation] test de webadmin"; return 0; fi
  local port user pw i
  port=$(ini_get "$APP_DIR/config.ini" server port); port="${port:-8080}"
  user=$(ini_get "$APP_DIR/config.ini" server user); user="${user:-admin}"
  pw="${WEBPW:-$(ini_get "$APP_DIR/config.ini" server password)}"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    curl -fs --max-time 5 -u "$user:$pw" "http://127.0.0.1:$port/api/status" >/dev/null && return 0
    sleep 2
  done
  return 1
}

# ------------------------------------------------------------------ programme principal
: >"$LOG" 2>/dev/null || LOG=/tmp/flightdisplay-install.log
if [ -n "$UI" ]; then clear; fi
if [ -z "$LANG_UI" ]; then
  if [ -n "$YES" ]; then LANG_UI=fr
  else LANG_UI=$(sys_lang); LANG_GUESS=1; fi  # langue du systeme ; demandee seulement en installation manuelle
fi
if [ "$LANG_UI" = en ]; then load_en; fi
banner
check_sudo
early_sudo
if [ -z "$YES" ] && [ -z "$MANUAL" ]; then
  # Installation automatique par defaut ; un delai laisse la possibilite de passer en manuel
  if [ -n "$HAVE_TTY" ] && [ -z "$FORCE_AUTO" ] && [ "$COUNTDOWN" -gt 0 ] 2>/dev/null; then countdown "$COUNTDOWN"; fi
  [ -n "$MANUAL" ] || AUTO=1
fi
if [ -n "$MANUAL" ]; then
  [ -n "$HAVE_TTY" ] || die "Aucun terminal interactif disponible (lancez la commande depuis une session SSH, ou utilisez --yes)."
  if [ -n "$LANG_GUESS" ]; then
    printf '\n  Langue / Language :   1) Français   2) English   [%s] : ' "$([ "$LANG_UI" = en ] && echo 2 || echo 1)"
    IFS= read -r _l <&3 || _l=""
    case "$_l" in 2|en|EN|English|english) LANG_UI=en ;; 1|fr|FR|Français|francais) LANG_UI=fr ;; esac
    if [ "$LANG_UI" = en ]; then load_en; fi
    if [ -n "$UI" ]; then clear; fi
    banner
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
if [ -f "$SCRIPT_DIR/main.py" ] && [ -f "$SCRIPT_DIR/build_map_vector.py" ]; then
  APP_DIR="$SCRIPT_DIR"
else
  APP_DIR="${FD_DIR:-$HOME/flightdisplay}"
fi

title "Vérification de votre Raspberry Pi"
preflight
info "$(Lf "Dossier d'installation : %s" "$APP_DIR")"
info "$(Lf 'Journal détaillé : %s' "$LOG")"
need_sudo

KEEP=""
if [ -f "$APP_DIR/config.ini" ]; then
  printf '\n'; warn "$(Lf 'Une configuration existe déjà dans %s.' "$APP_DIR")"
  if [ -n "$YES" ]; then [ "${FD_KEEP:-1}" = 1 ] && KEEP=1
  elif [ -n "$AUTO" ]; then KEEP=1
  elif yesno "La conserver et ne mettre à jour que le logiciel ?" o; then KEEP=1; fi
fi
GENPW=""; LAT=""; LON=""; RADIUS=""; MAPW=""; MAPH=""; AIRPORT=""; CARTO_KEY=""; WEBPW=""; MQTT_ON=""; HDMI_FIX=""; NAME=""
MQTT_HOST=""; MQTT_PORT=""; MQTT_USER=""; MQTT_PASS=""
if [ -n "$AUTO" ]; then collect_auto
elif [ -z "$KEEP" ]; then if [ -n "$YES" ]; then collect_env; else collect_answers; fi; else collect_keep; fi

title "Installation"
if [ -n "$AUTO" ]; then pt '  %sL'"'"'installation se déroule seule (plusieurs minutes, selon votre Pi et votre connexion).%s\n' "$DIM" "$R"
else pt '  %sToutes les questions sont posées : l'"'"'installation se déroule maintenant sans intervention.%s\n' "$DIM" "$R"; fi

step "Mise à jour de la liste des paquets"
run_step "Téléchargement de la liste des paquets" apt_update

step "Installation des paquets système"
run_step "Installation de Python, pygame, Pillow, EGL, git, audio, MQTT" apt_install git curl python3-venv python3-pygame python3-requests python3-paho-mqtt fonts-dejavu-core alsa-utils kbd python3-pil libegl1 libegl-mesa0 libgles2

step "Téléchargement de Flight display"
if [ "$APP_DIR" = "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/main.py" ]; then ok "$(Lf 'Projet déjà présent dans %s' "$APP_DIR")"; else run_step "Récupération du projet depuis GitHub" fetch_project; fi

step "Environnement Python"
run_step "Création de l'environnement et installation des bibliothèques" make_venv

step "Dépendances de la carte"
if soft "Analyse et installation des dépendances de build_map_vector.py" map_deps; then :; else warn "Dépendances de la carte incomplètes (voir le journal)."; fi

step "Configuration"
if [ -n "$KEEP" ]; then
  run_step "Mise à jour de config.ini (vos réglages sont conservés)" write_configs
else
  run_step "Écriture de config.ini" write_configs
  if [ -n "$CARTO_KEY" ]; then info "Clé CARTO enregistrée dans config.ini (section [map], clé carto_key)"; fi
fi

step "Construction de la carte"
if [ -f "$APP_DIR/background.png" ] && [ -f "$APP_DIR/map_meta.json" ] && [ -n "$KEEP" ]; then
  ok "Carte déjà construite"; MAP_OK=1
elif [ -n "$AUTO" ]; then
  if [ -f "$APP_DIR/background.png" ] && [ -f "$APP_DIR/map_meta.json" ]; then
    ok "Carte fournie (aéroport de Bordeaux-Mérignac) : aucune construction nécessaire"; MAP_OK=1
  else
    warn "Carte fournie introuvable : construisez la carte depuis webadmin (Réglages, Carte et position) avec une clé CARTO."
  fi
elif [ -z "$KEEP" ] && [ -z "$CARTO_KEY" ]; then
  warn "Clé CARTO absente : étape ignorée. Construisez la carte plus tard depuis webadmin (Réglages, Carte et position)."
else
  if soft "Génération de la carte (plusieurs minutes sur un Pi Zero)" build_map; then
    if [ -f "$APP_DIR/background.png" ] && [ -f "$APP_DIR/map_meta.json" ]; then MAP_OK=1; else warn "Le script s'est terminé sans produire la carte."; fi
  else
    warn "La construction de la carte a échoué : vérifiez la clé CARTO (Réglages, Carte et position), puis relancez-la depuis webadmin."
  fi
fi

step "Service d'affichage"
run_step "$(Lf 'Création du service %s et de la commande fd' "$SERVICE")" install_services

step "Interface web d'administration"
run_step "Installation de webadmin (service, droits sudo, script de veille)" install_webadmin

step "Correctif de veille d'écran"
if [ -n "$HDMI_FIX" ]; then
  if soft "Ajout de vc4.force_hotplug=1 et video=HDMI-A-1:D au démarrage" hdmi_fix; then NEED_REBOOT=1; else warn "Correctif non appliqué (voir le journal)."; fi
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
PORT=$(ini_get "$APP_DIR/config.ini" server port); PORT="${PORT:-8080}"
WEBUSER=$(ini_get "$APP_DIR/config.ini" server user); WEBUSER="${WEBUSER:-admin}"
printf '\n%s%s' "$B" "$GRN"
printf '  ╔══════════════════════════════════════════════════════════╗\n'
_t=$(L 'Installation terminée'); _pad=$(( (58 - ${#_t}) / 2 ))
printf '  ║%*s%s%*s║
' "$_pad" '' "$_t" $((58 - _pad - ${#_t})) ''
printf '  ╚══════════════════════════════════════════════════════════╝%s\n\n' "$R"
pt '  %sInterface web%s  http://%s.local:%s   ou   http://%s:%s\n' "$B" "$R" "$HOST" "$PORT" "${IP:-$(L adresse-ip)}" "$PORT"
pt '  %sIdentifiant%s    %s\n' "$B" "$R" "$WEBUSER"
if [ -n "$AUTO" ] && [ -z "$KEEP" ]; then
  pt '  %sMot de passe%s   aucun : définissez-en un dans webadmin (Réglages, Serveur web)\n' "$B" "$R"
elif [ -n "$WEBPW" ]; then
  if [ -n "$GENPW" ]; then pt '  %sMot de passe%s   %s%s%s   (notez-le, il ne sera plus affiché)\n' "$B" "$R" "$YEL" "$WEBPW" "$R"
  else pt '  %sMot de passe%s   celui que vous avez saisi\n' "$B" "$R"; fi
fi
if [ -n "$AUTO" ] && [ -z "$KEEP" ]; then
  pt '\n  %sPosition%s       aéroport de Bordeaux-Mérignac : réglez la vôtre dans webadmin (Réglages, Carte et position)\n' "$B" "$R"
fi
pt '\n  %sCommandes utiles%s  fd logs   fd status   fd restart\n' "$B" "$R"
pt '  %sRéglages%s          tout se règle depuis l'"'"'interface web (onglet Réglages)\n' "$B" "$R"
pt '  %sDocumentation%s     %s/docs/FLIGHT_DISPLAY_DOCUMENTATION.md\n' "$B" "$R" "$APP_DIR"
if [ -z "$MAP_OK" ]; then
  pt '\n  %s%s La carte n'"'"'est pas construite : obtenez une clé CARTO (%s), saisissez-la dans webadmin\n    (Réglages, Carte et position), puis « Reconstruire la carte » en bas de la page.%s\n' "$YEL" "$WRN" "$CARTO_URL" "$R"
fi
if [ "${#WARNINGS[@]}" -gt 0 ]; then
  pt '\n  %sPoints d'"'"'attention%s\n' "$B$YEL" "$R"
  for w in "${WARNINGS[@]}"; do printf '    %s•%s %s\n' "$YEL" "$R" "$w"; done
fi
printf '\n'
if [ -n "$NEED_REBOOT" ]; then
  if [ -n "$AUTO_REBOOT" ]; then
    pt '  %sRedémarrage dans 10 secondes pour finaliser (Ctrl+C pour annuler)...%s\n' "$YEL" "$R"
    if [ -n "$DRY" ]; then echo "[simulation] sudo reboot"; else sleep 10; sudo reboot; fi
  else
    pt '  %sUn redémarrage est nécessaire pour finaliser : sudo reboot%s\n' "$YEL" "$R"
  fi
fi
printf '\n'
