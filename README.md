# Flight display

Affichage temps réel des avions autour de chez vous sur un Raspberry Pi Zero : carte vectorielle, fiches photo, alerte de proximité (son et teinte rouge), liste des avions au sol, et une interface web d'administration pour tout régler depuis un téléphone ou un ordinateur (réglages, carte, logs, son, veille d'écran, MQTT / Home Assistant).

<!-- Ajoutez ici une capture d'écran : ![Flight display](docs/capture.png) -->

## Fonctionnalités

- Carte vectorielle centrée sur votre domicile, avions orientés selon leur cap, étiquettes (modèle, compagnie, trajet, altitude, vitesse).
- Fiche photo de l'avion, liste des avions au sol.
- Alerte de proximité : carillon, teinte rouge clignotante, fiche prioritaire, avec plage d'altitude réglable.
- Webadmin : tuiles de supervision (température, CPU, mémoire, MQTT), interrupteurs (programme, écran, son), volume en direct, réglages complets, reconstruction de la carte, logs.
- Veille et réveil de l'écran, redémarrage et extinction du Pi à distance.
- Intégration Home Assistant par MQTT (écran, son, volume, température).

## Avertissement important

Ce projet n'est affilié ni à Flightradar24 ni à aucune compagnie. Les données de vol sont obtenues avec la bibliothèque non officielle [FlightRadarAPI](https://github.com/JeanExtreme002/FlightRadarAPI). Les conditions d'utilisation de Flightradar24 réservent l'accès automatisé à l'API officielle (payante) et limitent l'usage du service à un usage personnel et non commercial. Utilisez ce logiciel à titre personnel et éducatif, à vos propres risques, et consultez les [conditions de Flightradar24](https://www.flightradar24.com/terms-of-service). Ne l'utilisez pas pour des décisions liées à la sécurité des vols. Les photos appartiennent à leurs auteurs (JetPhotos) et ne sont pas redistribuées par ce dépôt ; les données cartographiques sont © OpenStreetMap contributors.

## Matériel

Raspberry Pi Zero W (ou Zero 2 W), carte microSD de 16 Go ou plus, écran HDMI. Pour le son : écran avec haut-parleurs ou carte son USB.

## Installation rapide

Sur un Raspberry Pi OS Lite (32 bits) déjà installé, connecté en SSH avec l'utilisateur `flightdisplay` :

```
sudo apt update
sudo apt install -y git python3-venv python3-pygame python3-requests fonts-dejavu-core alsa-utils kbd python3-paho-mqtt
git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay
cd ~/flightdisplay
python3 -m venv --system-site-packages venv
./venv/bin/pip install -r requirements.txt
cp config.ini.example config.ini
cp webadmin.ini.example webadmin.ini
nano config.ini
./venv/bin/python -u build_map_vector.py
```

Il reste à créer le service d'affichage (section 5 de la documentation), puis à installer webadmin :

```
sudo bash install_webadmin.sh
```

Le guide complet, de la carte SD vierge jusqu'au dépannage, est dans [FLIGHT_DISPLAY_DOCUMENTATION.md](FLIGHT_DISPLAY_DOCUMENTATION.md) (à l'étape 4.2, remplacez la copie de fichiers par le `git clone` ci-dessus).

## Mettre à jour

```
cd ~/flightdisplay
git pull
fd restart
sudo systemctl restart flightadmin
```

Vos réglages (`config.ini`, `webadmin.ini`) ne sont pas touchés : ils ne sont pas versionnés.

## Licence

Code sous licence MIT (voir [LICENSE](LICENSE)). Les bibliothèques utilisées (pygame, requests, FlightRadarAPI, paho-mqtt) ont leurs propres licences.
