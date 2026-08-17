#!/usr/bin/env python3
import os

path = "/home/user/deploy_final.log"
if os.path.exists(path):
    print("=== LIVE DEPLOYMENT RESULT ===")
    print(open(path).read())
else:
    print("Log file not found.")
