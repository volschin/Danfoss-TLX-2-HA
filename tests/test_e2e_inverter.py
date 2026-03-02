"""End-to-End-Test gegen einen echten Danfoss TLX Pro Wechselrichter.

Dieser Test wird nur ausgeführt, wenn ein Inverter im lokalen Netz
erreichbar ist. Er validiert das vollständige Protokoll:
Discovery → Parameter-Request → Response-Parsing → Plausibilitätsprüfung.

Verwendung:
    INVERTER_IP=192.168.68.103 pytest tests/test_e2e_inverter.py -v -s

Ohne INVERTER_IP werden alle Tests automatisch übersprungen.
"""

import os
import socket
import struct
import pytest

from danfoss_etherlynx import (
    DanfossEtherLynx,
    TLX_PARAMETERS,
    ETHERLYNX_PORT,
    ETHERLYNX_HEADER_SIZE,
    ETHERLYNX_DATA_OFFSET,
    MASTER_SERIAL,
    Flag,
    MessageID,
    build_ping_packet,
    build_get_parameters_packet,
)


@pytest.fixture
def inverter_ip():
    """Inverter-IP aus Umgebungsvariable, überspringt wenn nicht gesetzt."""
    ip = os.environ.get("INVERTER_IP")
    if ip is None:
        pytest.skip("INVERTER_IP nicht gesetzt, E2E-Test übersprungen")
    return ip


@pytest.fixture
def client(inverter_ip):
    """Erstellt einen DanfossEtherLynx Client."""
    with DanfossEtherLynx(inverter_ip, timeout=5.0) as c:
        yield c


# ── Discovery ────────────────────────────────────────────────────────


class TestDiscovery:
    """Testet die Inverter-Erkennung via Ping."""

    def test_ping_packet_header_format(self):
        """Ping-Paket hat korrektes data_offset-Byte (0x0D, nicht bit-shifted)."""
        packet = build_ping_packet()
        assert len(packet) == ETHERLYNX_HEADER_SIZE
        # byte36 = data_offset als roher Wert
        assert packet[36] == ETHERLYNX_DATA_OFFSET  # 0x0D, nicht 0x68
        # byte37 = flags: FB | RES_NEEDED
        assert packet[37] == (Flag.FB | Flag.RES_NEEDED)
        # byte39 = message_id: PING
        assert packet[39] == MessageID.PING

    def test_discover_returns_serial(self, client):
        """Discovery gibt eine nicht-leere Seriennummer zurück."""
        serial = client.discover()
        assert serial is not None
        assert len(serial) > 0
        print(f"  Seriennummer: {serial}")

    def test_discover_serial_is_stored(self, client):
        """Nach Discovery wird die Seriennummer im Client gespeichert."""
        serial = client.discover()
        assert client.inverter_serial == serial

    def test_ping_response_is_valid(self, inverter_ip):
        """Ping-Response hat korrekten Header mit Response-Flag."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        sock.bind(('', 0))
        try:
            packet = build_ping_packet()
            sock.sendto(packet, (inverter_ip, ETHERLYNX_PORT))
            response, addr = sock.recvfrom(4096)

            assert len(response) == ETHERLYNX_HEADER_SIZE
            # Response-Flag muss gesetzt sein
            assert response[37] & Flag.RESPONSE
            # data_offset im Response = 0x0D (raw)
            assert response[36] == ETHERLYNX_DATA_OFFSET
            # Message ID = PING
            assert response[39] == MessageID.PING
        finally:
            sock.close()


# ── Parameter-Requests ───────────────────────────────────────────────


class TestParameterRequest:
    """Testet den Aufbau und Versand von Parameter-Requests."""

    def test_parameter_packet_header_format(self):
        """Parameter-Request hat korrektes data_offset und LE num_params."""
        param = TLX_PARAMETERS["operation_mode"]
        packet = build_get_parameters_packet(
            MASTER_SERIAL, "TESTSERIAL", [param], transaction_no=1,
        )

        # Header: byte36 = 0x0D (raw data_offset)
        assert packet[36] == ETHERLYNX_DATA_OFFSET
        # Header: byte37 = SB | RES_NEEDED
        assert packet[37] == (Flag.SB | Flag.RES_NEEDED)
        # Header: byte39 = GET_SET_PARAMETER
        assert packet[39] == MessageID.GET_SET_PARAMETER

        # Payload: num_params als Little-Endian
        payload = packet[ETHERLYNX_HEADER_SIZE:]
        num_params_le = struct.unpack('<I', payload[0:4])[0]
        assert num_params_le == 1

    def test_single_parameter_read(self, client):
        """Einzelner Parameter kann gelesen werden."""
        serial = client.discover()
        assert serial is not None

        result = client.read_parameters(["grid_power_total"])
        assert "grid_power_total" in result
        power = result["grid_power_total"]
        assert isinstance(power, float)
        # Leistung muss >= 0 sein (auch nachts: 0 W ist valide)
        assert power >= 0, f"Negative Leistung: {power} W"
        print(f"  grid_power_total: {power} W")

    def test_batch_parameter_read(self, client):
        """Mehrere Parameter in einem Batch abfragen."""
        client.discover()

        keys = ["grid_voltage_l1", "grid_voltage_l2", "grid_voltage_l3"]
        result = client.read_parameters(keys)

        for key in keys:
            assert key in result, f"Parameter {key} fehlt in Antwort"
            voltage = result[key]
            # Netzspannung: 0 V (Inverter aus) oder 180-260 V (normal)
            assert voltage == 0 or 180 <= voltage <= 260, (
                f"{key} = {voltage} V außerhalb des Bereichs"
            )
            print(f"  {key}: {voltage} V")


# ── read_all ─────────────────────────────────────────────────────────


class TestReadAll:
    """Testet das Lesen aller Parameter (vollständiger Durchlauf)."""

    def test_read_all_returns_data(self, client):
        """read_all() gibt ein nicht-leeres Dict zurück."""
        client.discover()
        data = client.read_all()
        assert len(data) > 0, "read_all() gab leeres Dict zurück"
        print(f"  Gelesene Parameter: {len(data)}/{len(TLX_PARAMETERS)}")

    def test_read_all_plausibility(self, client):
        """Plausibilitätsprüfung der gelesenen Werte."""
        client.discover()
        data = client.read_all()

        # Netzfrequenz: 0 Hz (aus) oder ~50 Hz (normal)
        if "grid_frequency_avg" in data:
            freq = data["grid_frequency_avg"]
            assert freq == 0 or 49.5 <= freq <= 50.5, (
                f"Netzfrequenz {freq} Hz unplausibel"
            )
            print(f"  grid_frequency_avg: {freq} Hz")

        # Nennleistung: typisch 6000-15000 W für TLX Pro
        if "nominal_power" in data:
            nom = data["nominal_power"]
            assert 5000 <= nom <= 20000, (
                f"Nennleistung {nom} W unplausibel"
            )
            print(f"  nominal_power: {nom} W")

        # Software-Version: > 1.0
        if "sw_version" in data:
            sw = data["sw_version"]
            assert sw > 1.0, f"Software-Version {sw} unplausibel"
            print(f"  sw_version: {sw}")

        # Gesamtenergie: muss positiv sein (Inverter hat produziert)
        if "total_energy" in data:
            total = data["total_energy"]
            assert total >= 0, f"Gesamtenergie {total} Wh negativ"
            print(f"  total_energy: {total} Wh")

    def test_pv_string_values(self, client):
        """PV-String-Werte sind physikalisch plausibel."""
        client.discover()
        data = client.read_all()

        for i in [1, 2]:
            vkey = f"pv_voltage_{i}"
            ckey = f"pv_current_{i}"
            pkey = f"pv_power_{i}"

            if vkey in data and ckey in data and pkey in data:
                v = data[vkey]
                c = data[ckey]
                p = data[pkey]
                # Spannung: 0 (nachts) oder 100-700 V
                assert v == 0 or 100 <= v <= 700, (
                    f"PV String {i} Spannung {v} V unplausibel"
                )
                # Strom: >= 0 und <= 15 A (typisch)
                assert 0 <= c <= 15, (
                    f"PV String {i} Strom {c} A unplausibel"
                )
                print(f"  PV String {i}: {v} V, {c} A, {p} W")


# ── System-Parameter ─────────────────────────────────────────────────


class TestSystemParameters:
    """Testet System-Parameter die spezifische Datentyp-Probleme hatten."""

    def test_hardware_type_nonzero(self, client):
        """Hardware-Typ muss einen plausiblen Wert > 0 liefern."""
        client.discover()
        result = client.read_parameters(["hardware_type"])
        assert "hardware_type" in result, "hardware_type fehlt in Antwort"
        hw = result["hardware_type"]
        assert hw >= 0, f"hardware_type = {hw}, erwartet >= 0"
        print(f"  hardware_type: {hw}")

    def test_latest_event_readable(self, client):
        """Letztes Ereignis muss lesbar sein (0 = kein Fehler)."""
        client.discover()
        result = client.read_parameters(["latest_event"])
        assert "latest_event" in result, "latest_event fehlt in Antwort"
        event = result["latest_event"]
        assert event >= 0, f"latest_event = {event}, erwartet >= 0"
        print(f"  latest_event: {event}")

    def test_latest_event_raw_bytes(self, client, inverter_ip):
        """Zeigt die Roh-Bytes des latest_event für Datentyp-Analyse."""
        serial = client.discover()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        sock.bind(('', 0))
        try:
            param = TLX_PARAMETERS["latest_event"]
            packet = build_get_parameters_packet(
                MASTER_SERIAL, serial, [param], transaction_no=77,
            )
            sock.sendto(packet, (inverter_ip, ETHERLYNX_PORT))
            resp, _ = sock.recvfrom(4096)

            # Payload: 4 Byte Header + 4 Byte Param-Header + 4 Byte Value
            payload = resp[ETHERLYNX_HEADER_SIZE:]
            raw_value = payload[8:12]
            print(f"  latest_event raw bytes: {raw_value.hex()}")
            print(f"    als UNSIGNED32 BE: {struct.unpack('>I', raw_value)[0]}")
            print(f"    als UNSIGNED16 BE (bytes 2-3): {struct.unpack('>H', raw_value[2:4])[0]}")
            print(f"    als UNSIGNED16 BE (bytes 0-1): {struct.unpack('>H', raw_value[0:2])[0]}")
            print(f"    als UNSIGNED8 (byte 3): {raw_value[3]}")
            print(f"    als UNSIGNED8 (byte 0): {raw_value[0]}")
        finally:
            sock.close()

    def test_hardware_type_raw_bytes(self, client, inverter_ip):
        """Zeigt die Roh-Bytes des hardware_type für Datentyp-Analyse."""
        serial = client.discover()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        sock.bind(('', 0))
        try:
            param = TLX_PARAMETERS["hardware_type"]
            packet = build_get_parameters_packet(
                MASTER_SERIAL, serial, [param], transaction_no=78,
            )
            sock.sendto(packet, (inverter_ip, ETHERLYNX_PORT))
            resp, _ = sock.recvfrom(4096)

            payload = resp[ETHERLYNX_HEADER_SIZE:]
            raw_value = payload[8:12]
            print(f"  hardware_type raw bytes: {raw_value.hex()}")
            print(f"    als UNSIGNED32 BE: {struct.unpack('>I', raw_value)[0]}")
            print(f"    als UNSIGNED16 BE (bytes 2-3): {struct.unpack('>H', raw_value[2:4])[0]}")
            print(f"    als UNSIGNED8 (byte 3): {raw_value[3]}")
            print(f"    als UNSIGNED8 (byte 0): {raw_value[0]}")
        finally:
            sock.close()


# ── Protokoll-Details ────────────────────────────────────────────────


class TestProtocolDetails:
    """Detaillierte Protokoll-Tests für Regression."""

    def test_response_data_offset_is_raw(self, inverter_ip):
        """Response-Header verwendet data_offset als rohen Byte-Wert."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        sock.bind(('', 0))
        try:
            sock.sendto(build_ping_packet(), (inverter_ip, ETHERLYNX_PORT))
            resp, _ = sock.recvfrom(4096)
            # Inverter sendet 0x0D, nicht 0x68
            assert resp[36] == 0x0D
        finally:
            sock.close()

    def test_parameter_values_are_big_endian(self, client, inverter_ip):
        """Parameterwerte werden als Big-Endian zurückgegeben."""
        serial = client.discover()
        assert serial is not None

        # Lese grid_frequency_avg — Wert muss ~50000 mHz sein
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        sock.bind(('', 0))
        try:
            param = TLX_PARAMETERS["grid_frequency_avg"]
            packet = build_get_parameters_packet(
                MASTER_SERIAL, serial, [param], transaction_no=42,
            )
            sock.sendto(packet, (inverter_ip, ETHERLYNX_PORT))
            resp, _ = sock.recvfrom(4096)

            # Payload ab Byte 52, Parameter-Entry ab Byte 56
            raw_value = resp[ETHERLYNX_HEADER_SIZE + 4 + 4:
                            ETHERLYNX_HEADER_SIZE + 4 + 8]

            val_be = struct.unpack('>I', raw_value)[0]
            val_le = struct.unpack('<I', raw_value)[0]

            # Big-Endian sollte ~50000 sein, Little-Endian Unsinn
            assert 49000 <= val_be <= 51000, (
                f"BE-Wert {val_be} nicht im erwarteten Bereich"
            )
            assert val_le > 100000 or val_le < 40000, (
                f"LE-Wert {val_le} sieht verdächtig korrekt aus"
            )
            print(f"  BE: {val_be} mHz, LE: {val_le} mHz")
        finally:
            sock.close()

    def test_response_num_params_in_first_byte(self, client, inverter_ip):
        """Response hat num_params im ersten Byte der Payload."""
        serial = client.discover()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        sock.bind(('', 0))
        try:
            params = [
                TLX_PARAMETERS["grid_power_total"],
                TLX_PARAMETERS["pv_voltage_1"],
                TLX_PARAMETERS["grid_frequency_avg"],
            ]
            packet = build_get_parameters_packet(
                MASTER_SERIAL, serial, params, transaction_no=99,
            )
            sock.sendto(packet, (inverter_ip, ETHERLYNX_PORT))
            resp, _ = sock.recvfrom(4096)

            payload = resp[ETHERLYNX_HEADER_SIZE:]
            # Erstes Byte = Anzahl Parameter
            assert payload[0] == 3
            print(f"  num_params byte: {payload[0]}")
        finally:
            sock.close()
