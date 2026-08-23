import os
import json
import time
import datetime
import smtplib
from email.mime.text import MIMEText
from google import genai
from google.genai.errors import APIError
import requests
import urllib.parse

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_ORIGEN = os.environ.get("EMAIL_ORIGEN")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_DESTINO = os.environ.get("EMAIL_DESTINO")
WHATSAPP_PHONE = os.environ.get("WHATSAPP_PHONE")
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY")

STABLECOINS = {"tether", "usd-coin", "first-digital-usd", "dai", "ethena-usde", "usdd", "pyusd", "tether-gold"}
HEADERS = {"User-Agent": "Mozilla/5.0"}
FILE_POSICIONES = "posiciones.json"
FILE_HISTORIAL = "historial.json"
FILE_CANDIDATAS = "candidatas.json"

FEE_TAKER_PCT = 0.0060
FEE_ROUNDTRIP_PCT = (FEE_TAKER_PCT * 2) * 100  # ~1.20% coste ida/vuelta
RIESGO_POR_TRADE_PCT = 0.015                   # Riesgo máximo del 1.5% del capital total por operación ($R)
MAX_POSICIONES_PARALELO = 4                    # 4 posiciones simultáneas (~750€ - 800€ por posición)

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

def enviar_whatsapp(mensaje):
    if not WHATSAPP_PHONE or not WHATSAPP_API_KEY:
        print("WhatsApp Secrets no configurados.")
        return
    try:
        texto_encoded = urllib.parse.quote(mensaje)
        url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_PHONE}&text={texto_encoded}&apikey={WHATSAPP_API_KEY}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            print("Mensaje de WhatsApp enviado correctamente.")
        else:
            print(f"Error enviando WhatsApp: Status {res.status_code}")
    except Exception as e:
        print("Error en conexión con CallMeBot:", e)

def evaluar_regimen_macro_btc():
    url_stats = "https://api.exchange.coinbase.com/products/BTC-USD/stats"
    url_ticker = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
    
    try:
        res_t = requests.get(url_ticker, headers=HEADERS, timeout=4)
        res_s = requests.get(url_stats, headers=HEADERS, timeout=4)
        
        if res_t.status_code == 200 and res_s.status_code == 200:
            precio_actual = float(res_t.json().get("price", 0))
            open_24h = float(res_s.json().get("open", precio_actual))
            
            if open_24h > 0:
                cambio_btc_pct = ((precio_actual - open_24h) / open_24h) * 100
                alcista_o_neutral = cambio_btc_pct > -3.5
                return {
                    "btc_precio": precio_actual,
                    "btc_cambio_24h_pct": round(cambio_btc_pct, 2),
                    "mercado_seguro": alcista_o_neutral
                }
    except Exception as e:
        print("Error consultando Macro BTC:", e)
    
    return {"btc_precio": 0, "btc_cambio_24h_pct": 0.0, "mercado_seguro": True}

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
        if len(matriz_filtrada) >= 8:
            break
    return matriz_filtrada

def analizar_oportunidades_y_cartera(matriz_fina, posiciones_actuales, candidatas_previas, saldo_simulado, macro_btc):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    riesgo_maximo_usd = saldo_simulado * RIESGO_POR_TRADE_PCT
    slots_disponibles = MAX_POSICIONES_PARALELO - len(posiciones_actuales)
    monto_maximo_por_slot = saldo_simulado / MAX_POSICIONES_PARALELO
    
    prompt = f"""
    Actúa como un Gestor Cuantitativo Profesional de Fondos Cripto con Filtro Macro de BTC Integrado.
    
    ESTADO MACRO DEL MERCADO (FILTRO BITCOIN):
    - Precio BTC: ${macro_btc.get('btc_precio', 0):.2f} USD
    - Variación BTC 24h: {macro_btc.get('btc_cambio_24h_pct', 0.0)}%
    - Estado Filtro Macro: {'SEGURO (Permitido operar)' if macro_btc.get('mercado_seguro') else 'PELIGRO MACRO (Bloquear nuevas compras)'}
    
    PARÁMETROS CUANTITATIVOS DE CUENTA:
    - Capital Total Disponible: ${saldo_simulado:.2f} USD
    - Riesgo Máximo Autorizado por Operación (R): ${riesgo_maximo_usd:.2f} USD (1.5% del saldo total)
    - Máximo Permitido por Slot/Operación: ${monto_maximo_por_slot:.2f} USD
    - Comisiones Ida/Vuelta Coinbase: {FEE_ROUNDTRIP_PCT:.2f}%
    - Huecos Disponibles en Cartera: {slots_disponibles} de {MAX_POSICIONES_PARALELO} máximo
    
    POSICIONES ACTIVAS ACTUALES ({len(posiciones_actuales)}/{MAX_POSICIONES_PARALELO}):
    {posiciones_actuales}
    
    CANDIDATAS EN SEGUIMIENTO (DOBLE CONFIRMACIÓN):
    {candidatas_previas}
    
    MATRIZ DE LIQUIDEZ NIVEL 2 (COINBASE):
    {matriz_fina}
    
    REGLAS DE GESTIÓN INSTITUCIONAL CON FILTRO MACRO:
    1. SI FILTRO MACRO = PELIGRO (BTC descolgándose): NO ABRIR NUEVAS POSICIONES. MANTENER LÍQUIDO EL CAPITAL LIBRE.
    2. SI FILTRO MACRO = SEGURO y hay slots libres ({slots_disponibles} disponibles): Evalúa ABRIR nuevas entradas.
       Monto USD = min(${monto_maximo_por_slot:.2f}, ${riesgo_maximo_usd:.2f} / % Distancia a Stop Loss).
    3. GESTIONAR POSICIONES EXISTENTES (SIEMPRE ACTIVO):
       - Ganancia Neta >= +1.5%: Mueve Stop Loss a precio_entrada (BREAK-EVEN / Riesgo Cero).
       - Ganancia Neta >= +3.0%: TRAILING STOP a 1.5% por debajo del máximo alcanzado.
       - Si salta el Stop Loss: Vender y devolver capital e intereses a la caja común.
    
    INCLUYE OBLIGATORIAMENTE ESTOS BLOQUES JSON AL FINAL:

    ===JSON_CARTERA===
    [
      {{"ticker": "BTC", "precio_entrada": 64000.0, "monto_usd": 750.0, "stop_loss": 64000.0, "take_profit": 67000.0, "break_even": true, "max_precio_alcanzado": 65500.0}}
    ]
    ===JSON_CARTERA===

    ===JSON_CANDIDATAS===
    ["SOL", "AVAX"]
    ===JSON_CANDIDATAS===

    ===JSON_DECISION===
    {{
      "accion": "MANTENER",
      "resumen": "MANTENER POSICIONES: Macro BTC a ${macro_btc.get('btc_precio', 0):.2f} ({macro_btc.get('btc_cambio_24h_pct', 0.0)}%). Protegiendo las {len(posiciones_actuales)} posiciones activas con Stop Loss ajustados.",
      "profit_cerrado_usd": 0.0
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
    historial = cargar_json(FILE_HISTORIAL, {"capital_inicial": 3300.0, "registro_saldo": [], "decisiones": [], "ultimo_envio_whatsapp": ""})
    fecha_dt = datetime.datetime.utcnow()
    fecha_iso = fecha_dt.isoformat() + "Z"

    saldo_actual = historial.get("registro_saldo", [{}])[-1].get("saldo", historial.get("capital_inicial", 3300.0)) if historial.get("registro_saldo") else historial.get("capital_inicial", 3300.0)

    resumen_decision = ""
    if "===JSON_DECISION===" in respuesta_ia:
        try:
            partes_dec = respuesta_ia.split("===JSON_DECISION===")
            dec_data = json.loads(partes_dec[1].strip())
            dec_data["fecha"] = fecha_iso
            resumen_decision = dec_data.get("resumen", "")
            
            profit_usd = float(dec_data.get("profit_cerrado_usd", 0.0))
            saldo_actual += profit_usd
            
            historial["decisiones"].append(dec_data)
        except Exception as e:
            print("Error JSON decisión:", e)

    posiciones = []
    if "===JSON_CARTERA===" in respuesta_ia:
        try:
            partes = respuesta_ia.split("===JSON_CARTERA===")
            texto_correo = partes[0].strip()
            posiciones = json.loads(partes[1].strip())
            guardar_json(FILE_POSICIONES, posiciones)
        except Exception as e:
            print("Error JSON cartera:", e)

    if "===JSON_CANDIDATAS===" in respuesta_ia:
        try:
            partes_c = respuesta_ia.split("===JSON_CANDIDATAS===")
            guardar_json(FILE_CANDIDATAS, json.loads(partes_c[1].strip()))
        except Exception as e:
            print("Error JSON candidatas:", e)

    historial["registro_saldo"].append({"fecha": fecha_iso, "saldo": round(saldo_actual, 2)})
    
    # LÓGICA DE RESUMEN DIARIO POR WHATSAPP (A las 20:00h UTC o en forzado manual)
    ultimo_envio_str = historial.get("ultimo_envio_whatsapp", "")
    debe_enviar_whatsapp = False
    
    if not ultimo_envio_str:
        debe_enviar_whatsapp = True
    else:
        try:
            ultimo_envio_dt = datetime.datetime.fromisoformat(ultimo_envio_str.replace("Z", ""))
            horas_pasadas = (fecha_dt - ultimo_envio_dt).total_seconds() / 3600.0
            if horas_pasadas >= 23.0:
                debe_enviar_whatsapp = True
        except Exception:
            debe_enviar_whatsapp = True

    if debe_enviar_whatsapp:
        cap_ini = historial.get("capital_inicial", 3300.0)
        diff = saldo_actual - cap_ini
        pct = (diff / cap_ini) * 100
        activos_str = ", ".join([p.get("ticker", "") for p in posiciones]) if posiciones else "Ninguno (100% Liquidez)"
        
        msg_wa = (
            f"📊 *RESUMEN DIARIO DE TRADING (Fondo 3,000 €)*\n\n"
            f"💰 *Capital Actual:* ${saldo_actual:.2f} USD\n"
            f"📈 *Rendimiento Total:* {pct:+.2f}% (${diff:+.2f} USD)\n"
            f"💼 *Posiciones Activas:* {len(posiciones)} / {MAX_POSICIONES_PARALELO} ({activos_str})\n\n"
            f"🧠 *Última Decisión IA:*\n\"{resumen_decision}\"\n\n"
            f"🌐 *Dashboard:* https://diegosp14031979.github.io/agente-cripto/"
        )
        enviar_whatsapp(msg_wa)
        historial["ultimo_envio_whatsapp"] = fecha_iso

    guardar_json(FILE_HISTORIAL, historial)
    return texto_correo

def enviar_correo(texto):
    if not EMAIL_ORIGEN or not EMAIL_PASSWORD or not EMAIL_DESTINO:
        return
    try:
        msg = MIMEText(texto, 'plain', 'utf-8')
        msg['Subject'] = "⚡ Alerta Trading Validado - Motor Macro BTC & WhatsApp Activos"
        msg['From'] = EMAIL_ORIGEN
        msg['To'] = EMAIL_DESTINO

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())
    except Exception as e:
        print("Error enviando correo:", e)

if __name__ == "__main__":
    posiciones = cargar_json(FILE_POSICIONES, [])
    candidatas = cargar_json(FILE_CANDIDATAS, [])
    historial = cargar_json(FILE_HISTORIAL, {"capital_inicial": 3300.0, "registro_saldo": []})
    
    saldo_actual = historial.get("registro_saldo", [{}])[-1].get("saldo", 3300.0) if historial.get("registro_saldo") else 3300.0
    
    macro_btc = evaluar_regimen_macro_btc()
    matriz_fina = construir_embudo_mercado()
    
    if matriz_fina:
        respuesta_raw = analizar_oportunidades_y_cartera(matriz_fina, posiciones, candidatas, saldo_actual, macro_btc)
        informe_limpio = actualizar_historial_y_cartera(respuesta_raw)
        enviar_correo(informe_limpio)
    else:
        print("No se encontraron activos válidos.")
