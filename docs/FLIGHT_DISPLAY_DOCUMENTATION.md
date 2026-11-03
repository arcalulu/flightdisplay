# Flight display — documentation unifiée

Affichage temps réel des avions autour de chez vous sur un Raspberry Pi Zero : carte vectorielle, fiches photo, alerte de proximité (son, teinte rouge), liste des avions au sol, et une interface web d'administration (webadmin) qui permet de tout régler depuis un téléphone ou un ordinateur : réglages, carte, logs, son, veille d'écran, MQTT et Home Assistant.

Cette documentation couvre l'installation automatique en une commande, l'installation manuelle complète depuis une carte SD vierge, toutes les modifications système nécessaires, puis la référence de chaque option du logiciel (`config.ini`), de webadmin (`webadmin.ini`, interface, API) et de MQTT.

## Sommaire

0. Démarrage rapide : installation automatique
1. Vue d'ensemble
2. Matériel et prérequis
3. Installer le Raspberry Pi (installation manuelle)
4. Installer Flight display
5. Services systemd et commande `fd`
6. Réglages système (audio, écran, carte SD, Wi-Fi)
7. Installer webadmin
8. Référence de `config.ini`
9. Fonctionnement de l'affichage
10. Référence de webadmin
11. MQTT et Home Assistant
12. Maintenance
13. Dépannage
14. Désinstallation

---

## 0. Démarrage rapide : installation automatique

L'installeur `install.sh` fait tout le travail des sections 3 à 7 : il pose quelques questions, installe les paquets, récupère le projet, construit la carte, crée les services et démarre l'affichage et webadmin. C'est la méthode recommandée.

### 0.1 Avant de commencer

1. Avec Raspberry Pi Imager, installez Raspberry Pi OS Lite (32-bit) sur la carte SD (voir 3.1). Dans la personnalisation, renseignez le nom d'hôte, un utilisateur, le Wi-Fi et activez SSH.
2. Tenez prêts : votre adresse (ou vos coordonnées), votre clé API CARTO (gratuite, voir 2 et le README), et si vous le souhaitez les identifiants de votre serveur MQTT.
3. Connectez-vous au Pi en SSH : `ssh <utilisateur>@<nom-du-pi>.local`.

### 0.2 La commande

```
bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh)
```

Sans `curl`, ou si vous préférez cloner d'abord :

```
sudo apt update && sudo apt install -y git
git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay
bash ~/flightdisplay/install.sh
```

Ne lancez pas le script avec `sudo` : il utilise votre utilisateur normal et demande le mot de passe sudo une fois si nécessaire. Il fonctionne avec n'importe quel nom d'utilisateur.

### 0.3 Les questions

| Question | Détail |
|---|---|
| Position | Votre adresse, convertie en coordonnées par le service OpenStreetMap Nominatim (l'adresse lui est envoyée une seule fois, les coordonnées sont arrondies à environ 11 m), ou une saisie manuelle de la latitude et de la longitude. |
| Rayon de la carte | De 1 à 200 km, 20 par défaut. |
| Résolution de la carte | 1920×1080, 1280×720 (conseillé sur Pi Zero : moins de charge) ou une taille personnalisée. Écrite dans `[display] width` et `height` de `config.ini`. |
| Aéroport proche | Code IATA à 3 lettres, facultatif. |
| Clé API CARTO | Saisie masquée. Écrite dans `config.ini`, section `[map]`, clé `carto_key`. Sans clé, la carte n'est pas construite (possible plus tard depuis webadmin). |
| Mot de passe de webadmin | Au moins 6 caractères, ou Entrée pour en générer un aléatoire (affiché une seule fois à la fin). |
| MQTT | Facultatif : serveur, port, identifiant, mot de passe. |
| Correctif de veille d'écran | Ajoute `vc4.force_hotplug=1` au démarrage (voir 3.6) ; redémarrage conseillé. |

Un récapitulatif est affiché avant le lancement.

### 0.4 Les étapes

| Étape | Action |
|---|---|
| 1 | Vérifications : système, matériel, mémoire, espace disque, Internet, horloge. |
| 2 | Mise à jour de la liste des paquets (`apt update`), avec barre de progression. |
| 3 | Installation des paquets : git, curl, Python, pygame, requests, paho-mqtt, polices, outils audio, kbd. |
| 4 | Récupération du projet depuis GitHub (ou mise à jour s'il est déjà cloné). |
| 5 | Environnement Python (venv) et bibliothèques (`requirements.txt`). |
| 6 | Dépendances de `build_map_vector.py` : le script est analysé et les modules manquants sont installés. |
| 7 | Écriture de `config.ini` et `webadmin.ini` (droits 600). |
| 8 | Construction de la carte (plusieurs minutes sur un Pi Zero). |
| 9 | Service `flightdisplay`, commande `fd`, groupes `video render input audio`. |
| 10 | webadmin : `install_webadmin.sh` (service, droits sudo limités, script de veille `flight-screen` et sa garde `flight-screen-guard`). |
| 11 | Correctif de veille d'écran (si accepté). |
| 12 | Démarrage des services et test de webadmin. |

L'écran montre pour chaque étape un indicateur animé, le temps écoulé, la dernière ligne de sortie et, pour les téléchargements, un pourcentage. Une barre globale indique l'avancement. Le détail complet est écrit dans le journal `~/flightdisplay-install.log`.

### 0.5 Si quelque chose échoue

- Une étape essentielle qui échoue arrête l'installeur avec un message clair, les dernières lignes du journal et le chemin du fichier. Corrigez la cause (réseau, espace disque), puis relancez la même commande : l'installeur reprend et conserve ce qui est déjà fait.
- Si seule la carte ne peut pas être construite (clé absente ou refusée, erreur du script), tout le reste est installé. webadmin fonctionne, et la carte se construit depuis l'onglet Carte après correction. Le programme d'affichage démarre automatiquement dès qu'une carte existe, ou avec « Programme d'affichage » dans Pilotage.
- Les avertissements non bloquants (horloge, espace disque, matériel non reconnu) sont rappelés dans le résumé final.

### 0.6 Relancer l'installeur

Si `config.ini` existe déjà, l'installeur propose de le conserver : il met alors à jour le logiciel et les services sans reposer les questions ni reconstruire la carte. En répondant non, il repose toutes les questions et réécrit les fichiers. Dans les deux cas, l'étape 10 réécrit `/usr/local/bin/flight-screen` et `/usr/local/bin/flight-screen-guard` avec les versions du dépôt : toute modification manuelle de ces deux scripts est écrasée.

### 0.7 Options et variables

| Élément | Effet |
|---|---|
| `--dry-run` | Simulation : le script déroule toutes les étapes sans rien installer. Utile pour voir ce qu'il va faire. |
| `--help` | Affiche l'aide. |
| `FD_DIR` | Dossier d'installation (par défaut `~/flightdisplay`, ou le dossier du script s'il est lancé depuis un clone). |
| `FD_REPO_URL`, `FD_BRANCH` | Dépôt et branche à cloner. |
| `FD_LOG` | Fichier journal (par défaut `~/flightdisplay-install.log`). |
| `NO_COLOR=1` | Désactive les couleurs. |

### 0.8 À la fin

Le résumé donne l'adresse de webadmin (`http://<nom-du-pi>.local:8080` et par adresse IP), l'identifiant `admin`, le mot de passe (s'il a été généré, il n'est plus affiché ensuite) et les commandes utiles. Si le correctif de veille a été appliqué, l'installeur propose de redémarrer le Pi.

Le mot de passe de webadmin, la clé CARTO et les identifiants MQTT sont stockés dans `config.ini` et `webadmin.ini`, avec des droits 600. Tous les réglages se modifient ensuite depuis webadmin.

---

## 1. Vue d'ensemble

### Composants

| Élément | Rôle |
|---|---|
| `main.py` | Programme d'affichage (pygame, sortie directe KMS/DRM, sans bureau graphique). |
| `build_map_vector.py` | Génère la carte `background.png` et `map_meta.json` à partir de `config.ini` (position, rayon, taille, clé CARTO). |
| `config.ini` | Réglages du programme. Modèle : `config.ini.example`. |
| `types_extra.txt` | Optionnel : associe des types d'avion inconnus à une forme d'icône. |
| `webadmin.py` | Serveur web d'administration (bibliothèque standard Python). |
| `webadmin_mqtt.py` | Pont MQTT / Home Assistant, chargé par webadmin. |
| `webadmin.ini` | Réglages de webadmin (port, mot de passe, chemins, MQTT). Modèle : `webadmin.ini.example`. |
| `install.sh` | Installeur automatique en une commande. |
| `install_webadmin.sh` | Installe webadmin, le script de veille, sa garde et les droits sudo (appelé par `install.sh`). |
| `/usr/local/bin/flight-screen` | Script root de veille et réveil de l'écran (créé par `install_webadmin.sh`). |
| `/usr/local/bin/flight-screen-guard` | Garde qui remet l'écran en veille s'il se rallume tout seul pendant une veille (créée par `install_webadmin.sh`). |
| `/usr/local/bin/fd` | Raccourci : `fd logs`, `fd restart`... |
| `cache/` | Détails d'avions, photos, état du son (`runtime.json`). |

### Services

| Service systemd | Programme | Utilisateur |
|---|---|---|
| `flightdisplay` | `main.py` | votre utilisateur |
| `flightadmin` | `webadmin.py` | votre utilisateur |
| `flight-screen-guard` | `flight-screen-guard` | root |

### Chemins utilisés dans ce document

| Élément | Valeur |
|---|---|
| Utilisateur | `flightdisplay` (n'importe quel nom convient avec l'installeur automatique) |
| Nom d'hôte | `flightradarpi` (accessible en `flightradarpi.local`) |
| Dossier de l'application | `/home/flightdisplay/flightdisplay` |
| Environnement Python | `/home/flightdisplay/flightdisplay/venv` |

Adaptez ces valeurs si vous en choisissez d'autres.

### Ce qui se règle où

| Besoin | Où |
|---|---|
| Tous les réglages du programme, de webadmin et de MQTT, la clé CARTO | webadmin, onglet Réglages (section 10) |
| Types d'avion inconnus | webadmin, Réglages, Types d'avion |
| Son (coupure, volume), veille de l'écran, relance, alimentation | webadmin, onglet Pilotage |
| Reconstruction de la carte | webadmin, onglet Carte |
| Éléments d'installation du système (services, sudoers, scripts de veille, `cmdline.txt`) | Installeur automatique, ou ligne de commande (sections 3 à 7) |

---

## 2. Matériel et prérequis

- Raspberry Pi Zero W (512 Mo de RAM). Le Zero 2 W fonctionne aussi, avec les mêmes étapes.
- Carte microSD de 16 Go ou plus, de préférence à endurance élevée.
- Alimentation 5 V adaptée au Pi.
- Un écran HDMI et un câble ou adaptateur mini-HDMI vers HDMI.
- Pour le son : un écran avec haut-parleurs ou sortie casque (le son sort par le HDMI), ou une carte son USB avec adaptateur OTG. Le Pi Zero n'a pas de prise jack.
- Un réseau Wi-Fi 2,4 GHz avec accès Internet. Le Pi Zero W ne gère pas le 5 GHz.
- Un ordinateur avec Raspberry Pi Imager et un client SSH.
- Une clé API CARTO, nécessaire pour construire la carte (le script télécharge le fond de carte vectoriel CARTO avec cette clé). Elle est gratuite pour un usage personnel et se demande sur `https://carto.com/basemaps/apikey/` : voir le README pour le pas à pas.
- Si vous utilisez Home Assistant : un serveur MQTT (par exemple Mosquitto) et ses identifiants.
- Pour l'installation manuelle : les fichiers du projet (`main.py`, `build_map_vector.py`, `config.ini.example`, `webadmin.py`, `webadmin_mqtt.py`, `webadmin.ini.example`, `install_webadmin.sh`, `requirements.txt`), soit par `git clone https://github.com/arcalulu/flightdisplay.git`, soit copiés depuis un ordinateur.

---

## 3. Installer le Raspberry Pi (installation manuelle)

Les sections 3 à 7 décrivent pas à pas ce que l'installeur automatique (section 0) réalise. Utilisez-les si vous préférez tout faire à la main, pour comprendre ce qui est installé, ou pour dépanner.

### 3.1 Flasher la carte SD

1. Installer Raspberry Pi Imager sur votre ordinateur.
2. Choisir l'appareil : Raspberry Pi Zero (ou Zero W).
3. Choisir le système : Raspberry Pi OS (other), puis Raspberry Pi OS Lite (32-bit). Le Zero W n'a pas de processeur 64 bits.
4. Choisir la carte SD.
5. Dans la personnalisation (Edit Settings), renseigner :
   - nom d'hôte : `flightradarpi` ;
   - utilisateur : `flightdisplay` (en minuscules) et un mot de passe ;
   - Wi-Fi : nom du réseau, mot de passe, pays (important pour l'activation du Wi-Fi) ;
   - localisation : fuseau `Europe/Paris`, clavier adapté ;
   - SSH : activé, avec mot de passe ou clé publique.
6. Écrire la carte, l'insérer dans le Pi, brancher l'écran puis l'alimentation.

Le premier démarrage prend plusieurs minutes sur un Zero.

### 3.2 Se connecter en SSH

```
ssh flightdisplay@flightradarpi.local
```

Si le nom ne se résout pas, utilisez l'adresse IP visible dans l'interface de votre box.

### 3.3 Mettre à jour le système

```
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

### 3.4 Fuseau horaire et horloge

L'heure du Pi doit être exacte : le programme compare l'horloge aux horodatages de Flightradar24 et affiche un avertissement en cas de décalage.

```
sudo timedatectl set-timezone Europe/Paris
timedatectl status
```

La ligne `System clock synchronized: yes` doit apparaître.

### 3.5 Paquets nécessaires

```
sudo apt install -y git curl python3-venv python3-pygame python3-pil python3-requests fonts-dejavu-core alsa-utils kbd python3-paho-mqtt libegl1 libegl-mesa0 libgles2
```

| Paquet | Pourquoi |
|---|---|
| `git`, `curl` | Récupération du projet et de l'installeur. |
| `python3-venv` | Création de l'environnement Python. |
| `python3-pygame` | Affichage et son. L'installer par apt apporte aussi les bibliothèques SDL nécessaires. |
| `python3-pil` | Pillow, bibliothèque d'images utilisée par `build_map_vector.py` pour construire la carte. |
| `python3-requests` | Téléchargement des photos et du fond de carte. |
| `fonts-dejavu-core` | Police utilisée par le programme (`DejaVuSans`). Sans elle, il se rabat sur une police par défaut. |
| `alsa-utils` | Outils audio (`aplay`, `alsamixer`, `speaker-test`). |
| `kbd` | Commande `chvt`, utilisée par la veille d'écran. |
| `python3-paho-mqtt` | MQTT / Home Assistant (même si vous ne l'utilisez pas encore : il s'active ensuite depuis webadmin). |
| `libegl1`, `libegl-mesa0`, `libgles2` | EGL et OpenGL ES, indispensables pour afficher sans bureau (pilote KMS/DRM). Sur Raspberry Pi OS Lite ils ne sont pas installés par défaut : sans eux le programme s'arrête avec `pygame.error: EGL not initialized`. |

### 3.6 Correctif du signal HDMI (hotplug)

Certains moniteurs coupent leur signal de détection en veille, ce qui fait croire au Pi qu'un écran vient d'être branché et rallume la sortie. Pour que le Pi ignore ces changements, ajouter `vc4.force_hotplug=1` à la fin de l'unique ligne de `cmdline.txt` :

```
sudo cp /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.bak
sudo sed -i '1 s/$/ vc4.force_hotplug=1/' /boot/firmware/cmdline.txt
cat /boot/firmware/cmdline.txt
sudo reboot
```

Le fichier doit rester sur une seule ligne. Sur certaines versions plus anciennes, il se trouve dans `/boot/cmdline.txt`. Conséquence : le Pi ne détecte plus un moniteur débranché ou changé à chaud, il faut alors le redémarrer. Vérification après le redémarrage : `grep -o 'vc4.force_hotplug=1' /proc/cmdline`.

---

## 4. Installer Flight display

### 4.1 Récupérer le projet et créer l'environnement Python

```
git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay
cd ~/flightdisplay
python3 -m venv --system-site-packages venv
./venv/bin/pip install -r requirements.txt
```

L'option `--system-site-packages` permet à l'environnement d'utiliser `pygame` et `requests` installés par apt. Vérification :

```
./venv/bin/python -c "import pygame, requests, FlightRadarAPI; print('ok')"
```

### 4.2 Alternative : copier les fichiers depuis un ordinateur

Au lieu du `git clone`, créez le dossier et copiez les fichiers depuis votre ordinateur :

```
mkdir -p ~/flightdisplay
scp main.py build_map_vector.py config.ini.example webadmin.py webadmin_mqtt.py webadmin.ini.example install_webadmin.sh requirements.txt flightdisplay@flightradarpi.local:~/flightdisplay/
```

Puis créez l'environnement Python comme en 4.1. Le fichier `types_extra.txt` est optionnel : il se crée depuis webadmin (section 9.8).

### 4.3 Dépendances de build_map_vector.py

Le script peut demander des bibliothèques supplémentaires (l'installeur automatique les détecte et les installe). Pour les repérer à la main :

```
cd ~/flightdisplay
grep -E '^(import|from) ' build_map_vector.py
```

Installer ce qui manque : paquets `python3-...` par apt s'ils existent, sinon `./venv/bin/pip install <nom>`. Pillow (`python3-pil`) est indispensable : l'installeur le vérifie et l'ajoute si besoin. Si l'étape affiche « Analyse de build_map_vector.py impossible », le script contient une erreur de syntaxe : corrigez-la (l'erreur est dans `~/flightdisplay-install.log`).

### 4.4 Créer config.ini

```
cd ~/flightdisplay
cp config.ini.example config.ini
cp webadmin.ini.example webadmin.ini
nano config.ini
```

Il faut renseigner au minimum la position, la clé CARTO et la taille de la carte. Toutes les options sont décrites en section 8 et modifiables ensuite depuis webadmin. Exemple minimal :

```ini
[position]
latitude = 48.8566
longitude = 2.3522
radius_km = 20

[map]
carto_key = VOTRE_CLE_API_CARTO

[display]
fullscreen = true
width = 1280
height = 720
```

`config.ini` et `webadmin.ini` contiennent des secrets : ils ne sont pas versionnés par Git (ils sont dans `.gitignore`) et doivent rester en droits restreints (`chmod 600`).

### 4.5 Construire la carte

```
cd ~/flightdisplay
./venv/bin/python -u build_map_vector.py
```

Le script télécharge le fond de carte CARTO avec la clé de `[map] carto_key`, puis produit `background.png` et `map_meta.json` dans le dossier. Il demande un accès Internet et peut durer plusieurs minutes sur un Zero. Il lit la position et le rayon dans `[position]`, la taille de l'image dans `[display] width` et `height`. Sans la clé `carto_key` dans `config.ini`, il s'arrête avec une erreur `NoOptionError`.

La carte est à refaire chaque fois que l'un de ces réglages change : latitude, longitude, rayon, largeur, hauteur, clé (depuis webadmin, onglet Carte).

### 4.6 Premier lancement manuel

```
cd ~/flightdisplay
./venv/bin/python main.py
```

Le programme choisit automatiquement le pilote vidéo KMS/DRM quand il n'y a pas de session graphique. Sortie avec la touche `Échap` (clavier connecté) ou `Ctrl+C`. Le message « premiere image apres X s » indique que l'affichage a démarré.

---

## 5. Services systemd et commande `fd`

### 5.1 Droits de l'utilisateur sur l'écran et le son

```
sudo usermod -aG video,render,input,audio flightdisplay
```

Les groupes ne sont pris en compte qu'à la prochaine connexion. Le service les reçoit de toute façon par `SupplementaryGroups`.

### 5.2 Service flightdisplay

```
sudo nano /etc/systemd/system/flightdisplay.service
```

```ini
[Unit]
Description=Flight display
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
User=flightdisplay
WorkingDirectory=/home/flightdisplay/flightdisplay
ExecStart=/home/flightdisplay/flightdisplay/venv/bin/python /home/flightdisplay/flightdisplay/main.py
SupplementaryGroups=video render input audio
Environment=PYGAME_HIDE_SUPPORT_PROMPT=1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Points importants :

- Ne définissez pas `SDL_AUDIODRIVER=dummy` : cela rendrait les alertes muettes.
- `PYGAME_HIDE_SUPPORT_PROMPT=1` masque le message d'accueil de pygame.

```
sudo systemctl daemon-reload
sudo systemctl enable --now flightdisplay
systemctl status flightdisplay --no-pager
```

### 5.3 Commande fd

```
sudo nano /usr/local/bin/fd
```

```sh
#!/bin/sh
SVC=flightdisplay
case "$1" in
  logs)    journalctl -u "$SVC" -f -n 50 --no-pager ;;
  status)  systemctl status "$SVC" --no-pager ;;
  start|stop|restart) sudo /usr/bin/systemctl "$1" "$SVC" ;;
  *) echo "usage : fd logs|status|start|stop|restart" >&2; exit 2 ;;
esac
```

```
sudo chmod 755 /usr/local/bin/fd
```

| Commande | Effet |
|---|---|
| `fd logs` | Suit le journal du programme en direct (Ctrl+C pour quitter). |
| `fd status` | État du service. |
| `fd start` / `fd stop` / `fd restart` | Démarrer, arrêter, relancer. |

`fd start|stop|restart` fonctionne sans mot de passe une fois webadmin installé, car l'installeur autorise ces commandes dans sudoers.

---

## 6. Réglages système

### 6.1 Son

Le son sort par le HDMI ou par une carte son USB. Lister les sorties détectées et tester :

```
aplay -l
speaker-test -t sine -f 880 -l 1
```

Dans Flight display, le son n'est ouvert que pendant l'alerte, puis refermé. Pour tester sans attendre un avion, utilisez le bouton « Tester le son » de webadmin (onglet Pilotage), ou cochez « Son au lancement du programme » ou « Simuler une alerte au démarrage » dans Réglages, Alerte de proximité (section 9.4).

Si le son est indisponible, `fd logs` affiche `son indisponible : ...` et l'affichage continue sans.

### 6.2 Veille d'écran

La veille est assurée par deux scripts créés par `install_webadmin.sh` : `/usr/local/bin/flight-screen` (veille et réveil) et `/usr/local/bin/flight-screen-guard` (garde).

**Pourquoi le programme est arrêté pendant la veille.** Tant que le programme d'affichage tourne, il garde la main sur la sortie vidéo : écrire dans le framebuffer ne coupe pas le signal (`dpms` reste à `On`). La veille arrête donc d'abord le service.

**Comment le signal est coupé.** La commande `setterm --blank force` n'éteint pas réellement la sortie HDMI de ce Pi (`dpms` reste `On`). Le script utilise à la place le framebuffer du noyau : écrire `4` dans `/sys/class/graphics/fb0/blank` coupe la sortie (`dpms` passe à `Off`, le moniteur s'endort), et écrire `0` la rallume. Si ce fichier n'est pas accessible, le script retombe sur `setterm`.

**Terminal de veille.** La veille bascule d'abord sur un terminal virtuel inutilisé (`tty7`), où aucun programme n'écrit : ni invite de connexion ni message ne peut ranimer la console. Le réveil revient sur `tty1`.

Contenu de `/usr/local/bin/flight-screen` (pour référence ou une installation manuelle) :

```sh
#!/bin/sh
SVC=flightdisplay
MAIN_VT=1
IDLE_VT=7
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
  off)
    systemctl stop "$SVC"
    sleep 1
    touch "$FLAG"
    chvt "$IDLE_VT"
    sleep 1
    blank
    ;;
  on)
    rm -f "$FLAG"
    unblank
    chvt "$MAIN_VT"
    systemctl start "$SVC"
    ;;
  *)
    echo "usage : flight-screen on|off" >&2
    exit 2
    ;;
esac
```

Le fichier témoin `/run/flight-screen-off` indique que la veille est demandée ; il disparaît au redémarrage du Pi.

**La garde.** `/usr/local/bin/flight-screen-guard`, lancée par le service `flight-screen-guard`, vérifie toutes les 20 secondes que la sortie vidéo est bien éteinte pendant une veille. Si l'écran s'est rallumé tout seul (fichier témoin présent, programme arrêté, `dpms` à `On`), elle le coupe de nouveau et note l'événement. Elle ne fait rien en dehors d'une veille, ni quand le programme tourne.

```sh
#!/bin/sh
SVC=flightdisplay
FLAG=/run/flight-screen-off
FB=/sys/class/graphics/fb0/blank
IDLE_VT=7
while true; do
  if [ -f "$FLAG" ] && ! systemctl is-active --quiet "$SVC"; then
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
```

Pour savoir si l'écran s'est rallumé et à quelle heure : `journalctl -t flight-screen-guard --no-pager`. Un journal vide signifie qu'aucun réveil spontané n'a eu lieu. Le journal est en mémoire : il est vidé à chaque redémarrage du Pi.

**Tests en SSH.**

```
sudo /usr/local/bin/flight-screen off
sleep 4
cat /sys/class/drm/card*-HDMI-A-*/dpms
systemctl is-active flightdisplay
sudo fgconsole
```

Résultats attendus : `Off`, `inactive`, `7`, et le moniteur éteint. Puis :

```
sudo /usr/local/bin/flight-screen on
sleep 10
cat /sys/class/drm/card*-HDMI-A-*/dpms
systemctl is-active flightdisplay
```

Résultats attendus : `On`, `active`, et la carte à l'écran.

**Si le moniteur se rallume malgré tout.** Dans l'ordre :

1. Vérifier que le correctif de l'étape 3.6 est actif (`grep -o 'vc4.force_hotplug=1' /proc/cmdline`).
2. Lire `journalctl -t flight-screen-guard` : les lignes donnent l'heure de chaque réveil. Des réveils à intervalles réguliers orientent vers le moniteur (détection automatique d'entrée ou « veille profonde » : désactiver cette option dans son menu).
3. Chercher une commande de réveil : `journalctl -t sudo --since today | grep flight-screen` (une automatisation Home Assistant ou un onglet webadmin peut avoir rallumé l'écran).
4. Vérifier que le Pi n'a pas redémarré (`uptime -s`) ni souffert d'une sous-tension (`vcgencmd get_throttled` doit renvoyer `0x0`).
5. Écarter le HDMI-CEC : `cec-ctl -d /dev/cec0` (paquet `v4l-utils`). Avec `Logical Addresses : 0`, le Pi ne participe pas au bus CEC et ne peut pas recevoir de touche de télécommande.
6. En dernier recours, essayer une mise en veille par DDC/CI (`ddcutil setvcp d6 5` pour éteindre, `ddcutil setvcp d6 1` pour allumer) en modifiant le script.

**Suivi de l'état de la sortie vidéo.**

```
cat /sys/class/drm/card*-HDMI-A-*/{enabled,status,dpms}
```

### 6.3 Ménager la carte SD

Le logiciel écrit très peu sur la carte : `cache/details.json` au plus une fois par minute, une photo par nouvel avion (effacée après 3 jours), et les fichiers de réglages quand vous les modifiez. Les vrais risques viennent du système :

- **Le swap sur la carte** : le Pi Zero a 512 Mo de RAM, et le swap sur carte SD use celle-ci rapidement. Vérifier avec `swapon --show` ; désactiver le swap fichier ou le remplacer par du zram.
- **Le journal persistant** : Raspberry Pi OS garde le journal en mémoire par défaut, ce qui ménage la carte. Ne créez pas `/var/log/journal` sauf besoin ponctuel de diagnostic. Pour forcer le journal en mémoire : `Storage=volatile` dans `/etc/systemd/journald.conf`, puis `sudo systemctl restart systemd-journald`.
- **Les coupures sans arrêt propre** : elles provoquent des corruptions du système de fichiers. Utilisez le bouton « Éteindre » de webadmin ou `sudo poweroff`, et attendez l'arrêt de la LED avant de débrancher.
- **Les options de montage** : `noatime` doit figurer dans `mount | grep ' / '`.

Mesurer les écritures depuis le démarrage :

```
awk '$3=="mmcblk0"{printf "%.1f Mo écrits depuis le démarrage\n", $10*512/1048576}' /proc/diskstats
```

### 6.4 Wi-Fi qui se coupe (optionnel)

Si la connexion Wi-Fi décroche, désactiver l'économie d'énergie de la carte Wi-Fi :

```
nmcli connection show
sudo nmcli connection modify "NOM_DE_LA_CONNEXION" 802-11-wireless.powersave 2
sudo nmcli connection up "NOM_DE_LA_CONNEXION"
```

---

## 7. Installer webadmin

L'installeur automatique (section 0) exécute déjà cette étape. Pour une installation manuelle :

### 7.1 Installation

```
cd ~/flightdisplay
sudo bash install_webadmin.sh
```

L'installeur détecte l'utilisateur qui l'a lancé avec sudo. Il demande un mot de passe pour l'interface (sauf si `webadmin.ini` en contient déjà un), puis :

1. installe `kbd` et `python3-paho-mqtt` s'ils manquent ;
2. crée `/usr/local/bin/flight-screen` (veille et réveil de l'écran, section 6.2) ;
3. crée `/usr/local/bin/flight-screen-guard` et son service `flight-screen-guard`, qu'il active et redémarre ;
4. ajoute `/etc/sudoers.d/flightadmin`, qui autorise uniquement, sans mot de passe : démarrer, arrêter, relancer le service `flightdisplay`, redémarrer, éteindre, et `flight-screen on|off` ;
5. renseigne dans `webadmin.ini` l'interpréteur Python du venv (utilisé pour construire la carte) et protège le fichier (droits 600) ;
6. crée, active et redémarre le service `flightadmin` (groupe `systemd-journal` pour lire les logs).

Le script est relançable à volonté : il réécrit les deux scripts de veille (toute modification manuelle est perdue) et redémarre les services webadmin et garde.

Variables d'environnement acceptées par `install_webadmin.sh` :

| Variable | Défaut | Rôle |
|---|---|---|
| `SERVICE` | `flightdisplay` | Nom du service d'affichage. |
| `MAIN_VT` | 1 | Terminal virtuel principal (retour au réveil). |
| `IDLE_VT` | 7 | Terminal virtuel inutilisé pour la veille. |

Exemple : `sudo IDLE_VT=8 bash install_webadmin.sh`.

### 7.2 Premier accès

Ouvrir `http://flightradarpi.local:8080`. Identifiant : `admin`, mot de passe : celui saisi à l'installation (modifiable dans Réglages, Serveur web). Sur iPhone, « Partager » puis « Sur l'écran d'accueil » donne une icône d'application.

```
sudo systemctl status flightadmin
journalctl -u flightadmin -n 50 --no-pager
```

### 7.3 Redémarrer ou mettre à jour webadmin

- Depuis l'interface : un changement de port ou d'adresse d'écoute propose « Enregistrer et appliquer », qui redémarre webadmin et rouvre la page (sur le nouveau port si besoin).
- En ligne de commande, après avoir remplacé `webadmin.py` ou `webadmin_mqtt.py` : `sudo systemctl restart flightadmin`.

---

## 8. Référence de `config.ini`

Les options manquantes prennent la valeur par défaut indiquée. Chacune se règle dans webadmin, onglet Réglages, dans la catégorie indiquée par le titre de section. Les changements sont lus par le programme au démarrage : il faut le relancer (« Enregistrer et appliquer », ou `fd restart`). Les réglages marqués « carte » demandent en plus de reconstruire la carte. Les largeurs (panneau, liste) sont exprimées pour un écran de 1080 pixels de haut et s'adaptent à la hauteur réelle de la carte. Si vous modifiez le fichier à la main, mettez les commentaires sur leur propre ligne, jamais à la suite d'une valeur.

Le modèle `config.ini.example` contient toutes les sections avec des valeurs d'exemple.

### 8.1 `[position]` — catégorie « Carte et position »

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `latitude` | obligatoire | -90 à 90 | Latitude de la maison, en degrés décimaux (carte). |
| `longitude` | obligatoire | -180 à 180 | Longitude de la maison (carte). |
| `radius_km` | obligatoire | 1 à 200 | Rayon couvert par la carte (km) (carte). |

Modifier l'une de ces trois valeurs oblige à reconstruire la carte (webadmin l'indique). Le programme affiche un avertissement au démarrage si la carte a été construite pour d'autres coordonnées.

### 8.2 `[map]` — catégorie « Carte et position », groupe « Fond de carte »

| Option | Défaut | Description |
|---|---|---|
| `carto_key` | obligatoire pour construire la carte | Clé API CARTO utilisée par `build_map_vector.py` pour télécharger le fond de carte vectoriel. Dans webadmin, le champ est masqué comme un mot de passe (carte). |

La clé n'est lue que par `build_map_vector.py`, pas par `main.py`. Elle est stockée en clair dans `config.ini` : gardez le fichier en droits 600 et ne le publiez jamais.

### 8.3 `[api]` — catégorie « Flightradar24 »

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `poll_seconds` | 30 | 5 à 600 | Intervalle entre deux requêtes de la liste des avions. Trop bas, Flightradar24 répond « 429 ». |
| `details_pause_seconds` | 4 | 0 à 60 | Pause entre deux requêtes de détails d'avion (modèle, compagnie, photo). |
| `stale_seconds` | 30 | 5 à 600 | Au-delà de ce délai sans nouvelle position, l'avion est retiré. Sert aussi de plafond à l'extrapolation de position. |

Protection automatique : après une erreur 429, l'intervalle est multiplié par 1,5 (maximum 120 s), les requêtes sont suspendues 60 s, puis l'intervalle redescend peu à peu vers `poll_seconds`. Pour les détails, une erreur 429 suspend les requêtes 120 s et la demande est rejouée. Une autre erreur réseau déclenche un délai croissant (maximum 5 minutes).

### 8.4 `[display]` — catégorie « Affichage »

| Option | Défaut | Valeurs | Description |
|---|---|---|---|
| `fullscreen` | false | true / false | Plein écran. À mettre à `true` sur le Pi. Sinon fenêtre redimensionnable (utile sur PC). |
| `fps` | 10 | 1 à 60 | Images par seconde. Une valeur basse ménage le Pi Zero : c'est le levier principal pour réduire l'utilisation du processeur. |
| `altitude_unit` | ft | `ft`, `m` | Unité d'altitude affichée. |
| `speed_unit` | kmh | `kmh`, `kt` | Unité de vitesse affichée. |
| `max_altitude_ft` | 0 | 0 à 100000 | Les avions plus hauts ne sont ni suivis ni affichés (0 = pas de limite). Leur nombre apparaît dans la ligne d'état. S'applique aussi à l'alerte. |
| `icon_scale` | 1.25 | 0.3 à 5 | Taille des icônes d'avion. |
| `width` | obligatoire | 320 à 7680 | Largeur de la carte en pixels (carte). |
| `height` | obligatoire | 240 à 4320 | Hauteur de la carte en pixels (carte). |

`width` et `height` sont lues par `build_map_vector.py`, qui s'en sert pour fixer la taille de l'image de fond. `main.py` ne les lit pas : il prend la taille réelle dans `map_meta.json`, produit à la construction. Changer ces valeurs n'a donc d'effet qu'après avoir reconstruit la carte.

Toute l'interface est dessinée à la résolution de la carte. Sous Windows et sur le Pi, la fenêtre ou l'écran affiche cette image mise à l'échelle en conservant les proportions : redimensionner la fenêtre ne change que le zoom. Pour une autre résolution de travail, changez `width` et `height`, puis reconstruisez la carte. Les tailles de texte et d'icônes s'adaptent à la hauteur de la carte. Sur Pi Zero, 1280×720 réduit nettement le nombre de pixels dessinés par rapport à 1920×1080, donc la charge du processeur.

### 8.5 `[panel]` — catégorie « Panneau photo »

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `width` | 480 | 200 à 1200 | Largeur du panneau (px, base 1080p). |
| `rotate_seconds` | 12 | 3 à 120 | Durée d'affichage de chaque avion quand plusieurs sont éligibles. |

### 8.6 `[ground]` — catégorie « Avions au sol »

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `show_list` | true | true / false | Affiche la liste des avions au sol en bas à droite. |
| `max_rows` | 8 | 1 à 30 | Nombre maximum de lignes de la liste. |
| `width` | 780 | 300 à 1800 | Largeur de la liste (px, base 1080p). |
| `airport_iata` | vide | code IATA | Aéroport de référence (ex. `BOD`). Affiche « de ... » pour les arrivées et « vers ... » pour les départs, et limite la détection d'atterrissage aux vols qui arrivent à cet aéroport. |
| `min_speed_kt` | 0 | 0 à 200 | Vitesse minimale pour apparaître dans la liste. Les avions plus lents ne déclenchent pas non plus de requêtes de détails. |
| `landed_alt_ft` | 2000 | 0 à 10000 | Un avion qui disparaît des données sous cette altitude est considéré comme posé et passe dans la liste au sol. |
| `landed_keep_minutes` | 10 | 0 à 240 | Durée pendant laquelle un avion posé reste affiché dans la liste. |

### 8.7 `[alert]` — catégorie « Alerte de proximité »

Les options sont regroupées dans webadmin en cinq groupes : Zone, Son, Teinte rouge, Plage d'altitude, Au démarrage.

| Option | Défaut | Plage | Groupe | Description |
|---|---|---|---|---|
| `radius_km` | 5 | 0 à 50 | Zone | Rayon du cercle d'alerte. `0` désactive toute l'alerte (teinte, son de proximité, simulation). |
| `sound` | true | true / false | Son | Interrupteur général du son. À `false`, aucun son ni périphérique audio n'est utilisé, y compris au démarrage. |
| `volume` | 0.6 | 0 à 1 | Son | Volume de départ. Le curseur de Pilotage le remplace en direct. |
| `pulse_seconds` | 3 | 0.5 à 30 | Teinte rouge | Durée d'un cycle de clignotement de la teinte rouge. |
| `alpha_min` | 10 | 0 à 255 | Teinte rouge | Intensité minimale du rouge. |
| `alpha_max` | 60 | 0 à 255 | Teinte rouge | Intensité maximale du rouge. |
| `min_altitude_ft` | 0 | 0 à 100000 | Plage d'altitude | Altitude minimale (pieds) pour déclencher l'alerte. |
| `max_altitude_ft` | 0 | 0 à 100000 | Plage d'altitude | Altitude maximale pour l'alerte (0 = pas de limite haute). |
| `sound_on_start` | false | true / false | Au démarrage | Joue le carillon une fois au lancement du programme, indépendamment de tous les autres réglages. |
| `simulate_on_start` | false | true / false | Au démarrage | Simule une entrée dans la zone au lancement : teinte rouge et carillon pendant `simulate_seconds`, même si `sound_on_start` est décoché. |
| `simulate_seconds` | 3 | 1 à 30 | Au démarrage | Durée de cette simulation. |

Combinaisons au démarrage :

| `sound_on_start` | `simulate_on_start` | Au lancement du programme |
|---|---|---|
| false | false | Rien (un avion déjà présent dans la zone déclenche tout de même une vraie alerte). |
| true | false | Un carillon. |
| false | true | Carillon et teinte rouge pendant la durée choisie. |
| true | true | Carillon et teinte rouge (un seul carillon). |

La coupure du son (icône de haut-parleur barré, interrupteur de Pilotage, touche `M`) et l'interrupteur général `sound` restent prioritaires sur ces deux options.

### 8.8 Autres sections

Toute autre clé ou section présente dans `config.ini` apparaît dans webadmin sous « Autres réglages », en champs texte, et reste modifiable.

### 8.9 Exemple complet

```ini
[position]
latitude = 48.8566
longitude = 2.3522
radius_km = 20

[map]
carto_key = VOTRE_CLE_API_CARTO

[api]
poll_seconds = 30
details_pause_seconds = 4
stale_seconds = 30

[display]
fullscreen = true
fps = 10
altitude_unit = ft
speed_unit = kmh
max_altitude_ft = 15000
icon_scale = 1.25
width = 1280
height = 720

[panel]
width = 480
rotate_seconds = 12

[ground]
show_list = true
max_rows = 8
width = 780
airport_iata = CDG
min_speed_kt = 0
landed_alt_ft = 2000
landed_keep_minutes = 10

[alert]
radius_km = 5
sound = true
volume = 0.6
pulse_seconds = 3
alpha_min = 10
alpha_max = 60
min_altitude_ft = 0
max_altitude_ft = 10000
sound_on_start = false
simulate_on_start = false
simulate_seconds = 3
```

---

## 9. Fonctionnement de l'affichage

### 9.1 Carte et avions

- La carte est une image de fond (`background.png`) centrée sur la maison, accompagnée de `map_meta.json` (taille en pixels et échelle en mètres par pixel). Des cercles de 5, 10, 15 et 20 km sont tracés dans la limite du rayon de la carte.
- Chaque avion en vol est dessiné avec une icône orientée selon son cap. Huit formes existent : `narrow` (monocouloir), `wide` (gros porteur), `quad` (quadriréacteur), `regional`, `turbo` (turbopropulseur), `light` (avion léger), `bizjet` et `heli`.
- Les positions sont extrapolées entre deux mises à jour (vitesse et cap) puis lissées, pour un mouvement fluide. Une traînée des dernières positions est tracée derrière chaque avion.
- Chaque avion a une étiquette : modèle, compagnie, trajet (origine → destination) et altitude · vitesse. Tant que les détails ne sont pas arrivés, elle affiche l'indicatif et le code du type. Le trajet est omis si l'origine et la destination sont inconnues (pas de plan de vol déclaré). Si une seule est connue, l'autre apparaît sous la forme `?`.
- Les étiquettes sont placées pour éviter de se recouvrir et de sortir de l'écran.
- La ligne d'état en bas à gauche indique le nombre d'avions en vol, au-dessus de la limite d'altitude, au sol, les erreurs réseau et la mention « données anciennes » si les mises à jour tardent. Elle contient aussi les crédits (OpenStreetMap, CARTO, Flightradar24) : l'attribution doit rester visible.

### 9.2 Panneau photo

- Un panneau avec la photo, le modèle, l'immatriculation, la compagnie, le trajet, l'altitude et la vitesse s'affiche pour un avion à la fois, en alternance toutes les `rotate_seconds` entre les avions qui ont une photo.
- L'avion présenté est surligné en rouge sur la carte.
- Le panneau se place dans le coin de l'écran qui gêne le moins les avions affichés.
- Les photos et détails viennent de Flightradar24 (crédit JetPhotos). Si une photo manque ou ne se charge pas, l'avion est ignoré en mode normal.

### 9.3 Avions au sol

La liste en bas à droite (voir `[ground]`) affiche indicatif, compagnie, modèle et trajet, triés par vitesse décroissante. Un avion qui disparaît des données sous `landed_alt_ft` est conservé `landed_keep_minutes` comme « posé ».

### 9.4 Alerte de proximité

Quand un avion en vol entre dans le cercle d'alerte (`[alert] radius_km`) et respecte la plage d'altitude :

- un carillon de trois notes retentit (généré par le programme, aucun fichier son) ;
- l'intérieur du cercle se teinte en rouge transparent avec un clignotement lent, et le cercle est entouré d'un cadre rouge, tant qu'un avion est dedans ;
- le panneau photo ne montre que les avions présents dans le cercle (en alternance s'il y en a plusieurs), avec une ligne rouge « ALERTE · à X.X km de la maison ». Si la photo manque, le panneau s'affiche avec un cadre « Photo indisponible » ;
- dès que le cercle est vide, l'affichage revient au fonctionnement normal.

La distance est mesurée au sol, avec une marge de sortie de 10 % du rayon pour éviter les alertes à répétition. Un avion déjà en alerte garde une marge de 10 % sur les bornes d'altitude. Le son n'est joué qu'à l'entrée d'un avion, jamais deux fois en parallèle.

**Au lancement du programme** : un avion déjà présent dans la zone déclenche une vraie alerte, comme à tout autre moment. Pour tester le son et la teinte sans avion, deux options indépendantes existent (section 8.7) : « Son au lancement du programme » (un carillon) et « Simuler une alerte au démarrage » (teinte rouge et carillon). Il n'y a jamais deux carillons à la fois.

### 9.5 Contrôle du son pendant l'exécution

Le son se coupe et se règle sans relancer le programme. webadmin écrit l'état dans `cache/runtime.json`, relu par le programme toutes les demi-secondes.

| Clé du fichier | Rôle |
|---|---|
| `muted` | `true` coupe le son. Une icône de haut-parleur barré s'affiche alors en bas à gauche. |
| `volume` | Volume de 0 à 1, prioritaire sur `config.ini`. |
| `test_seq` | Compteur incrémenté pour demander un son de test. Le programme mémorise sa valeur au chargement : seules les demandes faites pendant son exécution jouent un son. |

La touche `M` du clavier connecté au Pi coupe ou réactive aussi le son. L'état coupé et le volume choisi sont conservés après un redémarrage.

### 9.6 Raccourcis clavier

| Touche | Action |
|---|---|
| `Échap` | Quitter le programme. |
| `M` | Couper ou réactiver le son des alertes. |

### 9.7 Cache et fichiers générés

| Fichier | Contenu | Durée de vie |
|---|---|---|
| `background.png`, `map_meta.json` | Carte et ses dimensions, produites par `build_map_vector.py`. | Jusqu'à la prochaine reconstruction. |
| `cache/details.json` | Détails d'avions (modèle, compagnie, trajet). | 3 heures. |
| `cache/*.jpg` | Photos téléchargées. | Nettoyées après 3 jours au démarrage. |
| `cache/runtime.json` | État du son (coupé, volume, test). | Persistant. |

### 9.8 Types d'avion inconnus

Quand un type d'avion n'a pas d'icône dédiée, une forme monocouloir est utilisée et le journal indique `type inconnu (icone par defaut) : XXXX`. Pour lui associer la bonne forme, utilisez webadmin, Réglages, « Types d'avion » : les types détectés dans les logs sont proposés, avec un champ pour ajouter une règle et l'éditeur du fichier `types_extra.txt`. Le fichier est vérifié à l'enregistrement et pris en compte au prochain démarrage du programme.

Format du fichier (une règle par ligne, `#` pour les commentaires) :

```
WT9 light
B350 turbo   # exemple
```

Catégories valides : `narrow`, `wide`, `quad`, `regional`, `turbo`, `light`, `bizjet`, `heli`.

### 9.9 Variables d'environnement reconnues

| Variable | Effet |
|---|---|
| `PYGAME_HIDE_SUPPORT_PROMPT=1` | Masque le message d'accueil de pygame. |
| `SDL_VIDEODRIVER`, `SDL_RENDER_DRIVER` | Définis automatiquement (`kmsdrm`, `opengles2`) sur Linux sans bureau, sauf si déjà présents. |
| `SDL_AUDIODRIVER` | Défini à `dummy` seulement si `[alert] sound = false`. Ne pas le définir autrement. |
| `WEBADMIN_INI` | Chemin alternatif pour `webadmin.ini`. |

---

## 10. Référence de webadmin

### 10.1 Les onglets

**Pilotage** (page d'accueil)

- Sept tuiles de supervision, alignées sur une seule ligne sur ordinateur et sur deux colonnes sur téléphone (la dernière occupe alors toute la largeur) :
  - Programme : actif ou arrêté.
  - Écran : allumé ou en veille.
  - Température du Pi.
  - Utilisation CPU : pourcentage d'occupation du processeur, mesuré toutes les 2 secondes (orange au-dessus de 85 %, rouge au-dessus de 95 %), avec en petit la charge moyenne du système sur 1 et 5 minutes. La charge moyenne n'est pas un pourcentage : sur le Pi Zero, qui n'a qu'un seul cœur, 1.00 correspond déjà à un processeur saturé.
  - Mémoire : pourcentage utilisé, avec les Mo.
  - Allumé depuis : durée de fonctionnement et nom d'hôte.
  - MQTT : connecté (vert), déconnecté ou refusé (rouge), désactivé (neutre), avec l'adresse du serveur.
  Rafraîchies toutes les 4 secondes. L'en-tête de la page n'affiche plus que les pastilles « son coupé » et « carte en construction ».
- Commandes à bascule, comme dans Réglages d'iOS ou Home Assistant :
  - Programme d'affichage : démarre ou arrête le service (si l'écran est en veille, l'interrupteur rallume l'écran).
  - Écran : veille et réveil (la veille arrête aussi le programme, voir 6.2).
  - Son des alertes : coupe ou réactive le son (désactivé et grisé si `sound = false` dans `config.ini`).
- Curseur de volume (0 à 100 %), appliqué en direct à la prochaine alerte.
- Boutons « Tester le son » (désactivé tant que le son est coupé) et « Relancer le programme ».
- Alimentation : redémarrer ou éteindre le Pi, avec confirmation. Après une extinction, il faut débrancher puis rebrancher l'alimentation.

**Réglages**

Sur ordinateur, un menu à gauche liste les catégories ; sur téléphone, il devient une barre de boutons défilante en haut. Les catégories sont :

| Menu | Catégorie | Fichier | Contenu |
|---|---|---|---|
| Programme | Carte et position | config.ini | Latitude, longitude, rayon de la carte, clé API CARTO (masquée). |
| | Flightradar24 | config.ini | Fréquence des requêtes, validité des positions. |
| | Affichage | config.ini | Plein écran, images par seconde, unités, filtre d'altitude, taille des icônes, taille de la carte (largeur et hauteur). |
| | Panneau photo | config.ini | Largeur, rotation. |
| | Avions au sol | config.ini | Liste, filtres, atterrissage. |
| | Alerte de proximité | config.ini | Zone, son et volume, teinte rouge, plage d'altitude, démarrage (son au lancement, simulation). |
| | Types d'avion | types_extra.txt | Éditeur des règles, types inconnus détectés. |
| | Autres réglages | config.ini | Toute clé hors schéma (affichée seulement s'il y en a). |
| Webadmin | Serveur web | webadmin.ini | Adresse, port, identifiant, mot de passe. L'avertissement « aucun mot de passe » s'affiche ici (et seulement ici) tant qu'aucun mot de passe n'est défini. |
| | Application et système | webadmin.ini | Dossier, fichiers, service, Python de la carte, sudo, commandes, script et témoin de veille, arrêt de l'affichage pendant la carte. |
| Intégrations | MQTT / Home Assistant | webadmin.ini | Connexion, sujets et découverte, avec état et bouton « Reconnecter ». |

Commandes de saisie : interrupteurs à bascule pour les valeurs oui/non, boutons segmentés pour les choix à deux ou trois valeurs, curseurs pour le volume et l'intensité du rouge, champs texte avec limites pour le reste. Les mots de passe et la clé CARTO sont masqués : le champ reste vide pour conserver la valeur actuelle, saisir une valeur la remplace, le bouton « Effacer » la supprime.

Enregistrement :

- Les champs modifiés sont entourés en jaune et un point signale les catégories modifiées. Une barre en bas indique le nombre de modifications et ce qu'il faudra appliquer.
- « Enregistrer » écrit les fichiers et affiche ce qu'il reste à appliquer, avec des boutons pour le faire.
- « Enregistrer et appliquer » fait aussi les relances nécessaires.
- Les réglages de carte (position, rayon, taille, clé) déclenchent un bandeau qui propose de reconstruire la carte.
- Seules les lignes modifiées sont réécrites : les commentaires des fichiers sont conservés. Une sauvegarde `.bak` est créée à chaque enregistrement. Pour `webadmin.ini`, un bouton « Revenir à la version précédente » en bas des catégories Webadmin et Intégrations échange le fichier avec elle (un second clic annule l'opération). Il n'y a pas de bouton équivalent pour `config.ini` dans l'interface : `config.ini.bak` reste disponible en ligne de commande.
- Les valeurs hors limites ou mal formées sont refusées avec un message, sans rien écrire.

Quand une modification est prise en compte :

| Réglages | Prise en compte |
|---|---|
| `config.ini` (toutes les catégories du menu Programme) | Au prochain lancement du programme (relance proposée). La carte doit en plus être reconstruite pour les réglages de carte. |
| Types d'avion | Au prochain lancement du programme. |
| Serveur web : adresse et port | Au redémarrage de webadmin (proposé : la page se rouvre toute seule, sur le nouveau port si besoin). |
| Serveur web : identifiant et mot de passe | Immédiate (le navigateur redemande les identifiants). |
| Application et système | Immédiate. |
| MQTT | Immédiate : webadmin se reconnecte au serveur. |

**Carte**

- Bouton « Reconstruire la carte » : lance `build_map_vector.py` avec les réglages actuels, affiche sa sortie en direct, et propose « Annuler ».
- Interrupteur « Arrêter l'affichage pendant la construction » : libère la mémoire du Pi Zero pendant le calcul. À la fin, l'affichage est relancé pour charger la nouvelle carte (sauf si l'écran est en veille). Si la construction échoue, l'affichage reprend avec l'ancienne carte.
- Une seule construction à la fois.

**Logs**

- Journal du service d'affichage : 100, 300 ou 1000 lignes, filtre texte, actualisation automatique (interrupteur) toutes les 3 secondes. Les erreurs sont en rouge, les avertissements en jaune.

### 10.2 Réglages de webadmin.ini

Toutes ces options se modifient dans Réglages, catégories « Serveur web », « Application et système » et « MQTT / Home Assistant ». Le fichier peut aussi s'éditer à la main (puis `sudo systemctl restart flightadmin`). Le modèle est `webadmin.ini.example`.

```ini
[server]
host = 0.0.0.0
port = 8080
user = admin
password =

[app]
dir =
config = config.ini
runtime = cache/runtime.json
service = flightdisplay
python =
build_script = build_map_vector.py
sudo = sudo -n
systemctl =
journalctl =

[screen]
helper = /usr/local/bin/flight-screen
flag = /run/flight-screen-off

[build]
stop_display = true

[mqtt]
enabled = false
host =
port = 1883
user =
password =
tls = false
base_topic = flightdisplay
discovery_prefix = homeassistant
device_name = Flight display
interval = 30
```

| Section | Option | Défaut | Description |
|---|---|---|---|
| `[server]` | `host` | `0.0.0.0` | Adresse d'écoute. `127.0.0.1` limite l'accès au Pi lui-même. |
| | `port` | 8080 | Port HTTP (1 à 65535). |
| | `user` | `admin` | Identifiant de connexion. |
| | `password` | vide | Mot de passe (authentification HTTP Basic). Vide : pas de protection, un avertissement s'affiche dans Réglages, Serveur web. |
| `[app]` | `dir` | dossier de `webadmin.py` | Dossier de l'application (où se trouvent `config.ini`, `cache/`, le script de carte). |
| | `config` | `config.ini` | Nom du fichier de réglages. |
| | `runtime` | `cache/runtime.json` | Fichier d'état du son partagé avec le programme. |
| | `service` | `flightdisplay` | Service systemd d'affichage. |
| | `python` | celui de webadmin | Interpréteur utilisé pour `build_map_vector.py` (rempli par l'installeur avec celui du venv). |
| | `build_script` | `build_map_vector.py` | Script de construction de la carte. |
| | `sudo` | `sudo -n` | Préfixe des commandes privilégiées (sans mot de passe). |
| | `systemctl`, `journalctl` | détectés | Chemins des commandes. `systemctl` doit correspondre à celui du fichier sudoers (`/usr/bin/systemctl`). |
| `[screen]` | `helper` | `/usr/local/bin/flight-screen` | Script de veille et de réveil. |
| | `flag` | `/run/flight-screen-off` | Fichier témoin de la veille (supprimé au redémarrage du Pi). |
| `[build]` | `stop_display` | true | Valeur par défaut de l'interrupteur de l'onglet Carte. |
| `[mqtt]` | | | Voir la section 11. |

Ne sont modifiables que par la ligne de commande : les services systemd, le fichier sudoers, le contenu des scripts de veille et de garde (numéros de terminaux virtuels) et les variables d'environnement.

### 10.3 API HTTP

Toutes les routes exigent l'authentification si un mot de passe est défini. Les requêtes `POST` exigent en plus l'en-tête `X-Admin: 1` (protection contre les requêtes déclenchées depuis une autre page web) et un corps JSON. Les mots de passe et la clé CARTO ne sont jamais renvoyés par l'API : seul leur état (défini ou non) l'est.

| Route | Méthode | Corps | Rôle |
|---|---|---|---|
| `/` | GET | | Interface web. |
| `/api/status` | GET | | État : service, écran, utilisation CPU en pourcentage (`cpu`), charge moyenne (`load`), température, mémoire, durée de fonctionnement, son (coupé, volume, activé), construction en cours, MQTT (`mqtt`, `mqtt_host`). |
| `/api/settings` | GET | | Catégories, groupes, paramètres, valeurs et sauvegardes disponibles. |
| `/api/settings` | POST | `{"changes": {"config:alert.volume": "0.5", "web:mqtt.host": "10.0.0.2"}}` | Enregistre les valeurs (clé = `fichier:section.option`, fichier `config` ou `web`). Renvoie ce qu'il faut appliquer. |
| `/api/settings/restore` | POST | `{"file": "config"}` | Échange le fichier (`config` ou `web`) avec sa sauvegarde `.bak`. |
| `/api/types` | GET / POST | `{"text": "WT9 light\n"}` | Lit et écrit `types_extra.txt` (GET : aussi les types inconnus des logs). |
| `/api/logs?lines=N` | GET | | Journal du service (10 à 2000 lignes). |
| `/api/sound` | POST | `{"muted": true, "volume": 0.5, "test": true}` | Couper, régler le volume, jouer un test (chaque clé est optionnelle). |
| `/api/service` | POST | `{"action": "start\|stop\|restart"}` | Pilote le service d'affichage. |
| `/api/screen` | POST | `{"action": "on\|off"}` | Veille et réveil de l'écran. |
| `/api/power` | POST | `{"action": "reboot\|poweroff"}` | Redémarre ou éteint le Pi. |
| `/api/build` | GET / POST | `{"stop_display": true}` | État et sortie de la construction / lancement. |
| `/api/build/cancel` | POST | `{}` | Annule la construction. |
| `/api/mqtt/reconnect` | POST | `{}` | Reconnecte MQTT et republie la découverte. |
| `/api/webadmin/restart` | POST | `{}` | Redémarre webadmin. |

Exemple avec `curl` (mot de passe défini) :

```
curl -u admin:MOTDEPASSE -H "X-Admin: 1" -H "Content-Type: application/json" \
  -d '{"muted": true}' http://flightradarpi.local:8080/api/sound
```

### 10.4 Sécurité

- L'authentification HTTP Basic envoie le mot de passe en clair sur le réseau local. À réserver à un réseau domestique de confiance, jamais exposé sur Internet.
- Sans mot de passe, tout appareil du réseau peut éteindre le Pi : l'avertissement s'affiche dans Réglages, Serveur web.
- webadmin tourne avec votre utilisateur, pas en root. Seules les commandes listées dans `/etc/sudoers.d/flightadmin` passent par sudo.
- `config.ini` (clé CARTO) et `webadmin.ini` (mots de passe) restent en droits 600 (installeur et enregistrements depuis l'interface).
- Il n'y a pas de blocage après des erreurs de mot de passe, mais chaque essai raté est ralenti d'une seconde.

---

## 11. MQTT et Home Assistant

### 11.1 Mise en place

1. Le paquet `python3-paho-mqtt` est installé à l'étape 3.5 (ou par l'installeur automatique).
2. Dans webadmin : Réglages, Intégrations, « MQTT / Home Assistant ». Activer MQTT, renseigner le serveur, le port, l'identifiant et le mot de passe, puis enregistrer. La connexion est immédiate. (L'installeur automatique peut aussi renseigner ces valeurs au moment de l'installation.)
3. L'état de la connexion (connecté, déconnecté, refusé, paho manquant, serveur manquant) s'affiche dans une tuile de la page Pilotage et en haut de la catégorie MQTT. Le bouton « Reconnecter / republier » relance la connexion et la découverte.

Les mêmes réglages existent dans `webadmin.ini`, section `[mqtt]`.

### 11.2 Options

| Option | Défaut | Description |
|---|---|---|
| `enabled` | false | Active le pont MQTT. |
| `host` | vide | Adresse du serveur MQTT (obligatoire). |
| `port` | 1883 | Port du serveur. |
| `user`, `password` | vides | Identifiants du serveur. |
| `tls` | false | Chiffrement TLS, certificat vérifié avec les autorités du système. |
| `base_topic` | `flightdisplay` | Préfixe des sujets MQTT. |
| `discovery_prefix` | `homeassistant` | Préfixe de la découverte automatique de Home Assistant. |
| `device_name` | `Flight display` | Nom de l'appareil dans Home Assistant. |
| `interval` | 30 | Période de republication complète des états (minimum 5 s). Les changements sont publiés dans les 5 secondes. |

### 11.3 Entités créées

| Entité | Type | Sujets (état / commande) | Description |
|---|---|---|---|
| Écran | interrupteur | `base/screen/state`, `base/screen/set` | ON rallume, OFF met en veille (et arrête le programme). |
| Son des alertes | interrupteur | `base/sound/state`, `base/sound/set` | ON si le son n'est ni coupé ni désactivé dans `config.ini`. OFF coupe le son. |
| Volume des alertes | nombre 0-100 % (pas de 5) | `base/volume/state`, `base/volume/set` | Règle le volume en direct. |
| Température | capteur °C | `base/temperature/state` | Température du Pi, arrondie à 0,5 °C. |

Autres sujets : `base/availability` (`online` / `offline`, avec testament pour que les entités passent en « indisponible » si webadmin s'arrête) et `homeassistant/status` (écouté : à chaque redémarrage de Home Assistant, la découverte est republiée). Les états et la découverte sont conservés (retain) par le serveur. Les commandes ne doivent jamais être publiées avec le drapeau « retain » : un message conservé serait renvoyé à chaque reconnexion.

L'appareil est identifié par `flightdisplay_<nom d'hôte>`. Les entités apparaissent sous Paramètres, Appareils, MQTT. Exemple d'automatisation pour éteindre l'écran à 23 h (adaptez le nom de l'entité) :

```yaml
automation:
  - alias: Flight display - écran éteint la nuit
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.flight_display_ecran
```

Le volume et le son restent réglables pendant la veille de l'écran : les valeurs s'appliqueront au réveil.

---

## 12. Maintenance

### 12.1 Mettre à jour

Avec une installation par Git ou par l'installeur automatique :

```
cd ~/flightdisplay
git pull
fd restart
sudo systemctl restart flightadmin
```

Vos réglages (`config.ini`, `webadmin.ini`) ne sont pas versionnés et restent intacts. Si la mise à jour modifie les scripts de veille, relancez `sudo bash install_webadmin.sh` pour les réinstaller. Relancer l'installeur (section 0.6) met aussi à jour les paquets et les services en conservant la configuration.

Avec une installation par copie de fichiers : recopier `main.py` (et `webadmin.py`, `webadmin_mqtt.py`) depuis l'ordinateur, puis `fd restart` et `sudo systemctl restart flightadmin`.

### 12.2 Sauvegarde

À conserver : `config.ini` (avec la clé CARTO), `webadmin.ini`, `types_extra.txt`, et `cache/runtime.json`. `background.png` et `map_meta.json` se régénèrent depuis `config.ini`.

```
cd ~/flightdisplay
tar czf ~/flightdisplay-backup.tgz config.ini webadmin.ini types_extra.txt cache/runtime.json
```

Cette sauvegarde contient des secrets : ne la partagez pas.

### 12.3 Mises à jour du système

```
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 12.4 Consulter les logs

| Besoin | Commande |
|---|---|
| Programme d'affichage en direct | `fd logs` (ou onglet Logs de webadmin) |
| Programme d'affichage, dernières lignes | `journalctl -u flightdisplay -n 100 --no-pager` |
| webadmin | `journalctl -u flightadmin -n 100 --no-pager` |
| Garde de veille d'écran | `journalctl -t flight-screen-guard --no-pager` |
| Installeur automatique | `less ~/flightdisplay-install.log` |
| Noyau | `journalctl -k -n 100 --no-pager` |

---

## 13. Dépannage

| Symptôme | Cause probable et solution |
|---|---|
| L'installeur s'arrête à une étape | Lire le message affiché et `~/flightdisplay-install.log`. Corriger (connexion Internet, espace disque), puis relancer la même commande. |
| « Ne lancez pas ce script avec sudo » | Relancer avec votre utilisateur normal, sans `sudo` : l'installeur demande sudo lui-même. |
| L'installeur ne propose pas de saisie | Il lit le clavier du terminal : lancez-le dans une session SSH interactive (pas depuis un script non interactif). |
| Écran noir au démarrage du service | Vérifier `fd logs`. S'assurer que l'utilisateur est dans les groupes `video` et `render` (service : `SupplementaryGroups`), et que `background.png` existe. |
| `pygame.error: EGL not initialized` (le service redémarre en boucle) | Bibliothèques EGL absentes : `sudo apt install -y libegl1 libegl-mesa0 libgles2`, puis `sudo systemctl restart flightdisplay`. Si l'erreur persiste, ajouter `libegl-dev`. Vérifier aussi que `/dev/dri/card0` existe. |
| « premiere image apres » jamais affiché | Le programme n'a pas pu ouvrir l'écran : relancer à la main (`./venv/bin/python main.py`) et lire l'erreur. |
| La carte ne se construit pas : erreur `NoOptionError` | La clé `carto_key` manque dans `config.ini`, section `[map]` : la renseigner (Réglages, Carte et position). |
| La carte ne se construit pas : erreur HTTP 401 ou 403 | Clé CARTO probablement invalide, expirée ou mal copiée : la ressaisir dans Réglages, Carte et position, puis reconstruire. |
| La carte ne se construit pas pour une autre raison | Lire la sortie dans l'onglet Carte. Vérifier le chemin Python (Réglages, Application et système) et les dépendances du script (4.3). |
| « ATTENTION : la carte a ete generee pour d'autres coordonnees » | Reconstruire la carte (onglet Carte). |
| Erreur 429 dans les logs | Trop de requêtes : augmenter l'intervalle de requête et la pause entre les détails (Réglages, Flightradar24). La limitation est automatique mais temporaire. |
| « ATTENTION : horloge du systeme decalee par rapport a FR24 » | Horloge du Pi fausse : vérifier `timedatectl status` et la connexion Internet. |
| `type inconnu (icone par defaut) : XXXX` | Ajouter le type dans Réglages, Types d'avion. |
| Aucun avion affiché | Vérifier la latitude, la longitude, le rayon et l'altitude maximale suivie. La ligne d'état en bas à gauche donne le nombre d'avions suivis. |
| Utilisation CPU proche de 90 % | Normal par moments sur un Pi Zero. Baisser les images par seconde (Réglages, Affichage) ou reconstruire la carte en 1280×720 réduit directement la charge. |
| La fenêtre Windows ne change pas de mise en page quand on la redimensionne | Normal : l'image de la carte est mise à l'échelle. Pour une autre taille de travail, changer `width` et `height` et reconstruire la carte (8.4). |
| Pas de son | `aplay -l` doit lister une sortie. Vérifier que `SDL_AUDIODRIVER=dummy` n'est pas dans le service, que « Son » est activé dans Réglages et dans Pilotage (icône de haut-parleur barré à l'écran sinon), et lire `fd logs` pour `son indisponible`. |
| Un son retentit au lancement alors que « Son au lancement » et « Simuler une alerte » sont décochés | Le compteur de test de `cache/runtime.json` n'est pas mémorisé au chargement de `main.py` : il faut une ligne `rt_refresh(True)` au niveau du module (sans indentation, après la définition de `rt_refresh`). Sinon, un avion se trouvait déjà dans la zone d'alerte. |
| Le son ne se coupe pas à distance | Le programme et webadmin doivent tourner avec le même utilisateur, et `cache/runtime.json` doit être modifiable par lui. |
| La page webadmin ne s'ouvre pas | `sudo systemctl status flightadmin` et `journalctl -u flightadmin -n 50`. |
| Après un changement de port, la page ne revient pas | Ouvrir `http://flightradarpi.local:<nouveau port>`. En cas d'erreur de réglage : éditer `webadmin.ini` en SSH puis `sudo systemctl restart flightadmin`. |
| Mot de passe webadmin perdu | Éditer `webadmin.ini` en SSH (ligne `password =`), puis `sudo systemctl restart flightadmin`. |
| « sudo: a password is required » | `/etc/sudoers.d/flightadmin` manque ou le chemin de `systemctl` diffère : relancer `install_webadmin.sh` (ou l'installeur). |
| Logs vides dans webadmin | L'utilisateur doit pouvoir lire le journal (groupe `systemd-journal`, ajouté par le service). Le journal est en mémoire par défaut : il est vidé à chaque redémarrage du Pi. |
| La veille ne coupe pas le signal (`dpms` reste `On`) | Le script de veille n'est pas la version à framebuffer (6.2) : `grep -c "fb0/blank" /usr/local/bin/flight-screen` doit renvoyer au moins `1`. Relancer `sudo bash install_webadmin.sh` pour le réinstaller. |
| L'écran se rallume seul pendant la veille | La garde le remet en veille en moins de 20 secondes. Lire `journalctl -t flight-screen-guard` pour les heures, puis suivre la démarche de 6.2 (correctif HDMI, détection d'entrée du moniteur, commande de réveil, redémarrage, CEC). |
| La garde recoupe l'écran en boucle toutes les 20 secondes | Ancienne version de la garde (basée sur `setterm`) : relancer `sudo bash install_webadmin.sh`. |
| Après la mise à jour, ma veille personnalisée a disparu | `install_webadmin.sh` réécrit `flight-screen` et `flight-screen-guard`. Conserver une copie de vos modifications. |
| L'écran se rallume seulement quand je l'éteins depuis Home Assistant | Vérifier que la commande de l'entité n'est pas publiée avec « retain » sur le serveur MQTT (11.3), et lire `journalctl -t sudo \| grep flight-screen` pour voir qui a lancé le réveil. |
| Le moniteur ne s'éteint pas en veille | Vérifier `cat /sys/class/drm/card*-HDMI-A-*/dpms` : `Off` après la veille. Sinon essayer le DDC/CI (6.2). |
| Les tuiles de Pilotage ne tiennent pas sur une ligne | Sur ordinateur, la ligne unique s'applique à partir de 860 px de large ; en dessous, les tuiles passent sur deux colonnes. |
| MQTT : « paho manquant » | `sudo apt install python3-paho-mqtt` puis `sudo systemctl restart flightadmin`. |
| MQTT : « refuse » | Identifiants ou droits (ACL) du serveur MQTT. |
| Entités absentes dans Home Assistant | Vérifier l'intégration MQTT, `discovery_prefix`, le même serveur, puis « Reconnecter / republier ». |
| Wi-Fi instable | Désactiver l'économie d'énergie (6.4). |

---

## 14. Désinstallation

```
sudo systemctl disable --now flightadmin flightdisplay flight-screen-guard
sudo rm /etc/systemd/system/flightadmin.service /etc/systemd/system/flightdisplay.service /etc/systemd/system/flight-screen-guard.service
sudo rm /etc/sudoers.d/flightadmin /usr/local/bin/flight-screen /usr/local/bin/flight-screen-guard /usr/local/bin/fd
sudo systemctl daemon-reload
rm -rf ~/flightdisplay ~/flightdisplay-install.log
```

Pour annuler le correctif de veille, restaurer l'ancien fichier :

```
sudo cp /boot/firmware/cmdline.txt.bak /boot/firmware/cmdline.txt
```
