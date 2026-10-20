import argparse, hashlib, json, logging, os, sys
from pathlib import Path
from .config import Settings, load_scoring
from .digest import render_digest, empty_reason
from .email_sender import send_email
from .freshrss_client import FreshRSSClient
from .render_html import render_html
from .scoring import score_article, RULES_VERSION
from .source_policy import load_sources, is_approved
from .store import Store
from .analyzer import PROMPT_VERSION

def evaluate(article,analysis,weights=None,thresholds=None,model='',source=None):
    sc=score_article(analysis,weights=weights,article=article,thresholds=thresholds,source=source)
    meta={'model':model,'prompt_version':PROMPT_VERSION,'rules_version':RULES_VERSION,'validation_status':'ok',
          'input_hash':hashlib.sha256(f"{article.url}\n{article.title}\n{article.summary}".encode()).hexdigest(),
          'output_hash':hashlib.sha256(json.dumps(analysis,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
    return {'title':article.title,'url':article.url,'source_name':article.source_name,'analysis':analysis,
            'score':sc['score'],'status':sc['status'],'filter_reason':sc['filter_reason'],
            'evidence_level':sc['evidence_level'],'classification':sc['classification'],
            'risk_flag':sc['risk_flag'],'verification_note':sc['verification_note'],
            'evidence':sc.get('evidence',[]),'evidence_integrity':sc.get('evidence_integrity',''),
            'meta':meta,'scoring':sc}

def sample():
    from types import SimpleNamespace
    a={'category':'customer_pain','summary_zh':'离线示例：重复性工作可能存在自动化需求，需访谈核实。','pain_point':'示例问题，非真实市场结论','target_customer':'待验证的业务团队','commercial_signal':'尚无真实付费证据','revenue_claim':'none','evidence_quotes':[],'uncertainties':['离线示例，不代表真实文章'],'suggested_next_step':'访谈潜在客户并确认问题频率与付费条件','relevance_score':60,'confidence':'low'}
    art=SimpleNamespace(title='离线示例：重复性工作自动化',url='https://example.invalid/sample',source_name='Sample only',summary='离线示例：重复性工作可能存在自动化需求，需访谈核实。',published='',feed_id='')
    return [evaluate(art,a)]

def _stats(items,fetched=0,new=0,queued=0,analyzed=0,failed=0,skipped=0,thresholds=None,weights=None):
    counts={s:sum(1 for x in items if x.get('status')==s) for s in ('priority','watch','filtered')}
    st={'fetched':fetched,'new':new,'queued':queued,'analyzed':analyzed,'failed':failed,'skipped':skipped,
        'counts':counts,'rules_version':RULES_VERSION,'thresholds':thresholds or {},'weights':weights or {}}
    st['empty_reason']=empty_reason(st); return st

def _validate_report(subject,body,html):
    if not subject or '执行摘要' not in body or '<html' not in html.lower():
        raise ValueError('report validation failed; keeping the previous report')

def _atomic_write(path,text):
    tmp=Path(str(path)+'.tmp'); tmp.write_text(text,encoding='utf-8'); os.replace(tmp,path)

def _write(report_dir,subject,body,html,name='latest-digest',archive=True):
    _validate_report(subject,body,html)
    d=Path(report_dir); d.mkdir(parents=True,exist_ok=True)
    _atomic_write(d/f'{name}.txt',subject+'\n\n'+body)
    _atomic_write(d/f'{name}.html',html)
    if not archive: return
    from datetime import datetime
    day=datetime.now().astimezone().strftime('%Y-%m-%d'); arch=d/'archive'; arch.mkdir(parents=True,exist_ok=True)
    _atomic_write(arch/f'{day}.txt',subject+'\n\n'+body)
    _atomic_write(arch/f'{day}.html',html)

def _render_only(store,s,weights,thresholds):
    """Rebuild the report from stored analyses without calling the model or re-scoring."""
    items=[]
    for r in store.list_analyses(500):
        try: d=json.loads(r['result_json'])
        except (ValueError,TypeError): continue
        sc=d.get('scoring',{})
        items.append({'title':r['title'],'url':r['url'],'source_name':r['source_name'],'analysis':d.get('analysis',{}),
                      'score':r['score'],'status':sc.get('status','filtered'),'filter_reason':sc.get('filter_reason',''),
                      'evidence_level':sc.get('evidence_level','none'),'classification':sc.get('classification',{}),
                      'risk_flag':sc.get('risk_flag',''),'verification_note':sc.get('verification_note',''),
                      'evidence':sc.get('evidence',[]),'evidence_integrity':sc.get('evidence_integrity',''),
                      'meta':d.get('meta',{})})
    stats={'fetched':len(items),'new':0,'queued':0,'analyzed':len(items),'failed':0,'skipped':0,
           'counts':{k:sum(1 for x in items if x.get('status')==k) for k in ('priority','watch','filtered')},
           'rules_version':RULES_VERSION,'thresholds':thresholds or {},'weights':weights or {},'render_only':True}
    stats['model']=next((x['meta'].get('model') for x in items if x.get('meta',{}).get('model')),'')
    stats['prompt_version']=next((x['meta'].get('prompt_version') for x in items if x.get('meta',{}).get('prompt_version')),'')
    stats['empty_reason']=empty_reason(stats)
    subject,body=render_digest(items,stats); html=render_html(items,stats); _write(s.report_dir,subject,body,html)
    print(body); print(f'Saved to {Path(s.report_dir)/"latest-digest.txt"} and latest-digest.html (render only).'); return 0

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--dry-run',action='store_true'); p.add_argument('--sample',action='store_true'); p.add_argument('--render-only',action='store_true'); args=p.parse_args(argv)
    s=Settings.from_env(); Path(s.log_path).parent.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[logging.FileHandler(s.log_path,encoding='utf-8'),logging.StreamHandler(sys.stdout)])
    Path(s.report_dir).mkdir(parents=True,exist_ok=True)
    cfg=load_scoring(); weights=cfg.get('weights'); thresholds=cfg.get('thresholds')
    if args.sample:
        items=sample(); stats=_stats(items,analyzed=len(items),thresholds=thresholds,weights=weights)
        subject,body=render_digest(items,stats); html=render_html(items,stats); _write(s.report_dir,subject,body,html,name='sample-digest',archive=False)
        print(body); print(f'\nSaved offline sample to {Path(s.report_dir)/"sample-digest.txt"}'); return 0
    missing=s.validate(mail=not (args.dry_run or args.render_only))
    if missing: print('Missing settings: '+', '.join(missing),file=sys.stderr); return 2
    store=Store(s.db_path)
    if args.render_only: return _render_only(store,s,weights,thresholds)
    sources=[x for x in load_sources() if is_approved(x)]
    approved_feed_ids={x.freshrss_feed_id for x in sources}
    source_by_feed={x.freshrss_feed_id:x for x in sources}
    if not sources:
        msg='No approved sources in config/sources.csv. Keep sources disabled until reviewed.'
        if not args.dry_run: print(msg,file=sys.stderr); return 3
        items=[]; stats=_stats(items,thresholds=thresholds,weights=weights)
        subject,body=render_digest(items,stats); html=render_html(items,stats); _write(s.report_dir,subject,body,html); print(body); return 0
    rid=store.start_run(); errors=analyzed=new_count=fetched=0; items=[]
    try:
        # Fail closed: only articles whose FreshRSS feed ID is explicitly mapped to an approved source are processed.
        client=FreshRSSClient(s.freshrss_base_url,s.freshrss_username,s.freshrss_api_key,s.request_timeout)
        articles=[a for a in client.fetch_articles(s.max_articles,feed_ids=sorted(approved_feed_ids)) if a.feed_id in approved_feed_ids][:s.max_articles]; fetched=len(articles)
        from .analyzer import LocalAnalyzer
        model=LocalAnalyzer(s.llm_base_url,s.llm_model,s.llm_timeout,s.llm_max_tokens,api_key=s.llm_api_key)
        queued=skipped=0
        for a in articles:
            key=Store.key(a.url); new_count+=store.save_article(a,key)
            if store.analyzed(key): skipped+=1; continue
            queued+=1
            try:
                result=model.analyze(a.title,a.summary,a.source_name,a.url); item=evaluate(a,result,weights,thresholds,s.llm_model,source_by_feed.get(a.feed_id)); store.save_analysis(key,result,item['scoring'],item['meta'])
                items.append(item); analyzed+=1
            except Exception:
                errors+=1; logging.exception('Article analysis failed: %s',a.url)
        stats=_stats(items,fetched,new_count,queued,analyzed,errors,skipped,thresholds,weights)
        stats['model']=s.llm_model; stats['prompt_version']=PROMPT_VERSION
        subject,body=render_digest(items,stats); html=render_html(items,stats); _write(s.report_dir,subject,body,html)
        out=Path(s.report_dir)/'latest-digest.txt'
        if args.dry_run: store.finish_run(rid,'dry_run',fetched,analyzed,errors,'No email sent'); print(body); print(f'Saved to {out} and latest-digest.html; no email sent.'); return 0
        send_email(s.smtp_host,s.smtp_port,s.smtp_username,s.smtp_password,s.email_from,s.email_to,subject,body,s.smtp_starttls,html=html)
        store.delivery(rid,'sent'); store.finish_run(rid,'success',fetched,analyzed,errors); logging.info('Digest sent: articles=%d analyzed=%d errors=%d',fetched,analyzed,errors); return 0
    except Exception as e:
        store.finish_run(rid,'failed',fetched,analyzed,errors+1,str(e)); logging.exception('Run failed'); print(f'Run failed: {e}',file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
