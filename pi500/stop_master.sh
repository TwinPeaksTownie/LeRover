#!/bin/bash
pkill -9 -f main.py 2>/dev/null
fuser -k 8085/tcp 2>/dev/null
