import os
import json
import time
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

# --- ESTRUCTURA DE COMISIONES COINBASE ADVANCED ---
# Ajusta estos valores según tu nivel de volumen en Coinbase
FEE_TAKER_PCT = 0.0060  # 0.60% comisión de mercado
FEE_MAKER_PCT = 0.0040  # 0.40% comisión límite
FEE_ROUNDTRIP_PCT = (FEE_TAKER_PCT + FEE_TAKER_PCT) * 100  # ~1.20% Coste total entrada/salida

# --- GESTIÓN DE MEMORIA Y POSICIONES ---

def cargar_posiciones():
    if os.path.exists(FILE_POSICIONES):
        try:
            with open(FILE_POSICIONES, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_posiciones(posiciones):
    with open(FILE_POSICIONES, "w", encoding="utf-8") as f:
        json.dump(posiciones, f, indent=4, ensure_ascii=False)

# --- ESCANEO DE MERCADO Y VALIDACIÓN EN DIRECTO ---

def obtener_candidatas_coingecko():
    """ CoinGecko actúa SOLO como radar de volumen para descubrir activos interesantes """
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "order": "volume_desc", "per_page": 40, "page": 1, "sparkline": False, "price_change_percentage": "24h"}
    try:
        res = requests.get(url, params=params, headers=HEADERS, timeout=10)
        res.raise_for_status()
        return [c["symbol"].upper() for c in res.json() if c["id"] not in STABLECOINS][:20]
    except Exception as e:
        print("Error CoinGecko Radar:", e)
        return []

def obtener_precio_real_coinbase(symbol):
    """ VALIDACIÓN EN VIVO: Obtiene el precio ejecutable exacto en Coinbase para evitar el efecto espejismo """
    url = f"https://api.exchange.coinbase.com/products/{symbol}-USD/ticker"
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        if res.status_code == 200:
            data = res.json()
            precio_real = float(data.get("price", 0))
            bid = float(data.get("bid", 0))
            ask = float(data.get("ask", 0))
            volume_24h = float(data.get("volume", 0))
            spread = ask - bid
            spread_pct = (spread / precio_real) * 100 if precio_real > 0 else 0
            
            return {
                "symbol": symbol,
                "coinbase_precio_vivo": precio_real,
                "coinbase_bid": bid,
                "coinbase_ask": ask,
                "spread_pct": round(spread_pct, 3),
                "volume_24h_coinbase": round(volume_24h, 2)
            }
    except Exception:
        pass
    return None

def construir_matriz_validada():
    candidatas = obtener_candidatas_coingecko()
    matriz_verificada = []
    
    for sym in candidatas:
        # Extraemos el precio REAL e INSTANTÁNEO directamente de Coinbase
        datos_cb = obtener_precio_real_coinbase(sym)
        if datos_cb and datos_cb["coinbase_precio_vivo"] > 0:
            matriz_verificada.append(datos_cb)
            
    return matriz_verificada

# --- INTELIGENCIA ARTIFICIAL Y CÁLCULO NETO DE RENTABILIDAD ---

def analizar_oportunidades_y_cartera(matriz, posiciones_actuales):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    Actúa como un gestor cuantitativo estricto para Coinbase Advanced Trade.
    
    PARAMETROS DE COMISIÓN DE COINBASE:
    - Coste por operación de compra/venta (Roundtrip Fee): {FEE_ROUNDTRIP_PCT:.2f}%
    - REGLA DE ORO DE COSTES: Ninguna recomendación de compra es válida si el objetivo estimado no supera holgadamente el coste de las comisiones ({FEE_ROUNDTRIP_PCT:.2f}%).
    
    ESTADO ACTUAL DE LA CARTERA:
    {posiciones_actuales}
    
    MATRIZ DE PRECIOS EN DIRECTO Y LIQUIDEZ (COINBASE LIVE):
    {matriz}
    
    INSTRUCCIONES DE FILTRADO ANTI-FALSOS POSITIVOS:
    1. VALIDACIÓN EN TIEMPO REAL: Los precios mostrados provienen directamente del ticker de Coinbase. No asumas precios de otras fuentes.
    2. REVISAR POSICIONES: Evalúa si alguna moneda en cartera debe VENDERSE por alcanzar un beneficio neto claro o por activación de Stop Loss.
    3. SELECCIONAR COMPRAS NETAS: Si encuentras una oportunidad, el Take Profit debe ser suficiente para cubrir la comisión de {FEE_ROUNDTRIP_PCT:.2f}% y dejar al menos un +2.5% de BENEFICIO NETO REAL.
    4. SPREAD: Descarta monedas cuyo Spread sea > 0.5%, ya que la iliquidez se comería las ganancias.
    
    REGLAS DE SALIDA:
    Genera el informe con este formato:
    
    🚨 ALERTAS DE GESTIÓN Y TRADING NETO 🚨
    - Moneda: [Ticker]
    - Acción: [COMPRAR / VENDER / MANTENER]
    - Precio en Vivo Coinbase: $X.XX
    - Comisión Estimada Coinbase ({FEE_ROUNDTRIP_PCT:.2f}%): $X.XX
    - Target Profit NETO (Libre de comisiones): +X.XX% ($X.XX)
    - Stop Loss Sugerido: $X.XX
    - Justificación de Liquidez y Spread: [Análisis del Spread en vivo]
    
    AL FINAL DEL TEXTO, INCLUYE EL BLOQUE JSON DE CARTERA ACTUALIZADA ENTRE ESTAS MARCAS:
    ===JSON_CARTERA===
    [
      {{"ticker": "BTC", "precio_entrada": 64000.0, "stop_loss": 62720.0, "take_profit": 66560.0}}
    ]
    ===JSON_CARTERA===
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
    raise Exception("Error consultando la IA.")

def procesar_respuesta_y_guardar(respuesta_ia):
    if "===JSON_CARTERA===" in respuesta_ia:
        partes = respuesta_ia.split("===JSON_CARTERA===")
        texto_correo = partes[0].strip()
        json_str = partes[1].strip()
        try:
            nuevas_posiciones = json.loads(json_str)
            guardar_posiciones(nuevas_posiciones)
        except Exception as e:
            print("Error parseando JSON de cartera:", e)
        return texto_correo
    return respuesta_ia

def enviar_correo(texto):
    msg = MIMEText(texto, 'plain', 'utf-8')
    msg['Subject'] = "⚡ Alerta Trading Validado Coinbase (Neto Fees)"
    msg['From'] = EMAIL_ORIGEN
    msg['To'] = EMAIL_DESTINO

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())

if __name__ == "__main__":
    posiciones = cargar_posiciones()
    matriz_live = construir_matriz_validada()
    if matriz_live:
        respuesta_raw = analizar_oportunidades_y_cartera(matriz_live, posiciones)
        informe_limpio = procesar_respuesta_y_guardar(respuesta_raw)
        enviar_correo(informe_limpio)
    else:
        print("Error construyendo matriz live de Coinbase.")
