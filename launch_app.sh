#!/bin/bash
cd "/home/kobdaj/Kcmh-Tricker"
export QT_BEARER_POLL_TIMEOUT=0
export QT_NETWORK_DISABLE_CACHE=1
/usr/bin/python3 main.py "$@"
