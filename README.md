# squeeze_thing

Simple server for creating webthings from a squeezebox server.

Currently not much more than proof of concept quality.

It will reconnect if the squeeze server is restarted, but how well that works I've not tested well.

All the things are labeled "Thing" and I've not worked out how to change that.

To install:

sudo useradd squeeze_thing
sudo mkdir -p /usr/local/lib/squeeze_thing
sudo cp "*.py" /usr/local/lib/squeeze_thing
sudo mkdir -p /var/local/squeeze_thing
sudo chown squeeze_thing  /var/local/squeeze_thing
sudo cp squeeze_thing.service /etc/systemd/system
