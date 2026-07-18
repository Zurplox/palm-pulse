#!/usr/bin/env python3
import os,json,re,html,time,urllib.request,urllib.parse,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone,timedelta
from email.utils import parsedate_to_datetime
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; KEY=os.getenv('GEMINI_API_KEY',''); MODEL=os.getenv('GEMINI_MODEL','gemini-2.5-flash-lite'); MAX=int(os.getenv('MAX_STORIES','18'))
SOURCES=json.loads((ROOT/'config/sources.json').read_text())
POS=['rise','gain','higher','tight','shortage','b50','b40','strong demand']; NEG=['fall','drop','lower','surplus','weak demand','oversupply']; POLICY=['policy','law','regulation','levy','duty','tax','eudr','ispo','mspo','rspo','biodiesel','b50']; PLANT=['plantation','smallholder','fertilizer','fertiliser','ganoderma','replanting','yield','harvest','tbs','ffb']
def clean(s): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',html.unescape(s or ''))).strip()
def first(s,n=300):
 s=clean(s)
 if not s:return 'Preview unavailable. Open the original article to read more.'
 p=re.split(r'(?<=[.!?])\s+',s); x=p[0]+((' '+p[1]) if len(p)>1 and len(p[0])<70 else '')
 return x if len(x)<=n else x[:n-1].rsplit(' ',1)[0]+'…'
def date(s):
 try:
  d=parsedate_to_datetime(s); return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
 except: 
  try:return datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(timezone.utc)
  except:return datetime.now(timezone.utc)
def parse(raw):
 root=ET.fromstring(raw); out=[]
 for n in root.iter():
  if n.tag.rsplit('}',1)[-1].lower() not in ('item','entry'):continue
  d={}
  for c in list(n):
   k=c.tag.rsplit('}',1)[-1].lower(); v=''.join(c.itertext()).strip()
   if k=='link':d['link']=c.attrib.get('href') or v
   elif k in ('title','summary','description','content','published','updated','pubdate'):d['published' if k=='pubdate' else k]=v
  out.append(d)
 return out
def classify(t,s,default):
 x=(t+' '+s).lower(); cat='Policy' if any(k in x for k in POLICY) else 'Plantation' if any(k in x for k in PLANT) else default
 a=sum(k in x for k in POS); b=sum(k in x for k in NEG); return cat,'Positive' if a>b else 'Negative' if b>a else 'Neutral'
def fetch():
 out=[]; cutoff=datetime.now(timezone.utc)-timedelta(days=5)
 for src in SOURCES:
  try:
   q=urllib.request.Request(src['url'],headers={'User-Agent':'PalmPulse/1.0'}); raw=urllib.request.urlopen(q,timeout=25).read()
   for e in parse(raw)[:25]:
    title=clean(e.get('title')); link=e.get('link',''); published=date(e.get('published') or e.get('updated') or '')
    if not title or not link or published<cutoff:continue
    snippet=first(e.get('summary') or e.get('description') or e.get('content')); publisher=src['name']
    if ' - ' in title:
     a,b=title.rsplit(' - ',1)
     if len(b.split())<8:title,publisher=a,b
    cat,impact=classify(title,snippet,src['category']); x=(title+' '+snippet).lower(); country='Indonesia' if 'indonesia' in x or 'jakarta' in x else 'Malaysia' if 'malaysia' in x or 'mpob' in x else src['country']
    out.append({'id':re.sub(r'[^a-z0-9]+','-',title.lower()).strip('-')[:100],'title':title,'url':link,'source':publisher,'country':country,'category':cat,'impact':impact,'published_at':published.isoformat(),'snippet':snippet,'summary':snippet,'summary_type':'extract'})
  except Exception as e: print('Feed warning:',src['name'],e)
 out.sort(key=lambda x:x['published_at'],reverse=True); seen=set(); unique=[]
 for x in out:
  k=' '.join(re.findall(r'[a-z0-9]+',x['title'].lower()))
  if k in seen:continue
  seen.add(k);unique.append(x)
  if len(unique)>=MAX:break
 return unique
def summarize(x):
 prompt=f"Summarize this palm-oil news item in 2 short factual sentences, maximum 60 words. Use only supplied text. If insufficient return INSUFFICIENT.\nHeadline: {x['title']}\nPreview: {x['snippet']}"
 endpoint='https://generativelanguage.googleapis.com/v1beta/models/'+urllib.parse.quote(MODEL,safe='')+':generateContent?key='+urllib.parse.quote(KEY,safe='')
 body=json.dumps({'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'temperature':.15,'maxOutputTokens':130}}).encode(); req=urllib.request.Request(endpoint,data=body,headers={'Content-Type':'application/json'})
 r=json.loads(urllib.request.urlopen(req,timeout=35).read()); text=clean(r['candidates'][0]['content']['parts'][0]['text'])
 return None if text=='INSUFFICIENT' or len(text)<30 else text
def main():
 DATA.mkdir(exist_ok=True); stories=fetch(); current=DATA/'latest.json'
 if not stories and current.exists():print('No fresh stories; kept current edition.');return
 if KEY:
  for x in stories[:12]:
   try:
    s=summarize(x)
    if s:x['summary']=s;x['summary_type']='ai'
    time.sleep(.3)
   except Exception as e:print('Gemini fallback:',e);break
 now=datetime.now(timezone.utc); score=sum(1 if x['impact']=='Positive' else -1 if x['impact']=='Negative' else 0 for x in stories); signal='Constructive' if score>=3 else 'Cautious' if score<=-3 else 'Balanced'
 if current.exists():
  try:
   old=json.loads(current.read_text()); day=old['generated_at'][:10]; (DATA/'archive').mkdir(exist_ok=True); (DATA/'archive'/f'{day}.json').write_text(json.dumps(old,indent=2,ensure_ascii=False))
  except:pass
 current.write_text(json.dumps({'generated_at':now.isoformat(),'timezone':'Asia/Singapore','market_signal':signal,'gemini_enabled':bool(KEY),'stories':stories},indent=2,ensure_ascii=False));print('Published',len(stories),'stories')
if __name__=='__main__':main()
