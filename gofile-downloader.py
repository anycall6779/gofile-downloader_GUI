#! /usr/bin/env python3

from sys import argv, exit
from os import name
from signal import signal, SIGINT, SIG_IGN
from types import FrameType
from gofile_core import Manager, NEW_LINE, TERMINAL_CLEAR_LINE

def die(msg: str):
    print(f"{msg}", flush=True)
    exit(-1)

def _handle_sigint(signum: int, frame: FrameType | None):
    global manager
    if manager:
        print(f"{TERMINAL_CLEAR_LINE}Stopping, please wait...{NEW_LINE}", flush=True)
        manager.stop()
        signal(SIGINT, SIG_IGN)

if __name__ == "__main__":
    url_or_file: str | None = None
    password: str | None = None
    argc: int = len(argv)

    if argc > 1:
        url_or_file = argv[1]
        if argc > 2:
            password = argv[2]

        manager = Manager(url_or_file=url_or_file, password=password)
        signal(SIGINT, _handle_sigint)
        
        print(f"Starting, please wait...{NEW_LINE}", flush=True)
        if not manager.login():
            die("Account creation failed!")
        
        downloader = manager.get_downloader(url_or_file, password)
        downloader.run()
    else:
        die(f"Usage:"
            f"{NEW_LINE}"
            f"python gofile-downloader.py https://gofile.io/d/contentid"
            f"{NEW_LINE}"
            f"python gofile-downloader.py https://gofile.io/d/contentid password"
        )
