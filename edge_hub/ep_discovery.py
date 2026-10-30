"""Passive official SN broadcast discovery; no packets sent or SDK initialization."""
import ipaddress
import re
import socket
import threading
import time


class EpDiscovery:
    def __init__(self):
        self.lock = threading.Lock()
        self.devices = {}
        self.until = 0
        self.thread = None
        self.stop = threading.Event()
        self.error = ''

    def accept(self, data, address):
        try:
            ip = ipaddress.IPv4Address(address[0])
            sn = data.split(b'\0', 1)[0].decode('ascii').strip()
            if (not ip.is_private or ip.is_loopback or ip.is_multicast or ip.is_link_local
                    or ip.is_unspecified or not re.fullmatch('[A-Z0-9]{14}', sn)):
                return
            with self.lock:
                self.devices[str(ip)] = {'ip': str(ip), 'sn': sn, 'seen': time.monotonic()}
                if len(self.devices) > 32:
                    del self.devices[min(self.devices, key=lambda key: self.devices[key]['seen'])]
        except (ValueError, UnicodeError):
            return

    def snapshot(self):
        with self.lock:
            return [dict(item) for item in self.devices.values() if time.monotonic()-item['seen'] < 15]

    def renew(self):
        # Once a local estate page enables discovery, keep it for this service lifetime.
        # Candidate freshness and manual-disconnect suppression still expire independently.
        self.until = float('inf')
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.run, daemon=True, name='ep-passive-discovery')
            self.thread.start()

    def run(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
                receiver.bind(('0.0.0.0', 40927))
                receiver.settimeout(.5)
                self.error = ''
                while not self.stop.is_set() and time.monotonic() < self.until:
                    try:
                        data, address = receiver.recvfrom(1024)
                        self.accept(data, address)
                    except TimeoutError:
                        continue
        except OSError:
            self.error = '自動發現暫不可用，仍可掃碼或連線已加入機體。'

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(1)
