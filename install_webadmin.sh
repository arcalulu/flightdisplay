#!/bin/bash
# Installe l'administration web : script de veille, droits sudo limites, service systemd.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Lancez : sudo bash install_webadmin.sh"; exit 1; }
RUN_USER="${SUDO_USER:-${1:-}}"
{ [ -n "$RUN_USER" ] && [ "$RUN_USER" != "root" ]; } || { echo "Utilisateur introuvable. Lancez : sudo bash install_webadmin.sh <utilisateur>"; exit 1; }
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE="${SERVICE:-flightdisplay}"
MAIN_VT="${MAIN_VT:-1}"
IDLE_VT="${IDLE_VT:-7}"
SYSTEMCTL=/usr/bin/systemctl
[ -x "$SYSTEMCTL" ] || SYSTEMCTL="$(command -v systemctl)"
HELPER=/usr/local/bin/flight-screen

PY_APP="$APP_DIR/venv/bin/python"
[ -x "$PY_APP" ] || PY_APP="$APP_DIR/.venv/bin/python"
[ -x "$PY_APP" ] || { PY_APP="$(command -v python3)"; echo "ATTENTION : venv introuvable, utilisation de $PY_APP pour la construction de la carte"; }

[ -f "$APP_DIR/webadmin.py" ] || { echo "webadmin.py introuvable dans $APP_DIR"; exit 1; }
[ -f "$APP_DIR/webadmin_mqtt.py" ] || { echo "webadmin_mqtt.py introuvable dans $APP_DIR"; exit 1; }
systemctl list-unit-files "$SERVICE.service" >/dev/null 2>&1 || echo "ATTENTION : le service $SERVICE n'existe pas (variable SERVICE=...)"

echo "== Paquets (chvt pour la veille, paho pour MQTT)"
if ! command -v chvt >/dev/null 2>&1 || ! python3 -c "import paho.mqtt.client" >/dev/null 2>&1; then
  apt-get install -y kbd python3-paho-mqtt || echo "ATTENTION : installation des paquets impossible (kbd, python3-paho-mqtt)"
fi

echo "== Script de mise en veille de l'ecran"
cat > "$HELPER" <<'EOF'
#!/bin/sh
# flight-screen on|off : veille / reveil de l'ecran.
# La veille arrete l'affichage, bascule sur un terminal virtuel inutilise (aucun texte n'y est ecrit)
# et met cette console en veille ; le reveil fait l'inverse.
SVC=__SERVICE__
MAIN_VT=__MAIN_VT__
IDLE_VT=__IDLE_VT__
FLAG=/run/flight-screen-off
case "$1" in
  off)
    systemctl stop "$SVC"
    sleep 1
    touch "$FLAG"
    chvt "$IDLE_VT"
    setterm --term linux --powersave powerdown --blank force < /dev/tty$IDLE_VT > /dev/tty$IDLE_VT 2>/dev/null || true
    ;;
  on)
    rm -f "$FLAG"
    setterm --term linux --powersave off --blank poke < /dev/tty$IDLE_VT > /dev/tty$IDLE_VT 2>/dev/null || true
    chvt "$MAIN_VT"
    systemctl start "$SVC"
    ;;
  *)
    echo "usage : flight-screen on|off" >&2
    exit 2
    ;;
esac
EOF
sed -i "s|__SERVICE__|$SERVICE|; s|__MAIN_VT__|$MAIN_VT|; s|__IDLE_VT__|$IDLE_VT|" "$HELPER"
chown root:root "$HELPER"; chmod 755 "$HELPER"

echo "== Droits sudo limites pour $RUN_USER"
TMP="$(mktemp)"
cat > "$TMP" <<EOF
$RUN_USER ALL=(root) NOPASSWD: $SYSTEMCTL start $SERVICE, $SYSTEMCTL stop $SERVICE, $SYSTEMCTL restart $SERVICE, $SYSTEMCTL reboot, $SYSTEMCTL poweroff, $HELPER on, $HELPER off
EOF
visudo -cf "$TMP" >/dev/null || { echo "Fichier sudoers invalide, abandon"; rm -f "$TMP"; exit 1; }
install -m 440 -o root -g root "$TMP" /etc/sudoers.d/flightadmin
rm -f "$TMP"

echo "== Configuration webadmin.ini"
INI="$APP_DIR/webadmin.ini"
[ -f "$INI" ] || { echo "webadmin.ini introuvable (copiez le modele fourni)"; exit 1; }
WA_PY="$PY_APP" python3 - "$INI" <<'EOF'
import os, re, sys
p = sys.argv[1]
lines = open(p, encoding="utf-8").read().splitlines()
for i, l in enumerate(lines):
    if re.match(r"^python\s*=\s*$", l):
        lines[i] = "python = " + os.environ["WA_PY"]
open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
if grep -Eq '^password[[:space:]]*=[[:space:]]*$' "$INI"; then
  read -rsp "Mot de passe pour l'interface web (Entree = aucun) : " WA_PW < /dev/tty || WA_PW=""
  echo
  if [ -n "$WA_PW" ]; then
    WA_PW="$WA_PW" python3 - "$INI" <<'EOF'
import os, re, sys
p = sys.argv[1]
lines = open(p, encoding="utf-8").read().splitlines()
done = False
for i, l in enumerate(lines):
    if not done and re.match(r"^password\s*=", l):
        lines[i] = "password = " + os.environ["WA_PW"]
        done = True
open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
EOF
  else
    echo "ATTENTION : aucun mot de passe, l'interface sera ouverte a tout le reseau local"
  fi
fi
chown "$RUN_USER":"$RUN_USER" "$INI"; chmod 600 "$INI"

echo "== Service systemd flightadmin"
cat > /etc/systemd/system/flightadmin.service <<EOF
[Unit]
Description=Flight display - administration web
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
SupplementaryGroups=systemd-journal
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/webadmin.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now flightadmin.service
sleep 1
systemctl --no-pager --lines=3 status flightadmin.service || true
PORT="$(sed -n 's/^port[[:space:]]*=[[:space:]]*//p' "$INI" | head -n1)"
echo
echo "Termine. Ouvrez : http://$(hostname).local:${PORT:-8080}"
