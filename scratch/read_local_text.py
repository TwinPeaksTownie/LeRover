#!/usr/bin/env python3
import os

path = os.path.expanduser("~/scratch/deploy_out.txt")
if os.path.exists(path):
    print("=== PI 4B LIVE DEPLOYMENT REPORT ===")
    print(open(path, "r", encoding="utf-8").read())
else:
    print(f"Path {path} does not exist.")
