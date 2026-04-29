# Intentionally empty.
# PyInstaller 6 registers _MEIPASS via os.add_dll_directory() in its
# bootstrapper, activating LOAD_LIBRARY_SEARCH_DEFAULT_DIRS. The PySide6
# subdirectory (where icuuc.dll lives) is NOT registered by default, so
# src/app.py calls os.add_dll_directory(_MEIPASS/PySide6) before importing
# PySide6 to ensure Qt's bundled ICU v73 is found before System32's v72 stub.
