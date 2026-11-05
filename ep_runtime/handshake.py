"""Versioned SDK route adapter; no sockets or connection attempts on import."""
import socket
import time
from types import MethodType


class HandshakeError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def attach_handshake(robot, target_ip, local_ip, progress):
    def switch_route(connection, message, remote_address, timeout=5):
        from robomaster import protocol
        if remote_address != (target_ip, 30030):
            raise HandshakeError('unexpected_target')
        progress('network_handshake')
        # The pinned SDK sets proto.ip instead of the serialized proto._ip.
        message.get_proto()._ip = local_ip
        sock = connection._sock
        if not getattr(connection, '_console_bound', False):
            sock.bind((local_ip, 0))
            connection._console_bound = True
        sock.settimeout(timeout)
        sock.sendto(message.pack(), remote_address)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sock.settimeout(max(.01, deadline - time.monotonic()))
            try:
                payload, peer = sock.recvfrom(2048)
            except socket.timeout:
                raise HandshakeError('handshake_timeout') from None
            if peer[0] != target_ip:
                continue
            response, _ = protocol.decode_msg(payload)
            if (response is None or response.is_ack is not True
                    or response.cmdset != message.cmdset or response.cmdid != message.cmdid
                    or response._seq_id != message._seq_id):
                continue
            if response.unpack_protocol() is not True:
                raise HandshakeError('invalid_handshake_response')
            result = response.get_proto()
            if result._retcode != 0:
                raise HandshakeError('handshake_rejected')
            if result._state == 1:
                raise HandshakeError('robot_busy')
            # SDK state 0 means accepted, but the original method returns None.
            if result._state == 0:
                progress('network_ready')
                return True, local_ip
            if result._state == 2:
                if result._config_ip != local_ip:
                    raise HandshakeError('local_interface_mismatch')
                progress('network_ready')
                return True, local_ip
            raise HandshakeError('unknown_handshake_state')
        raise HandshakeError('handshake_timeout')

    def guarded_switch(connection, *args, **kwargs):
        try:
            return switch_route(connection, *args, **kwargs)
        except HandshakeError as error:
            connection._console_error = error.code
            raise
        except Exception as error:
            connection._console_error = type(error).__name__
            raise
    robot._sdk_conn.switch_remote_route = MethodType(guarded_switch, robot._sdk_conn)
