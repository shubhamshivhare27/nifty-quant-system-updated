"""
generate_upstox_symbols.py (v2 — fixed)
"""
import gzip, io, requests, pandas as pd

UPSTOX_NSE_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.csv.gz"

print("Downloading NSE instruments from Upstox...")
resp = requests.get(UPSTOX_NSE_URL, timeout=60)
resp.raise_for_status()

with gzip.open(io.BytesIO(resp.content)) as f:
    df = pd.read_csv(f)

print(f"Downloaded {len(df)} total instruments.")
print(f"Unique instrument_type values: {df['instrument_type'].unique()[:20]}")
print(f"Unique exchange values: {df['exchange'].unique()[:10]}")

# Filter by instrument_key starting with NSE_EQ| (most reliable method)
df_eq = df[df["instrument_key"].str.startswith("NSE_EQ|")].copy()
print(f"NSE equity stocks found: {len(df_eq)}")

df_out = pd.DataFrame({
    "ticker":         df_eq["tradingsymbol"].str.strip() + ".NS",
    "instrument_key": df_eq["instrument_key"].str.strip(),
})
df_out = df_out.dropna()
df_out = df_out[df_out["ticker"] != ".NS"]
df_out = df_out.sort_values("ticker").reset_index(drop=True)

output_path = "upstox_symbols.csv"
df_out.to_csv(output_path, index=False)

print(f"\n✅ Done! Saved {len(df_out)} stocks to: {output_path}")
print("\nSample rows:")
print(df_out.head(10).to_string(index=False))
print(f"\nNext step: Upload '{output_path}' to the data/ folder in your GitHub repo.")
