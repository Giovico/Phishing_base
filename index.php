<?php

// 1. QUI VIENE INSERITO AUTOMATICAMENTE L'URL NGROK DALLO SCRIPT start_tool.sh
//    Preferiamo la variabile d'ambiente NGROK_URL (impostata dallo script) se presente.
//    In mancanza della variabile, manteniamo il valore hardcoded per compatibilità.
$env_ngrok = getenv('NGROK_URL');
if ($env_ngrok !== false && $env_ngrok !== '') {
    $ngrok_url = $env_ngrok;
} else {
    $ngrok_url = 'https://d4982ded468a.ngrok-free.app';
}

// --- NUOVA LOGICA DEL PROXY ---

// Costruisci l'URL di destinazione completo, includendo il percorso (es. /login)
$destination_url = $ngrok_url . $_SERVER['REQUEST_URI'];

// Inizializza cURL
$ch = curl_init();

// Imposta l'URL di destinazione
curl_setopt($ch, CURLOPT_URL, $destination_url);

// Costruisci gli header: inoltra quelli originali tranne Host
$forward_headers = [];
foreach (getallheaders() as $h => $v) {
    if (strtolower($h) === 'host') continue;
    $forward_headers[] = "$h: $v";
}
// Aggiungi header utili per ngrok
$forward_headers[] = 'ngrok-skip-browser-warning: true';
// Imposta gli header
if (!empty($forward_headers)) {
    curl_setopt($ch, CURLOPT_HTTPHEADER, $forward_headers);
}

// Imposta User-Agent e altre opzioni utili
curl_setopt($ch, CURLOPT_USERAGENT, isset($_SERVER['HTTP_USER_AGENT']) ? $_SERVER['HTTP_USER_AGENT'] : 'Mozilla/5.0');
curl_setopt($ch, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_1_1);
curl_setopt($ch, CURLOPT_ENCODING, ''); // accetta gzip/deflate
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HEADER, true); // vogliamo i header per gestire Location
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, false);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 10);
curl_setopt($ch, CURLOPT_TIMEOUT, 20);

// Per testing locale e tunnelling: evita fallimenti SSL dovuti a verifiche locali
curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);
curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, 0);

// Usa il corpo raw per POST/PUT per non perdere payload non form-urlencode
$method = $_SERVER['REQUEST_METHOD'];
if ($method === 'POST' || $method === 'PUT' || $method === 'PATCH') {
    $body = file_get_contents('php://input');
    curl_setopt($ch, CURLOPT_CUSTOMREQUEST, $method);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $body);
}

// Esegui la richiesta
$resp = curl_exec($ch);

// Gestione errori: log in debug e mostra messaggio conciso
if (curl_errno($ch)) {
    $err = curl_error($ch);
    // log
    @file_put_contents(__DIR__ . '/debug/ngrok.log', "[" . date('c') . "] cURL error: $err\n", FILE_APPEND);
    echo 'Errore cURL: ' . htmlspecialchars($err);
    curl_close($ch);
    exit;
}

// Separiamo header e body
$header_size = curl_getinfo($ch, CURLINFO_HEADER_SIZE);
$header_text = substr($resp, 0, $header_size);
$body = substr($resp, $header_size);
// Parse headers
$headers = preg_split("/\r?\n/", $header_text);
$response_headers = [];
foreach ($headers as $hline) {
    if (strpos($hline, ':') !== false) {
        list($hn, $hv) = explode(':', $hline, 2);
        $response_headers[trim($hn)] = trim($hv);
    }
}

// Se esiste Location, inoltrala al client
if (!empty($response_headers['Location'])) {
    header('Location: ' . $response_headers['Location']);
    curl_close($ch);
    exit;
}

// Altrimenti inoltra gli header rilevanti al client e poi il body
foreach ($response_headers as $hn => $hv) {
    // evita duplicare header come Transfer-Encoding che possono confondere
    if (in_array(strtolower($hn), ['transfer-encoding', 'content-encoding'])) continue;
    header("$hn: $hv");
}

echo $body;

// Chiudi la sessione cURL
curl_close($ch);

?>
