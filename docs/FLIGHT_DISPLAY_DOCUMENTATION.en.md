# Flight display — unified documentation

[🇫🇷 Français](FLIGHT_DISPLAY_DOCUMENTATION.md) · 🇬🇧 **English**

Real-time display of the aircraft flying around your home on a Raspberry Pi Zero: vector map, photo cards, proximity alert (sound, red tint), a list of aircraft on the ground, and a web administration interface (webadmin) that lets you set everything up from a phone or a computer: settings, map, logs, sound, screen sleep, software updates, language, MQTT and Home Assistant. The interface and the screen are available in French and in English.

This documentation covers the one-command automatic installation, the complete manual installation from a blank SD card, all the necessary system changes, then the reference of every option of the software (`config.ini`), of webadmin (interface settings, API) and of MQTT.

## Contents

0. Quick start: automatic installation
1. Overview
2. Hardware and prerequisites
3. Setting up the Raspberry Pi (manual installation)
4. Installing Flight display
5. systemd services and the `fd` command
6. System settings (audio, screen, SD card, Wi-Fi)
7. Installing webadmin (manual)
8. `config.ini` reference
9. How the display works
10. webadmin reference (web interface settings in 10.2)
11. MQTT and Home Assistant
12. Maintenance
13. Troubleshooting
14. Uninstalling

---

## 0. Quick start: automatic installation

The `install.sh` installer does all the work of sections 3 to 7: it installs the packages, fetches the project, installs the map, creates the services and starts the display and webadmin. By default, it installs **by itself**, with a sample configuration (Bordeaux-Merignac airport) that you then adjust from webadmin; in manual mode (`--manual`), it first asks a few questions. This is the recommended method.

### 0.1 Before you start

1. With Raspberry Pi Imager, install Raspberry Pi OS Lite (32-bit) on the SD card (see 3.1). In the customization options, set the hostname, a user, the Wi-Fi and enable SSH.
2. For a manual installation, have ready: your address (or your coordinates), your CARTO API key (free, see 2 and the README), and if you wish the credentials of your MQTT server. The automatic installation needs nothing.
3. Connect to the Pi over SSH: `ssh <user>@<pi-name>.local`.

### 0.2 The command

```
bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh)
```

Without `curl`, or if you prefer to clone first:

```
sudo apt update && sudo apt install -y git
git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay
bash ~/flightdisplay/install.sh
```

Do not run the script with `sudo`: it uses your normal user and asks for the sudo password right at the start, before the countdown, so that the rest runs without intervention (nothing is asked if `sudo` works without a password, as with Raspberry Pi Imager). It works with any user name.

**Automatic installation (default).** When started, a 15-second countdown is displayed. Press a key (or Ctrl+C) to switch to the manual installation; otherwise the installation starts by itself, with no question at all:

- the configuration is that of `config.ini.example` (Bordeaux-Merignac airport, radius 30 km);
- the map is supplied: `defaults/background.png` and `defaults/map_meta.json` are copied to the root, with no CARTO key and no build. The aircraft type rules of `defaults/types_extra.txt` are copied too. Files already present are never overwritten;
- MQTT is disabled and **no webadmin password is set** (the installer reports it: set one in Settings, Web server);
- the screen sleep fix is applied, with no automatic reboot;
- the display program starts as soon as the installation ends; you then set your position (picker map in Settings, Map and position), the CARTO key, the style and the rest from webadmin;
- the language is the system's (French if the Pi is in French, English otherwise); `--lang fr` or `--lang en` forces it;
- without a terminal (installation started by a script), it starts immediately, and `sudo` must then work without a password;
- if a configuration already exists, it is kept: only the software is updated.

`--manual` starts the classic installation (the questions below); `--auto` starts the automatic installation without waiting for the 15 seconds.

### 0.3 The questions

These questions are only asked in a manual installation: with `--manual`, or if you interrupt the countdown of the automatic installation.

| Question | Detail |
|---|---|
| `sudo` password | Asked once, before the first step, so that the installation then runs unattended. |
| Position | Your address, converted into coordinates by the OpenStreetMap Nominatim service (the address is sent to it only once, the coordinates are rounded to about 11 m), or a manual entry of latitude and longitude. |
| Map radius | From 1 to 200 km, 20 by default. |
| Map resolution | 1920×1080, 1280×720 (recommended on the Pi Zero: lighter load) or a custom size. Written to `[display] width` and `height` in `config.ini`. |
| Nearby airport | 3-letter IATA code, optional. |
| CARTO API key | Visible input, so you can check the paste (the field stays hidden in webadmin). Written to `config.ini`, section `[map]`, key `carto_key`. Without a key, the map is not built (possible later from webadmin). |
| Webadmin password | At least 6 characters, with confirmation, or Enter to generate a random one (shown only once at the end). Visible input. |
| MQTT | Optional: server, port, username, password (visible input). |
| Screen sleep fix | Adds `vc4.force_hotplug=1` and `video=HDMI-A-1:D` to the boot options (see 3.6); a reboot is recommended. |
| Automatic reboot | If the screen fix is accepted: reboot the Pi by itself at the end (10 seconds, Ctrl+C to cancel), or have it offered as a command. |

All inputs stay visible, passwords included, so you can check what you type. A summary is shown before the start. All these questions, plus the `sudo` password, are asked **before** the first step: the installation then runs unattended.

### 0.4 The steps

| Step | Action |
|---|---|
| 1 | Update of the package list (`apt update`), with a progress bar. |
| 2 | Package installation: git, curl, Python, pygame, Pillow, requests, paho-mqtt, fonts, audio tools, kbd, EGL libraries (`libegl1`, `libegl-mesa0`, `libgles2`). |
| 3 | Fetching the project from GitHub (or updating it if it is already cloned). |
| 4 | Python environment (venv) and libraries (`requirements.txt`). |
| 5 | Dependencies of `build_map_vector.py`: the script is analyzed and the missing modules are installed. |
| 6 | Writing `config.ini` (permissions 600), web interface settings included. |
| 7 | Building the map (several minutes on a Pi Zero). |
| 8 | `flightdisplay` service, `fd` command, groups `video render input audio`. |
| 9 | webadmin: `flightadmin` service, limited sudo rights, `flight-screen` sleep script and its `flight-screen-guard` guard. |
| 10 | Screen sleep fix (if accepted). |
| 11 | Starting the services and testing webadmin. |

The Pi checks (system, hardware, memory, disk space, Internet, clock) come before step 1 and are not numbered.

For each step, the screen shows an animated indicator, the elapsed time, the last output line and, for downloads, a percentage. Each step fits on a single line that updates in place: nothing scrolls. A global bar shows the progress. The full detail is written to the log `~/flightdisplay-install.log`.

### 0.5 If something fails

- An essential step that fails stops the installer with a clear message, the last lines of the log and the file path. Fix the cause (network, disk space), then run the same command again: the installer resumes and keeps what is already done.
- If only the map cannot be built (missing or rejected key, script error), everything else is installed. webadmin works, and the map is built from webadmin (Settings, Map and position, "Rebuild the map") after the fix. The display program starts automatically as soon as a map exists, or with the "Flight Display program" switch in Control.
- **No sudo rights**: the installer checks right away that your user can use `sudo` (without a password, or as a member of the `sudo` group) and stops otherwise, before changing anything. The user created by Raspberry Pi Imager normally has these rights. Otherwise:
  - the simplest: re-flash the card with Raspberry Pi Imager, filling in the username and password in the customization;
  - from another administrator account: `sudo usermod -aG sudo <user>` and `echo '<user> ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/010_<user>` (then `sudo chmod 440` on that file), then log out and back in;
  - with no other account: on the `bootfs` partition of the card, add `init=/bin/bash` at the end of the `cmdline.txt` line, start the Pi, type `mount -o remount,rw /`, the two commands `usermod -aG sudo <user>` and `echo '<user> ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/010_<user>` followed by `chmod 440 /etc/sudoers.d/010_<user>` and `sync`, power off, then remove `init=/bin/bash` from `cmdline.txt`.
- Non-blocking warnings (clock, disk space, unrecognized hardware) are repeated in the final summary.

### 0.6 Running the installer again

If `config.ini` already exists, the installer offers to keep it: it then updates the software and the services without asking the questions again or rebuilding the map. If you answer no, it asks all the questions again and rewrites the files. In both cases, step 9 rewrites `/usr/local/bin/flight-screen` and `/usr/local/bin/flight-screen-guard` with the versions from the repository: any manual change to these two scripts is overwritten.

### 0.7 Options and variables

| Item | Effect |
|---|---|
| `--dry-run` | Simulation: the script goes through all the steps without installing anything. Useful to see what it is going to do. |
| `--help` | Shows the help. |
| `--manual`, `FD_MANUAL=1` | Classic installation: the questions are asked (0.3). |
| `--auto`, `FD_AUTO=1` | Automatic installation right away, without the countdown. |
| `FD_COUNTDOWN` | Duration of the automatic installation countdown, in seconds (15 by default, `0` = none). |
| `FD_DIR` | Installation folder (`~/flightdisplay` by default, or the script's folder if it is run from a clone). |
| `FD_REPO_URL`, `FD_BRANCH` | Repository and branch to clone. |
| `FD_LOG` | Log file (`~/flightdisplay-install.log` by default). |
| `NO_COLOR=1` | Disables colors. |
| `--lang fr\|en`, `FD_LANG` | Language of the installer, of webadmin and of the screen. Without an option: the system language in the automatic installation, a question at the start in the manual installation. Written to `[general] language`. |
| `--yes`, `--non-interactive`, `FD_YES=1` | No-questions mode (see below). |

**No-questions mode.** With `--yes`, the installer reads nothing from the keyboard: it takes its answers from environment variables and uses `sudo -n` (sudo must work without a password, which is the default on Raspberry Pi OS). Example:

```
FD_LAT=48.8566 FD_LON=2.3522 FD_RADIUS=20 FD_MAP_SIZE=1280x720 FD_CARTO_KEY=YOUR_KEY FD_LANG=en \
  bash <(curl -fsSL https://raw.githubusercontent.com/arcalulu/flightdisplay/main/install.sh) --yes
```

| Variable | Default | Role |
|---|---|---|
| `FD_ADDRESS` or `FD_LAT` and `FD_LON` | required for a first installation | Position (the address is converted to coordinates). |
| `FD_RADIUS` | 20 | Map radius in km (1 to 200). |
| `FD_MAP_SIZE` | `1280x720` | Map size (`1920x1080` possible). |
| `FD_AIRPORT` | empty | IATA code of a nearby airport. |
| `FD_CARTO_KEY` | empty | CARTO API key (without it, the map is built later from webadmin). |
| `FD_WEB_PASSWORD` | generated | webadmin password (6 characters minimum); if empty, a password is generated and shown at the end. |
| `FD_MQTT_HOST`, `FD_MQTT_PORT`, `FD_MQTT_USER`, `FD_MQTT_PASS` | empty (port 1883) | Optional MQTT server. |
| `FD_HDMI_FIX` | 1 | Screen sleep fix (3.6). |
| `FD_AUTO_REBOOT` | 0 | `1`: reboot at the end if the fix was applied. |
| `FD_KEEP` | 1 | If `config.ini` exists: `1` keeps it (software update only), `0` rewrites it. |

An invalid value stops the installer with a clear message before anything is installed.

### 0.8 At the end

The summary gives the webadmin address (`http://<pi-name>.local:8080` and by IP address), the username, the password (if it was generated, it is not shown again afterwards) and the useful commands. If the sleep fix was applied, the installer reboots the Pi (or tells you `sudo reboot`) depending on your answer to the automatic reboot question.

The webadmin password, the CARTO key and the MQTT credentials are stored in `config.ini`, with permissions 600. All settings are then changed from webadmin. The installer exists in French and in English (chosen at the start, or with `--lang`); the language of webadmin and of the screen, written to `config.ini`, is changed afterwards in Settings, Language (8.1).

---

## 1. Overview

### Components

| Item | Role |
|---|---|
| `main.py` | Display program (pygame, direct KMS/DRM output, no desktop environment). |
| `build_map_vector.py` | Generates the map `background.png` and `map_meta.json` from `config.ini` (position, radius, size, CARTO key). |
| `mapstyle.py` | Themes, layers and colors of the base map, shared by `build_map_vector.py` and webadmin ("Map style" page). |
| `config.ini` | All the settings: the program (including `[general]` for the language and `[label]` for the labels), plus the web interface sections `[server]`, `[app]`, `[screen]`, `[build]`, `[update]` and `[mqtt]`. Template: `config.ini.example`. |
| `types_extra.txt` | Optional: maps unknown aircraft types to an icon shape. |
| `webadmin.py` | Web administration server (Python standard library). |
| `webadmin_mqtt.py` | MQTT / Home Assistant bridge, loaded by webadmin. |
| `webadmin_update.py` | Updates from GitHub ("Updates" tab), loaded by webadmin. |
| `i18n.py` and the `lang/` folder | Translations (French, English) shared by the display program and webadmin. |
| `install.sh` | One-command automatic installer. |
| `/usr/local/bin/flight-screen` | Root script for screen sleep and wake-up (created by step 9 of `install.sh`). |
| `/usr/local/bin/flight-screen-guard` | Guard that puts the screen back to sleep if it wakes up by itself during a sleep (created by step 9 of `install.sh`). |
| `/usr/local/bin/fd` | Shortcut: `fd logs`, `fd restart`... |
| `cache/` | Aircraft details, photos, sound state (`runtime.json`), state of the last update (`update.json`). |

### Services

| systemd service | Program | User |
|---|---|---|
| `flightdisplay` | `main.py` | your user |
| `flightadmin` | `webadmin.py` | your user |
| `flight-screen-guard` | `flight-screen-guard` | root |

### Paths used in this document

| Item | Value |
|---|---|
| User | `flightdisplay` (any name works with the automatic installer) |
| Hostname | `flightradarpi` (reachable as `flightradarpi.local`) |
| Application folder | `/home/flightdisplay/flightdisplay` |
| Python environment | `/home/flightdisplay/flightdisplay/venv` |

Adapt these values if you choose others.

### What is set where

| Need | Where |
|---|---|
| All the settings of the program, of webadmin and of MQTT, the CARTO key | webadmin, Settings tab (section 10) |
| Unknown aircraft types | webadmin, Settings, Aircraft types |
| Sound (mute, volume), screen sleep, restart, power | webadmin, Control tab |
| Map rebuild | webadmin, Settings, Map and position ("Map rebuild" section, at the bottom of the page) |
| Language of the interface and of the screen | webadmin, Settings, Language (8.1) |
| Content, order and style of the aircraft labels | webadmin, Settings, Aircraft labels (8.7) |
| Software update, version history | webadmin, Updates tab (12.1) |
| Automatic screen on/off | webadmin, Settings, Screen schedule (10.1) |
| System installation items (services, sudoers, sleep scripts, `cmdline.txt`) | Automatic installer, or command line (sections 3 to 7) |

---

## 2. Hardware and prerequisites

- Raspberry Pi Zero W (512 MB of RAM). The Zero 2 W works too, with the same steps.
- microSD card of 16 GB or more, preferably high-endurance.
- 5 V power supply suited to the Pi.
- An HDMI screen and a mini-HDMI to HDMI cable or adapter.
- For sound: a screen with speakers or a headphone output (the sound goes out through HDMI), or a USB sound card with an OTG adapter. The Pi Zero has no jack.
- A 2.4 GHz Wi-Fi network with Internet access. The Pi Zero W does not support 5 GHz.
- A computer with Raspberry Pi Imager and an SSH client.
- A CARTO API key, needed to build the map (the script downloads the CARTO vector base map with this key). It is free for personal use and is requested at `https://carto.com/basemaps/apikey/`: see the README for the step by step.
- If you use Home Assistant: an MQTT server (for example Mosquitto) and its credentials.
- For the manual installation: the project files (`main.py`, `build_map_vector.py`, `config.ini.example`, `webadmin.py`, `webadmin_mqtt.py`, `webadmin_update.py`, `i18n.py`, the `lang` folder, `requirements.txt`), either with `git clone https://github.com/arcalulu/flightdisplay.git` or copied from a computer.

---

## 3. Setting up the Raspberry Pi (manual installation)

Sections 3 to 7 describe step by step what the automatic installer (section 0) does. Use them if you prefer to do everything by hand, to understand what is installed, or to troubleshoot.

### 3.1 Flashing the SD card

1. Install Raspberry Pi Imager on your computer.
2. Choose the device: Raspberry Pi Zero W (the Pi Zero without the W has no Wi-Fi and is not suitable).
3. Choose the system: Raspberry Pi OS (other), then Raspberry Pi OS Lite (32-bit). The Zero W has no 64-bit processor.
4. Choose the SD card.
5. In the customization (Edit Settings), set:
   - hostname: `flightradarpi`;
   - user: `flightdisplay` (lowercase) and a password;
   - Wi-Fi: network name, password, country (important for the Wi-Fi to be enabled);
   - locale: time zone `Europe/Paris`, suitable keyboard;
   - SSH: enabled, with a password or a public key.
6. Write the card, insert it in the Pi, plug in the screen then the power.

The first boot takes several minutes on a Zero.

### 3.2 Connecting over SSH

```
ssh flightdisplay@flightradarpi.local
```

If the name does not resolve, use the IP address shown in your router's interface.

### 3.3 Updating the system

```
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

### 3.4 Time zone and clock

The Pi's time must be accurate: the program compares the clock with the Flightradar24 timestamps and shows a warning in case of a gap.

```
sudo timedatectl set-timezone Europe/Paris
timedatectl status
```

The line `System clock synchronized: yes` must appear.

### 3.5 Required packages

```
sudo apt install -y git curl python3-venv python3-pygame python3-pil python3-requests fonts-dejavu-core alsa-utils kbd python3-paho-mqtt libegl1 libegl-mesa0 libgles2
```

| Package | Why |
|---|---|
| `git`, `curl` | Fetching the project and the installer. |
| `python3-venv` | Creating the Python environment. |
| `python3-pygame` | Display and sound. Installing it with apt also brings the required SDL libraries. |
| `python3-pil` | Pillow, the image library used by `build_map_vector.py` to build the map. |
| `python3-requests` | Downloading the photos and the base map. |
| `fonts-dejavu-core` | Font used by the program (`DejaVuSans`). Without it, it falls back to a default font. |
| `alsa-utils` | Audio tools (`aplay`, `alsamixer`, `speaker-test`). |
| `kbd` | The `chvt` command, used by the screen sleep. |
| `python3-paho-mqtt` | MQTT / Home Assistant (even if you do not use it yet: it is enabled afterwards from webadmin). |
| `libegl1`, `libegl-mesa0`, `libgles2` | EGL and OpenGL ES, essential to display without a desktop (KMS/DRM driver). On Raspberry Pi OS Lite they are not installed by default: without them the program stops with `pygame.error: EGL not initialized`. |

### 3.6 HDMI signal fix (hotplug)

Some monitors cut their detection signal during sleep, which makes the Pi think a screen has just been plugged in and turns the output back on. For the Pi to ignore these changes, add `vc4.force_hotplug=1` and `video=HDMI-A-1:D` at the end of the single line of `cmdline.txt` (the second option forces the HDMI output as "connected" in the current graphics driver; with recent kernels, the first one alone is no longer enough):

```
sudo cp /boot/firmware/cmdline.txt /boot/firmware/cmdline.txt.bak
sudo sed -i '1 s/$/ vc4.force_hotplug=1 video=HDMI-A-1:D/' /boot/firmware/cmdline.txt
cat /boot/firmware/cmdline.txt
sudo reboot
```

The file must remain on a single line. On some older versions, it is at `/boot/cmdline.txt`. Consequence: the Pi no longer detects a monitor that is unplugged or changed while running; it must then be restarted. Check after the reboot: `grep -o 'vc4.force_hotplug=1\|video=HDMI-A-1:D' /proc/cmdline` (both options must appear).

---

## 4. Installing Flight display

### 4.1 Fetching the project and creating the Python environment

```
git clone https://github.com/arcalulu/flightdisplay.git ~/flightdisplay
cd ~/flightdisplay
python3 -m venv --system-site-packages venv
./venv/bin/pip install -r requirements.txt
```

The `--system-site-packages` option lets the environment use `pygame` and `requests` installed by apt. Check:

```
./venv/bin/python -c "import pygame, requests, FlightRadarAPI; print('ok')"
```

### 4.2 Alternative: copying the files from a computer

Instead of `git clone`, create the folder and copy the files from your computer:

```
mkdir -p ~/flightdisplay
scp -r main.py build_map_vector.py config.ini.example webadmin.py webadmin_mqtt.py webadmin_update.py i18n.py lang requirements.txt flightdisplay@flightradarpi.local:~/flightdisplay/
```

Then create the Python environment as in 4.1. This method disables the updates from webadmin (the folder is not a Git repository). The `types_extra.txt` file is optional: it is created from webadmin (section 9.8).

### 4.3 Dependencies of build_map_vector.py

The script may need extra libraries (the automatic installer detects and installs them). To spot them by hand:

```
cd ~/flightdisplay
grep -E '^(import|from) ' build_map_vector.py
```

Install what is missing: `python3-...` packages through apt if they exist, otherwise `./venv/bin/pip install <name>`. Pillow (`python3-pil`) is essential: the installer checks it and adds it if needed. If the step shows "Analyse de build_map_vector.py impossible" (analysis of build_map_vector.py impossible), the script contains a syntax error: the exact error is in `~/flightdisplay-install.log`.

### 4.4 Creating config.ini

```
cd ~/flightdisplay
cp config.ini.example config.ini
chmod 600 config.ini
nano config.ini
```

You must fill in at least the position, the CARTO key and the map size. All the options are described in section 8 (program) and 10.2 (web interface), and can then be changed from webadmin. The automatic installer adds the web interface sections itself with their default values. Minimal example:

```ini
[position]
latitude = 48.8566
longitude = 2.3522
radius_km = 20

[map]
carto_key = YOUR_CARTO_API_KEY

[display]
fullscreen = true
width = 1280
height = 720
```

`config.ini` contains secrets (CARTO key, webadmin password, MQTT credentials): it is not versioned by Git (it is in `.gitignore`) and must keep restricted permissions (`chmod 600`).

### 4.5 Building the map

```
cd ~/flightdisplay
./venv/bin/python -u build_map_vector.py
```

The script downloads the CARTO base map with the key from `[map] carto_key`, then produces `background.png` and `map_meta.json` in the folder. It needs Internet access and can take several minutes on a Zero. It reads the position and the radius in `[position]`, the image size in `[display] width` and `height`. Without the `carto_key` key in `config.ini`, it stops with a `NoOptionError` error.

The map must be rebuilt each time one of these settings changes: latitude, longitude, radius, width, height, key (from webadmin, Settings, Map and position).

### 4.6 First manual run

```
cd ~/flightdisplay
./venv/bin/python main.py
```

The program automatically chooses the KMS/DRM video driver when there is no graphical session. Exit with the `Esc` key (connected keyboard) or `Ctrl+C`. The message "premiere image apres X s" (first frame after X s) shows that the display has started.

---

## 5. systemd services and the `fd` command

### 5.1 User rights on the screen and the sound

```
sudo usermod -aG video,render,input,audio flightdisplay
```

The groups only take effect at the next login. The service receives them anyway through `SupplementaryGroups`.

### 5.2 flightdisplay service

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

Important points:

- Do not set `SDL_AUDIODRIVER=dummy`: it would mute the alerts.
- `PYGAME_HIDE_SUPPORT_PROMPT=1` hides the pygame welcome message.

```
sudo systemctl daemon-reload
sudo systemctl enable --now flightdisplay
systemctl status flightdisplay --no-pager
```

### 5.3 The fd command

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

| Command | Effect |
|---|---|
| `fd logs` | Follows the program's log live (Ctrl+C to quit). |
| `fd status` | Service state. |
| `fd start` / `fd stop` / `fd restart` | Start, stop, restart. |

`fd start|stop|restart` works without a password once webadmin is installed, because the installer allows these commands in sudoers.

---

## 6. System settings

### 6.1 Sound

The sound goes out through HDMI or a USB sound card. List the detected outputs and test:

```
aplay -l
speaker-test -t sine -f 880 -l 1
```

In Flight display, the sound is only opened during the alert, then closed again. To test without waiting for an aircraft, use the "Test the sound" button of webadmin (Control tab), or tick "Sound when the program starts" or "Simulate an alert at startup" in Settings, Proximity alert (section 9.4).

If the sound is unavailable, `fd logs` shows `son indisponible : ...` (sound unavailable) and the display continues without it.

### 6.2 Screen sleep

The sleep is handled by two scripts created by step 9 of `install.sh`: `/usr/local/bin/flight-screen` (sleep and wake-up) and `/usr/local/bin/flight-screen-guard` (guard).

**Why the program is stopped during sleep.** As long as the display program runs, it keeps control of the video output: writing to the framebuffer does not cut the signal (`dpms` stays `On`). The sleep therefore stops the service first.

**How the signal is cut.** The `setterm --blank force` command does not really turn off this Pi's HDMI output (`dpms` stays `On`). The script uses the kernel framebuffer instead: writing `4` to `/sys/class/graphics/fb0/blank` cuts the output (`dpms` goes to `Off`, the monitor goes to sleep), and writing `0` turns it back on. If this file is not accessible, the script falls back to `setterm`.

**Sleep terminal.** The sleep first switches to an unused virtual terminal (`tty7`), where no program writes: no login prompt or message can wake the console. The wake-up goes back to `tty1`.

Content of `/usr/local/bin/flight-screen` (for reference or a manual installation):

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

The marker file `/run/flight-screen-off` indicates that sleep is requested; it disappears when the Pi reboots.

**The guard.** `/usr/local/bin/flight-screen-guard`, started by the `flight-screen-guard` service, checks every 20 seconds that the video output is really off during a sleep. If the screen has woken up by itself (marker file present, program stopped, `dpms` at `On`), it cuts it again and logs the event. It does nothing outside a sleep, nor when the program is running.

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

To know whether the screen woke up and at what time: `journalctl -t flight-screen-guard --no-pager`. An empty log means no spontaneous wake-up occurred. The log is in memory: it is cleared at each reboot of the Pi.

**Tests over SSH.**

```
sudo /usr/local/bin/flight-screen off
sleep 4
cat /sys/class/drm/card*-HDMI-A-*/dpms
systemctl is-active flightdisplay
sudo fgconsole
```

Expected results: `Off`, `inactive`, `7`, and the monitor off. Then:

```
sudo /usr/local/bin/flight-screen on
sleep 10
cat /sys/class/drm/card*-HDMI-A-*/dpms
systemctl is-active flightdisplay
```

Expected results: `On`, `active`, and the map on the screen.

**If the monitor still wakes up.** In order:

1. Check that the fix of step 3.6 is active (`grep -o 'vc4.force_hotplug=1\|video=HDMI-A-1:D' /proc/cmdline`, both options must appear).
2. Read `journalctl -t flight-screen-guard`: the lines give the time of each wake-up. Wake-ups at regular intervals point to the monitor (automatic input detection or "deep sleep": disable this option in its menu).
3. Look for a wake-up command: `journalctl -t sudo --since today | grep flight-screen` (a Home Assistant automation or a webadmin tab may have turned the screen back on).
4. Check that the Pi has not rebooted (`uptime -s`) nor suffered an under-voltage (`vcgencmd get_throttled` must return `0x0`).
5. Rule out HDMI-CEC: `cec-ctl -d /dev/cec0` (package `v4l-utils`). With `Logical Addresses : 0`, the Pi does not take part in the CEC bus and cannot receive a remote-control key.
6. As a last resort, try a DDC/CI sleep (`ddcutil setvcp d6 5` to turn off, `ddcutil setvcp d6 1` to turn on) by modifying the script.

**Monitoring the state of the video output.**

```
cat /sys/class/drm/card*-HDMI-A-*/{enabled,status,dpms}
```

### 6.3 Sparing the SD card

The software writes very little to the card: `cache/details.json` at most once a minute, one photo per new aircraft (deleted after 3 days), and the settings files when you change them. The real risks come from the system:

- **Swap on the card**: the Pi Zero has 512 MB of RAM, and swap on an SD card wears it out quickly. Check with `swapon --show`; disable the swap file or replace it with zram.
- **Persistent journal**: Raspberry Pi OS keeps the journal in memory by default, which spares the card. Do not create `/var/log/journal` except for a one-off diagnostic need. To force the journal in memory: `Storage=volatile` in `/etc/systemd/journald.conf`, then `sudo systemctl restart systemd-journald`.
- **Power cuts without a clean shutdown**: they cause file-system corruption. Use the "Shut down" button of webadmin or `sudo poweroff`, and wait for the LED to stop before unplugging.
- **Mount options**: `noatime` must appear in `mount | grep ' / '`.

Measure the writes since boot:

```
awk '$3=="mmcblk0"{printf "%.1f MB written since boot\n", $10*512/1048576}' /proc/diskstats
```

### 6.4 Wi-Fi that drops (optional)

If the Wi-Fi connection drops, disable the power saving of the Wi-Fi card:

```
nmcli connection show
sudo nmcli connection modify "CONNECTION_NAME" 802-11-wireless.powersave 2
sudo nmcli connection up "CONNECTION_NAME"
```

---

## 7. Installing webadmin (manual)

The automatic installer (section 0) already runs this step, at its step 9. There is no separate script.

### 7.1 Installation

The simplest is to run the installer again while keeping the configuration (section 0.6): it reinstalls the webadmin and sleep services without asking the questions again. For a fully manual installation, the steps are:

1. install `kbd` and `python3-paho-mqtt` if they are missing;
2. create `/usr/local/bin/flight-screen` (screen sleep and wake-up, section 6.2, permissions 755, owner root);
3. create `/usr/local/bin/flight-screen-guard` and the `flight-screen-guard.service` unit, then enable and start the service;
4. create `/etc/sudoers.d/flightadmin` (permissions 440), validated beforehand with `visudo -cf`: it only allows, without a password, starting, stopping and restarting the `flightdisplay` service, rebooting, powering off, and `flight-screen on|off`;
5. set `python` in `config.ini`, section `[app]`, to the venv interpreter (used to build the map) and keep `config.ini` at permissions 600;
6. create the `flightadmin.service` unit (normal user, `systemd-journal` group to read the logs), then `systemctl daemon-reload`, `enable` and `restart`.

Step 9 can be run as often as you like: it rewrites the two sleep scripts (any manual change is lost) and restarts the webadmin and guard services.

Environment variables accepted by the installer for this step:

| Variable | Default | Role |
|---|---|---|
| `FD_MAIN_VT` | 1 | Main virtual terminal (return at wake-up). |
| `FD_IDLE_VT` | 7 | Unused virtual terminal for the sleep. |

Example: `FD_IDLE_VT=8 bash install.sh`.

### 7.2 First access

Open `http://flightradarpi.local:8080`. Username: `admin`, password: the one entered during installation (changeable in Settings, Web server). On iPhone, "Share" then "Add to Home Screen" gives an app icon.

```
sudo systemctl status flightadmin
journalctl -u flightadmin -n 50 --no-pager
```

### 7.3 Restarting or updating webadmin

- From the interface: a change of port or listening address offers "Save and apply", which restarts webadmin and reopens the page (on the new port if needed).
- On the command line, after replacing `webadmin.py`, `webadmin_mqtt.py`, `webadmin_update.py`, `i18n.py` or a file of `lang/`: `sudo systemctl restart flightadmin`.
- From the Updates tab (12.1), webadmin restarts itself at the end of the update.

---

## 8. `config.ini` reference

Missing options take the default value shown. Each one is set in webadmin, Settings tab, in the category given by the section title. The changes are read by the program at startup: it must be restarted ("Save and apply", or `fd restart`). The settings marked "map" also require rebuilding the map. Widths (panel, list) are expressed for a screen 1080 pixels high and adapt to the real height of the map. If you edit the file by hand, put comments on their own line, never after a value.

The `config.ini.example` template contains all the sections with example values. The web interface sections (`[server]`, `[app]`, `[screen]`, `[build]`, `[update]`, `[mqtt]`) are described in 10.2.

### 8.1 `[general]` — category "Language"

| Option | Default | Description |
|---|---|---|
| `language` | `fr` | Language code: `fr` (French) or `en` (English), or any language added in `lang/`. Changes the webadmin interface at once (immediately) and the text shown on screen by the display program (after it restarts). An unknown code falls back to French. |

Set in webadmin: Settings, Language. Adding a language is described in 12.3.

### 8.2 `[position]` — category "Map and position"

| Option | Default | Range | Description |
|---|---|---|---|
| `latitude` | required | -90 to 90 | Latitude of the house, in decimal degrees (map). |
| `longitude` | required | -180 to 180 | Longitude of the house (map). |
| `radius_km` | required | 1 to 200 | Radius covered by the map (km) (map). |

Changing one of these three values requires rebuilding the map (webadmin says so). The program shows a warning at startup if the map was built for other coordinates.

**Distance circles** (`[rings]`, webadmin, Settings, "Map and position", group "Distance circles"). These circles are drawn by the program around your position: no map rebuild is needed, only a program restart. Default: 4 circles, from 5 to 20 km.

| Option | Default | Range | Description |
|---|---|---|---|
| `show` | `true` | `true` / `false` | Show the circles. |
| `count` | 4 | 0 to 30 | Number of circles. Only those that fit within the map height (map radius) are drawn. |
| `first_km` | 5 | 0.1 to 200 | Distance of the first circle (km). Can also be used as the alert distance (`[alert] link_first_ring`). |
| `step_km` | 5 | 0.1 to 200 | Spacing between two circles (km). |
| `width` | 1 | 1 to 8 | Line thickness (pixels). |
| `color` | `#2d3746` | `#rrggbb` | Circle color. |
| `show_labels` | `false` | `true` / `false` | Writes the distance ("5 km") at the top of each circle. |

The position picker map in webadmin draws these circles (gray) and the alert circle (red): they move live when you change the values.

### 8.3 `[map]` — category "Map and position", group "Base map"

| Option | Default | Description |
|---|---|---|
| `carto_key` | required to build the map | CARTO API key used by `build_map_vector.py` to download the vector base map. In webadmin, the field is hidden like a password (map). |

The key is only read by `build_map_vector.py`, not by `main.py`. It is stored in clear text in `config.ini`: keep the file at permissions 600 and never publish it.

**Base map style** (webadmin, Settings, "Map style"; all these options require rebuilding the map). Without these options, the map keeps its original look (Dark theme: water, rivers, airports and runways).

| Option | Default | Description |
|---|---|---|
| `[mapstyle] preset` | `dark` | Theme: `dark`, `black`, `light`, `voyager`, `radar`. |
| `[mapstyle] show_water`, `show_rivers`, `show_aerodromes`, `show_runways` | `true` | Water, rivers and canals, airports, runways. |
| `[mapstyle] show_taxiways`, `show_parks`, `show_roads_major`, `show_roads_minor`, `show_rail`, `show_buildings`, `show_boundaries` | `false` | Taxiways, parks, main roads and motorways, minor roads, railways, buildings, borders. |
| `[map] forest` | `false` | Forests (historical key, also read from `[mapstyle] show_forest`). |
| `[mapstyle] road_width` | `1.0` | Road thickness multiplier (0.3 to 4). |
| `[mapstyle] color_<name>` | empty | `#rrggbb` color that replaces the theme's: `land`, `water`, `forest`, `park`, `aero`, `building`, `road_minor`, `road_major`, `road_high`, `rail`, `taxiway`, `runway`, `boundary`, `label`. |
| `[cities] show` | `true` | Show place names. |
| `[cities] kinds` | `city,town` | Place types: `city`, `town`, `village`. |
| `[cities] max_labels` | `25` | Maximum number of names. |
| `[cities] font_size` | `20` | Text size (pixels). |

The webadmin page offers thumbnails of the five themes, switches for the elements, a color picker and the place name settings. The **preview** is drawn by `build_map_vector.py --preview` (same program as the build, image reduced to 640 px wide, area and ratio of the "Map and position" page, unsaved settings included): it needs the CARTO key and internet. It is generated automatically only the first time the page is opened; afterwards a message says it is out of date after a change, and the "Refresh the preview" button regenerates it. The images and downloaded tiles are kept in `cache/mapprev/` (the preview stays displayed after a restart). Light themes make the yellow aircraft less readable.

### 8.4 `[api]` — category "Flightradar24"

| Option | Default | Range | Description |
|---|---|---|---|
| `poll_seconds` | 30 | 5 to 600 | Interval between two requests of the aircraft list. Too low, and Flightradar24 answers "429". |
| `details_pause_seconds` | 4 | 0 to 60 | Pause between two aircraft detail requests (model, airline, photo). |
| `stale_seconds` | 30 | 5 to 600 | Beyond this delay without a new position, the aircraft is removed. Also serves as a cap for the position extrapolation. |

Automatic protection: after a 429 error, the interval is multiplied by 1.5 (maximum 120 s), requests are suspended for 60 s, then the interval gradually goes back down to `poll_seconds`. For the details, a 429 error suspends the requests for 120 s and the request is replayed. Another network error triggers an increasing delay (maximum 5 minutes).

### 8.5 `[display]` — categories "Display" and "Map and position"

| Option | Default | Values | Description |
|---|---|---|---|
| `fullscreen` | false | true / false | Full screen. Set to `true` on the Pi. Otherwise a resizable window (useful on a PC). |
| `fps` | 10 | 1 to 60 | Frames per second. A low value spares the Pi Zero: it is the main lever to reduce processor use. The real rate is shown in the Program tile of Control. |
| `altitude_unit` | ft | `ft`, `m` | Displayed altitude unit. |
| `speed_unit` | kmh | `kmh`, `kt` | Displayed speed unit. |
| `max_altitude_ft` | 0 | 0 to 100000 | Higher aircraft are neither tracked nor displayed (0 = no limit). Their number appears in the status line. Also applies to the alert. |
| `icon_scale` | 1.25 | 0.3 to 5 | Aircraft icon size. |
| `plane_color_panel` | `#ff4646` | `#rrggbb` | Color of the aircraft whose photo is shown in the panel (its trail takes a matching shade). |
| `plane_color_known` | `#ffd250` | `#rrggbb` | Color of the other aircraft, whose type is known. |
| `plane_color_unknown` | `#ffaa5a` | `#rrggbb` | Color of aircraft whose type is not in the list (default icon). |
| `width` | required | 320 to 7680 | Map width in pixels (map). |
| `height` | required | 240 to 4320 | Map height in pixels (map). |

`width` and `height` are read by `build_map_vector.py`, which uses them to set the size of the background image. `main.py` does not read them: it takes the real size from `map_meta.json`, produced at build time. Changing these values therefore only takes effect after rebuilding the map. In webadmin, these two settings are in the "Map and position" category (group "Map size"), with those of the position.

The whole interface is drawn at the resolution of the map. On Windows and on the Pi, the window or the screen shows this image scaled while keeping the proportions: resizing the window only changes the zoom. For another working resolution, change `width` and `height`, then rebuild the map. Text and icon sizes adapt to the height of the map. On the Pi Zero, 1280×720 clearly reduces the number of pixels drawn compared with 1920×1080, hence the processor load.

### 8.6 `[panel]` — category "Photo panel"

| Option | Default | Range | Description |
|---|---|---|---|
| `width` | 480 | 200 to 1200 | Panel width (px, 1080p basis). |
| `rotate_seconds` | 12 | 3 to 120 | Display time of each aircraft when several are eligible. |
| `corner_top_left`, `corner_top_right`, `corner_bottom_left`, `corner_bottom_right` | true | true / false | Corners where the panel may be shown. An unticked corner is never used, even if aircraft pass behind the other corners (the panel then picks the least obstructive among the allowed corners). If all four are unticked, there is no restriction. |

The text shown below the photo (model, airline, route, altitude, speed, credit) is set in the "Text content" tab of the "Photo panel" category (see below, `[panel_content]`). The red proximity alert line cannot be changed. The text never goes beyond the panel: a line that is too long is cut and ends with "…" (reduce the size, remove an item from the line or widen the panel, `[panel] width`, to show everything).

**`[panel_content]` — category "Photo panel", "Text content" tab**

Same system as the aircraft labels (8.7): an editor with a preview (the photo is shown as a frame), and for each item the ▲ ▼ arrows (order), the switch (show or not), the size (Small, Medium, Large), B (bold), I (italic) and "Same line". Items: `model`, `registration`, `callsign`, `airline`, `route`, `altitude`, `speed`, and `credit` (the photographer's credit).

| Option | Default | Description |
|---|---|---|
| `order` | `model,registration,callsign,airline,route,altitude,speed,credit` | Display order, from top to bottom. Items missing from the list are added at the end. |
| `show_<item>` | all: true, except callsign: false | Show the item. For the credit, the option is `[panel] show_credit` (historical key kept): the credit is already visible inside the image, this line repeats it below the photo. |
| `<item>_size` | model, registration, callsign: `large`; airline, route, altitude, speed: `medium`; credit: `small` | `small`, `medium` or `large`. |
| `<item>_bold` | model, registration, callsign: true; the others: false | Bold. |
| `<item>_italic` | false | Italic (synthetic). |
| `<item>_same_line` | registration, speed, callsign: true; the others: false | On the same line as the previous visible item. |

The default values reproduce the former panel: model and registration in bold on the first line, airline, route, "Altitude … · Speed …" and the credit.

### 8.7 `[label]` — category "Aircraft labels"

Small panels shown next to each aircraft on the map (the large photo panel is not concerned). In webadmin, the category offers an editor: a live preview, then one row per item with the ▲ ▼ arrows (order), the switch (show or not), the size (Small, Medium, Large), the B (bold) and I (italic) buttons, and "Same line" (places the item on the line of the previous item, separated by a middle dot). If everything is hidden, no panel is shown. Applied after the program restarts.

Items: `model` (model; before the details are loaded: type code), `registration`, `callsign`, `airline`, `route`, `altitude`, `speed`.

| Option | Default | Description |
|---|---|---|
| `order` | `model,registration,callsign,airline,route,altitude,speed` | Display order, from top to bottom. Items missing from the list are added at the end. |
| `show_<item>` | model, airline, route, altitude, speed: true; registration, callsign: false | Show the item. |
| `<item>_size` | model, registration, callsign: `medium`; the others: `small` | `small`, `medium` or `large`. |
| `<item>_bold` | false | Bold. |
| `<item>_italic` | false | Italic (synthetic: the Pi's font has no italic variant). |
| `<item>_same_line` | registration, callsign, speed: true; the others: false | On the same line as the previous visible item. |

### 8.8 `[ground]` — category "Aircraft on the ground"

| Option | Default | Range | Description |
|---|---|---|---|
| `show_list` | true | true / false | Shows the list of aircraft on the ground at the bottom right. |
| `max_rows` | 8 | 1 to 30 | Maximum number of rows of the list. |
| `width` | 780 | 300 to 1800 | List width (px, 1080p basis). |
| `airport_iata` | empty | IATA code | Reference airport (e.g. `BOD`). Shows "from ..." for arrivals and "to ..." for departures, and limits landing detection to flights arriving at this airport. |
| `min_speed_kt` | 0 | 0 to 200 | Minimum speed to appear in the list. Slower aircraft do not trigger detail requests either. |
| `landed_alt_ft` | 2000 | 0 to 10000 | An aircraft that disappears from the data below this altitude is considered landed and goes into the ground list. |
| `landed_keep_minutes` | 10 | 0 to 240 | Time a landed aircraft stays displayed in the list. |

### 8.9 `[alert]` — category "Proximity alert"

The options are grouped in webadmin in five groups: Zone, Sound, Red tint, Altitude range, At startup.

| Option | Default | Range | Group | Description |
|---|---|---|---|---|
| `radius_km` | 5 | 0 to 50 | Zone | Radius of the alert circle. `0` disables the whole alert (tint, proximity sound, simulation). Ignored if `link_first_ring` is on. |
| `link_first_ring` | `false` | `true` / `false` | Zone | `true`: the alert radius is the distance of the first circle (`[rings] first_km`). `false`: `radius_km` (independent distance). |
| `sound` | true | true / false | Sound | Master switch of the sound. At `false`, no sound nor audio device is used, including at startup. |
| `volume` | 0.6 | 0 to 1 | Sound | Starting volume. The slider in Control overrides it live. |
| `pulse_seconds` | 3 | 0.5 to 30 | Red tint | Duration of one blink cycle of the red tint. |
| `alpha_min` | 10 | 0 to 255 | Red tint | Minimum intensity of the red. |
| `alpha_max` | 60 | 0 to 255 | Red tint | Maximum intensity of the red. |
| `min_altitude_ft` | 0 | 0 to 100000 | Altitude range | Minimum altitude (feet) to trigger the alert. |
| `max_altitude_ft` | 0 | 0 to 100000 | Altitude range | Maximum altitude for the alert (0 = no upper limit). |
| `sound_on_start` | false | true / false | At startup | Plays the chime once when the program starts, independently of all the other settings. |
| `simulate_on_start` | false | true / false | At startup | Simulates an entry into the zone at startup: red tint and chime for `simulate_seconds`, even if `sound_on_start` is unticked. |
| `simulate_seconds` | 3 | 1 to 30 | At startup | Duration of this simulation. |

Combinations at startup:

| `sound_on_start` | `simulate_on_start` | When the program starts |
|---|---|---|
| false | false | Nothing (an aircraft already in the zone still triggers a real alert). |
| true | false | One chime. |
| false | true | Chime and red tint for the chosen duration. |
| true | true | Chime and red tint (a single chime). |

Muting the sound (crossed-out speaker icon, Control switch, `M` key) and the master `sound` switch remain a priority over these two options.

### 8.10 Other sections

Any other key or section present in `config.ini` appears in webadmin under "Other settings", as text fields, and remains editable.

### 8.11 Complete example

```ini
[general]
language = en

[position]
latitude = 48.8566
longitude = 2.3522
radius_km = 20

[map]
carto_key = YOUR_CARTO_API_KEY

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

## 9. How the display works

### 9.1 Map and aircraft

- The map is a background image (`background.png`) centered on the house, accompanied by `map_meta.json` (size in pixels and scale in meters per pixel). Circles of 5, 10, 15 and 20 km are drawn within the limit of the map radius.
- Each aircraft in flight is drawn with an icon oriented along its heading. Eight shapes exist: `narrow` (single-aisle), `wide` (wide-body), `quad` (four-engine jet), `regional`, `turbo` (turboprop), `light` (light aircraft), `bizjet` and `heli`.
- Positions are extrapolated between two updates (speed and heading) then smoothed, for a fluid movement. A trail of the last positions is drawn behind each aircraft.
- Each aircraft has a label whose content, order and formatting (size, bold, italic) are set in Settings, Aircraft labels (8.7). By default: model, airline, route (origin → destination) and altitude · speed; the registration and the callsign are available as options. Until the details have arrived, it shows the type code (and the registration or callsign if they are enabled). The route is omitted if the origin and the destination are unknown (no declared flight plan). If only one is known, the other appears as `?`.
- The labels are placed to avoid overlapping each other and leaving the screen.
- The status line at the bottom left shows the number of aircraft in flight, above the altitude limit, on the ground, network errors and the "old data" mention if updates are late. On the right of the same line, the credits "© OpenStreetMap contributors · © CARTO · Flightradar24" are always shown (they are also in the "Credits" page of webadmin, reached through the link at the top of the interface): the attribution required by OpenStreetMap and CARTO must remain visible. See [CREDITS.md](../CREDITS.md).

### 9.2 Photo panel

- A panel with the photo, then the text (by default the model, the registration, the airline, the route, the altitude, the speed and the photographer's credit; content, order and style can be set in Settings, Photo panel, "Text content" tab, 8.6) is shown for one aircraft at a time, alternating every `rotate_seconds` among the aircraft that have a photo.
- The presented aircraft is highlighted in red on the map.
- The panel is placed in the corner of the screen that obstructs the displayed aircraft the least, among the corners allowed in Settings, Photo panel (8.6). An unticked corner is never used.
- Photos and details come from Flightradar24; the photographer's credit is visible in the image and repeated ("© name / JetPhotos") in small print below the panel information, unless the "Photographer credit" item is hidden in Settings, Photo panel, "Text content" tab (8.6). If a photo is missing or does not load, the aircraft is ignored in normal mode.

### 9.3 Aircraft on the ground

The list at the bottom right (see `[ground]`) shows callsign, airline, model and route, sorted by decreasing speed. An aircraft that disappears from the data below `landed_alt_ft` is kept for `landed_keep_minutes` as "landed".

### 9.4 Proximity alert

When an aircraft in flight enters the alert circle (`[alert] radius_km`) and respects the altitude range:

- a three-note chime sounds (generated by the program, no sound file);
- the inside of the circle is tinted transparent red with a slow blink, and the circle is surrounded by a red frame, as long as an aircraft is inside;
- the photo panel only shows the aircraft present in the circle (alternating if there are several), with a red line "ALERT · X.X km from home". If the photo is missing, the panel is shown with a "Photo unavailable" frame;
- as soon as the circle is empty, the display returns to normal operation.

The distance is measured on the ground, with an exit margin of 10% of the radius to avoid repeated alerts. An aircraft already in alert keeps a 10% margin on the altitude bounds. The sound is only played when an aircraft enters, never twice in parallel.

**When the program starts**: an aircraft already in the zone triggers a real alert, as at any other time. To test the sound and the tint without an aircraft, two independent options exist (section 8.9): "Sound when the program starts" (one chime) and "Simulate an alert at startup" (red tint and chime). There are never two chimes at once.

### 9.5 Sound control while running

The sound can be muted and adjusted without restarting the program. webadmin writes the state to `cache/runtime.json`, re-read by the program every half second.

| File key | Role |
|---|---|
| `muted` | `true` mutes the sound. A crossed-out speaker icon is then shown at the bottom left. |
| `volume` | Volume from 0 to 1, takes priority over `config.ini`. |
| `test_seq` | Counter incremented to request a test sound. The program remembers its value when it loads: only requests made while it runs play a sound. |

The `M` key of the keyboard connected to the Pi also mutes or unmutes the sound. The muted state and the chosen volume are kept after a restart.

### 9.6 Keyboard shortcuts

| Key | Action |
|---|---|
| `Esc` | Quit the program. |
| `M` | Mute or unmute the alert sound. |

### 9.7 Cache and generated files

| File | Content | Lifetime |
|---|---|---|
| `background.png`, `map_meta.json` | Map and its dimensions, produced by `build_map_vector.py`. | Until the next rebuild. |
| `cache/details.json` | Aircraft details (model, airline, route). | 3 hours. |
| `cache/*.jpg` | Downloaded photos. | Cleaned after 3 days at startup; can be deleted from webadmin (Settings, Storage and photos). |
| `cache/runtime.json` | Sound state (muted, volume, test). | Persistent. |
| `/dev/shm/flightdisplay-fps.json` | Frames per second really displayed, published every 2 seconds for webadmin. In memory: no write to the SD card (`cache/fps.json` if `/dev/shm` does not exist). | Lost at reboot. |
| `cache/update.json` | State and log of the last update from webadmin. | Persistent. |

### 9.8 Unknown aircraft types

When an aircraft type has no dedicated icon, a single-aisle shape is used and the log shows `type inconnu (icone par defaut) : XXXX` (unknown type, default icon). To assign it the right shape, use webadmin, Settings, "Aircraft types": the types detected in the logs are offered, with a field to add a rule and the editor of the `types_extra.txt` file. The file is checked when saved and taken into account at the next start of the program.

File format (one rule per line, `#` for comments):

```
WT9 light
B350 turbo   # example
```

Valid categories: `narrow`, `wide`, `quad`, `regional`, `turbo`, `light`, `bizjet`, `heli`.

### 9.9 Recognized environment variables

| Variable | Effect |
|---|---|
| `PYGAME_HIDE_SUPPORT_PROMPT=1` | Hides the pygame welcome message. |
| `SDL_VIDEODRIVER`, `SDL_RENDER_DRIVER` | Set automatically (`kmsdrm`, `opengles2`) on Linux without a desktop, unless already present. |
| `SDL_AUDIODRIVER` | Set to `dummy` only if `[alert] sound = false`. Do not set it otherwise. |
| `WEBADMIN_INI` | Alternative path of the settings file read by webadmin (`config.ini` by default). |

---

## 10. webadmin reference

### 10.1 The tabs

**Control** (home page)

- Eight monitoring tiles, in two rows of four on a computer (four columns) and in two columns on a phone. The first row gives the state, the second the measurements as progress rings:
  - Program: active or stopped. When it is active, the number of frames per second really displayed (average over 2 seconds) is shown under the status, with the target set in `[display] fps`. A value clearly lower than the target signals an overloaded Pi Zero. The program publishes this measurement in `/dev/shm/flightdisplay-fps.json` (memory, not the SD card; `cache/fps.json` if `/dev/shm` does not exist).
  - Screen: on or asleep.
  - MQTT: connected (green), disconnected or refused (red), disabled (neutral).
  - Time: local time of the Raspberry Pi (to the second), date and time zone, uptime and hostname. This is the time used by the screen schedule: if it is wrong, see 3.4.
  - Temperature: ring graduated from 0 to 85 °C (the SoC limit set by Raspberry Pi for all models). Orange 10 °C before the throttling threshold, red from the threshold. The threshold depends on the model, detected automatically (`/proc/device-tree/model`), according to Raspberry Pi's documentation: **80 °C** for the Pi Zero, Zero 2 W, Pi 4, Pi 5 and the other models (the firmware throttles the Arm cores between 80 and 85 °C, then the GPU too above 85 °C); **60 °C** for the Pi 3 B+, 3 A+ and Compute Module 3+ (default soft limit, with frequency reduction). Raspberry Pi does not publish a Pi Zero specific value: the general 80 °C value applies. Hovering the tile gives the model and the limits.
  - CPU usage: ring from 0 to 100% measured every 2 seconds (orange above 85%, red above 95%), with the system load average over 1 and 5 minutes next to it. The load average is not a percentage: on the Pi Zero, which has a single core, 1.00 already means a saturated processor.
  - Memory: ring with the percentage used and the MB (orange above 80%, red above 90%).
  - Disk: ring with the percentage used and the free space (hover for the total). The ring turns orange 10 points before the alert threshold and red at the threshold, with a colored frame (see "Storage and photos").
  Refreshed every 4 seconds. The page header only shows status dots: "sound muted", "map building", "update in progress", "update available" or "disk X % full" (orange 10 points before the threshold, red at the threshold; a click opens "Storage and photos").
- Toggle commands, like in iOS Settings or Home Assistant:
  - Flight Display program: starts or stops the service (if the screen is asleep, the switch turns the screen back on).
  - Screen: sleep and wake-up (sleep also stops the program, see 6.2).
  - Screen schedule (shown only when a schedule is active): next scheduled action, with the time and the time left (for example "Next action: turn off at 23:00 (in 4 h 12 min)"). The "Edit" button opens the calendar.
  - Alert sound: mutes or unmutes the sound (disabled and greyed out if `sound = false` in `config.ini`).
- Volume slider (0 to 100%), applied live at the next alert.
- "Test the sound" button (disabled while the sound is muted). Restarting the program is offered in Settings after saving ("Save and apply").
- Power: restart or shut down the Pi, with confirmation. After a shutdown, the power supply must be unplugged and plugged back in.

**Settings**

On a computer, a menu on the left lists the categories; on a phone, it becomes a scrolling bar of buttons at the top. The categories are:

| Menu | Category | File | Content |
|---|---|---|---|
| General | Language | config.ini | Language of the interface and of the screen (8.1). |
| Program | Map and position | config.ini | Latitude, longitude, radius, map size (width and height), CARTO API key (hidden), then the "Map rebuild" section (see below). |
| | Flightradar24 | config.ini | Request frequency, position validity. |
| | Display | config.ini | Full screen, frames per second, units, altitude filter, icon size. |
| | Aircraft labels | config.ini | Editor: preview, order, display, size, bold, italic, "same line" (8.7). |
| | Photo panel | config.ini | Two tabs: "Text content" (editor with a fixed preview: order, display, size, bold, italic, "same line", photographer credit) and "Size and corners" (width, rotation, allowed corners). See 8.6. |
| | Aircraft on the ground | config.ini | List, filters, landing. |
| | Proximity alert | config.ini | Zone, sound and volume, red tint, altitude range, startup (sound at launch, simulation). |
| | Aircraft types | types_extra.txt | Rules editor, detected unknown types. |
| | Other settings | config.ini | Any key outside the schema (shown only if there are any), in the "Not in the schema (config.ini)" group. |
| Webadmin | Web server | config.ini | Address, port, username, password. The "no password" warning is shown here (and only here) as long as no password is set. |
| | Application and system | config.ini | Folder, files, service, map Python, sudo, commands, sleep script and marker, stopping the display during the map build. |
| | Updates | config.ini | Channel, automatic check (`auto_check`), interval from 1 to 48 hours (`check_hours`) and automatic installation (`auto_install`). |
| | Screen schedule | config.ini | Schedule switch and weekly calendar of the on ranges (see below). |
| | Backup | — | Export of the configuration to a file and restore (see below). |
| | Storage and photos | config.ini | Disk usage, cached photos, "Clear the photo cache" button, alert threshold (see below). |
| Integrations | MQTT / Home Assistant | config.ini | Connection, topics and discovery, with state and a "Reconnect" button. |

Input controls: toggle switches for yes/no values, segmented buttons for choices of two or three values (label size, language), sliders for the volume and the red intensity, text fields with limits for the rest. Passwords and the CARTO key are hidden: the field stays empty to keep the current value, typing a value replaces it, the "Clear" button deletes it.

Saving:

- Modified fields are outlined in yellow and a dot marks the modified categories. A bar at the bottom shows the number of changes and what will need to be applied.
- "Save" writes the files and shows what remains to be applied, with buttons to do it.
- "Save and apply" also performs the necessary restarts.
- Map settings (position, radius, size, key) trigger a banner that offers to rebuild the map.
- Only the modified lines are rewritten: the comments of the files are kept. A `config.ini.bak` backup is created at each save, even when the change affects both program and web interface settings (a single write, a single backup). The "Go back to the previous version" button, at the bottom of the Webadmin and Integrations categories, restores the whole `config.ini` (a second click cancels the operation): it therefore also puts the program settings back in the state of the backup.
- Out-of-range or malformed values are refused with a message, without writing anything.
- A language change reloads the page: webadmin switches to the new language at once, the display program takes it after it restarts.

When a change takes effect:

| Settings | Taken into account |
|---|---|
| `config.ini` (all the categories of the Program menu) | At the next start of the program (restart offered). The map must also be rebuilt for the map settings. |
| Aircraft types | At the next start of the program. |
| Language | Immediately for webadmin (the page reloads); at the next start of the program for the text shown on screen. |
| Web server: address and port | At the restart of webadmin (offered: the page reopens by itself, on the new port if needed). |
| Web server: username and password | Immediate (the browser asks for the credentials again). |
| Application and system, Updates, Screen schedule | Immediate. |
| MQTT | Immediate: webadmin reconnects to the server. |

**Storage and photos** (Settings, Storage and photos)

- **Disk**: a usage bar of the disk that contains the application (the SD card, same calculation as `df`): percentage used, space used, total and free. The bar is green, orange 10 points before the threshold, red at the threshold; a white line marks the alert threshold and a blue part shows the room taken by the photos.
- **JetPhotos photos in cache**: number of image files (`cache/*.jpg`), the volume they occupy, the share this represents as a percentage of the disk and of the used space, age of the oldest photo, and volume of the other cache files (aircraft details, sound state).
- **Clear the photo cache**: deletes all the photos of the cache after confirmation. Only the photos are deleted (not the aircraft details, to avoid multiplying requests to Flightradar24). The display program downloads a deleted photo again when it is needed once more; until then, the panel shows "Photo unavailable" for that aircraft.
- **Monitoring**: the "Disk alert threshold (%)" setting (90 by default, from 50 to 99) triggers the alert: "disk X % full" chip in the header (all pages), colored Memory tile, banner in this page. The orange alert comes 10 points before the threshold.
- The program deletes photos older than 3 days at each start anyway (9.7).

**Backup** (Settings, Backup)

- **Export**: the "Download the backup" button produces a file `flightdisplay-backup-<pi-name>-<date>.zip` containing `config.ini` (all the program and webadmin settings), `types_extra.txt` (aircraft types), the sound state, the map already built (`background.png` and `map_meta.json`, so it does not have to be rebuilt) and a small information file. Photos are not in it.
- **Secrets**: the "Include passwords and the CARTO key" switch (on by default) decides whether the secrets (CARTO key, webadmin password, MQTT password) are in the file. With the secrets, the restore gets everything back; **the file is then sensitive**: do not share it. Without secrets, it can be shared (for example for a diagnosis). An export with secrets is only possible from the interface (`X-Admin` header), never through a plain link.
- **Restore**: choose a file then "Restore" (confirmation asked). The current configuration is replaced (the old `config.ini` stays as `config.ini.bak`). A backup made without secrets keeps those of the current installation. The file is checked before any change (format, allowed content, readable `config.ini`, valid type rules): an invalid file is refused without changing anything. Webadmin then offers to restart the program (equivalent to "Save and apply"); a language change reloads the page.
- Typical case, after an SD card failure: install a new Pi (section 0, with `--yes` if you like), open webadmin, restore the file, restart the program, then rebuild the map.

**Screen schedule** (Settings, Screen schedule)

Turns the screen on and off by itself following a weekly calendar, like a diary.

- The "Enable the schedule" switch starts the schedule. The calendar shows the seven days (Monday to Sunday) over 24 hours; the **blue** ranges are the hours when the screen is on, everything else is off. A red bar marks the current time in the column of the day.
- On the calendar: dragging on a day draws a range (in steps of 15 minutes); a simple click creates a one-hour one; pulling the top or bottom of a range adjusts it; moving it with the mouse or a finger changes its time, or its day if you drag it onto another column; ✕ deletes it; ⧉ at the head of a column copies the day to the whole week. "Every day 07:00-23:00" and "Clear all" are shortcuts. Ranges that touch or overlap are merged.
- Like the other settings, changes are saved with the bottom bar, then taken into account immediately (no restart).
- The action runs **at the scheduled times**: at the start of each range, webadmin turns the screen on (wake-up, like the Screen button in Control); at the end of each range, it puts it to sleep (the display program is then stopped, see 6.2). Between two scheduled times, you can turn the screen on or off by hand: the schedule does not correct it and resumes at the next scheduled time. A day without ranges is a day entirely off.
- When the schedule is saved, the screen is aligned at once with the state wanted at that time. When webadmin restarts, nothing is forced.
- The Control page shows the next action (turn on or off, time and time left) as long as the schedule is active.
- The schedule follows the **Pi time** (system time zone, see 3.4). It runs inside webadmin: it only works while webadmin is running, and uses the `flight-screen` script through sudo like the Screen button. An action is postponed while a map rebuild or an update is in progress. If the command fails, the message is shown below the next action.
- In `config.ini`, section `[schedule]`: `enabled` and one line per day (`mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`) like `mon = 07:00-09:30,18:00-24:00` (`HH:MM` times, from `00:00` to `24:00`).

**Choosing the position and the radius** (Settings, Map and position, at the top of the page)
- An OpenStreetMap map (darkened so that the yellow frame stands out) lets you click or drag the marker to set the position, or search an address (Nominatim search, run only when you ask for it). The latitude and longitude fields below are updated.
- The "Radius" slider sets `radius_km`. The yellow rectangle shows the area actually displayed (height = 2 × radius, width following the "Width / Height" ratio of the map size) and the dashed circle shows the radius.
- When "Show the distance circles" is checked, two controls are added under the "Radius" slider: a "1st circle" slider (`first_km`) and two buttons − and + for the number of circles (`count`). The grey circles of the map and those of the preview follow live.
- Below the map, a preview with the same ratio as the display shows the area on a darkened OpenStreetMap background (the real background is CARTO's, built at rebuild time).
- The values are pending changes: "Save", then rebuild the map. The map needs internet access from the browser (Leaflet is loaded from cdnjs); without it, the fields can still be filled in by hand.

**Map rebuild** (Settings, Map and position, at the bottom of the page; a banner points to it when a map setting has changed)

- "Rebuild the map" button: runs `build_map_vector.py` with the current settings, shows its output live, and offers "Cancel".
- "Stop the display during the build" switch: frees the Pi Zero's memory during the computation. At the end, the display is restarted to load the new map (unless the screen is asleep). If the build fails, the display resumes with the old map.
- Only one build at a time (and not during a software update).

**Updates**

- A **summary card** at the top: the installed version in large print, a chip "up to date" (or "check failed", "not checked"), the date, the last commit and the time of the last check. When a newer version exists, the card shows `v1.1.0 → v1.2.0` with the number of changes, and the "Update" button comes to the front. A check starts by itself when the tab is opened and there is none yet.
- "Check for updates" queries GitHub; "Update" starts the update immediately, without confirmation.
- **During the update**: a compact card with the title ("Updating to v1.2.0"), the percentage, the progress bar, a seven-segment bar (one per step: checks, download, apply, libraries, code check, display restart, webadmin restart; green when done, yellow in progress, red on error), the current step with the elapsed time, and a "Detailed log" that is collapsed and opens with a click. The page reloads by itself at the end.
- **Display restart**: the display program is restarted only if the update changes its files (`main.py`, `aircraft_types.py`, `i18n.py`, `requirements.txt`, or a `lang/` text that is shown on the display: webadmin-only texts do not count). An update that only touches webadmin, the documentation or the installer does not interrupt it (step "not concerned"). Webadmin itself always restarts.
- **After the update**, a single line summarizes the last operation ("✓ Last update: v1.0.0 → v1.1.0, 2 min ago"). A click on "Details" opens the list of steps and the log. On failure, the line turns red with the cause and the details open automatically.
- "Version history": changelog grouped by version. Each version (git tag `vX.Y.Z`) is a collapsible separator, with its commits below it from the most recent to the oldest (number, commit, date, description). The commits after the latest version are grouped under "In development (unreleased)". The most recent version is expanded, the others collapsed. Markers: "new" (not installed yet) and "installed". Warnings point out a locally modified file, local commits missing from GitHub or a modified `install.sh`. The complete procedure is described in 12.1.
- **Going back to the previous version**: after an update (or a rollback), the versions left by the last 8 updates are **fallback versions**: in the history, the commit line shows a "Go back to this version" button (just as the "installed" badge marks the running version), and the group header carries a "fallback version" badge. The button restores that version (confirmation asked): same steps as an update without the download (libraries reinstalled if needed, code check, restart of the display and of webadmin, automatic restore on failure). After a rollback, the version left is available again as an update ("Update"). Your settings are not touched.
- **Channel**: "Update channel" in Settings, Updates: "Stable" (published versions, default) or "Development" (every commit). The summary card shows the channel; on the stable channel, a Pi running a commit newer than the latest version shows "N commits after vX.Y.Z".
- A green "update available" chip appears in the header, on every page. A click on the chip opens the Updates tab; hovering it reveals a small ⬆ icon (always visible on a touch screen): a click on it starts the update at once, without leaving the current page. The chip then shows "update in progress · X %", and the page reloads at the end. The icon is only offered if the update is possible (no locally modified file, no conflict); on failure, a message is shown.

**Credits**

The small "Credits" link, at the top of the page next to the status chips, opens a dedicated page: sources of the maps (OpenStreetMap, CARTO), of the flight data (Flightradar24, FlightRadarAPI), of the photos (JetPhotos) and the licenses of the libraries, with a link to `CREDITS.md` for the detail. The "Back" button returns to Control.

**Logs**

- Display service log: 100, 300 or 1000 lines, text filter, automatic refresh (switch) every 3 seconds. Errors are in red, warnings in yellow.

### 10.2 Web interface settings

These options live in `config.ini`, in the sections `[server]`, `[app]`, `[screen]`, `[build]`, `[update]` and `[mqtt]`, and are changed in Settings, categories "Web server", "Application and system", "Updates" and "MQTT / Home Assistant". The file can also be edited by hand (then `sudo systemctl restart flightadmin`). The installer writes these sections with the default values below when they are missing.

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

| Section | Option | Default | Description |
|---|---|---|---|
| `[server]` | `host` | `0.0.0.0` | Listening address. `127.0.0.1` limits access to the Pi itself. |
| | `port` | 8080 | HTTP port (1 to 65535). |
| | `user` | `admin` | Login username. |
| | `password` | empty | Password (HTTP Basic authentication). Empty: no protection, a warning is shown in Settings, Web server. |
| `[app]` | `dir` | folder of `webadmin.py` | Application folder (where `config.ini`, `cache/` and the map script are). |
| | `config` | `config.ini` | Name of the settings file. |
| | `runtime` | `cache/runtime.json` | Sound state file shared with the program. |
| | `service` | `flightdisplay` | Display systemd service. |
| | `python` | the one of webadmin | Interpreter used for `build_map_vector.py` (filled by the installer with the venv one). |
| | `build_script` | `build_map_vector.py` | Map build script. |
| | `sudo` | `sudo -n` | Prefix of privileged commands (without a password). |
| | `systemctl`, `journalctl` | detected | Command paths. `systemctl` must match the one in the sudoers file (`/usr/bin/systemctl`). |
| `[screen]` | `helper` | `/usr/local/bin/flight-screen` | Sleep and wake-up script. |
| | `flag` | `/run/flight-screen-off` | Sleep marker file (deleted when the Pi reboots). |
| `[build]` | `stop_display` | true | Default value of the "Stop the display during the build" switch (map rebuild). |
| `[update]` | `channel` | `stable` | Update channel: `stable` (only published `vX.Y.Z` versions, recommended) or `latest` (latest commit of the branch, development). |
| | `auto_check` | true | Regularly checks whether a new version exists on GitHub (shown by a chip in the header). |
| | `check_hours` | 12 | Interval between two checks, from 1 to 48 hours (slider in Settings, "Updates"). Read again at each cycle: a change applies without a restart. |
| | `auto_install` | false | Automatically installs every new version detected, without a click (requires `auto_check`). Disabled by default: nothing is installed without your approval. |
| `[schedule]` | `enabled` | false | Enables the screen on/off schedule. |
| | `mon` to `sun` | empty | On ranges of the day (`HH:MM-HH:MM`, separated by commas). Empty: screen off all day while the schedule is active. |
| `[storage]` | `warn_percent` | 90 | Disk usage alert threshold, in % (50 to 99). Orange alert 10 points earlier. |
| `[mqtt]` | | | See section 11. |

Can only be changed from the command line: the systemd services, the sudoers file, the content of the sleep and guard scripts (virtual terminal numbers) and the environment variables.

### 10.3 HTTP API

All routes require authentication if a password is set. `POST` requests additionally require the `X-Admin: 1` header (protection against requests triggered from another web page) and a JSON body. Passwords and the CARTO key are never returned by the API: only their state (set or not) is.

| Route | Method | Body | Role |
|---|---|---|---|
| `/` | GET | | Web interface. |
| `/api/status` | GET | | State: service, screen, CPU usage as a percentage (`cpu`), load average (`load`), temperature, memory, uptime, sound (muted, volume, enabled), build in progress, MQTT (`mqtt`), real frames per second and target (`fps`, `fps_target`), disk (`disk`: total, free, percentage, level), update available or in progress (`update_available`, `update_running`). |
| `/api/settings` | GET | | Categories, groups, parameters, values and available backups, texts in the active language. |
| `/api/settings` | POST | `{"changes": {"config:alert.volume": "0.5", "web:mqtt.host": "10.0.0.2"}}` | Saves the values (key = `file:section.option`, file `config` or `web`). Returns what needs to be applied. |
| `/api/settings/restore` | POST | `{"file": "config"}` | Swaps the file (`config` or `web`) with its `.bak` backup. |
| `/api/types` | GET / POST | `{"text": "WT9 light\n"}` | Reads and writes `types_extra.txt` (GET: also the unknown types from the logs). |
| `/api/logs?lines=N` | GET | | Service log (10 to 2000 lines). |
| `/api/sound` | POST | `{"muted": true, "volume": 0.5, "test": true}` | Mute, set the volume, play a test (each key is optional). |
| `/api/service` | POST | `{"action": "start\|stop\|restart"}` | Controls the display service. |
| `/api/screen` | POST | `{"action": "on\|off"}` | Screen sleep and wake-up. |
| `/api/power` | POST | `{"action": "reboot\|poweroff"}` | Restarts or shuts down the Pi. |
| `/api/build` | GET / POST | `{"stop_display": true}` | State and output of the build / start. |
| `/api/build/cancel` | POST | `{}` | Cancels the build. |
| `/api/backup` | GET | | Downloads the backup (zip). `?secrets=1` includes the secrets and requires the `X-Admin: 1` header; `?secrets=0` removes them. |
| `/api/backup/restore` | POST | `{"data": "<zip in base64>"}` | Restores a backup (up to 3 MB). |
| `/api/storage` | GET | | Disk usage (total, used, free, percentage, alert level) and cache usage (number and volume of photos, other files). |
| `/api/storage/clear` | POST | `{}` | Deletes the photos of the cache; returns the number and volume deleted. |
| `/api/update` | GET | | State of the updates: last check (versions, changes), progress, steps and log of the current or last update, version history. |
| `/api/update/check` | POST | `{}` | Queries GitHub (`git fetch`) and returns the updated state. |
| `/api/update/start` | POST | `{}` | Starts the update in the background (followed through `GET /api/update`). |
| `/api/update/rollback` | POST | `{}` | Goes back to the version left by the last update. |
| `/api/mqtt/reconnect` | POST | `{}` | Reconnects MQTT and republishes the discovery. |
| `/api/webadmin/restart` | POST | `{}` | Restarts webadmin. |

Example with `curl` (password set):

```
curl -u admin:PASSWORD -H "X-Admin: 1" -H "Content-Type: application/json" \
  -d '{"muted": true}' http://flightradarpi.local:8080/api/sound
```

### 10.4 Security

- HTTP Basic authentication sends the password in clear text on the local network. Reserve it for a trusted home network, never exposed to the Internet.
- Without a password, any device on the network can shut the Pi down: the warning is shown in Settings, Web server.
- webadmin runs with your user, not as root. Only the commands listed in `/etc/sudoers.d/flightadmin` go through sudo.
- `config.ini` (CARTO key and passwords) stays at permissions 600 (installer and saves from the interface).
- There is no lockout after password errors, but each failed attempt is slowed down by one second.

---

## 11. MQTT and Home Assistant

### 11.1 Setup

1. The `python3-paho-mqtt` package is installed at step 3.5 (or by the automatic installer).
2. In webadmin: Settings, Integrations, "MQTT / Home Assistant". Enable MQTT, fill in the server, the port, the username and the password, then save. The connection is immediate. (The automatic installer can also fill in these values at installation time.)
3. The connection state (connected, disconnected, refused, paho missing, server missing) is shown in a tile of the Control page and at the top of the MQTT category. The "Reconnect / republish" button restarts the connection and the discovery.

The same settings exist in `config.ini`, section `[mqtt]`.

### 11.2 Options

| Option | Default | Description |
|---|---|---|
| `enabled` | false | Enables the MQTT bridge. |
| `host` | empty | Address of the MQTT server (required). |
| `port` | 1883 | Server port. |
| `user`, `password` | empty | Server credentials. |
| `tls` | false | TLS encryption, certificate verified with the system authorities. |
| `base_topic` | `flightdisplay` | Prefix of the MQTT topics. |
| `discovery_prefix` | `homeassistant` | Prefix of Home Assistant's automatic discovery. |
| `device_name` | `Flight display` | Name of the device in Home Assistant. |
| `interval` | 30 | Period of the full republication of the states (minimum 5 s). Changes are published within 5 seconds. |

### 11.3 Entities created

| Entity | Type | Topics (state / command) | Description |
|---|---|---|---|
| Screen | switch | `base/screen/state`, `base/screen/set` | ON turns it back on, OFF puts it to sleep (and stops the program). |
| Alert sound | switch | `base/sound/state`, `base/sound/set` | ON if the sound is neither muted nor disabled in `config.ini`. OFF mutes the sound. |
| Alert volume | number 0-100% (steps of 5) | `base/volume/state`, `base/volume/set` | Sets the volume live. |
| Temperature | sensor °C | `base/temperature/state` | Pi temperature, rounded to 0.5 °C. |
| Aircraft in flight | sensor | `base/aircraft/state` | Number of aircraft in flight shown on the map. `unavailable` when the program is stopped. |
| Aircraft on the ground | sensor | `base/aircraft_ground/state` | Number of aircraft in the ground list. |
| Aircraft in the alert zone | sensor | `base/aircraft_zone/state` | Number of aircraft inside the alert circle. |
| Alert active | binary sensor | `base/alert/state` | ON as long as at least one aircraft is in the alert zone. |
| Program running | binary sensor (running) | `base/program/state` | ON if the display service is running. |
| Frames per second | sensor (diagnostic) | `base/fps/state` | Rate really displayed. |
| CPU usage, Memory used, Disk used | % sensors (diagnostic) | `base/cpu/state`, `base/memory/state`, `base/disk/state` | Pi measurements. |

The entity names follow the language chosen in webadmin (for example "Écran", "Son des alertes", "Volume des alertes", "Température" in French), published at each (re)connection.

Other topics: `base/availability` (`online` / `offline`, with a last will so that the entities become "unavailable" if webadmin stops) and `homeassistant/status` (listened to: each time Home Assistant restarts, the discovery is republished). The states and the discovery are retained by the server. Commands must never be published with the "retain" flag: a retained message would be sent again at each reconnection.

The device is identified by `flightdisplay_<hostname>`. The entities appear under Settings, Devices, MQTT. Example automation to turn the screen off at 11 pm (adapt the entity name):

```yaml
automation:
  - alias: Flight display - screen off at night
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id: switch.flight_display_screen
```

The volume and the sound remain adjustable during the screen sleep: the values will apply at wake-up.

---

## 12. Maintenance

### 12.1 Updating

**From webadmin (recommended).** **Updates** tab:

1. A card at the top of the tab summarizes the situation: installed version (with the channel followed), status (up to date, new version available with the number of changes, or check failed), "Update to X" button, time of the last and of the next check, and a link to the automatic update settings. "Check for updates" compares your version with the one on GitHub (branch followed by the installation, `main` by default) and lists the changes. An "update available" chip appears at the top of the page; by default, webadmin checks by itself every 12 hours (Settings, "Updates": `auto_check` and `check_hours` options, from 1 to 48 hours, `[update]` section of `config.ini`). By default, nothing is installed without a click on "Update"; the `auto_install` option ("Install updates automatically") starts the update by itself as soon as a new version is detected, with the same automatic return to the previous version on failure. A version whose automatic installation failed is not retried in a loop: install it by hand then.
2. "Update" chains: checks (Git repository, disk space, no locally modified file), download, apply (fast-forward only), Python libraries (only if `requirements.txt` or the dependencies of `build_map_vector.py` changed), code check, display restart, webadmin restart. The progress and the log are shown live; the page reloads at the end.
3. If the code of the new version contains an error or if the display does not stay active after the restart, the previous version is restored automatically.

Limits: webadmin does not have the rights to modify system components (systemd services, sudo rights, sleep script, HDMI fix). If a version changes them, a warning is shown (when `install.sh` is modified): run the installer again while keeping the configuration. The update is refused if files tracked by Git were modified by hand, or if the installation is not a Git repository.

**On the command line**, with a Git installation or one made by the automatic installer:

```
cd ~/flightdisplay
git pull
fd restart
sudo systemctl restart flightadmin
```

Your settings (`config.ini`) are not versioned and remain intact. If the update changes the sleep scripts or the services, run the installer again while keeping the configuration (section 0.6): step 9 reinstalls them, and it also updates the packages.

If `git pull` refuses to run because files were modified by hand, see what differs with `git status`, then discard the changes (`git checkout <file>`) or set them aside (`git stash`). `config.ini` is never concerned: it is not tracked by Git.

With a file-copy installation: copy all the project files again (`main.py`, `webadmin.py`, `webadmin_mqtt.py`, `webadmin_update.py`, `i18n.py`, the `lang` folder...) from the computer, then `fd restart` and `sudo systemctl restart flightadmin`.

### 12.2 Publishing a version (maintainer)

A version is an annotated git tag `vX.Y.Z` placed on a commit, then sent to GitHub. The webadmin history files the commits under the matching version (that of the commit and of the previous commits, up to the earlier tag).

```
git tag -a v1.1.0 -m "Version 1.1.0"
git push origin v1.1.0
```

Installations fetch the tags at each check. On the **stable** channel (default, `[update] channel`), an update installs the latest `vX.Y.Z` tagged version of the branch (pre-releases such as `v1.3.0-rc1` and unpublished commits are ignored); on the **latest** channel ("Development" in Settings, Updates), it installs the latest commit of the branch, published or not. For a version to reach stable-channel users, the tag must therefore be placed.

### 12.3 Adding a language

French is the reference language: the French texts of the code serve as keys. Each language is a file `lang/<code>.json`:

```json
{
 "_meta": {"name": "Deutsch"},
 "strings": {
  "Pilotage": "Steuerung",
  "{0} avion(s) en vol": "{0} Flugzeug(e) in der Luft"
 }
}
```

- A key containing `{0}`, `{1}`... is a template: it recognizes composed texts ("3 on the ground", "Latitude: minimum -90") and the translation reuses the same placeholders, in the desired order.
- A missing or empty text stays in French: a partial translation works.
- To create the file with all the texts to translate: `python3 lang/check_lang.py --new de "Deutsch"`. To see what remains to be translated and to check the placeholders: `python3 lang/check_lang.py de`. `lang/en.json` is the reference for the list of keys.
- Restart webadmin (`sudo systemctl restart flightadmin`, or an update): the language appears in Settings, Language. It applies to webadmin immediately and to the display program after it restarts.
- Not translated: the installer (`install.sh`), the technical log messages and the commit descriptions. The documentation exists in French and in English (`docs/FLIGHT_DISPLAY_DOCUMENTATION.md` and `.en.md`).

When a new version of the software adds a text, it appears in French until `lang/en.json` (and the other files) has the matching key.

### 12.4 Backup

To keep: `config.ini` (CARTO key, webadmin password, MQTT), `types_extra.txt`, `cache/runtime.json`, and your own language files if any (`lang/<code>.json` not provided by the project). `background.png` and `map_meta.json` are regenerated from `config.ini`.

```
cd ~/flightdisplay
tar czf ~/flightdisplay-backup.tgz config.ini types_extra.txt cache/runtime.json background.png map_meta.json
```

This backup contains secrets: do not share it.

### 12.5 System updates

```
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

### 12.6 Viewing the logs

| Need | Command |
|---|---|
| Display program live | `fd logs` (or the Logs tab of webadmin) |
| Display program, last lines | `journalctl -u flightdisplay -n 100 --no-pager` |
| webadmin | `journalctl -u flightadmin -n 100 --no-pager` |
| Screen sleep guard | `journalctl -t flight-screen-guard --no-pager` |
| Automatic installer | `less ~/flightdisplay-install.log` |
| Kernel | `journalctl -k -n 100 --no-pager` |

---

## 13. Troubleshooting

| Symptom | Likely cause and solution |
|---|---|
| The installer stops at a step | Read the message shown and `~/flightdisplay-install.log`. Fix (Internet connection, disk space), then run the same command again. |
| "Ne lancez pas ce script avec sudo" (do not run this script with sudo) | Run again with your normal user, without `sudo`: the installer asks for sudo itself. |
| The installer does not offer any input | It reads the terminal keyboard: run it in an interactive SSH session (not from a non-interactive script). |
| Black screen when the service starts | Check `fd logs`. Make sure the user is in the `video` and `render` groups (service: `SupplementaryGroups`), and that `background.png` exists. |
| `pygame.error: EGL not initialized`, the service restarts in a loop | EGL libraries missing (common on Raspberry Pi OS Lite): `sudo apt install -y libegl1 libegl-mesa0 libgles2`, then `sudo systemctl restart flightdisplay`. If the error persists, add `libegl-dev`. Also check that `/dev/dri/card0` exists. |
| "premiere image apres" never shown | The program could not open the screen: run it by hand (`./venv/bin/python main.py`) and read the error. |
| The map does not build: `NoOptionError` error | The `carto_key` key is missing from `config.ini`, section `[map]`: set it (Settings, Map and position). |
| The map does not build: HTTP 401 or 403 error | CARTO key probably invalid, expired or badly copied: enter it again in Settings, Map and position, then rebuild. |
| The map does not build for another reason | Read the output in the "Map rebuild" section (Settings, Map and position). Check the Python path (Settings, Application and system) and the script dependencies (4.3). |
| "ATTENTION : la carte a ete generee pour d'autres coordonnees" (the map was generated for other coordinates) | Rebuild the map (Settings, Map and position, "Rebuild the map"). |
| 429 error in the logs | Too many requests: increase the request interval and the pause between details (Settings, Flightradar24). The throttling is automatic but temporary. |
| "ATTENTION : horloge du systeme decalee par rapport a FR24" (system clock out of step with FR24) | The Pi's clock is wrong: check `timedatectl status` and the Internet connection. |
| `type inconnu (icone par defaut) : XXXX` | Add the type in Settings, Aircraft types. |
| No aircraft displayed | Check the latitude, the longitude, the radius and the maximum tracked altitude. The status line at the bottom left gives the number of tracked aircraft. |
| CPU usage close to 90% | Normal at times on a Pi Zero. Lowering the frames per second (Settings, Display) or rebuilding the map at 1280×720 directly reduces the load. |
| The Windows window does not change layout when resized | Normal: the map image is scaled. For another working size, change `width` and `height` and rebuild the map (8.5). |
| No sound | `aplay -l` must list an output. Check that `SDL_AUDIODRIVER=dummy` is not in the service, that "Sound" is enabled in Settings and in Control (crossed-out speaker icon on screen otherwise), and read `fd logs` for `son indisponible`. |
| A sound plays at startup although "Sound when the program starts" and "Simulate an alert" are unticked | The test counter of `cache/runtime.json` is not remembered when `main.py` loads: a line `rt_refresh(True)` is needed at module level (no indentation, after the definition of `rt_refresh`). Otherwise, an aircraft was already in the alert zone. |
| The sound cannot be muted remotely | The program and webadmin must run with the same user, and `cache/runtime.json` must be writable by it. |
| The webadmin page does not open | `sudo systemctl status flightadmin` and `journalctl -u flightadmin -n 50`. |
| After a port change, the page does not come back | Open `http://flightradarpi.local:<new port>`. In case of a settings error: edit `config.ini` over SSH (section `[server]`) then `sudo systemctl restart flightadmin`. |
| webadmin password lost | Edit `config.ini` over SSH (section `[server]`, line `password =`), then `sudo systemctl restart flightadmin`. |
| "sudo: a password is required" | `/etc/sudoers.d/flightadmin` is missing or the `systemctl` path differs: run the installer again while keeping the configuration (step 9). |
| Empty logs in webadmin | The user must be able to read the journal (`systemd-journal` group, added by the service). The journal is in memory by default: it is cleared at each reboot of the Pi. |
| The sleep does not cut the signal (`dpms` stays `On`) | The sleep script is not the framebuffer version (6.2): `grep -c "fb0/blank" /usr/local/bin/flight-screen` must return at least `1`. Run the installer again while keeping the configuration (step 9) to reinstall it. |
| The screen wakes up by itself during the sleep | The guard puts it back to sleep in less than 20 seconds. Read `journalctl -t flight-screen-guard` for the times, then follow the procedure of 6.2 (HDMI fix, monitor input detection, wake-up command, reboot, CEC). |
| The guard cuts the screen again in a loop every 20 seconds | Old version of the guard (based on `setterm`): run the installer again (step 9). |
| After the update, my custom sleep has disappeared | Step 9 of the installer rewrites `flight-screen` and `flight-screen-guard`. Keep a copy of your changes. |
| The screen only wakes up when I turn it off from Home Assistant | Check that the entity's command is not published with "retain" on the MQTT server (11.3), and read `journalctl -t sudo \| grep flight-screen` to see who started the wake-up. |
| The monitor does not turn off during sleep | Check `cat /sys/class/drm/card*-HDMI-A-*/dpms`: `Off` after the sleep. Otherwise try DDC/CI (6.2). |
| The Control tiles are in two columns | On a computer, the four columns apply from 860 px wide; below that, the tiles go into two columns. |
| The schedule does not turn the screen on or off | Check that "Enable the schedule" is ticked and that the calendar contains ranges. Check the Pi time ("Time" tile, 3.4): the schedule follows its time zone. The action only happens at the scheduled times (a manual shutdown in the middle of a range is not corrected). An error message under "Next action" shows whether the `flight-screen` command failed (sudo rights: installer step 9). The schedule stops with webadmin (`sudo systemctl status flightadmin`). |
| MQTT: "paho missing" | `sudo apt install python3-paho-mqtt` then `sudo systemctl restart flightadmin`. |
| MQTT: "refuse" (refused) | Credentials or rights (ACL) of the MQTT server. |
| Entities missing in Home Assistant | Check the MQTT integration, `discovery_prefix`, the same server, then "Reconnect / republish". |
| Updates: "check failed" | webadmin cannot reach GitHub (Internet, DNS) or the installation is not a Git repository: read the message shown in the Updates tab. |
| Updates: "software files modified locally" | Files tracked by Git differ from GitHub (copied by hand, for example). See which with `git status`, then `git checkout <file>` or `git stash` (12.1). `config.ini` is never concerned. |
| Updates: "going back to the previous version" | The new version did not pass the code check or does not start. The old version still works; the update log gives the cause. |
| After a language change, the screen stays in the old language | The display program reads the language at startup: "Save and apply", or `fd restart`. |
| A language added in `lang/` does not appear | The file must be named `<code>.json` (2 or 3 lowercase letters) and contain valid JSON; restart webadmin. Check: `python3 lang/check_lang.py <code>` (12.3). |
| No label appears next to the aircraft | All the items are hidden in Settings, Aircraft labels (8.7). |
| The photo panel never appears in a corner | That corner is unticked in Settings, Photo panel (8.6). If all four corners are unticked, there is no restriction. |
| The Program tile shows fewer frames per second than the target | The Pi Zero cannot keep the pace: lower `fps`, switch the map to 1280×720, or limit the number of aircraft (maximum tracked altitude). |
| "disk X % full" alert | The SD card is approaching saturation. Open Settings, Storage and photos: clear the photo cache, then look for big files (`du -h --max-depth=1 ~ \| sort -h`, logs, old backups). See also 6.3. |
| Updates: no new version although commits were pushed | The channel is "Stable": only tagged `vX.Y.Z` versions are offered (12.2). Switch to the "Development" channel (Settings, Updates) to receive every commit. |
| Restore: "invalid backup file" | The file must be a zip produced by Settings, Backup (containing `config.ini`, possibly `types_extra.txt`, `runtime.json`, `manifest.json` and the map `background.png` with `map_meta.json`), unmodified, under 1 MB per file (8 MB for the map image, whose dimensions must match `map_meta.json`). |
| Unstable Wi-Fi | Disable power saving (6.4). |

---

## 14. Uninstalling

```
sudo systemctl disable --now flightadmin flightdisplay flight-screen-guard
sudo rm /etc/systemd/system/flightadmin.service /etc/systemd/system/flightdisplay.service /etc/systemd/system/flight-screen-guard.service
sudo rm /etc/sudoers.d/flightadmin /usr/local/bin/flight-screen /usr/local/bin/flight-screen-guard /usr/local/bin/fd
sudo systemctl daemon-reload
rm -rf ~/flightdisplay ~/flightdisplay-install.log
```

To undo the sleep fix, restore the old file:

```
sudo cp /boot/firmware/cmdline.txt.bak /boot/firmware/cmdline.txt
```
