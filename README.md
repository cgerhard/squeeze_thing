# squeeze_thing

Simple server for creating webthings (https://webthings.io/) from a squeezebox server.

Currently not much more than proof of concept quality.

By default it will broadcast and use the first squeezeserver to respond. If you
have multiple squeeze servers then you will need to use the configuration file.

It will reconnect if the squeeze server is restarted. 

Adding brand new players will require a restart but once it knows about a player it will remember it forever. So if a player disappears and reappers it should work even if the the server is restarted.

Persistent state is stored in the /var/local/squeeze_thing directory. If that state is lost then all the squeezethings that your webthing server knows about will have to be deleted and readded.

All the things are labeled "Thing" and I've not worked out how to change that.

To install:

sudo useradd squeeze_thing
sudo mkdir -p /usr/local/lib/squeeze_thing
sudo cp "*.py" /usr/local/lib/squeeze_thing
sudo mkdir -p /var/local/squeeze_thing
sudo chown squeeze_thing  /var/local/squeeze_thing
sudo cp squeeze_thing.service /etc/systemd/system
