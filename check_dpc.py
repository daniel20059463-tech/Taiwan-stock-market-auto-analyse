import sys, json
sys.stdout.reconfigure(encoding='utf-8')

with open(r'E:\claude code test\data\daily_price_cache.json', 'r', encoding='utf-8') as f:
    dpc = json.load(f)

# 檢查幾個股票的 volume 單位
for sym in ['2330', '6488', '2303', '2409']:
    if sym not in dpc:
        print(f'{sym}: 不在 daily_price_cache')
        continue
    bars = sorted(dpc[sym].values(), key=lambda b: b.get('date',''))
    last = bars[-1]
    vals = [b.get('close',0) * b.get('volume',0) for b in bars[-20:] if b.get('volume',0) > 0]
    avg = sum(vals)/len(vals) if vals else 0
    vals1000 = [v * 1000 for v in vals]
    avg1000 = sum(vals1000)/len(vals1000) if vals1000 else 0
    print(f'{sym}: last close={last.get("close")}, vol={last.get("volume")}, avg_val={avg:,.0f}, avg_val×1000={avg1000:,.0f}')
