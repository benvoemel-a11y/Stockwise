#!/bin/bash
# Filer für den Mac installieren oder aktualisieren – mit einer Zeile im Terminal:
#   bash -c "$(curl -fsSL https://benvoemel-a11y.github.io/Stockwise/filer/mac/install.sh)"
# Deine Einträge (~/.filer.json) bleiben dabei erhalten.
URL="https://benvoemel-a11y.github.io/Stockwise/filer/mac"
TMP="$(mktemp -d)/Filer"
mkdir -p "$TMP" || exit 1
echo "Lade die neueste Filer-Version …"
for f in main.py index.html icon.png Installieren.command; do
  if ! curl -fsSL "$URL/$f?t=$(date +%s)" -o "$TMP/$f"; then
    echo "Download fehlgeschlagen ($f). Bitte Internetverbindung prüfen."; exit 1
  fi
done
V="$(grep -o "Filer Mac v[0-9]*" "$TMP/index.html" | head -1)"
echo "Neue Version: ${V:-unbekannt}"
bash "$TMP/Installieren.command"
