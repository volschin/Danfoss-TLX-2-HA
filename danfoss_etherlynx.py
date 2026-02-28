# #!/usr/bin/env python3
“””
Danfoss EtherLynx Protocol - Python Implementation

Kommuniziert mit Danfoss TLX Pro Wechselrichtern über das
EtherLynx-Protokoll (UDP Port 48004).

Basiert auf dem offiziellen “ComLynx and EtherLynx User Guide”
von Danfoss Solar Inverters A/S (Revision 20, 2013-04-22).

Autor: Generiert für Home Assistant Integration
Lizenz: MIT
“””

import socket
import struct
import logging
import json
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Dict, List, Any, Tuple

logger = logging.getLogger(**name**)

# ============================================================================

# Protokoll-Konstanten (aus Danfoss EtherLynx User Guide, Kapitel 5)

# ============================================================================

ETHERLYNX_PORT = 48004
ETHERLYNX_HEADER_SIZE = 52  # 13 Doppelwörter × 4 Bytes
ETHERLYNX_DATA_OFFSET = 0x0D  # Minimum = 13 (32-bit Wörter)

# Timeout für UDP-Antworten (Sekunden)

DEFAULT_TIMEOUT = 3.0
DISCOVERY_TIMEOUT = 5.0

# Dummy-Seriennummer für den “Master” (PC/HA)

# Laut Doku: “In case the source is some other device other than an inverter,

# e.g. PC, then this field must contain a dummy serial number not present

# in the inverter network.”

MASTER_SERIAL = “HA_MASTER”

class MessageID(IntEnum):
“”“EtherLynx Message IDs (Kapitel 5.4)”””
PING = 0x01
GET_SET_PARAMETER = 0x02
GET_SET_TEXT = 0x03

class Flag:
“”“EtherLynx Flags (Kapitel 5.1, Byte 37)”””
RESPONSE    = 0x40  # Bit 14: R - 0=Request, 1=Response
RES_NEEDED  = 0x20  # Bit 13: RES - Response erwartet
SYN         = 0x10  # Bit 12: SYN - Synchronisierung (reserviert)
FB          = 0x08  # Bit 11: FB - Full Broadcast
GB          = 0x04  # Bit 10: GB - Group Broadcast
SB          = 0x02  # Bit 9:  SB - Single Broadcast
ERROR       = 0x01  # Bit 8:  E - Error

class DataType(IntEnum):
“”“Parameter-Datentypen (Kapitel 5.4.2 / Appendix C)”””
RESERVED     = 0x0
BOOLEAN      = 0x1
SIGNED8      = 0x2
SIGNED16     = 0x3
SIGNED32     = 0x4
UNSIGNED8    = 0x5
UNSIGNED16   = 0x6
UNSIGNED32   = 0x7
FLOAT        = 0x8
VISIBLE_STR  = 0x9
PACKED_BYTES = 0xA
PACKED_WORDS = 0xB
FIX_POINT    = 0xC

# Module ID für TLX Pro (Kapitel 3.6)

MODULE_COMM_BOARD = 8

# ============================================================================

# Parameter-Definitionen für TLX Pro (Appendix C, Kapitel 6.3)

# ============================================================================

@dataclass
class ParameterDef:
“”“Definition eines Wechselrichter-Parameters”””
name: str              # Anzeigename
index: int             # Parameter Index
subindex: int          # Parameter Subindex
data_type: int         # Erwarteter Datentyp
module_id: int         # Modul-ID (8 = Communication Board)
unit: str = “”         # Einheit
scale: float = 1.0     # Skalierungsfaktor (Wert × scale = Realwert)
description: str = “”  # Beschreibung
device_class: str = “” # HA device_class
state_class: str = “”  # HA state_class

# Vollständige Parameter-Tabelle für Danfoss TLX Pro

# Quelle: Appendix C - Inverter Parameters (Kapitel 6.3)

TLX_PARAMETERS: Dict[str, ParameterDef] = {
# ── Rohwerte (Index 0x01) ──────────────────────────────────────────
“total_energy”: ParameterDef(
name=“Gesamtproduktion”,
index=0x01, subindex=0x02, data_type=DataType.UNSIGNED32,
module_id=MODULE_COMM_BOARD, unit=“Wh”, scale=1.0,
description=“Total Energy Production über Lebensdauer”,
device_class=“energy”, state_class=“total_increasing”,
),
“energy_today”: ParameterDef(
name=“Produktion heute”,
index=0x01, subindex=0x04, data_type=DataType.UNSIGNED32,
module_id=MODULE_COMM_BOARD, unit=“Wh”, scale=1.0,
description=“Energieproduktion seit letztem Einschalten”,
device_class=“energy”, state_class=“total_increasing”,
),

```
# ── Geglättete Messwerte (Index 0x02) ──────────────────────────────
# PV-Strings (DC-Seite)
"pv_voltage_1": ParameterDef(
    name="PV Spannung String 1",
    index=0x02, subindex=0x28, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="PV Voltage, input 1 [V/10]",
    device_class="voltage", state_class="measurement",
),
"pv_voltage_2": ParameterDef(
    name="PV Spannung String 2",
    index=0x02, subindex=0x29, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="PV Voltage, input 2 [V/10]",
    device_class="voltage", state_class="measurement",
),
"pv_voltage_3": ParameterDef(
    name="PV Spannung String 3",
    index=0x02, subindex=0x2A, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="PV Voltage, input 3 [V/10] (nur TLX 10k/12.5k/15k)",
    device_class="voltage", state_class="measurement",
),
"pv_current_1": ParameterDef(
    name="PV Strom String 1",
    index=0x02, subindex=0x2D, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="A", scale=0.001,
    description="PV Current, input 1 [mA]",
    device_class="current", state_class="measurement",
),
"pv_current_2": ParameterDef(
    name="PV Strom String 2",
    index=0x02, subindex=0x2E, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="A", scale=0.001,
    description="PV Current, input 2 [mA]",
    device_class="current", state_class="measurement",
),
"pv_current_3": ParameterDef(
    name="PV Strom String 3",
    index=0x02, subindex=0x2F, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="A", scale=0.001,
    description="PV Current, input 3 [mA] (nur TLX 10k/12.5k/15k)",
    device_class="current", state_class="measurement",
),
"pv_power_1": ParameterDef(
    name="PV Leistung String 1",
    index=0x02, subindex=0x32, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="W", scale=1.0,
    description="PV Power, input 1 [W]",
    device_class="power", state_class="measurement",
),
"pv_power_2": ParameterDef(
    name="PV Leistung String 2",
    index=0x02, subindex=0x33, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="W", scale=1.0,
    description="PV Power, input 2 [W]",
    device_class="power", state_class="measurement",
),
"pv_power_3": ParameterDef(
    name="PV Leistung String 3",
    index=0x02, subindex=0x34, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="W", scale=1.0,
    description="PV Power, input 3 [W] (nur TLX 10k/12.5k/15k)",
    device_class="power", state_class="measurement",
),
"pv_energy_1": ParameterDef(
    name="PV Energie String 1",
    index=0x02, subindex=0x37, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="PV Energy, input 1 [Wh]",
    device_class="energy", state_class="total_increasing",
),
"pv_energy_2": ParameterDef(
    name="PV Energie String 2",
    index=0x02, subindex=0x38, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="PV Energy, input 2 [Wh]",
    device_class="energy", state_class="total_increasing",
),
"pv_energy_3": ParameterDef(
    name="PV Energie String 3",
    index=0x02, subindex=0x39, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="PV Energy, input 3 [Wh] (nur TLX 10k/12.5k/15k)",
    device_class="energy", state_class="total_increasing",
),

# Netz (AC-Seite) - Spannungen
"grid_voltage_l1": ParameterDef(
    name="Netzspannung L1",
    index=0x02, subindex=0x3C, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="Grid voltage, phase L1 [V/10]",
    device_class="voltage", state_class="measurement",
),
"grid_voltage_l2": ParameterDef(
    name="Netzspannung L2",
    index=0x02, subindex=0x3D, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="Grid voltage, phase L2 [V/10]",
    device_class="voltage", state_class="measurement",
),
"grid_voltage_l3": ParameterDef(
    name="Netzspannung L3",
    index=0x02, subindex=0x3E, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="Grid voltage, phase L3 [V/10]",
    device_class="voltage", state_class="measurement",
),

# Netz - 10-min Mittelwerte
"grid_voltage_l1_avg": ParameterDef(
    name="Netzspannung L1 (10min Ø)",
    index=0x02, subindex=0x5B, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="Grid voltage, 10-min mean, phase L1 [V/10]",
    device_class="voltage", state_class="measurement",
),
"grid_voltage_l2_avg": ParameterDef(
    name="Netzspannung L2 (10min Ø)",
    index=0x02, subindex=0x5C, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="Grid voltage, 10-min mean, phase L2 [V/10]",
    device_class="voltage", state_class="measurement",
),
"grid_voltage_l3_avg": ParameterDef(
    name="Netzspannung L3 (10min Ø)",
    index=0x02, subindex=0x5D, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="V", scale=0.1,
    description="Grid voltage, 10-min mean, phase L3 [V/10]",
    device_class="voltage", state_class="measurement",
),

# Netz - Ströme
"grid_current_l1": ParameterDef(
    name="Netzstrom L1",
    index=0x02, subindex=0x3F, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="A", scale=0.001,
    description="Grid current, phase L1 [mA]",
    device_class="current", state_class="measurement",
),
"grid_current_l2": ParameterDef(
    name="Netzstrom L2",
    index=0x02, subindex=0x40, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="A", scale=0.001,
    description="Grid current, phase L2 [mA]",
    device_class="current", state_class="measurement",
),
"grid_current_l3": ParameterDef(
    name="Netzstrom L3",
    index=0x02, subindex=0x41, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="A", scale=0.001,
    description="Grid current, phase L3 [mA]",
    device_class="current", state_class="measurement",
),

# Netz - Leistung
"grid_power_l1": ParameterDef(
    name="Netzleistung L1",
    index=0x02, subindex=0x42, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="W", scale=1.0,
    description="Grid power, phase L1 [W]",
    device_class="power", state_class="measurement",
),
"grid_power_l2": ParameterDef(
    name="Netzleistung L2",
    index=0x02, subindex=0x43, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="W", scale=1.0,
    description="Grid power, phase L2 [W]",
    device_class="power", state_class="measurement",
),
"grid_power_l3": ParameterDef(
    name="Netzleistung L3",
    index=0x02, subindex=0x44, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="W", scale=1.0,
    description="Grid power, phase L3 [W]",
    device_class="power", state_class="measurement",
),
"grid_power_total": ParameterDef(
    name="Netzleistung Gesamt",
    index=0x02, subindex=0x46, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="W", scale=1.0,
    description="Grid power, sum of L1+L2+L3 [W] = Instant Energy Production",
    device_class="power", state_class="measurement",
),

# Netz - Energie heute
"grid_energy_today_l1": ParameterDef(
    name="Netzenergie heute L1",
    index=0x02, subindex=0x47, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="Grid Energy Today, phase L1 [Wh]",
    device_class="energy", state_class="total_increasing",
),
"grid_energy_today_l2": ParameterDef(
    name="Netzenergie heute L2",
    index=0x02, subindex=0x48, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="Grid Energy Today, phase L2 [Wh]",
    device_class="energy", state_class="total_increasing",
),
"grid_energy_today_l3": ParameterDef(
    name="Netzenergie heute L3",
    index=0x02, subindex=0x49, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="Grid Energy Today, phase L3 [Wh]",
    device_class="energy", state_class="total_increasing",
),
"grid_energy_today_total": ParameterDef(
    name="Netzenergie heute Gesamt",
    index=0x02, subindex=0x4A, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="Grid Energy Today, sum of L1+L2+L3 [Wh]",
    device_class="energy", state_class="total_increasing",
),

# Netz - DC-Anteil im AC-Strom
"grid_dc_l1": ParameterDef(
    name="DC-Anteil Strom L1",
    index=0x02, subindex=0x4C, data_type=DataType.SIGNED32,
    module_id=MODULE_COMM_BOARD, unit="mA", scale=1.0,
    description="Grid current, DC content, phase L1 [mA]",
    device_class="current", state_class="measurement",
),
"grid_dc_l2": ParameterDef(
    name="DC-Anteil Strom L2",
    index=0x02, subindex=0x4D, data_type=DataType.SIGNED32,
    module_id=MODULE_COMM_BOARD, unit="mA", scale=1.0,
    description="Grid current, DC content, phase L2 [mA]",
    device_class="current", state_class="measurement",
),
"grid_dc_l3": ParameterDef(
    name="DC-Anteil Strom L3",
    index=0x02, subindex=0x4E, data_type=DataType.SIGNED32,
    module_id=MODULE_COMM_BOARD, unit="mA", scale=1.0,
    description="Grid current, DC content, phase L3 [mA]",
    device_class="current", state_class="measurement",
),

# Netz - Frequenz
"grid_frequency_l1": ParameterDef(
    name="Netzfrequenz L1",
    index=0x02, subindex=0x61, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Hz", scale=0.001,
    description="Grid frequency, phase L1 [mHz]",
    device_class="frequency", state_class="measurement",
),
"grid_frequency_l2": ParameterDef(
    name="Netzfrequenz L2",
    index=0x02, subindex=0x62, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Hz", scale=0.001,
    description="Grid frequency, phase L2 [mHz]",
    device_class="frequency", state_class="measurement",
),
"grid_frequency_l3": ParameterDef(
    name="Netzfrequenz L3",
    index=0x02, subindex=0x63, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Hz", scale=0.001,
    description="Grid frequency, phase L3 [mHz]",
    device_class="frequency", state_class="measurement",
),
"grid_frequency_avg": ParameterDef(
    name="Netzfrequenz Ø",
    index=0x02, subindex=0x50, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Hz", scale=0.001,
    description="Grid frequency, mean L1+L2+L3 [mHz]",
    device_class="frequency", state_class="measurement",
),

# Sensoren (nur wenn physisch angeschlossen)
"irradiance": ParameterDef(
    name="Einstrahlung",
    index=0x02, subindex=0x02, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="W/m²", scale=1.0,
    description="Global irradiance [W/m²] (nur mit Sensor)",
    device_class="irradiance", state_class="measurement",
),
"ambient_temp": ParameterDef(
    name="Umgebungstemperatur",
    index=0x02, subindex=0x03, data_type=DataType.SIGNED16,
    module_id=MODULE_COMM_BOARD, unit="°C", scale=1.0,
    description="Ambient temperature [°C] (nur mit Sensor)",
    device_class="temperature", state_class="measurement",
),
"pv_array_temp": ParameterDef(
    name="Modultemperatur",
    index=0x02, subindex=0x04, data_type=DataType.SIGNED16,
    module_id=MODULE_COMM_BOARD, unit="°C", scale=1.0,
    description="PV array temperature [°C] (nur mit Sensor)",
    device_class="temperature", state_class="measurement",
),

# ── Status (Index 0x0A) ────────────────────────────────────────────
"operation_mode": ParameterDef(
    name="Betriebsmodus",
    index=0x0A, subindex=0x02, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="", scale=1.0,
    description="Operation Mode ID",
    device_class="", state_class="",
),
"latest_event": ParameterDef(
    name="Letztes Ereignis",
    index=0x0A, subindex=0x28, data_type=DataType.UNSIGNED16,
    module_id=MODULE_COMM_BOARD, unit="", scale=1.0,
    description="Latest Event Code",
    device_class="", state_class="",
),

# ── Systeminfo (Index 0x1E, 0x32, 0x3C, 0x46, 0x47) ──────────────
"hardware_type": ParameterDef(
    name="Hardware-Typ",
    index=0x1E, subindex=0x14, data_type=DataType.UNSIGNED8,
    module_id=MODULE_COMM_BOARD, unit="", scale=1.0,
    description="Hardware Type ID (6=10kW, 7=12.5kW, 8=15kW)",
),
"nominal_power": ParameterDef(
    name="Nennleistung",
    index=0x47, subindex=0x01, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="W", scale=1.0,
    description="Nominal AC power [W]",
    device_class="power", state_class="",
),
"sw_version": ParameterDef(
    name="Software-Version",
    index=0x32, subindex=0x28, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="", scale=0.01,
    description="Software package version [/100]",
),

# ── Energielog (Index 120) ─────────────────────────────────────────
"production_today_log": ParameterDef(
    name="Produktion heute (Log)",
    index=120, subindex=10, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="Inverter production today",
    device_class="energy", state_class="total_increasing",
),
"production_this_week": ParameterDef(
    name="Produktion diese Woche",
    index=120, subindex=20, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="Inverter production this week",
    device_class="energy", state_class="total_increasing",
),
"production_this_month": ParameterDef(
    name="Produktion diesen Monat",
    index=120, subindex=30, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="Wh", scale=1.0,
    description="Inverter production this month",
    device_class="energy", state_class="total_increasing",
),
"production_this_year": ParameterDef(
    name="Produktion dieses Jahr",
    index=120, subindex=50, data_type=DataType.UNSIGNED32,
    module_id=MODULE_COMM_BOARD, unit="kWh", scale=1.0,
    description="Inverter production this year [kWh für TLX]",
    device_class="energy", state_class="total_increasing",
),
```

}

# Betriebsmodus-Texte (aus Appendix C, Status Information)

OPERATION_MODES = {
0: “Nicht verfügbar”,
1: “Aus”,
2: “Standby”,
3: “Startet”,
4: “Produziert”,
5: “Netzfehler”,
6: “Störung”,
7: “Selbsttest”,
8: “Nacht/Schlaf”,
}

# ============================================================================

# EtherLynx Paket-Builder und -Parser

# ============================================================================

def _pad_serial(serial: str, length: int = 12) -> bytes:
“”“Seriennummer als nullterminierter String mit Zero-Padding.

```
Laut Doku: "Zero terminated string. Not used bytes after
terminating zero must have zero value."
"""
encoded = serial.encode('ascii') + b'\x00'
return encoded.ljust(length, b'\x00')
```

def _build_header(
source_serial: str,
dest_serial: str,
flags: int,
transaction_no: int,
message_id: int,
data_length: int,
) -> bytes:
“”“Baut den 52-Byte EtherLynx-Header.

```
EtherLynx Packet Structure (Kapitel 5.1):
┌─────────────┬──────┬─────────────────────────────────┐
│ Offset (bit) │ Size │ Field                           │
├─────────────┼──────┼─────────────────────────────────┤
│ 0           │ 96b  │ Source serial number (12 bytes)  │
│ 96          │ 192b │ Destination (24 bytes)           │
│ 288         │ 32b  │ DataOffset|Flags|TransNo|MsgID   │
│ 320         │ 32b  │ Total data length                │
│ 352         │ 32b  │ Sequence number                  │
│ 384         │ 32b  │ Acknowledge number               │
│ 416         │ 32b  │ Future options                   │
└─────────────┴──────┴─────────────────────────────────┘
Total: 52 bytes
"""
header = bytearray()

# Source serial (12 bytes, nullterminiert + zero-padded)
header.extend(_pad_serial(source_serial, 12))

# Destination (24 bytes, nullterminiert + zero-padded)
header.extend(_pad_serial(dest_serial, 24))

# Byte 36-39: Data offset (5 bits) | unused (3 bits) | flags (8 bits) | 
#             transaction no (8 bits) | message ID (8 bits)
# Data offset ist in 32-bit Wörtern, Minimum = 13 (0x0D)
byte36 = (ETHERLYNX_DATA_OFFSET & 0x1F) << 3  # data_offset in oberen 5 bits
byte37 = flags & 0xFF
byte38 = transaction_no & 0xFF
byte39 = message_id & 0xFF
header.extend(struct.pack('BBBB', byte36, byte37, byte38, byte39))

# Total data length (4 bytes, big-endian)
header.extend(struct.pack('>I', data_length))

# Sequence number (4 bytes, = 0 für non-file-transfer)
header.extend(struct.pack('>I', 0))

# Acknowledge number (4 bytes, = 0 für Requests)
header.extend(struct.pack('>I', 0))

# Future options (4 bytes, = 0)
header.extend(struct.pack('>I', 0))

return bytes(header)
```

def build_ping_packet(source_serial: str = MASTER_SERIAL) -> bytes:
“”“Baut ein EtherLynx Broadcast-Ping-Paket (Kapitel 5.4.1).

```
Flags: FB=1 (Full Broadcast), RES=1 (Response erwartet), R=0 (Request)
Message ID: 0x01 (Ping)
"""
flags = Flag.FB | Flag.RES_NEEDED  # 0x28
return _build_header(
    source_serial=source_serial,
    dest_serial="",
    flags=flags,
    transaction_no=0,
    message_id=MessageID.PING,
    data_length=0,
)
```

def build_get_parameters_packet(
source_serial: str,
dest_serial: str,
parameters: List[ParameterDef],
transaction_no: int = 0,
) -> bytes:
“”“Baut ein Get Parameter Values Paket (Kapitel 5.4.2).

```
Flags: SB=1 (Single Broadcast an spezifischen Inverter), 
       RES=1 (Response erwartet), R=0 (Request)
Message ID: 0x02

Data Payload Struktur pro Parameter (8 Bytes):
┌────────────────────────────────────────────────────────────────────┐
│ Byte 0: Attributes (E=0, Type=0, SG=0=Get)                       │
│ Byte 1: Source Module ID (obere 4 bits) | Dest Module ID (untere) │
│ Byte 2: Parameter Index                                           │
│ Byte 3: Parameter Subindex                                        │
│ Bytes 4-7: Parameter Value (= 0 bei Get)                         │
└────────────────────────────────────────────────────────────────────┘
"""
flags = Flag.SB | Flag.RES_NEEDED  # 0x22

# Data payload aufbauen
data = bytearray()

# Byte 0-3: Anzahl der Parameter-Requests (32-bit)
num_params = len(parameters)
data.extend(struct.pack('>I', num_params))

# Pro Parameter: 8 Bytes
for param in parameters:
    # Attributes Byte: E(0)|Type(0000)|SG(0=Get)|unused(00) = 0x00
    attr_byte = 0x00
    
    # Module IDs: Source (obere 4 bits) = Comm Board, Dest (untere 4 bits) = Comm Board
    # Laut Doku-Beispiel: Source=8, Dest=8 → 0x88
    module_byte = ((param.module_id & 0x0F) << 4) | (param.module_id & 0x0F)
    
    # Parameter index und subindex
    data.extend(struct.pack('BBBB',
        attr_byte,
        module_byte,
        param.index & 0xFF,
        param.subindex & 0xFF,
    ))
    
    # Parameter value = 0 bei Get-Request
    data.extend(struct.pack('>I', 0))

# Header bauen
header = _build_header(
    source_serial=source_serial,
    dest_serial=dest_serial,
    flags=flags,
    transaction_no=transaction_no,
    message_id=MessageID.GET_SET_PARAMETER,
    data_length=len(data),
)

return header + bytes(data)
```

def parse_ping_response(data: bytes) -> Optional[str]:
“”“Parst eine Ping-Response und extrahiert die Inverter-Seriennummer.

```
Laut Doku (Kapitel 5.4.1 / 6.4.2):
Die Response enthält im Source-Feld die Seriennummer des antwortenden Inverters.
"""
if len(data) < ETHERLYNX_HEADER_SIZE:
    logger.warning(f"Ping-Response zu kurz: {len(data)} Bytes")
    return None

# Prüfe ob es eine Response ist (R-Bit gesetzt)
flags = data[37]
if not (flags & Flag.RESPONSE):
    logger.debug("Kein Response-Paket (R-Bit nicht gesetzt)")
    return None

# Source serial number: Bytes 0-11, nullterminierter ASCII-String
serial_bytes = data[0:12]
serial = serial_bytes.split(b'\x00')[0].decode('ascii', errors='replace')

return serial if serial else None
```

def parse_parameter_response(
data: bytes,
requested_params: List[ParameterDef],
) -> Dict[str, Any]:
“”“Parst eine Get Parameter Values Response (Kapitel 5.4.2.2).

```
Response hat gleiche Struktur wie Request, aber mit gefüllten Werten.
"""
results = {}

if len(data) < ETHERLYNX_HEADER_SIZE:
    logger.error(f"Response zu kurz: {len(data)} Bytes")
    return results

# Prüfe Flags
flags = data[37]
if not (flags & Flag.RESPONSE):
    logger.warning("Kein Response-Paket")
    return results

# Prüfe auf Fehler
if flags & Flag.ERROR:
    logger.error("Inverter meldet Fehler in Response")
    return results

# Data beginnt nach dem Header (52 Bytes)
payload = data[ETHERLYNX_HEADER_SIZE:]

if len(payload) < 4:
    logger.error("Payload zu kurz für Parameteranzahl")
    return results

# Anzahl Parameter
num_params = struct.unpack('>I', payload[0:4])[0]

if num_params != len(requested_params):
    logger.warning(
        f"Erwartete {len(requested_params)} Parameter, "
        f"erhielt {num_params}"
    )

# Parse jedes Parameter-Ergebnis (je 8 Bytes, ab Offset 4)
offset = 4
for i, param_def in enumerate(requested_params):
    if offset + 8 > len(payload):
        logger.warning(f"Payload endet vor Parameter {i+1}")
        break
    
    attr_byte = payload[offset]
    module_byte = payload[offset + 1]
    param_index = payload[offset + 2]
    param_subindex = payload[offset + 3]
    raw_value = payload[offset + 4: offset + 8]
    
    # Prüfe Error-Bit im Attributes-Byte
    error_bit = attr_byte & 0x01
    if error_bit:
        logger.warning(
            f"Fehler bei Parameter {param_def.name} "
            f"(Index={param_index:#x}, Sub={param_subindex:#x})"
        )
        offset += 8
        continue
    
    # Datentyp aus Attributes extrahieren (Bits 1-4)
    data_type = (attr_byte >> 1) & 0x0F
    
    # Wert parsen abhängig vom Datentyp
    # Byte order: LSB first (Intel format) laut Doku
    value = _parse_value(raw_value, data_type, param_def.data_type)
    
    # Skalierung anwenden
    if value is not None and param_def.scale != 1.0:
        value = round(value * param_def.scale, 3)
    
    # Ergebnis-Key ist der Parameter-Name aus der Definition
    # Finde den Key in TLX_PARAMETERS
    for key, pdef in TLX_PARAMETERS.items():
        if pdef is param_def:
            results[key] = value
            break
    else:
        results[f"param_{param_index}_{param_subindex}"] = value
    
    offset += 8

return results
```

def _parse_value(
raw: bytes,
response_type: int,
expected_type: int,
) -> Optional[float]:
“”“Parst einen 4-Byte Parameterwert basierend auf dem Datentyp.

```
Laut Doku: "The byte order is LSB first and MSB last" (Intel/Little-Endian)
"""
if len(raw) != 4:
    return None

# Verwende den Response-Datentyp wenn verfügbar, sonst den erwarteten
dtype = response_type if response_type != 0 else expected_type

try:
    if dtype == DataType.BOOLEAN:
        return float(struct.unpack('<I', raw)[0] != 0)
    elif dtype == DataType.SIGNED8:
        return float(struct.unpack('<b', raw[0:1])[0])
    elif dtype == DataType.SIGNED16:
        return float(struct.unpack('<h', raw[0:2])[0])
    elif dtype == DataType.SIGNED32:
        return float(struct.unpack('<i', raw)[0])
    elif dtype == DataType.UNSIGNED8:
        return float(raw[0])
    elif dtype == DataType.UNSIGNED16:
        return float(struct.unpack('<H', raw[0:2])[0])
    elif dtype == DataType.UNSIGNED32:
        return float(struct.unpack('<I', raw)[0])
    elif dtype == DataType.FLOAT:
        return float(struct.unpack('<f', raw)[0])
    elif dtype in (DataType.PACKED_BYTES, DataType.PACKED_WORDS):
        return float(struct.unpack('<I', raw)[0])
    else:
        # Fallback: unsigned 32
        return float(struct.unpack('<I', raw)[0])
except struct.error as e:
    logger.error(f"Struct-Fehler beim Parsen: {e}")
    return None
```

# ============================================================================

# EtherLynx Client-Klasse

# ============================================================================

class DanfossEtherLynx:
“”“Client für die Kommunikation mit Danfoss TLX Pro über EtherLynx/UDP.

```
Verwendung:
    client = DanfossEtherLynx("192.168.1.100")
    
    # Inverter entdecken
    serial = client.discover()
    
    # Alle Parameter abfragen
    data = client.read_all()
    print(json.dumps(data, indent=2))
"""

def __init__(
    self,
    inverter_ip: str,
    port: int = ETHERLYNX_PORT,
    timeout: float = DEFAULT_TIMEOUT,
    master_serial: str = MASTER_SERIAL,
):
    self.inverter_ip = inverter_ip
    self.port = port
    self.timeout = timeout
    self.master_serial = master_serial
    self._inverter_serial: Optional[str] = None
    self._transaction_counter = 0
    self._sock: Optional[socket.socket] = None

def _get_socket(self) -> socket.socket:
    """Erstellt oder gibt bestehenden UDP-Socket zurück."""
    if self._sock is None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self.timeout)
        # Bind auf beliebigen lokalen Port
        self._sock.bind(('', 0))
    return self._sock

def _next_transaction(self) -> int:
    """Inkrementiert und gibt die nächste Transaktionsnummer zurück."""
    self._transaction_counter = (self._transaction_counter + 1) & 0xFF
    return self._transaction_counter

def _send_receive(
    self, 
    packet: bytes, 
    timeout: Optional[float] = None,
) -> Optional[bytes]:
    """Sendet UDP-Paket und wartet auf Antwort."""
    sock = self._get_socket()
    old_timeout = sock.gettimeout()
    
    if timeout is not None:
        sock.settimeout(timeout)
    
    try:
        sock.sendto(packet, (self.inverter_ip, self.port))
        logger.debug(
            f"Gesendet: {len(packet)} Bytes an "
            f"{self.inverter_ip}:{self.port}"
        )
        
        response, addr = sock.recvfrom(4096)
        logger.debug(
            f"Empfangen: {len(response)} Bytes von {addr}"
        )
        return response
        
    except socket.timeout:
        logger.warning(
            f"Timeout beim Warten auf Antwort von "
            f"{self.inverter_ip}:{self.port}"
        )
        return None
    except OSError as e:
        logger.error(f"Socket-Fehler: {e}")
        return None
    finally:
        sock.settimeout(old_timeout)

def close(self):
    """Schließt den UDP-Socket."""
    if self._sock:
        self._sock.close()
        self._sock = None

def __enter__(self):
    return self

def __exit__(self, *args):
    self.close()

def discover(self) -> Optional[str]:
    """Entdeckt den Inverter per Ping und gibt die Seriennummer zurück.
    
    Sendet ein Full Broadcast Ping (Kapitel 5.4.1).
    Der Inverter antwortet mit seiner Seriennummer.
    """
    logger.info(f"Sende Ping an {self.inverter_ip}:{self.port}...")
    
    packet = build_ping_packet(self.master_serial)
    response = self._send_receive(packet, timeout=DISCOVERY_TIMEOUT)
    
    if response is None:
        logger.error("Kein Inverter antwortet - ist er eingeschaltet und erreichbar?")
        return None
    
    serial = parse_ping_response(response)
    if serial:
        self._inverter_serial = serial
        logger.info(f"Inverter gefunden! Seriennummer: {serial}")
    
    return serial

@property
def inverter_serial(self) -> Optional[str]:
    """Die Seriennummer des entdeckten Inverters."""
    return self._inverter_serial

@inverter_serial.setter
def inverter_serial(self, serial: str):
    """Setzt die Seriennummer manuell (falls Discovery übersprungen wird)."""
    self._inverter_serial = serial

def read_parameters(
    self,
    param_keys: List[str],
    max_per_request: int = 10,
) -> Dict[str, Any]:
    """Liest die angegebenen Parameter vom Inverter.
    
    Args:
        param_keys: Liste von Schlüsseln aus TLX_PARAMETERS
        max_per_request: Max. Parameter pro UDP-Request
        
    Returns:
        Dict mit param_key → skalierter Wert
    """
    if not self._inverter_serial:
        logger.info("Keine Seriennummer bekannt, starte Discovery...")
        if not self.discover():
            return {}
    
    # Parameter-Definitionen sammeln
    params = []
    for key in param_keys:
        if key in TLX_PARAMETERS:
            params.append((key, TLX_PARAMETERS[key]))
        else:
            logger.warning(f"Unbekannter Parameter: {key}")
    
    all_results = {}
    
    # In Batches aufteilen (EtherLynx unterstützt N Parameter pro Request)
    for batch_start in range(0, len(params), max_per_request):
        batch = params[batch_start:batch_start + max_per_request]
        batch_defs = [pdef for _, pdef in batch]
        
        packet = build_get_parameters_packet(
            source_serial=self.master_serial,
            dest_serial=self._inverter_serial,
            parameters=batch_defs,
            transaction_no=self._next_transaction(),
        )
        
        response = self._send_receive(packet)
        
        if response is None:
            logger.warning(
                f"Keine Antwort für Batch {batch_start}-"
                f"{batch_start + len(batch)}"
            )
            continue
        
        results = parse_parameter_response(response, batch_defs)
        all_results.update(results)
        
        # Kurze Pause zwischen Batches
        if batch_start + max_per_request < len(params):
            time.sleep(0.1)
    
    return all_results

def read_all(self) -> Dict[str, Any]:
    """Liest alle definierten Parameter vom Inverter.
    
    Gibt ein Dict zurück mit allen Messwerten, Status- und
    Systeminformationen. Ideal für die Anbindung an Home Assistant.
    """
    all_keys = list(TLX_PARAMETERS.keys())
    return self.read_parameters(all_keys)

def read_realtime(self) -> Dict[str, Any]:
    """Liest nur die häufig benötigten Echtzeit-Parameter.
    
    Optimiert für schnelle, häufige Abfragen (z.B. alle 10 Sekunden).
    Enthält: Leistung, Spannung, Strom, Frequenz, Status.
    """
    realtime_keys = [
        # Aktuelle Leistung
        "grid_power_total",
        "grid_power_l1", "grid_power_l2", "grid_power_l3",
        # PV-Strings
        "pv_voltage_1", "pv_voltage_2",
        "pv_current_1", "pv_current_2",
        "pv_power_1", "pv_power_2",
        # Netz
        "grid_voltage_l1", "grid_voltage_l2", "grid_voltage_l3",
        "grid_current_l1", "grid_current_l2", "grid_current_l3",
        "grid_frequency_avg",
        # Status
        "operation_mode",
        # Energie heute
        "grid_energy_today_total",
    ]
    return self.read_parameters(realtime_keys)

def read_energy(self) -> Dict[str, Any]:
    """Liest Energie-/Produktionswerte (seltener abgefragt)."""
    energy_keys = [
        "total_energy", "energy_today",
        "grid_energy_today_total",
        "grid_energy_today_l1", "grid_energy_today_l2", "grid_energy_today_l3",
        "pv_energy_1", "pv_energy_2",
        "production_today_log", "production_this_week",
        "production_this_month", "production_this_year",
    ]
    return self.read_parameters(energy_keys)

def get_status_text(self, mode_id: int) -> str:
    """Gibt den Betriebsmodus als Text zurück."""
    return OPERATION_MODES.get(int(mode_id), f"Unbekannt ({mode_id})")
```

# ============================================================================

# Standalone-Ausführung

# ============================================================================

def main():
“”“Kommandozeilen-Tool für schnelle Tests.”””
import argparse

```
parser = argparse.ArgumentParser(
    description="Danfoss TLX Pro EtherLynx Abfrage-Tool"
)
parser.add_argument(
    "ip",
    help="IP-Adresse des Danfoss TLX Pro Wechselrichters"
)
parser.add_argument(
    "--mode", "-m",
    choices=["all", "realtime", "energy", "discover", "json"],
    default="json",
    help="Abfragemodus (default: json)"
)
parser.add_argument(
    "--timeout", "-t",
    type=float, default=DEFAULT_TIMEOUT,
    help=f"Timeout in Sekunden (default: {DEFAULT_TIMEOUT})"
)
parser.add_argument(
    "--serial", "-s",
    help="Inverter-Seriennummer (überspringt Discovery)"
)
parser.add_argument(
    "--verbose", "-v",
    action="store_true",
    help="Verbose/Debug-Ausgabe"
)

args = parser.parse_args()

# Logging
log_level = logging.DEBUG if args.verbose else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

with DanfossEtherLynx(args.ip, timeout=args.timeout) as client:
    # Seriennummer setzen oder Discovery
    if args.serial:
        client.inverter_serial = args.serial
    else:
        serial = client.discover()
        if not serial:
            logger.error("Inverter nicht erreichbar. Beende.")
            return 1
    
    if args.mode == "discover":
        # Nur Discovery
        print(json.dumps({
            "inverter_ip": args.ip,
            "inverter_serial": client.inverter_serial,
            "status": "online",
        }, indent=2))
        return 0
    
    # Parameter lesen
    if args.mode == "realtime":
        data = client.read_realtime()
    elif args.mode == "energy":
        data = client.read_energy()
    elif args.mode == "all":
        data = client.read_all()
    else:  # json
        data = client.read_all()
    
    # Betriebsmodus-Text hinzufügen
    if "operation_mode" in data:
        data["operation_mode_text"] = client.get_status_text(
            data["operation_mode"]
        )
    
    # JSON-Ausgabe
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0
```

if **name** == “**main**”:
exit(main())
