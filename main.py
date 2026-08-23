import os
import json
import time
import datetime
import smtplib
from email.mime.text import MIMEText
from google import genai
from google.genai.errors import APIError
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_ORIGEN = os.environ.get("EMAIL_ORIGEN")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_DESTINO = os.environ.get("EMAIL_DESTINO")

STABLECOINS = {"tether", "usd-coin", "first-digital-usd", "dai", "ethena-usde", "usdd", "pyusd", "tether-gold"}
HEADERS = {"User-Agent": "Mozilla/5.0"}
FILE_POSICIONES = "posiciones.json"
FILE_HISTORIAL = "historial.json"
FILE_CANDIDATAS = "candidatas.json"

FEE_TAKER_PCT = 0.0060
FEE_ROUNDTRIP_PCT = (FEE_TAKER_PCT * 2) * 100

def cargar_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def guardar_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def obtener_candidatas_coingecko():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "order": "volume_desc", "per_page": 50, "page": 1, "sparkline": False, "price_change_percentage": "24h"}
    try:
        res = requests.get(url, params=params, headers=HEADERS, timeout=10)
        res.raise_for_status()
        return [c["symbol"].upper() for c in res.json() if c["id"] not in STABLECOINS]
    except Exception as e:
        print("Error CoinGecko:", e)
        return []

def obtener_profundidad_libro_coinbase(symbol):
    url_ticker = f"https://api.exchange.coinbase.com/products/{symbol}-USD/ticker"
    url_book = f"https://api.exchange.coinbase.com/products/{symbol}-USD/book?level=2"
    
    try:
        res_t = requests.get(url_ticker, headers=HEADERS, timeout=4)
        if res_t.status_code != 200:
            return None
        t_data = res_t.json()
        precio_real = float(t_data.get("price", 0))
        bid, ask = float(t_data.get("bid", 0)), float(t_data.get("ask", 0))
        if precio_real == 0:
            return None
            
        spread_pct = ((ask - bid) / precio_real) * 100
        if spread_pct > 0.3:
            return None
            
        res_b = requests.get(url_book, headers=HEADERS, timeout=4)
        liquidez_ask_usd, liquidez_bid_usd = 0, 0
        if res_b.status_code == 200:
            b_data = res_b.json()
            bids, asks = b_data.get("bids", [])[:15], b_data.get("asks", [])[:15]
            liquidez_bid_usd = sum(float(b[0]) * float(b[1]) for b in bids)
            liquidez_ask_usd = sum(float(a[0]) * float(a[1]) for a in asks)
            
        return {
            "symbol": symbol,
            "precio_vivido": precio_real,
            "spread_pct": round(spread_pct, 3),
            "profundidad_compra_usd": round(liquidez_bid_usd, 2),
            "profundidad_venta_usd": round(liquidez_ask_usd, 2)
        }
    except Exception:
        pass
    return None

def construir_embudo_mercado():
    candidatas = obtener_candidatas_coingecko()
    matriz_filtrada = []
    for sym in candidatas:
        datos_depth = obtener_profundidad_libro_coinbase(sym)
        if datos_depth and datos_depth["profundidad_compra_usd"] >= 10000:
            matriz_filtrada.append(datos_depth)
        if len(matriz_filtrada) >= 5:
            break
    return matriz_filtrada

def analizar_oportunidades_y_cartera(matriz_fina, posiciones_actuales, candidatas_previas):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Actúa como un gestor cuantitativo avanzado con motor de Doble Confirmación Técnica.
    
    POSICIONES ACTIVAS EN CARTERA:
    {posiciones_actuales}
    
    CANDIDATAS EN SEGUIMIENTO DESDE EL CICLO ANTERIOR (1 HORA ATRÁS):
    {candidatas_previas}
    
    MATRIZ PRE-FILTRADA EN TIEMPO REAL (COINBASE LEVEL 2):
    {matriz_fina}
    
    REGLAS DE DOBLE CONFIRMACIÓN Y DECISIÓN:
    1. OPORTUNIDAD ÉLITE: Si una moneda tiene una liquidez extrema (> $50,000 en soporte) y ruptura clara, ordénala COMPRAR inmediatamente (sin esperar).
    2. CONFIRMACIÓN HORARIA: Si una moneda estaba en "CANDIDATAS EN SEGUIMIENTO" y en la matriz actual MANTIENE la fuerza técnica, apruébala para COMPRAR (Doble Confirmación superada).
    3. NUEVA CANDIDATA: Si ves una buena oportunidad pero no es Élite, regístrala como "EN_SEGUIMIENTO" para confirmarla en el siguiente ciclo.
    4. REVISAR CARTERA: Evalúa si alguna de las posiciones activas debe VENDERSE.
    
    INCLUYE OBLIGATORIAMENTE ESTOS BLOQUES JSON AL FINAL DE TU RESPUESTA:

    ===JSON_CARTERA===
    [
      {{"ticker": "BTC", "precio_entrada": 64000.0, "stop_loss": 62720.0, "take_profit": 66560.0}}
    ]
    ===JSON_CARTERA===

    ===JSON_CANDIDATAS===
    ["ETH", "SOL"]
    ===JSON_CANDIDATAS===

    ===JSON_DECISION===
    {{
      "accion": "COMPRAR",
      "resumen": "COMPRA VALIDADA BTC: Confirmación técnica de 2da hora + Soporte $120k."
    }}
    ===JSON_DECISION===
    """
    
    modelos = ['gemini-3.6-flash']
    for modelo in modelos:
        for intento in range(3):
            try:
                response = client.models.generate_content(model=modelo, contents=prompt)
                return response.text
            except APIError as e:
                print(f"Intento {intento + 1} falló: {e}")
                time.sleep(5)
    raise Exception("Error consultando Gemini.")

def actualizar_historial_y_cartera(respuesta_ia):
    texto_correo = respuesta_ia
    
    # 1. Cartera
    if "===JSON_CARTERA===" in respuesta_ia:
        try:
            partes = respuesta_ia.split("===JSON_CARTERA===")
            texto_correo = partes[0].strip()
            guardar_json(FILE_POSICIONES, json.loads(partes[1].strip()))
        except Exception as e:
            print("Error JSON cartera:", e)

    # 2. Candidatas en seguimiento
    if "===JSON_CANDIDATAS===" in respuesta_ia:
        try:
            partes_c = respuesta_ia.split("===JSON_CANDIDATAS===")
            guardar_json(FILE_CANDIDATAS, json.loads(partes_c[1].strip()))
        except Exception as e:
            print("Error JSON candidatas:", e)

    # 3. Historial
    historial = cargar_json(FILE_HISTORIAL, {"capital_inicial": 1000.0, "registro_saldo": [], "decisiones": []})
    fecha_iso = datetime.datetime.utcnow().isoformat() + "Z"

    if "===JSON_DECISION===" in respuesta_ia:
        try:
            partes_dec = respuesta_ia.split("===JSON_DECISION===")
            dec_data = json.loads(partes_dec[1].strip())
            dec_data["fecha"] = fecha_iso
            historial["decisiones"].append(dec_data)
        except Exception as e:
            print("Error JSON decisión:", e)

    historial["registro_saldo"].append({"fecha": fecha_iso, "saldo": round(historial.get("capital_inicial", 1000.0), 2)})
    guardar_json(FILE_HISTORIAL, historial)
    return texto_correo

def enviar_correo(texto):
    msg = MIMEText(texto, 'plain', 'utf-8')
    msg['Subject'] = "⚡ Alerta Trading Validado - Confirmación Técnica"
    msg['From'] = EMAIL_ORIGEN
    msg['To'] = EMAIL_DESTINO

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())

if __name__ == "__main__":
    posiciones = cargar_json(FILE_POSICIONES, [])
    candidatas = cargar_json(FILE_CANDIDATAS, [])
    matriz_fina = construir_embudo_mercado()
    if matriz_fina:
        respuesta_raw = analizar_oportunidades_y_cartera(matriz_fina, posiciones, candidatas)
        informe_limpio = actualizar_historial_y_cartera(respuesta_raw)
        enviar_correo(informe_limpio)
    else:
        print("No se encontraron activos válidos.")
