# Crédits et licences · Credits and licenses

🇫🇷 Flight display s'appuie sur des données, des services et des bibliothèques de tiers. Cette page liste ce qu'ils exigent et comment le logiciel le respecte. 🇬🇧 Flight display relies on third-party data, services and libraries. This page lists what they require and how the software complies.

Le code de Flight display est sous licence MIT (voir [LICENSE](LICENSE)). Les données, photos et marques ci-dessous appartiennent à leurs propriétaires. · Flight display's own code is under the MIT license (see [LICENSE](LICENSE)). The data, photos and trademarks below belong to their owners.

## Données et services · Data and services

| Source | Utilisation · Use | Ce qui est exigé · What is required | Dans Flight display · In Flight display |
|---|---|---|---|
| **OpenStreetMap** | Données cartographiques (routes, eau, pistes), via le fond de carte CARTO · Map data (roads, water, runways), through the CARTO base map | Données ODbL : attribution « © OpenStreetMap contributors », avec lien vers [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright) · ODbL data: attribution "© OpenStreetMap contributors", linking to [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright) | Affichée en permanence en bas à droite de l'écran, et en pied de page de webadmin · Always shown at the bottom right of the screen, and in the webadmin footer |
| **CARTO** | Fond de carte vectoriel, téléchargé avec votre clé API personnelle à la construction de la carte · Vector base map, downloaded with your personal API key when the map is built | [Conditions du fond de carte](https://carto.com/legal/basemap-terms/) et [attributions](https://carto.com/attributions) : « © CARTO » visible ; clé personnelle ; usage non commercial gratuit dans la limite des quotas · [Base map terms](https://carto.com/legal/basemap-terms/) and [attributions](https://carto.com/attributions): "© CARTO" visible; personal key; free non-commercial use within the quotas | Attribution affichée avec celle d'OpenStreetMap ; la clé reste dans `config.ini` (non publié) · Attribution shown together with OpenStreetMap's; the key stays in `config.ini` (never published) |
| **Flightradar24** | Positions et détails des vols (bibliothèque non officielle FlightRadarAPI) · Flight positions and details (unofficial FlightRadarAPI library) | [Conditions d'utilisation](https://www.flightradar24.com/terms-of-service) : usage personnel et non commercial ; l'accès automatisé est réservé à l'API officielle payante · [Terms of service](https://www.flightradar24.com/terms-of-service): personal, non-commercial use; automated access is reserved to the paid official API | Source citée à l'écran ; avertissement dans le README · Source credited on screen; notice in the README |
| **JetPhotos** | Photos d'avions, fournies via Flightradar24 · Aircraft photos, provided through Flightradar24 | Les photos appartiennent à leurs photographes ; elles ne doivent pas être redistribuées · The photos belong to their photographers; they must not be redistributed | Le crédit du photographe est affiché sous chaque photo ; les photos restent dans le cache local (supprimées après 3 jours) et ne sont jamais publiées par ce dépôt · The photographer's credit is shown under each photo; photos stay in the local cache (deleted after 3 days) and are never published by this repository |
| **Nominatim** (OpenStreetMap) | Conversion de votre adresse en coordonnées, une seule fois, à l'installation · Converting your address to coordinates, once, at installation | [Politique d'usage](https://operations.osmfoundation.org/policies/nominatim/) : requête unique, identification de l'application · [Usage policy](https://operations.osmfoundation.org/policies/nominatim/): single request, application identified | L'installeur envoie une requête unique avec un User-Agent identifiant le projet · The installer sends a single request with a User-Agent identifying the project |

## Bibliothèques · Libraries

Aucune n'est redistribuée par ce dépôt : elles sont installées sur votre Pi (apt, pip). · None is redistributed by this repository: they are installed on your Pi (apt, pip).

| Bibliothèque · Library | Licence · License |
|---|---|
| [FlightRadarAPI](https://github.com/JeanExtreme002/FlightRadarAPI) (JeanExtreme002) | MIT |
| [pygame](https://www.pygame.org/) | LGPL 2.1 |
| [requests](https://requests.readthedocs.io/) | Apache 2.0 |
| [Pillow](https://python-pillow.org/) | MIT-CMU (HPND) |
| [paho-mqtt](https://github.com/eclipse/paho.mqtt.python) | EPL 2.0 ou BSD 3-Clause · EPL 2.0 or BSD 3-Clause |
| [DejaVu Fonts](https://dejavu-fonts.github.io/) | Licence libre dérivée de Bitstream Vera · Free license derived from Bitstream Vera |
| Python (bibliothèque standard · standard library) | PSF License |

## Marques · Trademarks

Flightradar24, JetPhotos, OpenStreetMap, CARTO, Raspberry Pi et Home Assistant sont des marques de leurs propriétaires respectifs. Ce projet n'est affilié à aucun d'eux. · Flightradar24, JetPhotos, OpenStreetMap, CARTO, Raspberry Pi and Home Assistant are trademarks of their respective owners. This project is not affiliated with any of them.

## Si vous réutilisez ou modifiez ce logiciel · If you reuse or modify this software

Conservez l'affichage des attributions (constante `CREDITS` de `main.py`, pied de page de webadmin) et le crédit du photographe. Pour un usage commercial, les conditions de CARTO, de Flightradar24 et de JetPhotos ne le permettent pas dans le cadre décrit ici : contactez-les. · Keep the attributions displayed (the `CREDITS` constant of `main.py`, the webadmin footer) and the photographer's credit. For commercial use, the terms of CARTO, Flightradar24 and JetPhotos do not allow it as described here: contact them.
