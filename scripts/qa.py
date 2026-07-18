#!/usr/bin/env python3
import json
from pathlib import Path
from html.parser import HTMLParser
R=Path(__file__).resolve().parents[1]; need=['index.html','assets/icon.svg','manifest.webmanifest','sw.js','data/latest.json','config/sources.json','.github/workflows/daily-news.yml']
missing=[x for x in need if not (R/x).exists()]
if missing:raise SystemExit('Missing: '+','.join(missing))
class H(HTMLParser):
 def __init__(self):super().__init__();self.ids=set()
 def handle_starttag(self,t,a):
  d=dict(a)
  if 'id' in d:
   assert d['id'] not in self.ids,'duplicate id '+d['id'];self.ids.add(d['id'])
h=H();h.feed((R/'index.html').read_text());d=json.loads((R/'data/latest.json').read_text());s=json.loads((R/'config/sources.json').read_text());assert isinstance(d['stories'],list) and len(s)>=5
for x in d['stories']:
 for k in ['title','url','source','country','category','summary','published_at']:assert x.get(k),f'missing {k}'
print(f'QA passed: {len(d["stories"])} stories, {len(s)} sources, valid HTML/JSON.')
