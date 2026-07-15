"""
run_app.py
------------
Startet die Streamlit-App programmatisch. Dieses Skript ist der
Einstiegspunkt fuer die .exe (PyInstaller braucht ein "normales"
Python-Skript als Ziel, keine Streamlit-CLI).

Manuell starten (ohne exe) geht weiterhin einfach mit:
    streamlit run app.py
"""

import os
import sys

from streamlit.web import cli as stcli


def resource_path(relative_path: str) -> str:
    """Findet Dateien sowohl im Normalbetrieb als auch in der gebauten exe
    (PyInstaller entpackt alles in einen temporären _MEIPASS-Ordner)."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


if __name__ == "__main__":
    app_path = resource_path("app.py")
    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
        "--server.headless=false",
    ]
    sys.exit(stcli.main())
