"""Only the small netifaces surface read by official robot.get_subnets.

ifaddr enumerates local adapters; this helper never scans peers. The offline
probe does not invoke adapter enumeration at all.
"""
import ipaddress
import socket

import ifaddr

AF_INET = socket.AF_INET


def interfaces():
    return [adapter.name for adapter in ifaddr.get_adapters()]


def ifaddresses(name):
    for adapter in ifaddr.get_adapters():
        if adapter.name == name:
            addresses = [
                {'addr': ip.ip, 'netmask': str(ipaddress.IPv4Network(
                    f'0.0.0.0/{ip.network_prefix}').netmask)}
                for ip in adapter.ips if isinstance(ip.ip, str)
            ]
            return {AF_INET: addresses} if addresses else {}
    raise ValueError('unknown local adapter')
