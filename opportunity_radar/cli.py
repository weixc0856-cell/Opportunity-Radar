from collections import Counter
import argparse, hashlib, json, logging, os, re, sys
from pathlib import Path
from .config import Settings, load_scoring
from .digest import render_digest, empty_reason
from .email_sender import send_email, send_email_detailed, parse_recipients
from .freshrss_client import FreshRSSClient, ordered_feed_ids
from .render_html import render_html
from .scoring import score_article, RULES_VERSION, DEFAULT_LANE_WEIGHTS, DEFAULT_LANE_THRESHOLDS
from .lanes import LANES
from .source_policy import load_sources, is_approved
from .store import Store
from .analyzer import PROMPT_VERSION, PROMPT_HASH
from .source_audit import audit_sources
from .sampling import parse_window, filter_articles
from .fulltext import apply_article_bodies
from .model_service import ensure_model
from .log_util import rotate_log, RedactFilter

def _norm_name(value):
    """FreshRSS feed titles and registry names differ only in punctuation far more often
    than they differ in words, so matching on letters and digits alone recovers most rows."""
    return re.sub(r'[^0-9a-z一-鿿]+','',str(value or '').lower())

def lane_display_config(cfg):
    """Effective weights/thresholds per lane, so the report shows what actually scored."""
    lanes=(cfg or {}).get('lanes') or {}
    weights={}; thresholds={}
    for lane in LANES:
        entry=lanes.get(lane) or {}
        weights[lane]={**DEFAULT_LANE_WEIGHTS[lane],**(entry.get('weights') or {})}
        thresholds[lane]={**DEFAULT_LANE_THRESHOLDS[lane],**(entry.get('thresholds') or {})}
    return weights,thresholds

def source_index(sources):
    """Id lookup plus an unambiguous normalised-name lookup.

    Name matching exists only for records written before source_id was stored. A name
    that collides after normalisation is dropped rather than guessed: applying one
    source's lane or quota to another is worse than applying neither.
    """
    by_id={}; by_name={}; ambiguous=set()
    for x in sources:
        by_id[x.source_id]=x
        key=_norm_name(x.name)
        if not key: continue
        prior=by_name.get(key)
        if prior is not None and prior.source_id!=x.source_id:
            ambiguous.add(key)
        else:
            by_name[key]=x
    for key in ambiguous: by_name.pop(key,None)
    return by_id,by_name,ambiguous

def resolve_source(item,by_id,by_name):
    sid=str((item or {}).get('source_id') or '')
    if sid and sid in by_id: return by_id[sid]
    key=_norm_name((item or {}).get('source_name'))
    return by_name.get(key) if key else None

def apply_source_caps(items,sources):
    """Decide what enters this issue, without rewriting what the item is worth.

    `status` stays the evidence-and-score verdict. `distribution` records whether the
    item made it into this reading list. A quota must never turn a priority finding into
    a "filtered" one: that would say "not worth attention" when the truth is "did not fit
    today's slice". Deferred items keep their status, score and evidence in the appendix.

    Runs after every item is scored, ordered by priority then score, so a late high-value
    announcement is never displaced by an earlier low-value one. The limit is hard across
    both bands, because the cap exists to guarantee diversity, not to reward volume.
    """
    by_id,by_name,_=source_index(sources)
    for item in items:
        item['distribution']='included' if item.get('status') in {'priority','watch'} else ''
    used=Counter(); deferred=0; unresolved=0
    order=sorted(range(len(items)),key=lambda i:(items[i].get('status')!='priority',-items[i].get('score',0),i))
    for i in order:
        item=items[i]
        if item.get('status') not in {'priority','watch'}: continue
        source=resolve_source(item,by_id,by_name)
        if source is None: unresolved+=1; continue
        if not source.source_cap: continue
        used[source.source_id]+=1
        if used[source.source_id]>source.source_cap:
            item['distribution']='deferred'; deferred+=1
    return {'deferred':deferred,'unresolved':unresolved}

def evaluate(article,analysis,weights=None,thresholds=None,model='',source=None,lanes_config=None,
             multi_source=False,event_seen_before=None,min_full_text_chars=None):
    extra={}
    if min_full_text_chars: extra['min_full_text_chars']=min_full_text_chars
    sc=score_article(analysis,weights=weights,article=article,thresholds=thresholds,source=source,
                     lanes_config=lanes_config,multi_source=multi_source,
                     event_seen_before=event_seen_before,**extra)
    meta={'model':model,'prompt_version':PROMPT_VERSION,'prompt_hash':PROMPT_HASH,'rules_version':RULES_VERSION,'validation_status':'ok',
          'source_id':getattr(source,'source_id','') if source is not None else '',
          'lane':sc['lane'],'evidence_state':sc['evidence_state'],'evidence_basis':sc['evidence_basis'],
          'content_basis_estimate':sc['content_basis_estimate'],
          'input_hash':hashlib.sha256(f"{article.url}\n{article.title}\n{article.summary}".encode()).hexdigest(),
          'source_content_hash':hashlib.sha256(article.summary.encode()).hexdigest(),
          'title_hash':hashlib.sha256(article.title.encode()).hexdigest(),
          'output_hash':hashlib.sha256(json.dumps(analysis,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
    return {'title':article.title,'url':article.url,'source_name':article.source_name,'analysis':analysis,
            'score':sc['score'],'status':sc['status'],'filter_reason':sc['filter_reason'],
            'source_id':meta['source_id'],'lane':sc['lane'],'distribution':'included',
            'evidence_level':sc['evidence_level'],'evidence_state':sc['evidence_state'],
            'evidence_rank':sc['evidence_rank'],'evidence_basis':sc['evidence_basis'],
            'content_basis_estimate':sc['content_basis_estimate'],
            'classification':sc['classification'],'market_validation':sc['market_validation'],
            'risk_flag':sc['risk_flag'],'verification_note':sc['verification_note'],
            'evidence':sc.get('evidence',[]),'evidence_integrity':sc.get('evidence_integrity',''),
            'components':sc['components'],'meta':meta,'scoring':sc}

def sample():
    from types import SimpleNamespace
    from datetime import datetime, timezone
    a={'category':'customer_pain','summary_zh':'离线示例：小型餐厅每周手工排班与核对工时，重复性工作可能存在自动化需求，需访谈核实。',
       'pain_point':'每周手工排班并重复核对工时，平均耗费两小时以上','target_customer':'使用 Excel 排班的独立餐厅老板',
       'commercial_signal':'尚无真实付费证据','revenue_claim':'none','evidence_quotes':['重复性工作量可能存在自动化需求'],
       'uncertainties':['离线示例，不代表真实文章'],'suggested_next_step':'访谈 5 位餐厅老板，确认每周耗时与现有排班工具的付费情况',
       'relevance_score':60,'confidence':'low'}
    art=SimpleNamespace(title='离线示例：重复性工作自动化',url='https://example.invalid/sample',source_name='Sample only',
                        summary='离线示例：餐厅老板每周手工排班与核对工时，重复性工作量可能存在自动化需求，需访谈核实。',published=datetime.now(timezone.utc).isoformat(),feed_id='')
    return [evaluate(art,a)]

def _stats(items,fetched=0,new=0,queued=0,analyzed=0,failed=0,skipped=0,thresholds=None,weights=None,
           updated=0,duplicate_events=0,lane_weights=None,lane_thresholds=None,source_issues=None,
           deferred=0,unresolved_sources=0,source_match=None):
    counts={s:sum(1 for x in items if x.get('status')==s) for s in ('priority','watch','filtered')}
    st={'fetched':fetched,'new':new,'updated':updated,'queued':queued,'duplicate_events':duplicate_events,'analyzed':analyzed,'failed':failed,'skipped':skipped,
        'counts':counts,'rules_version':RULES_VERSION,'thresholds':thresholds or {},'weights':weights or {},
        'lane_weights':lane_weights or {},'lane_thresholds':lane_thresholds or {},'source_issues':source_issues or [],
        'deferred':deferred,'unresolved_sources':unresolved_sources,'source_match':source_match or {}}
    st['empty_reason']=empty_reason(st); return st

def _validate_report(subject,body,html,items=None,stats=None):
    if not subject or '执行摘要' not in body or '<html' not in html.lower():
        raise ValueError('report validation failed; keeping the previous report')
    # Every number printed in the report must come from the records it renders. Recompute
    # the status counts here rather than trusting a value passed alongside them.
    if items is not None and stats and stats.get('counts'):
        actual={s:sum(1 for x in items if x.get('status')==s) for s in ('priority','watch','filtered')}
        expected={s:stats['counts'][s] for s in actual if s in stats['counts']}
        if {s:actual[s] for s in expected}!=expected:
            raise ValueError('report counts do not match the analysed items; keeping the previous report')

def _atomic_write(path,text):
    tmp=Path(str(path)+'.tmp'); tmp.write_text(text,encoding='utf-8'); os.replace(tmp,path)

def _write(report_dir,subject,body,html,name='latest-digest',archive=True,items=None,stats=None,run_id=None):
    """Write the latest report plus a dated local archive of the report and structured results.

    The archive stores this application's generated analysis, evidence metadata and report
    artifacts. It intentionally does not snapshot full third-party article bodies.
    """
    from datetime import datetime
    d=Path(report_dir); d.mkdir(parents=True,exist_ok=True)
    text=subject+'\n\n'+body
    _validate_report(subject,body,html,items,stats)
    report_hash=hashlib.sha256(text.encode()).hexdigest()[:16]
    _atomic_write(d/f'{name}.txt',text)
    _atomic_write(d/f'{name}.html',html)
    if not archive: return '',report_hash
    local_now=datetime.now().astimezone()
    stamp=local_now.strftime('%Y-%m-%d-%H%M%S')
    # Date folders keep daily browsing, backup and retention predictable.
    arch=d/'archive'/local_now.strftime('%Y')/local_now.strftime('%m')/local_now.strftime('%d')
    arch.mkdir(parents=True,exist_ok=True)
    txt=arch/f'{stamp}.txt'; html_path=arch/f'{stamp}.html'
    items_path=arch/f'{stamp}.items.json'; manifest_path=arch/f'{stamp}.manifest.json'
    _atomic_write(txt,text); _atomic_write(html_path,html)
    payload_items=[{k:item.get(k) for k in ('title','url','source_name','analysis','score','status','filter_reason',
                                             'source_id','intelligence_lines','lane','distribution','evidence_level','evidence_state','evidence_rank','evidence_basis','content_basis_estimate',
                                             'classification','market_validation','risk_flag','verification_note',
                                             'evidence','evidence_integrity','components','meta','scoring')} for item in (items or [])]
    _atomic_write(items_path,json.dumps({'schema_version':2,'generated_at':local_now.isoformat(),
                                         'run_id':run_id,'report_hash':report_hash,'items':payload_items},
                                        ensure_ascii=False,indent=2,default=str))
    manifest={'schema_version':2,'generated_at':local_now.isoformat(),'run_id':run_id,'report_hash':report_hash,
              'subject':subject,'article_count':len(payload_items),
              'files':{'text':txt.name,'html':html_path.name,'items':items_path.name,'manifest':manifest_path.name},
              'stats':stats or {},
              'storage_note':'Generated analysis snapshot and report only; full source article bodies are not archived.'}
    _atomic_write(manifest_path,json.dumps(manifest,ensure_ascii=False,indent=2,default=str))
    return str(txt),report_hash

def send_decision(analyzed,updated,failed,email_on_empty):
    """Decide whether this run should send mail; keeps failure and no-new-content distinct."""
    if analyzed==0 and failed>0: return 'analysis_failed'
    if analyzed==0 and updated==0 and not email_on_empty: return 'no_new_content'
    return 'send'

def run_status(errors,failed_recipients=0):
    """Partial article or recipient failures are not a clean success."""
    return 'partial_failed' if (errors>0 or failed_recipients>0) else 'success'

def _alert(store,s,reason):
    try: n=store.consecutive_failures()
    except Exception: n=0
    if n < s.alert_after_failures: return False
    try:
        send_email(s.smtp_host,s.smtp_port,s.smtp_username,s.smtp_password,s.email_from,s.email_to,
                   '[Opportunity Radar] 连续运行失败告警',
                   f'连续 {n} 次运行失败。最近一次原因：{reason}\n\n请检查 FreshRSS、本地模型服务和运行日志。\n',
                   s.smtp_starttls,security=s.smtp_security)
        logging.warning('Alert email sent after %d consecutive failures',n); return True
    except Exception:
        logging.exception('Failed to send alert email'); return False

def _render_only(store,s,cfg):
    """Rebuild the report from stored analyses without calling the model or re-scoring."""
    from .lanes import derive_lane
    rows=load_sources()
    by_id,by_name,ambiguous=source_index(rows)
    if ambiguous: logging.warning('Ambiguous source names after normalisation, ignored for backfill: %s',', '.join(sorted(ambiguous)))
    unresolved=matched_id=matched_name=0
    items=[]
    for r in store.list_analyses(500):
        try: d=json.loads(r['result_json'])
        except (ValueError,TypeError): continue
        sc=d.get('scoring',{}); meta=d.get('meta',{})
        # Records stored before lanes existed still have a source; route them the same
        # way a live run would instead of dumping everything into lane A.
        sid=str(meta.get('source_id') or '')
        if sid and sid in by_id: source=by_id[sid]; matched_id+=1
        else:
            source=by_name.get(_norm_name(r['source_name']))
            if source is not None: matched_name+=1
        if not sc.get('lane') and source is None:
            unresolved+=1
            logging.warning('Legacy record matched no source; lane derived from content only: %s',r['title'][:80])
        lane=sc.get('lane') or derive_lane({},d.get('analysis',{}),source,sc.get('classification',{}))
        items.append({'title':r['title'],'url':r['url'],'source_name':r['source_name'],'analysis':d.get('analysis',{}),
                      'score':r['score'],'status':sc.get('status','filtered'),'filter_reason':sc.get('filter_reason',''),
                      'source_id':meta.get('source_id',''),
                      'intelligence_lines':getattr(source,'intelligence_lines',''),
                      'lane':lane,'content_basis_estimate':sc.get('content_basis_estimate',''),
                      'evidence_basis':sc.get('evidence_basis',''),
                      'evidence_level':sc.get('evidence_level','none'),
                      'evidence_state':sc.get('evidence_state',''),'evidence_rank':sc.get('evidence_rank',''),
                      'classification':sc.get('classification',{}),'market_validation':sc.get('market_validation',''),
                      'risk_flag':sc.get('risk_flag',''),'verification_note':sc.get('verification_note',''),
                      'evidence':sc.get('evidence',[]),'evidence_integrity':sc.get('evidence_integrity',''),
                      'components':sc.get('components',{}),'meta':d.get('meta',{})})
    lane_weights,lane_thresholds=lane_display_config(cfg)
    caps=apply_source_caps(items,rows)
    stats={'fetched':len(items),'new':0,'updated':0,'queued':0,'analyzed':len(items),'failed':0,'skipped':0,
           'counts':{k:sum(1 for x in items if x.get('status')==k) for k in ('priority','watch','filtered')},
           'rules_version':RULES_VERSION,'lane_weights':lane_weights,'lane_thresholds':lane_thresholds,
           'render_only':True,'unresolved_sources':unresolved,'deferred':caps['deferred'],
           'source_match':{'by_id':matched_id,'by_name':matched_name,'unresolved':unresolved,'ambiguous':len(ambiguous)}}
    stats['model']=next((x['meta'].get('model') for x in items if x.get('meta',{}).get('model')),'')
    stats['prompt_version']=next((x['meta'].get('prompt_version') for x in items if x.get('meta',{}).get('prompt_version')),'')
    stats['prompt_hash']=next((x['meta'].get('prompt_hash') for x in items if x.get('meta',{}).get('prompt_hash')),'')
    stats['empty_reason']=empty_reason(stats)
    subject,body=render_digest(items,stats); html=render_html(items,stats); _write(s.report_dir,subject,body,html,archive=False)
    print(body); print(f'Saved to {Path(s.report_dir)/"latest-digest.txt"} and latest-digest.html (render only, no archive).'); return 0

def main(argv=None):
    # A report can contain currency symbols or non-CJK characters. On Windows the
    # console defaults to a legacy code page, and echoing the report used to raise
    # UnicodeEncodeError *after* the report was written, marking a good run as failed.
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    p=argparse.ArgumentParser(); p.add_argument('--dry-run',action='store_true'); p.add_argument('--sample',action='store_true'); p.add_argument('--render-only',action='store_true'); args=p.parse_args(argv)
    s=Settings.from_env(); Path(s.log_path).parent.mkdir(parents=True,exist_ok=True)
    rotate_log(s.log_path)
    handlers=[logging.FileHandler(s.log_path,encoding='utf-8'),logging.StreamHandler(sys.stdout)]
    for h in handlers: h.addFilter(RedactFilter())
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=handlers)
    Path(s.report_dir).mkdir(parents=True,exist_ok=True)
    cfg=load_scoring(); lanes_cfg=cfg.get('lanes'); lane_weights,lane_thresholds=lane_display_config(cfg)
    min_chars=(cfg.get('evidence') or {}).get('full_text_min_chars')
    if args.sample:
        items=sample(); stats=_stats(items,fetched=len(items),new=len(items),queued=len(items),analyzed=len(items),
                                    lane_weights=lane_weights,lane_thresholds=lane_thresholds)
        stats['sample_mode']=True
        stats['empty_reason']='离线演示数据，不代表真实来源、用户需求或商业机会。'
        subject,body=render_digest(items,stats); html=render_html(items,stats); _write(s.report_dir,subject,body,html,name='sample-digest',archive=False)
        print(body); print(f'\nSaved offline sample to {Path(s.report_dir)/"sample-digest.txt"}'); return 0
    missing=s.validate(mail=not (args.dry_run or args.render_only))
    if missing: print('Missing settings: '+', '.join(missing),file=sys.stderr); return 2
    if args.render_only:
        if not Path(s.db_path).exists():
            print(f'Database not found: {s.db_path}. Run a digest first, then re-render.',file=sys.stderr); return 2
        # Genuinely read-only: no schema migration, no backfill, no writes of any kind.
        return _render_only(Store(s.db_path,read_only=True),s,cfg)
    store=Store(s.db_path)
    registry=load_sources()
    audit=audit_sources(registry)
    audit_errors=[x for x in audit if x['severity']=='error']
    source_issues=[x for x in audit if x['severity']!='info']
    if audit_errors:
        for issue in audit_errors:
            logging.error('Source registry blocked: %s [%s] %s',issue['source_id'],issue['code'],issue['message'])
        print(f'Source registry has {len(audit_errors)} blocking error(s). Run python -m opportunity_radar.source_audit and fix config/sources.csv.',file=sys.stderr)
        return 3
    sources=[x for x in registry if is_approved(x)]
    approved_feed_ids={x.freshrss_feed_id for x in sources}
    source_by_feed={x.freshrss_feed_id:x for x in sources}
    try:
        win_start,win_end=parse_window(s.sample_since,s.sample_until)
    except ValueError as e:
        print(f'Invalid sample window: {e}',file=sys.stderr); return 2
    if not sources:
        msg='No approved sources in config/sources.csv. Keep sources disabled until reviewed.'
        if not args.dry_run: print(msg,file=sys.stderr); return 3
        items=[]; stats=_stats(items,lane_weights=lane_weights,lane_thresholds=lane_thresholds,source_issues=source_issues)
        subject,body=render_digest(items,stats); html=render_html(items,stats); _write(s.report_dir,subject,body,html); print(body); return 0
    ready,detail=ensure_model(s)
    if not ready:
        logging.error('Local model unavailable: %s',detail)
        print(f'Local model unavailable: {detail}. Start deploy/windows/start-model.ps1 or set OR_MODEL_AUTOSTART=1.',file=sys.stderr)
        return 3
    rid=store.start_run(stage='starting'); store.update_run(rid,pid=os.getpid()); errors=analyzed=new_count=fetched=updated_count=duplicate_events=0; items=[]
    try:
        # Fail closed: only articles whose FreshRSS feed ID is explicitly mapped to an approved source are processed.
        store.update_run(rid,stage='fetching')
        client=FreshRSSClient(s.freshrss_base_url,s.freshrss_username,s.freshrss_api_key,s.request_timeout)
        # A windowed run has to look past max_articles to still fill the window; the
        # ceiling keeps a low-frequency feed from triggering an unbounded fetch.
        pool_limit=s.max_articles if not (win_start or win_end) else max(s.max_articles,200)
        raw=[a for a in client.fetch_articles(pool_limit,feed_ids=ordered_feed_ids(approved_feed_ids)) if a.feed_id in approved_feed_ids]
        in_window=filter_articles(raw,win_start,win_end)
        articles=in_window[:s.max_articles]; fetched=len(articles)
        # Opt-in page fetch: the registry decides per source; the evidence rules do not move.
        pages_fetched=apply_article_bodies(articles,source_by_feed)
        if win_start or win_end:
            logging.info('Sample window %s..%s: pool=%d in_window=%d sampled=%d',
                         s.sample_since or '(open)',s.sample_until or '(open)',len(raw),len(in_window),len(articles))
        store.update_run(rid,stage='analyzing')
        from .analyzer import LocalAnalyzer
        model=LocalAnalyzer(s.llm_base_url,s.llm_model,s.llm_timeout,s.llm_max_tokens,api_key=s.llm_api_key)
        queued=skipped=0
        for a in articles:
            key=Store.key(a.url)
            was_analyzed=store.analyzed(key)
            previous_input_hash=store.analysis_input_hash(key) if was_analyzed else None
            current_input_hash=hashlib.sha256(f"{a.url}\n{a.title}\n{a.summary}".encode()).hexdigest()
            new_count+=store.save_article(a,key)
            if was_analyzed and previous_input_hash==current_input_hash:
                skipped+=1; continue
            if was_analyzed and previous_input_hash!=current_input_hash:
                updated_count+=1
                logging.info('Source content changed; re-analyzing and invalidating stale review: %s',a.url)
                store.invalidate_review(key)
            if not was_analyzed and store.event_seen(Store.event_key(a.title),key,hashlib.sha256(a.summary.encode()).hexdigest()):
                duplicate_events+=1
                logging.info('Duplicate event skipped: %s',a.title)
                continue
            queued+=1
            try:
                prior_sources=store.event_sources(Store.event_key(a.title),key)
                multi_source=len(prior_sources|{a.source_name})>=2
                result=model.analyze(a.title,a.summary,a.source_name,a.url)
                item=evaluate(a,result,thresholds=None,model=s.llm_model,source=source_by_feed.get(a.feed_id),
                              lanes_config=lanes_cfg,multi_source=multi_source,event_seen_before=bool(prior_sources),
                              min_full_text_chars=min_chars)
                # Reporting only: which intelligence mainline(s) this source was registered for.
                item['intelligence_lines']=getattr(source_by_feed.get(a.feed_id),'intelligence_lines','')
                store.save_analysis(key,result,item['scoring'],item['meta'])
                items.append(item); analyzed+=1
            except Exception:
                errors+=1; logging.exception('Article analysis failed: %s',a.url)
        caps=apply_source_caps(items,sources)
        stats=_stats(items,fetched,new_count,queued,analyzed,errors,skipped,updated=updated_count,duplicate_events=duplicate_events,
                     lane_weights=lane_weights,lane_thresholds=lane_thresholds,source_issues=source_issues,
                     deferred=caps['deferred'],unresolved_sources=caps['unresolved'])
        stats['model']=s.llm_model; stats['prompt_version']=PROMPT_VERSION; stats['prompt_hash']=PROMPT_HASH
        if pages_fetched: stats['full_text_fetched']=pages_fetched
        if win_start or win_end:
            stats['sample_window']={'since':s.sample_since,'until':s.sample_until,
                                    'pool':len(raw),'in_window':len(in_window),'sampled':len(articles)}
        subject,body=render_digest(items,stats); html=render_html(items,stats)
        store.update_run(rid,stage='rendering')
        archive_path,report_hash=_write(s.report_dir,subject,body,html,items=items,stats=stats,run_id=rid)
        out=Path(s.report_dir)/'latest-digest.txt'
        if args.dry_run:
            store.finish_run(rid,'dry_run',fetched,analyzed,errors,'No email sent',archive_path,report_hash,exit_code=0)
            print(body); print(f'Saved to {out} and latest-digest.html; no email sent.'); return 0
        decision=send_decision(analyzed,updated_count,errors,s.email_on_empty)
        if decision=='analysis_failed':
            store.finish_run(rid,'analysis_failed',fetched,analyzed,errors,'All attempted analyses failed; email skipped',archive_path,report_hash,exit_code=1)
            logging.error('No analysis succeeded; digest not sent.')
            _alert(store,s,f'{errors} analyses failed and none succeeded')
            print(body); print('No analysis succeeded; digest not sent. See the log.',file=sys.stderr); return 1
        if decision=='no_new_content':
            store.delivery(rid,'skipped_no_new_content','No new analyses')
            store.finish_run(rid,'no_new_content',fetched,analyzed,errors,'No new content; email skipped',archive_path,report_hash,exit_code=0)
            logging.info('No new content; digest not sent.')
            print(body); print(f'No new content; report saved to {out} but not emailed.'); return 0
        key=hashlib.sha256(f'{subject}|{report_hash}'.encode()).hexdigest()[:32]
        recipients=parse_recipients(s.email_to)
        already=store.sent_recipients(key)
        pending=[r for r in recipients if r.casefold() not in already]
        if not pending:
            store.delivery(rid,'skipped_duplicate','All recipients already sent',key)
            status=run_status(errors)
            store.finish_run(rid,status,fetched,analyzed,errors,'Duplicate report; email skipped',archive_path,report_hash,exit_code=0 if status=='success' else 1)
            logging.info('Duplicate report; email skipped.')
            print(f'Same report already sent to all recipients; email skipped. Report saved to {out}.'); return 0 if status=='success' else 1
        store.update_run(rid,stage='sending')
        results=send_email_detailed(s.smtp_host,s.smtp_port,s.smtp_username,s.smtp_password,s.email_from,pending,subject,body,s.smtp_starttls,html=html,security=s.smtp_security)
        failed=[]
        for res in results:
            store.delivery(rid,'sent' if res['ok'] else 'failed',res.get('error',''),key,res['recipient'])
            if not res['ok']: failed.append(res)
        if failed:
            msg=f"{len(results)-len(failed)}/{len(results)} pending recipient(s) sent; failed: "+', '.join(r['recipient'] for r in failed)
            logging.error(msg)
            store.finish_run(rid,'partial_failed',fetched,analyzed,errors,msg,archive_path,report_hash,exit_code=1)
            print(body); print(msg,file=sys.stderr); return 1
        status=run_status(errors)
        store.finish_run(rid,status,fetched,analyzed,errors,'Some articles failed' if status!='success' else '',archive_path,report_hash,exit_code=0 if status=='success' else 1)
        if status!='success': logging.warning('Run completed with article errors: %d',errors)
        logging.info('Digest sent: articles=%d analyzed=%d errors=%d recipients=%d',fetched,analyzed,errors,len(results))
        return 0 if status=='success' else 1
    except Exception as e:
        store.finish_run(rid,'failed',fetched,analyzed,errors+1,str(e),exit_code=1); logging.exception('Run failed')
        _alert(store,s,str(e))
        print(f'Run failed: {e}',file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
