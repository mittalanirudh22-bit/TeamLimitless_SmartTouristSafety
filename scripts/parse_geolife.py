from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
raw=ROOT/'data/raw/geolife'
out=ROOT/'data/processed/geolife_points.csv'
rows=[]

for plt in raw.rglob('*.plt'):
    try: df=pd.read_csv(plt,skiprows=6,header=None)
    except Exception as e:
        print('Skipping',plt,e); continue
    if df.shape[1]<7: continue
    df=df.iloc[:,:7]
    df.columns=['latitude','longitude','unused','altitude','days','date','time']
    df['user_id']=plt.parent.parent.name
    df['trajectory_id']=plt.stem
    rows.append(df[['user_id','trajectory_id','date','time','latitude','longitude','altitude']])

if not rows: raise SystemExit('No .plt files found under data/raw/geolife/')
outdf=pd.concat(rows,ignore_index=True)
outdf['timestamp']=pd.to_datetime(outdf['date'].astype(str)+' '+outdf['time'].astype(str),errors='coerce')
outdf=outdf.dropna(subset=['timestamp','latitude','longitude']).drop(columns=['date','time'])
outdf.to_csv(out,index=False)
print(f'Wrote {len(outdf):,} points to {out}')
