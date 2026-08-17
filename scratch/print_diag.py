#!/usr/bin/env python3
import base64
import os

path = "/home/user/so101/scratch/diag_out.txt"
if os.path.exists(path):
    txt = open(path).read()
    b64 = base64.b64encode(txt.encode()).decode()
    open("/home/user/diag_b64.txt", "w").write(b64)
