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
  timezone: Asia/Kolkata

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
import json
if not (d/'geofences.geojson').exists():
    (d/'geofences.geojson').write_text(json.dumps({'type':'FeatureCollection','features':[]},indent=1),encoding='utf-8')
# Tourist-website content. Fill it in, then rename to guide.json; the city appears on the site once guide.json exists.
skeleton={'slug':slug,'name':a.city,'state':a.state,'wiki':a.city.replace(' ','_'),'tagline':'','intro':'',
          'center':[0.0,0.0],'zoom':13,'timezone':'Asia/Kolkata','checked':'',
          'facts':{'best_time':'','getting_there':'','getting_around':'','languages':''},
          'emergency':[{'label':'Police, fire, ambulance','number':'112','note':'National emergency number, works from any phone'},
                       {'label':'Ambulance','number':'108'},{'label':'Tourist helpline','number':'1363','note':'Ministry of Tourism, 24x7, 12 languages'}],
          'safety_tips':[],
          'places':[{'id':'example','name':'','category':'heritage','area':'','must':True,'lat':0.0,'lon':0.0,'wiki':'','summary':'',
                     'hours':{'open':'09:00','close':'17:00','closed':[]},'fee':{'indian':'','foreign':''},'visit_min':60,'best':'','tips':[],'safety':''}],
          'food':[{'id':'example','name':'','kind':'street','veg':'veg','price':'₹','area':'','lat':0.0,'lon':0.0,'known_for':''}],
          'stays':[{'id':'example','name':'','kind':'area','price':'₹₹','area':'','lat':0.0,'lon':0.0,'note':''}]}
if not (d/'guide.json').exists():
    (d/'guide.todo.json').write_text(json.dumps(skeleton,indent=2,ensure_ascii=False),encoding='utf-8')
(d/'README.md').write_text(f'# {a.city}\nGenerated location configuration. Add normalized datasets; core code remains reusable.\n',encoding='utf-8')
print('Created',d)
