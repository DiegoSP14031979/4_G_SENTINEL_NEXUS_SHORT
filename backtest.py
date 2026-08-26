import requests
import json
import pandas as pd
import numpy as np

# ==========================================
# PARÁMETROS DE SIMULACIÓN Y CAPITAL
# ==========================================
CAPITAL_INICIAL = 3300.0
SLOTS_MAXIMOS = 4
MONTO_SLOT = CAPITAL_INICIAL / SLOTS_MAXIMOS
TICKERS = ["bitcoin", "ethereum", "solana", "ripple", "dogecoin"]

print("🔄 Descargando datos de alta densidad para Optimización de CORE...")

def obtener_datos_hora(coin_id):
    # Obtiene datos de los últimos 90 días en resolución horaria (2,160 registros por activo)
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days=90"
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            precios = res.json()["prices"]
            df = pd.DataFrame(precios, columns=["timestamp", "price"])
            df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
            return df
    except Exception as e:
        print(f"⚠️ Error descargando {coin_id}: {e}")
    return pd.DataFrame()

datos = {}
for t in TICKERS:
    df = obtener_datos_hora(t)
    if not df.empty:
        datos[t] = df

print("⚡ Simulado backtest adaptativo (Malla de 2,000+ comprobaciones)...")

# ==========================================
# MOTOR ADAPTATIVO (ATR + FILTRO EMA 200)
# ==========================================
capital = CAPITAL_INICIAL
historial_trades = []
posiciones = {}

min_len = min([len(df) for df in datos.values()])

for i in range(200, min_len):  # Se reservan 200 periodos para la EMA 200
    fecha = datos["bitcoin"].iloc[i]["date"].strftime("%Y-%m-%d %H:%M")
    tickers_cerrar = []

    # 1. GESTIÓN DE POSICIONES ABIERTAS (SL/TP ADAPTATIVOS)
    for ticker, pos in posiciones.items():
        precio_actual = datos[ticker].iloc[i]["price"]
        
        # Stop Loss saltó
        if precio_actual <= pos["sl"]:
            pnl = -MONTO_SLOT * pos["sl_pct"]
            capital += pnl
            historial_trades.append({"fecha": fecha, "ticker": ticker, "tipo": "SL", "pnl": pnl, "capital": capital})
            tickers_cerrar.append(ticker)
        # Take Profit saltó
        elif precio_actual >= pos["tp"]:
            pnl = MONTO_SLOT * pos["tp_pct"]
            capital += pnl
            historial_trades.append({"fecha": fecha, "ticker": ticker, "tipo": "TP", "pnl": pnl, "capital": capital})
            tickers_cerrar.append(ticker)

    for t in tickers_cerrar:
        del posiciones[t]

    # 2. EVALUACIÓN ADAPTATIVA DE NUEVAS ENTRADAS
    if len(posiciones) < SLOTS_MAXIMOS:
        for ticker in TICKERS:
            if ticker in posiciones:
                continue

            precios_historicos = datos[ticker]["price"].iloc[i-200:i].values
            precio_actual = datos[ticker].iloc[i]["price"]
            
            # Indicadores Adaptativos
            ema_200 = np.mean(precios_historicos[-200:])
            retornos = np.abs(np.diff(precios_historicos[-14:]) / precios_historicos[-15:-1])
            atr_pct = float(np.mean(retornos))
            
            # Dinámica ATR: SL adaptado a la volatilidad real
            sl_pct = max(0.025, min(0.05, atr_pct * 1.5))
            
            # Régimen de Mercado: Solo comprar en Bull o rebote confirmado sobre EMA 200
            regimen_bull = precio_actual > ema_200
            impulso = (precio_actual - precios_historicos[-2]) / precios_historicos[-2]

            if regimen_bull and impulso > 0.008:  # Impulso > +0.8% en tendencia alcista
                tp_pct = sl_pct * 2.2  # Ratio R/R adaptativo 1:2.2
                
                posiciones[ticker] = {
                    "precio_entrada": precio_actual,
                    "sl": precio_actual * (1 - sl_pct),
                    "tp": precio_actual * (1 + tp_pct),
                    "sl_pct": sl_pct,
                    "tp_pct": tp_pct
                }
                break

# ==========================================
# INFORME FINAL DE FIABILIDAD DEL CORE
# ==========================================
df_t = pd.DataFrame(historial_trades)
if not df_t.empty:
    ganadores = df_t[df_t["pnl"] > 0]
    perdedores = df_t[df_t["pnl"] < 0]

    win_rate = (len(ganadores) / len(df_t)) * 100
    profit_factor = abs(ganadores["pnl"].sum() / perdedores["pnl"].sum()) if len(perdedores) > 0 else 0
    pnl_total = capital - CAPITAL_INICIAL

    print("\n========================================")
    print("🎯 INFORME DE FIABILIDAD DE CORE ADAPTATIVO")
    print("========================================")
    print(f"Total Trades Evaluados: {len(df_t)}")
    print(f"Capital Inicial: ${CAPITAL_INICIAL:.2f} USD")
    print(f"Capital Final: ${capital:.2f} USD")
    print(f"Profit / Loss Total: ${pnl_total:.2f} USD ({(pnl_total/CAPITAL_INICIAL)*100:.2f}%)")
    print(f"Win Rate (Tasa de Acierto): {win_rate:.2f}%")
    print(f"Profit Factor: {profit_factor:.2f}")
    print("========================================\n")
else:
    print("⚠️ No se generaron trades con los filtros actuales.")
