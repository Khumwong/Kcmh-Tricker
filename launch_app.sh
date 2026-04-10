#!/bin/bash
cd /home/santa/Workspace/kcmh-zaber-trigger
export QT_BEARER_POLL_TIMEOUT=0
export QT_NETWORK_DISABLE_CACHE=1
/home/santa/miniconda3/envs/kcmh/bin/python main.py "$@"
