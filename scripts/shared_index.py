"""Publish an index-only manifest when full artifacts/records were not authorized."""
import argparse,json
from pathlib import Path
import library as lib

def build_team(config,db,batch,dest):
    """Public metadata index, independent of withheld full records/cards/raw."""
    import team_sync
    control=team_sync.control(config,db);team_sync.validate_control(control)
    version=lib.jsha(control)[:16];dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    scope=db['batches'][batch]['scope']
    text=f'# 论文库共享索引\n\n批次：{batch}；本次成果范围：{", ".join(scope)}；元数据版本：{version}。\n\n本索引展示身份、分类与真实对象状态，不含卡片正文或完整参考raw。已保存成果逐项列media_id，owner_local_only保留为执行者本地；团队生效以知识库更新状态中的唯一连续入口链为准。\n\n'
    text+='| ID | 题名 | 主分类 | 原文media_id | 新卡media_id／状态 | 新参考media_id／状态 | 迁移状态 |\n| --- | --- | --- | --- | --- | --- | --- |\n'
    for sid,r in sorted(control['literature'].items()):
        if not sid.startswith('S'):continue
        def object_label(kind):
            a=r['artifacts'].get(kind,{})
            return (a.get('media_id') or a.get('availability') or '待重构')+' / '+a.get('save_status','not_requested')
        title=(r.get('title') or sid).replace('|','\\|').replace('\n',' ')
        text+=f'| {sid} | {title} | {(r.get("classification") or {}).get("path","待内容重分类")} | {r.get("original",{}).get("media_id","未保存")} | {object_label("card")} | {object_label("reference")} | {r.get("migration_status","pending")} |\n'
    text+=f'\n外部身份：{sum(k.startswith("E") for k in control["literature"])}；来源映射：{len(control["occurrences"])}；引用关系：{len(control["relations"])}。未匹配身份和用途待核验独立保留；未执行施引不是零。\n\n'
    text+='## 本次来源映射\n\n| 出现ID | 原编号／顺序 | PDF页 | 作品ID | 身份状态 |\n| --- | --- | --- | --- | --- |\n'
    for oid,o in sorted(control['occurrences'].items()):
        if o['source_id'] in scope and o['state']=='effective':text+=f'| {oid} | {o.get("number")} / {o["order"]} | {o["pages"]} | {o["entity_id"]} | {o.get("identity_status","unresolved")} |\n'
    p=dest/f'论文库共享索引_{batch}_{version}.md';p.write_bytes(text.encode('utf-8'))
    m={'data_version':version,'batch':batch,'scope':scope,'state':'local_index_candidate',
       'index':{'path':str(p),'sha256':lib.sha(p.read_bytes()),'receipt':str(dest/'index-receipt.json')}}
    mp=dest/'index-manifest.json';lib.write(mp,m);return {'path':str(p),'manifest':str(mp),'sha256':m['index']['sha256']}

def build(config,db,local_manifest):
    m=lib.load(local_manifest);version=m['data_version'];dest=Path(local_manifest).parent
    text=f'# 论文库基础索引\n\n批次 {m["batch"]}；数据版本 {version}；schema {lib.VERSIONS["schema"]}。\n\n共享范围：身份、对象及迁移状态索引。代表卡片、新版逐篇参考清单、五类完整记录仅本地核验，未上传。旧ima成果保留，原文不重复上传；共享生效由manifest明确。\n\n'
    text+='## 组内成果及实时对象\n\n| ID | 题名 | 原文media_id | 原文回读 | 旧卡／参考 | 新主类 | 本地迁移 |\n| --- | --- | --- | --- | --- | --- | --- |\n'
    for sid,r in sorted(db['literature'].items()):
        if not sid.startswith('S'):continue
        old=r.get('legacy',{});cl=r.get('classification') or {}
        text+=f"| {sid} | {r['title']} | {r['original'].get('media_id','未保存')} | {r['original'].get('remote_hash_status','未核验')} | {old.get('card_status','无')}／{old.get('reference_status','无')} | {cl.get('path','未重新分类')} | {r.get('migration_status','pending')} |\n"
    active=[r for r in db['relations'].values() if r['state']=='effective']
    verified=[r for r in active if r['identity_status']=='verified']
    eids=sorted(k for k in db['literature'] if k.startswith('E'))
    text+=f'\n## 外部身份与出处基础\n\n已登记{len(eids)}个E占位身份（{eids[0] if eids else "无"}至{eids[-1] if eids else "无"}），{len(db["occurrences"])}个来源出现、{len(active)}条引用记录。来源参考列表已核验，外部题录身份未全部匹配；完整raw与页码保存在本地同源记录。端点身份已核验的原参考边{len(verified)}条，其余候选{len(active)-len(verified)}条；用途未全面核验。施引查询未执行，hits=null。\n\n'
    text+='## 基础设施与本地完整记录\n\n- 项目处理数据：'+config['state_file']+'\n- 生效manifest：'+config['effective_manifest']+'\n- 本地快照manifest：'+str(local_manifest)+'\n'
    for a in m['artifacts']:text+=f"- {a['kind']}（本地）：{a['path']}；SHA256 {a['sha256']}\n"
    text+='- 图数据（本地，不表示ima交互实现）：'+m['graph']+'\n\n日期最新不自动生效；原文／卡／参考／索引分别判断，legacy条目仍待按用户范围重构。其余S题录来源历史记录，未阅读全文重分类。\n'
    p=dest/f'论文库基础索引_{m["batch"]}_{version}.md';p.write_bytes(text.encode('utf-8'))
    m['index']={'path':str(p),'sha256':lib.sha(p.read_bytes())};lib.write(local_manifest,m)
    return m['index']

def publish(config,db,manifest):
    if config.get('team_sync',{}).get('enabled'):raise ValueError('team-managed project: use team publish; legacy index publish cannot bypass the shared version check')
    m=lib.load(manifest);a=m['index'];r=lib.load(a['receipt'])
    if r.get('status') not in ('uploaded_verified','reused_verified','recovered_verified') or r['sha256']!=a['sha256'] or lib.sha(Path(a['path']).read_bytes())!=a['sha256']:
        raise ValueError('index receipt/hash mismatch')
    if r['knowledge_base_id']!=config['knowledge_base_id'] or r['folder_id']!=config['folders']['文献目录与索引']:raise ValueError('index destination mismatch')
    if m.get('entry'):
        e=m['entry'];er=lib.load(e['receipt'])
        if er.get('status') not in ('uploaded_verified','reused_verified','recovered_verified') or er['sha256']!=e['sha256'] or lib.sha(Path(e['path']).read_bytes())!=e['sha256']:
            raise ValueError('entry receipt/hash mismatch')
        if er['knowledge_base_id']!=config['knowledge_base_id'] or er['folder_id']!=config['folders']['知识库更新状态']:raise ValueError('entry destination mismatch')
        e['media_id']=er['media_id']
    a['media_id']=r['media_id'];m.update(state='effective_shared_index_only',effective_at=lib.now(),records_state='local_verified_not_shared',representative_artifacts_state='local_verified_not_shared')
    if Path(config['effective_manifest']).exists():m['supersedes']=lib.load(config['effective_manifest']).get('data_version')
    lib.write(config['effective_manifest'],m)
    db.setdefault('shared_publications',{})[m['data_version']]={'state':m['state'],'effective_at':m['effective_at'],'manifest':config['effective_manifest']}
    return {'status':m['state'],'data_version':m['data_version'],'media_id':a['media_id']}

def build_entry(config,manifest):
    m=lib.load(manifest);r=lib.load(m['index']['receipt'])
    if r['sha256']!=m['index']['sha256'] or r['status'] not in ('uploaded_verified','reused_verified','recovered_verified'):raise ValueError('verify index before entry')
    previous=lib.load(config['effective_manifest']).get('data_version') if Path(config['effective_manifest']).exists() else None
    data={'state':'index_verified','effective_data_version':m['data_version'],'batch':m['batch'],
        'scope':'shared_baseline_index_only','knowledge_base_id':config['knowledge_base_id'],
        'index':{'file_name':Path(m['index']['path']).name,'media_id':r['media_id'],'sha256':r['sha256'],'folder_id':r['folder_id'],'verified_at':r['verified_at']},
        'versions':m['versions'],'supersedes':previous,'records_state':'local_verified_not_shared',
        'representative_card_reference_state':'local_verified_not_shared','local_manifest':str(manifest),
        'project_state':config['state_file'],'unresolved':['remaining group artifacts pending migration','external identity/ranks/use evidence incomplete','ima platform parsing not verified']}
    text='# 论文库生效入口\n\n本入口指定以下已回读核验的基础索引为本批共享版本。完整五类记录、代表卡片和新版逐篇清单仍仅本地；旧成果没有删除或覆盖。入口自身保存核验后，以项目effective_manifest中的receipt回查。日期最新不自动生效。\n\n```json\n'+json.dumps(data,ensure_ascii=False,indent=2)+'\n```\n'
    p=Path(manifest).parent/f'论文库生效入口_{m["batch"]}_{m["data_version"]}.md';p.write_bytes(text.encode('utf-8'))
    m['entry']={'path':str(p),'sha256':lib.sha(p.read_bytes())};lib.write(manifest,m);return m['entry']

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project',required=True);ap.add_argument('--manifest');ap.add_argument('--batch');ap.add_argument('--output');ap.add_argument('action',choices=['build','build-entry','publish','build-team']);args=ap.parse_args()
    c=lib.load(args.project)
    with lib.locked(c['state_file']):
        db=lib.load(c['state_file'])
        if args.action=='build-team':
            if not args.batch or not args.output:raise ValueError('build-team requires --batch and --output')
            result=build_team(c,db,args.batch,args.output)
        else:
            if not args.manifest:raise ValueError('legacy action requires --manifest')
            result=build(c,db,args.manifest) if args.action=='build' else build_entry(c,args.manifest) if args.action=='build-entry' else publish(c,db,args.manifest)
        if args.action=='publish':lib.write(c['state_file'],db)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
