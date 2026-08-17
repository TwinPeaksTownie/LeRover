#!/usr/bin/env python3
import os
import shutil

src = os.path.expanduser("~/deploy_final.txt")
dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy_final.txt")

if os.path.exists(src):
    shutil.copy(src, dst)
    print("=== LIVE DEPLOYMENT REPORT ===")
    print(open(dst, "r", encoding="utf-8").read())
else:
    print(f"File {src} not found.")
