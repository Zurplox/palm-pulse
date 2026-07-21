#!/usr/bin/env python3
import json, re, sys
from pathlib import Path
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[1]
required=['index.html','assets/styles.css','assets/app.js','assets/icon.svg','manifest.webmanifest','sw.js','data/latest.json','config/sources.json']
missing=[p for p in required if not (ROOT/p).exists()]
if missing: raise SystemExit('Missing: '+', '.join(missing))
class Checker(HTMLParser):
    def __init__(self): super().__init__(); self.ids=set(); self.dupes=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if 'id' in values:
            if values['id'] in self.ids:self.dupes.append(values['id'])
            self.ids.add(values['id'])
c=Checker(); c.feed((ROOT/'index.html').read_text())
if c.dupes: raise SystemExit('Duplicate HTML ids: '+str(c.dupes))
for json_path in (ROOT/'data').rglob('*.json'):
    json_text=json_path.read_text()
    assert not re.search(r'AIza[0-9A-Za-z_-]{20,}', json_text), f'possible Google API key found in {json_path}'
data_text=(ROOT/'data/latest.json').read_text()
data=json.loads(data_text)
assert isinstance(data.get('stories'),list), 'stories must be a list'
assert isinstance(data.get('tbs_prices'),list), 'tbs_prices must be a list'
assert data.get('master_summary'), 'master_summary is required'
assert data.get('master_summary_type') in {'ai','extract'}, 'invalid master_summary_type'
for i,s in enumerate(data['stories']):
    for key in ['title','url','source','country','category','summary','published_at']:
        assert s.get(key), f'story {i} missing {key}'
for i,p in enumerate(data['tbs_prices']):
    for key in ['region','scheme','price_rp_per_kg','valid_from','valid_to','source_name','source_url','status','trend']:
        assert key in p and p[key] not in (None,''), f'TBS price {i} missing {key}'
    assert float(p['price_rp_per_kg']) > 0, f'TBS price {i} invalid price'
manifest=json.loads((ROOT/'manifest.webmanifest').read_text())
sources=json.loads((ROOT/'config/sources.json').read_text())
assert manifest.get('display')=='standalone'
assert len(sources)>=5
print(f'QA passed: {len(required)} files, {len(data["stories"])} stories, {len(sources)} sources.')
