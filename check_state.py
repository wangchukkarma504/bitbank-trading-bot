import json

with open("forex_state.json", "r", encoding="utf-8") as f:
    st = json.load(f)

print(f"Equity JPY: ¥{st.get('equity_jpy', 0):,.1f}")
print(f"Equity USD: ${st.get('equity', 0):.2f}")
print(f"Positions : {len(st.get('positions', {}))}")
print(f"Closed    : {len(st.get('closed_trades', []))}")
