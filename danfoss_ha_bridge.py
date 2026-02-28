# #!/usr/bin/env python3
“””
Danfoss TLX Pro → Home Assistant Bridge

Daemon-Script, das den Danfoss TLX Pro Wechselrichter über EtherLynx
(UDP Port 48004) abfragt und die Daten per MQTT an Home Assistant
publiziert.

Alternative: Kann auch als command_line-Sensor aufgerufen werden
(Modus –mode json).

Installation:
1. Dieses Script + danfoss_etherlynx.py nach /config/scripts/ kopieren
2. Konfiguration in danfoss_config.yaml anpassen
3. Starten als Daemon oder via command_line Sensor

Voraussetzungen:
- Python 3.9+
- paho-mqtt (pip install paho-mqtt)  [nur für MQTT-Modus]
- Netzwerkzugriff auf den Inverter (UDP Port 48004)
“””

import json
import logging
import signal
import sys
import time
import os
from pathlib import Path
from typing import Dict, Any, Optional

# Eigene Bibliothek importieren

sys.path.insert(0, os.path.dirname(os.path.abspath(**file**)))
from danfoss_etherlynx import (
DanfossEtherLynx, TLX_PARAMETERS, OPERATION_MODES,
MODULE_COMM_BOARD,
)

logger = logging.getLogger(“danfoss_ha_bridge”)

# ============================================================================

# Konfiguration

# ============================================================================

from dataclasses import dataclass

@dataclass
class BridgeConfig:
“”“Konfiguration für die HA-Bridge.”””
# Inverter
inverter_ip: str = “192.168.1.100”
inverter_serial: str = “”  # Leer = auto-discovery

```
# MQTT
mqtt_host: str = "localhost"
mqtt_port: int = 1883
mqtt_user: str = ""
mqtt_password: str = ""
mqtt_topic_prefix: str = "danfoss_tlx"
mqtt_discovery_prefix: str = "homeassistant"

# Polling
poll_interval_realtime: int = 15    # Sekunden
poll_interval_energy: int = 300     # 5 Minuten
poll_interval_system: int = 3600    # 1 Stunde

# Allgemein
log_level: str = "INFO"
pv_strings: int = 2  # Anzahl PV-Strings (2 oder 3)
```

def load_config(config_path: str = None) -> BridgeConfig:
“”“Lädt die Konfiguration aus YAML oder Umgebungsvariablen.”””
config = BridgeConfig()

```
# Versuche YAML zu laden
if config_path and Path(config_path).exists():
    try:
        import yaml
        with open(config_path) as f:
            data = yaml.safe_load(f)
        if data:
            for key, value in data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
        logger.info(f"Konfiguration geladen: {config_path}")
    except ImportError:
        logger.warning("PyYAML nicht installiert, verwende Umgebungsvariablen")
    except Exception as e:
        logger.error(f"Fehler beim Laden der Konfig: {e}")

# Umgebungsvariablen überschreiben (für Docker/HA Add-on)
env_map = {
    "DANFOSS_IP": "inverter_ip",
    "DANFOSS_SERIAL": "inverter_serial",
    "MQTT_HOST": "mqtt_host",
    "MQTT_PORT": "mqtt_port",
    "MQTT_USER": "mqtt_user",
    "MQTT_PASSWORD": "mqtt_password",
    "MQTT_TOPIC": "mqtt_topic_prefix",
    "POLL_REALTIME": "poll_interval_realtime",
    "POLL_ENERGY": "poll_interval_energy",
    "PV_STRINGS": "pv_strings",
    "LOG_LEVEL": "log_level",
}

for env_key, config_key in env_map.items():
    value = os.environ.get(env_key)
    if value is not None:
        # Typ-Konvertierung
        current = getattr(config, config_key)
        if isinstance(current, int):
            value = int(value)
        setattr(config, config_key, value)

return config
```

# ============================================================================

# MQTT Auto-Discovery für Home Assistant

# ============================================================================

def publish_mqtt_discovery(mqtt_client, config: BridgeConfig, serial: str):
“”“Publiziert MQTT Auto-Discovery-Konfigurationen für alle Sensoren.

```
Home Assistant erkennt die Sensoren automatisch über das
Discovery-Prefix (default: homeassistant/).
"""
device_info = {
    "identifiers": [f"danfoss_tlx_{serial}"],
    "name": f"Danfoss TLX Pro ({serial})",
    "manufacturer": "Danfoss Solar Inverters",
    "model": "TLX Pro",
    "serial_number": serial,
    "sw_version": "EtherLynx",
}

for key, param in TLX_PARAMETERS.items():
    # String 3 überspringen wenn nur 2 Strings konfiguriert
    if config.pv_strings < 3 and "_3" in key and "pv_" in key:
        continue
    
    # Sensor-Konfig für MQTT Discovery
    unique_id = f"danfoss_tlx_{serial}_{key}"
    topic = f"{config.mqtt_discovery_prefix}/sensor/{unique_id}/config"
    
    payload = {
        "name": param.name,
        "unique_id": unique_id,
        "state_topic": f"{config.mqtt_topic_prefix}/{key}",
        "device": device_info,
        "availability_topic": f"{config.mqtt_topic_prefix}/status",
        "payload_available": "online",
        "payload_not_available": "offline",
    }
    
    if param.unit:
        payload["unit_of_measurement"] = param.unit
    if param.device_class:
        payload["device_class"] = param.device_class
    if param.state_class:
        payload["state_class"] = param.state_class
    
    mqtt_client.publish(topic, json.dumps(payload), retain=True)

# Betriebsmodus als Text-Sensor
unique_id = f"danfoss_tlx_{serial}_operation_mode_text"
topic = f"{config.mqtt_discovery_prefix}/sensor/{unique_id}/config"
payload = {
    "name": "Betriebsmodus (Text)",
    "unique_id": unique_id,
    "state_topic": f"{config.mqtt_topic_prefix}/operation_mode_text",
    "device": device_info,
    "availability_topic": f"{config.mqtt_topic_prefix}/status",
    "icon": "mdi:solar-power",
}
mqtt_client.publish(topic, json.dumps(payload), retain=True)

logger.info(f"MQTT Auto-Discovery publiziert für {len(TLX_PARAMETERS)} Sensoren")
```

def publish_values(mqtt_client, config: BridgeConfig, values: Dict[str, Any]):
“”“Publiziert Parameterwerte über MQTT.”””
for key, value in values.items():
if value is not None:
topic = f”{config.mqtt_topic_prefix}/{key}”
mqtt_client.publish(topic, str(value), retain=True)

# ============================================================================

# MQTT Daemon-Modus

# ============================================================================

def run_mqtt_daemon(config: BridgeConfig):
“”“Hauptschleife: Pollt den Inverter und publiziert über MQTT.”””
try:
import paho.mqtt.client as mqtt
except ImportError:
logger.error(
“paho-mqtt nicht installiert! “
“Installieren mit: pip install paho-mqtt”
)
sys.exit(1)

```
# MQTT verbinden
mqtt_client = mqtt.Client(client_id="danfoss_etherlynx_bridge")
if config.mqtt_user:
    mqtt_client.username_pw_set(config.mqtt_user, config.mqtt_password)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("MQTT verbunden")
        client.publish(
            f"{config.mqtt_topic_prefix}/status", "online", retain=True
        )
    else:
        logger.error(f"MQTT Verbindungsfehler: {rc}")

def on_disconnect(client, userdata, rc):
    logger.warning(f"MQTT getrennt (rc={rc})")

mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.will_set(
    f"{config.mqtt_topic_prefix}/status", "offline", retain=True
)

try:
    mqtt_client.connect(config.mqtt_host, config.mqtt_port)
except Exception as e:
    logger.error(f"MQTT Verbindung fehlgeschlagen: {e}")
    sys.exit(1)

mqtt_client.loop_start()

# EtherLynx Client
client = DanfossEtherLynx(config.inverter_ip)

if config.inverter_serial:
    client.inverter_serial = config.inverter_serial
else:
    serial = client.discover()
    if not serial:
        logger.error(
            "Inverter nicht gefunden. Prüfen Sie:\n"
            "  1. IP-Adresse korrekt?\n"
            "  2. Inverter eingeschaltet (Tageslicht)?\n"
            "  3. Ethernet-Kabel verbunden?\n"
            "  4. UDP Port 48004 nicht blockiert?"
        )
        sys.exit(1)

# MQTT Discovery publizieren
publish_mqtt_discovery(mqtt_client, config, client.inverter_serial)

# Signal-Handler für sauberes Beenden
running = True
def signal_handler(sig, frame):
    nonlocal running
    logger.info("Beende...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Polling-Loop
last_realtime = 0
last_energy = 0
last_system = 0
consecutive_errors = 0
MAX_ERRORS = 10

logger.info(
    f"Starte Polling: Realtime alle {config.poll_interval_realtime}s, "
    f"Energie alle {config.poll_interval_energy}s"
)

while running:
    now = time.time()
    
    try:
        # Realtime-Daten (häufig)
        if now - last_realtime >= config.poll_interval_realtime:
            data = client.read_realtime()
            if data:
                # Betriebsmodus-Text hinzufügen
                if "operation_mode" in data:
                    data["operation_mode_text"] = client.get_status_text(
                        data["operation_mode"]
                    )
                publish_values(mqtt_client, config, data)
                consecutive_errors = 0
                last_realtime = now
            else:
                consecutive_errors += 1
                logger.warning(
                    f"Keine Realtime-Daten "
                    f"({consecutive_errors}/{MAX_ERRORS})"
                )
        
        # Energie-Daten (selten)
        if now - last_energy >= config.poll_interval_energy:
            data = client.read_energy()
            if data:
                publish_values(mqtt_client, config, data)
                last_energy = now
        
        # System-Daten (sehr selten)
        if now - last_system >= config.poll_interval_system:
            system_keys = [
                "nominal_power", "sw_version", "hardware_type"
            ]
            data = client.read_parameters(system_keys)
            if data:
                publish_values(mqtt_client, config, data)
                last_system = now
        
        # Zu viele aufeinanderfolgende Fehler → Inverter offline
        if consecutive_errors >= MAX_ERRORS:
            mqtt_client.publish(
                f"{config.mqtt_topic_prefix}/status",
                "offline", retain=True
            )
            logger.warning(
                f"Inverter nicht erreichbar nach {MAX_ERRORS} Versuchen. "
                f"Warte 60s..."
            )
            time.sleep(60)
            consecutive_errors = 0
            # Neuen Discovery-Versuch
            client.discover()
            if client.inverter_serial:
                mqtt_client.publish(
                    f"{config.mqtt_topic_prefix}/status",
                    "online", retain=True
                )
        
    except Exception as e:
        logger.error(f"Fehler in der Hauptschleife: {e}", exc_info=True)
        consecutive_errors += 1
    
    # Kurz schlafen
    time.sleep(1)

# Aufräumen
mqtt_client.publish(
    f"{config.mqtt_topic_prefix}/status", "offline", retain=True
)
mqtt_client.loop_stop()
mqtt_client.disconnect()
client.close()
logger.info("Beendet.")
```

# ============================================================================

# JSON-Modus (für command_line Sensor)

# ============================================================================

def run_json_mode(config: BridgeConfig, mode: str = “all”):
“”“Einmalige Abfrage, Ausgabe als JSON auf stdout.

```
Ideal für Home Assistant command_line Sensor-Integration.
"""
with DanfossEtherLynx(config.inverter_ip) as client:
    if config.inverter_serial:
        client.inverter_serial = config.inverter_serial
    else:
        serial = client.discover()
        if not serial:
            # Offline - leeres Ergebnis
            print(json.dumps({"status": "offline"}))
            return 1
    
    if mode == "realtime":
        data = client.read_realtime()
    elif mode == "energy":
        data = client.read_energy()
    else:
        data = client.read_all()
    
    if data:
        data["status"] = "online"
        data["inverter_serial"] = client.inverter_serial
        if "operation_mode" in data:
            data["operation_mode_text"] = client.get_status_text(
                data["operation_mode"]
            )
    else:
        data = {"status": "offline"}
    
    print(json.dumps(data, ensure_ascii=False))
    return 0
```

# ============================================================================

# Entry Point

# ============================================================================

def main():
import argparse

```
parser = argparse.ArgumentParser(
    description="Danfoss TLX Pro → Home Assistant Bridge (EtherLynx/UDP)"
)
parser.add_argument(
    "--config", "-c",
    default=None,
    help="Pfad zur YAML-Konfigurationsdatei"
)
parser.add_argument(
    "--ip",
    help="IP-Adresse des Inverters (überschreibt Konfig)"
)
parser.add_argument(
    "--serial",
    help="Inverter-Seriennummer (überspringt Discovery)"
)
parser.add_argument(
    "--mode",
    choices=["mqtt", "json", "realtime", "energy"],
    default="json",
    help="Betriebsmodus (default: json)"
)
parser.add_argument(
    "--mqtt-host",
    help="MQTT Broker Host"
)
parser.add_argument(
    "--pv-strings",
    type=int, choices=[2, 3], default=2,
    help="Anzahl PV-Strings (2 oder 3)"
)
parser.add_argument(
    "--verbose", "-v",
    action="store_true",
    help="Debug-Ausgabe"
)

args = parser.parse_args()

# Konfiguration laden
config = load_config(args.config)

# CLI-Argumente überschreiben Konfig
if args.ip:
    config.inverter_ip = args.ip
if args.serial:
    config.inverter_serial = args.serial
if args.mqtt_host:
    config.mqtt_host = args.mqtt_host
if args.pv_strings:
    config.pv_strings = args.pv_strings
if args.verbose:
    config.log_level = "DEBUG"

# Logging
logging.basicConfig(
    level=getattr(logging, config.log_level.upper()),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,  # JSON geht auf stdout, Logs auf stderr
)

# Modus
if args.mode == "mqtt":
    run_mqtt_daemon(config)
elif args.mode in ("json", "realtime", "energy"):
    return run_json_mode(config, args.mode)

return 0
```

if **name** == “**main**”:
sys.exit(main() or 0)
