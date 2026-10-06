"""Project state, stable identities, deterministic exports and resumable batches.

No credentials. PDF understanding and identity decisions are provided by a reviewing
agent. State is one atomic JSON transaction; shared Markdown and graph derive from it.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unicodedata

VERSIONS={'skill':'3.1.2','card':'3.0.0','reference':'1.0.0','schema':'1.0.0','classification':'1.0.0'}
HEADINGS=['快速理解','数据与研究设计','方法与关键设计','主要结果','贡献、局限与分析','分类与检索入口','阅读提示与待核验']
CLASS={'T01E':'心脏活动与心血管疾病/心电','T01M':'心脏活动与心血管疾病/心脏机械信号',
       'T01P':'心脏活动与心血管疾病/心音与脉搏波','T01X':'心脏活动与心血管疾病/多模态',
       'T02':'血压与脉搏传播','T03':'呼吸与心肺联合监测','T04':'自主神经与压力状态',
       'T05':'胎儿与孕期监测','T06':'其他人体测量与生理建模','T07':'工程技术与计算方法','T00':'待确认'}

def now():return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
def sha(data):return hashlib.sha256(data).hexdigest()
def jsha(data):return sha(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,data):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_name(p.name+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(temp,p)
def norm(s):return ''.join(c for c in unicodedata.normalize('NFKC',s).casefold() if c.isalnum())
def norm_doi(s):return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)','',(s or '').strip().lower())
def citation_fields(raw,typ):
    quoted=re.search(r'[“\"](.+?)[”\"]',raw)
    apa=re.search(r'\([^)]*\b(?:19|20)\d{2}[^)]*\)\.\s*',raw)
    title=None;author_text=None
    if quoted:title=quoted[1];author_text=raw[:quoted.start()].rstrip(' ,')
    elif apa:
        title=raw[apa.end():].split('. ',1)[0].rstrip(' .');author_text=raw[:apa.start()].strip()
    years=list(dict.fromkeys(int(x) for x in re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)',raw)))
    return {'title':title,'authors_source_text':author_text,'year':years[0] if len(years)==1 and typ not in ('website','equipment_website') else None,
            'year_candidates':years,'source_citation_raw':raw,'display_label':title or raw[:160],
            'bibliographic_fields_status':'source_parser_candidate_external_identity_unresolved'}
def scope(text):
    ids=[]
    for part in re.split(r'[,，\s]+',text.strip()):
        if not part:continue
        m=re.fullmatch(r'[sS](\d+)(?:[-–—~至][sS]?(\d+))?',part)
        if not m:raise ValueError('invalid S scope: '+part)
        a,b=int(m[1]),int(m[2] or m[1])
        if a<1 or b<a or b-a>10000:raise ValueError('invalid scope range')
        ids.extend(f'S{i:03d}' for i in range(a,b+1))
    return list(dict.fromkeys(ids))

@contextmanager
def locked(path):
    p=Path(str(path)+'.lock');p.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise RuntimeError('state locked; inspect running writer before recovery')
    try:
        os.write(fd,str(os.getpid()).encode());os.close(fd);yield
    finally:p.unlink(missing_ok=True)

def find_project(given):
    if given:return Path(given)
    if os.getenv('PAPER_LIBRARY_PROJECT'):return Path(os.environ['PAPER_LIBRARY_PROJECT'])
    for d in [Path.cwd(),*Path.cwd().parents]:
        if (d/'paper-library.project.json').exists():return d/'paper-library.project.json'
    raise FileNotFoundError('provide --project or PAPER_LIBRARY_PROJECT')

def artifact_ok(a):
    if not a or not a.get('path'):return False
    p=Path(a['path'])
    return p.is_file() and sha(p.read_bytes())==a['sha256']

def fingerprint(rec,kind=None):
    selected=VERSIONS if not kind else {k:v for k,v in VERSIONS.items()
        if k in ('schema',kind if kind=='card' else 'reference') or kind=='card' and k=='classification'}
    return jsha({'source_sha256':rec.get('original',{}).get('sha256'),
                 'version':rec.get('adopted_version'),'versions':selected})

def task_status(rec,mode,save_target='local'):
    if not rec:return {'status':'missing_identity','next':['核对身份及原文']}
    orig=rec.get('original',{});p=Path(orig.get('local_path') or '__missing__')
    valid=p.is_file() and sha(p.read_bytes())==orig.get('sha256')
    if not valid:return {'status':'source_missing_or_changed','next':['fetch_original' if orig.get('media_id') else '核对原文／版本／哈希，受影响产物待重新生成']}
    nexts=[]
    if mode!='original-only':
        for kind in (['reference'] if mode=='references-only' else ['card','reference']):
            art=rec.get('artifacts',{}).get(kind)
            if not artifact_ok(art):
                nexts.append('fetch_'+kind if art and art.get('availability')=='remote_verified' else
                             'owner_local_'+kind if art and art.get('availability')=='owner_local_only' else kind)
            elif art.get('source_fingerprint')!=fingerprint(rec,kind):nexts.append(kind)
    if save_target=='ima':
        if orig.get('save_status')!='saved_verified':nexts.append('verify_original' if orig.get('media_id') else 'save_original')
        for kind in ([] if mode=='original-only' else ['reference'] if mode=='references-only' else ['card','reference']):
            art=rec.get('artifacts',{}).get(kind)
            if art and artifact_ok(art) and art.get('save_status')!='saved_verified':nexts.append('save_'+kind)
    return {'status':'reusable' if not nexts else 'pending','next':nexts,
            'save':{k:v.get('save_status','save_not_requested') for k,v in rec.get('artifacts',{}).items()}}

def plan(db,args):
    bid=args.batch or db.get('last_batch')
    old=db['batches'].get(bid)
    if args.resume:
        if not old:raise ValueError('resume batch missing')
        ids=old['scope'];mode=old['mode'];target=old.get('save_target','local')
    else:
        if not bid or not args.scope:raise ValueError('plan requires --batch and --scope')
        ids=scope(args.scope);mode=args.mode;target=getattr(args,'save_target','local')
        if old and (old['scope']!=ids or old['mode']!=mode):raise ValueError('batch scope/mode conflict; use new ID')
    results={sid:task_status(db['literature'].get(sid),mode,target) for sid in ids}
    if not args.dry_run:
        b=old or {'id':bid,'scope':ids,'mode':mode,'created_at':now(),'versions':VERSIONS.copy(),
                  'papers':{},'shared_state':'local_candidate','next':'逐篇完成后export及按请求发布'}
        b['save_target']=target
        if b.get('plan')!=results:b['plan_checked_at']=now();b['plan']=results
        db['batches'][bid]=b;db['last_batch']=bid
    return {'batch':bid,'mode':mode,'save_target':target,'scope':ids,'papers':results}

def register(db,meta):
    p=Path(meta['pdf_path']);content=p.read_bytes()
    if not content.startswith(b'%PDF-'):raise ValueError('invalid PDF')
    h=sha(content)
    for sid,r in db['literature'].items():
        if not sid.startswith('S'):continue
        if r.get('original',{}).get('sha256')==h:return {'id':sid,'status':'reused_original'}
        if norm(r.get('title') or '')==norm(meta['title']):
            raise ValueError('same-title existing S with different file; review identity/version before allocation')
        if meta.get('doi') and meta.get('doi_verified') and norm_doi(r.get('doi'))==norm_doi(meta['doi']):
            if norm(r['title'])!=norm(meta['title']):raise ValueError('DOI title conflict')
            raise ValueError('existing work DOI with different file/version; add reviewed version to existing S')
    if not meta.get('live_duplicate_check') or not meta.get('version_id'):
        raise ValueError('new registration requires live full-library duplicate check and version_id')
    n=max([int(k[1:]) for k in db['literature'] if re.fullmatch(r'S\d+',k)] or [0])+1
    sid=f'S{n:03d}'
    rec={k:v for k,v in meta.items() if k not in ('pdf_path','live_duplicate_check','version_id')}
    rec.update(id=sid,roles=['group'],adopted_version=meta['version_id'],
        original={'local_path':str(p.resolve()),'sha256':h,'save_status':'save_pending'},
        versions=[{'id':meta['version_id'],'sha256':h,'status':'reviewed'}],
        artifacts={},migration_status='new_pending',registered_at=now())
    if rec.get('type') in ('conference_paper','preprint'):
        rec['journal_rank']={'cas':{'status':'not_applicable','year':None,'source':None},'jcr':{'status':'not_applicable','categories':[]}}
    db['literature'][sid]=rec
    return {'id':sid,'status':'registered','next':'save original, plan --mode new'}

def choose_entity(db,ref):
    eid=ref.get('entity_id')
    if eid:
        if eid not in db['literature'] or not ref.get('identity_evidence'):
            raise ValueError('explicit identity requires existing entity and evidence')
        if 'reference' not in db['literature'][eid]['roles']:db['literature'][eid]['roles'].append('reference')
        return eid,'verified',ref['identity_evidence']
    if ref.get('doi_verified'):
        if not ref.get('doi') or not ref.get('identity_evidence'):raise ValueError('DOI verification lacks evidence')
        key='doi:'+norm_doi(ref['doi'])
        status='verified'
    elif ref.get('identity_key'):
        if not ref.get('identity_evidence'):raise ValueError('shared identity lacks evidence')
        key='reviewed:'+ref['identity_key'];status='verified'
    else:key='rawhash:'+sha(norm(ref['raw']).encode('utf-8'));status='unresolved'
    def identity_key(r):
        old=r.get('identity_key')
        return 'rawhash:'+sha(old[4:].encode('utf-8')) if old and old.startswith('raw:') else old
    matches=[k for k,r in db['literature'].items() if identity_key(r)==key]
    if len(matches)>1:raise ValueError('ambiguous duplicate identity key')
    if matches:return matches[0],status,ref.get('identity_evidence') or '原始题录完全相同；外部身份待匹配'
    n=max([int(k[1:]) for k in db['literature'] if re.fullmatch(r'E\d+',k)] or [0])+1
    eid=f'E{n:05d}'
    fields=citation_fields(ref['raw'],ref['type'])
    db['literature'][eid]={'id':eid,'roles':['reference'],**fields,'title':ref.get('title') or fields['title'],
        'authors':ref.get('authors',[]),'year':ref.get('year',fields['year']),'source':ref.get('source'),
        'type':ref['type'],'doi':ref.get('doi'),'doi_status':'verified' if ref.get('doi_verified') else 'not_matched',
        'identity_key':key,'identity_status':status,'identity_evidence':ref.get('identity_evidence'),
        'versions':[],'adopted_version':None,'abstract_original':None,'author_keywords':[],
        'tags':[],'full_text_status':'not_requested','registered_at':now()}
    return eid,status,ref.get('identity_evidence') or '来源参考条目已核验；外部题录身份未匹配'

def artifact_filename(folder,sid,title,kind,h):
    if not isinstance(title,str) or not title.strip():raise ValueError('verified paper title required for file name')
    mapping=dict(zip('\\/:*?"<>|','＼／：＊？＂＜＞｜'))
    clean=''.join(mapping.get(c,c) for c in title if ord(c)>=32)
    clean=re.sub(r'\s+',' ',clean).strip(' .')
    label='知识卡片' if kind=='card' else '参考文献清单'
    suffix=f'_{label}_r{h[:8]}.md'
    budget=min(180,245-len(str(Path(folder).resolve()))-len(sid)-len(suffix)-2)
    if budget<20:raise ValueError('output path too long; shorten project output_root')
    return f'{sid}_{clean[:budget].rstrip(" .")}{suffix}'

def put_artifact(config,sid,kind,text,fp,old,title):
    h=sha(text.encode())
    folder=Path(config['output_root'])/('cards' if kind=='card' else 'references')
    target=folder/artifact_filename(folder,sid,title,kind,h)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and sha(target.read_bytes())!=h:
        # A generated Windows CRLF copy can be repaired only if its text is identical.
        if sha(target.read_text(encoding='utf-8').encode())!=h:raise ValueError('artifact name collision')
    target.write_bytes(text.encode('utf-8'))
    result={'path':str(target),'sha256':h,'source_fingerprint':fp,'status':'local_verified',
            'save_status':'save_not_requested','created_at':now()}
    if old and old.get('sha256')==h and Path(old['path']).name==target.name:result=old
    elif old:result['supersedes']=old
    return result

def commit(config,db,bid,payload,force=False):
    b=db['batches'][bid];sid=payload['id']
    if sid not in b['scope']:raise ValueError('outside batch scope')
    rec=db['literature'][sid];mode=b['mode'];review=payload.get('review',{})
    h=sha(Path(payload['pdf_path']).read_bytes())
    if h!=payload['pdf_sha256'] or h!=rec['original']['sha256']:raise ValueError('source hash differs; review new version first')
    if payload['version_id']!=rec['adopted_version']:raise ValueError('adopted version mismatch')
    fp=fingerprint(rec);ph=jsha(payload)
    prev=b['papers'].get(sid,{})
    if not force and prev.get('payload_sha256')==ph and task_status(rec,mode)['status']=='reusable':
        return {'id':sid,'status':'reused_valid','artifacts':rec.get('artifacts',{})}
    rec['original']['page_count']=payload['page_count']
    reuse_reference=(prev.get('payload_sha256')==ph and artifact_ok(rec.get('artifacts',{}).get('reference'))
                     and rec['artifacts']['reference'].get('source_fingerprint')==fingerprint(rec,'reference'))
    reuse_card=(prev.get('payload_sha256')==ph and artifact_ok(rec.get('artifacts',{}).get('card'))
                and rec['artifacts']['card'].get('source_fingerprint')==fingerprint(rec,'card'))
    if mode!='original-only' and (force or not reuse_reference):
        refs=payload.get('references',[])
        if not review.get('references_checked') or review.get('reference_count')!=len(refs):raise ValueError('reference review/count missing')
        if any(not x.get('raw') or not x.get('pages') or x.get('type','unclassified')=='unclassified' for x in refs):raise ValueError('reference raw/pages/type incomplete')
        if [x['order'] for x in refs]!=list(range(1,len(refs)+1)):raise ValueError('nonconsecutive reference order')
        nums=[x.get('number') for x in refs]
        if any(n is not None for n in nums) and nums!=list(range(1,len(refs)+1)):raise ValueError('printed reference numbering gap')
        if any(any(not isinstance(pg,int) or pg<1 or pg>payload['page_count'] for pg in x['pages']) for x in refs):raise ValueError('reference page outside source')
        for x in db['occurrences'].values():
            if x['source_id']==sid and x['source_version']==payload['version_id']:x['state']='history'
        for x in db['relations'].values():
            if x['from']==sid and x['from_version']==payload['version_id']:x['state']='history'
        occurrences=[]
        for ref in refs:
            eid,status,evidence=choose_entity(db,ref)
            rid=f"{sid}@{payload['version_id']}#"+('ref-' if ref.get('number') is not None else 'order-')+f"{ref['order']:03d}"
            occ={'id':rid,'source_id':sid,'source_version':payload['version_id'],'number':ref.get('number'),
                 'order':ref['order'],'raw':ref['raw'],'pages':ref['pages'],'entity_id':eid,'type':ref['type'],
                 'identity_status':status,'identity_evidence':evidence,'source_status':'reference_list_verified',
                 'state':'effective','extracted_at':payload.get('extracted_at') or now()[:10]}
            entity=db['literature'][eid]
            occ['identifiers']={'doi':entity.get('doi'),'doi_status':entity.get('doi_status','not_matched'),
                                'other':ref.get('other_identifiers',[]),'other_status':'source_reported' if ref.get('other_identifiers') else 'not_matched'}
            if ref.get('correction'):occ['correction']=ref['correction']
            db['occurrences'][rid]=occ;occurrences.append(occ)
            relid='R'+sha(rid.encode())[:20]
            db['relations'][relid]={'id':relid,'from':sid,'from_version':payload['version_id'],'to':eid,
                'to_version':db['literature'][eid].get('adopted_version'),'type':'cites',
                'statement':f'{sid}采用版本参考列表列出{eid}', 'evidence':{'occurrence_id':rid,'pages':ref['pages'],
                'source':'adopted_pdf_reference_list','obtained_at':occ['extracted_at']},
                'citation_status':'reference_list_verified','identity_status':status,
                'use':None,'use_status':'unreviewed','state':'effective'}
        rec.update(payload.get('metadata',{}));rec['reference_count']=len(refs)
        rec['reference_review']=dict(review);rec['reference_legacy_reuse']=payload.get('legacy_reuse')
        text=reference_md(rec,occurrences)
        rec.setdefault('artifacts',{})['reference']=put_artifact(config,sid,'reference',text,fingerprint(rec,'reference'),rec.get('artifacts',{}).get('reference'),rec['title'])
    if mode in ('new','reconstruct') and (force or not reuse_card):
        if not all(review.get(k) for k in ('full_text_read','key_figures_checked','classification_reviewed')):raise ValueError('full text/figures/classification review missing')
        cl=payload['classification'];sections=payload['card_sections']
        if cl['code'] not in CLASS or cl['path']!=CLASS[cl['code']] or not cl.get('reason') or not cl.get('evidence'):raise ValueError('classification path/evidence invalid')
        if len(sections)!=7 or not all(sections) or any('团队补充' in x for x in sections):raise ValueError('card must have sections2..8 and no team section')
        rec['classification']=cl;rec['classification_version']=VERSIONS['classification'];rec['tags']=cl.get('tags',[])
        rec['card_review']=dict(review)
        rec['card_sections']=sections
        text=card_md(rec,sections)
        rec['artifacts']['card']=put_artifact(config,sid,'card',text,fingerprint(rec,'card'),rec['artifacts'].get('card'),rec['title'])
    elif mode=='references-only' and rec.get('card_sections') and artifact_ok(rec.get('artifacts',{}).get('card')):
        # Keep reviewed body; refresh the reference entry in the generated identity section.
        text=card_md(rec,rec['card_sections'])
        rec['artifacts']['card']=put_artifact(config,sid,'card',text,fingerprint(rec,'card'),rec['artifacts'].get('card'),rec['title'])
    rec['migration_status']='local_reconstructed' if mode!='original-only' else rec.get('migration_status','new_pending')
    requested=b.get('save_target','local')
    if requested=='ima':
        for kind,a in rec.get('artifacts',{}).items():
            if a.get('save_status')!='saved_verified':a['save_status']='save_pending'
    b['papers'][sid]={'status':'local_verified','mode':mode,'source_fingerprint':fp,'payload_sha256':ph,
        'artifacts':rec.get('artifacts',{}),'save_status':'save_pending' if requested=='ima' else 'save_not_requested','completed_at':now(),
        'save_target':requested,'executed_steps':(['reference_structure'] if mode!='original-only' and (force or not reuse_reference) else [])+(['reading_classification_card'] if mode in ('new','reconstruct') and (force or not reuse_card) else []),
        'unresolved':['外部身份未全部匹配','期刊分区待查','引用用途未全面核验','代表产物尚未同步ima']}
    searchkey=sid+'@'+payload['version_id']
    db['searches'].setdefault(searchkey,{'id':searchkey,'seed_id':sid,'seed_version':payload['version_id'],
        'source':None,'query_at':None,'conditions':None,'index_status':'not_run','pagination_complete':None,
        'hits':None,'candidates':[],'failure_reason':None,'status':'not_run'})
    return {'id':sid,'status':'local_verified','reference_count':rec.get('reference_count'),'artifacts':rec.get('artifacts',{})}

def card_md(r,sections):
    o=r['original'];kw='; '.join(r.get('author_keywords',[])) or '原文未报告'
    head=f"# {r['id']} {r.get('title_zh',r['title'])}\n\n## 1. 身份与来源\n\n"
    fields=[('英文题名',r['title']),('作者','; '.join(r.get('authors',[]))),('年份／来源',f"{r.get('year')}；{r.get('source')}"),
        ('发表日期',r.get('publication_date','待核验')),('DOI',r.get('doi') or '未报告／待核验'),('文献类型',r.get('type')),
        ('采用版本',r['adopted_version']),('原文文件',o.get('file_name') or Path(o.get('local_path','')).name),('ima原文media_id',o.get('media_id','未保存')),
        ('PDF SHA256',o['sha256']),('作者关键词原文',kw),('参考清单',Path(r['artifacts']['reference']['path']).name),
        ('ima参考清单media_id',r['artifacts']['reference'].get('media_id','保存后按文件名及团队生效入口定位')),
        ('模板／schema／修订',f"{VERSIONS['card']}／{VERSIONS['schema']}／{now()[:10]}"),
        ('中科院分区',json.dumps(r.get('journal_rank',{}).get('cas',{'status':'pending','year':None,'source':None}),ensure_ascii=False)),
        ('JCR分区',json.dumps(r.get('journal_rank',{}).get('jcr',{'status':'pending','categories':[]}),ensure_ascii=False))]
    head+='\n'.join(f'- {k}：{v}' for k,v in fields)+'\n'
    return head+'\n'.join(f'\n## {i+2}. {h}\n\n{s}\n' for i,(h,s) in enumerate(zip(HEADINGS,sections)))

def reference_md(r,occs):
    o=r['original'];text=f"# {r['id']} 新版参考文献清单\n\n"
    for k,v in [('来源作品',r['id']),('采用版本',r['adopted_version']),('英文题名',r['title']),
        ('原文文件',o.get('file_name') or Path(o.get('local_path','')).name),('ima原文media_id',o.get('media_id','未保存')),('PDF SHA256',o['sha256']),
        ('模板／schema',VERSIONS['reference']+'／'+VERSIONS['schema']),('提取／修订',now()[:10]),
        ('条目数',len(occs)),('旧数据复用','已核对PDF版本与SHA256；完整恢复备份由执行者本地保留' if r.get('reference_legacy_reuse') else '从采用原文首次提取'),
        ('共享记录','ima“文献目录与索引”；“知识库更新状态”中的团队入口按parent链核验生效版本')]:text+=f'- {k}：{v}\n'
    text+='\n全部来源条目已对照原文；外部DOI／完整题录匹配状态逐条列出。以下原编号与整理顺序分开。生成时本地核验，保存状态以生效manifest和回执为准。\n'
    for x in occs:
        ids=x.get('identifiers',{})
        text+=f"\n## {x['order']}. {x['id']}\n\n- 原编号：{x['number'] if x['number'] is not None else '无印刷编号（作者年份制）'}\n- 整理顺序：{x['order']}\n- 原始题录：{x['raw']}\n- PDF页：{', '.join(map(str,x['pages']))}\n- 作品ID：{x['entity_id']}\n- 类型：{x['type']}\n- 身份状态：{x['identity_status']}\n- 核验来源：{x['identity_evidence']}\n- DOI：{ids.get('doi') or '未匹配'}（{ids.get('doi_status','not_matched')}）\n- 其他标识：{ids.get('other') or '未匹配；原始条目中的入口仍完整保留'}\n"
        if x.get('correction'):text+='- 提取修正：'+x['correction']+'\n'
    return text

def validate(db):
    errors=[];warnings=[]
    for sid,r in db['literature'].items():
        for kind,a in r.get('artifacts',{}).items():
            if not artifact_ok(a):
                if a.get('local_status')=='not_downloaded':warnings.append(sid+':'+kind+' shared locator only; content unavailable locally')
                else:errors.append(sid+':'+kind+' hash/file invalid')
            elif kind=='card' and len(re.findall(r'^## [1-8]\. ',Path(a['path']).read_text(encoding='utf-8'),re.M))!=8:
                errors.append(sid+':card must have exactly eight sections')
        active=[x for x in db['occurrences'].values() if x['source_id']==sid and x['state']=='effective']
        if r.get('reference_count') is not None and len(active)!=r['reference_count']:errors.append(sid+':reference count differs')
    for oid,x in db['occurrences'].items():
        if x['source_id'] not in db['literature'] or x['entity_id'] not in db['literature']:errors.append(oid+':missing endpoint')
        if not x.get('pages') or (not x.get('raw') and not (x.get('raw_sha256') and x.get('raw_state')=='withheld_use_source_or_verified_reference')):errors.append(oid+':missing provenance')
        elif not x.get('raw'):warnings.append(oid+':raw withheld; control provenance only')
        if x['source_id'] in db['literature']:
            cap=db['literature'][x['source_id']].get('original',{}).get('page_count')
            if cap and any(pg<1 or pg>cap for pg in x['pages']):errors.append(oid+':invalid page')
    for rid,x in db['relations'].items():
        if x['from'] not in db['literature'] or x['to'] not in db['literature']:errors.append(rid+':missing endpoint')
        if x['evidence']['occurrence_id'] not in db['occurrences']:errors.append(rid+':missing occurrence')
    keys=[('rawhash:'+sha(r['identity_key'][4:].encode('utf-8'))) if r['identity_key'].startswith('raw:') else r['identity_key'] for r in db['literature'].values() if r.get('identity_key')]
    if len(keys)!=len(set(keys)):errors.append('duplicate identity keys')
    for x in db['searches'].values():
        if x['status']=='not_run' and (x['hits'] is not None or x['query_at'] is not None):errors.append(x['id']+':unsearched falsely counted')
    return {'status':'passed' if not errors else 'failed','errors':errors,'warnings':warnings,
            'counts':{k:len(db[k]) for k in ('literature','occurrences','relations','searches','batches')}}

def export(config,db,bid):
    check=validate(db)
    if check['errors']:raise ValueError('export validation failed: '+str(check['errors']))
    if any(not o.get('raw') for o in db['occurrences'].values()):raise ValueError('control state lacks full reference raw; use team publish for control status, restore reviewed raw before full export')
    snapshot=jsha({k:db[k] for k in ('literature','occurrences','relations','searches','batches')})[:12]
    dest=Path(config['output_root'])/'shared'/snapshot;dest.mkdir(parents=True,exist_ok=True)
    artifacts=[]
    titles={'literature':'文献目录','occurrences':'参考条目映射','relations':'引用关系记录','searches':'检索记录','batches':'批次与版本记录'}
    for kind,title in titles.items():
        content=f'# {title}\n\n数据版本：{snapshot}；schema {VERSIONS["schema"]}；批次 {bid}。\n\n本快照由同源JSON生成，原文／卡片／参考清单状态分别记录；共享生效以manifest为准，生成日期最新不自动生效。legacy为旧模板待迁移，未检索不是零。\n\n'
        data=db[kind] if kind!='literature' else {k:{x:v for x,v in r.items() if x!='card_sections'} for k,r in db[kind].items()}
        content+='```json\n'+json.dumps(data,ensure_ascii=False,indent=2)+'\n```\n'
        p=dest/f'{title}_{bid}_{snapshot}.md';p.write_text(content,encoding='utf-8')
        artifacts.append({'kind':kind,'path':str(p),'sha256':sha(p.read_bytes())})
    active=[r for r in db['relations'].values() if r.get('state')=='effective']
    verified=[r for r in active if r['identity_status']=='verified' and r['citation_status']=='reference_list_verified']
    endpoints=set([x for r in active for x in (r['from'],r['to'])])
    graph={'data_version':snapshot,'schema':VERSIONS['schema'],
           'nodes':[{'id':k,'title':db['literature'][k].get('title') or db['literature'][k].get('display_label') or k,'roles':db['literature'][k]['roles']} for k in sorted(endpoints)],
           'verified_edges':verified,'candidate_edges':[r for r in active if r not in verified]}
    write(dest/'graph.json',graph)
    manifest={'batch':bid,'data_version':snapshot,'state':'local_candidate','artifacts':artifacts,
              'graph':str(dest/'graph.json'),'created_at':now(),'versions':VERSIONS.copy()}
    write(dest/'manifest.json',manifest)
    return manifest

def record_save(config,db,sid,kind,receipt):
    rec=load(receipt)
    if rec.get('status') not in ('uploaded_verified','reused_verified','recovered_verified'):raise ValueError('unverified save receipt')
    r=db['literature'][sid]
    if kind=='original':
        target=r['original'];expected=target['sha256'];folder=config['folders']['成果原文']
    else:
        target=r['artifacts'][kind];expected=target['sha256']
        folder=config['folders']['参考文献清单' if kind=='reference' else '原文笔记卡片/'+r['classification']['path']]
    if rec['sha256']!=expected or rec['folder_id']!=folder or rec['knowledge_base_id']!=config['knowledge_base_id']:raise ValueError('receipt hash/destination differs')
    if target.get('media_id') and target['media_id']!=rec['media_id']:target['supersedes_media_id']=target['media_id']
    target.update(media_id=rec['media_id'],folder_id=rec['folder_id'],file_name=Path(rec['file']).name,
                  save_status='saved_verified',receipt=str(Path(receipt).resolve()),verified_at=rec['verified_at'])
    if kind!='original':target['availability']='remote_verified'
    target['platform_parsing']='not_verified'
    if kind=='original':target['remote_hash_status']='matched'
    else:
        legacy=r.get('legacy',{})
        if isinstance(legacy.get(kind),dict) and legacy[kind].get('media_id')!=rec['media_id']:
            legacy[kind+'_status']='superseded_preserved'
            legacy[kind+'_replacement_media_id']=rec['media_id']
            target.setdefault('supersedes_media_id',legacy[kind]['media_id'])
    bid=db.get('last_batch');b=db['batches'].get(bid,{})
    if sid in b.get('papers',{}):
        b['papers'][sid].setdefault('save_results',{})[kind]={'status':'saved_verified','receipt':str(Path(receipt).resolve()),'media_id':rec['media_id']}
        b['papers'][sid]['artifacts']=r.get('artifacts',{})
        required=[] if b.get('mode')=='original-only' else ['reference'] if b.get('mode')=='references-only' else ['card','reference']
        complete=r['original'].get('save_status')=='saved_verified' and all(r.get('artifacts',{}).get(k,{}).get('save_status')=='saved_verified' for k in required)
        b['papers'][sid]['save_status']='saved_verified' if complete else 'save_pending'
        if complete:
            b['papers'][sid]['unresolved']=[x for x in b['papers'][sid].get('unresolved',[]) if x!='代表产物尚未同步ima']
            r['migration_status']='saved_reconstructed' if b.get('mode')!='original-only' else r.get('migration_status','new_pending')
    return {'id':sid,'kind':kind,'status':'saved_verified'}

def refresh_card_links(config,db,sid):
    r=db['literature'][sid];old=r.get('artifacts',{}).get('card')
    if not r.get('card_sections') or not artifact_ok(old):raise ValueError('reviewed card body/hash unavailable')
    ref=r['artifacts'].get('reference')
    if not artifact_ok(ref):raise ValueError('verified reference artifact unavailable')
    new=put_artifact(config,sid,'card',card_md(r,r['card_sections']),fingerprint(r,'card'),old,r['title'])
    if new is old:return {'id':sid,'status':'reused_valid','artifact':old}
    r['artifacts']['card']=new
    b=db['batches'].get(db.get('last_batch'),{})
    if sid in b.get('papers',{}):
        p=b['papers'][sid];p['artifacts']=r['artifacts']
        if b.get('save_target')=='ima':new['save_status']='save_pending';p['save_status']='save_pending'
        p.setdefault('executed_steps',[]).append('card_reference_locator_refresh')
    return {'id':sid,'status':'local_verified','artifact':new}

def activate(config,db,manifestpath):
    m=load(manifestpath)
    if {x['kind'] for x in m['artifacts']}!=set(('literature','occurrences','relations','searches','batches')):raise ValueError('five shared snapshots required')
    for a in m['artifacts']:
        r=load(a['receipt'])
        if r.get('status') not in ('uploaded_verified','reused_verified','recovered_verified') or r['sha256']!=a['sha256'] or sha(Path(a['path']).read_bytes())!=a['sha256']:raise ValueError('shared receipt/hash mismatch')
        expected=config['folders']['引用关系与可视化' if a['kind']=='relations' else '知识库更新状态' if a['kind']=='batches' else '文献目录与索引']
        if r['knowledge_base_id']!=config['knowledge_base_id'] or r['folder_id']!=expected:raise ValueError('shared destination mismatch')
        a['media_id']=r['media_id']
    m.update(state='effective_shared',effective_at=now())
    if Path(config['effective_manifest']).exists():m['supersedes']=load(config['effective_manifest']).get('data_version')
    write(config['effective_manifest'],m)
    db.setdefault('shared_publications',{})[m['data_version']]={'manifest':config['effective_manifest'],'effective_at':m['effective_at'],'state':'effective_shared'}
    return {'status':'effective_shared','data_version':m['data_version'],'manifest':config['effective_manifest']}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project')
    sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('plan');p.add_argument('--batch');p.add_argument('--scope');p.add_argument('--mode',choices=['reconstruct','references-only','new','original-only'],default='reconstruct');p.add_argument('--save-target',choices=['local','ima'],default='local');p.add_argument('--resume',action='store_true');p.add_argument('--dry-run',action='store_true')
    p=sub.add_parser('register');p.add_argument('--input',required=True)
    p=sub.add_parser('commit');p.add_argument('--batch',required=True);p.add_argument('--input',required=True);p.add_argument('--force',action='store_true',help='reviewed regeneration requested or implementation repair')
    sub.add_parser('validate')
    p=sub.add_parser('export');p.add_argument('--batch',required=True)
    p=sub.add_parser('record-save');p.add_argument('--id',required=True);p.add_argument('--kind',choices=['original','card','reference'],required=True);p.add_argument('--receipt',required=True)
    p=sub.add_parser('refresh-card-links');p.add_argument('--id',required=True)
    p=sub.add_parser('activate');p.add_argument('--manifest',required=True)
    p=sub.add_parser('fail');p.add_argument('--batch',required=True);p.add_argument('--id',required=True);p.add_argument('--step',required=True);p.add_argument('--reason',required=True)
    args=ap.parse_args()
    try:
        project_path=find_project(args.project);config=load(project_path);state=Path(config['state_file'])
        with locked(state):
            db=load(state)
            before=jsha(db)
            mutating=args.command not in ('validate','export') and not (args.command=='plan' and args.dry_run)
            if mutating:
                import team_sync
                team_sync.local_guard(config,allocating=args.command in ('register','commit'))
            if args.command=='activate' and config.get('team_sync',{}).get('enabled'):
                raise ValueError('team-managed project: publish the team head with verified artifact release; do not bypass shared version check')
            if args.command=='plan':result=plan(db,args)
            elif args.command=='register':result=register(db,load(args.input))
            elif args.command=='commit':result=commit(config,db,args.batch,load(args.input),args.force)
            elif args.command=='validate':result=validate(db)
            elif args.command=='export':result=export(config,db,args.batch)
            elif args.command=='record-save':result=record_save(config,db,args.id,args.kind,args.receipt)
            elif args.command=='refresh-card-links':result=refresh_card_links(config,db,args.id)
            elif args.command=='activate':result=activate(config,db,args.manifest)
            else:
                if args.id not in db['batches'][args.batch]['scope']:raise ValueError('failed item outside scope')
                db['batches'][args.batch]['papers'].setdefault(args.id,{})['failure']={'step':args.step,'reason':args.reason,'recorded_at':now()}
                result={'id':args.id,'status':'failed','step':args.step}
            if mutating and jsha(db)!=before:
                team_sync.mark_pending(config,db)
                db['updated_at']=now();write(state,db)
        print(json.dumps(result,ensure_ascii=False))
        if args.command=='export':
            config['working_manifest']=str(Path(result['graph']).parent/'manifest.json');write(project_path,config)
        return 0 if result.get('status')!='failed' else 1
    except Exception as exc:
        print(json.dumps({'status':'failed','reason':str(exc)},ensure_ascii=False));return 1

if __name__=='__main__':sys.exit(main())
