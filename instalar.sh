#!/bin/sh
set -eu
orbita_source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 "$orbita_source_dir/instalar.py" "$@"
