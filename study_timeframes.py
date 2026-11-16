import python_bitbankcc
import pandas as pd
import numpy as np
import datetime

pub = python_bitbankcc.public()

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def analyze_candles(pair, candle_type):
    today = datetime.datetime.now().strftime('%Y')
    try:
        # candle types: '1hour', '4hour', '1day'
        raw = pub.get_candle(pair, candle_type, today)
        candles = raw.get('candlestick', [])[0].get('ohlcv', [])
        df = pd.DataFrame(candles, columns=['open', 'high', 'low', 'close', 'volume', 'timestamp'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        # Calculate Indicators
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema90'] = df['close'].ewm(span=90, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['rsi'] = calculate_rsi(df['close'], 14)
        
        # Wick analysis on last 5 candles
        last_row = df.iloc[-1]
        prev_row = df.iloc[-2]
        
        upper_wick = last_row['high'] - max(last_row['open'], last_row['close'])
        lower_wick = min(last_row['open'], last_row['close']) - last_row['low']
        body = abs(last_row['close'] - last_row['open'])
        
        return {
            'pair': pair,
            'timeframe': candle_type,
            'close': last_row['close'],
            'ema20': last_row['ema20'],
            'ema50': last_row['ema50'],
            'ema90': last_row['ema90'],
            'ema200': last_row['ema200'],
            'rsi': last_row['rsi'],
            'upper_wick': upper_wick,
            'lower_wick': lower_wick,
            'body': body,
            'trend_ema200': 'BEARISH (Below EMA200)' if last_row['close'] < last_row['ema200'] else 'BULLISH (Above EMA200)',
            'trend_ema50': 'BEARISH (Below EMA50)' if last_row['close'] < last_row['ema50'] else 'BULLISH (Above EMA50)'
        }
    except Exception as e:
        return {'error': str(e), 'pair': pair, 'timeframe': candle_type}

pairs = ['btc_jpy', 'sol_jpy', 'eth_jpy', 'doge_jpy']
timeframes = ['1hour', '4hour']

print("=== TIMEFRAME STUDY ===")
for p in pairs:
    for tf in timeframes:
        res = analyze_candles(p, tf)
        if 'error' in res:
            print(f"Error {p} {tf}: {res['error']}")
        else:
            print(f"[{res['pair'].upper()} {res['timeframe']}] Close: {res['close']} | RSI: {res['rsi']:.1f} | EMA50: {res['ema50']:.1f} | EMA200: {res['ema200']:.1f} | 50-Trend: {res['trend_ema50']} | 200-Trend: {res['trend_ema200']} | UpperWick: {res['upper_wick']:.2f} | LowerWick: {res['lower_wick']:.2f}")
