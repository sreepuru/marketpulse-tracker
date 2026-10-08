import argparse,csv,os,re
from collections import defaultdict
import psycopg2
from dotenv import load_dotenv

ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),"..",".."))
load_dotenv(os.path.join(ROOT,".env"))

def conn():
    password=os.getenv("MARKETPULSE_DB_PASSWORD")
    if password is None: raise RuntimeError("MARKETPULSE_DB_PASSWORD is not set")
    return psycopg2.connect(
        host=os.getenv("MARKETPULSE_DB_HOST","localhost"),
        port=int(os.getenv("MARKETPULSE_DB_PORT","5432")),
        dbname=os.getenv("MARKETPULSE_DB_NAME","marketpulse"),
        user=os.getenv("MARKETPULSE_DB_USER","postgres"),
        password=password)

def norm(v):
    if v is None:return ""
    return re.sub(r"\s+"," ",re.sub(r"[^A-Z0-9]+"," ",str(v).upper().strip())).strip()

def sym(v): return re.sub(r"[^A-Z0-9]","",norm(v))

def groups(c,limit):
    q="""SELECT COALESCE(exchange,''),COALESCE(symbol,''),COALESCE(company_name,''),
    COUNT(*),MIN(news_id) FROM market_news
    WHERE news_scope='STOCK' AND (mapping_status IS DISTINCT FROM 'MAPPED' OR security_id IS NULL)
    AND COALESCE(symbol,'')<>'' GROUP BY exchange,symbol,company_name
    ORDER BY COUNT(*) DESC,exchange,symbol,company_name"""
    with c.cursor() as x:x.execute(q); r=x.fetchall()
    r=r if limit is None else r[:limit]
    return [(norm(a),sym(b),str(d).strip(),norm(d),int(e),int(f)) for a,b,d,e,f in r]

def securities(c):
    q="""SELECT security_id,isin,symbol,instrument_name,exchange,exchange_tag,asset_category
    FROM security_master WHERE is_active=TRUE ORDER BY security_id"""
    with c.cursor() as x:x.execute(q);return x.fetchall()

def identities(c):
    with c.cursor() as x:
        x.execute("""SELECT security_id,identity_type,normalized_value,exchange,source
                    FROM security_identity WHERE is_active=TRUE""")
        return x.fetchall()

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--limit-groups",type=int,default=100)
    a.add_argument("--all-groups",action="store_true")
    a.add_argument("--output",default="marketpulse_historical_identity_review.csv")
    z=a.parse_args()
    c=conn()
    try:
        gs=groups(c,None if z.all_groups else z.limit_groups); ss=securities(c); ids=identities(c)
        bysym=defaultdict(list); byname=defaultdict(list); byi=defaultdict(list); byid={r[0]:r for r in ss}
        for r in ss:
            if sym(r[2]): bysym[sym(r[2])].append(r)
            if norm(r[3]): byname[norm(r[3])].append(r)
        for sid,it,val,ex,src in ids: byi[(norm(ex),norm(val))].append((sid,it,src))
        out=[]
        for ex,s,cn,nn,ncount,sample in gs:
            cand={}
            for k in ((ex,s),(ex,nn),("",s),("",nn)):
                for sid,it,src in byi.get(k,[]): cand.setdefault(sid,[]).append("PERSISTED_IDENTITY:"+it)
            for r in bysym.get(s,[]):
                if not ex or norm(r[4])==ex or norm(r[5]) in (ex,"BOTH"):
                    cand.setdefault(r[0],[]).append("EXACT_CURRENT_SYMBOL")
            for r in byname.get(nn,[]):
                if not ex or norm(r[4])==ex or norm(r[5]) in (ex,"BOTH"):
                    cand.setdefault(r[0],[]).append("EXACT_CURRENT_NAME")
            if not cand:
                out.append([ex,s,cn,ncount,sample,0,"","","","NONE","REVIEW_REQUIRED"])
            else:
                for sid,ev in sorted(cand.items()):
                    r=byid[sid]; st="IDENTITY_EXISTS" if len(cand)==1 and any(e.startswith("PERSISTED_IDENTITY") for e in ev) else ("REVIEW_REQUIRED" if len(cand)==1 else "AMBIGUOUS")
                    out.append([ex,s,cn,ncount,sample,len(cand),sid,r[2] or "",r[3] or "" ,";".join(ev),st])
        fields=["exchange","historical_symbol","historical_name","news_count","sample_news_id","candidate_count","candidate_security_id","candidate_current_symbol","candidate_current_name","evidence","status"]
        op=os.path.abspath(z.output)
        with open(op,"w",newline="",encoding="utf-8") as f:
            w=csv.writer(f);w.writerow(fields);w.writerows(out)
        print("="*70);print("MARKETPULSE HISTORICAL IDENTITY REVIEW");print("="*70)
        print(f"Active securities loaded: {len(ss):,}")
        print(f"Identity groups selected: {len(gs):,}")
        print(f"Existing identity rows: {len(ids):,}")
        print(f"Review rows generated: {len(out):,}")
        print("No database mappings were created.")
        print("No market_news/security_master rows were changed.")
        print(f"Review file: {op}")
    finally:c.close()

if __name__=="__main__":main()