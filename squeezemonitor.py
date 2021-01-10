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

from  threading import Thread, Condition
import asyncio
import urllib
import squeeze_thing
import traceback
from urllib import parse

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
        self.wt_set_property = None
        if not loop:
            loop = asyncio.get_event_loop()
        self.loop = loop

    def set_property(self, attr, value, internal=False):
        ident = parse.quote(self.ident)
        ident = self.ident

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
                cmd = '%s playlist pause %d' % (ident, offon(value))
        elif attr == "power":
            if self.power != value:
                v = onoff(value)
                self.power = value
                cmd = '%s power %s' % (ident, offon(value))

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
                    print("Exception:", e)
                    traceback.print_exc()

            self.sqm.push_cb(cb, None)
        if cmd and self.wt_set_property:
            self.wt_set_property(attr, v)


    def __str__(self):
        return "%s '%s' Pause: %s Power: %s" % (self.ident, self.name, str(self.pause), str(self.power))
            

class SqueezeMon:
    def __init__(self, host="squeeze", port=9090):
        self.byid = {}
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


    async def Xget_player(self, player):
        r = (await self.send("%s player count ?" % player))[0].split()
        
    async def get_players(self):
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
                print(r)
                d = parse.unquote(r).split()
                print(d)
                p[key] = d[1+l]
            ident = p["id"]
            print(p)
            p = Squeeze(self, p, loop=self.loop)
            print(p)
            self.byid[ident] = p

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
        return self.byid.values()

    async def send(self, cmd):
        self.writer.write((cmd + "\n").encode())
        await self.writer.drain()

    async def popper(self):
        print("Popper")
        while True:
            async with self.acv:
                while len(self.cmds) == 0:
                    await self.acv.wait()
                e = self.cmds.pop(0)
                print("popped", e)
            await self.send(e)

    async def push(self, cmd):
        print("push")
        async with self.acv:
            self.cmds.append(cmd)
            self.acv.notify_all()
            print("pushed")

    async def _send(self, cmd, lines=1):
        await self.send(cmd)
        return await self.recv(lines)

    async def _recv(self, lines=1, callback=None):
        results=[]
        res=[]
        loop_forever = lines == 0
        while lines > 0 or loop_forever:
            x = (await self.reader.read(1)).decode('utf-8')
            if not x:
                self.writer.close()
                await self.connect()
                await self.get_players()
                await self.subscribe()
                print("reconnected")
                res=[]
                continue
            if x == '\n':
                r = ''.join(res)
                res = []
                if callback:
                    print("Recieved", r)
                    try:
                        await callback(r)
                    except Exception as e:
                        print("Exception:", e)
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
            print("Recieved", ' '.join(r))
            return r
        except Exception as e:
            print("Exception:", e)
            traceback.print_exc()

    def print(self):
        for x in self.players:
            print(x)

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
            print(d)
            if d[2] == "pause":
                entry.set_property("pause", d[3], internal=True)
        elif d[1] == "mixer":
            print(d)
            if d[2] == "volume":
                entry.set_property(d[2], abs(int(d[3])), internal=True)
    

    async def subscribe(self):
        subscriptions = ["power", "playlist stop", "playlist pause",
                         "mixer volume"]
        await self.send("subscribe " + ",".join(subscriptions))
        self.coros = [self.recv(lines=0, callback=self.update),
                self.popper()]


async def multiple_tasks(coros):
    print(coros)
    res = await asyncio.gather(*coros, return_exceptions=True)
    return res

def handle_exception(loop, context):
    print("Exception", context["message"])
    print(context['exception'])

def run_and_wait(coros):
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(handle_exception)
    loop.run_until_complete(multiple_tasks(coros))
    loop.run_forever()


async def runit():
    x = SqueezeMon()
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
        print("done")


if __name__ == "__main__":
    import sys
    try:
        sys.exit(asyncio.run(runit()))
    except Exception as e:
        print(e)

