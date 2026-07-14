#!/bin/bash
cd "$(dirname "$0")"

PYTHON_BIN=""
for candidate in \
  /opt/homebrew/bin/python3.13 \
  /usr/local/bin/python3.13 \
  /opt/homebrew/bin/python3.12 \
  /usr/local/bin/python3.12 \
  python3
do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON_BIN="$candidate"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "Nie znaleziono Python 3."
  read -p "Naciśnij Enter..."
  exit 1
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
python -m pip install -r requirements.txt

echo ""
echo "GO PARTNER Manager 4.21 ING BANK uruchomiony."
echo "Na tym Macu: http://localhost:8501"
echo "Inna osoba w tej samej sieci Wi-Fi powinna otworzyć:"
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
if [ -n "$IP" ]; then
  echo "http://$IP:8501"
fi
echo ""
open "http://localhost:8501"

python app.py
