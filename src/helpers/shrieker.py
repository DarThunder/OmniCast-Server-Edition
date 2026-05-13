# OmniCast — Personal offline media server
# Copyright (C) 2026-Present  DarThunder
# SPDX-License-Identifier: AGPL-3.0-or-later

import socket
import threading
from time import sleep
from zeroconf import ServiceInfo, Zeroconf
from src.helpers.configs import opts

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

class Shrieker:
    def __init__(self, port=8080):
        self.port = port
        self.zeroconf = None
        self.info = None
        self.running = False
        self.thread = None
        self.ip_address = None

    def start(self):
        self.ip_address = get_local_ip()
        service_type = "_omnicast._tcp.local."
        service_name = f"OmniCastServer.{service_type}"

        self.info = ServiceInfo(
            service_type,
            service_name,
            addresses=[socket.inet_aton(self.ip_address)],
            port=self.port,
            properties={'version': b'1.0'}, 
            server="omnicast.local."
        )

        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        print(f"Iniciating OmniCast server in {self.ip_address}:{self.port}...")
        self.zeroconf = Zeroconf(interfaces=[self.ip_address])
        self.zeroconf.register_service(self.info)
        print("Service registered successfully in the local network.")

        while self.running:
            # i hate this goofy ass hack, but this mf doesn't work if i delete this update_service
            self.zeroconf.update_service(self.info)
            sleep(3)

        print("\nshutting down broadcast mDNS...")
        self.zeroconf.unregister_service(self.info)
        self.zeroconf.close()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2) 

omni_shrieker = Shrieker(port=opts["port"])