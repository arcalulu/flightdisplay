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

Ce projet n'est affilié ni à Flightradar24 ni à aucune compagnie. Les données de vol sont obtenues avec la bibliothèque non officielle [FlightRadarAPI](https://github.com/JeanExtreme002/FlightRadarAPI). Les conditions d'utilisation de Flightradar24 réservent l'accès automatisé à l'API officielle (payante) et limitent l'usage du service à un usage personnel et non commercial. Utilisez ce logiciel à titre personnel et éducatif, à vos propres risques, et consultez les [conditions de Flightradar24](https://www.flightradar24.com/terms-of-service). Ne l'utilisez pas pour des décisions liées à la sécurité des vols. Les photos appartiennent à leurs auteurs (JetPhotos) et ne sont pas redistribuées par ce dépôt ; les données cartographiques sont © OpenStreetMap contributors, fond de carte © CARTO.

## Ce qu'il vous faut

- Un Raspberry Pi Zero W (ou Zero 2 W), une carte microSD de 16 Go ou plus, un écran HDMI. Pour le son : un écran avec haut-parleurs ou une carte son USB.
- Un réseau Wi-Fi 2,4 GHz avec accès à Internet.
- **Une clé API CARTO, à obtenir avant de lancer l'installation** (gratuite, voir ci-dessous).

## Avant de commencer : obtenir une clé API CARTO

**À quoi elle sert.** La carte affichée en fond (routes, eau, pistes d'aéroport) est dessinée à partir du fond de carte vectoriel de [CARTO](https://carto.com/basemaps/), construit sur les données OpenStreetMap. CARTO exige désormais une clé API pour toute utilisation directe de ses fonds de carte. Dans Flight display, la clé ne sert qu'à construire l'image de fond (à l'installation, puis à chaque reconstruction de la carte) : elle n'est pas utilisée pendant le fonctionnement quotidien.

**Comment l'obtenir (environ une minute, gratuit, sans compte CARTO).**

1. Ouvrez [carto.com/basemaps/apikey](https://carto.com/basemaps/apikey/) depuis votre ordinateur ou votre téléphone.
2. Saisissez votre adresse e-mail, décrivez votre usage honnêtement (personnel, non commercial) et acceptez les [conditions](https://carto.com/legal/basemap-terms/).
3. La clé arrive par e-mail en quelques instants. Gardez-la sous la main : l'installeur vous la demandera.

**Ce qu'il faut savoir.**

- Gratuit pour un usage personnel ou non commercial, jusqu'à 5 millions de tuiles par mois, toutes vos clés confondues. La construction d'une carte n'en consomme qu'une infime partie. L'usage commercial est gratuit jusqu'à 1 million de tuiles par mois, puis payant.
- La clé est personnelle : ne la partagez pas et ne la réutilisez pas pour des projets sans rapport. Ne la publiez jamais (le fichier `config.ini`, qui la contient, n'est pas versionné par Git).
- L'attribution « © OpenStreetMap contributors, © CARTO » doit rester visible : Flight display l'affiche dans la ligne d'état en bas de l'écran, ne la retirez pas.
- Vous pouvez installer sans clé : tout est installé sauf la carte, que vous construirez plus tard.

**Où elle est enregistrée.** L'installeur l'écrit dans `config.ini`, section `[map]`, clé `carto_key` (fichier en droits 600). Pour la changer plus tard : webadmin, Réglages, Carte et position, champ « Clé API CARTO » (masqué), puis onglet Carte, « Reconstruire la carte ».

**Clé perdue ou refusée.** Si la construction de la carte échoue avec une erreur HTTP 401 ou 403, la clé est probablement incorrecte ou invalide : demandez-en une nouvelle sur la même page, remplacez-la dans webadmin, puis reconstruisez la carte.

## Installation en une commande

1. Avec Raspberry Pi Imager, installez **Raspberry Pi OS Lite (32-bit)** sur la carte SD. Dans la personnalisation, renseignez le nom d'hôte, un utilisateur, le Wi-Fi et activez SSH.
2. Munissez-vous de votre **clé API CARTO** (section précédente).
3. Connectez-vous au Pi en SSH, puis tapez :

```
bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh)
```

L'installeur pose quelques questions (adresse ou coordonnées, clé API CARTO, mot de passe de l'interface web, MQTT facultatif), installe tout le nécessaire en affichant sa progression, construit la carte, puis démarre l'affichage et l'interface web. À la fin, un résumé donne l'adresse de l'interface (`http://<nom-du-pi>.local:8080`) et le mot de passe.

Sans `curl` : `sudo apt update && sudo apt install -y git && git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay && bash ~/flightdisplay/install.sh`.

Relancer la même commande plus tard met à jour le logiciel et conserve votre configuration.

## Documentation

Le guide complet (installation manuelle, référence de tous les réglages, webadmin, MQTT, dépannage) est dans [docs/FLIGHT_DISPLAY_DOCUMENTATION.md](docs/FLIGHT_DISPLAY_DOCUMENTATION.md).

## Mettre à jour

```
cd ~/flightdisplay
git pull
fd restart
sudo systemctl restart flightadmin
```

ou relancer l'installeur. Vos réglages (`config.ini`, `webadmin.ini`) ne sont pas touchés : ils ne sont pas versionnés.

## Licence

Code sous licence MIT (voir [LICENSE](LICENSE)). Les bibliothèques utilisées (pygame, requests, FlightRadarAPI, paho-mqtt) ont leurs propres licences.
