# Flight display

[🇫🇷 Français](README.md) · 🇬🇧 **English**

Real-time display of the aircraft flying around your home on a Raspberry Pi: vector map, photo cards, proximity alert (sound and red tint), a list of aircraft on the ground, and a web administration interface to set everything up from a phone or a computer (settings, map, logs, sound, screen sleep, MQTT / Home Assistant).

<!-- Add a screenshot here: ![Flight display](docs/capture.png) -->

## Features

- Vector map centered on your home, aircraft oriented along their heading, labels (model, airline, route, altitude, speed) that you can reorder and style.
- Photo card of the aircraft, list of aircraft on the ground.
- Proximity alert: chime, blinking red tint, priority card, with an adjustable altitude range.
- Webadmin: monitoring tiles (temperature, CPU, memory, MQTT, frames per second), switches (program, screen, sound), live volume, full settings, map rebuild, logs, and software updates straight from GitHub.
- Screen sleep and wake-up, remote restart and shutdown of the Pi.
- Multilingual: French and English, selectable in webadmin (Settings, Language), for the interface and for the on-screen text; other languages can be added with a simple file (`lang` folder).
- Home Assistant integration through MQTT (screen, sound, volume, temperature).

## Important notice

This project is not affiliated with Flightradar24 or with any airline. Flight data is obtained with the unofficial [FlightRadarAPI](https://github.com/JeanExtreme002/FlightRadarAPI) library. Flightradar24's terms of use reserve automated access to the official (paid) API and limit the use of the service to personal, non-commercial use. Use this software for personal and educational purposes, at your own risk, and read the [Flightradar24 terms](https://www.flightradar24.com/terms-of-service). Do not use it for flight-safety decisions. The photos belong to their authors (JetPhotos) and are not redistributed by this repository; map data is © OpenStreetMap contributors, base map © CARTO.

## What you need

- **Any Raspberry Pi**: Zero, Zero 2 W, 3, 4, 5 or Compute Module. The Zero is the cheapest; from the Pi 3 on, the display is smoother and the map builds much faster, but the settings do not change.
- A microSD card of 16 GB or more, and an HDMI screen. For sound: the screen's speakers, the headphone jack if your model has one, or a USB sound card (the Pi Zero has no jack).
- An Internet connection: 2.4 GHz Wi-Fi on the Zero and Zero 2 W (no 5 GHz), Wi-Fi or Ethernet on the other models.
- **A CARTO API key, to get before running the installation** (free, see below).

## Before you start: get a CARTO API key

**What it is for.** The background map (roads, water, airport runways) is drawn from the vector base map of [CARTO](https://carto.com/basemaps/), built on OpenStreetMap data. CARTO now requires an API key for any direct use of its base maps. In Flight display, the key is only used to build the background image (at installation, then each time the map is rebuilt): it is not used during everyday operation.

**How to get it (about one minute, free, no CARTO account).**

1. Open [carto.com/basemaps/apikey](https://carto.com/basemaps/apikey/) from your computer or phone.
2. Enter your e-mail address, describe your use honestly (personal, non-commercial) and accept the [terms](https://carto.com/legal/basemap-terms/).
3. The key arrives by e-mail within moments. Keep it at hand: the installer will ask for it.

**Good to know.**

- Free for personal or non-commercial use, up to 5 million tiles per month, all your keys combined. Building a map uses only a tiny part of that. Commercial use is free up to 1 million tiles per month, then paid.
- The key is personal: do not share it and do not reuse it for unrelated projects. Never publish it (the `config.ini` file, which contains it, is not versioned by Git).
- The attribution "© OpenStreetMap contributors, © CARTO" must remain visible: Flight display always shows it at the bottom right of the screen (and in the webadmin footer), do not remove it. The photographer's credit is visible inside the image and repeated under each photo (can be turned off in Settings, Photo panel).
- You can install without a key: everything is installed except the map, which you will build later.

**Where it is stored.** The installer writes it to `config.ini`, section `[map]`, key `carto_key` (file with 600 permissions). To change it later: webadmin, Settings, Map and position, "CARTO API key" field (hidden), then, at the bottom of the same page, "Rebuild the map".

**Lost or rejected key.** If the map build fails with an HTTP 401 or 403 error, the key is probably wrong or invalid: request a new one on the same page, replace it in webadmin, then rebuild the map.

## One-command installation

1. With Raspberry Pi Imager, install **Raspberry Pi OS Lite** on the SD card: 32-bit on the Zero and Zero 2 W, 64-bit possible on newer models. In the customization options, set the hostname, a user, the Wi-Fi and enable SSH.
2. Have your **CARTO API key** ready (previous section).
3. Connect to the Pi over SSH, then type:

```
bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh)
```

The installer asks all its questions up front, `sudo` password included (address or coordinates, CARTO API key, web interface password, optional MQTT, screen fix, final reboot). What you type stays visible, passwords included. It then installs everything needed while showing its progress on a single line, builds the map and starts the display and the web interface. At the end, a summary gives the interface address (`http://<pi-name>.local:8080`), the username and the password. The installer's prompts are currently in French only; once installed, the language can be switched to English in webadmin (Settings, Language).

Without `curl`: `sudo apt update && sudo apt install -y git && git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay && bash ~/flightdisplay/install.sh`.

Running the same command again later updates the software and keeps your configuration.

## Documentation

The full guide (manual installation, reference of all settings, webadmin, MQTT, troubleshooting) is in [docs/FLIGHT_DISPLAY_DOCUMENTATION.en.md](docs/FLIGHT_DISPLAY_DOCUMENTATION.en.md). It is also available in French: [documentation française](docs/FLIGHT_DISPLAY_DOCUMENTATION.md).

## Updating

The easiest way: web interface, **Updates** tab. "Check for updates" queries GitHub, "Update" downloads and installs the new version while showing the progress step by step (if anything goes wrong, the previous version is restored automatically). A dot on the tab shows that a new version is available.

Or on the command line:

```
cd ~/flightdisplay
git pull
fd restart
sudo systemctl restart flightadmin
```

or run the installer again. Your settings (`config.ini`, which also holds those of the web interface) are not touched: they are not versioned.

## License and credits

Code under the MIT license (see [LICENSE](LICENSE)). The libraries used (pygame, requests, FlightRadarAPI, paho-mqtt) have their own licenses. The third-party data, services and photos (OpenStreetMap, CARTO, Flightradar24, JetPhotos), their terms and how the software complies with them are detailed in [CREDITS.md](CREDITS.md).
