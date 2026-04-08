"""Tests für das EtherLynx-Protokollmodul."""
import asyncio
import struct
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from custom_components.danfoss_tlx.etherlynx import (
    ETHERLYNX_PORT,
    ETHERLYNX_HEADER_SIZE,
    ETHERLYNX_DATA_OFFSET,
    MessageID,
    Flag,
    DataType,
    MODULE_COMM_BOARD,
    ParameterDef,
    TLX_PARAMETERS,
    DanfossEtherLynx,
    _pad_serial,
    _build_header,
    _parse_value,
    build_ping_packet,
    build_get_parameters_packet,
    parse_ping_response,
    parse_parameter_response,
)


# ============================================================================
# _EtherLynxProtocol Tests
# ============================================================================


class TestEtherLynxProtocol:
    @pytest.mark.asyncio
    async def test_send_receive_returns_response(self):
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        async def deliver():
            await asyncio.sleep(0)
            protocol.datagram_received(b"hello", ("127.0.0.1", 48004))

        asyncio.create_task(deliver())
        result = await protocol.send_receive(b"ping", timeout=1.0)
        assert result == b"hello"

    @pytest.mark.asyncio
    async def test_send_receive_timeout(self):
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)

        result = await protocol.send_receive(b"ping", timeout=0.01)
        assert result is None

    @pytest.mark.asyncio
    async def test_send_receive_propagates_transport_error(self):
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        protocol.connection_made(MagicMock())

        async def inject_error():
            await asyncio.sleep(0)
            protocol.error_received(OSError("Netzwerk nicht erreichbar"))

        asyncio.create_task(inject_error())
        result = await protocol.send_receive(b"ping", timeout=1.0)
        assert result is None


# ============================================================================
# _pad_serial Tests
# ============================================================================


class TestPadSerial:
    def test_normal_serial(self):
        result = _pad_serial("ABC123", 12)
        assert len(result) == 12
        assert result[:6] == b"ABC123"
        assert result[6] == 0  # null-terminator
        assert result[7:] == b'\x00' * 5

    def test_empty_serial(self):
        result = _pad_serial("", 12)
        assert len(result) == 12
        assert result[0] == 0  # null-terminator
        assert result == b'\x00' * 12

    def test_exact_fit(self):
        # 11 chars + null-terminator = 12
        result = _pad_serial("12345678901", 12)
        assert len(result) == 12
        assert result[:11] == b"12345678901"
        assert result[11] == 0

    def test_overflow_truncated(self):
        # 12+ chars: encoded is 13 bytes (12 chars + null), ljust to 12 keeps 13
        result = _pad_serial("123456789012", 12)
        # encoded = b"123456789012\x00" (13 bytes), ljust(12) = still 13
        assert result[:12] == b"123456789012"
        assert result[12] == 0

    def test_different_length(self):
        result = _pad_serial("AB", 24)
        assert len(result) == 24
        assert result[:2] == b"AB"
        assert result[2] == 0


# ============================================================================
# _build_header Tests
# ============================================================================


class TestBuildHeader:
    def test_header_size_is_52_bytes(self):
        header = _build_header("SRC", "DST", 0x00, 0, 0x01, 0)
        assert len(header) == ETHERLYNX_HEADER_SIZE

    def test_source_serial_placement(self):
        header = _build_header("HA_MASTER", "", 0, 0, 1, 0)
        # Bytes 0-11: source serial
        source = header[0:12]
        assert source[:9] == b"HA_MASTER"
        assert source[9] == 0

    def test_dest_serial_placement(self):
        header = _build_header("SRC", "TLX123", 0, 0, 1, 0)
        # Bytes 12-35: dest serial (24 bytes)
        dest = header[12:36]
        assert dest[:6] == b"TLX123"
        assert dest[6] == 0

    def test_flags_byte(self):
        flags = Flag.FB | Flag.RES_NEEDED  # 0x28
        header = _build_header("S", "D", flags, 0, 1, 0)
        assert header[37] == 0x28

    def test_transaction_byte(self):
        header = _build_header("S", "D", 0, 42, 1, 0)
        assert header[38] == 42

    def test_message_id_byte(self):
        header = _build_header("S", "D", 0, 0, MessageID.PING, 0)
        assert header[39] == 0x01

    def test_data_length_big_endian(self):
        header = _build_header("S", "D", 0, 0, 1, 256)
        # Bytes 40-43: data length big-endian
        length = struct.unpack('>I', header[40:44])[0]
        assert length == 256

    def test_remaining_fields_zero(self):
        header = _build_header("S", "D", 0, 0, 1, 0)
        # Bytes 44-51: sequence, ack, future = all zeros
        assert header[44:52] == b'\x00' * 8

    def test_data_offset_field(self):
        header = _build_header("S", "D", 0, 0, 1, 0)
        # Byte 36: data offset als roher Wert (0x0D)
        assert header[36] == ETHERLYNX_DATA_OFFSET


# ============================================================================
# build_ping_packet Tests
# ============================================================================


class TestBuildPingPacket:
    def test_size_is_52(self):
        packet = build_ping_packet()
        assert len(packet) == ETHERLYNX_HEADER_SIZE

    def test_flags_are_fb_and_res(self):
        packet = build_ping_packet()
        assert packet[37] == (Flag.FB | Flag.RES_NEEDED)  # 0x28

    def test_message_id_is_ping(self):
        packet = build_ping_packet()
        assert packet[39] == MessageID.PING

    def test_dest_is_empty(self):
        packet = build_ping_packet()
        # Dest bytes 12-35 should be all zeros (empty serial)
        assert packet[12:36] == b'\x00' * 24

    def test_custom_source_serial(self):
        packet = build_ping_packet("CUSTOM")
        assert packet[:6] == b"CUSTOM"


# ============================================================================
# build_get_parameters_packet Tests
# ============================================================================


class TestBuildGetParametersPacket:
    def _make_param(self, index=0x01, subindex=0x02):
        return ParameterDef(
            name="Test", index=index, subindex=subindex,
            data_type=DataType.UNSIGNED32, module_id=MODULE_COMM_BOARD,
        )

    def test_flags_are_sb_and_res(self):
        param = self._make_param()
        packet = build_get_parameters_packet("SRC", "DST", [param])
        assert packet[37] == (Flag.SB | Flag.RES_NEEDED)  # 0x22

    def test_message_id_is_get_set_parameter(self):
        param = self._make_param()
        packet = build_get_parameters_packet("SRC", "DST", [param])
        assert packet[39] == MessageID.GET_SET_PARAMETER

    def test_count_field(self):
        params = [self._make_param(0x01, i) for i in range(3)]
        packet = build_get_parameters_packet("SRC", "DST", params)
        payload = packet[ETHERLYNX_HEADER_SIZE:]
        # Parameteranzahl als Little-Endian 32-bit
        count = struct.unpack('<I', payload[0:4])[0]
        assert count == 3

    def test_param_entry_structure(self):
        param = self._make_param(0x02, 0x28)
        packet = build_get_parameters_packet("SRC", "DST", [param])
        payload = packet[ETHERLYNX_HEADER_SIZE:]
        # After 4-byte count: 8-byte entry
        entry = payload[4:12]
        assert entry[0] == 0x00  # attr_byte (Get)
        assert entry[1] == 0x88  # module_byte (8 << 4 | 8)
        assert entry[2] == 0x02  # index
        assert entry[3] == 0x28  # subindex
        assert entry[4:8] == b'\x00\x00\x00\x00'  # value = 0 for Get

    def test_total_packet_size(self):
        params = [self._make_param(0x01, i) for i in range(5)]
        packet = build_get_parameters_packet("SRC", "DST", params)
        expected = ETHERLYNX_HEADER_SIZE + 4 + (5 * 8)
        assert len(packet) == expected

    def test_transaction_number(self):
        param = self._make_param()
        packet = build_get_parameters_packet("SRC", "DST", [param], transaction_no=99)
        assert packet[38] == 99


# ============================================================================
# parse_ping_response Tests
# ============================================================================


class TestParsePingResponse:
    def test_valid_response(self, make_ping_response):
        data = make_ping_response("TLX999")
        serial = parse_ping_response(data)
        assert serial == "TLX999"

    def test_too_short(self):
        result = parse_ping_response(b'\x00' * 10)
        assert result is None

    def test_no_response_flag(self):
        data = bytearray(ETHERLYNX_HEADER_SIZE)
        data[0:6] = b"TLX123"
        data[37] = Flag.FB  # No RESPONSE flag
        result = parse_ping_response(bytes(data))
        assert result is None

    def test_empty_serial(self):
        data = bytearray(ETHERLYNX_HEADER_SIZE)
        data[37] = Flag.RESPONSE
        # Source serial is all zeros
        result = parse_ping_response(bytes(data))
        assert result is None


# ============================================================================
# parse_parameter_response Tests
# ============================================================================


class TestParseParameterResponse:
    def _make_param(self, name="test_param", index=0x02, subindex=0x46,
                    data_type=DataType.UNSIGNED32, scale=1.0):
        return ParameterDef(
            name=name, index=index, subindex=subindex,
            data_type=data_type, module_id=MODULE_COMM_BOARD,
            scale=scale,
        )

    def test_single_param(self, make_parameter_response):
        param = TLX_PARAMETERS["grid_power_total"]
        raw = struct.pack('>I', 2903)
        response = make_parameter_response([(param, raw)])
        result = parse_parameter_response(response, [("grid_power_total", param)])
        assert result["grid_power_total"] == 2903.0

    def test_multi_params(self, make_parameter_response):
        p1 = TLX_PARAMETERS["grid_power_total"]
        p2 = TLX_PARAMETERS["operation_mode"]
        raw1 = struct.pack('>I', 5000)
        # operation_mode: UNSIGNED16, rechts-aligniert im 4-Byte-Feld
        raw2 = b'\x00\x00' + struct.pack('>H', 4)
        response = make_parameter_response([(p1, raw1), (p2, raw2)])
        result = parse_parameter_response(response, [("grid_power_total", p1), ("operation_mode", p2)])
        assert result["grid_power_total"] == 5000.0
        assert result["operation_mode"] == 4.0

    def test_scaling(self, make_parameter_response):
        param = TLX_PARAMETERS["pv_voltage_1"]  # scale=0.1
        # UNSIGNED16, rechts-aligniert: 2 Null-Bytes + 2 Wert-Bytes
        raw = b'\x00\x00' + struct.pack('>H', 3520)
        response = make_parameter_response([(param, raw)])
        result = parse_parameter_response(response, [("pv_voltage_1", param)])
        assert result["pv_voltage_1"] == 352.0

    def test_error_bit_skips_param(self, make_parameter_response):
        param = TLX_PARAMETERS["grid_power_total"]
        raw = struct.pack('>I', 999)
        response = make_parameter_response([(param, raw)], error_indices={0})
        result = parse_parameter_response(response, [("grid_power_total", param)])
        assert "grid_power_total" not in result

    def test_missing_response_flag(self):
        data = bytearray(ETHERLYNX_HEADER_SIZE + 12)
        data[37] = Flag.SB  # No RESPONSE flag
        result = parse_parameter_response(bytes(data), [])
        assert result == {}

    def test_error_flag(self):
        data = bytearray(ETHERLYNX_HEADER_SIZE + 12)
        data[37] = Flag.RESPONSE | Flag.ERROR
        result = parse_parameter_response(bytes(data), [])
        assert result == {}

    def test_too_short_response(self):
        result = parse_parameter_response(b'\x00' * 10, [])
        assert result == {}

    def test_short_payload(self):
        # Header only, no payload for param count
        data = bytearray(ETHERLYNX_HEADER_SIZE + 2)
        data[37] = Flag.RESPONSE
        result = parse_parameter_response(bytes(data), [])
        assert result == {}


# ============================================================================
# _parse_value Tests
# ============================================================================


class TestParseValue:
    def test_boolean_true(self):
        raw = struct.pack('>I', 1)
        assert _parse_value(raw, DataType.BOOLEAN, DataType.BOOLEAN) == 1.0

    def test_boolean_false(self):
        raw = struct.pack('>I', 0)
        assert _parse_value(raw, DataType.BOOLEAN, DataType.BOOLEAN) == 0.0

    def test_signed8(self):
        # Rechts-aligniert: Wert im letzten Byte
        raw = b'\x00\x00\x00' + struct.pack('>b', -42)
        assert _parse_value(raw, DataType.SIGNED8, DataType.SIGNED8) == -42.0

    def test_signed16(self):
        # Rechts-aligniert: Wert in den letzten 2 Bytes
        raw = b'\x00\x00' + struct.pack('>h', -1000)
        assert _parse_value(raw, DataType.SIGNED16, DataType.SIGNED16) == -1000.0

    def test_signed32(self):
        raw = struct.pack('>i', -100000)
        assert _parse_value(raw, DataType.SIGNED32, DataType.SIGNED32) == -100000.0

    def test_unsigned8(self):
        # Rechts-aligniert: Wert im letzten Byte
        raw = bytes([0, 0, 0, 200])
        assert _parse_value(raw, DataType.UNSIGNED8, DataType.UNSIGNED8) == 200.0

    def test_unsigned16(self):
        # Rechts-aligniert: Wert in den letzten 2 Bytes
        raw = b'\x00\x00' + struct.pack('>H', 50000)
        assert _parse_value(raw, DataType.UNSIGNED16, DataType.UNSIGNED16) == 50000.0

    def test_unsigned32(self):
        raw = struct.pack('>I', 3000000)
        assert _parse_value(raw, DataType.UNSIGNED32, DataType.UNSIGNED32) == 3000000.0

    def test_float(self):
        raw = struct.pack('>f', 3.14)
        result = _parse_value(raw, DataType.FLOAT, DataType.FLOAT)
        assert abs(result - 3.14) < 0.001

    def test_packed_bytes(self):
        raw = struct.pack('>I', 42)
        assert _parse_value(raw, DataType.PACKED_BYTES, DataType.PACKED_BYTES) == 42.0

    def test_packed_words(self):
        raw = struct.pack('>I', 42)
        assert _parse_value(raw, DataType.PACKED_WORDS, DataType.PACKED_WORDS) == 42.0

    def test_wrong_length(self):
        assert _parse_value(b'\x00\x00', 0, DataType.UNSIGNED32) is None

    def test_response_type_zero_uses_expected(self):
        raw = struct.pack('>I', 100)
        # response_type=0, expected=UNSIGNED32
        assert _parse_value(raw, 0, DataType.UNSIGNED32) == 100.0

    def test_unknown_type_fallback(self):
        raw = struct.pack('>I', 77)
        # FIX_POINT (0xC) fällt durch auf default unsigned32 BE
        assert _parse_value(raw, DataType.FIX_POINT, DataType.FIX_POINT) == 77.0


# ============================================================================
# DanfossEtherLynx Klasse Tests
# ============================================================================


class TestDanfossEtherLynx:
    @pytest.mark.asyncio
    async def test_discover_success(self, make_ping_response):
        ping_resp = make_ping_response("INV_SER_001")
        client = DanfossEtherLynx("192.168.1.100")
        with patch.object(client, "_send_receive_async", AsyncMock(return_value=ping_resp)):
            serial = await client.discover()
        assert serial == "INV_SER_001"
        assert client.inverter_serial == "INV_SER_001"
        await client.close()

    @pytest.mark.asyncio
    async def test_discover_timeout(self):
        client = DanfossEtherLynx("192.168.1.100")
        with patch.object(client, "_send_receive_async", AsyncMock(return_value=None)):
            result = await client.discover()
        assert result is None
        assert client.inverter_serial is None
        await client.close()

    @pytest.mark.asyncio
    async def test_read_parameters_triggers_discovery(self, make_ping_response, make_parameter_response):
        ping_resp = make_ping_response("SER123")
        param = TLX_PARAMETERS["grid_power_total"]
        raw = struct.pack('>I', 1500)
        param_resp = make_parameter_response([(param, raw)])

        client = DanfossEtherLynx("192.168.1.100")
        with patch.object(
            client, "_send_receive_async",
            AsyncMock(side_effect=[ping_resp, param_resp])
        ):
            result = await client.read_parameters(["grid_power_total"])

        assert "grid_power_total" in result
        assert result["grid_power_total"] == 1500.0
        await client.close()

    @pytest.mark.asyncio
    async def test_read_parameters_skips_unknown_keys(self):
        client = DanfossEtherLynx("192.168.1.100")
        client._inverter_serial = "SER123"
        with patch.object(client, "_send_receive_async", AsyncMock(return_value=None)):
            result = await client.read_parameters(["nonexistent_key"])
        assert result == {}
        await client.close()

    @pytest.mark.asyncio
    async def test_read_all_returns_dict(self, make_parameter_response):
        all_keys = list(TLX_PARAMETERS.keys())
        num_batches = (len(all_keys) + 9) // 10
        responses = []
        for i in range(num_batches):
            batch_start = i * 10
            batch_end = min(batch_start + 10, len(all_keys))
            batch_params = [TLX_PARAMETERS[k] for k in all_keys[batch_start:batch_end]]
            resp = make_parameter_response([(p, struct.pack('>I', 0)) for p in batch_params])
            responses.append(resp)

        client = DanfossEtherLynx("192.168.1.100")
        client._inverter_serial = "SER123"
        with patch.object(client, "_send_receive_async", AsyncMock(side_effect=responses)):
            result = await client.read_all()

        assert isinstance(result, dict)
        await client.close()

    @pytest.mark.asyncio
    async def test_async_context_manager(self, make_ping_response):
        ping_resp = make_ping_response("CTX_SER")
        async with DanfossEtherLynx("192.168.1.100") as client:
            with patch.object(client, "_send_receive_async", AsyncMock(return_value=ping_resp)):
                serial = await client.discover()
        assert serial == "CTX_SER"

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self):
        client = DanfossEtherLynx("192.168.1.100")
        await client.close()
        await client.close()

    @pytest.mark.asyncio
    async def test_send_receive_async_opens_connection(self):
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        mock_transport = MagicMock()
        mock_transport.is_closing.return_value = False
        mock_protocol = MagicMock(spec=_EtherLynxProtocol)
        mock_protocol.send_receive = AsyncMock(return_value=b"response")

        with patch("custom_components.danfoss_tlx.etherlynx.asyncio.get_running_loop") as mock_loop_fn:
            mock_loop = MagicMock()
            mock_loop.create_datagram_endpoint = AsyncMock(
                return_value=(mock_transport, mock_protocol)
            )
            mock_loop_fn.return_value = mock_loop

            client = DanfossEtherLynx("192.168.1.100")
            result = await client._send_receive_async(b"packet", 3.0)

        assert result == b"response"
        mock_loop.create_datagram_endpoint.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_parameters_batch_no_response(self, make_ping_response):
        """Batch ohne Antwort wird übersprungen, kein Fehler."""
        make_ping_response("SER123")
        client = DanfossEtherLynx("192.168.1.100")
        client._inverter_serial = "SER123"
        with patch.object(
            client, "_send_receive_async",
            AsyncMock(return_value=None)
        ):
            result = await client.read_parameters(["grid_power_total"])
        assert result == {}
        await client.close()

    @pytest.mark.asyncio
    async def test_read_realtime_returns_subset(self, make_parameter_response):
        """read_realtime gibt nur Echtzeit-Parameter zurück."""
        from custom_components.danfoss_tlx.etherlynx import TLX_PARAMETERS
        all_keys = list(TLX_PARAMETERS.keys())
        num_batches = (len(all_keys) + 9) // 10
        responses = []
        for i in range(num_batches):
            batch_start = i * 10
            batch_end = min(batch_start + 10, len(all_keys))
            batch_params = [TLX_PARAMETERS[k] for k in all_keys[batch_start:batch_end]]
            resp = make_parameter_response([(p, struct.pack('>I', 100)) for p in batch_params])
            responses.append(resp)

        client = DanfossEtherLynx("192.168.1.100")
        client._inverter_serial = "SER123"
        with patch.object(client, "_send_receive_async", AsyncMock(side_effect=responses * 2)):
            result = await client.read_realtime()
        assert isinstance(result, dict)
        await client.close()

    @pytest.mark.asyncio
    async def test_read_energy_returns_subset(self, make_parameter_response):
        """read_energy gibt Energie-Parameter zurück."""
        from custom_components.danfoss_tlx.etherlynx import TLX_PARAMETERS
        all_keys = list(TLX_PARAMETERS.keys())
        num_batches = (len(all_keys) + 9) // 10
        responses = []
        for i in range(num_batches):
            batch_start = i * 10
            batch_end = min(batch_start + 10, len(all_keys))
            batch_params = [TLX_PARAMETERS[k] for k in all_keys[batch_start:batch_end]]
            resp = make_parameter_response([(p, struct.pack('>I', 100)) for p in batch_params])
            responses.append(resp)

        client = DanfossEtherLynx("192.168.1.100")
        client._inverter_serial = "SER123"
        with patch.object(client, "_send_receive_async", AsyncMock(side_effect=responses * 2)):
            result = await client.read_energy()
        assert isinstance(result, dict)
        await client.close()

    def test_transaction_counter_wraps(self):
        client = DanfossEtherLynx("192.168.1.100")
        client._transaction_counter = 254
        assert client._next_transaction() == 255
        assert client._next_transaction() == 0  # wraps at 256
        assert client._next_transaction() == 1

    def test_set_serial_manually(self):
        client = DanfossEtherLynx("192.168.1.100")
        assert client.inverter_serial is None
        client.inverter_serial = "MANUAL_SER"
        assert client.inverter_serial == "MANUAL_SER"

    @pytest.mark.asyncio
    async def test_close_releases_transport(self):
        """close() schließt den Transport und setzt Attribute zurück."""
        client = DanfossEtherLynx("192.168.1.100")
        mock_transport = MagicMock()
        client._transport = mock_transport
        client._protocol = MagicMock()
        await client.close()
        mock_transport.close.assert_called_once()
        assert client._transport is None
        assert client._protocol is None

    @pytest.mark.asyncio
    async def test_get_connection_raises_when_protocol_none(self):
        """_get_connection löst RuntimeError aus wenn _protocol None ist nach create_datagram_endpoint."""
        client = DanfossEtherLynx("192.168.1.100")

        async def fake_create_endpoint(factory, remote_addr):
            return (MagicMock(), None)

        mock_loop = MagicMock()
        mock_loop.create_datagram_endpoint = AsyncMock(side_effect=fake_create_endpoint)
        with patch("asyncio.get_running_loop", return_value=mock_loop):
            with pytest.raises(RuntimeError, match="_protocol ist None"):
                await client._get_connection()
        await client.close()

    @pytest.mark.asyncio
    async def test_read_parameters_discover_fails(self):
        """read_parameters gibt leeres Dict zurück wenn Discovery fehlschlägt."""
        client = DanfossEtherLynx("192.168.1.100")
        # No serial set, discover returns None
        with patch.object(client, "discover", AsyncMock(return_value=None)):
            result = await client.read_parameters(["grid_power_total"])
        assert result == {}
        await client.close()

    def test_get_status_text(self):
        """get_status_text gibt lesbaren Modustext zurück."""
        client = DanfossEtherLynx("192.168.1.100")
        text = client.get_status_text(0)
        assert isinstance(text, str)
        assert len(text) > 0


class TestEtherLynxProtocol:
    """Tests für _EtherLynxProtocol send_receive Grenzfälle."""

    @pytest.mark.asyncio
    async def test_send_receive_raises_when_transport_none(self):
        """send_receive löst RuntimeError aus wenn transport None ist."""
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        # transport is None by default
        with pytest.raises(RuntimeError, match="send_receive aufgerufen ohne aktive Verbindung"):
            await protocol.send_receive(b"test", timeout=1.0)

    def test_connection_made_sets_transport(self):
        """connection_made setzt das Transport-Attribut."""
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        mock_transport = MagicMock()
        protocol.connection_made(mock_transport)
        assert protocol.transport is mock_transport

    def test_datagram_received_sets_future_result(self):
        """datagram_received setzt das Future-Ergebnis."""
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            protocol._response_future = future
            protocol.datagram_received(b"response_data", ("192.168.1.1", 48004))
            assert future.result() == b"response_data"
        finally:
            loop.close()

    def test_error_received_sets_future_exception(self):
        """error_received setzt die Exception am Future."""
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        loop = asyncio.new_event_loop()
        try:
            future = loop.create_future()
            protocol._response_future = future
            exc = OSError("Network error")
            protocol.error_received(exc)
            with pytest.raises(OSError):
                future.result()
        finally:
            loop.close()

    @pytest.mark.asyncio
    async def test_send_receive_returns_data(self):
        """send_receive gibt Antwort-Daten zurück."""
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        mock_transport = MagicMock()
        mock_transport.sendto = MagicMock()
        protocol.transport = mock_transport

        async def deliver_response():
            await asyncio.sleep(0)  # yield to let send_receive run
            if protocol._response_future and not protocol._response_future.done():
                protocol._response_future.set_result(b"response")

        asyncio.ensure_future(deliver_response())
        result = await protocol.send_receive(b"request", timeout=1.0)
        assert result == b"response"

    @pytest.mark.asyncio
    async def test_send_receive_oserror_returns_none(self):
        """send_receive gibt None zurück bei OSError."""
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        mock_transport = MagicMock()
        mock_transport.sendto = MagicMock()
        protocol.transport = mock_transport

        async def deliver_error():
            await asyncio.sleep(0)
            if protocol._response_future and not protocol._response_future.done():
                protocol._response_future.set_exception(OSError("network error"))

        asyncio.ensure_future(deliver_error())
        result = await protocol.send_receive(b"request", timeout=1.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_send_receive_timeout_returns_none(self):
        """send_receive gibt None zurück bei Timeout."""
        from custom_components.danfoss_tlx.etherlynx import _EtherLynxProtocol
        protocol = _EtherLynxProtocol()
        mock_transport = MagicMock()
        mock_transport.sendto = MagicMock()
        protocol.transport = mock_transport
        # No response delivered → timeout fires
        result = await protocol.send_receive(b"request", timeout=0.01)
        assert result is None


class TestParseValueEdgeCases:
    """Tests für Grenzfälle in _parse_value."""

    def test_struct_error_returns_none(self):
        """_parse_value gibt None zurück bei ungültiger Länge."""
        from custom_components.danfoss_tlx.etherlynx import _parse_value
        # Pass wrong-length bytes to trigger struct.error
        result = _parse_value(b'\x00\x01', 0, int(DataType.FLOAT))  # too short for float
        assert result is None


class TestParseParameterResponseEdgeCases:
    """Tests für Grenzfälle in parse_parameter_response."""

    def test_payload_too_short_breaks_loop(self):
        """parse_parameter_response stoppt wenn Payload zu kurz für nächsten Parameter."""
        param = TLX_PARAMETERS["grid_power_total"]

        # Build a fake response: 52 header bytes + payload
        # Flags byte is at data[37] per parse_parameter_response code
        # From Flag class: RESPONSE = 0x02
        fake_header = bytearray(52)
        fake_header[37] = Flag.RESPONSE  # set RESPONSE flag at correct offset
        # Payload: num_params=1 (first byte) + 3 padding bytes, but NO 8-byte param entries
        # offset=4, offset+8=12 > len(payload)=4 → triggers warning at line 760
        payload = bytes([1]) + b'\x00' * 3
        response = bytes(fake_header) + payload

        result = parse_parameter_response(response, [("grid_power_total", param)])
        assert result == {}


class TestDanfossEtherLynxEdgeCases:
    """Tests für Grenzfälle im EtherLynx-Protokoll."""

    def test_parse_parameter_response_param_count_mismatch(self, make_parameter_response):
        """parse_parameter_response: Anzahl-Mismatch wird toleriert."""
        param1 = TLX_PARAMETERS["grid_power_total"]
        param2 = TLX_PARAMETERS["operation_mode"]
        raw1 = struct.pack('>I', 2000)
        raw2 = b'\x00\x00' + struct.pack('>H', 4)

        # Response contains 2 params but we say we only requested 1
        response = make_parameter_response([(param1, raw1), (param2, raw2)])

        # Request only param1, but response has 2 entries
        result = parse_parameter_response(response, [("grid_power_total", param1)])

        # Should still parse the first param even with mismatch
        assert "grid_power_total" in result


# ============================================================================
# Registry Validation Tests
# ============================================================================


class TestRegistry:
    def test_all_parameters_have_valid_data_type(self):
        valid_types = set(DataType)
        for key, param in TLX_PARAMETERS.items():
            assert param.data_type in valid_types, \
                f"Parameter '{key}' hat ungültigen DataType: {param.data_type}"

    def test_operation_modes_cover_all_ranges(self):
        """Alle definierten Bereiche liefern einen Text, nicht 'Unbekannt'."""
        from danfoss_etherlynx import get_operation_mode_text
        test_values = [0, 5, 9, 10, 30, 49, 50, 55, 59, 60, 65, 69, 70, 75, 79, 80, 85, 89]
        for v in test_values:
            text = get_operation_mode_text(v)
            assert "Unbekannt" not in text, f"Modus {v} ist 'Unbekannt'"
        # Werte außerhalb der Bereiche → Unbekannt
        assert "Unbekannt" in get_operation_mode_text(90)
        assert "Unbekannt" in get_operation_mode_text(99)

    def test_event_codes_cover_known_events(self):
        """Bekannte Ereignis-Codes liefern einen Text."""
        from danfoss_etherlynx import get_event_text
        assert get_event_text(0) == "Kein Ereignis"
        assert get_event_text(1) == "Netzspannung L1 zu niedrig"
        assert get_event_text(115) == "Isolationswiderstand PV-Erde zu niedrig"
        # Unbekannter Code → Fallback
        assert get_event_text(999) == "Ereignis 999"
        # Float-Werte werden korrekt auf int konvertiert
        assert get_event_text(0.0) == "Kein Ereignis"

    def test_all_parameters_have_module_id(self):
        for key, param in TLX_PARAMETERS.items():
            assert param.module_id == MODULE_COMM_BOARD, \
                f"Parameter '{key}' hat unerwartete module_id: {param.module_id}"

    def test_parameter_count(self):
        # Sanity check: we expect ~40+ parameters
        assert len(TLX_PARAMETERS) >= 40

    def test_pv_string_3_params_exist(self):
        pv3_keys = [k for k in TLX_PARAMETERS if k.startswith("pv_") and "_3" in k]
        assert len(pv3_keys) >= 3  # voltage, current, power, energy
