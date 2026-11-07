#!/usr/bin/env python3
"""Pont MQTT / Home Assistant pour webadmin (decouverte automatique).

Entites creees : ecran (switch), son des alertes (switch), volume (number), temperature (sensor).
Necessite paho-mqtt : sudo apt install python3-paho-mqtt
"""
import json, re, socket, threading, time

import i18n

try:
    import paho.mqtt.client as paho
except ImportError:
    paho = None


def parse_onoff(payload):
    p = payload.strip().upper()
    if p in ("ON", "TRUE", "1"):
        return True
    if p in ("OFF", "FALSE", "0"):
        return False
    return None


class Bridge:
    def __init__(self, api):
        self.api = api
        self.status = "off"
        self.client = None
        self.last = {}
        self.t_full = 0.0
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.enabled = False
        host = re.sub(r"[^a-z0-9]+", "_", socket.gethostname().lower()).strip("_") or "pi"
        self.uid = "flightdisplay_" + host

    def configure(self, ini):
        g = lambda k, d="": ini.get("mqtt", k, fallback=d)

        def num(fn, k, d):
            try:
                return fn("mqtt", k, fallback=d)
            except ValueError:
                return d

        self.enabled = num(ini.getboolean, "enabled", False)
        self.host = g("host").strip()
        self.port = num(ini.getint, "port", 1883)
        self.user, self.pw = g("user").strip(), g("password")
        self.tls = num(ini.getboolean, "tls", False)
        self.base = g("base_topic", "flightdisplay").strip().strip("/") or "flightdisplay"
        self.prefix = g("discovery_prefix", "homeassistant").strip().strip("/") or "homeassistant"
        self.name = g("device_name", "Flight display").strip() or "Flight display"
        self.interval = max(5.0, num(ini.getfloat, "interval", 30.0))

    def t(self, suffix):
        return self.base + "/" + suffix

    def start(self):
        self.status = "off"
        if not self.enabled:
            return
        if paho is None:
            self.status = "paho manquant"
            print("MQTT : paho-mqtt manquant -> sudo apt install python3-paho-mqtt", flush=True)
            return
        if not self.host:
            self.status = "host manquant"
            print("MQTT : serveur non renseigné", flush=True)
            return
        try:
            c = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id=self.uid)
        except AttributeError:
            c = paho.Client(client_id=self.uid)
        if self.user:
            c.username_pw_set(self.user, self.pw)
        if self.tls:
            c.tls_set()
        c.will_set(self.t("availability"), "offline", retain=True)
        c.on_connect = lambda *a, **k: self._on_connect(c, *a[2:], **k)
        c.on_disconnect = lambda *a, **k: self._on_disconnect(c)
        c.on_message = lambda cl, ud, msg: self._on_message(c, msg)
        c.reconnect_delay_set(2, 60)
        self.client = c
        self.status = "deconnecte"
        self.stop_evt = threading.Event()
        c.connect_async(self.host, self.port, keepalive=60)
        c.loop_start()
        threading.Thread(target=self._loop, args=(self.stop_evt, c), daemon=True).start()

    def stop(self):
        self.stop_evt.set()
        c, self.client = self.client, None
        if c is not None:
            try:
                if self.status == "connecte":
                    c.publish(self.t("availability"), "offline", qos=0, retain=True)
                    time.sleep(0.2)
                c.disconnect()
                c.loop_stop()
            except Exception:
                pass
        self.status = "off"

    def restart(self, ini):
        self.stop()
        self.configure(ini)
        self.start()

    def _pub(self, topic, payload, retain=True):
        try:
            self.client.publish(topic, payload, qos=0, retain=retain)
        except Exception as e:
            print("MQTT publish :", e, flush=True)

    def _on_connect(self, c, flags=None, rc=0, properties=None):
        if c is not self.client:
            return
        ok = (rc == 0) if isinstance(rc, int) else not getattr(rc, "is_failure", False)
        if not ok:
            self.status = "refuse (" + str(rc) + ")"
            print("MQTT : connexion refusée", rc, flush=True)
            return
        self.status = "connecte"
        print("MQTT : connecté à", self.host, flush=True)
        for sub in ("screen/set", "sound/set", "volume/set"):
            c.subscribe(self.t(sub), 0)
        c.subscribe(self.prefix + "/status", 0)
        self._announce()

    def _on_disconnect(self, c):
        if c is self.client:
            self.status = "deconnecte"

    def _announce(self):
        self._discovery()
        self._pub(self.t("availability"), "online")
        self.last = {}
        self.publish_states(force=True)

    def _discovery(self):
        dev = {"identifiers": [self.uid], "name": self.name, "manufacturer": "Raspberry Pi", "model": "Flight display"}
        avail = self.t("availability")
        ents = [
            ("switch", "screen", {"name": i18n.tr("Écran"), "icon": "mdi:monitor",
                                  "command_topic": self.t("screen/set"), "state_topic": self.t("screen/state")}),
            ("switch", "sound", {"name": i18n.tr("Son des alertes"), "icon": "mdi:volume-high",
                                 "command_topic": self.t("sound/set"), "state_topic": self.t("sound/state")}),
            ("number", "volume", {"name": i18n.tr("Volume des alertes"), "icon": "mdi:volume-medium", "min": 0, "max": 100,
                                  "step": 5, "mode": "slider", "unit_of_measurement": "%",
                                  "command_topic": self.t("volume/set"), "state_topic": self.t("volume/state")}),
            ("sensor", "temperature", {"name": i18n.tr("Température"), "device_class": "temperature",
                                       "unit_of_measurement": "°C", "state_class": "measurement",
                                       "state_topic": self.t("temperature/state")}),
            ("sensor", "aircraft", {"name": i18n.tr("Avions en vol"), "icon": "mdi:airplane", "state_class": "measurement",
                                    "state_topic": self.t("aircraft/state")}),
            ("sensor", "aircraft_ground", {"name": i18n.tr("Avions au sol"), "icon": "mdi:airplane-landing", "state_class": "measurement",
                                           "state_topic": self.t("aircraft_ground/state")}),
            ("sensor", "aircraft_zone", {"name": i18n.tr("Avions dans la zone d'alerte"), "icon": "mdi:airplane-alert",
                                         "state_class": "measurement", "state_topic": self.t("aircraft_zone/state")}),
            ("binary_sensor", "alert", {"name": i18n.tr("Alerte en cours"), "icon": "mdi:alert-circle", "payload_on": "ON",
                                        "payload_off": "OFF", "state_topic": self.t("alert/state")}),
            ("binary_sensor", "program", {"name": i18n.tr("Programme actif"), "device_class": "running", "payload_on": "ON",
                                          "payload_off": "OFF", "state_topic": self.t("program/state")}),
            ("sensor", "fps", {"name": i18n.tr("Images par seconde"), "icon": "mdi:speedometer", "unit_of_measurement": "fps",
                               "state_class": "measurement", "entity_category": "diagnostic", "state_topic": self.t("fps/state")}),
            ("sensor", "cpu", {"name": i18n.tr("Utilisation CPU"), "icon": "mdi:cpu-32-bit", "unit_of_measurement": "%",
                               "state_class": "measurement", "entity_category": "diagnostic", "state_topic": self.t("cpu/state")}),
            ("sensor", "memory", {"name": i18n.tr("Mémoire utilisée"), "icon": "mdi:memory", "unit_of_measurement": "%",
                                  "state_class": "measurement", "entity_category": "diagnostic", "state_topic": self.t("memory/state")}),
            ("sensor", "disk", {"name": i18n.tr("Disque utilisé"), "icon": "mdi:sd", "unit_of_measurement": "%",
                                "state_class": "measurement", "entity_category": "diagnostic", "state_topic": self.t("disk/state")}),
        ]
        for comp, key, cfg in ents:
            cfg.update(unique_id=f"{self.uid}_{key}", availability_topic=avail, device=dev)
            self._pub(f"{self.prefix}/{comp}/{self.uid}/{key}/config", json.dumps(cfg, ensure_ascii=False))

    def collect(self):
        si = self.api["sysinfo"]()
        ss = self.api["sound_state"]()
        d = {"screen": "OFF" if self.api["screen_off"]() else "ON",
             "sound": "ON" if (ss["sound_enabled"] and not ss["muted"]) else "OFF",
             "volume": str(int(round(ss["volume"] * 100)))}
        if si.get("temp") is not None:
            d["temperature"] = f"{round(si['temp'] * 2) / 2:.1f}"
        live = self.api["live"]() if "live" in self.api else None
        d["program"] = "ON" if self.api.get("service_active", lambda: False)() else "OFF"
        d["aircraft"] = str(live["aircraft"]) if live else "unavailable"
        d["aircraft_ground"] = str(live["ground"]) if live else "unavailable"
        d["aircraft_zone"] = str(live["zone"]) if live else "unavailable"
        d["alert"] = "ON" if live and live["zone"] > 0 else "OFF"
        d["fps"] = f"{live['fps']:.1f}" if live else "unavailable"
        cpu = self.api["cpu"]() if "cpu" in self.api else None
        if cpu is not None:
            d["cpu"] = f"{cpu:.0f}"
        if si.get("mem_total"):
            d["memory"] = f"{100.0 * (si['mem_total'] - si['mem_avail']) / si['mem_total']:.0f}"
        disk = self.api["disk"]() if "disk" in self.api else None
        if disk:
            d["disk"] = f"{disk['pct']:.1f}"
        return d

    def publish_states(self, force=False):
        if self.client is None:
            return
        with self.lock:
            now = time.time()
            full = force or now - self.t_full >= self.interval
            for k, v in self.collect().items():
                if full or self.last.get(k) != v:
                    self._pub(self.t(k + "/state"), v)
                    self.last[k] = v
            if full:
                self.t_full = now

    def _loop(self, stop, client):
        while not stop.wait(5):
            if self.status == "connecte" and client is self.client:
                try:
                    self.publish_states()
                except Exception as e:
                    print("MQTT état :", e, flush=True)

    def _set_screen(self, on):
        try:
            if on != (not self.api["screen_off"]()):
                ok, out = self.api["screen"]("on" if on else "off")
                if not ok:
                    print("MQTT écran :", out, flush=True)
        finally:
            self.publish_states(force=True)

    def _on_message(self, c, msg):
        if c is not self.client:
            return
        try:
            payload = msg.payload.decode("utf-8", "replace").strip()
            if msg.topic == self.prefix + "/status":
                if payload == "online":
                    self._announce()
            elif msg.topic == self.t("screen/set"):
                on = parse_onoff(payload)
                if on is not None:
                    threading.Thread(target=self._set_screen, args=(on,), daemon=True).start()
            elif msg.topic == self.t("sound/set"):
                on = parse_onoff(payload)
                if on is not None:
                    self.api["sound_update"]({"muted": not on})
                    self.publish_states(force=True)
            elif msg.topic == self.t("volume/set"):
                self.api["sound_update"]({"volume": float(payload) / 100.0})
                self.publish_states(force=True)
        except Exception as e:
            print("MQTT commande :", type(e).__name__, e, flush=True)
