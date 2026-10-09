from pathlib import Path
import numpy as np, pandas as pd

ROOT=Path(__file__).resolve().parents[1]
inp=ROOT/'data/processed/geolife_points.csv'
out=ROOT/'data/processed/mobility_features.csv'
R=6371000.0

def hav(lat1,lon1,lat2,lon2):
    lat1,lon1,lat2,lon2=map(np.radians,[lat1,lon1,lat2,lon2])
    a=np.sin((lat2-lat1)/2)**2+np.cos(lat1)*np.cos(lat2)*np.sin((lon2-lon1)/2)**2
    return 2*R*np.arcsin(np.sqrt(a))

def bear(lat1,lon1,lat2,lon2):
    a,b=np.radians(lat1),np.radians(lat2)
    d=np.radians(lon2-lon1)
    y=np.sin(d)*np.cos(b)
    x=np.cos(a)*np.sin(b)-np.sin(a)*np.cos(b)*np.cos(d)
    return (np.degrees(np.arctan2(y,x))+360)%360

df=pd.read_csv(inp,parse_dates=['timestamp']).sort_values(['user_id','trajectory_id','timestamp'])
g=df.groupby(['user_id','trajectory_id'],group_keys=False)
df['prev_lat']=g.latitude.shift(); df['prev_lon']=g.longitude.shift(); df['prev_time']=g.timestamp.shift()
df['distance_m']=hav(df.prev_lat,df.prev_lon,df.latitude,df.longitude)
df['dt_seconds']=(df.timestamp-df.prev_time).dt.total_seconds()
df['speed_kmh']=df.distance_m/df.dt_seconds*3.6
df['bearing']=bear(df.prev_lat,df.prev_lon,df.latitude,df.longitude)
df['prev_bearing']=g.bearing.shift()
df['direction_change_deg']=((df.bearing-df.prev_bearing+180)%360-180).abs()
df['acceleration_kmh_s']=(g.speed_kmh.diff()/df.dt_seconds).replace([np.inf,-np.inf],np.nan).abs()
df['inactivity_seconds']=np.where(df.speed_kmh.fillna(0)<1,df.dt_seconds.clip(lower=0),0)
df['hour']=df.timestamp.dt.hour
df['night_flag']=df.hour.between(22,23)|df.hour.between(0,5)
df=df[(df.speed_kmh.isna())|(df.speed_kmh<=180)]
cols=['user_id','trajectory_id','timestamp','latitude','longitude','altitude','distance_m','dt_seconds',
      'speed_kmh','acceleration_kmh_s','bearing','direction_change_deg','inactivity_seconds','hour','night_flag']
df[cols].to_csv(out,index=False)
print(f'Wrote {len(df):,} rows to {out}')
