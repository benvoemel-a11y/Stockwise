#!/bin/bash
# Filer als eigene Mac-App einrichten und auf den Schreibtisch legen (ohne Compiler).
cd "$(dirname "$0")" || exit 1
DIR="$HOME/.filer"
APP="$HOME/Desktop/Filer.app"
PY="$DIR/venv/bin/python"

pause() { echo; read -n1 -s -r -p "Beliebige Taste drücken, um das Fenster zu schließen …"; echo; }

echo "Filer wird eingerichtet …"
echo

# 0) Kostenloses Apple-Werkzeug (bringt Python mit)
if ! xcode-select -p >/dev/null 2>&1; then
  echo "Dein Mac braucht zuerst ein kostenloses Werkzeug von Apple."
  echo "Im Fenster, das gleich erscheint, auf „Installieren“ klicken."
  echo "Wenn das fertig ist, den Befehl einfach noch einmal ausführen."
  xcode-select --install >/dev/null 2>&1
  pause; exit 0
fi

# 1) Python-Umgebung
mkdir -p "$DIR"
if [ ! -x "$PY" ]; then
  python3 -m venv "$DIR/venv" || { echo "Python-Umgebung konnte nicht erstellt werden."; pause; exit 1; }
fi

# 2) Mac-Bausteine für Fenster und Anzeige (einmalig)
echo "Lade Bausteine (einmalig, kann 1–2 Minuten dauern) …"
"$PY" -m pip install -q --upgrade pip >/dev/null 2>&1
if ! "$PY" -m pip install -q pyobjc-framework-WebKit pyobjc-framework-Quartz; then
  echo; echo "Download fehlgeschlagen. Bitte Internetverbindung prüfen und den Text oben an Claude schicken."
  pause; exit 1
fi
if ! "$PY" -c "import AppKit, WebKit, Quartz, PyObjCTools.AppHelper"; then
  echo; echo "Die Bausteine lassen sich nicht laden. Bitte den Text oben an Claude schicken."
  pause; exit 1
fi

# 3) App bauen (ersetzt die alte Version)
# Laufendes Filer sicher beenden, damit wirklich die neue Version startet
osascript -e 'tell application "Filer" to quit' >/dev/null 2>&1
pkill -f "Filer.app/Contents/" >/dev/null 2>&1
pkill -f "Resources/main.py" >/dev/null 2>&1
sleep 1
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp main.py index.html icon.png "$APP/Contents/Resources/"

# Eigener Python-Starter in der App, damit der Mac sie im Dock als „Filer“ mit Icon zeigt
MODE="venv"
SITE="$("$PY" -c 'import site; print(site.getsitepackages()[0])')"
REAL="$("$PY" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
GUI_BIN="$(dirname "$REAL")/../Resources/Python.app/Contents/MacOS/Python"
BIN="$APP/Contents/MacOS/filer-python"
if [ -f "$GUI_BIN" ]; then
  GUI_DIR="$(cd "$(dirname "$GUI_BIN")" && pwd)"
  cp "$GUI_BIN" "$BIN"
  for lib in $(otool -L "$BIN" 2>/dev/null | awk 'NR>1 {print $1}' | grep '^@executable_path/'); do
    rel="${lib#@executable_path/}"
    abs="$(cd "$GUI_DIR/$(dirname "$rel")" 2>/dev/null && pwd)/$(basename "$rel")"
    install_name_tool -change "$lib" "$abs" "$BIN" 2>/dev/null
  done
  codesign --force --sign - "$BIN" >/dev/null 2>&1
  if PYTHONPATH="$SITE" "$BIN" -c "import AppKit, WebKit, Quartz, PyObjCTools.AppHelper" >/dev/null 2>&1; then
    MODE="bundle"
  else
    rm -f "$BIN"
  fi
fi

L="$APP/Contents/MacOS/Filer"
if [ "$MODE" = "bundle" ]; then
  {
    echo '#!/bin/bash'
    echo 'D="$(cd "$(dirname "$0")" && pwd)"'
    echo "export PYTHONPATH=\"$SITE\""
    echo 'exec "$D/filer-python" "$D/../Resources/main.py" >> "$HOME/.filer/filer.log" 2>&1'
  } > "$L"
else
  {
    echo '#!/bin/bash'
    echo 'R="$(cd "$(dirname "$0")/../Resources" && pwd)"'
    echo 'exec "$HOME/.filer/venv/bin/python" "$R/main.py" >> "$HOME/.filer/filer.log" 2>&1'
  } > "$L"
fi
chmod +x "$L"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Filer</string>
  <key>CFBundleDisplayName</key><string>Filer</string>
  <key>CFBundleIdentifier</key><string>de.bene.filer</string>
  <key>CFBundleExecutable</key><string>Filer</string>
  <key>CFBundleIconFile</key><string>Filer</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>5</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

ICONSET="$(mktemp -d)/Filer.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s icon.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) icon.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Filer.icns"
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" >/dev/null 2>&1

echo
if [ "$MODE" = "bundle" ]; then
  echo "Fertig. Filer liegt als eigene App auf deinem Schreibtisch und startet gleich."
else
  echo "Fertig. Filer startet gleich (im Dock kann weiterhin „Python“ stehen – bitte Claude Bescheid geben)."
fi
open "$APP"
pause
