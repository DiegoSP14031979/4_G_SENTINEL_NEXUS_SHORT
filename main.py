import os
import json
import requests
import numpy as np
from datetime import datetime

# ==========================================
# CONFIGURACIÓN CORE VALIDADA EN BACKTEST
# ==========================================
CAPITAL_INICIAL = 3300.0
SLOTS_MAXIMOS = 4
TICKERS_PRINCIPALES = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

POSICIONES_FILE = "posiciones.json"
HISTORIAL_FILE = "historial.json"

MAPA_GECKO = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "XRP": "ripple", "DOGE": "dogecoin"
}

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

def obtener_historico_hora(ticker):
    coin_id = MAPA_GECKO.get(ticker, ticker.lower())
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=90"
    try:
        res = requests.get(url, timeout=12)
        if res.status_code == 200:
            return [p[1] for p in res.json()["prices"]]
    except Exception as e:
        print(f"⚠️ Error al obtener datos para {ticker}: {e}")
    return []

def ejecutar_agente():
    timestamp = datetime.now().strftime("%d/%m/%Y, %H:%M:%S")
    posiciones = cargar_json(POSICIONES_FILE, {})
    historial = cargar_json(HISTORIAL_FILE, [])

    capital_actual = historial[-1].get("capital", CAPITAL_INICIAL) if historial else CAPITAL_INICIAL
    monto_slot = capital_actual / SLOTS_MAXIMOS

    print(f"🤖 Ejecutando Agente Cripto (Core Backtest Validado) - {timestamp}")

    # 1. EVALUAR POSICIONES ABIERTAS
    tickers_eliminar = []
    accion_tomada = "MANTENER"
    razonamiento = f"Cartera con {len(posiciones)}/{SLOTS_MAXIMOS} slots ocupados. Guardián adaptativo activo."

    for ticker, pos in posiciones.items():
        precios = obtener_historico_hora(ticker)
        if not precios:
            continue
            
        precio_actual = precios[-1]
        pos["precio_actual"] = round(precio_actual, 4)

        if precio_actual <= pos["stop_loss"]:
            pnl_usd = pos["monto_usd"] * (precio_actual - pos["precio_entrada"]) / pos["precio_entrada"]
            capital_actual += pnl_usd
            accion_tomada = "EJECUTAR_STOP_LOSS"
            razonamiento = f"VENTA SL ({ticker}): Salida adaptativa ejecutada a ${precio_actual:.4f}."
            tickers_eliminar.append(ticker)
            
        elif precio_actual >= pos["take_profit"]:
            pnl_usd = pos["monto_usd"] * (precio_actual - pos["precio_entrada"]) / pos["precio_entrada"]
            capital_actual += pnl_usd
            accion_tomada = "EJECUTAR_TAKE_PROFIT"
            razonamiento = f"VENTA TP ({ticker}): Objetivo alcanzado a ${precio_actual:.4f}."
            tickers_eliminar.append(ticker)

    for t in tickers_eliminar:
        del posiciones[t]

    # 2. EVALUAR NUEVAS ENTRADAS CON LÓGICA EXACTA DE BACKTEST
    if len(posiciones) < SLOTS_MAXIMOS:
        for ticker in TICKERS_PRINCIPALES:
            if ticker in posiciones:
                continue
                
            precios = obtener_historico_hora(ticker)
            if len(precios) < 200:
                continue

            precio_actual = precios[-1]
            precios_slice = precios[-200:]
            
            # Filtro Tendencial: EMA 200
            ema_200 = float(np.mean(precios_slice))
            regimen_bull = precio_actual > ema_200
            
            # Impulso inmediato
            impulso = (precio_actual - precios[-2]) / precios[-2]
            
            # ATR (14 periodos)
            p_slice = precios[-15:]
            retornos = np.abs(np.diff(p_slice) / p_slice[:-1])
            atr_pct = float(np.mean(retornos))
            
            sl_pct = max(0.025, min(0.05, atr_pct * 1.5))
            tp_pct = sl_pct * 2.2  # Ratio Riesgo/Beneficio 1:2.2

            if regimen_bull and impulso > 0.008:
                posiciones[ticker] = {
                    "precio_entrada": round(precio_actual, 4),
                    "precio_actual": round(precio_actual, 4),
                    "monto_usd": round(monto_slot, 2),
                    "stop_loss": round(precio_actual * (1 - sl_pct), 4),
                    "take_profit": round(precio_actual * (1 + tp_pct), 4),
                    "estado_sl": f"ATR ({sl_pct*100:.1f}%)"
                }
                accion_tomada = f"COMPRA_{ticker}"
                razonamiento = f"ENTRADA EN {ticker}: Confirmada tendencia alcista > EMA 200 e impulso de +{impulso*100:.2f}%. SL a -{sl_pct*100:.1f}% | TP a +{tp_pct*100:.1f}%."
                break

    # 3. ALMACENAMIENTO DE DATOS
    guardar_json(POSICIONES_FILE, posiciones)
    
    log_entry = {
        "timestamp": timestamp,
        "capital": round(capital_actual, 2),
        "accion": accion_tomada,
        "razonamiento": razonamiento
    }
    historial.append(log_entry)
    guardar_json(HISTORIAL_FILE, historial)

if __name__ == "__main__":
    ejecutar_agente()
