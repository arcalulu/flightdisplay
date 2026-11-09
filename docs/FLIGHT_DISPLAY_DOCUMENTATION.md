# Flight display — documentation unifiée

🇫🇷 **Français** · [🇬🇧 English](FLIGHT_DISPLAY_DOCUMENTATION.en.md)

Affichage temps réel des avions autour de chez vous sur un Raspberry Pi Zero : carte vectorielle, fiches photo, alerte de proximité (son, teinte rouge), liste des avions au sol, et une interface web d'administration (webadmin) qui permet de tout régler depuis un téléphone ou un ordinateur : réglages, carte, logs, son, veille d'écran, mises à jour du logiciel, langue, MQTT et Home Assistant. L'interface et l'écran existent en français et en anglais.

Cette documentation couvre l'installation automatique en une commande, l'installation manuelle complète depuis une carte SD vierge, toutes les modifications système nécessaires, puis la référence de chaque option du logiciel (`config.ini`), de webadmin (réglages de l'interface, API) et de MQTT.

## Sommaire

0. Démarrage rapide : installation automatique
1. Vue d'ensemble
2. Matériel et prérequis
3. Installer le Raspberry Pi (installation manuelle)
4. Installer Flight display
5. Services systemd et commande `fd`
6. Réglages système (audio, écran, carte SD, Wi-Fi)
7. Installer webadmin (manuel)
8. Référence de `config.ini`
9. Fonctionnement de l'affichage
10. Référence de webadmin (réglages de l'interface web en 10.2)
11. MQTT et Home Assistant
12. Maintenance
13. Dépannage
14. Désinstallation

---

## 0. Démarrage rapide : installation automatique

L'installeur `install.sh` fait tout le travail des sections 3 à 7 : il installe les paquets, récupère le projet, installe la carte, crée les services et démarre l'affichage et webadmin. Par défaut, il s'installe **tout seul**, avec une configuration d'exemple (aéroport de Bordeaux-Mérignac) que vous réglez ensuite depuis webadmin ; en mode manuel (`--manual`), il pose d'abord quelques questions. C'est la méthode recommandée.

### 0.1 Avant de commencer

1. Avec Raspberry Pi Imager, installez Raspberry Pi OS Lite (32-bit) sur la carte SD (voir 3.1). Dans la personnalisation, renseignez le nom d'hôte, un utilisateur, le Wi-Fi et activez SSH.
2. Pour une installation manuelle, tenez prêts : votre adresse (ou vos coordonnées), votre clé API CARTO (gratuite, voir 2 et le README), et si vous le souhaitez les identifiants de votre serveur MQTT. L'installation automatique n'a besoin de rien.
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

Ne lancez pas le script avec `sudo` : il utilise votre utilisateur normal et demande le mot de passe sudo tout au début, avant le compte à rebours, pour que le reste se déroule sans intervention (rien n'est demandé si `sudo` fonctionne sans mot de passe, comme avec Raspberry Pi Imager). Il fonctionne avec n'importe quel nom d'utilisateur.

**Installation automatique (par défaut).** Au lancement, un compte à rebours de 15 secondes s'affiche. Appuyez sur une touche (ou Ctrl+C) pour passer à l'installation manuelle ; sinon l'installation démarre seule, sans aucune question :

- la configuration est celle de `config.ini.example` (aéroport de Bordeaux-Mérignac, rayon 30 km) ;
- la carte est fournie : `defaults/background.png` et `defaults/map_meta.json` sont copiés à la racine, sans clé CARTO ni construction. Les règles de types d'avion de `defaults/types_extra.txt` sont copiées aussi. Les fichiers déjà présents ne sont jamais écrasés ;
- MQTT est désactivé et **aucun mot de passe webadmin n'est défini** (l'installeur le signale : définissez-en un dans Réglages, Serveur web) ;
- le correctif de veille d'écran est appliqué, sans redémarrage automatique ;
- le programme d'affichage démarre dès la fin de l'installation ; vous réglez ensuite votre position (carte de choix dans Réglages, Carte et position), la clé CARTO, le style et le reste depuis webadmin ;
- la langue est celle du système (français si le Pi est en français, sinon anglais) ; `--lang fr` ou `--lang en` la force ;
- sans terminal (installation lancée par un script), elle démarre immédiatement, et `sudo` doit alors fonctionner sans mot de passe ;
- si une configuration existe déjà, elle est conservée : seul le logiciel est mis à jour.

`--manual` lance l'installation classique (les questions ci-dessous) ; `--auto` démarre l'installation automatique sans attendre les 15 secondes.

### 0.3 Les questions

Ces questions ne sont posées qu'en installation manuelle : avec `--manual`, ou si vous interrompez le compte à rebours de l'installation automatique.

| Question | Détail |
|---|---|
| Mot de passe `sudo` | Demandé une fois, avant la première étape, pour que l'installation se déroule ensuite sans intervention. |
| Position | Votre adresse, convertie en coordonnées par le service OpenStreetMap Nominatim (l'adresse lui est envoyée une seule fois, les coordonnées sont arrondies à environ 11 m), ou une saisie manuelle de la latitude et de la longitude. |
| Rayon de la carte | De 1 à 200 km, 20 par défaut. |
| Résolution de la carte | 1920×1080, 1280×720 (conseillé sur Pi Zero : moins de charge) ou une taille personnalisée. Écrite dans `[display] width` et `height` de `config.ini`. |
| Aéroport proche | Code IATA à 3 lettres, facultatif. |
| Clé API CARTO | Saisie visible, pour vérifier le collage (le champ reste masqué dans webadmin). Écrite dans `config.ini`, section `[map]`, clé `carto_key`. Sans clé, la carte n'est pas construite (possible plus tard depuis webadmin). |
| Mot de passe de webadmin | Au moins 6 caractères, avec confirmation, ou Entrée pour en générer un aléatoire (affiché une seule fois à la fin). Saisie visible. |
| MQTT | Facultatif : serveur, port, identifiant, mot de passe (saisie visible). |
| Correctif de veille d'écran | Ajoute `vc4.force_hotplug=1` et `video=HDMI-A-1:D` au démarrage (voir 3.6) ; redémarrage conseillé. |
| Redémarrage automatique | Si le correctif d'écran est accepté : redémarrer le Pi tout seul à la fin (10 secondes, Ctrl+C pour annuler), ou le proposer en commande. |

Toutes les saisies restent visibles, mots de passe compris, pour que vous puissiez vérifier ce que vous tapez. Un récapitulatif est affiché avant le lancement. Toutes ces questions, plus le mot de passe `sudo`, sont posées **avant** la première étape : l'installation se déroule ensuite sans intervention.

### 0.4 Les étapes

| Étape | Action |
|---|---|
| 1 | Mise à jour de la liste des paquets (`apt update`), avec barre de progression. |
| 2 | Installation des paquets : git, curl, Python, pygame, Pillow, requests, paho-mqtt, polices, outils audio, kbd, bibliothèques EGL (`libegl1`, `libegl-mesa0`, `libgles2`). |
| 3 | Récupération du projet depuis GitHub (ou mise à jour s'il est déjà cloné). |
| 4 | Environnement Python (venv) et bibliothèques (`requirements.txt`). |
| 5 | Dépendances de `build_map_vector.py` : le script est analysé et les modules manquants sont installés. |
| 6 | Écriture de `config.ini` (droits 600), réglages de l'interface web compris. |
| 7 | Construction de la carte (plusieurs minutes sur un Pi Zero). |
| 8 | Service `flightdisplay`, commande `fd`, groupes `video render input audio`. |
| 9 | webadmin : service `flightadmin`, droits sudo limités, script de veille `flight-screen` et sa garde `flight-screen-guard`. |
| 10 | Correctif de veille d'écran (si accepté). |
| 11 | Démarrage des services et test de webadmin. |

Les vérifications du Pi (système, matériel, mémoire, espace disque, Internet, horloge) viennent avant l'étape 1 et ne sont pas numérotées.

L'écran montre pour chaque étape un indicateur animé, le temps écoulé, la dernière ligne de sortie et, pour les téléchargements, un pourcentage. Chaque étape tient sur une seule ligne qui se met à jour : rien ne défile. Une barre globale indique l'avancement. Le détail complet est écrit dans le journal `~/flightdisplay-install.log`.

### 0.5 Si quelque chose échoue

- Une étape essentielle qui échoue arrête l'installeur avec un message clair, les dernières lignes du journal et le chemin du fichier. Corrigez la cause (réseau, espace disque), puis relancez la même commande : l'installeur reprend et conserve ce qui est déjà fait.
- Si seule la carte ne peut pas être construite (clé absente ou refusée, erreur du script), tout le reste est installé. webadmin fonctionne, et la carte se construit depuis webadmin (Réglages, Carte et position, « Reconstruire la carte ») après correction. Le programme d'affichage démarre automatiquement dès qu'une carte existe, ou avec l'interrupteur « Programme Flight Display » dans Pilotage.
- **Pas de droits sudo** : l'installeur vérifie tout de suite que votre utilisateur peut utiliser `sudo` (sans mot de passe, ou membre du groupe `sudo`) et s'arrête sinon, avant toute modification. L'utilisateur créé par Raspberry Pi Imager a normalement ces droits. Sinon :
  - le plus simple : reflasher la carte avec Raspberry Pi Imager en renseignant le nom d'utilisateur et le mot de passe dans la personnalisation ;
  - depuis un autre compte administrateur : `sudo usermod -aG sudo <utilisateur>` et `echo '<utilisateur> ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/010_<utilisateur>` (puis `sudo chmod 440` sur ce fichier), puis déconnexion et reconnexion ;
  - sans autre compte : sur la partition `bootfs` de la carte, ajouter `init=/bin/bash` à la fin de la ligne de `cmdline.txt`, démarrer le Pi, taper `mount -o remount,rw /`, les deux commandes `usermod -aG sudo <utilisateur>` et `echo '<utilisateur> ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/010_<utilisateur>` suivies de `chmod 440 /etc/sudoers.d/010_<utilisateur>` et `sync`, éteindre, puis retirer `init=/bin/bash` de `cmdline.txt`.
- Les avertissements non bloquants (horloge, espace disque, matériel non reconnu) sont rappelés dans le résumé final.

### 0.6 Relancer l'installeur

Si `config.ini` existe déjà, l'installeur propose de le conserver : il met alors à jour le logiciel et les services sans reposer les questions ni reconstruire la carte. En répondant non, il repose toutes les questions et réécrit les fichiers. Dans les deux cas, l'étape 9 réécrit `/usr/local/bin/flight-screen` et `/usr/local/bin/flight-screen-guard` avec les versions du dépôt : toute modification manuelle de ces deux scripts est écrasée.

### 0.7 Options et variables

| Élément | Effet |
|---|---|
| `--dry-run` | Simulation : le script déroule toutes les étapes sans rien installer. Utile pour voir ce qu'il va faire. |
| `--help` | Affiche l'aide. |
| `--manual`, `FD_MANUAL=1` | Installation classique : les questions sont posées (0.3). |
| `--auto`, `FD_AUTO=1` | Installation automatique tout de suite, sans le compte à rebours. |
| `FD_COUNTDOWN` | Durée du compte à rebours de l'installation automatique, en secondes (15 par défaut, `0` = aucun). |
| `FD_DIR` | Dossier d'installation (par défaut `~/flightdisplay`, ou le dossier du script s'il est lancé depuis un clone). |
| `FD_REPO_URL`, `FD_BRANCH` | Dépôt et branche à cloner. |
| `FD_LOG` | Fichier journal (par défaut `~/flightdisplay-install.log`). |
| `NO_COLOR=1` | Désactive les couleurs. |
| `--lang fr\|en`, `FD_LANG` | Langue de l'installeur, de webadmin et de l'écran. Sans option : la langue du système en installation automatique, une question au début en installation manuelle. Écrite dans `[general] language`. |
| `--yes`, `--non-interactive`, `FD_YES=1` | Mode sans questions (voir ci-dessous). |

**Mode sans questions.** Avec `--yes`, l'installeur ne lit rien au clavier : il prend ses réponses dans des variables d'environnement et utilise `sudo -n` (sudo doit fonctionner sans mot de passe, ce qui est le cas par défaut sur Raspberry Pi OS). Exemple :

```
FD_LAT=48.8566 FD_LON=2.3522 FD_RADIUS=20 FD_MAP_SIZE=1280x720 FD_CARTO_KEY=VOTRE_CLE FD_LANG=fr \
  bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh) --yes
```

| Variable | Défaut | Rôle |
|---|---|---|
| `FD_ADDRESS` ou `FD_LAT` et `FD_LON` | obligatoire à la première installation | Position (l'adresse est convertie en coordonnées). |
| `FD_RADIUS` | 20 | Rayon de la carte en km (1 à 200). |
| `FD_MAP_SIZE` | `1280x720` | Taille de la carte (`1920x1080` possible). |
| `FD_AIRPORT` | vide | Code IATA d'un aéroport proche. |
| `FD_CARTO_KEY` | vide | Clé API CARTO (sans elle, la carte se construit plus tard depuis webadmin). |
| `FD_WEB_PASSWORD` | généré | Mot de passe de webadmin (6 caractères minimum) ; s'il est vide, un mot de passe est généré et affiché à la fin. |
| `FD_MQTT_HOST`, `FD_MQTT_PORT`, `FD_MQTT_USER`, `FD_MQTT_PASS` | vides (port 1883) | Serveur MQTT facultatif. |
| `FD_HDMI_FIX` | 1 | Correctif de veille d'écran (3.6). |
| `FD_AUTO_REBOOT` | 0 | `1` : redémarrer à la fin si le correctif a été appliqué. |
| `FD_KEEP` | 1 | Si `config.ini` existe : `1` le conserve (mise à jour du logiciel seule), `0` le réécrit. |

Une valeur invalide arrête l'installeur avec un message clair avant toute installation.

### 0.8 À la fin

Le résumé donne l'adresse de webadmin (`http://<nom-du-pi>.local:8080` et par adresse IP), l'identifiant, le mot de passe (s'il a été généré, il n'est plus affiché ensuite) et les commandes utiles. Si le correctif de veille a été appliqué, l'installeur redémarre le Pi (ou vous indique `sudo reboot`) selon votre réponse à la question sur le redémarrage automatique.

Le mot de passe de webadmin, la clé CARTO et les identifiants MQTT sont stockés dans `config.ini`, avec des droits 600. Tous les réglages se modifient ensuite depuis webadmin. L'installeur existe en français et en anglais (choisi au début, ou avec `--lang`) ; la langue de webadmin et de l'écran, écrite dans `config.ini`, se change ensuite dans Réglages, Langue (8.1).

---

## 1. Vue d'ensemble

### Composants

| Élément | Rôle |
|---|---|
| `main.py` | Programme d'affichage (pygame, sortie directe KMS/DRM, sans bureau graphique). |
| `build_map_vector.py` | Génère la carte `background.png` et `map_meta.json` à partir de `config.ini` (position, rayon, taille, clé CARTO). |
| `mapstyle.py` | Thèmes, couches et couleurs du fond de carte, partagé par `build_map_vector.py` et webadmin (page « Style de la carte »). |
| `config.ini` | Tous les réglages : programme (dont `[general]` pour la langue et `[label]` pour les étiquettes), plus les sections `[server]`, `[app]`, `[screen]`, `[build]`, `[update]` et `[mqtt]` de l'interface web. Modèle : `config.ini.example`. |
| `types_extra.txt` | Optionnel : associe des types d'avion inconnus à une forme d'icône. |
| `webadmin.py` | Serveur web d'administration (bibliothèque standard Python). |
| `webadmin_mqtt.py` | Pont MQTT / Home Assistant, chargé par webadmin. |
| `webadmin_update.py` | Mises à jour depuis GitHub (onglet « Mises à jour »), chargé par webadmin. |
| `i18n.py` et dossier `lang/` | Traductions (français, anglais) partagées par le programme d'affichage et webadmin. |
| `install.sh` | Installeur automatique en une commande. |
| `/usr/local/bin/flight-screen` | Script root de veille et réveil de l'écran (créé par l'étape 9 de `install.sh`). |
| `/usr/local/bin/flight-screen-guard` | Garde qui remet l'écran en veille s'il se rallume tout seul pendant une veille (créée par l'étape 9 de `install.sh`). |
| `/usr/local/bin/fd` | Raccourci : `fd logs`, `fd restart`... |
| `cache/` | Détails d'avions, photos, état du son (`runtime.json`), état de la dernière mise à jour (`update.json`). |

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
| Reconstruction de la carte | webadmin, Réglages, Carte et position (section « Reconstruction de la carte », en bas de la page) |
| Langue de l'interface et de l'écran | webadmin, Réglages, Langue (8.1) |
| Contenu, ordre et style des étiquettes d'avions | webadmin, Réglages, Étiquettes des avions (8.7) |
| Mise à jour du logiciel, historique des versions | webadmin, onglet Mises à jour (12.1) |
| Allumage et extinction automatiques de l'écran | webadmin, Réglages, Planning de l'écran (10.1) |
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
- Pour l'installation manuelle : les fichiers du projet (`main.py`, `build_map_vector.py`, `config.ini.example`, `webadmin.py`, `webadmin_mqtt.py`, `webadmin_update.py`, `i18n.py`, le dossier `lang`, `requirements.txt`), soit par `git clone https://github.com/arcalulu/flightdisplay.git`, soit copiés depuis un ordinateur.

---

## 3. Installer le Raspberry Pi (installation manuelle)

Les sections 3 à 7 décrivent pas à pas ce que l'installeur automatique (section 0) réalise. Utilisez-les si vous préférez tout faire à la main, pour comprendre ce qui est installé, ou pour dépanner.

### 3.1 Flasher la carte SD

1. Installer Raspberry Pi Imager sur votre ordinateur.
2. Choisir l'appareil : Raspberry Pi Zero W (le Pi Zero sans W n'a pas de Wi-Fi et ne convient pas).
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

Certains moniteurs coupent leur signal de détection en veille, ce qui fait croire au Pi qu'un écran vient d'être branché et rallume la sortie. Pour que le Pi ignore ces changements, ajouter `vc4.force_hotplug=1` et `video=HDMI-A-1:D` à la fin de l'unique ligne de `cmdline.txt` (la seconde option force la sortie HDMI comme « connectée » dans le pilote graphique actuel ; avec les noyaux récents, la première seule ne suffit plus) :

```
sudo cp /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.bak
sudo sed -i '1 s/$/ vc4.force_hotplug=1 video=HDMI-A-1:D/' /boot/firmware/cmdline.txt
cat /boot/firmware/cmdline.txt
sudo reboot
```

Le fichier doit rester sur une seule ligne. Sur certaines versions plus anciennes, il se trouve dans `/boot/cmdline.txt`. Conséquence : le Pi ne détecte plus un moniteur débranché ou changé à chaud, il faut alors le redémarrer. Vérification après le redémarrage : `grep -o 'vc4.force_hotplug=1\|video=HDMI-A-1:D' /proc/cmdline` (les deux options doivent apparaître).

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
scp -r main.py build_map_vector.py config.ini.example webadmin.py webadmin_mqtt.py webadmin_update.py i18n.py lang requirements.txt flightdisplay@flightradarpi.local:~/flightdisplay/
```

Puis créez l'environnement Python comme en 4.1. Cette méthode désactive les mises à jour depuis webadmin (le dossier n'est pas un dépôt Git). Le fichier `types_extra.txt` est optionnel : il se crée depuis webadmin (section 9.8).

### 4.3 Dépendances de build_map_vector.py

Le script peut demander des bibliothèques supplémentaires (l'installeur automatique les détecte et les installe). Pour les repérer à la main :

```
cd ~/flightdisplay
grep -E '^(import|from) ' build_map_vector.py
```

Installer ce qui manque : paquets `python3-...` par apt s'ils existent, sinon `./venv/bin/pip install <nom>`. Pillow (`python3-pil`) est indispensable : l'installeur le vérifie et l'ajoute si besoin. Si l'étape affiche « Analyse de build_map_vector.py impossible », le script contient une erreur de syntaxe : l'erreur exacte est dans `~/flightdisplay-install.log`.

### 4.4 Créer config.ini

```
cd ~/flightdisplay
cp config.ini.example config.ini
chmod 600 config.ini
nano config.ini
```

Il faut renseigner au minimum la position, la clé CARTO et la taille de la carte. Toutes les options sont décrites en section 8 (programme) et 10.2 (interface web), et modifiables ensuite depuis webadmin. L'installeur automatique ajoute lui-même les sections de l'interface web avec leurs valeurs par défaut. Exemple minimal :

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

`config.ini` contient des secrets (clé CARTO, mot de passe webadmin, identifiants MQTT) : il n'est pas versionné par Git (il est dans `.gitignore`) et doit rester en droits restreints (`chmod 600`).

### 4.5 Construire la carte

```
cd ~/flightdisplay
./venv/bin/python -u build_map_vector.py
```

Le script télécharge le fond de carte CARTO avec la clé de `[map] carto_key`, puis produit `background.png` et `map_meta.json` dans le dossier. Il demande un accès Internet et peut durer plusieurs minutes sur un Zero. Il lit la position et le rayon dans `[position]`, la taille de l'image dans `[display] width` et `height`. Sans la clé `carto_key` dans `config.ini`, il s'arrête avec une erreur `NoOptionError`.

La carte est à refaire chaque fois que l'un de ces réglages change : latitude, longitude, rayon, largeur, hauteur, clé (depuis webadmin, Réglages, Carte et position).

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

La veille est assurée par deux scripts créés par l'étape 9 de `install.sh` : `/usr/local/bin/flight-screen` (veille et réveil) et `/usr/local/bin/flight-screen-guard` (garde).

**Ce que devient le programme pendant la veille.** Il n'est plus arrêté : il continue de suivre les avions (historique « Avions vus », alertes marquées, sans son), mais il cesse de dessiner et **ferme son affichage** dès qu'il voit le fichier témoin `/run/flight-screen-off`. Tant qu'il garde l'affichage, il garde la main sur la sortie vidéo et écrire dans le framebuffer ne coupe pas le signal (`dpms` reste à `On`) : c'est pourquoi il le ferme. Il économise ainsi le processeur et la température. Au réveil, il rouvre l'affichage tout seul ; si la réouverture échoue, il se relance (le service est en `Restart=always`). La commande `flight-screen version` renvoie `2` : webadmin s'en sert pour savoir que le script est à jour.

**Comment le signal est coupé.** La commande `setterm --blank force` n'éteint pas réellement la sortie HDMI de ce Pi (`dpms` reste `On`). Le script utilise à la place le framebuffer du noyau : écrire `4` dans `/sys/class/graphics/fb0/blank` coupe la sortie (`dpms` passe à `Off`, le moniteur s'endort), et écrire `0` la rallume. Si ce fichier n'est pas accessible, le script retombe sur `setterm`.

**Terminal de veille.** Une fois l'affichage fermé, la veille bascule sur un terminal virtuel inutilisé (`tty7`), où aucun programme n'écrit : ni invite de connexion ni message ne peut ranimer la console. Le réveil revient sur `tty1`.

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
```

Le fichier témoin `/run/flight-screen-off` indique que la veille est demandée ; il disparaît au redémarrage du Pi.

**La garde.** `/usr/local/bin/flight-screen-guard`, lancée par le service `flight-screen-guard`, vérifie toutes les 20 secondes que la sortie vidéo est bien éteinte pendant une veille. Si l'écran s'est rallumé tout seul (fichier témoin présent, `dpms` à `On`), elle le coupe de nouveau et note l'événement. Elle ne fait rien en dehors d'une veille.

```sh
#!/bin/sh
SVC=flightdisplay
FLAG=/run/flight-screen-off
FB=/sys/class/graphics/fb0/blank
IDLE_VT=7
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

1. Vérifier que le correctif de l'étape 3.6 est actif (`grep -o 'vc4.force_hotplug=1\|video=HDMI-A-1:D' /proc/cmdline`, les deux options doivent apparaître).
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

## 7. Installer webadmin (manuel)

L'installeur automatique (section 0) exécute déjà cette étape, à son étape 9. Il n'y a pas de script séparé.

### 7.1 Installation

Le plus simple est de relancer l'installeur en conservant la configuration (section 0.6) : il réinstalle les services webadmin et veille sans reposer les questions. Pour une installation entièrement manuelle, les étapes sont :

1. installer `kbd` et `python3-paho-mqtt` s'ils manquent ;
2. créer `/usr/local/bin/flight-screen` (veille et réveil de l'écran, section 6.2, droits 755, propriétaire root) ;
3. créer `/usr/local/bin/flight-screen-guard` et l'unité `flight-screen-guard.service`, puis activer et démarrer le service ;
4. créer `/etc/sudoers.d/flightadmin` (droits 440), validé au préalable par `visudo -cf` : il autorise uniquement, sans mot de passe, démarrer, arrêter et relancer le service `flightdisplay`, redémarrer, éteindre, et `flight-screen on|off` ;
5. renseigner `python` dans `config.ini`, section `[app]`, avec l'interpréteur du venv (utilisé pour construire la carte) et laisser `config.ini` en droits 600 ;
6. créer l'unité `flightadmin.service` (utilisateur normal, groupe `systemd-journal` pour lire les logs), puis `systemctl daemon-reload`, `enable` et `restart`.

L'étape 9 est relançable à volonté : elle réécrit les deux scripts de veille (toute modification manuelle est perdue) et redémarre les services webadmin et garde.

Variables d'environnement acceptées par l'installeur pour cette étape :

| Variable | Défaut | Rôle |
|---|---|---|
| `FD_MAIN_VT` | 1 | Terminal virtuel principal (retour au réveil). |
| `FD_IDLE_VT` | 7 | Terminal virtuel inutilisé pour la veille. |

Exemple : `FD_IDLE_VT=8 bash install.sh`.

### 7.2 Premier accès

Ouvrir `http://flightradarpi.local:8080`. Identifiant : `admin`, mot de passe : celui saisi à l'installation (modifiable dans Réglages, Serveur web). Sur iPhone, « Partager » puis « Sur l'écran d'accueil » donne une icône d'application.

```
sudo systemctl status flightadmin
journalctl -u flightadmin -n 50 --no-pager
```

### 7.3 Redémarrer ou mettre à jour webadmin

- Depuis l'interface : un changement de port ou d'adresse d'écoute redémarre webadmin à l'enregistrement et rouvre la page et rouvre la page (sur le nouveau port si besoin).
- En ligne de commande, après avoir remplacé `webadmin.py`, `webadmin_mqtt.py`, `webadmin_update.py`, `i18n.py` ou un fichier de `lang/` : `sudo systemctl restart flightadmin`.
- Depuis l'onglet Mises à jour (12.1), webadmin se redémarre tout seul à la fin de la mise à jour.

---

## 8. Référence de `config.ini`

Les options manquantes prennent la valeur par défaut indiquée. Chacune se règle dans webadmin, onglet Réglages, dans la catégorie indiquée par le titre de section. Les changements sont lus par le programme au démarrage : il faut le relancer (l'enregistrement dans webadmin le fait pour vous, ou `fd restart`). Les réglages marqués « carte » demandent en plus de reconstruire la carte. Les largeurs (panneau, liste) sont exprimées pour un écran de 1080 pixels de haut et s'adaptent à la hauteur réelle de la carte. Si vous modifiez le fichier à la main, mettez les commentaires sur leur propre ligne, jamais à la suite d'une valeur.

Le modèle `config.ini.example` contient toutes les sections avec des valeurs d'exemple. Les sections de l'interface web (`[server]`, `[app]`, `[screen]`, `[build]`, `[update]`, `[mqtt]`) sont décrites en 10.2.

### 8.1 `[general]` — catégorie « Langue »

| Option | Défaut | Description |
|---|---|---|
| `language` | `fr` | Code de la langue : `fr` (français) ou `en` (anglais), ou toute langue ajoutée dans `lang/`. Change d'un coup l'interface webadmin (immédiatement) et le texte affiché à l'écran par le programme d'affichage (après sa relance). Un code inconnu revient au français. |

Se règle dans webadmin : Réglages, Langue. L'ajout d'une langue est décrit en 12.3.

### 8.2 `[position]` — catégorie « Carte et position »

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `latitude` | obligatoire | -90 à 90 | Latitude de la maison, en degrés décimaux (carte). |
| `longitude` | obligatoire | -180 à 180 | Longitude de la maison (carte). |
| `radius_km` | obligatoire | 1 à 200 | Rayon couvert par la carte (km) (carte). |

Modifier l'une de ces trois valeurs oblige à reconstruire la carte (webadmin l'indique). Le programme affiche un avertissement au démarrage si la carte a été construite pour d'autres coordonnées.

**Cercles de distance** (`[rings]`, webadmin, Réglages, « Carte et position », groupe « Cercles de distance »). Ces cercles sont tracés par le programme autour de votre position : aucune reconstruction de carte n'est nécessaire, seulement une relance du programme. Par défaut : 4 cercles, de 5 à 20 km.

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `show` | `true` | `true` / `false` | Afficher les cercles. |
| `count` | 4 | 0 à 30 | Nombre de cercles. Seuls ceux qui tiennent dans la hauteur de la carte (rayon de la carte) sont tracés. |
| `first_km` | 5 | 0,1 à 200 | Distance du premier cercle (km). Peut aussi servir de distance d'alerte (`[alert] link_first_ring`). |
| `step_km` | 5 | 0,1 à 200 | Écartement entre deux cercles (km). |
| `width` | 1 | 1 à 8 | Épaisseur du trait (pixels). |
| `color` | `#2d3746` | `#rrggbb` | Couleur des cercles. |
| `show_labels` | `false` | `true` / `false` | Écrit la distance (« 5 km ») au sommet de chaque cercle. |

La carte de choix de la position de webadmin dessine ces cercles (gris) : ils bougent en direct quand vous changez les valeurs.

### 8.3 `[map]` — catégorie « Carte et position », groupe « Fond de carte »

| Option | Défaut | Description |
|---|---|---|
| `carto_key` | obligatoire pour construire la carte | Clé API CARTO utilisée par `build_map_vector.py` pour télécharger le fond de carte vectoriel. Dans webadmin, le champ est masqué comme un mot de passe (carte). |

La clé n'est lue que par `build_map_vector.py`, pas par `main.py`. Elle est stockée en clair dans `config.ini` : gardez le fichier en droits 600 et ne le publiez jamais.

**Style du fond de carte** (webadmin, Réglages, « Style de la carte » ; toutes ces options demandent de reconstruire la carte). Sans ces options, la carte garde son apparence d'origine (thème Sombre : eau, rivières, aéroports et pistes).

| Option | Défaut | Description |
|---|---|---|
| `[mapstyle] preset` | `dark` | Thème : `dark` (Sombre), `black` (Noir), `light` (Clair), `voyager`, `radar`. |
| `[mapstyle] show_water`, `show_rivers`, `show_aerodromes`, `show_runways` | `true` | Eau, rivières et canaux, aéroports, pistes. |
| `[mapstyle] show_taxiways`, `show_parks`, `show_roads_major`, `show_roads_minor`, `show_rail`, `show_buildings`, `show_boundaries` | `false` | Voies de circulation, parcs, routes principales et autoroutes, petites routes, voies ferrées, bâtiments, frontières. |
| `[map] forest` | `false` | Forêts (clé historique, aussi lue depuis `[mapstyle] show_forest`). |
| `[mapstyle] road_width` | `1.0` | Multiplicateur d'épaisseur des routes (0,3 à 4). |
| `[mapstyle] color_<nom>` | vide | Couleur `#rrggbb` qui remplace celle du thème : `land`, `water`, `forest`, `park`, `aero`, `building`, `road_minor`, `road_major`, `road_high`, `rail`, `taxiway`, `runway`, `boundary`, `label`. |
| `[cities] show` | `true` | Afficher les noms de lieux. |
| `[cities] kinds` | `city,town` | Types de lieux : `city`, `town`, `village`. |
| `[cities] max_labels` | `25` | Nombre maximum de noms. |
| `[cities] font_size` | `20` | Taille du texte (pixels). |

La page de webadmin propose des miniatures des cinq thèmes, des interrupteurs pour les éléments, un sélecteur de couleurs et les réglages des noms de lieux. Il y a deux aperçus. L'**aperçu indicatif** s'affiche tout de suite, sans internet ni clé : une carte d'exemple par thème (`defaults/themes/*.png`, générées une fois avec CARTO sur la zone d'origine de `config.ini.example`) s'affiche dans l'aperçu quand vous choisissez un thème. Les cinq vignettes de thèmes sont ces mêmes images : elles ne changent jamais. Les couleurs personnalisées et les éléments cochés n'y apparaissent pas. L'**aperçu fidèle**, lancé par le bouton « Mettre à jour l'aperçu », est dessiné par `build_map_vector.py --preview` (même programme que la construction, image réduite à 640 px de large, zone et ratio de la page « Carte et position », tous les réglages non enregistrés compris : thème, éléments, couleurs, noms de lieux) : il nécessite la clé CARTO et internet, et montre ce que l'écran affichera. Le bouton « Voir la carte actuelle » affiche la carte réellement utilisée par le programme (`background.png`) avec sa date de construction. Aucun des aperçus ne modifie la vraie carte : une fois l'aperçu validé, il faut enregistrer puis reconstruire la carte. Les images et les tuiles téléchargées pour l'aperçu fidèle sont gardées dans `cache/mapprev/`. Les thèmes clairs rendent les avions jaunes moins lisibles.

### 8.4 `[api]` — catégorie « Flightradar24 »

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `poll_seconds` | 30 | 5 à 600 | Intervalle entre deux requêtes de la liste des avions. Trop bas, Flightradar24 répond « 429 ». |
| `details_pause_seconds` | 4 | 0 à 60 | Pause entre deux requêtes de détails d'avion (modèle, compagnie, photo). |
| `stale_seconds` | 30 | 5 à 600 | Au-delà de ce délai sans nouvelle position, l'avion est retiré. Sert aussi de plafond à l'extrapolation de position. |

Protection automatique : après une erreur 429, l'intervalle est multiplié par 1,5 (maximum 120 s), les requêtes sont suspendues 60 s, puis l'intervalle redescend peu à peu vers `poll_seconds`. Pour les détails, une erreur 429 suspend les requêtes 120 s et la demande est rejouée. Une autre erreur réseau déclenche un délai croissant (maximum 5 minutes).

### 8.5 `[display]` — catégories « Affichage » et « Carte et position »

| Option | Défaut | Valeurs | Description |
|---|---|---|---|
| `fullscreen` | false | true / false | Plein écran. Sur un Raspberry Pi, l'affichage est toujours en plein écran : le réglage est masqué dans webadmin et ignoré. Sur PC, `false` donne une fenêtre redimensionnable. |
| `fps` | 10 | 1 à 60 | Images par seconde. Une valeur basse ménage le Pi Zero : c'est le levier principal pour réduire l'utilisation du processeur. |
| `altitude_unit` | ft | `ft`, `m` | Unité d'altitude affichée. |
| `speed_unit` | kmh | `kmh`, `kt` | Unité de vitesse affichée. |
| `max_altitude_ft` | 0 | 0 à 100000 | Les avions plus hauts ne sont ni suivis ni affichés (0 = pas de limite). Leur nombre apparaît dans la ligne d'état. S'applique aussi à l'alerte. |
| `icon_scale` | 1.25 | 0.3 à 5 | Taille des icônes d'avion. |
| `plane_color_panel` | `#ff4646` | `#rrggbb` | Couleur de l'avion dont la photo est affichée dans le panneau (sa traînée prend une teinte assortie). |
| `plane_color_known` | `#ffd250` | `#rrggbb` | Couleur des autres avions, dont le type est connu. |
| `plane_color_unknown` | `#ffaa5a` | `#rrggbb` | Couleur des avions dont le type est absent de la liste (icône par défaut). |
| `width` | obligatoire | 320 à 7680 | Largeur de la carte en pixels (carte). |
| `height` | obligatoire | 240 à 4320 | Hauteur de la carte en pixels (carte). |

`width` et `height` sont lues par `build_map_vector.py`, qui s'en sert pour fixer la taille de l'image de fond. `main.py` ne les lit pas : il prend la taille réelle dans `map_meta.json`, produit à la construction. Changer ces valeurs n'a donc d'effet qu'après avoir reconstruit la carte. Dans webadmin, ces deux réglages se trouvent dans la catégorie « Carte et position » (groupe « Taille de la carte »), avec ceux de la position. Quand le Pi détecte l'écran branché, ce groupe affiche sa résolution maximale (lue sur la sortie vidéo) avec un bouton « Utiliser pour la carte » qui reporte largeur et hauteur dans les deux champs. Sur un Raspberry Pi Zero, un avertissement rappelle que la reconstruction d'une grande carte peut durer plusieurs minutes.

Toute l'interface est dessinée à la résolution de la carte. Sous Windows et sur le Pi, la fenêtre ou l'écran affiche cette image mise à l'échelle en conservant les proportions : redimensionner la fenêtre ne change que le zoom. Pour une autre résolution de travail, changez `width` et `height`, puis reconstruisez la carte. Les tailles de texte et d'icônes s'adaptent à la hauteur de la carte. Sur Pi Zero, 1280×720 réduit nettement le nombre de pixels dessinés par rapport à 1920×1080, donc la charge du processeur.

### 8.6 `[panel]` — catégorie « Panneau photo »

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `width` | 480 | 200 à 1200 | Largeur du panneau (px, base 1080p). |
| `rotate_seconds` | 12 | 3 à 120 | Durée d'affichage de chaque avion quand plusieurs sont éligibles. |
| `corner_top_left`, `corner_top_right`, `corner_bottom_left`, `corner_bottom_right` | true | true / false | Angles où le panneau peut s'afficher. Un angle décoché n'est jamais utilisé, même si des avions passent derrière les autres angles (le panneau choisit alors le moins gênant parmi les angles autorisés). Si les quatre sont décochés, aucune restriction. |

Le texte affiché sous la photo (modèle, compagnie, trajet, altitude, vitesse, crédit) se règle dans l'onglet « Contenu du texte » de la catégorie « Panneau photo » (voir plus bas, `[panel_content]`). La ligne rouge d'alerte de proximité n'est pas modifiable. Le texte ne dépasse jamais du panneau : une ligne trop longue est coupée et terminée par « … » (réduire la taille, retirer un élément de la ligne ou élargir le panneau, `[panel] width`, pour tout afficher).

**`[panel_content]` — catégorie « Panneau photo », onglet « Contenu du texte »**

Même système que les étiquettes d'avions (8.7) : un éditeur avec aperçu (la photo y est figurée par un cadre), et pour chaque élément les flèches ▲ ▼ (ordre), l'interrupteur (afficher ou non), la taille (Petit, Moyen, Grand), G (gras), I (italique) et « Même ligne ». Éléments : `model`, `registration`, `callsign`, `airline`, `route`, `altitude`, `speed`, et `credit` (le crédit du photographe).

| Option | Défaut | Description |
|---|---|---|
| `order` | `model,registration,callsign,airline,route,altitude,speed,credit` | Ordre d'affichage, de haut en bas. Les éléments absents de la liste sont ajoutés à la fin. |
| `show_<élément>` | tous : true, sauf callsign : false | Afficher l'élément. Pour le crédit, l'option est `[panel] show_credit` (clé historique conservée) : le crédit est déjà visible à l'intérieur de l'image, cette ligne le répète sous la photo. |
| `<élément>_size` | model, registration, callsign : `large` ; airline, route, altitude, speed : `medium` ; credit : `small` | `small`, `medium` ou `large`. |
| `<élément>_bold` | model, registration, callsign : true ; les autres : false | Gras. |
| `<élément>_italic` | false | Italique (synthétique). |
| `<élément>_same_line` | registration, speed : true ; callsign : true ; les autres : false | Sur la même ligne que l'élément visible précédent. |

Les valeurs par défaut reproduisent l'ancien panneau : modèle et immatriculation en gras sur la première ligne, compagnie, trajet, « Altitude … · Vitesse … » et crédit.

### 8.7 `[label]` — catégorie « Étiquettes des avions »

Petits panneaux affichés à côté de chaque avion sur la carte (le grand panneau photo n'est pas concerné). Dans webadmin, la catégorie propose un éditeur : un aperçu en direct, puis une ligne par élément avec les flèches ▲ ▼ (ordre), l'interrupteur (afficher ou non), la taille (Petit, Moyen, Grand), les boutons G (gras) et I (italique), et « Même ligne » (place l'élément sur la ligne de l'élément précédent, séparé par un point médian). Si tout est masqué, aucun panneau n'est affiché. Pris en compte après relance du programme.

Éléments : `model` (modèle ; avant le chargement des détails : code du type), `registration` (immatriculation), `callsign` (indicatif de vol), `airline` (compagnie), `route` (trajet), `altitude`, `speed` (vitesse).

| Option | Défaut | Description |
|---|---|---|
| `order` | `model,registration,callsign,airline,route,altitude,speed` | Ordre d'affichage, de haut en bas. Les éléments absents de la liste sont ajoutés à la fin. |
| `show_<élément>` | model, airline, route, altitude, speed : true ; registration, callsign : false | Afficher l'élément. |
| `<élément>_size` | model, registration, callsign : `medium` ; les autres : `small` | `small`, `medium` ou `large`. |
| `<élément>_bold` | false | Gras. |
| `<élément>_italic` | false | Italique (synthétique : la police du Pi n'a pas de variante italique). |
| `<élément>_same_line` | registration, callsign, speed : true ; les autres : false | Sur la même ligne que l'élément visible précédent. |

### 8.8 `[ground]` — catégorie « Avions au sol »

| Option | Défaut | Plage | Description |
|---|---|---|---|
| `show_list` | true | true / false | Affiche la liste des avions au sol en bas à droite. |
| `max_rows` | 8 | 1 à 30 | Nombre maximum de lignes de la liste. |
| `width` | 780 | 300 à 1800 | Largeur de la liste (px, base 1080p). |
| `airport_iata` | vide | code IATA | Aéroport de référence (ex. `BOD`). Affiche « de ... » pour les arrivées et « vers ... » pour les départs, et limite la détection d'atterrissage aux vols qui arrivent à cet aéroport. |
| `min_speed_kt` | 0 | 0 à 200 | Vitesse minimale pour apparaître dans la liste. Les avions plus lents ne déclenchent pas non plus de requêtes de détails. |
| `landed_alt_ft` | 2000 | 0 à 10000 | Un avion qui disparaît des données sous cette altitude est considéré comme posé et passe dans la liste au sol. |
| `landed_keep_minutes` | 10 | 0 à 240 | Durée pendant laquelle un avion posé reste affiché dans la liste. |

### 8.9 `[alert]` — catégorie « Alerte de proximité »

Les options sont regroupées dans webadmin en cinq groupes : Zone, Son, Teinte rouge, Plage d'altitude, Au démarrage.

| Option | Défaut | Plage | Groupe | Description |
|---|---|---|---|---|
| `radius_km` | 5 | 0 à 50 | Zone | Rayon du cercle d'alerte. `0` désactive toute l'alerte (teinte, son de proximité, simulation). Ignoré si `link_first_ring` est activé. |
| `link_first_ring` | `false` | `true` / `false` | Zone | `true` : le rayon d'alerte est la distance du premier cercle (`[rings] first_km`). `false` : `radius_km` (distance indépendante). |
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

### 8.10 Autres sections

Toute autre clé ou section présente dans `config.ini` apparaît dans webadmin sous « Autres réglages », en champs texte, et reste modifiable.

### 8.11 Exemple complet

```ini
[general]
language = fr

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
plane_color_panel = #ff4646
plane_color_known = #ffd250
plane_color_unknown = #ffaa5a
width = 1280
height = 720

[panel]
width = 480
rotate_seconds = 12
corner_top_left = true
corner_top_right = true
corner_bottom_left = true
corner_bottom_right = false

[label]
order = model,registration,callsign,airline,route,altitude,speed
show_registration = true
model_bold = true
model_size = large

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
- Chaque avion a une étiquette dont le contenu, l'ordre et la mise en forme (taille, gras, italique) se règlent dans Réglages, Étiquettes des avions (8.7). Par défaut : modèle, compagnie, trajet (origine → destination) et altitude · vitesse ; l'immatriculation et l'indicatif de vol sont disponibles en option. Tant que les détails ne sont pas arrivés, elle affiche le code du type (et l'immatriculation ou l'indicatif s'ils sont activés). Le trajet est omis si l'origine et la destination sont inconnues (pas de plan de vol déclaré). Si une seule est connue, l'autre apparaît sous la forme `?`.
- Les étiquettes sont placées pour éviter de se recouvrir et de sortir de l'écran.
- La ligne d'état en bas à gauche indique le nombre d'avions en vol, au-dessus de la limite d'altitude, au sol, les erreurs réseau et la mention « données anciennes » si les mises à jour tardent. À droite de la même ligne, les crédits « © OpenStreetMap contributors · © CARTO · Flightradar24 » sont toujours affichés (ils figurent aussi dans la page « Crédits » de webadmin, accessible par le lien en haut de l'interface) : l'attribution exigée par OpenStreetMap et CARTO doit rester visible. Voir [CREDITS.md](../CREDITS.md).

### 9.2 Panneau photo

- Un panneau avec la photo, puis le texte (par défaut le modèle, l'immatriculation, la compagnie, le trajet, l'altitude, la vitesse et le crédit du photographe ; contenu, ordre et style réglables dans Réglages, Panneau photo, onglet « Contenu du texte », 8.6) s'affiche pour un avion à la fois, en alternance toutes les `rotate_seconds` entre les avions qui ont une photo.
- L'avion présenté est surligné en rouge sur la carte.
- Le panneau se place dans le coin de l'écran qui gêne le moins les avions affichés, parmi les angles autorisés dans Réglages, Panneau photo (8.6). Un angle décoché n'est jamais utilisé.
- Les photos et détails viennent de Flightradar24 ; le crédit du photographe est visible dans l'image et répété (« © nom / JetPhotos ») en petit sous les informations du panneau, sauf si l'élément « Crédit du photographe » est masqué dans Réglages, Panneau photo, onglet « Contenu du texte » (8.6). Si une photo manque ou ne se charge pas, l'avion est ignoré en mode normal.

### 9.3 Avions au sol

La liste en bas à droite (voir `[ground]`) affiche indicatif, compagnie, modèle et trajet, triés par vitesse décroissante. Un avion qui disparaît des données sous `landed_alt_ft` est conservé `landed_keep_minutes` comme « posé ».

### 9.4 Alerte de proximité

Quand un avion en vol entre dans le cercle d'alerte (`[alert] radius_km`) et respecte la plage d'altitude :

- un carillon de trois notes retentit (généré par le programme, aucun fichier son) ;
- l'intérieur du cercle se teinte en rouge transparent avec un clignotement lent, et le cercle est entouré d'un cadre rouge, tant qu'un avion est dedans ;
- le panneau photo ne montre que les avions présents dans le cercle (en alternance s'il y en a plusieurs), avec une ligne rouge « ALERTE · à X.X km de la maison ». Si la photo manque, le panneau s'affiche avec un cadre « Photo indisponible » ;
- dès que le cercle est vide, l'affichage revient au fonctionnement normal.

La distance est mesurée au sol, avec une marge de sortie de 10 % du rayon pour éviter les alertes à répétition. Un avion déjà en alerte garde une marge de 10 % sur les bornes d'altitude. Le son n'est joué qu'à l'entrée d'un avion, jamais deux fois en parallèle.

**Au lancement du programme** : un avion déjà présent dans la zone déclenche une vraie alerte, comme à tout autre moment. Pour tester le son et la teinte sans avion, deux options indépendantes existent (section 8.9) : « Son au lancement du programme » (un carillon) et « Simuler une alerte au démarrage » (teinte rouge et carillon). Il n'y a jamais deux carillons à la fois.

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
| `cache/*.jpg` | Photos téléchargées. | Nettoyées après 3 jours au démarrage, ou selon un quota avec le nettoyage automatique ; effaçables depuis webadmin (Réglages, Stockage et photos). |
| `cache/history.json` | Historique des avions vus (page « Avions vus » de webadmin). | Les 1000 derniers vols. |
| `cache/runtime.json` | État du son (coupé, volume, test). | Persistant. |
| `/dev/shm/flightdisplay-fps.json` | Images par seconde réellement affichées, publiées toutes les 2 secondes pour webadmin. En mémoire : aucune écriture sur la carte SD (`cache/fps.json` si `/dev/shm` n'existe pas). | Perdu au redémarrage. |
| `cache/update.json` | État et journal de la dernière mise à jour depuis webadmin. | Persistant. |

### 9.8 Types d'avion inconnus

Quand un type d'avion n'a pas d'icône dédiée, une forme monocouloir est utilisée et le journal indique `type inconnu (icone par defaut) : XXXX`. Pour lui associer la bonne forme, utilisez webadmin, Réglages, « Types d'avion » : les types détectés dans les logs sont proposés, avec un champ pour ajouter une règle et l'éditeur du fichier `types_extra.txt`. Les changements s'enregistrent avec le bouton en bas de page (« Enregistrer et relancer le programme ») : le fichier est vérifié, puis le programme est relancé pour les prendre en compte.

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
| `WEBADMIN_INI` | Chemin alternatif du fichier de réglages lu par webadmin (par défaut `config.ini`). |

---

## 10. Référence de webadmin

### 10.1 Les onglets

**Pilotage** (page d'accueil)

- Huit tuiles de supervision, sur deux rangées de quatre sur ordinateur (quatre colonnes) et sur deux colonnes sur téléphone. La première rangée donne l'état, la seconde les mesures sous forme d'anneaux de progression :
  - Programme : actif ou arrêté. Quand il est actif, le nombre d'images par seconde réellement affichées (moyenne sur 2 secondes) est indiqué sous le statut, avec la cible réglée dans `[display] fps`. Une valeur nettement plus basse que la cible signale un Pi Zero surchargé. Le programme publie cette mesure dans `/dev/shm/flightdisplay-fps.json` (mémoire, pas la carte SD ; `cache/fps.json` si `/dev/shm` n'existe pas).
  - Écran : allumé ou en veille.
  - MQTT : connecté (vert), déconnecté ou refusé (rouge), désactivé (neutre).
  - Temps : heure locale du Raspberry Pi (à la seconde), date et fuseau horaire, durée de fonctionnement et nom d'hôte. C'est l'heure utilisée par le planning de l'écran : si elle est fausse, voir 3.4.
  - Température : anneau gradué de 0 à 85 °C (limite du SoC fixée par Raspberry Pi pour tous les modèles). Orange 10 °C avant le seuil de ralentissement, rouge à partir du seuil. Le seuil dépend du modèle, détecté automatiquement (`/proc/device-tree/model`), d'après la documentation de Raspberry Pi : **80 °C** pour les Pi Zero, Zero 2 W, Pi 4, Pi 5 et les autres modèles (le micrologiciel ralentit les cœurs Arm entre 80 et 85 °C, puis aussi le GPU au-delà de 85 °C) ; **60 °C** pour les Pi 3 B+, 3 A+ et Compute Module 3+ (limite douce par défaut, avec réduction de fréquence). Raspberry Pi ne publie pas de valeur propre au Pi Zero : la valeur générale de 80 °C s'applique. Le survol de la tuile donne le modèle et les limites.
  - Utilisation CPU : anneau de 0 à 100 % mesuré toutes les 2 secondes (orange au-dessus de 85 %, rouge au-dessus de 95 %), avec à côté la charge moyenne du système sur 1 et 5 minutes. La charge moyenne n'est pas un pourcentage : sur le Pi Zero, qui n'a qu'un seul cœur, 1.00 correspond déjà à un processeur saturé.
  - Mémoire : anneau avec le pourcentage utilisé et les Mo (orange au-dessus de 80 %, rouge au-dessus de 90 %).
  - Disque : anneau avec le pourcentage utilisé et l'espace libre (le survol donne le total). L'anneau passe en orange 10 points avant le seuil d'alerte et en rouge au seuil, avec un cadre coloré (voir « Stockage et photos »).
  Rafraîchies toutes les 4 secondes. L'en-tête de la page n'affiche que des pastilles d'état : « son coupé », « carte en construction », « mise à jour en cours », « mise à jour disponible » ou « disque rempli à X % » (orange 10 points avant le seuil, rouge au seuil ; un clic ouvre « Stockage et photos »).
- Commandes à bascule, comme dans Réglages d'iOS ou Home Assistant :
  - Programme Flight Display : démarre ou arrête le service. C'est le seul moyen d'arrêter le programme. Quand l'écran est en veille, le programme continue de tourner : la tuile « Programme » du haut de la page affiche « image en pause (écran en veille) » à la place des images par seconde, et la ligne de l'interrupteur « En fonctionnement, image en pause ».
  - Écran : veille et réveil. La veille n'arrête pas le programme : il suit toujours les avions (historique) mais ne rafraîchit plus l'image (voir 6.2).
  - Planning de l'écran (affiché seulement quand un planning est actif) : prochaine action programmée, avec l'heure et le temps restant (par exemple « Prochaine action : extinction à 23:00 (dans 4 h 12 min) »). Le bouton « Modifier » ouvre le calendrier.
  - Son des alertes : coupe ou réactive le son (désactivé et grisé si `sound = false` dans `config.ini`).
- Curseur de volume (0 à 100 %), appliqué en direct à la prochaine alerte.
- Bouton « Tester le son » (désactivé tant que le son est coupé). L'enregistrement dans Réglages relance le programme si besoin.
- Les interrupteurs « Programme Flight Display » et « Écran » agissent tout de suite, sans demande de confirmation.
- **Mode hors ligne** (toutes les pages) : quand le Pi ne répond plus (redémarrage, coupure du réseau), la page masque tout sauf la barre de titre et affiche « Raspberry Pi injoignable » avec un anneau jaune qui se vide en 10 secondes ; à chaque fin de compte à rebours elle tente de se reconnecter. Dès que le Pi répond, la page revient sur l'onglet (et la catégorie de Réglages) où vous étiez ; si webadmin a redémarré, elle se recharge pour charger la version à jour. Le mode hors ligne ne s'active pas pendant une mise à jour ni un redémarrage de webadmin demandé depuis la page, qui ont leur propre suivi.
- Alimentation : redémarrer ou éteindre le Pi, avec confirmation. Après une extinction, il faut débrancher puis rebrancher l'alimentation.

**Avions vus** (entre Pilotage et Réglages)

- L'historique des avions qui ont survolé la zone, en cartes avec leur photo : modèle, compagnie, trajet (ville de départ → ville d'arrivée), immatriculation et « il y a X » ; tout ce que montre le panneau de l'écran, sauf l'altitude et la vitesse.
- Des pastilles sur les photos : « Alerte » (l'avion a déclenché l'alerte, enregistrée par le programme au moment où il entre dans la zone), « 1re fois » (appareil jamais vu auparavant), « Type rare » (modèle jamais vu avant), un petit nombre gris « ×N » (même immatriculation déjà vue N fois, dès la 2e fois : il remplace alors « 1re fois »).
- En haut : quatre compteurs (avions vus, appareils différents, compagnies, dernières 24 h) et un « Palmarès » repliable (compagnies et modèles les plus vus, appareils habitués).
- Deux modes d'affichage : **Cartes** (grille de photos) ou **Liste** (une ligne par avion : vignette, modèle avec la compagnie dessous, trajet avec les codes aéroport dessous, immatriculation avec l'indicatif dessous, heure, pastilles). Le choix est mémorisé dans le navigateur.
- Une **colonne de navigation verticale à gauche** (un bouton « Filtres » sur téléphone) : « Regrouper par » **Constructeur** (Airbus, Boeing, ATR…, puis la famille : tous les A320-251N, A320-232, A320neo sont réunis sous « A320 », tous les 737 sous « 737 ») ou par **Compagnie**, avec le nombre d'avions de chaque entrée, et le filtre « **Avec alerte sonore** » qui ne garde que les avions ayant déclenché l'alerte en entrant dans la zone d'alerte. Un fil d'Ariane au-dessus des résultats (« Tous les avions › Airbus › A320 ») permet de remonter d'un niveau.
- Recherche (modèle, immatriculation, indicatif, compagnie, ville, code aéroport), période (aujourd'hui, 7 jours, tout) et tri (récents ou habitués).
- **Pagination** comme sur un forum : nombre d'avions par page réglable (12, 24, 48, 96 ou 200), puis « Page 3 sur 12 ‹ 1 2 3 … 11 12 › » en haut et en bas de la liste.
- Un clic sur une carte ouvre la fiche : grande photo avec son crédit, immatriculation, indicatif, type ICAO, constructeur, trajet avec codes aéroport, premier et dernier passage, nombre de passages. Le petit bouton « tableau » à côté du nombre de passages déplie le **tableau des passages** de cet appareil vus par le programme (date et heure, durée vue, indicatif, trajet, alerte). Deux boutons ouvrent JetPhotos et l'« Historique Flightradar24 » de l'immatriculation. Les touches ← → passent d'un avion à l'autre ; la fiche se ferme avec ✕, Échap ou un clic à côté.
- L'historique est tenu par le programme d'affichage dans `cache/history.json` (les 1000 derniers vols, écrit 30 secondes après l'arrivée d'un nouvel avion) ; la page les montre tous. Si une photo a été supprimée du cache (nettoyage), webadmin la retélécharge au besoin.

**Réglages**

Sur ordinateur, un menu à gauche liste les catégories ; sur téléphone, il devient une barre de boutons défilante en haut. Les catégories sont :

| Menu | Catégorie | Fichier | Contenu |
|---|---|---|---|
| Général | Langue | config.ini | Langue de l'interface et de l'écran (8.1). |
| Programme | Carte et position | config.ini | Latitude, longitude, rayon, taille de la carte (largeur et hauteur), clé API CARTO (masquée), puis la section « Reconstruction de la carte » (voir plus bas). |
| | Flightradar24 | config.ini | Fréquence des requêtes, validité des positions. |
| | Affichage | config.ini | Plein écran, images par seconde, unités, filtre d'altitude, taille des icônes. |
| | Étiquettes des avions | config.ini | Éditeur : aperçu, ordre, affichage, taille, gras, italique, « même ligne » (8.7). |
| | Panneau photo | config.ini | Deux onglets : « Contenu du texte » (éditeur avec aperçu fixe : ordre, affichage, taille, gras, italique, « même ligne », crédit du photographe) et « Taille et angles » (largeur, rotation, angles autorisés). Voir 8.6. |
| | Avions au sol | config.ini | Liste, filtres, atterrissage. |
| | Alerte de proximité | config.ini | Zone, son et volume, teinte rouge, plage d'altitude, démarrage (son au lancement, simulation). |
| | Types d'avion | types_extra.txt | Éditeur des règles, types inconnus détectés. |
| | Autres réglages | config.ini | Toute clé hors schéma (affichée seulement s'il y en a), dans le groupe « Hors schéma (config.ini) ». |
| Webadmin | Serveur web | config.ini | Adresse, port, identifiant, mot de passe. L'avertissement « aucun mot de passe » s'affiche ici (et seulement ici) tant qu'aucun mot de passe n'est défini. |
| | Application et système | config.ini | Dossier, fichiers, service, Python de la carte, sudo, commandes, script et témoin de veille, arrêt de l'affichage pendant la carte. |
| | Mises à jour | config.ini | Canal, vérification automatique (`auto_check`), intervalle de 1 à 48 heures (`check_hours`) et installation automatique (`auto_install`). |
| | Planning de l'écran | config.ini | Activation du planning et calendrier hebdomadaire des plages d'allumage (voir plus bas). |
| | Sauvegarde | — | Export de la configuration dans un fichier et restauration (voir plus bas). |
| | Stockage et photos | config.ini | Occupation du disque, photos en cache, bouton « Vider le cache des photos », seuil d'alerte (voir plus bas). |
| Intégrations | MQTT / Home Assistant | config.ini | Connexion, sujets et découverte, avec état et bouton « Reconnecter ». |

Commandes de saisie : interrupteurs à bascule pour les valeurs oui/non, boutons segmentés pour les choix à deux ou trois valeurs (taille des étiquettes, langue), curseurs pour le volume et l'intensité du rouge, champs texte avec limites pour le reste. Les mots de passe et la clé CARTO sont masqués : le champ reste vide pour conserver la valeur actuelle, saisir une valeur la remplace, le bouton « Effacer » la supprime.

Enregistrement :

- Les champs modifiés sont entourés en jaune et un point signale les catégories modifiées. Une barre en bas indique le nombre de modifications et dit clairement ce qui se passera.
- Le bouton écrit les valeurs et les applique tout de suite, et son nom dit ce qui va se passer : « Enregistrer » quand l'effet est immédiat ; « Enregistrer et relancer le programme » quand le réglage concerne le programme d'affichage (quelques secondes sans image) ; « Enregistrer et redémarrer webadmin » pour l'adresse ou le port de webadmin (la page se rouvre toute seule) ; « Enregistrer et relancer le programme et webadmin » quand les deux sont concernés. « Annuler » abandonne les modifications non enregistrées.
- Les réglages de carte (position, rayon, taille, clé) déclenchent un bandeau qui propose de reconstruire la carte.
- Seules les lignes modifiées sont réécrites : les commentaires des fichiers sont conservés. Il n'y a pas de retour en arrière sur les réglages : une valeur enregistrée est appliquée tout de suite (pour garder un état de référence, utilisez l'export de la catégorie Sauvegarde).
- Les valeurs hors limites ou mal formées sont refusées avec un message, sans rien écrire.
- Un changement de langue recharge la page : webadmin passe tout de suite dans la nouvelle langue, le programme d'affichage la prend après sa relance.

Quand une modification est prise en compte :

| Réglages | Prise en compte |
|---|---|
| `config.ini` (toutes les catégories du menu Programme) | À l'enregistrement (« Enregistrer et relancer le programme »). La carte doit en plus être reconstruite pour les réglages de carte. |
| Types d'avion | À l'enregistrement (« Enregistrer et relancer le programme »), comme les autres réglages. |
| Langue | Immédiate pour webadmin (la page se recharge) ; à l'enregistrement (relance du programme) pour le texte affiché à l'écran. |
| Serveur web : adresse et port | À l'enregistrement (« Enregistrer et redémarrer webadmin ») : la page se rouvre toute seule, sur le nouveau port si besoin. |
| Serveur web : identifiant et mot de passe | Immédiate (le navigateur redemande les identifiants). |
| Application et système, Mises à jour, Planning de l'écran | Immédiate. |
| MQTT | Immédiate : webadmin se reconnecte au serveur. |

**Stockage et photos** (Réglages, Stockage et photos)

- **Disque** : une barre d'utilisation du disque qui contient l'application (la carte SD, même calcul que `df`) : pourcentage utilisé, espace utilisé, total et libre. La barre est verte, orange 10 points avant le seuil, rouge au seuil ; un trait blanc marque le seuil d'alerte et une partie bleue montre la place prise par les photos.
- **Photos JetPhotos en cache** : nombre de fichiers image (`cache/*.jpg`), volume qu'ils occupent, part que cela représente en pourcentage du disque et de l'espace utilisé, ancienneté de la plus ancienne photo, et volume des autres fichiers du cache (détails d'avions, état du son).
- **Vider le cache des photos** : supprime toutes les photos du cache après confirmation. Seules les photos sont effacées (pas les détails d'avions, pour ne pas multiplier les requêtes vers Flightradar24). Le programme d'affichage retélécharge une photo effacée quand elle est de nouveau nécessaire ; en attendant, le panneau affiche « Photo indisponible » pour cet avion.
- **Surveillance** : le réglage « Seuil d'alerte du disque (%) » (90 par défaut, de 50 à 99) déclenche l'alerte : pastille « disque rempli à X % » en en-tête (toutes les pages), tuile Mémoire colorée, bandeau dans cette page. L'alerte orange précède le seuil de 10 points.
- **Nettoyage automatique** : l'option « Nettoyer automatiquement le cache des photos » (`auto_clean`, désactivée par défaut) et le « Quota du cache des photos (Mo) » (`cache_max_mb`, 200 par défaut, de 20 à 100000) évitent d'avoir à vider le cache : webadmin vérifie le volume des photos une fois par jour (et à l'enregistrement de ces réglages) et, seulement quand il dépasse le quota, supprime les photos les **plus anciennes** (date du fichier) jusqu'à revenir à 80 % du quota ; les plus récentes sont gardées, et rien n'est fait en dessous du quota. Chaque nettoyage (automatique ou « Vider le cache ») est inscrit dans le « Journal du nettoyage » de cette page (les 30 derniers, 100 gardés dans `cache/cleanup.json`) et dans le journal du service.
- Sans nettoyage automatique, le programme supprime les photos de plus de 3 jours à chaque démarrage (9.7) ; avec, il ne le fait plus et laisse webadmin gérer le quota.

**Sauvegarde** (Réglages, Sauvegarde)

- **Exporter** : le bouton « Télécharger la sauvegarde » produit un fichier `flightdisplay-backup-<nom-du-pi>-<date>.zip` contenant `config.ini` (tous les réglages du programme et de webadmin), `types_extra.txt` (types d'avion), l'état du son, la carte déjà construite (`background.png` et `map_meta.json`, pour ne pas avoir à la reconstruire) et un petit fichier d'information. Les photos n'y sont pas.
- **Secrets** : l'interrupteur « Inclure les mots de passe et la clé CARTO » (activé par défaut) décide si les secrets (clé CARTO, mot de passe de webadmin, mot de passe MQTT) sont dans le fichier. Avec les secrets, la restauration retrouve tout ; **le fichier est alors sensible** : ne le partagez pas. Sans secrets, il peut être partagé (par exemple pour un diagnostic). Un export avec secrets n'est possible que depuis l'interface (en-tête `X-Admin`), jamais par un simple lien.
- **Restaurer** : choisissez un fichier puis « Restaurer » (confirmation demandée). La configuration actuelle est remplacée. Une sauvegarde faite sans secrets conserve ceux de l'installation actuelle. Le fichier est vérifié avant tout changement (format, contenu autorisé, `config.ini` lisible, règles de types valides) : un fichier invalide est refusé sans rien modifier. Webadmin propose ensuite de relancer le programme (comme après un enregistrement) ; un changement de langue recharge la page.
- Cas typique, après une panne de carte SD : installer un Pi neuf (section 0, avec `--yes` si vous voulez), ouvrir webadmin, restaurer le fichier, relancer le programme, puis reconstruire la carte.

**Planning de l'écran** (Réglages, Planning de l'écran)

Allume et éteint l'écran tout seul selon un calendrier hebdomadaire, comme un agenda.

- L'interrupteur « Activer le planning » met le planning en marche. Le calendrier montre les sept jours (lundi à dimanche) sur 24 heures ; les plages **bleues** sont les heures où l'écran est allumé, tout le reste est éteint. Une barre rouge marque l'heure actuelle dans la colonne du jour.
- Sur le calendrier : faire glisser sur une journée trace une plage (par pas de 15 minutes) ; un simple clic en crée une d'une heure ; tirer le haut ou le bas d'une plage l'ajuste ; la déplacer avec la souris ou le doigt change son heure, ou son jour si on la glisse sur une autre colonne ; ✕ la supprime ; ⧉ en tête de colonne copie la journée sur toute la semaine. « Tous les jours 07:00-23:00 » et « Tout effacer » sont des raccourcis. Les plages qui se touchent ou se chevauchent sont fusionnées.
- Comme les autres réglages, les modifications sont enregistrées avec la barre du bas, puis prises en compte immédiatement (pas de relance).
- L'action s'exécute **aux heures programmées** : à chaque début de plage, webadmin allume l'écran (réveil, comme le bouton Écran de Pilotage) ; à chaque fin de plage, il le met en veille (le programme continue de tourner sans rafraîchir l'image, voir 6.2). Entre deux heures programmées, vous pouvez allumer ou éteindre l'écran à la main : le planning ne le corrige pas et reprend à la prochaine heure programmée. Un jour sans plage est un jour entièrement éteint.
- Au moment où le planning est enregistré, l'écran est aligné tout de suite sur l'état voulu à cette heure. Au redémarrage de webadmin, rien n'est forcé.
- La page Pilotage affiche la prochaine action (allumage ou extinction, heure et temps restant) tant que le planning est actif.
- Le planning suit l'**heure du Pi** (fuseau horaire du système, voir 3.4). Il s'exécute dans webadmin : il ne fonctionne que tant que webadmin tourne, et utilise le script `flight-screen` via sudo comme le bouton Écran. Une action est reportée si une reconstruction de carte ou une mise à jour est en cours. En cas d'échec de la commande, le message est affiché sous la prochaine action.
- Dans `config.ini`, section `[schedule]` : `enabled` et une ligne par jour (`mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`) du type `mon = 07:00-09:30,18:00-24:00` (heures `HH:MM`, de `00:00` à `24:00`).

**Choix de la position et du rayon** (Réglages, Carte et position, en haut de la page)
- Une carte OpenStreetMap (assombrie pour que le cadre jaune ressorte) permet de cliquer ou de glisser le repère pour placer la position, ou de chercher une adresse (recherche Nominatim, lancée seulement quand vous la demandez). La latitude et la longitude des champs plus bas se mettent à jour.
- Sous la carte, une ligne donne la zone affichée (par exemple « 142,2 km × 80 km, ratio 16:9, 74,1 m par pixel »). Le curseur « Taille de la zone » règle `radius_km`. Le rectangle jaune montre la zone réellement affichée (hauteur = 2 × rayon, largeur dans le ratio « Largeur / Hauteur » de la taille de la carte).
- Quand « Afficher les cercles de distance » est coché, trois commandes s'ajoutent sous le curseur « Taille de la zone », dans cet ordre : deux boutons − et + pour le nombre de cercles (`count`), un curseur « 1er cercle » (`first_km`) et un curseur « Écartement » (`step_km`).
- Sous la carte, un aperçu au même ratio que l'écran montre la zone avec un fond OpenStreetMap assombri (le vrai fond est celui de CARTO, construit à la reconstruction).
- Les valeurs sont des modifications en attente : « Enregistrer », puis reconstruire la carte. La carte demande l'accès à internet depuis le navigateur (Leaflet est chargé depuis cdnjs) ; sans cela, les champs restent utilisables à la main.

**Reconstruction de la carte** (Réglages, Carte et position, en bas de la page ; un bandeau y renvoie quand un réglage de carte a changé)

- Bouton « Reconstruire la carte » : lance `build_map_vector.py` avec les réglages actuels, affiche sa sortie en direct, et propose « Annuler ».
- Interrupteur « Arrêter l'affichage pendant la construction » : libère la mémoire du Pi Zero pendant le calcul. À la fin, l'affichage est relancé pour charger la nouvelle carte (il reste sans image tant que l'écran est en veille). Si la construction échoue, l'affichage reprend avec l'ancienne carte.
- Une seule construction à la fois (et pas pendant une mise à jour du logiciel).

**Mises à jour**

- Une **carte résumé** en haut : la version installée en grand, une pastille « à jour » (ou « vérification impossible », « non vérifié »), la date, le dernier commit et l'heure de la dernière vérification. Quand une version plus récente existe, la carte montre `v1.1.0 → v1.2.0` avec le nombre de nouveautés, et le bouton « Mettre à jour » passe au premier plan. Une vérification se lance seule à l'ouverture de l'onglet quand il n'y en a pas encore.
- « Vérifier les mises à jour » interroge GitHub ; « Mettre à jour » lance la mise à jour immédiatement, sans confirmation.
- **Pendant la mise à jour** : une carte compacte avec un anneau de progression (pourcentage au centre), les deux versions (« v1.2.0 → v1.3.0 »), le nom de l'étape en cours en grand (sept étapes : vérifications, téléchargement, application, bibliothèques, contrôle du code, relance de l'affichage, redémarrage de webadmin), puis « Étape 5 sur 7 », le temps écoulé et l'étape suivante, et un « Journal détaillé » replié que l'on déplie d'un clic. La page se recharge seule à la fin.
- **Relance de l'affichage** : le programme d'affichage n'est relancé que si la mise à jour modifie ses fichiers (`main.py`, `aircraft_types.py`, `i18n.py`, `requirements.txt`, ou un texte de `lang/` qui est affiché à l'écran : les textes réservés à webadmin ne comptent pas). Une mise à jour qui ne touche que webadmin, la documentation ou l'installeur ne l'interrompt pas (étape « non concerné »). Webadmin, lui, redémarre toujours.
- **Après la mise à jour**, une seule ligne résume la dernière opération (« ✓ Dernière mise à jour : v1.0.0 → v1.1.0, il y a 2 min »). Un clic sur « Détails » déplie la liste des étapes et le journal. En cas d'échec, la ligne devient rouge avec la cause et les détails s'ouvrent automatiquement.
- « Historique des versions » : changelog groupé par version. Chaque version (étiquette git `vX.Y.Z`) est un séparateur repliable, avec ses commits dessous du plus récent au plus ancien (version, commit, date, description). Les commits postérieurs à la dernière version sont regroupés sous « En développement » et numérotés à partir d'elle : `v1.5.2-1`, `v1.5.2-2`… (le numéro est le nombre de commits depuis la version publiée, le même que celui affiché en haut de l'onglet pour la version installée). La version la plus récente est dépliée, les autres repliées. Repères : « nouveau » (pas encore installé) et « installé ». Des avertissements signalent un fichier modifié localement, des commits locaux absents de GitHub ou un `install.sh` modifié. La procédure complète est décrite en 12.1.
- **Retour à la version précédente** : après une mise à jour (ou un retour), les versions quittées par les 8 dernières mises à jour sont des **versions de secours** : dans l'historique, la ligne du commit correspondant affiche un bouton « Revenir à cette version » (comme la pastille « installé » marque la version en cours), et l'en-tête du groupe porte la pastille « version de secours ». Le bouton restaure cette version (confirmation demandée) : mêmes étapes que la mise à jour sans téléchargement (réinstallation des bibliothèques si besoin, contrôle du code, relance de l'affichage et de webadmin, restauration automatique en cas d'échec). Après un retour, la version quittée redevient disponible comme mise à jour (« Mettre à jour »). Vos réglages ne sont pas touchés.
- **Canal** : « Canal de mise à jour » dans Réglages, Mises à jour : « Stable » (versions publiées, défaut) ou « Développement » (chaque commit). La carte résumé indique le canal ; sur le canal stable, un Pi qui exécute un commit plus récent que la dernière version affiche « N commits après vX.Y.Z ».
- Une puce verte « mise à jour disponible » apparaît dans l'en-tête, sur toutes les pages. Un clic sur la puce ouvre l'onglet Mises à jour ; en la survolant, une petite icône ⬆ apparaît (toujours visible sur écran tactile) : un clic dessus lance la mise à jour tout de suite, sans quitter la page en cours. La puce affiche alors « mise à jour en cours · X % », et la page se recharge à la fin. L'icône n'est proposée que si la mise à jour est possible (pas de fichier modifié localement, pas de conflit) ; en cas d'échec, un message s'affiche.

**Crédits**

Le petit lien « Crédits », en haut de la page à côté des pastilles d'état, ouvre une page dédiée : sources des cartes (OpenStreetMap, CARTO), des données de vol (Flightradar24, FlightRadarAPI), des photos (JetPhotos) et licences des bibliothèques, avec un lien vers `CREDITS.md` pour le détail. Le bouton « Retour » revient à Pilotage.

**Logs**

- Journal du service d'affichage : 100, 300 ou 1000 lignes, filtre texte, actualisation automatique (interrupteur) toutes les 3 secondes. Les erreurs sont en rouge, les avertissements en jaune.

### 10.2 Réglages de l'interface web

Ces options vivent dans `config.ini`, aux sections `[server]`, `[app]`, `[screen]`, `[build]`, `[update]` et `[mqtt]`, et se modifient dans Réglages, catégories « Serveur web », « Application et système » et « MQTT / Home Assistant ». Le fichier peut aussi s'éditer à la main (puis `sudo systemctl restart flightadmin`). L'installeur écrit ces sections avec les valeurs par défaut ci-dessous quand elles manquent.

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

[update]
channel = stable
auto_check = true
check_hours = 12
auto_install = false

[schedule]
enabled = false
mon =
tue =
wed =
thu =
fri =
sat =
sun =

[storage]
warn_percent = 90
auto_clean = false
cache_max_mb = 200

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
| `[build]` | `stop_display` | true | Valeur par défaut de l'interrupteur « Arrêter l'affichage pendant la construction » (reconstruction de la carte). |
| `[update]` | `channel` | `stable` | Canal de mise à jour : `stable` (seulement les versions publiées `vX.Y.Z`, recommandé) ou `latest` (dernier commit de la branche, développement). |
| | `auto_check` | true | Vérifie régulièrement si une nouvelle version existe sur GitHub (signalée par une puce dans l'en-tête). |
| | `check_hours` | 12 | Intervalle entre deux vérifications, de 1 à 48 heures (curseur dans Réglages, « Mises à jour »). Relu à chaque tour : un changement s'applique sans redémarrage. |
| | `auto_install` | false | Installe automatiquement chaque nouvelle version détectée, sans clic (nécessite `auto_check`). Par défaut désactivée : rien n'est installé sans votre accord. |
| `[schedule]` | `enabled` | false | Active le planning d'allumage et d'extinction de l'écran. |
| | `mon` à `sun` | vide | Plages d'allumage du jour (`HH:MM-HH:MM`, séparées par des virgules). Vide : écran éteint toute la journée quand le planning est actif. |
| `[storage]` | `warn_percent` | 90 | Seuil d'alerte d'occupation du disque, en % (50 à 99). Alerte orange 10 points avant. |
| | `auto_clean` | false | Nettoyage automatique du cache des photos : au-delà du quota, les plus anciennes sont supprimées. |
| | `cache_max_mb` | 200 | Quota du cache des photos, en Mo (20 à 100000). Le nettoyage revient à 80 % du quota. |
| `[mqtt]` | | | Voir la section 11. |

Ne sont modifiables que par la ligne de commande : les services systemd, le fichier sudoers, le contenu des scripts de veille et de garde (numéros de terminaux virtuels) et les variables d'environnement.

### 10.3 API HTTP

Toutes les routes exigent l'authentification si un mot de passe est défini. Les requêtes `POST` exigent en plus l'en-tête `X-Admin: 1` (protection contre les requêtes déclenchées depuis une autre page web) et un corps JSON. Les mots de passe et la clé CARTO ne sont jamais renvoyés par l'API : seul leur état (défini ou non) l'est.

| Route | Méthode | Corps | Rôle |
|---|---|---|---|
| `/` | GET | | Interface web. |
| `/api/status` | GET | | État : service, écran, utilisation CPU en pourcentage (`cpu`), charge moyenne (`load`), température, mémoire, durée de fonctionnement, son (coupé, volume, activé), construction en cours, MQTT (`mqtt`), images par seconde réelles et cible (`fps`, `fps_target`), disque (`disk` : total, libre, pourcentage, niveau), mise à jour disponible ou en cours (`update_available`, `update_running`). |
| `/api/settings` | GET | | Catégories, groupes, paramètres, valeurs et sauvegardes disponibles, textes dans la langue active. |
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
| `/api/backup` | GET | | Télécharge la sauvegarde (zip). `?secrets=1` inclut les secrets et exige l'en-tête `X-Admin: 1` ; `?secrets=0` les retire. |
| `/api/backup/restore` | POST | `{"data": "<zip en base64>"}` | Restaure une sauvegarde (jusqu'à 3 Mo). |
| `/api/storage` | GET | | Occupation du disque (total, utilisé, libre, pourcentage, niveau d'alerte) et du cache (nombre et volume des photos, autres fichiers). |
| `/api/storage/clear` | POST | `{}` | Supprime les photos du cache ; renvoie le nombre et le volume supprimés. |
| `/api/update` | GET | | État des mises à jour : dernière vérification (versions, nouveautés), progression, étapes et journal de la mise à jour en cours ou de la dernière. |
| `/api/update/check` | POST | `{}` | Interroge GitHub (`git fetch`) et renvoie l'état à jour. |
| `/api/update/start` | POST | `{}` | Lance la mise à jour en arrière-plan (suivi par `GET /api/update`). |
| `/api/update/rollback` | POST | `{}` | Revient à la version quittée par la dernière mise à jour. |
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
- `config.ini` (clé CARTO et mots de passe) reste en droits 600 (installeur et enregistrements depuis l'interface).
- Il n'y a pas de blocage après des erreurs de mot de passe, mais chaque essai raté est ralenti d'une seconde.

---

## 11. MQTT et Home Assistant

### 11.1 Mise en place

1. Le paquet `python3-paho-mqtt` est installé à l'étape 3.5 (ou par l'installeur automatique).
2. Dans webadmin : Réglages, Intégrations, « MQTT / Home Assistant ». Activer MQTT, renseigner le serveur, le port, l'identifiant et le mot de passe, puis enregistrer. La connexion est immédiate. (L'installeur automatique peut aussi renseigner ces valeurs au moment de l'installation.)
3. L'état de la connexion (connecté, déconnecté, refusé, paho manquant, serveur manquant) s'affiche dans une tuile de la page Pilotage et en haut de la catégorie MQTT. Le bouton « Reconnecter / republier » relance la connexion et la découverte.

Les mêmes réglages existent dans `config.ini`, section `[mqtt]`.

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
| Écran | interrupteur | `base/screen/state`, `base/screen/set` | ON rallume, OFF met en veille (le programme continue de tourner sans rafraîchir l'image). |
| Son des alertes | interrupteur | `base/sound/state`, `base/sound/set` | ON si le son n'est ni coupé ni désactivé dans `config.ini`. OFF coupe le son. |
| Volume des alertes | nombre 0-100 % (pas de 5) | `base/volume/state`, `base/volume/set` | Règle le volume en direct. |
| Température | capteur °C | `base/temperature/state` | Température du Pi, arrondie à 0,5 °C. |
| Avions en vol | capteur | `base/aircraft/state` | Nombre d'avions en vol affichés sur la carte. `unavailable` quand le programme est arrêté. |
| Avions au sol | capteur | `base/aircraft_ground/state` | Nombre d'avions dans la liste au sol. |
| Avions dans la zone d'alerte | capteur | `base/aircraft_zone/state` | Nombre d'avions dans le cercle d'alerte. |
| Alerte en cours | capteur binaire | `base/alert/state` | ON tant qu'au moins un avion est dans la zone d'alerte. |
| Programme actif | capteur binaire (running) | `base/program/state` | ON si le service d'affichage tourne. |
| Images par seconde | capteur (diagnostic) | `base/fps/state` | Cadence réellement affichée. |
| Utilisation CPU, Mémoire utilisée, Disque utilisé | capteurs % (diagnostic) | `base/cpu/state`, `base/memory/state`, `base/disk/state` | Mesures du Pi. |

Les noms des entités suivent la langue choisie dans webadmin (par exemple « Screen », « Alert sound », « Alert volume », « Temperature » en anglais), publiés à chaque (re)connexion.

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

**Depuis webadmin (recommandé).** Onglet **Mises à jour** :

1. Une carte en haut de l'onglet résume la situation : version installée (avec le canal suivi), état (à jour, nouvelle version disponible avec le nombre de nouveautés, ou vérification impossible), bouton « Mettre à jour vers X », heure de la dernière vérification et de la prochaine, et un lien vers les réglages automatiques. « Vérifier les mises à jour » compare votre version à celle de GitHub (branche suivie par l'installation, `main` par défaut) et liste les nouveautés. Une puce « mise à jour disponible » apparaît en haut de la page ; par défaut, webadmin vérifie seul toutes les 12 heures (Réglages, « Mises à jour » : options `auto_check` et `check_hours`, de 1 à 48 heures, section `[update]` de `config.ini`). Par défaut, rien n'est installé sans clic sur « Mettre à jour » ; l'option `auto_install` (« Installer automatiquement les mises à jour ») lance la mise à jour toute seule dès qu'une nouvelle version est détectée, avec le même retour automatique à la version précédente en cas d'échec. Une version dont l'installation automatique a échoué n'est pas retentée en boucle : l'installer alors à la main.
2. « Mettre à jour » enchaîne : vérifications (dépôt Git, espace disque, aucun fichier modifié localement), téléchargement, application (fast-forward uniquement), bibliothèques Python (seulement si `requirements.txt` ou les dépendances de `build_map_vector.py` ont changé), contrôle du code, relance de l'affichage, redémarrage de webadmin. La progression et le journal s'affichent en direct ; la page se recharge à la fin.
3. Si le code de la nouvelle version contient une erreur ou si l'affichage ne reste pas actif après la relance, la version précédente est restaurée automatiquement.

Limites : webadmin n'a pas les droits pour modifier les composants système (services systemd, droits sudo, script de veille, correctif HDMI). Si une version en change, un avertissement s'affiche (lorsque `install.sh` est modifié) : relancez alors l'installeur en conservant la configuration. La mise à jour est refusée si des fichiers suivis par Git ont été modifiés à la main, ou si l'installation n'est pas un dépôt Git.

**En ligne de commande**, avec une installation par Git ou par l'installeur automatique :

```
cd ~/flightdisplay
git pull
fd restart
sudo systemctl restart flightadmin
```

Vos réglages (`config.ini`) ne sont pas versionnés et restent intacts. Si la mise à jour modifie les scripts de veille ou les services, relancez l'installeur en conservant la configuration (section 0.6) : l'étape 9 les réinstalle, et il met aussi à jour les paquets.

Si `git pull` refuse de s'exécuter parce que des fichiers ont été modifiés à la main, voir ce qui diffère avec `git status`, puis écarter les modifications (`git checkout <fichier>`) ou les mettre de côté (`git stash`). `config.ini` n'est jamais concerné : il n'est pas suivi par Git.

Avec une installation par copie de fichiers : recopier tous les fichiers du projet (`main.py`, `webadmin.py`, `webadmin_mqtt.py`, `webadmin_update.py`, `i18n.py`, le dossier `lang`...) depuis l'ordinateur, puis `fd restart` et `sudo systemctl restart flightadmin`.

### 12.2 Publier une version (mainteneur)

Une version est une étiquette git annotée `vX.Y.Z` posée sur un commit, puis envoyée sur GitHub. L'historique de webadmin range les commits sous la version correspondante (celle du commit et des commits précédents, jusqu'à l'étiquette antérieure).

```
git tag -a v1.1.0 -m "Version 1.1.0"
git push origin v1.1.0
```

Les installations récupèrent les étiquettes à chaque vérification. Sur le canal **stable** (défaut, `[update] channel`), une mise à jour installe la dernière version étiquetée `vX.Y.Z` de la branche (les pré-versions comme `v1.3.0-rc1` et les commits non publiés sont ignorés) ; sur le canal **latest** (« Développement » dans Réglages, Mises à jour), elle installe le dernier commit de la branche, publié ou non. Pour qu'une version atteigne les utilisateurs du canal stable, il faut donc poser l'étiquette.

### 12.3 Ajouter une langue

Le français est la langue de référence : les textes du code en français servent de clés. Chaque langue est un fichier `lang/<code>.json` :

```json
{
 "_meta": {"name": "Deutsch"},
 "strings": {
  "Pilotage": "Steuerung",
  "{0} avion(s) en vol": "{0} Flugzeug(e) in der Luft"
 }
}
```

- Une clé contenant `{0}`, `{1}`... est un modèle : elle reconnaît les textes composés (« 3 au sol », « Latitude : minimum -90 ») et la traduction réutilise les mêmes emplacements, dans l'ordre voulu.
- Un texte absent ou vide reste en français : une traduction partielle fonctionne.
- Pour créer le fichier avec tous les textes à traduire : `python3 lang/check_lang.py --new de "Deutsch"`. Pour voir ce qu'il reste à traduire et vérifier les emplacements : `python3 lang/check_lang.py de`.
- Redémarrer webadmin (`sudo systemctl restart flightadmin`, ou une mise à jour) : la langue apparaît dans Réglages, Langue. Elle s'applique à webadmin tout de suite et au programme d'affichage après sa relance.
- Ne sont pas traduits : l'installeur (`install.sh`), les messages techniques du journal et les descriptions des commits. La documentation existe en français et en anglais (`docs/FLIGHT_DISPLAY_DOCUMENTATION.md` et `.en.md`).

Quand une nouvelle version du logiciel ajoute un texte, il apparaît en français tant que `lang/en.json` (et les autres fichiers) n'a pas la clé correspondante.

### 12.4 Sauvegarde

À conserver : `config.ini` (clé CARTO, mot de passe webadmin, MQTT), `types_extra.txt`, `cache/runtime.json`, et vos fichiers de langue personnels s'il y en a (`lang/<code>.json` non fournis par le projet). `background.png` et `map_meta.json` se régénèrent depuis `config.ini`.

```
cd ~/flightdisplay
tar czf ~/flightdisplay-backup.tgz config.ini types_extra.txt cache/runtime.json background.png map_meta.json
```

Cette sauvegarde contient des secrets : ne la partagez pas.

### 12.5 Mises à jour du système

```
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 12.6 Consulter les logs

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
| `pygame.error: EGL not initialized`, le service redémarre en boucle | Bibliothèques EGL absentes (fréquent sur Raspberry Pi OS Lite) : `sudo apt install -y libegl1 libegl-mesa0 libgles2`, puis `sudo systemctl restart flightdisplay`. Si l'erreur persiste, ajouter `libegl-dev`. Vérifier aussi que `/dev/dri/card0` existe. |
| « premiere image apres » jamais affiché | Le programme n'a pas pu ouvrir l'écran : relancer à la main (`./venv/bin/python main.py`) et lire l'erreur. |
| La carte ne se construit pas : erreur `NoOptionError` | La clé `carto_key` manque dans `config.ini`, section `[map]` : la renseigner (Réglages, Carte et position). |
| La carte ne se construit pas : erreur HTTP 401 ou 403 | Clé CARTO probablement invalide, expirée ou mal copiée : la ressaisir dans Réglages, Carte et position, puis reconstruire. |
| La carte ne se construit pas pour une autre raison | Lire la sortie dans la section « Reconstruction de la carte » (Réglages, Carte et position). Vérifier le chemin Python (Réglages, Application et système) et les dépendances du script (4.3). |
| « ATTENTION : la carte a ete generee pour d'autres coordonnees » | Reconstruire la carte (Réglages, Carte et position, « Reconstruire la carte »). |
| Erreur 429 dans les logs | Trop de requêtes : augmenter l'intervalle de requête et la pause entre les détails (Réglages, Flightradar24). La limitation est automatique mais temporaire. |
| « ATTENTION : horloge du systeme decalee par rapport a FR24 » | Horloge du Pi fausse : vérifier `timedatectl status` et la connexion Internet. |
| `type inconnu (icone par defaut) : XXXX` | Ajouter le type dans Réglages, Types d'avion. |
| Aucun avion affiché | Vérifier la latitude, la longitude, le rayon et l'altitude maximale suivie. La ligne d'état en bas à gauche donne le nombre d'avions suivis. |
| Utilisation CPU proche de 90 % | Normal par moments sur un Pi Zero. Baisser les images par seconde (Réglages, Affichage) ou reconstruire la carte en 1280×720 réduit directement la charge. |
| La fenêtre Windows ne change pas de mise en page quand on la redimensionne | Normal : l'image de la carte est mise à l'échelle. Pour une autre taille de travail, changer `width` et `height` et reconstruire la carte (8.5). |
| Pas de son | `aplay -l` doit lister une sortie. Vérifier que `SDL_AUDIODRIVER=dummy` n'est pas dans le service, que « Son » est activé dans Réglages et dans Pilotage (icône de haut-parleur barré à l'écran sinon), et lire `fd logs` pour `son indisponible`. |
| Un son retentit au lancement alors que « Son au lancement » et « Simuler une alerte » sont décochés | Le compteur de test de `cache/runtime.json` n'est pas mémorisé au chargement de `main.py` : il faut une ligne `rt_refresh(True)` au niveau du module (sans indentation, après la définition de `rt_refresh`). Sinon, un avion se trouvait déjà dans la zone d'alerte. |
| Le son ne se coupe pas à distance | Le programme et webadmin doivent tourner avec le même utilisateur, et `cache/runtime.json` doit être modifiable par lui. |
| La page webadmin ne s'ouvre pas | `sudo systemctl status flightadmin` et `journalctl -u flightadmin -n 50`. |
| Après un changement de port, la page ne revient pas | Ouvrir `http://flightradarpi.local:<nouveau port>`. En cas d'erreur de réglage : éditer `config.ini` en SSH (section `[server]`) puis `sudo systemctl restart flightadmin`. |
| Mot de passe webadmin perdu | Éditer `config.ini` en SSH (section `[server]`, ligne `password =`), puis `sudo systemctl restart flightadmin`. |
| « sudo: a password is required » | `/etc/sudoers.d/flightadmin` manque ou le chemin de `systemctl` diffère : relancer l'installeur en conservant la configuration (étape 9). |
| Logs vides dans webadmin | L'utilisateur doit pouvoir lire le journal (groupe `systemd-journal`, ajouté par le service). Le journal est en mémoire par défaut : il est vidé à chaque redémarrage du Pi. |
| La veille ne coupe pas le signal (`dpms` reste `On`) | Le script de veille n'est pas la version à framebuffer (6.2) : `grep -c "fb0/blank" /usr/local/bin/flight-screen` doit renvoyer au moins `1`. Relancer l'installeur en conservant la configuration (étape 9) pour le réinstaller. |
| L'écran se rallume seul pendant la veille | La garde le remet en veille en moins de 20 secondes. Lire `journalctl -t flight-screen-guard` pour les heures, puis suivre la démarche de 6.2 (correctif HDMI, détection d'entrée du moniteur, commande de réveil, redémarrage, CEC). |
| La garde recoupe l'écran en boucle toutes les 20 secondes | Ancienne version de la garde (basée sur `setterm`) : relancer l'installeur (étape 9). |
| Après la mise à jour, ma veille personnalisée a disparu | L'étape 9 de l'installeur réécrit `flight-screen` et `flight-screen-guard`. Conserver une copie de vos modifications. |
| L'écran se rallume seulement quand je l'éteins depuis Home Assistant | Vérifier que la commande de l'entité n'est pas publiée avec « retain » sur le serveur MQTT (11.3), et lire `journalctl -t sudo \| grep flight-screen` pour voir qui a lancé le réveil. |
| Le moniteur ne s'éteint pas en veille | Vérifier `cat /sys/class/drm/card*-HDMI-A-*/dpms` : `Off` après la veille. Sinon essayer le DDC/CI (6.2). |
| Les tuiles de Pilotage sont sur deux colonnes | Sur ordinateur, les quatre colonnes s'appliquent à partir de 860 px de large ; en dessous, les tuiles passent sur deux colonnes. |
| Le planning n'allume ou n'éteint pas l'écran | Vérifier que « Activer le planning » est coché et que le calendrier contient des plages. Contrôler l'heure du Pi (tuile « Temps », 3.4) : le planning suit son fuseau horaire. L'action n'a lieu qu'aux heures programmées (une extinction manuelle en cours de plage n'est pas corrigée). Un message d'erreur sous « Prochaine action » indique si la commande `flight-screen` a échoué (droits sudo : étape 9 de l'installeur). Le planning s'arrête avec webadmin (`sudo systemctl status flightadmin`). |
| MQTT : « paho manquant » | `sudo apt install python3-paho-mqtt` puis `sudo systemctl restart flightadmin`. |
| MQTT : « refuse » | Identifiants ou droits (ACL) du serveur MQTT. |
| Entités absentes dans Home Assistant | Vérifier l'intégration MQTT, `discovery_prefix`, le même serveur, puis « Reconnecter / republier ». |
| Mises à jour : « vérification impossible » | webadmin ne joint pas GitHub (Internet, DNS) ou l'installation n'est pas un dépôt Git : lire le message affiché dans l'onglet Mises à jour. |
| Mises à jour : « fichiers du logiciel modifiés localement » | Des fichiers suivis par Git diffèrent de GitHub (copie faite à la main, par exemple). Voir lesquels avec `git status`, puis `git checkout <fichier>` ou `git stash` (12.1). `config.ini` n'est jamais concerné. |
| Mises à jour : « retour à la version précédente » | La nouvelle version n'a pas passé le contrôle du code ou ne démarre pas. L'ancienne version fonctionne toujours ; le journal de la mise à jour donne la cause. |
| Après un changement de langue, l'écran reste dans l'ancienne langue | Le programme d'affichage lit la langue au démarrage : « Enregistrer » dans webadmin, ou `fd restart`. |
| Une langue ajoutée dans `lang/` n'apparaît pas | Le fichier doit s'appeler `<code>.json` (2 ou 3 lettres minuscules) et contenir un JSON valide ; redémarrer webadmin. Contrôle : `python3 lang/check_lang.py <code>` (12.3). |
| Aucune étiquette n'apparaît à côté des avions | Tous les éléments sont masqués dans Réglages, Étiquettes des avions (8.7). |
| Le panneau photo n'apparaît jamais dans un angle | Cet angle est décoché dans Réglages, Panneau photo (8.6). Si les quatre angles sont décochés, il n'y a aucune restriction. |
| La tuile Programme affiche moins d'images par seconde que la cible | Le Pi Zero ne tient pas la cadence : baisser `fps`, passer la carte en 1280×720, ou limiter le nombre d'avions (altitude maximale suivie). |
| Alerte « disque rempli à X % » | La carte SD approche de la saturation. Ouvrir Réglages, Stockage et photos : vider le cache des photos, puis chercher les gros fichiers (`du -h --max-depth=1 ~ \| sort -h`, journaux, anciennes sauvegardes). Voir aussi 6.3. |
| Mises à jour : aucune nouvelle version alors que des commits ont été poussés | Le canal est « Stable » : seules les versions étiquetées `vX.Y.Z` sont proposées (12.2). Passer au canal « Développement » (Réglages, Mises à jour) pour recevoir chaque commit. |
| Restauration : « fichier de sauvegarde invalide » | Le fichier doit être un zip produit par Réglages, Sauvegarde (contenant `config.ini`, éventuellement `types_extra.txt`, `runtime.json`, `manifest.json` et la carte `background.png` avec `map_meta.json`), non modifié, de moins de 1 Mo par fichier (8 Mo pour l'image de la carte, dont les dimensions doivent correspondre à `map_meta.json`). |
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
