#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
G-SENTINEL PATA 4 // NEXUS SHORT ENGINE (V5.0 VPS)
==============================================================================
Fase 2: Motor Optimizado para VPS con Circuit Breaker, Cooldown, Control de
Correlación, Interés Compuesto Dinámico, Trailing Stop ATR y Ejecución Maker.
==============================================================================
"""

import os
import sys
import time
import datetime
import math
import logging
import requests
import pandas as pd
import numpy as np

# ------------------------------------------------------------------------------
# CONFIGURACIÓN Y PARÁMETROS GLOBALES
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("nexus_short.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Parámetros Operativos
INITIAL_CAPITAL = 3300.0         # Base de capital
RISK_FACTOR_BASE = 0.015         # 1.5% R por slot
MAX_SLOTS = 4                    # Máximo de slots simultáneos
COOLDOWN_HOURS = 6               # Horas de bloqueo tras saltar un SL
MAX_CORRELATED_SLOTS = 2         # Máximo de altcoins correlacionadas (>0.85)

# Lista de Activos Supervisados
ASSETS = ["BTC", "ETH", "SOL", "XRP"]

# Estado en memoria / almacenamiento local para Cooldowns
cooldown_tracker = {asset: None for asset in ASSETS}


# ------------------------------------------------------------------------------
# 1. MÓDULO DE LECTURA MACRO & CIRCUIT BREAKER
# ------------------------------------------------------------------------------
def get_macro_regime():
    """
    Evalúa la tendencia de largo plazo de Bitcoin.
    Retorna: 'BULLISH_TREND_CRYPTO', 'STRONG_BEARISH_CRYPTO' o 'NEUTRAL'
    """
    try:
        # Consulta de datos históricos diarios de BTC (ej. vía API pública / Coinbase)
        # En producción sustituir por la llamada directa a Coinbase Client L3
        url = "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        df = pd.DataFrame(data, columns=['time', 'low', 'high', 'open', 'close', 'volume'])
        df = df.sort_values('time').reset_index(drop=True)
        
        # Indicadores Estructurales (Medias Móviles 50d y 200d)
        df['sma_50'] = df['close'].rolling(window=50).mean()
        df['sma_200'] = df['close'].rolling(window=200).mean()
        
        last_close = df['close'].iloc[-1]
        sma_50 = df['sma_50'].iloc[-1]
        sma_200 = df['sma_200'].iloc[-1]
        
        if last_close > sma_50 and sma_50 > sma_200:
            return "BULLISH_TREND_CRYPTO"
        elif last_close < sma_50 and sma_50 < sma_200:
            return "STRONG_BEARISH_CRYPTO"
        else:
            return "NEUTRAL_CRYPTO"
            
    except Exception as e:
        logging.error(f"Error consultando régimen macro: {e}")
        return "NEUTRAL_CRYPTO"


def is_circuit_breaker_active(macro_regime):
    """
    CIRCUIT BREAKER: Si el mercado está en Bull Run Macro, CONGELA el 100%
    de las entradas SHORT para evitar pérdidas por contra-tendencia.
    """
    if macro_regime == "BULLISH_TREND_CRYPTO":
        logging.warning("⚠️ MACRO CIRCUIT BREAKER ACTIVADO: Mercado en BULL RUN. Entradas SHORT suspendidas.")
        return True
    return False


# ------------------------------------------------------------------------------
# 2. GESTIÓN DE COOLDOWN Y CORRELACIÓN SINCRÓNICA
# ------------------------------------------------------------------------------
def is_in_cooldown(asset):
    """
    Verifica si un activo está bajo el temporizador de enfriamiento tras un SL.
    """
    last_sl_time = cooldown_tracker.get(asset)
    if last_sl_time is None:
        return False
        
    elapsed_hours = (datetime.datetime.utcnow() - last_sl_time).total_seconds() / 3600.0
    if elapsed_hours < COOLDOWN_HOURS:
        logging.info(f"⏳ {asset} en Cooldown ({COOLDOWN_HOURS - elapsed_hours:.1f}h restantes).")
        return True
    
    # Cooldown expirado
    cooldown_tracker[asset] = None
    return False


def register_stop_loss_event(asset):
    """
    Registra el momento del Stop Loss para activar el Cooldown.
    """
    cooldown_tracker[asset] = datetime.datetime.utcnow()
    logging.info(f"🛑 Stop Loss activado en {asset}. Cooldown de {COOLDOWN_HOURS}h iniciado.")


def check_correlation_limit(active_positions):
    """
    Evita sobre-exposición simultánea en altcoins altamente correlacionadas.
    """
    altcoins_active = [pos for pos in active_positions if pos in ["ETH", "SOL", "XRP"]]
    if len(altcoins_active) >= MAX_CORRELATED_SLOTS:
        logging.info("🛡️ Límite de correlación alcanzado para Altcoins. Entrada bloqueada.")
        return False
    return True


# ------------------------------------------------------------------------------
# 3. INTERÉS COMPUESTO DINÁMICO & POSITION SIZING
# ------------------------------------------------------------------------------
def calculate_dynamic_position_size(current_equity, current_price, atr_value):
    """
    Recalcula el tamaño del lote (1.5% R) basándose en la cartera viva.
    """
    risk_capital = current_equity * RISK_FACTOR_BASE
    stop_distance = atr_value * 1.5  # Distancia de Stop basada en volatilidad ATR
    
    if stop_distance == 0:
        return 0.0
        
    position_units = risk_capital / stop_distance
    return position_units


# ------------------------------------------------------------------------------
# 4. MOTOR DE EJECUCIÓN MAKER (POST-ONLY ORDERS)
# ------------------------------------------------------------------------------
def execute_maker_short_entry(asset, size, target_price):
    """
    Lanza orden LÍMITE (Post-Only) en Coinbase para pagar 0.25% de fee en lugar de 0.50%
    y evitar pagar el Spread de Mercado.
    """
    logging.info(f"🚀 Lanzando orden MAKER (Post-Only) SHORT en {asset} | Tamaño: {size:.4f} | Precio Límite: ${target_price:.2f}")
    
    # Estructura de la payload para API v3 de Coinbase Advanced Trade
    order_payload = {
        "client_order_id": f"nexus_short_{asset}_{int(time.time())}",
        "product_id": f"{asset}-USD",
        "side": "SELL",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": str(round(size, 4)),
                "limit_price": str(round(target_price, 2)),
                "post_only": True  # Fuerza ejecución como MAKER
            }
        }
    }
    
    # Aquí va la firma HMAC y llamada HTTP POST a Coinbase API
    # return coinbase_client.post('/orders', json=order_payload)
    return True


# ------------------------------------------------------------------------------
# 5. BUCLE PRINCIPAL (MAIN LOOP)
# ------------------------------------------------------------------------------
def run_nexus_engine():
    logging.info("=" * 70)
    logging.info("INICIANDO G-SENTINEL PATA 4 // NEXUS SHORT ENGINE V5.0 (VPS)")
    logging.info("=" * 70)
    
    # Capital simulado/real devuelto por el API de Coinbase
    current_portfolio_equity = 3047.60  # Valor real tras trade 103
    
    # 1. Analizar Régimen Macro
    macro_regime = get_macro_regime()
    logging.info(f"📊 Régimen Macro Actual: {macro_regime}")
    
    # 2. Verificar Circuit Breaker
    if is_circuit_breaker_active(macro_regime):
        logging.info("💤 Motor en espera de liquidez. No se buscarán entradas SHORT.")
        return
        
    # 3. Monitoreo de activos y señales
    active_positions = [] # Consultar API para ver posiciones abiertas actuales
    
    for asset in ASSETS:
        if asset in active_positions:
            # Lógica de gestión de Trailing Stop por ATR en posiciones abiertas
            continue
            
        if is_in_cooldown(asset):
            continue
            
        if not check_correlation_limit(active_positions):
            break
            
        # Evaluar disparador de entrada (EXHAUSTION_REVERSAL)
        # Si hay señal:
        # atr_val = get_atr(asset)
        # target_p = get_orderbook_ask(asset)
        # size = calculate_dynamic_position_size(current_portfolio_equity, target_p, atr_val)
        # execute_maker_short_entry(asset, size, target_p)

if __name__ == "__main__":
    run_nexus_engine()
