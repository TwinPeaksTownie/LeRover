#!/usr/bin/env python3
import shutil
import os

src = os.path.expanduser("~/ctl_out.txt")
dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ctl_out.txt")

if os.path.exists(src):
    shutil.copy(src, dst)
    print("Copied", src, "to", dst)
    print(open(dst).read())
else:
    print(f"Source file {src} does not exist.")
