"""The program the .exe starts (PyInstaller needs a script; it can't start from `python -m atc.app`)."""
from atc.app.__main__ import main

if __name__ == "__main__":
    main()
