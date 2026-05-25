import sys
sys.stdout.reconfigure(encoding='utf-8')
from historical_data import TWSEHistoricalFetcher
import datetime

_TZ = datetime.timezone(datetime.timedelta(hours=8))
fetcher = TWSEHistoricalFetcher()

for sym in ['3545', '2545', '2393', '2352', '6962', '6770']:
    try:
        bars = fetcher.fetch_bars(sym, '2026-05-14', '2026-05-21')
        print(f'\n{sym}:')
        for b in bars:
            dt = datetime.datetime.fromtimestamp(b.ts_ms/1000, tz=_TZ).strftime('%Y-%m-%d')
            print(f'  {dt}: open={b.open} high={b.high} low={b.low} close={b.close}')
    except Exception as e:
        print(f'{sym}: error {e}')
