#!/usr/bin/python3
"""
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

""" The squeezeservers port """
MYPORT = 3483

import sys, time
import select
from socket import *

def find_server():
    s = socket(AF_INET, SOCK_DGRAM)
    s.bind(('', 0))
    s.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
    poll = select.poll()

    poll.register(s, select.POLLIN)

    servers = []

    while len(servers) == 0:
        data = repr(time.time()) + '\n'
        s.sendto(b'e', ('<broadcast>', MYPORT))
        while True:
            fdVsEvent = poll.poll(100)
            if not fdVsEvent:
                break
            for descriptor, Event in fdVsEvent:
                data, (addr, port) = s.recvfrom(100)
                if addr not in servers:
                    servers.append(addr)

    for i in servers:
        print(i)
    return servers

if __name__ == "__main__":
    try:
        find_server()
        sys.exit()
    except Exception as e:
        print(e, flush=True)
