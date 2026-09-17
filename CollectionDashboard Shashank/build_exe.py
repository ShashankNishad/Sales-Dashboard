"""
build_exe.py
------------
Run this ON WINDOWS (inside your venv, with requirements.txt installed)
to produce CollectionDashboard.exe in the dist/ folder.

    python build_exe.py

This wraps PyInstaller with the correct --add-data flags so that the
templates/ and static/ folders are bundled inside the .exe, and the
database/uploads/logs folders are created next to the .exe at runtime
(see app.py's BASE_DIR logic for frozen mode).

Usage after building:
  1. Go to dist/CollectionDashboard/
  2. Double-click CollectionDashboard.exe
  3. Your browser opens automatically to the dashboard
"""

import subprocess
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    sep = ";" if os.name == "nt" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=CollectionDashboard",
        "--onedir",
        "--noconfirm",
        "--windowed",  # no console window; remove this flag if you want a debug console
        f"--add-data=templates{sep}templates",
        f"--add-data=static{sep}static",
        "--hidden-import=pandas",
        "--hidden-import=openpyxl",
        "--hidden-import=engineio.async_drivers.threading",
        "app.py",
    ]
    print("Running:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=BASE_DIR)
    print("\nBuild complete. Find your EXE in dist/CollectionDashboard/CollectionDashboard.exe")


if __name__ == "__main__":
    main()
