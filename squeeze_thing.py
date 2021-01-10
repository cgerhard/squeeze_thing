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
from __future__ import division
from webthing import (Action, Event, Property, MultipleThings, Thing, Value,
                      WebThingServer)
import logging
import time
import uuid
import asyncio
import ssl
import platform


class Player(Thing):
    def __init__(self, squeeze, *arg):
        self._squeeze = squeeze
        squeeze.wt_set_property = self.set_property_x
        super().__init__(*arg)
        
    def set_property(self, property_name, value):
        self.set_property_x(property_name, value)
        self._squeeze.set_property(property_name.lower(), value)

    def set_property_x(self, property_name, value):
        super().set_property(property_name.lower(), value)


def make_thing(squeeze):
    name = squeeze.name
    power = squeeze.power
    pause = squeeze.pause

    thing = Player(
            squeeze,
            'urn:dev:ops:squeezebox',
            name,
            ['MediaPlayer', 'Squeezebox'],
            'A web connected misic player'
    )

    for i,d,s in [('Power', 'Whether the squeezebox is powered on', power),
        ('Pause', 'Whether the squeezebox is paused', pause)]:

        metadata={
             '@type': 'OnOffProperty' if s == power else 'MutedProperty',
             'title': i,
             'type': 'boolean',
             'description': d,
        }
        value = Value(s)
        prop = i.lower()
        thing.add_property(Property(thing, prop, value, metadata=metadata))

    metadata={
        '@type': 'VolumeProperty',
        'title': 'Volume',
        'type': 'number',
        'description': "The identity of the player (mac address)",
        'minimum': 0,
        'maximum': 100,
        'unit': 'percent',
    }
    value = Value(squeeze.volume)
    prop = "volume"
    thing.add_property(Property(thing, prop, value, metadata=metadata))

    metadata={
         'title': "Identity",
         'type': 'string',
         'readOnly': True,
         'description': "The identity of the player (mac address)"
    }
    value = Value(squeeze.ident)
    prop = "identity"
    thing.add_property(Property(thing, prop, value, metadata=metadata))

    return thing


async def run_async_webthing(rwt):
    while True:
        # If adding more than one thing, use MultipleThings() with a name.
        # In the single thing case, the thing's name will be broadcast.
        ssl_context = None

        server = WebThingServer(MultipleThings(rwt.things, name="SqueezeBox"), port=7777,
                ssl_options=ssl_context)
        try:
            print('starting the server')
            logging.info('starting the server')
            server.start()
        except KeyboardInterrupt:
            logging.info('stopping the server')
            server.stop()
            logging.info('done')


class run_webthing:
    def __init__(self, players):
        self.players = players
        self.things = [make_thing(t) for t in players]
        self.coros = [run_async_webthing(self)]


if __name__ == '__main__':
    logging.basicConfig(
        level=10,
        format="%(asctime)s %(filename)s:%(lineno)s %(levelname)s %(message)s"
    )
    run_webthing()
