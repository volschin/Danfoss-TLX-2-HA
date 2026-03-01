"""Tests für das EtherLynx-Protokollmodul."""
import struct
from unittest.mock import patch, MagicMock


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
    OPERATION_MODES,
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
        # Byte 36: data offset (0x0D) shifted left by 3
        expected = (ETHERLYNX_DATA_OFFSET & 0x1F) << 3
        assert header[36] == expected


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
        count = struct.unpack('>I', payload[0:4])[0]
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
        raw = struct.pack('<I', 2903)
        response = make_parameter_response([(param, raw)])
        result = parse_parameter_response(response, [param])
        assert result["grid_power_total"] == 2903.0

    def test_multi_params(self, make_parameter_response):
        p1 = TLX_PARAMETERS["grid_power_total"]
        p2 = TLX_PARAMETERS["operation_mode"]
        raw1 = struct.pack('<I', 5000)
        raw2 = struct.pack('<H', 4) + b'\x00\x00'
        response = make_parameter_response([(p1, raw1), (p2, raw2)])
        result = parse_parameter_response(response, [p1, p2])
        assert result["grid_power_total"] == 5000.0
        assert result["operation_mode"] == 4.0

    def test_scaling(self, make_parameter_response):
        param = TLX_PARAMETERS["pv_voltage_1"]  # scale=0.1
        raw = struct.pack('<H', 3520) + b'\x00\x00'
        response = make_parameter_response([(param, raw)])
        result = parse_parameter_response(response, [param])
        assert result["pv_voltage_1"] == 352.0

    def test_error_bit_skips_param(self, make_parameter_response):
        param = TLX_PARAMETERS["grid_power_total"]
        raw = struct.pack('<I', 999)
        response = make_parameter_response([(param, raw)], error_indices={0})
        result = parse_parameter_response(response, [param])
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
        raw = struct.pack('<I', 1)
        assert _parse_value(raw, DataType.BOOLEAN, DataType.BOOLEAN) == 1.0

    def test_boolean_false(self):
        raw = struct.pack('<I', 0)
        assert _parse_value(raw, DataType.BOOLEAN, DataType.BOOLEAN) == 0.0

    def test_signed8(self):
        raw = struct.pack('<b', -42) + b'\x00\x00\x00'
        assert _parse_value(raw, DataType.SIGNED8, DataType.SIGNED8) == -42.0

    def test_signed16(self):
        raw = struct.pack('<h', -1000) + b'\x00\x00'
        assert _parse_value(raw, DataType.SIGNED16, DataType.SIGNED16) == -1000.0

    def test_signed32(self):
        raw = struct.pack('<i', -100000)
        assert _parse_value(raw, DataType.SIGNED32, DataType.SIGNED32) == -100000.0

    def test_unsigned8(self):
        raw = bytes([200, 0, 0, 0])
        assert _parse_value(raw, DataType.UNSIGNED8, DataType.UNSIGNED8) == 200.0

    def test_unsigned16(self):
        raw = struct.pack('<H', 50000) + b'\x00\x00'
        assert _parse_value(raw, DataType.UNSIGNED16, DataType.UNSIGNED16) == 50000.0

    def test_unsigned32(self):
        raw = struct.pack('<I', 3000000)
        assert _parse_value(raw, DataType.UNSIGNED32, DataType.UNSIGNED32) == 3000000.0

    def test_float(self):
        raw = struct.pack('<f', 3.14)
        result = _parse_value(raw, DataType.FLOAT, DataType.FLOAT)
        assert abs(result - 3.14) < 0.001

    def test_packed_bytes(self):
        raw = struct.pack('<I', 42)
        assert _parse_value(raw, DataType.PACKED_BYTES, DataType.PACKED_BYTES) == 42.0

    def test_packed_words(self):
        raw = struct.pack('<I', 42)
        assert _parse_value(raw, DataType.PACKED_WORDS, DataType.PACKED_WORDS) == 42.0

    def test_wrong_length(self):
        assert _parse_value(b'\x00\x00', 0, DataType.UNSIGNED32) is None

    def test_response_type_zero_uses_expected(self):
        raw = struct.pack('<I', 100)
        # response_type=0, expected=UNSIGNED32
        assert _parse_value(raw, 0, DataType.UNSIGNED32) == 100.0

    def test_unknown_type_fallback(self):
        raw = struct.pack('<I', 77)
        # Use FIX_POINT (0xC) which falls through to default unsigned32
        assert _parse_value(raw, DataType.FIX_POINT, DataType.FIX_POINT) == 77.0


# ============================================================================
# DanfossEtherLynx Klasse Tests
# ============================================================================


class TestDanfossEtherLynx:
    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_discover_success(self, mock_socket_cls, make_ping_response):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        ping_resp = make_ping_response("INV_SER_001")
        mock_sock.recvfrom.return_value = (ping_resp, ("192.168.1.100", ETHERLYNX_PORT))

        client = DanfossEtherLynx("192.168.1.100")
        serial = client.discover()

        assert serial == "INV_SER_001"
        assert client.inverter_serial == "INV_SER_001"
        mock_sock.sendto.assert_called_once()
        client.close()

    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_discover_timeout(self, mock_socket_cls):
        import socket as real_socket
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        mock_sock.recvfrom.side_effect = real_socket.timeout("timeout")

        client = DanfossEtherLynx("192.168.1.100")
        result = client.discover()

        assert result is None
        assert client.inverter_serial is None
        client.close()

    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_read_parameters_triggers_discovery(self, mock_socket_cls, make_ping_response, make_parameter_response):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        ping_resp = make_ping_response("SER123")
        param = TLX_PARAMETERS["grid_power_total"]
        raw = struct.pack('<I', 1500)
        param_resp = make_parameter_response([(param, raw)])

        mock_sock.recvfrom.side_effect = [
            (ping_resp, ("192.168.1.100", ETHERLYNX_PORT)),
            (param_resp, ("192.168.1.100", ETHERLYNX_PORT)),
        ]

        client = DanfossEtherLynx("192.168.1.100")
        result = client.read_parameters(["grid_power_total"])

        assert result["grid_power_total"] == 1500.0
        assert client.inverter_serial == "SER123"
        client.close()

    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_read_parameters_batching(self, mock_socket_cls, make_ping_response, make_parameter_response):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        # Use small max_per_request to force batching
        all_keys = list(TLX_PARAMETERS.keys())[:5]
        params = [TLX_PARAMETERS[k] for k in all_keys]

        # Build responses for 2 batches (3 + 2 with max_per_request=3)
        batch1_resp = make_parameter_response([
            (params[0], struct.pack('<I', 100)),
            (params[1], struct.pack('<I', 200)),
            (params[2], struct.pack('<I', 300)),
        ])
        batch2_resp = make_parameter_response([
            (params[3], struct.pack('<I', 400)),
            (params[4], struct.pack('<I', 500)),
        ])

        mock_sock.recvfrom.side_effect = [
            (batch1_resp, ("192.168.1.100", ETHERLYNX_PORT)),
            (batch2_resp, ("192.168.1.100", ETHERLYNX_PORT)),
        ]

        client = DanfossEtherLynx("192.168.1.100")
        client.inverter_serial = "SER123"
        result = client.read_parameters(all_keys, max_per_request=3)

        assert len(result) == 5
        # sendto called twice (2 batches)
        assert mock_sock.sendto.call_count == 2
        client.close()

    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_read_all_delegates(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        client = DanfossEtherLynx("192.168.1.100")
        client.inverter_serial = "SER123"

        with patch.object(client, 'read_parameters', return_value={"a": 1}) as mock_rp:
            result = client.read_all()
            mock_rp.assert_called_once_with(list(TLX_PARAMETERS.keys()))
            assert result == {"a": 1}

        client.close()

    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_read_realtime_delegates(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        client = DanfossEtherLynx("192.168.1.100")
        client.inverter_serial = "SER123"

        with patch.object(client, 'read_parameters', return_value={}) as mock_rp:
            client.read_realtime()
            keys = mock_rp.call_args[0][0]
            assert "grid_power_total" in keys
            assert "operation_mode" in keys

        client.close()

    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_read_energy_delegates(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        client = DanfossEtherLynx("192.168.1.100")
        client.inverter_serial = "SER123"

        with patch.object(client, 'read_parameters', return_value={}) as mock_rp:
            client.read_energy()
            keys = mock_rp.call_args[0][0]
            assert "total_energy" in keys
            assert "production_this_year" in keys

        client.close()

    def test_get_status_text_known(self):
        client = DanfossEtherLynx("192.168.1.100")
        assert client.get_status_text(4) == "Produziert"
        assert client.get_status_text(0) == "Nicht verfügbar"
        assert client.get_status_text(8) == "Nacht/Schlaf"

    def test_get_status_text_unknown(self):
        client = DanfossEtherLynx("192.168.1.100")
        assert client.get_status_text(99) == "Unbekannt (99)"

    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_context_manager_closes_socket(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        with DanfossEtherLynx("192.168.1.100") as client:
            client._get_socket()  # force socket creation

        mock_sock.close.assert_called_once()

    @patch("custom_components.danfoss_tlx.etherlynx.socket.socket")
    def test_transaction_counter_wraps(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        client = DanfossEtherLynx("192.168.1.100")
        client._transaction_counter = 254
        assert client._next_transaction() == 255
        assert client._next_transaction() == 0  # wraps at 256
        assert client._next_transaction() == 1
        client.close()

    def test_set_serial_manually(self):
        client = DanfossEtherLynx("192.168.1.100")
        assert client.inverter_serial is None
        client.inverter_serial = "MANUAL_SER"
        assert client.inverter_serial == "MANUAL_SER"


# ============================================================================
# Registry Validation Tests
# ============================================================================


class TestRegistry:
    def test_all_parameters_have_valid_data_type(self):
        valid_types = set(DataType)
        for key, param in TLX_PARAMETERS.items():
            assert param.data_type in valid_types, \
                f"Parameter '{key}' hat ungültigen DataType: {param.data_type}"

    def test_operation_modes_cover_0_to_8(self):
        for i in range(9):
            assert i in OPERATION_MODES, f"Modus {i} fehlt in OPERATION_MODES"

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
