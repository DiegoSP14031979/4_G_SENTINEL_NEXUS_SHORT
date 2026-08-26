import requests
import json
import pandas as pd
import numpy as np
from datetime import datetime

# ==========================================
# PARÁMETROS DEL CORE PARA EL BACKTEST
# ==========================================
CAPITAL_INICIAL = 3300.0
SLOTS = 4
MONTO_SLOT = CAPITAL_INICIAL / SLOTS  # $825 USD
RIESGO_SL_PCT = 0.03                 # -3.0% Stop Loss
OBJETIVO_TP_PCT = 0.06               # +6.0% Take Profit
TICKERS = ["bitcoin", "ethereum", "solana", "ripple"]

print("🔄 Descargando datos históricos de CoinGecko...")

def obtener_datos_historicos(coin_id):
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=365&interval=daily"
    res = requests.get(url)
    if res.status_code == 200:
        precios = res.json()["prices"]
        df = pd.DataFrame(precios, columns=["timestamp", "price"])
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    return pd.DataFrame()

# Cargar datos de todos los activos
datos = {}
for ticker in TICKERS:
    df = obtener_datos_historicos(ticker)
    if not df.empty:
        datos[ticker] = df

print("⚡ Ejecutando simulación de 100 trades...")

# ==========================================
# MOTOR DE SIMULACIÓN
# ==========================================
capital = CAPITAL_INICIAL
historial_trades = []
posiciones_activas = {}

# Recorrer velas históricas día a día
min_len = min([len(df) for df in datos.values()])

for i in range(1, min_len):
    fecha = datos["bitcoin"].iloc[i]["date"].strftime("%Y-%m-%d")
    
    # 1. Comprobar posiciones abiertas
    tickers_a_cerrar = []
    for ticker, pos in posiciones_activas.items():
        precio_actual = datos[ticker].iloc[i]["price"]
        precio_entrada = pos["precio_entrada"]
        
        # Evaluar Stop Loss
        if precio_actual <= pos["sl"]:
            resultado = -MONTO_SLOT * RIESGO_SL_PCT
            capital += resultado
            historial_trades.append({
                "fecha": fecha, "ticker": ticker, "tipo": "STOP_LOSS",
                "pnl": resultado, "capital": capital
            })
            tickers_a_cerrar.append(ticker)
            
        # Evaluar Take Profit
        elif precio_actual >= pos["tp"]:
            resultado = MONTO_SLOT * OBJETIVO_TP_PCT
            capital += resultado
            historial_trades.append({
                "fecha": fecha, "ticker": ticker, "tipo": "TAKE_PROFIT",
                "pnl": resultado, "capital": capital
            })
            tickers_a_cerrar.append(ticker)

    for t in tickers_a_cerrar:
        del posiciones_activas[t]

    # 2. Buscar nuevas entradas si hay slots libres
    for ticker in TICKERS:
        if len(posiciones_activas) < SLOTS and ticker not in posiciones_activas:
            precio_hoy = datos[ticker].iloc[i]["price"]
            precio_ayer = datos[ticker].iloc[i-1]["price"]
            
            # Condición de entrada: Vela diaria verde (+1.5% momentum)
            if (precio_hoy - precio_ayer) / precio_ayer > 0.015:
                posiciones_activas[ticker] = {
                    "precio_entrada": precio_hoy,
                    "sl": precio_hoy * (1 - RIESGO_SL_PCT),
                    "tp": precio_hoy * (1 + OBJETIVO_TP_PCT)
                }

    if len(historial_trades) >= 100:
        break

# ==========================================
# INFORME RESULTADOS Y CALIBRACIÓN
# ==========================================
df_trades = pd.DataFrame(historial_trades)
ganadores = df_trades[df_trades["pnl"] > 0]
perdedores = df_trades[df_trades["pnl"] < 0]

win_rate = (len(ganadores) / len(df_trades)) * 100 if len(df_trades) > 0 else 0
profit_factor = abs(ganadores["pnl"].sum() / perdedores["pnl"].sum()) if len(perdedores) > 0 else 0

print("\n" + "="*40)
print("📊 RESULTADOS DEL BACKTESTING (100 TRADES)")
print("="*40)
print(f"Total Trades Evaluados: {len(df_trades)}")
print(f"Capital Final: ${capital:.2f} USD")
print(f"Profit / Loss Total: ${capital - CAPITAL_INICIAL:.2f} USD")
print(f"Win Rate: {win_rate:.2f}%")
print(f"Profit Factor: {profit_factor:.2f}")
print("="*40)
