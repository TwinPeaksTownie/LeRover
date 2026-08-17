#!/usr/bin/env python3
import os

log_file = "/home/user/test_queue.log"
if os.path.exists(log_file):
    print(open(log_file).read())
else:
    print(f"File {log_file} does not exist.")
