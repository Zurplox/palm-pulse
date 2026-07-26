#!/usr/bin/env python3
"""Validation and client-contract checks.

This script guards two different things:

1. The original file/shape checks.
2. The consumer contract. data/latest.json is read by the website AND by an
   Android app that parses it with Moshi + KotlinJsonAdapterFactory. Moshi
   ignores unknown JSON keys (so adding fields is safe) but throws when a
   non-null Kotlin field is missing or null. It also matches several values by
   string, so those vocabularies must not drift. Every check below exists to
   stop a server-side change from breaking that app.
"""
import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
warnings: list[str] = []

required = ['index.html','assets/styles.css','assets/app.js','assets/icon.svg','manifest.webmanifest','sw.js','data/latest.json','config/sources.json']
missing = [p for p in required if not (ROOT/p).exists()]
if missing: raise SystemExit('Missing: '+', '.join(missing))


class Checker(HTMLParser):
    def __init__(self): super().__init__(); self.ids=set(); self.dupes=[]
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if 'id' in values:
            if values['id'] in self.ids: self.dupes.append(values['id'])
            self.ids.add(values['id'])


c = Checker(); c.feed((ROOT/'index.html').read_text())
if c.dupes: raise SystemExit('Duplicate HTML ids: '+str(c.dupes))

for json_path in (ROOT/'data').rglob('*.json'):
    json_text = json_path.read_text()
    assert not re.search(r'AIza[0-9A-Za-z_-]{20,}', json_text), f'possible Google API key found in {json_path}'

data_text = (ROOT/'data/latest.json').read_text()
data = json.loads(data_text)

# ----------------------------------------------------------- original checks
assert isinstance(data.get('stories'), list), 'stories must be a list'
assert isinstance(data.get('tbs_prices'), list), 'tbs_prices must be a list'
assert data.get('master_summary'), 'master_summary is required'
assert data.get('master_summary_type') in {'ai','extract'}, 'invalid master_summary_type'
for i, s in enumerate(data['stories']):
    for key in ['title','url','source','country','category','summary','published_at']:
        assert s.get(key), f'story {i} missing {key}'
for i, p in enumerate(data['tbs_prices']):
    for key in ['region','scheme','price_rp_per_kg','valid_from','valid_to','source_name','source_url','status','trend']:
        assert key in p and p[key] not in (None,''), f'TBS price {i} missing {key}'
    ages = p.get('age_prices_rp_per_kg', {})
    if p.get('data_quality','full_age_table') == 'full_age_table':
        for age in ('4','5','6'):
            assert float(ages.get(age,0)) > 0, f'TBS price {i} missing age {age}'

manifest = json.loads((ROOT/'manifest.webmanifest').read_text())
sources = json.loads((ROOT/'config/sources.json').read_text())
assert manifest.get('display') == 'standalone'
assert len(sources) >= 5

# ============ ANDROID / WEB CONSUMER CONTRACT (do not relax) ================
# Moshi throws JsonDataException on a missing or null non-null field. These are
# the non-null fields in PalmPulseNews / PalmPulseStory.
for key, kind in (('generated_at', str), ('story_count', int), ('master_summary', str), ('stories', list)):
    assert key in data and data[key] is not None, f'CONTRACT: {key} must never be null (Moshi non-null field)'
    assert isinstance(data[key], kind), f'CONTRACT: {key} must be {kind.__name__}'

for i, s in enumerate(data['stories']):
    for key in ('id','title','url','source','published_at'):
        assert isinstance(s.get(key), str) and s[key].strip(), \
            f'CONTRACT: story {i} field {key} must be a non-empty string (Moshi non-null)'

# The widget matches market_signal by substring. This vocabulary must hold:
# changing these strings silently alters widget sentiment scoring.
assert data.get('market_signal') in {'Constructive','Cautious','Balanced'}, \
    'CONTRACT: market_signal vocabulary changed; widget scoring depends on it'

# The widget headline is the first non-blank line of master_summary, and the app
# splits the summary into sections. Keep the ALL-CAPS heading structure.
first_line = next((l.strip() for l in data['master_summary'].splitlines() if l.strip()), '')
assert first_line, 'CONTRACT: master_summary must start with a non-blank line'
if first_line != 'RINGKASAN EKSEKUTIF':
    warnings.append(f'master_summary first line is {first_line!r}, not "RINGKASAN EKSEKUTIF" (widget headline)')

# Value vocabularies the clients switch on.
for i, s in enumerate(data['stories']):
    if s.get('impact') is not None:
        assert s['impact'] in {'Positive','Negative','Neutral'}, f'CONTRACT: story {i} impact vocabulary changed'
    if s.get('summary_type') is not None:
        assert s['summary_type'] in {'ai','extract'}, f'CONTRACT: story {i} summary_type vocabulary changed'
    assert re.match(r'^https?://', s['url']), f'CONTRACT: story {i} url must be http(s)'

for i, p in enumerate(data['tbs_prices']):
    assert p['trend'] in {'up','down','flat'}, f'CONTRACT: TBS {i} trend vocabulary changed'
    assert p['status'] in {'current_period','latest_available'}, f'CONTRACT: TBS {i} status vocabulary changed'
    assert p['scheme'] in {'Plasma','Swadaya','Umum'}, f'CONTRACT: TBS {i} scheme vocabulary changed'
    assert float(p['price_rp_per_kg']) > 0, f'CONTRACT: TBS {i} price must be positive'
    assert re.match(r'^https?://', str(p['source_url'])), f'CONTRACT: TBS {i} source_url must be http(s)'
    assert re.match(r'^\d{4}-\d{2}-\d{2}$', str(p['valid_from'])), f'CONTRACT: TBS {i} valid_from must be yyyy-MM-dd'
    assert re.match(r'^\d{4}-\d{2}-\d{2}$', str(p['valid_to'])), f'CONTRACT: TBS {i} valid_to must be yyyy-MM-dd'
    assert p['valid_from'] <= p['valid_to'], f'CONTRACT: TBS {i} period is inverted'
    # The app resolves prices via age keys 5 -> 6 -> 4 -> 9, so keys must stay
    # plain digit strings mapping to positive numbers.
    for age, value in (p.get('age_prices_rp_per_kg') or {}).items():
        assert re.match(r'^\d+$', str(age)), f'CONTRACT: TBS {i} age key {age!r} must be a digit string'
        assert isinstance(value, (int, float)) and value > 0, f'CONTRACT: TBS {i} age {age} must be a positive number'

# The Android FreshnessRules parser accepts only these timestamp shapes.
ts_patterns = (
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$',
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$',
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\+|-)\d{2}:\d{2}$',
    r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$',
    r'^\d{4}-\d{2}-\d{2}$',
)
for field in ('generated_at','tbs_price_updated_at'):
    value = data.get(field)
    if value:
        assert any(re.match(p, str(value)) for p in ts_patterns), \
            f'CONTRACT: {field}={value!r} is not parseable by the Android date formats'

# ------------------------------------------------------------ freshness sanity
try:
    generated = datetime.fromisoformat(str(data['generated_at']).replace('Z','+00:00'))
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - generated).total_seconds() / 3600
    if age_hours > 36:
        warnings.append(f'data/latest.json is {age_hours:.0f}h old (seed or stale republish)')
    if age_hours < -2:
        raise SystemExit(f'generated_at is {abs(age_hours):.0f}h in the future')
except ValueError:
    raise SystemExit('generated_at is not a parseable timestamp')

if isinstance(data.get('health'), dict) and data['health'].get('stale_republish'):
    warnings.append('this edition is a stale republish of the last live edition')

# ------------------------------------------------------------- history (if any)
history_path = ROOT/'data/history.json'
if history_path.exists():
    history = json.loads(history_path.read_text())
    assert isinstance(history.get('points'), list), 'history.points must be a list'
    for i, point in enumerate(history['points']):
        assert re.match(r'^\d{4}-\d{2}-\d{2}$', str(point.get('valid_from',''))), f'history point {i} bad valid_from'

for warning in warnings:
    print(f'WARNING: {warning}', file=sys.stderr)
print(f'QA passed: {len(required)} files, {len(data["stories"])} stories, {len(sources)} sources, '
      f'{len(data["tbs_prices"])} TBS schemes, contract checks OK.')
