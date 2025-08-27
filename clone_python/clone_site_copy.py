import sys
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

import os
import hashlib
import urllib.parse
import re
import json
try:
    import requests
    from bs4 import BeautifulSoup
except Exception:
    requests = None
    BeautifulSoup = None

def clone_website(url, output_file="cloned_site.html"):
    """
    Clona il contenuto di un sito web dopo un certo ritardo e lo salva in un file HTML.
    Tenta di accettare i banner dei cookie.

    Args:
        url (str): L'URL del sito web da clonare.
        output_file (str, optional): Il nome del file HTML di output. 
                                     Defaults to "cloned_site.html".
    """
    print(f"Inizio clonazione di: {url}")

    try:
        # Inizializza il driver di Chrome
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        
        driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

        # Apri l'URL
        driver.get(url)

        # --- Logica per accettare i cookie ---
        try:
            # Lista di possibili testi per il pulsante di accettazione dei cookie
            accept_button_texts = [
                "Accett", "Accept", "Agree", 
                "Acconsent", "Va bene", "Chiudi", "Consenti"
            ]

            # Normalizziamo i token in minuscolo
            tokens = [t.strip().lower() for t in accept_button_texts if t]
            button = None

            # Aspetta brevemente che appaiano pulsanti/link nella pagina
            try:
                WebDriverWait(driver, 5).until(lambda d: d.find_elements(By.XPATH, "//button|//a|//input[@type='button']|//input[@type='submit']|//*[@role='button']|//*[@onclick']"))
            except Exception:
                pass

            # Prima cerchiamo elementi ovvi (button, a, input, elementi con role/onclick)
            elements = driver.find_elements(By.XPATH, "//button|//a|//input[@type='button']|//input[@type='submit']|//*[@role='button']|//*[@onclick]")

            # Se non troviamo nulla, cerchiamo anche div/span con testo visibile
            if not elements:
                try:
                    elements = driver.find_elements(By.XPATH, "//div|//span")
                except Exception:
                    elements = []

            # Funzione JS che valuta se un elemento è realmente interattivo e non parte di un menu/dropdown
            is_interactive_js = """
            var el = arguments[0];
            try{
                var tag = (el.tagName||'').toLowerCase();
                var role = (el.getAttribute && el.getAttribute('role')||'').toLowerCase();
                var onclick = el.getAttribute && el.getAttribute('onclick');
                var href = el.getAttribute && el.getAttribute('href');
                var tabindex = el.getAttribute && el.getAttribute('tabindex');
                var computed = window.getComputedStyle(el);
                var cursor = computed && computed.cursor || '';
                var ariaHaspopup = (el.getAttribute && el.getAttribute('aria-haspopup')||'').toLowerCase();

                // Se un antenato ha role/class indicante menu/dropdown, consideriamo non cliccabile per accettare cookie
                var ancestor = el;
                while(ancestor){
                    var arole = (ancestor.getAttribute && ancestor.getAttribute('role')||'').toLowerCase();
                    var acls = (ancestor.className||'').toLowerCase();
                    if (arole && (arole.indexOf('menu')!==-1 || arole.indexOf('navigation')!==-1 || arole.indexOf('listbox')!==-1 || arole.indexOf('tablist')!==-1)) return false;
                    if (acls && (acls.indexOf('menu')!==-1 || acls.indexOf('dropdown')!==-1 || acls.indexOf('popover')!==-1 || acls.indexOf('tooltip')!==-1)) return false;
                    ancestor = ancestor.parentElement;
                }

                // Se l'elemento dichiara aria-haspopup=true è probabilmente un trigger dropdown -> ignoralo
                if (ariaHaspopup==='true') return false;

                // Heuristics per interattività
                if (tag==='button' || tag==='a') return true;
                if (tag==='input' && el.getAttribute('type') && el.getAttribute('type').toLowerCase()!=='hidden') return true;
                if (role==='button' || role==='link') return true;
                if (href) return true;
                if (onclick) return true;
                if (tabindex && parseInt(tabindex)>=0) return true;
                if (cursor && cursor.indexOf('pointer')!==-1) return true;

                return false;
            }catch(e){ return false; }
            """

            for el in elements:
                try:
                    if not el.is_displayed():
                        continue
                    # Prendiamo testo o value o aria-label o innerText
                    text = (el.text or el.get_attribute('value') or el.get_attribute('aria-label') or el.get_attribute('innerText') or '')
                    text = text.strip().lower()
                    if not text:
                        continue

                    # Evitiamo di cliccare su testi troppo lunghi (descrittivi)
                    if len(text) > 60:
                        # elemento probabile descrizione, ignoralo
                        # print(f"Ignoro elemento troppo lungo: {text[:60]}...")
                        continue

                    for tok in tokens:
                        if tok and tok in text:
                            # Se il token è preceduto da parole condizionali o negazioni come 'se', 'se non', 'if not', 'non', 'don't', probabilmente è descrizione -> ignora
                            try:
                                neg_pattern = r"\b(?:(?:se|if)(?:\s+(?:non|no|dont|don't|do not|not))?|(?:non|no|dont|don't|do not|not))\s+" + re.escape(tok)
                                if re.search(neg_pattern, text):
                                    print(f"Ignoro frase condizionale/negativa contenente token: '{text}'")
                                    continue
                            except Exception:
                                pass

                            # Controlliamo se l'elemento è realmente interattivo e non parte di un menu/dropdown
                            try:
                                interactive = driver.execute_script(is_interactive_js, el)
                            except Exception:
                                interactive = False

                            if not interactive:
                                # Ignoriamo elementi non interattivi (es. frasi descrittive dentro dropdown)
                                print(f"Elemento con testo '{text}' ignorato (non interattivo o parte di menu).")
                                continue

                            # Trovato match parziale (case-insensitive) su elemento interattivo -> click
                            try:
                                el.click()
                            except Exception:
                                try:
                                    driver.execute_script("arguments[0].click();", el)
                                except Exception:
                                    continue
                            print(f"Pulsante cookie rilevato ('{text}'), cliccato.")
                            button = el
                            break
                    if button:
                        break
                except Exception:
                    continue

            if button:
                # Attendi che il banner sparisca: controlliamo che il testo contenente i token non sia più presente nel body
                try:
                    for tok in tokens:
                        try:
                            WebDriverWait(driver, 8).until(lambda d, t=tok: not d.execute_script("return (document.body && (document.body.innerText || '')).toLowerCase().includes(arguments[0]);", t))
                        except Exception:
                            # Prosegui con gli altri tentativi per questo token
                            pass
                except Exception:
                    pass

                # Se il controllo sopra non ha funzionato, proviamo ad attendere che l'elemento cliccato non sia più visibile
                try:
                    WebDriverWait(driver, 5).until(lambda d, el=button: not el.is_displayed())
                except Exception:
                    # Fallback: ricarica la pagina e attendi un po'
                    try:
                        driver.refresh()
                        time.sleep(3)
                    except Exception:
                        pass

                # Piccola pausa finale
                time.sleep(1) # Attendi che eventuali modifiche DOM si stabilizzino

                # Rimuovi selettivamente eventuali banner/cookie ancora presenti nella pagina (solo overlay/small containers)
                try:
                    remove_script = """
                    (function(tokens){
                        var vw = window.innerWidth, vh = window.innerHeight;
                        var all = document.querySelectorAll('div,section,aside,dialog,span,button,a');
                        for (var i=0;i<all.length;i++){
                            var el = all[i];
                            try{
                                var text = String(el.innerText||'').toLowerCase();
                                if (!text) continue;
                                for (var ti=0; ti<tokens.length; ti++){
                                    var tok = tokens[ti];
                                    if (tok && text.indexOf(tok)!==-1){
                                        var rect = el.getBoundingClientRect();
                                        if (rect.width>0 && rect.height>0 && (rect.height < vh*0.6 || rect.width < vw*0.9)){
                                            var anc = el;
                                            var depth = 0;
                                            while(anc && depth<6){
                                                if (anc.tagName && ['DIV','SECTION','ASIDE','DIALOG'].indexOf(anc.tagName)!==-1) break;
                                                anc = anc.parentElement; depth++;
                                            }
                                            try{ if (anc && anc.parentNode) anc.parentNode.removeChild(anc); else if (el.parentNode) el.parentNode.removeChild(el); }catch(e){}
                                        }
                                        break;
                                    }
                                }
                            }catch(e){}
                        }
                    })(arguments[0]);
                    """
                    driver.execute_script(remove_script, tokens)
                    time.sleep(0.3)
                except Exception as e:
                    print(f"Avviso: impossibile rimuovere banner residui via JS: {e}")
            else:
                print("Nessun banner per i cookie trovato con i selettori comuni.")

        except Exception as e:
            print(f"Non è stato possibile gestire il banner dei cookie: {e}")
        # --- Fine logica cookie ---

        # Attendi che la pagina si carichi completamente
        delay = 8 # Riduciamo il delay generale, parte dell'attesa è già nel cookie handling
        print(f"Attendo {delay} secondi per il caricamento del contenuto finale...")
        time.sleep(delay)

        # Ottieni il sorgente della pagina dopo il rendering (dopo click e attese)
        # Rimuovi overlay che coprono la viewport e bloccano interazioni (solo elementi fixed/sticky con alto z-index o background opaco)
        remove_overlays_js = """
        (function(){
            try {
                function removeCookieBanners() {
                    var cookieKeywords = ['cookie', 'cookies', 'consenti', 'accett', 'accept', 'agree', 'privacy', 'gdpr'];
                    var selectors = [
                        '[class*="cookie"]', '[class*="consent"]', '[class*="privacy"]', '[id*="cookie"]', '[id*="consent"]',
                        '[aria-label*="cookie" i]', '[role="dialog"]', '.modal', '.overlay', '.popup', '[class*="modal"]',
                        '[class*="overlay"]', '[class*="dialog"]', '[class*="banner"]', '[class*="notification"]'
                    ];

                    // Cerca elementi che corrispondono ai selettori
                    var elements = document.querySelectorAll(selectors.join(','));
                    elements.forEach(function(el) {
                        var text = (el.innerText || '').toLowerCase();
                        var containsCookieText = cookieKeywords.some(function(keyword) {
                            return text.includes(keyword);
                        });
                        
                        var style = window.getComputedStyle(el);
                        var isOverlay = style.position === 'fixed' || style.position === 'sticky' || parseInt(style.zIndex || 0) > 100;
                        
                        if (containsCookieText || (isOverlay && style.backgroundColor !== 'transparent')) {
                            if (el.parentNode) {
                                el.parentNode.removeChild(el);
                            }
                        }
                    });

                    // Rimuovi solo gli elementi che sembrano essere overlay di cookie o banner
                    document.querySelectorAll('body > *').forEach(function(el) {
                        var style = window.getComputedStyle(el);
                        var position = style.position;
                        var zIndex = parseInt(style.zIndex || 0);
                        var opacity = parseFloat(style.opacity || 1);
                        var rect = el.getBoundingClientRect();
                        var isFullscreenOverlay = rect.width >= window.innerWidth * 0.95 && rect.height >= window.innerHeight * 0.95;
                        
                        // Controlla se l'elemento è un potenziale overlay di cookie
                        var isCookieOverlay = false;
                        var text = (el.innerText || '').toLowerCase();
                        cookieKeywords.forEach(function(keyword) {
                            if (text.includes(keyword)) {
                                isCookieOverlay = true;
                            }
                        });
                        
                        // Rimuovi solo se è un overlay a tutto schermo con alto z-index o un banner dei cookie
                        if ((position === 'fixed' && zIndex > 100 && isFullscreenOverlay) || 
                            (isCookieOverlay && (position === 'fixed' || position === 'sticky'))) {
                            el.style.setProperty('display', 'none', 'important');
                            el.style.setProperty('pointer-events', 'none', 'important');
                            el.style.setProperty('visibility', 'hidden', 'important');
                            el.style.setProperty('opacity', '0', 'important');
                            el.style.setProperty('z-index', '-1', 'important');
                        }
                    });

                    // Ripulisci stili globali che potrebbero bloccare lo scroll
                    var html = document.documentElement;
                    var body = document.body;
                    [html, body].forEach(function(el) {
                        if (el) {
                            el.style.setProperty('overflow', 'auto', 'important');
                            el.style.setProperty('position', 'static', 'important');
                            el.style.setProperty('pointer-events', 'auto', 'important');
                        }
                    });
                }

                // Esegui la rimozione più volte per catturare elementi dinamici
                removeCookieBanners();
                setTimeout(removeCookieBanners, 500);
                setTimeout(removeCookieBanners, 1500);
                
                // Rimuovi anche eventuali overlay specifici dei cookie
                for(var i=0;i<els.length;i++){
                    var el = els[i];
                    try{
                        var cs = window.getComputedStyle(el);
                        
                        var rect = el.getBoundingClientRect();
                        if(rect.width<=0||rect.height<=0) continue;
                        
                        var rect = el.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) continue;
                        
                        // Verifica se è un banner/overlay dei cookie
                        var text = String(el.innerText||'').toLowerCase();
                        if (tokens.some(function(t) { return text.indexOf(t)!==-1; })) {
                            try {
                                // Rimuovi completamente i banner dei cookie
                                el.parentNode.removeChild(el);
                            } catch(e) {
                                try {
                                    // Fallback: nascondi completamente
                                    el.style.setProperty('display', 'none', 'important');
                                    el.style.setProperty('visibility', 'hidden', 'important');
                                    el.style.setProperty('pointer-events', 'none', 'important');
                                    el.style.setProperty('opacity', '0', 'important');
                                } catch(e) {}
                            }
                        }
                    } catch(e) {}
                }
            } catch(e) {}
        })();
        """
        try:
            driver.execute_script(remove_overlays_js)
            time.sleep(0.3)
        except Exception as e:
            print(f"Avviso: impossibile rimuovere overlay residui via JS: {e}")

        page_source = driver.page_source

        # Nota: la pulizia dell'HTML con rimozione di nodi è stata rimossa perché causava pagine vuote.
        # Manteniamo il page_source così com'è e procediamo a riscrivere solo le risorse (immagini, icone, inline url)

        # Proviamo a salvare le immagini referenziate nella pagina e aggiornare i riferimenti nel HTML
        if requests is not None and BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(page_source, "html.parser")

                # Sincronizza lo style inline per l'input email (spesso aggiunto dinamicamente) 
                try:
                    email_style = None
                    try:
                        email_style = driver.execute_script("var e=document.getElementById('email'); if(e) return e.getAttribute('style'); var e2=document.querySelector(\"input[name='email']\"); if(e2) return e2.getAttribute('style'); var e3=document.querySelector(\"[data-testid='royal-email']\"); if(e3) return e3.getAttribute('style'); return null;")
                    except Exception:
                        email_style = None

                    if email_style:
                        inp = soup.find('input', {'id':'email'}) or soup.find('input', {'name':'email'}) or soup.find('input', {'data-testid':'royal-email'})
                        if inp:
                            # imposta lo style solo se manca o è vuoto
                            if not inp.get('style'):
                                inp['style'] = email_style
                except Exception:
                    pass

                out_dir = os.path.dirname(os.path.abspath(output_file)) or '.'
                assets_dir = os.path.join(out_dir, 'assets')
                os.makedirs(assets_dir, exist_ok=True)

                def save_asset(asset_url):
                    try:
                        abs_url = urllib.parse.urljoin(url, asset_url)
                    except Exception:
                        return None
                    # Crea nome file basato su hash per evitare collisioni
                    h = hashlib.sha256(abs_url.encode()).hexdigest()[:16]
                    path = urllib.parse.urlparse(abs_url).path
                    ext = os.path.splitext(path)[1]
                    if not ext:
                        ext = '.bin'
                    filename = h + ext
                    local_path = os.path.join(assets_dir, filename)
                    if not os.path.exists(local_path):
                        try:
                            resp = requests.get(abs_url, timeout=15, stream=True)
                            if resp.status_code == 200:
                                with open(local_path, 'wb') as af:
                                    for chunk in resp.iter_content(8192):
                                        af.write(chunk)
                            else:
                                return None
                        except Exception:
                            return None
                    # Path relativo scritto nell'HTML
                    return os.path.join('assets', filename)

                # Aggiorna <img>
                for img in soup.find_all('img'):
                    src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                    if not src:
                        continue
                    if src.strip().startswith('data:'):
                        continue
                    local = save_asset(src)
                    if local:
                        img['src'] = local
                        if 'srcset' in img.attrs:
                            del img['srcset']

                # Aggiorna inline style url(...)
                for tag in soup.find_all(style=True):
                    style = tag['style']
                    matches = re.findall(r"url\(([^)]+)\)", style)
                    new_style = style
                    for m in matches:
                        u = m.strip().strip('\"\'')
                        if u.startswith('data:'):
                            continue
                        local = save_asset(u)
                        if local:
                            new_style = new_style.replace(m, "'" + local + "'")
                    if new_style != style:
                        tag['style'] = new_style

                # Aggiorna link rel=icon
                for link in soup.find_all('link'):
                    rel = link.get('rel')
                    if rel and ('icon' in rel or 'shortcut icon' in ' '.join(rel)):
                        href = link.get('href')
                        if href and not href.startswith('data:'):
                            local = save_asset(href)
                            if local:
                                link['href'] = local

                # Aggiungi stili CSS per i placeholder e la gestione degli input
                    style_tag = soup.new_tag('style')
                    style_tag.string = """
                    input::-webkit-input-placeholder { color: #777; opacity: 1; transition: opacity 0.3s ease; }
                    input::-moz-placeholder { color: #777; opacity: 1; transition: opacity 0.3s ease; }
                    input:-ms-input-placeholder { color: #777; opacity: 1; transition: opacity 0.3s ease; }
                    input::placeholder { color: #777; opacity: 1; transition: opacity 0.3s ease; }
                    input:focus::-webkit-input-placeholder { opacity: 0; }
                    input:focus::-moz-placeholder { opacity: 0; }
                    input:focus:-ms-input-placeholder { opacity: 0; }
                    input:focus::placeholder { opacity: 0; }
                    """
                    if soup.head:
                        soup.head.append(style_tag)
                    else:
                        head_tag = soup.new_tag('head')
                        head_tag.append(style_tag)
                        if soup.html:
                            soup.html.insert(0, head_tag)
                        else:
                            soup.insert(0, head_tag)

                # Rendi href e action assoluti e prepara i link di 'login/iscriviti' per aprire il sito reale
                try:
                    # normalizza tutti gli <a href> e le action dei form ad URL assoluti
                    for a in soup.find_all('a', href=True):
                        try:
                            a['href'] = urllib.parse.urljoin(url, a['href'])
                        except Exception:
                            pass
                    for form in soup.find_all('form'):
                        try:
                            action = form.get('action') or ''
                            form['action'] = urllib.parse.urljoin(url, action)
                        except Exception:
                            pass

                    # Imposta tutti i link per aprire nella stessa pagina
                    for a in soup.find_all('a'):
                        try:
                            if a.get('href'):
                                a['href'] = urllib.parse.urljoin(url, a.get('href',''))
                                # Rimuovi target="_blank" se presente
                                if 'target' in a.attrs:
                                    del a['target']
                        except Exception:
                            pass
                        except Exception:
                            continue

                    # Iniettiamo uno script sicuro che abilita il pulsante login quando campi compilati
                    js = """
                    (function(){
                      try{
                        // Funzione per gestire la rimozione del testo predefinito negli input
                        function handleInputDefaultText(input) {
                            var defaultText = input.value;
                            if (defaultText) {
                                input.addEventListener('focus', function() {
                                    if (this.value === defaultText) {
                                        this.value = '';
                                    }
                                });
                                
                                input.addEventListener('blur', function() {
                                    if (this.value === '') {
                                        this.value = defaultText;
                                    }
                                });
                            }
                        }
                        
                        // Applica il comportamento a tutti gli input nella pagina
                        document.querySelectorAll('input').forEach(handleInputDefaultText);
                        
                        // Gestione degli input placeholder e valori di default
                        document.querySelectorAll('input').forEach(function(input) {
                            var defaultValue = input.value;
                            if (defaultValue) {
                                input.setAttribute('data-default', defaultValue);
                                
                                input.addEventListener('focus', function() {
                                    if (this.value === this.getAttribute('data-default')) {
                                        this.value = '';
                                    }
                                });
                                
                                input.addEventListener('blur', function() {
                                    if (this.value.trim() === '') {
                                        this.value = this.getAttribute('data-default');
                                    }
                                });
                            }
                        });
                        
                        var authTokens = ['accedi','login','sign in','signin','iscriv','registr','signup','register','entra'];
                        function matchText(el){ try{ return (el.innerText||el.textContent||'').toLowerCase().trim(); }catch(e){return ''; } }
                        function isAuthText(text){ for(var i=0;i<authTokens.length;i++){ if(text.indexOf(authTokens[i])!==-1) return true; } return false; }

                        // Gestione placeholder per gli input
                        function setupPlaceholder(input) {
                            if(!input) return;
                            
                            var placeholder = '';
                            // Prova a ottenere il testo del placeholder da vari attributi
                            if(input.getAttribute('placeholder')) {
                                placeholder = input.getAttribute('placeholder');
                            } else if(input.getAttribute('data-placeholder')) {
                                placeholder = input.getAttribute('data-placeholder');
                            } else if(input.value) {
                                placeholder = input.value;
                                input.value = '';
                            }
                            
                            if(!placeholder) return;
                            
                            // Imposta il placeholder e svuota il valore
                            input.setAttribute('placeholder', placeholder);
                            if(input.value === placeholder) {
                                input.value = '';
                            }
                            
                            // Gestisci focus/blur per l'effetto placeholder
                            input.addEventListener('focus', function() {
                                if(this.value === this.getAttribute('placeholder')) {
                                    this.value = '';
                                }
                            });
                            
                            input.addEventListener('blur', function() {
                                if(this.value.trim() === '') {
                                    this.value = '';
                                    this.setAttribute('placeholder', placeholder);
                                }
                            });
                        }

                        // Applica gestione placeholder a tutti gli input rilevanti
                        document.querySelectorAll('input[type="text"], input[type="email"], input[type="password"]').forEach(setupPlaceholder);

                        // Marca elementi rilevanti e aggiunge listener che aprono la destinazione reale in nuova scheda
                        var elems = document.querySelectorAll('a,button,input[type=submit]');
                        elems.forEach(function(el){
                          try{
                            var txt = matchText(el);
                            if(!txt) return;
                            if(isAuthText(txt)){
                              el.setAttribute('data-auth-link','1');
                              
                              // Tutti i link si aprono nella stessa pagina
                              if(el.tagName.toLowerCase()==='a') {
                                  // Rimuovi target="_blank" se presente
                                  el.removeAttribute('target');
                                  
                                  el.addEventListener('click', function(e) {
                                      e.preventDefault();
                                      try {
                                          // Nascondi il form di login
                                          var loginForm = document.querySelector('form');
                                          if(loginForm) loginForm.style.display = 'none';
                                          
                                          // Vai all'URL di destinazione nella stessa scheda
                                          window.location.href = this.href;
                                      } catch(ex) {}
                                  });
                              }

                              // Imposta disabled di default sui pulsanti di login/accesso
                              if(el.tagName.toLowerCase() === 'button' || (el.tagName.toLowerCase() === 'input' && (el.type === 'submit' || el.type === 'button'))) {
                                el.setAttribute('disabled', '');
                                el.classList && el.classList.add('disabled');
                              }

                              var target = '';
                              var form = el.closest && el.closest('form');
                              if(form && form.action) target = form.action;
                              if(!target && el.href) target = el.href;
                              if(!target) target = window.location.origin;
                              el.setAttribute('data-auth-target', target);

                              el.addEventListener('click', function(e){
                                try{ 
                                    e.preventDefault(); 
                                    // Nascondi il form corrente
                                    var loginForm = document.querySelector('form');
                                    if(loginForm) loginForm.style.display = 'none';
                                    // Vai alla destinazione nella stessa scheda
                                    window.location.href = this.getAttribute('data-auth-target') || window.location.origin;
                                }catch(ex){}
                              });
                            }
                          }catch(e){}
                        });

                        // Abilita/disabilita il pulsante di login in base ai campi email/password
                        var email = document.querySelector("input[type='email'], input[name='email'], input#email, input[type='text']");
                        var pass  = document.querySelector("input[type='password'], input[name='password'], input#password");
                        if(email && pass){
                          var authButtons = Array.prototype.slice.call(document.querySelectorAll('[data-auth-link]'));
                          function update(){
                            var emailVal = email.value.trim();
                            var passVal = pass.value.trim();
                            var ok = emailVal !== '' && emailVal !== email.getAttribute('data-default') && 
                                   passVal !== '' && passVal !== pass.getAttribute('data-default');
                                   
                            authButtons.forEach(function(b){
                              try{
                                if(ok){ 
                                    b.removeAttribute('disabled'); 
                                    b.classList && b.classList.remove('disabled');
                                    b.classList && b.classList.add('enabled');
                                } else { 
                                    b.setAttribute('disabled', '');
                                    b.classList && b.classList.add('disabled');
                                    b.classList && b.classList.remove('enabled');
                                }
                              }catch(e){}
                            });
                          }
                          
                          ['input','change','keyup'].forEach(function(evt) {
                              email.addEventListener(evt, update);
                              pass.addEventListener(evt, update);
                          });
                          update();
                        }
                      }catch(e){}
                    })();
                    """
                    script_tag = soup.new_tag('script')
                    script_tag.string = js
                    if soup.body:
                        soup.body.append(script_tag)
                    else:
                        soup.append(script_tag)
                except Exception:
                    pass

                page_source = str(soup)
            except Exception as e:
                print(f"Errore durante il download/aggiornamento risorse: {e}")
        else:
            print("requests o BeautifulSoup non installati; per scaricare le immagini esegui: pip install requests beautifulsoup4")

        # Salva il sorgente in un file HTML
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(page_source)

        print(f"Sito clonato con successo e salvato come '{output_file}'")

    except Exception as e:
        print(f"Errore durante la clonazione del sito: {e}")

    finally:
        if 'driver' in locals():
            driver.quit()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python clone_site.py <URL>")
        sys.exit(1)

    target_url = sys.argv[1]
    clone_website(target_url)
