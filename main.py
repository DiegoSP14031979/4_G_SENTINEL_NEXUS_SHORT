import os
import json
import requests
import numpy as np
from datetime import datetime

# ==========================================
# CONFIGURACIÓN DEL CORE Y CAPA ADAPTATIVA
# ==========================================
CAPITAL_INICIAL = 3300.0
SLOTS_MAXIMOS = 4
RIESGO_BASE_SL_PCT = 0.03  # 3% Base
TAKE_PROFIT_BASE_PCT = 0.08 # 8% Base en Bull Market
TICKERS_PRINCIPALES = ["BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX"]

POSICIONES_FILE = "posiciones.json"
HISTORIAL_FILE = "historial.json"

# ==========================================
# FUNCIONES AUXILIARES DE ARCHIVOS
# ==========================================
def cargar_json(filepath, default):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def guardar_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ==========================================
# INDICADORES ADAPTATIVOS: ATR Y REGIMEN (EMA)
# ==========================================
def obtener_precios_historicos(ticker, dias=30):
    mapa_coingecko = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "XRP": "ripple", "DOGE": "dogecoin", "AVAX": "avalanche-2"
    }
    coin_id = mapa_coingecko.get(ticker, ticker.lower())
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={dias}&interval=daily"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            precios = [p[1] for p in res.json()["prices"]]
            return precios
    except Exception as e:
        print(f"⚠️ Error obteniendo histórico para {ticker}: {e}")
    return []

def calcular_atr_y_regimen(ticker):
    precios = obtener_precios_historicos(ticker, dias=50)
    if len(precios) < 20:
        return RIESGO_BASE_SL_PCT, TAKE_PROFIT_BASE_PCT, "NEUTRAL"
    
    # 1. Cálculo de Volatilidad Relativa (ATR Simplificado)
    retornos = np.abs(np.diff(precios) / precios[:-1])
    volatilidad_atr = float(np.mean(retornos[-14:]))
    
    # Adaptar Stop Loss según la volatilidad del activo (1.5x Volatilidad diaria)
    sl_adaptativo = max(0.025, min(0.06, volatilidad_atr * 1.8))
    
    # 2. Detector de Régimen por Media Móvil (EMA 20)
    ema_20 = float(np.mean(precios[-20:]))
    precio_actual = precios[-1]
    
    if precio_actual > ema_20 * 1.02:
        regimen = "BULL"
        tp_adaptativo = sl_adaptativo * 2.5 # Ratio R/R dinámico 1:2.5
    elif precio_actual < ema_20 * 0.98:
        regimen = "BEAR"
        tp_adaptativo = sl_adaptativo * 1.2 # Cierres rápidos en caídas
    else:
        regimen = "CHOP"
        tp_adaptativo = sl_adaptativo * 1.5 # Mercado lateral
        
    return float(sl_adaptativo), float(tp_adaptativo), regimen

# ==========================================
# MOTOR PRINCIPAL DE EJECUCIÓN
# ==========================================
def ejecutar_agente():
    timestamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
    posiciones = cargar_json(POSICIONES_FILE, {})
    historial = cargar_json(HISTORIAL_FILE, [])

    # Obtener el último capital registrado
    capital_actual = historial[-1].get("capital", CAPITAL_INICIAL) if historial else CAPITAL_INICIAL
    
    print(f"🤖 Ejecutando Agente Cripto Adaptativo - {timestamp}")
    print(f"💰 Capital Actual: ${capital_actual:.2f} USD | Posiciones Abiertas: {len(posiciones)}/{SLOTS_MAXIMOS}")

    # 1. ACTUALIZAR Y REVISAR POSICIONES EXISTENTES
    tickers_a_eliminar = []
    accion_tomada = "MANTENER"
    razonamiento = f"Cartera con {len(posiciones)}/{SLOTS_MAXIMOS} slots ocupados. Evaluando condiciones adaptativas."

    for ticker, pos in posiciones.items():
        precios = obtener_precios_historicos(ticker, dias=2)
        if not precios:
            continue
        
        precio_actual = precios[-1]
        precio_entrada = pos["precio_entrada"]
        pos["precio_actual"] = precio_actual # Para el Dashboard
        
        pnl_pct = (precio_actual - precio_entrada) / precio_entrada
        
        # Evaluar Stop Loss Adaptativo
        if precio_actual <= pos["stop_loss"]:
            pda_usd = pos["monto_usd"] * (precio_actual - precio_entrada) / precio_entrada
            capital_actual += pda_usd
            accion_tomada = "EJECUTAR_STOP_LOSS"
            razonamiento = f"VENTA EN SL ({ticker}): Ejecutada a ${precio_actual:.2f} tras saltar el nivel de guardián adaptativo."
            tickers_a_eliminar.append(ticker)
            
        # Evaluar Take Profit Adaptativo
        elif precio_actual >= pos["take_profit"]:
            ganancia_usd = pos["monto_usd"] * (precio_actual - precio_entrada) / precio_entrada
            capital_actual += ganancia_usd
            accion_tomada = "EJECUTAR_TAKE_PROFIT"
            razonamiento = f"VENTA EN TP ({ticker}): Ganancia asegurada a ${precio_actual:.2f}."
            tickers_a_eliminar.append(ticker)

    for t in tickers_a_eliminar:
        del posiciones[t]

    # 2. EVALUAR NUEVAS ENTRADAS SI HAY SLOTS LIBRES
    if len(posiciones) < SLOTS_MAXIMOS:
        for ticker in TICKERS_PRINCIPALES:
            if ticker in posiciones:
                continue
                
            sl_ad, tp_ad, regimen = calcular_atr_y_regimen(ticker)
            precios = obtener_precios_historicos(ticker, dias=3)
            if len(precios) < 2:
                continue
                
            precio_hoy = precios[-1]
            precio_ayer = precios[-2]
            impulso = (precio_hoy - precio_ayer) / precio_ayer

            # Solo autorizar compra en régimen alcista o impulso limpio en CHOP
            if (regimen == "BULL" and impulso > 0.01) or (regimen == "CHOP" and impulso > 0.025):
                monto_slot = capital_actual / SLOTS_MAXIMOS
                
                posiciones[ticker] = {
                    "precio_entrada": round(precio_hoy, 4),
                    "precio_actual": round(precio_hoy, 4),
                    "monto_usd": round(monto_slot, 2),
                    "stop_loss": round(precio_hoy * (1 - sl_ad), 4),
                    "take_profit": round(precio_hoy * (1 + tp_ad), 4),
                    "estado_sl": f"Adaptativo ATR ({regimen})"
                }
                accion_tomada = f"COMPRA_{ticker}"
                razonamiento = f"ENTRADA ADAPTATIVA EN {ticker}: Confirmado régimen {regimen}. SL ajustado por ATR a -{sl_ad*100:.1f}% y TP a +{tp_ad*100:.1f}%."
                break # Una entrada por ciclo

    # 3. GUARDAR ESTADOS E HISTORIAL
    guardar_json(POSICIONES_FILE, posiciones)
    
    log_entry = {
        "timestamp": timestamp,
        "capital": round(capital_actual, 2),
        "accion": accion_tomada,
        "razonamiento": razonamiento
    }
    historial.append(log_entry)
    guardar_json(HISTORIAL_FILE, historial)
    
    print("✅ Ciclo de ejecución adaptativa completado con éxito.")

if __name__ == "__main__":
    ejecutar_agente()
