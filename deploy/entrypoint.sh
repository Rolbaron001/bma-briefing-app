#!/bin/sh
set -eu

mkdir -p /data/db /data/exports
if [ "$(id -u)" = "0" ]; then
  chown -R briefing:briefing /data
  exec gosu briefing "$@"
fi
exec "$@"

