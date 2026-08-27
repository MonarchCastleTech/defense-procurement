"""Autonomous, reproducible defense-procurement acceleration warning."""
from __future__ import annotations

import json, math, statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import requests

ROOT=Path(__file__).resolve().parents[1]; OUTPUT=ROOT/"data"/"output.json"; TIMEOUT=60; FALLBACK_HOURS=72
USER_AGENT="MonarchCastleTech-DefenseProcurement/2.0 (public research; github.com/MonarchCastleTech/defense-procurement)"
WEIGHTS={"eu_notices":.30,"us_awards":.25,"nato_demand":.20,"acquisition_policy":.15,"critical_materials":.10}
TED="https://api.ted.europa.eu/v3/notices/search"; USA="https://api.usaspending.gov/api/v2/search/spending_by_transaction/"; NATO="https://www.nato.int/sitemap.xml"; FR="https://www.federalregister.gov/api/v1/documents.json"; FRED="https://fred.stlouisfed.org/graph/fredgraph.csv"
NAICS=["336411","336412","336413","336414","336415","336419","332993","332994"]
CPV=["35300000","35400000","35600000","35700000"]
NATO_TERMS={"procurement":2,"production":2,"industry":1.5,"industrial":1.5,"munition":2,"capability":1,"capabilities":1,"investment":1,"contract":1.5,"air-defence":2,"missile":2,"drone":2}
SOURCES=[
 {"name":"EU TED Search API","role":"European defense procurement notices","url":"https://docs.ted.europa.eu/api/latest/search.html"},
 {"name":"USAspending API","role":"U.S. defense-industrial transactions","url":"https://api.usaspending.gov/docs/intro-tutorial"},
 {"name":"NATO official sitemap","role":"Alliance demand and production language","url":NATO},
 {"name":"Federal Register API","role":"Defense acquisition policy activity","url":"https://www.federalregister.gov/developers/documentation/api/v1"},
 {"name":"FRED","role":"Copper and nickel dislocation","url":"https://fred.stlouisfed.org/"},
]

def clamp(v:float,lo:float=0,hi:float=100)->float:return max(lo,min(hi,v))
def avg(v:list[float])->float:return sum(v)/len(v) if v else 0.0
def number(v:Any)->float:
 try:return float(v or 0)
 except (TypeError,ValueError):return 0.0
def parse_date(v:Any)->date|None:
 try:return date.fromisoformat(str(v)[:10])
 except (TypeError,ValueError):return None
def parse_dt(v:Any)->datetime|None:
 try:
  d=datetime.fromisoformat(str(v).replace("Z","+00:00")); return d.replace(tzinfo=d.tzinfo or timezone.utc).astimezone(timezone.utc)
 except (TypeError,ValueError):return None
def robust_z(current:float,baseline:list[float])->float:
 clean=[x for x in baseline if math.isfinite(x)]
 if len(clean)<3:return 0.0
 med=statistics.median(clean); mad=statistics.median(abs(x-med) for x in clean)
 if mad>1e-9:return (current-med)/(1.4826*mad)
 sd=statistics.pstdev(clean); return (current-med)/sd if sd>1e-9 else 0.0
def band(s:float)->str:return "BASELINE" if s<25 else "WATCH" if s<45 else "ELEVATED" if s<65 else "HIGH" if s<80 else "SEVERE"
def get(url:str,**kwargs:Any)->requests.Response:
 headers={"User-Agent":USER_AGENT,"Accept":"*/*",**kwargs.pop("headers",{})}; r=requests.get(url,headers=headers,timeout=kwargs.pop("timeout",TIMEOUT),**kwargs); r.raise_for_status(); return r
def post(url:str,payload:dict[str,Any])->dict[str,Any]:
 r=requests.post(url,json=payload,headers={"User-Agent":USER_AGENT,"Accept":"application/json"},timeout=TIMEOUT); r.raise_for_status(); return r.json()
def weekly(rows:list[tuple[date,float]],anchor:date,size:int=14)->list[float]:
 bins=[0.0]*size
 for observed,value in rows:
  age=(anchor-observed).days
  if 0<=age<size*7:bins[age//7]+=value
 return bins
def velocity(current:float,baseline:list[float],density_scale:float)->tuple[float,float]:
 z=robust_z(current,baseline); density=clamp(current*density_scale,hi=55); anomaly=clamp(max(0,z)*18,hi=45); return round(.55*density+.45*anomaly,1),round(z,2)
def scalar(v:Any)->Any:
 if isinstance(v,list):return v[0] if v else None
 if isinstance(v,dict):
  for k in ("eng","en"):
   if k in v:return scalar(v[k])
  return scalar(next(iter(v.values()),None))
 return v

def collect_ted(now:datetime)->dict[str,Any]:
 start=(now.date()-timedelta(days=98)).strftime("%Y%m%d"); query=f"publication-date >= {start} AND classification-cpv IN ({' '.join(CPV)}) SORT BY publication-date DESC"
 fields=["publication-number","publication-date","notice-title","buyer-name","buyer-country","classification-cpv","notice-type"]; notices=[]
 for page in range(1,7):
  data=post(TED,{"query":query,"fields":fields,"page":page,"limit":250,"scope":"ALL","paginationMode":"PAGE_NUMBER"}); batch=data.get("notices",[]); notices.extend(batch)
  if len(batch)<250:break
 seen={}; observations=[]
 for row in notices:
  pub=str(scalar(row.get("publication-number")) or ""); observed=parse_date(scalar(row.get("publication-date")))
  if pub and observed:seen[pub]=row; observations.append((observed,1.0))
 bins=weekly(observations,now.date()); current=avg(bins[:2]); score,z=velocity(current,bins[2:14],1.8); evidence=[]
 for pub,row in sorted(seen.items(),key=lambda x:str(scalar(x[1].get("publication-date"))),reverse=True):
  evidence.append({"id":pub,"date":str(scalar(row.get("publication-date")))[:10],"title":str(scalar(row.get("notice-title")) or "Untitled defense notice"),"buyer":str(scalar(row.get("buyer-name")) or "—"),"country":str(scalar(row.get("buyer-country")) or "—"),"cpv":list(dict.fromkeys(row.get("classification-cpv") or []))[:4],"url":f"https://ted.europa.eu/en/notice/-/detail/{pub}"})
 return {"key":"eu_notices","score":score,"status":band(score),"weight":WEIGHTS["eu_notices"],"available":True,"retained":False,"coverage":len(seen),"current_14d_weekly_equivalent":round(current,2),"baseline_weekly_median":round(statistics.median(bins[2:14]),2),"anomaly_z":z,"method":"Defense CPV publication velocity over 14 days versus 12 prior weeks.","evidence":evidence[:16]}

def collect_usa(now:datetime)->dict[str,Any]:
 payload={"filters":{"time_period":[{"start_date":(now.date()-timedelta(days=260)).isoformat(),"end_date":now.date().isoformat()}],"agencies":[{"type":"awarding","tier":"toptier","name":"Department of Defense"}],"award_type_codes":["A","B","C","D"],"naics_codes":{"require":NAICS}},"fields":["Action Date","Award ID","Recipient Name","Transaction Amount","Awarding Sub Agency","Transaction Description","NAICS"],"sort":"Action Date","order":"desc","limit":100,"page":1}; rows=[]
 for page in range(1,7):
  payload["page"]=page; data=post(USA,payload); batch=data.get("results",[]); rows.extend(batch)
  if not (data.get("page_metadata") or {}).get("hasNext"):break
 parsed=[(parse_date(r.get("Action Date")),r) for r in rows]; parsed=[x for x in parsed if x[0]]
 if not parsed:raise RuntimeError("No USAspending defense-industrial transactions")
 anchor=max(x[0] for x in parsed); lag=(now.date()-anchor).days; obs=[(d,max(0,number(r.get("Transaction Amount")))) for d,r in parsed]; bins=weekly(obs,anchor); current=avg(bins[:2]); base=bins[2:14]; z=robust_z(current,base)
 magnitude=clamp((math.log10(max(current,1))-6)/3*55); anomaly=clamp(max(0,z)*18,hi=45); freshness=clamp(1-lag/120,0,1); score=round((.55*magnitude+.45*anomaly)*freshness,1); recipients={}
 for d,r in parsed:
  if (anchor-d).days<35:
   name=r.get("Recipient Name") or "Unknown"; recipients[name]=recipients.get(name,0)+max(0,number(r.get("Transaction Amount")))
 evidence=[]
 for d,r in sorted(parsed,key=lambda x:(x[0],number(x[1].get("Transaction Amount"))),reverse=True)[:18]:
  naics=r.get("NAICS") or {}; evidence.append({"date":d.isoformat(),"award_id":r.get("Award ID"),"recipient":r.get("Recipient Name"),"amount":round(number(r.get("Transaction Amount")),2),"agency":r.get("Awarding Sub Agency"),"description":r.get("Transaction Description"),"naics":naics.get("code") if isinstance(naics,dict) else naics})
 return {"key":"us_awards","score":score,"status":band(score),"weight":WEIGHTS["us_awards"],"available":True,"retained":False,"coverage":len(rows),"latest_observation":anchor.isoformat(),"reporting_lag_days":lag,"freshness_factor":round(freshness,2),"current_14d_weekly_equivalent":round(current,2),"baseline_weekly_median":round(statistics.median(base),2),"anomaly_z":round(z,2),"recipient_concentration":sorted(({"name":k,"amount":round(v,2)} for k,v in recipients.items()),key=lambda x:x["amount"],reverse=True)[:8],"method":"Defense-industrial NAICS obligations anchored to latest reported date and freshness-discounted.","evidence":evidence}

def collect_nato(now:datetime)->dict[str,Any]:
 root=ET.fromstring(get(NATO).content); rows=[]
 for node in root:
  vals={c.tag.split("}")[-1]:c.text for c in node}; url=vals.get("loc") or ""; modified=parse_dt(vals.get("lastmod")); age=(now-modified).days if modified else 999
  if not 0<=age<98:continue
  slug=urlparse(url).path.lower(); terms=[t for t in NATO_TERMS if t in slug]
  if terms:
   weight=1+sum(NATO_TERMS[t] for t in terms); rows.append({"date":modified.date().isoformat(),"title":" ".join(w.capitalize() for w in slug.rstrip('/').split('/')[-1].replace('-',' ').split()),"url":url,"terms":terms,"weight":round(weight,2),"age":age})
 bins=weekly([(parse_date(r["date"]),r["weight"]) for r in rows],now.date()); current=avg(bins[:2]); score,z=velocity(current,bins[2:14],7)
 return {"key":"nato_demand","score":score,"status":band(score),"weight":WEIGHTS["nato_demand"],"available":True,"retained":False,"coverage":len(rows),"current_14d_weekly_equivalent":round(current,2),"baseline_weekly_median":round(statistics.median(bins[2:14]),2),"anomaly_z":z,"method":"Official NATO capability, procurement and production title-language velocity.","evidence":sorted([r for r in rows if r["age"]<35],key=lambda x:x["date"],reverse=True)[:14]}

def collect_policy(now:datetime)->dict[str,Any]:
 params={"per_page":100,"order":"newest","conditions[agencies][]":"defense-acquisition-regulations-system","conditions[publication_date][gte]":(now.date()-timedelta(days=98)).isoformat(),"fields[]":["document_number","title","publication_date","type","html_url","abstract"]}; results=get(FR,params=params).json().get("results",[]); obs=[]
 for r in results:
  d=parse_date(r.get("publication_date"));
  if d:obs.append((d,1.5 if r.get("type") in ("Rule","Proposed Rule") else 1.0))
 bins=weekly(obs,now.date()); current=avg(bins[:2]); score,z=velocity(current,bins[2:14],12); evidence=[{"date":r.get("publication_date"),"title":r.get("title"),"type":r.get("type"),"url":r.get("html_url"),"abstract":r.get("abstract")} for r in results if parse_date(r.get("publication_date")) and (now.date()-parse_date(r.get("publication_date"))).days<35]
 return {"key":"acquisition_policy","score":score,"status":band(score),"weight":WEIGHTS["acquisition_policy"],"available":True,"retained":False,"coverage":len(results),"current_14d_weekly_equivalent":round(current,2),"baseline_weekly_median":round(statistics.median(bins[2:14]),2),"anomaly_z":z,"method":"Defense Acquisition Regulations System publication velocity; rules weighted 1.5.","evidence":evidence[:12]}

def fred_series(series:str,label:str,now:datetime)->dict[str,Any]:
 lines=get(FRED,params={"id":series,"cosd":(now.date()-timedelta(days=1500)).isoformat()}).text.splitlines(); points=[]
 for line in lines[1:]:
  parts=line.split(','); d=parse_date(parts[0] if parts else None)
  if d and len(parts)>1 and parts[1] not in ("","."):points.append((d,number(parts[1])))
 returns=[(points[i][1]/points[i-1][1]-1)*100 for i in range(1,len(points)) if points[i-1][1]>0]
 if len(returns)<12:raise RuntimeError(f"Insufficient FRED {series}")
 z=robust_z(returns[-1],returns[-31:-1]); score=clamp((abs(z)-.5)/2.5*100)
 return {"id":series,"label":label,"latest_date":points[-1][0].isoformat(),"latest_value":round(points[-1][1],2),"change_pct":round(returns[-1],2),"robust_z":round(z,2),"score":round(score,1),"url":f"https://fred.stlouisfed.org/series/{series}"}
def collect_materials(now:datetime)->dict[str,Any]:
 with ThreadPoolExecutor(max_workers=2) as pool:
  a=pool.submit(fred_series,"PCOPPUSDM","Global copper",now); b=pool.submit(fred_series,"PNICKUSDM","Global nickel",now); rows=[a.result(),b.result()]
 score=round(.55*rows[0]["score"]+.45*rows[1]["score"],1); return {"key":"critical_materials","score":score,"status":band(score),"weight":WEIGHTS["critical_materials"],"available":True,"retained":False,"coverage":2,"method":"Absolute robust-z of one-month copper and nickel returns.","evidence":rows}

def load_previous()->dict[str,Any]:
 try:return json.loads(OUTPUT.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError):return {}
def fallback(previous:dict[str,Any],key:str,now:datetime,error:Exception)->dict[str,Any]:
 generated=parse_dt((previous.get("meta") or {}).get("generated")); old=(previous.get("components") or {}).get(key)
 if generated and timedelta(0)<=now-generated<=timedelta(hours=FALLBACK_HOURS) and isinstance(old,dict) and old.get("available"):
  row=json.loads(json.dumps(old)); row["retained"]=True; row["retained_reason"]=type(error).__name__; return row
 return {"key":key,"score":None,"status":"UNAVAILABLE","weight":WEIGHTS[key],"available":False,"retained":False,"coverage":0,"method":"Unavailable; excluded and weights renormalized.","evidence":[],"error":type(error).__name__}
def main()->None:
 now=datetime.now(timezone.utc); previous=load_previous(); collectors={"eu_notices":collect_ted,"us_awards":collect_usa,"nato_demand":collect_nato,"acquisition_policy":collect_policy,"critical_materials":collect_materials}; components={}; notes=[]
 for key,collector in collectors.items():
  try:components[key]=collector(now); print(f"[live] {key}: {components[key]['score']}")
  except Exception as error:components[key]=fallback(previous,key,now,error); notes.append(f"{key}: {'retained' if components[key].get('retained') else 'unavailable'} ({type(error).__name__})"); print(f"[fallback] {key}: {error}")
 available=[r for r in components.values() if r.get("available") and r.get("score") is not None]; denom=sum(r["weight"] for r in available); raw=sum(r["score"]*r["weight"] for r in available)/denom if denom else 0; official=any(number(components.get(k,{}).get("score"))>=45 for k in ("eu_notices","nato_demand","acquisition_policy")); industrial=any(number(components.get(k,{}).get("score"))>=40 for k in ("us_awards","critical_materials")); bonus=5.0 if official and industrial else 0.0; score=round(clamp(raw+bonus),1); status=band(score); coverage=len(available); retained=sum(1 for r in available if r.get("retained")); confidence="HIGH" if coverage==5 and not retained else "MEDIUM" if coverage>=4 else "LOW"; generated=now.isoformat(); old_history=[r for r in previous.get("history",[]) if isinstance(r,dict) and r.get("generated")]; old_history.append({"generated":generated,"score":score,"status":status})
 output={"meta":{"project":"defense-procurement","generated":generated,"mode":"live" if coverage==5 and not retained else "partial","version":"2.0.0","horizon":"0–90 days","classification":"procurement-acceleration-screening-not-conflict-probability-or-contract-forecast","coverage":f"{coverage}/5","confidence":confidence,"source_notes":notes},"warning":{"score":score,"raw_score":round(raw,1),"concurrence_bonus":bonus,"status":status,"headline":f"Defense procurement acceleration pressure is {status.lower()} at {score:.1f}/100.","interpretation":"The index detects unusual procurement, policy, industrial-demand and input-cost pressure. It is a screening warning, not a conflict probability or contract forecast."},"components":components,"history":old_history[-60:],"sources":SOURCES,"methodology":{"weights":WEIGHTS,"fallback_hours":FALLBACK_HOURS,"concurrence_rule":"+5 when official demand/policy ≥45 and awards/materials ≥40"}}
 OUTPUT.parent.mkdir(parents=True,exist_ok=True); OUTPUT.write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding="utf-8"); print(f"score={score} status={status} coverage={coverage}/5 confidence={confidence}")

if __name__=="__main__":main()
