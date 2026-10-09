from pathlib import Path
import pandas as pd, joblib
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest

ROOT=Path(__file__).resolve().parents[1]
inp=ROOT/'data/processed/mobility_features.csv'
out=ROOT/'data/processed/mobility_with_anomaly.csv'
model_path=ROOT/'ml/models/mobility_isolation_forest.joblib'
model_path.parent.mkdir(parents=True,exist_ok=True)

features=['speed_kmh','acceleration_kmh_s','direction_change_deg','inactivity_seconds','distance_m']
df=pd.read_csv(inp).dropna(subset=features).copy()
model=Pipeline([('scaler',StandardScaler()),('isolation_forest',
    IsolationForest(n_estimators=300,contamination='auto',random_state=42,n_jobs=-1))])
model.fit(df[features])
raw=model.decision_function(df[features])
df['movement_anomaly']=1-(raw-raw.min())/(raw.max()-raw.min()+1e-9)
joblib.dump({'model':model,'features':features,'raw_min':float(raw.min()),'raw_max':float(raw.max())},model_path)
df.to_csv(out,index=False)
print('Saved',model_path)
print('Saved',out)
