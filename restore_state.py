import json

with open("forex_state.json", "r", encoding="utf-8") as f:
    st = json.load(f)

st["equity"] = 57.35775169521909
st["cash"] = 57.35775169521909
st["equity_jpy"] = 9050.94
st["cash_jpy"] = 9050.94
st["positions"] = {}
st["closed_trades"] = st["closed_trades"][:9]

with open("forex_state.json", "w", encoding="utf-8") as f:
    json.dump(st, f, indent=2)

print(f"Restored clean state: ¥{st['equity_jpy']:,.1f} (${st['equity']:.2f})")
