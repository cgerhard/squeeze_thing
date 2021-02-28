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

CONFIG = "CONFIG"
STATE_FILE = "state_file"
CONFIG_FILE = "/usr/local/etc/squeeze_thing.cfg"
STORE="/var/local/squeeze_thing/squeeze_players.json"
from  threading import Thread, Condition
import asyncio
import urllib
import json
import squeeze_thing
import traceback
import os
import sys
from getopt import getopt, GetoptError
from urllib import parse
from configparser import ConfigParser
from broadcast import find_server

def onoff(v):
    return str(v) == '1'

def offon(v):
    return 1 if v else 0

class Squeeze:
    '''
    Simple class describing a single player. Only limited state makes sense
    on a webthing. So it's just the power state and whether it is playing.

    Volume might be interesting as well
    '''
    # p = Squeeze(self, p, p["id"], name=p["name"], pause=onoff(p["playlist pause"]), power=onoff(p["power"]), loop=self.loop)
    def __init__(self, sqm, settings, loop=None):
        self.sqm = sqm
        self.initial_settings = settings
        self.ident = settings["id"]
        self.name = settings["name"]
        self.pause = settings["playlist pause"]
        self.power = settings["power"]
        self.volume = abs(int(settings["mixer volume"]))
        self.playing = ""
        self.wt_set_property = None
        if not loop:
            loop = asyncio.get_event_loop()
        self.loop = loop

    def set_property(self, attr, value, internal=False):
        ident = parse.quote(self.ident)
        ident = self.ident
        print("set_property", attr, value)

        cmd = None
        v = None
        if attr == "name":
            if self.name != value:
                v = value
                self.name = value
                cmd = '%s name %s' % (ident, value)
        elif attr == "volume":
            if self.volume != value:
                v = value
                self.name = value
                cmd = '%s mixer volume %s' % (ident, value)
        elif attr == "pause":
            if self.pause != value:
                v = onoff(value)
                self.pause = value
                cmd = '%s mode %s' % (ident, "play" if offon(value) == 1 else "pause")
        elif attr == "power":
            if self.power != value:
                v = onoff(value)
                self.power = value
                cmd = '%s power %s' % (ident, offon(value))
        elif attr == "playing":
            if self.playing != value:
                print("set playing", value)
                self.playing = value
                v = value
                cmd = True

        if cmd and not internal:
            # For some reason calling run_coroutine_threadsafe() from the main
            # thread results in the callback never running. Since we are
            # in the async loop here there should be away to schedule it to
            # run, but I've not found one so once again I have a worker thread
            # that runs it.
            def cb():
                async def xx():
                    return await self.sqm.push(cmd)
                try:
                    asyncio.run_coroutine_threadsafe(xx(), self.loop).result()
                except Exception as e:
                    print("Exception:", e, flush=True)
                    traceback.print_exc()

            self.sqm.push_cb(cb, None)

        if cmd and self.wt_set_property:
            print("wt set p", attr, v)
            self.wt_set_property(attr, v)

    def __str__(self):
        return "%s '%s' Pause: %s Power: %s" % (self.ident, self.name, str(self.pause), str(self.power))


class SqueezeMon:
    def __init__(self, config, host, port=9090):
        self.config = config
        self.byid = {}
        self._players = None
        self.host = host
        self.port = port
        self.coro = []
        self.acv = asyncio.Condition()
        self.cmds = []
        self.loop = asyncio.get_event_loop()
        self.thr = Thread(target=self.worker, daemon=True)
        self._queue = []
        self.cv = Condition()

    async def __aenter__(self):
        await self.connect()
        self.thr.start()

    async def connect(self):
        while True:
            try:
                self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
                return
            except ConnectionError:
                await asyncio.sleep(1)

    async def get_players(self):
        """
        get the list of players. The list is first read from a state file
        and any new players added to that state file. This is only done
        to keep the order of the players the same, which the squeezeserver
        does not garuntee. The order is important as they need to appear
        as webthings in the same order each time so that http://hostname.local/0
        always refers to the same player.
        """
        store = self.config.get(CONFIG, STATE_FILE, fallback=STORE)
        try:
            players = json.loads(open(store, "r").read())
        except Exception as exc:
            print(exc)
            players = []

        r = (await self._send("player count ?"))[0].split()
        n = int(r[-1])
        for i in range(n):
            p = {"index": i}
            for key in ["id", "name", "uuid", "ip"]:
                r = (await self._send("player %s %d ?" % (key, i)))[0]
                d = parse.unquote(r).split()
                p[key] = ' '.join(d[3:])

            for key in ["power", "playlist pause", "mixer volume"]:
                l = len(key.split())
                r = (await self._send("%s %s ?" % (p["id"], key)))[0]
                print(r, flush=True)
                d = parse.unquote(r).split()
                print(d, flush=True)
                p[key] = d[1+l]
            added = False
            for i in range(len(players)):
                if players[i]["id"] == p["id"]:
                    players[i] = p
                    added = True
            if not added:
                players.append(p)

        self._players = []
        for p in players:
            ident = p["id"]
            p = Squeeze(self, p, loop=self.loop)
            self.byid[ident] = p
            self._players.append(p)
        """
        Write the new status file with a .tmp suffix and then
        rename it over the existing file so that the file update
        is atomic.
        """
        json.dump(players, open(store + ".tmp", "w"))
        os.rename(store + ".tmp", store)

    async def __aexit__(self, *x):
        self._push_cb({ "quit" : True })
        return

    def worker(self):
        while True:
            with self.cv:
                while len(self._queue) == 0:
                    self.cv.wait()
                cb = self._queue.pop(0)
            if "quit" in cb:
                break
            if "args" in cb:
                cb["func"](cb["args"])
            else:
                cb["func"]()

    def push_cb(self, func, args):
        cb =  { "func" : func }
        if args:
            cb["args"] = args
        self._push_cb(cb)

    def _push_cb(self, cb):
        with self.cv:
            self._queue.append(cb)
            self.cv.notify_all()

    def players(self):
        return self._players

    async def send(self, cmd):
        self.writer.write((cmd + "\n").encode())
        await self.writer.drain()

    async def popper(self):
        print("Popper", flush=True)
        while True:
            async with self.acv:
                while len(self.cmds) == 0:
                    await self.acv.wait()
                e = self.cmds.pop(0)
            await self.send(e)

    async def push(self, cmd):
        print("push", flush=True)
        async with self.acv:
            self.cmds.append(cmd)
            self.acv.notify_all()

    async def _send(self, cmd, lines=1):
        await self.send(cmd)
        return await self.recv(lines)

    async def _recv(self, lines=1, callback=None):
        results=[]
        res=[]
        loop_forever = lines == 0
        while lines > 0 or loop_forever:
            x = (await self.reader.read(1)).decode('utf-8')
            if not x or x == '':
                self.writer.close()
                await self.connect()
                await self.subscribe()
                print("reconnected", flush=True)
                res=[]
                continue
            if x == '\n':
                r = ''.join(res)
                res = []
                if callback:
                    print("Received", r, flush=True)
                    try:
                        await callback(r)
                    except Exception as e:
                        print("Exception:", e, flush=True)
                        traceback.print_exc()
                else:
                    results.append(r)
                lines = lines - 1
                continue

            res.append(x)

        return results

    async def recv(self, lines=1, callback=None):
        try:
            r = await self._recv(lines=lines, callback=callback)
            print("Received", ' '.join(r), flush=True)
            return r
        except Exception as e:
            print("Exception:", e, flush=True)
            traceback.print_exc()

    def print(self):
        for x in self.players:
            print(x, flush=True)

    async def update(self, x):
        d = parse.unquote(x).split()
        if d[0] in ["subscribe"]:
            return
        entry = self.byid.get(d[0], None)
        if not entry:
            self.byid[d[0]] = {}
            entry = self.byid
        if d[1] == "power":
            entry.set_property("power", d[2], internal=True)
        elif d[1] == "name":
            entry.set_property("name", ''.join(d[2:]), internal=True)
        elif d[1] == "playlist":
            print(d, flush=True)
            if d[2] in ["newsong"]:
                print("newsong")
                entry.set_property("playing", ' '.join(d[3:-1]), internal=True)
                entry.set_property("pause", 0, internal=True)
            elif d[2] == "pause":
                entry.set_property("pause", d[3], internal=True)
        elif d[1] == "mixer":
            print(d, flush=True)
            if d[2] == "volume":
                entry.set_property(d[2], abs(int(d[3])), internal=True)


    async def subscribe(self):
        subscriptions = ["power", "playlist stop", "playlist pause",
                         "mixer volume"]
        await self.send("subscribe " + ",".join(subscriptions))
        self.coros = [self.recv(lines=0, callback=self.update),
                self.popper()]


async def multiple_tasks(coros):
    print(coros, flush=True)
    res = await asyncio.gather(*coros, return_exceptions=True)
    return res

def handle_exception(loop, context):
    print("Exception", context["message"], flush=True)
    print(context['exception'], flush=True)

def run_and_wait(coros):
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(handle_exception)
    loop.run_until_complete(multiple_tasks(coros))
    loop.run_forever()


async def runit():
    config = ConfigParser()
    try:
        options, remainder = getopt(sys.argv[1:], 'S:c:s:', ['state=', 'config=', 'server='])
    except GetoptError as err:
        print(err, file=sys.stderr)
        print("Usage:", sys.argv[0], "[-S statefile][-c config][-s server]", file=sys.stderr)
        sys.exit(1)

    config_file = CONFIG_FILE
    server = None
    store = None

    for opt, arg in options:
        if opt in ('-c', '--config'):
            config_file = arg
        elif opt in ('-s', '--server'):
            server = arg
        elif opt in ('-S', '--state'):
            global STORE
            store = arg

    try:
        f = open(config_file, 'r')
        config.read_file(f)
    except OSError as e:
        if config_file != CONFIG_FILE:
            raise

    if store:
        config.set(CONFIG, STATE_FILE, store)

    if not server:
        server = config.get(CONFIG, "server", fallback=None)
        if not server:
            server = find_server()[0]

    x = SqueezeMon(config, host=server)
    async with x:
        # Get the list of players
        await x.get_players()
        # Create the webthings for those players
        st = squeeze_thing.run_webthing(x.players())
        # Subscribe to any changes
        await x.subscribe()
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(handle_exception)
        coros = x.coros + st.coros
        await multiple_tasks(coros)
        print("done", flush=True)


if __name__ == "__main__":
    import sys
    try:
        sys.exit(asyncio.run(runit()))
    except Exception as e:
        print(e, flush=True)
