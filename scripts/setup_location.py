import argparse,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--city',required=True); p.add_argument('--state',required=True); p.add_argument('--country',default='India')
a=p.parse_args()
slug=re.sub(r'[^a-z0-9]+','-',a.city.lower()).strip('-')
d=ROOT/'locations'/slug; d.mkdir(parents=True,exist_ok=True)
(d/'config.yaml').write_text(f'''location:
  slug: {slug}
  name: {a.city}
  state: {a.state}
  country: {a.country}

data:
  gps: data/raw/geolife
  osm: data/external/osm/{slug}.osm.pbf
  tourism: data/external/tourism/{slug}_tourism.csv
  crime: data/external/ncrb/{slug}_crime.csv
  weather: data/external/weather/{slug}_weather.csv

risk:
  weights:
    movement_anomaly: 0.35
    geofence_risk: 0.25
    route_deviation: 0.10
    inactivity: 0.10
    historical_context: 0.10
    night_flag: 0.05
    sos: 0.05
  thresholds:
    low_max: 0.35
    moderate_max: 0.65
''',encoding='utf-8')
(d/'README.md').write_text(f'# {a.city}\nGenerated location configuration. Add normalized datasets; core code remains reusable.\n',encoding='utf-8')
print('Created',d)
