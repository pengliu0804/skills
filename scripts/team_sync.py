"""Portable control state, append-only ima heads and serial writer handoff.

The shared state deliberately excludes card bodies and complete citation raw text.
ima has no tested compare-and-swap: branch detection is not a distributed lock.
"""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import library as lib

PROTOCOL = 'paper-library-team/1'
PREFIX = '论文库团队生效入口_'
STATE_PREFIX = '论文库共享状态_'
OK = ('uploaded_verified', 'reused_verified', 'recovered_verified')
LOCATOR = Path(__file__).resolve().parent.parent / 'references' / 'project-locator.json'


def select(data, keys):
    return {k: copy.deepcopy(data[k]) for k in keys if k in data}


def key_hash(key):
    if key and key.startswith('raw:'):
        return 'rawhash:' + lib.sha(key[4:].encode('utf-8'))
    return key


def artifact(a, owner, kind, config, rec):
    out = select(a, ('sha256', 'source_fingerprint', 'status', 'save_status',
                     'created_at', 'media_id', 'verified_at', 'platform_parsing', 'supersedes_media_id'))
    out['file_name'] = a.get('file_name') or Path(a.get('path', kind + '.md')).name
    folder = '参考文献清单' if kind == 'reference' else '原文笔记卡片/' + (rec.get('classification') or {}).get('path', '待确认')
    out['folder_id'] = a.get('folder_id') or config['folders'].get(folder)
    out['owner_id'] = a.get('owner_id', owner)
    out['availability'] = ('remote_verified' if out.get('media_id') and out.get('save_status') == 'saved_verified'
                           else a.get('availability', 'owner_local_only'))
    return out


def control(config, db):
    """Allowlisted identity/provenance/status projection; no machine paths/bodies."""
    owner = config.get('team_sync', {}).get('member_id', 'maintainer-local')
    out = {'schema': db['schema'], 'versions': lib.VERSIONS.copy(),
           'last_batch': db.get('last_batch'), 'literature': {}, 'occurrences': {},
           'relations': {}, 'searches': {}, 'batches': {}}
    for sid, r in db['literature'].items():
        x = select(r, ('id', 'roles', 'title', 'title_zh', 'title_status', 'authors', 'year',
                       'source', 'doi', 'doi_status', 'type', 'adopted_version', 'versions',
                       'identity_status', 'year_candidates', 'bibliographic_fields_status',
                       'migration_status', 'classification', 'classification_version',
                       'tags', 'journal_rank', 'citation_metrics', 'attention_status',
                       'reference_count', 'registered_at', 'full_text_status'))
        if r.get('identity_key'): x['identity_key'] = key_hash(r['identity_key'])
        if r.get('original'):
            o = r['original']
            x['original'] = select(o, ('sha256', 'media_id', 'page_count', 'save_status',
                                       'remote_hash_status', 'verified_at', 'platform_parsing', 'folder_path'))
            x['original']['file_name'] = o.get('file_name') or Path(o.get('local_path', sid + '.pdf')).name
            x['original']['folder_id'] = config['folders'].get('成果原文')
        x['artifacts'] = {k: artifact(a, owner, k, config, r) for k, a in r.get('artifacts', {}).items()}
        if r.get('legacy'):
            x['legacy'] = {k: select(v, ('media_id', 'title', 'parent_folder_id', 'media_type', 'folder_path'))
                           if isinstance(v, dict) else v for k, v in r['legacy'].items()}
        out['literature'][sid] = x
    for oid, o in db['occurrences'].items():
        x = select(o, ('id', 'source_id', 'source_version', 'number', 'order', 'pages', 'entity_id',
                       'type', 'identity_status', 'source_status', 'state', 'extracted_at', 'identifiers'))
        x['raw_sha256'] = lib.sha(o['raw'].encode('utf-8')) if o.get('raw') else o.get('raw_sha256')
        x['raw_state'] = 'withheld_use_source_or_verified_reference'
        out['occurrences'][oid] = x
    for rid, r in db['relations'].items():
        out['relations'][rid] = select(r, ('id', 'from', 'from_version', 'to', 'to_version', 'type',
                                          'evidence', 'citation_status', 'identity_status', 'use_status', 'state'))
        out['relations'][rid]['use'] = None
    for qid, q in db['searches'].items():
        out['searches'][qid] = select(q, ('id', 'seed_id', 'seed_version', 'source', 'query_at',
                                         'conditions', 'index_status', 'pagination_complete', 'hits', 'status'))
    for bid, b in db['batches'].items():
        x = select(b, ('id', 'scope', 'mode', 'save_target', 'created_at', 'versions', 'next'))
        x['papers'] = {}
        for sid, p in b.get('papers', {}).items():
            x['papers'][sid] = select(p, ('status', 'mode', 'source_fingerprint', 'payload_sha256',
                                         'save_status', 'completed_at', 'save_target', 'executed_steps', 'unresolved'))
            if p.get('failure'):
                # Free-text errors may contain machine paths or provider secrets.
                x['papers'][sid]['failure'] = select(p['failure'], ('step', 'recorded_at'))
                x['papers'][sid]['failure']['reason_state'] = 'owner_local_details'
        x['shared_state'] = 'control_state_only'
        out['batches'][bid] = x
    return out


def validate_control(db):
    ids = set(db['literature']); keys = [key_hash(r['identity_key']) for r in db['literature'].values() if r.get('identity_key')]
    if len(keys) != len(set(keys)): raise ValueError('shared duplicate identity keys')
    for oid, o in db['occurrences'].items():
        if o['source_id'] not in ids or o['entity_id'] not in ids or not o.get('pages'):
            raise ValueError('shared occurrence endpoint/provenance missing: ' + oid)
        if not re.fullmatch(r'[0-9a-f]{64}', o.get('raw_sha256') or ''): raise ValueError('shared raw hash missing: ' + oid)
    for sid, r in db['literature'].items():
        active = [o for o in db['occurrences'].values() if o['source_id'] == sid and o.get('state') == 'effective']
        if r.get('reference_count') is not None and len(active) != r['reference_count']: raise ValueError('shared reference count differs: ' + sid)
    for rid, r in db['relations'].items():
        if r['from'] not in ids or r['to'] not in ids or r['evidence']['occurrence_id'] not in db['occurrences']:
            raise ValueError('shared relation endpoint/provenance missing: ' + rid)


def encode(title, data):
    return ('# ' + title + '\n\n```json\n' + json.dumps(data, ensure_ascii=False, indent=2) + '\n```\n').encode('utf-8')


def decode(data):
    text = data.decode('utf-8-sig')
    blocks = re.findall(r'^```json\s*\n(.*?)\n```', text, re.M | re.S)
    if len(blocks) != 1: raise ValueError('exactly one JSON block required')
    return json.loads(blocks[0])


def filename(name):
    if not name or name in ('.', '..') or re.search(r'[\\/:<>?*|\x00]', name):
        raise ValueError('unsafe shared file name')
    return name


def locator(op, config=None):
    loc = lib.load(op.get('locator', LOCATOR))
    if config:
        loc.update(project=config['project'], knowledge_base_id=config['knowledge_base_id'],
                   status_folder_id=config['folders']['知识库更新状态'])
    return loc


def read_head(ima, loc):
    nodes = {}
    for item in ima.listing(loc['knowledge_base_id'], loc['status_folder_id']):
        if not item.get('title', '').startswith(PREFIX): continue
        data = ima.download(item['media_id']); h = decode(data)
        if h.get('protocol') != PROTOCOL or h.get('project') != loc['project'] or h.get('knowledge_base_id') != loc['knowledge_base_id']:
            raise RuntimeError('invalid/foreign team head; reconcile instead of guessing')
        if not isinstance(h.get('revision'), int) or h['revision'] < 1: raise RuntimeError('invalid head revision')
        if not h.get('writer_id') or not h.get('state_object'): raise RuntimeError('incomplete head')
        if not re.fullmatch(r'[0-9a-f]{16}', h.get('data_version', '')) or item['title'] != PREFIX + f'r{h["revision"]:06d}_' + h['data_version'] + '.md':
            raise RuntimeError('head file name/data version differs')
        h.update(media_id=item['media_id'], sha256=lib.sha(data), file_name=item['title'])
        nodes[h['media_id']] = h
    if not nodes: return None
    roots = [h for h in nodes.values() if not h.get('parent')]
    if len(roots) != 1 or roots[0]['revision'] != 1: raise RuntimeError('team head fork/invalid root; stop shared writes')
    cur = roots[0]; visited = {cur['media_id']}
    while True:
        children = [h for h in nodes.values() if (h.get('parent') or {}).get('media_id') == cur['media_id']]
        if len(children) > 1: raise RuntimeError('team head fork; stop shared writes, reconcile both branches')
        if not children: break
        child = children[0]
        if child['parent']['sha256'] != cur['sha256'] or child['revision'] != cur['revision'] + 1:
            raise RuntimeError('team head chain mismatch')
        cur = child; visited.add(cur['media_id'])
    if len(visited) != len(nodes): raise RuntimeError('orphan team head; stop shared writes')
    return cur


def head_ref(h):
    return select(h, ('media_id', 'sha256', 'revision', 'data_version', 'writer_id')) if h else None


def same_head(a, b):
    return head_ref(a) == head_ref(b)


def fetch_state(ima, loc, head):
    obj = head['state_object']
    if obj['folder_id'] != loc['status_folder_id']: raise RuntimeError('state folder mismatch')
    found = [x for x in ima.listing(loc['knowledge_base_id'], obj['folder_id'])
             if x['media_id'] == obj['media_id'] and x['title'] == obj['file_name']]
    if len(found) != 1: raise RuntimeError('shared state object missing/ambiguous')
    data = ima.download(obj['media_id'])
    if lib.sha(data) != obj['sha256']: raise RuntimeError('shared state hash differs')
    state = decode(data)
    if state.get('protocol') != PROTOCOL or state.get('project') != loc['project']: raise RuntimeError('state protocol/project differs')
    if lib.jsha(state)[:16] != head['data_version']: raise RuntimeError('shared state data version differs')
    if state['project_config']['knowledge_base_id'] != loc['knowledge_base_id']: raise RuntimeError('state KB differs')
    if state['writer_id'] != head['writer_id'] or state['required_versions'] != head['required_versions']:
        raise RuntimeError('head/state writer or rule version differs')
    if state['control_state']['schema'] != lib.VERSIONS['schema']: raise RuntimeError('unsupported shared schema; update skill before init')
    validate_control(state['control_state'])
    return state


def local_guard(config, allocating=False):
    t = config.get('team_sync', {})
    if Path(config['output_root'], 'team', 'pending.json').exists():
        raise RuntimeError('publication pending; reconcile/retry publish before changing state')
    if not t.get('enabled'): return
    s = t.get('writer_session', {})
    if not s.get('active') or t.get('member_id') != (t.get('base_head') or {}).get('writer_id'):
        raise RuntimeError('read-only/no writer session; team begin or explicit handoff required')
    if allocating and not s.get('online_checked_at'): raise RuntimeError('new identities require online writer check')


def mark_pending(config, db):
    if config.get('team_sync', {}).get('enabled'):
        db['team_sync_status'] = {'state': 'pending_publish', 'recorded_at': lib.now()}


def begin(ima, config_path, op):
    c = lib.load(config_path); loc = locator(op, c); h = read_head(ima, loc)
    if not h: raise RuntimeError('no portable shared head; maintainer must publish initial state')
    t = c['team_sync']
    if not same_head(t.get('base_head'), h): raise RuntimeError('shared version changed; refresh before writing')
    if t['member_id'] != h['writer_id']: raise RuntimeError('another member owns serial writes; request explicit handoff')
    if tuple(map(int,h['required_versions']['skill'].split('.'))) > tuple(map(int,lib.VERSIONS['skill'].split('.'))): raise RuntimeError('update installed skill to required version before writing')
    t['writer_session'] = {'active': True, 'online_checked_at': lib.now(), 'base_head': head_ref(h)}
    lib.write(config_path, c)
    return {'status': 'writer_ready', 'head': head_ref(h)}


def restore(ima, op, existing=None):
    loc = locator(op, existing); h = read_head(ima, loc)
    if not h: raise RuntimeError('portable shared state not published yet')
    state = fetch_state(ima, loc, h)
    root = Path(op['root']).resolve() if not existing else Path(existing['output_root']).parent
    cp = root / 'paper-library.project.json' if not existing else Path(op['project'])
    if cp.exists() and not existing: raise RuntimeError('project exists; use refresh, never overwrite init')
    if existing:
        old = lib.load(existing['state_file'])
        if old.get('team_sync_status', {}).get('state') == 'pending_publish':
            raise RuntimeError('unpublished local changes; retain them and reconcile before refresh')
        if Path(existing['output_root'], 'team', 'pending.json').exists(): raise RuntimeError('publication pending; retry before refresh')
    output = Path(existing['output_root']) if existing else root / 'output'
    c = copy.deepcopy(existing) if existing else dict(state['project_config'])
    member = op.get('member_id') or c.get('team_sync', {}).get('member_id')
    if not member: raise ValueError('provide member_id for local ownership')
    c.update(state_file=str(output / 'state' / 'library.json'), output_root=str(output),
             effective_manifest=str(output / 'state' / 'team-effective.json'), local_pdf_root=str(output / 'originals'))
    c['team_sync'] = {'enabled': True, 'member_id': member, 'base_head': head_ref(h),
                      'writer_session': {'active': False}, 'locator': loc}
    db = copy.deepcopy(state['control_state'])
    for sid, r in db['literature'].items():
        if r.get('original'):
            r['original']['local_path'] = str(output / 'originals' / filename(r['original']['file_name']))
        for kind, a in r.get('artifacts', {}).items():
            a['path'] = str(output / ('cards' if kind == 'card' else 'references') / filename(a['file_name']))
            a['local_status'] = 'not_downloaded'
    # Keep the active writer's reviewed source text, bodies and valid local artifacts.
    if existing:
        for sid, r in db['literature'].items():
            oldr = old['literature'].get(sid, {})
            if oldr.get('original', {}).get('sha256') == r.get('original', {}).get('sha256') and oldr.get('adopted_version') == r.get('adopted_version'):
                merged = dict(oldr); merged.update(r); db['literature'][sid] = merged; r = merged
                if oldr.get('original', {}).get('local_path'):
                    r['original'] = dict(oldr['original'], **r['original']); r['original']['local_path'] = oldr['original']['local_path']
                if oldr.get('card_sections') and oldr.get('artifacts', {}).get('card', {}).get('sha256') != r.get('artifacts', {}).get('card', {}).get('sha256'):
                    r.pop('card_sections', None)
                for kind, a in r.get('artifacts', {}).items():
                    prior = oldr.get('artifacts', {}).get(kind, {})
                    if prior.get('sha256') == a.get('sha256') and lib.artifact_ok(prior):
                        a.update(path=prior['path'], local_status='local_verified')
        for oid, o in db['occurrences'].items():
            prior = old['occurrences'].get(oid, {})
            if prior.get('raw') and lib.sha(prior['raw'].encode()) == o.get('raw_sha256'): o['raw'] = prior['raw']
        backup = output / 'backups' / ('state_before_refresh_' + lib.jsha(old)[:16] + '.json')
        if not backup.exists(): lib.write(backup, old)
    db['team_sync_status'] = {'state': 'shared_control_current', 'head': head_ref(h)}
    if not same_head(read_head(ima, loc), h): raise RuntimeError('shared head changed during restore; retry refresh/init')
    lib.write(c['state_file'], db); lib.write(c['effective_manifest'], h); lib.write(cp, c)
    return {'status': 'initialized' if not existing else 'refreshed', 'project': str(cp), 'head': head_ref(h),
            'counts': {k: len(db[k]) for k in ('literature', 'occurrences', 'relations', 'searches', 'batches')},
            'content_scope': 'control_only; owner-local artifacts/raw not downloaded'}


def finish(config_path, c, db, head, state):
    c['effective_manifest'] = str(Path(c['output_root']) / 'state' / 'team-effective.json')
    t = c['team_sync']; t.update(base_head=head_ref(head), published_version=head['data_version'])
    t['writer_session'] = {'active': t['member_id'] == head['writer_id'], 'online_checked_at': lib.now()}
    c['versions'] = lib.VERSIONS.copy(); db['versions'] = lib.VERSIONS.copy()
    c['last_batch']=db.get('last_batch')
    c['pending_sync']=[sid+':'+kind for sid,r in db['literature'].items() for kind,a in r.get('artifacts',{}).items()
                       if a.get('save_status')!='saved_verified']
    db['team_sync_status'] = {'state': 'shared_control_current', 'head': head_ref(head)}
    for b in db['batches'].values(): b['shared_state'] = 'control_state_published'
    lib.write(c['effective_manifest'], head); lib.write(c['state_file'], db); lib.write(config_path, c)
    pending = Path(c['output_root']) / 'team' / 'pending.json'
    if pending.exists(): pending.unlink()
    return {'status': 'published_verified', 'head': head_ref(head), 'scope': state['scope'],
            'representative_artifacts': 'remain_owner_local_unless_separately_saved_verified'}


def artifact_release(ima, c, op, head):
    if not op.get('release_manifest'):
        if head:release=copy.deepcopy(head.get('artifact_release', {}))
        else:
            m = lib.load(c['effective_manifest']) if Path(c['effective_manifest']).exists() else {}
            release = m.get('artifact_release') or select(m, ('state', 'data_version', 'index', 'entry'))
            for kind in ('index', 'entry'):
                if kind in release: release[kind] = select(release[kind], ('media_id', 'sha256'))
        if op.get('index_manifest'):
            m=lib.load(op['index_manifest']);a=m['index'];p=Path(a['path']);r=lib.load(a['receipt'])
            folder=c['folders']['文献目录与索引']
            if r.get('status') not in OK or r['sha256']!=a['sha256'] or lib.sha(p.read_bytes())!=a['sha256']:raise ValueError('index receipt/hash differs')
            if r['knowledge_base_id']!=c['knowledge_base_id'] or r['folder_id']!=folder:raise ValueError('index destination differs')
            found=[x for x in ima.listing(c['knowledge_base_id'],folder) if x['media_id']==r['media_id'] and x['title']==p.name]
            if len(found)!=1 or lib.sha(ima.download(r['media_id']))!=a['sha256']:raise ValueError('index remote verification failed')
            if release.get('entry'):
                release['historical_entry']=release.pop('entry')
            release.update(state='metadata_index_verified',data_version=m['data_version'],updated_scope=m['scope'],
                           index={'file_name':p.name,'media_id':r['media_id'],'sha256':r['sha256'],'folder_id':folder},
                           full_records_state='local_not_published')
        return release
    m = lib.load(op['release_manifest'])
    if {a['kind'] for a in m['artifacts']} != {'literature', 'occurrences', 'relations', 'searches', 'batches'}:
        raise ValueError('full artifact release requires all five verified records')
    objects = []
    for a in m['artifacts']:
        r = lib.load(a['receipt']); p = Path(a['path'])
        folder = c['folders']['引用关系与可视化' if a['kind'] == 'relations' else '知识库更新状态' if a['kind'] == 'batches' else '文献目录与索引']
        if r.get('status') not in OK or r['sha256'] != a['sha256'] or lib.sha(p.read_bytes()) != a['sha256']:
            raise ValueError('artifact release receipt/hash differs')
        if r['knowledge_base_id'] != c['knowledge_base_id'] or r['folder_id'] != folder: raise ValueError('artifact release destination differs')
        found = [x for x in ima.listing(c['knowledge_base_id'], folder) if x['media_id'] == r['media_id'] and x['title'] == p.name]
        if len(found) != 1 or lib.sha(ima.download(r['media_id'])) != a['sha256']: raise ValueError('artifact release remote verification failed')
        objects.append({'kind': a['kind'], 'file_name': p.name, 'sha256': a['sha256'], 'media_id': r['media_id'], 'folder_id': folder})
    return {'state': 'full_records_verified', 'data_version': m['data_version'], 'artifacts': objects}


def publish(ima, config_path, op):
    c = lib.load(config_path); loc = locator(op, c)
    with lib.locked(c['state_file']):
        db = lib.load(c['state_file']); h = read_head(ima, loc)
        if not h and op.get('initial'):
            inv = lib.load(op['initial_inventory']) if op.get('initial_inventory') else ima.inventory(c['knowledge_base_id'])
            if op.get('initial_inventory'):
                age=(datetime.fromisoformat(lib.now())-datetime.fromisoformat(inv['checked_at'])).total_seconds()
                if inv.get('knowledge_base_id')!=c['knowledge_base_id'] or not 0<=age<=3600:
                    raise RuntimeError('initial inventory must be a complete check from this session within one hour')
                if not all(x.get('pagination_complete') is True for x in inv['folders'].values()):raise RuntimeError('incomplete initial inventory')
            for path, fid in c['folders'].items():
                actual = inv['folders'].get(path)
                if not actual or actual['folder_id'] != fid: raise RuntimeError('initial project folder differs from live inventory: ' + path)
            originals = inv['folders']['成果原文']['items']
            for sid, rec in db['literature'].items():
                o = rec.get('original', {})
                if o.get('media_id'):
                    found = [x for x in originals if x['media_id'] == o['media_id']]
                    if len(found) != 1: raise RuntimeError('initial original object missing/ambiguous: ' + sid)
                    o['file_name'] = found[0]['title']
            # Persist verified names before staging, so uncertain commit retries use identical bytes.
            lib.write(c['state_file'], db)
        t = c.setdefault('team_sync', {'enabled': True, 'member_id': op.get('member_id', 'maintainer-local'), 'base_head': None})
        if not h: lib.write(config_path, c)
        member = t['member_id']; target_writer = op.get('handoff_to') or (h['writer_id'] if h else member)
        public = {'protocol': PROTOCOL, 'project': c['project'], 'scope': 'control_state_only',
                  'project_config': select(c, ('schema', 'project', 'knowledge_base_id', 'folders')),
                  'required_versions': lib.VERSIONS.copy(), 'writer_id': target_writer, 'control_state': control(c, db),
                  'artifact_release': artifact_release(ima, c, op, h)}
        validate_control(public['control_state'])
        version = lib.jsha(public)[:16]
        pending_path = Path(c['output_root']) / 'team' / 'pending.json'
        pending = lib.load(pending_path) if pending_path.exists() else None
        if pending and pending['data_version'] != version: raise RuntimeError('local state differs from staged publication; reconcile')
        if h and h['data_version'] == version:
            remote = fetch_state(ima, loc, h)
            if lib.jsha(remote) != lib.jsha(public): raise RuntimeError('data version collision')
            result = finish(config_path, c, db, h, public); result['status'] = 'reused_verified'; return result
        if h and member != h['writer_id']: raise RuntimeError('only serial writer may publish/handoff')
        base = pending['base_head'] if pending else t.get('base_head')
        if not same_head(base, h): raise RuntimeError('shared version changed; stop publication and reconcile')
        if h and not t.get('writer_session', {}).get('active'): raise RuntimeError('team begin required before publishing')
        if not h and not op.get('initial'): raise RuntimeError('initial publication requires explicit initial=true')
        dest = Path(c['output_root']) / 'team' / version; dest.mkdir(parents=True, exist_ok=True)
        sp = dest / (STATE_PREFIX + version + '.md')
        if not sp.exists(): sp.write_bytes(encode('论文库共享状态（身份、出处与进度）', public))
        if lib.jsha(decode(sp.read_bytes())) != lib.jsha(public): raise RuntimeError('staged state differs')
        if not pending:
            pending = {'base_head': head_ref(h), 'data_version': version, 'state_path': str(sp), 'phase': 'state_upload_pending'}
            lib.write(pending_path, pending)
        sr = ima.upload(loc['knowledge_base_id'], loc['status_folder_id'], sp, dest / 'state-receipt.json')
        # State is only a candidate until a valid head is uploaded; recheck after it.
        current = read_head(ima, loc)
        if not same_head(current, h): raise RuntimeError('shared head changed during staging; candidate not effective')
        revision = h['revision'] + 1 if h else 1
        ep = dest / (PREFIX + f'r{revision:06d}_' + version + '.md')
        if not ep.exists():
            entry = {'protocol': PROTOCOL, 'project': c['project'], 'knowledge_base_id': loc['knowledge_base_id'],
                     'revision': revision, 'data_version': version, 'parent': head_ref(h), 'writer_id': target_writer,
                     'scope': 'control_state_only', 'required_versions': lib.VERSIONS.copy(),
                     'state_object': {'file_name': sp.name, 'media_id': sr['media_id'], 'sha256': sr['sha256'],
                                      'folder_id': sr['folder_id']}, 'artifact_release': public['artifact_release'],
                     'created_at': sr['verified_at'], 'installation': 'install the complete manage-paper-library folder locally; then team init',
                     'concurrency': 'single writer by explicit handoff; API has no tested distributed lock/CAS',
                     'withheld': ['card bodies', 'complete reference raw text', 'machine paths', 'credentials']}
            ep.write_bytes(encode('论文库团队项目入口与生效状态', entry))
        pending.update(phase='head_upload_pending', entry_path=str(ep)); lib.write(pending_path, pending)
        # Do not allocate/upload a head if an intervening writer has advanced it.
        if not same_head(read_head(ima, loc), h): raise RuntimeError('shared head changed before commit')
        er = ima.upload(loc['knowledge_base_id'], loc['status_folder_id'], ep, dest / 'entry-receipt.json')
        final = read_head(ima, loc)
        if not final or final['media_id'] != er['media_id'] or final['sha256'] != er['sha256']:
            raise RuntimeError('head publication not uniquely effective; retain pending receipt')
        fetch_state(ima, loc, final)
        return finish(config_path, c, db, final, public)


def hydrate(ima, config_path, op):
    c = lib.load(config_path); db = lib.load(c['state_file']); sid = op['id']; r = db['literature'][sid]
    loc = locator(op, c); h = read_head(ima, loc)
    if not same_head(h, c['team_sync']['base_head']): raise RuntimeError('shared version changed; refresh before download')
    results = []
    for kind in op.get('kinds', ['original']):
        a = r['original'] if kind == 'original' else r.get('artifacts', {}).get(kind)
        if not a or not a.get('media_id'):
            results.append({'kind': kind, 'status': 'owner_local_only_or_missing'}); continue
        p = Path(a['local_path'] if kind == 'original' else a['path'])
        name = a.get('file_name') or p.name
        folder = a.get('folder_id') or c['folders']['成果原文']
        found = [x for x in ima.listing(loc['knowledge_base_id'], folder) if x['media_id'] == a['media_id'] and x['title'] == name]
        if len(found) != 1: raise RuntimeError('source object name/location differs; inspect actual inventory')
        data = ima.download(a['media_id'])
        if lib.sha(data) != a['sha256']: raise RuntimeError('source object hash differs')
        if p.exists() and lib.sha(p.read_bytes()) != a['sha256']: raise RuntimeError('local file differs; preserve it before repair')
        p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        results.append({'kind': kind, 'status': 'downloaded_verified', 'path': str(p), 'sha256': a['sha256']})
    return {'status': 'hydrated', 'id': sid, 'results': results}


def run(ima, op):
    action = op['team_action']; cp = op.get('project')
    if action == 'inspect':
        c = lib.load(cp) if cp else None; loc = locator(op, c); h = read_head(ima, loc)
        if h: fetch_state(ima, loc, h)
        return {'status': 'shared_verified' if h else 'not_initialized', 'head': head_ref(h)}
    if action == 'init': return restore(ima, op)
    if not cp: raise ValueError('project path required')
    if action == 'begin': return begin(ima, cp, op)
    if action == 'refresh':
        c = lib.load(cp)
        with lib.locked(c['state_file']): return restore(ima, op, c)
    if action == 'publish': return publish(ima, cp, op)
    if action == 'hydrate': return hydrate(ima, cp, op)
    if action == 'close':
        c = lib.load(cp); c['team_sync']['writer_session']['active'] = False; lib.write(cp, c)
        return {'status': 'local_session_closed', 'writer_ownership': 'unchanged; explicit publish handoff required'}
    raise ValueError('unknown team_action')


def main():
    from ima_client import Ima
    ap = argparse.ArgumentParser(); ap.add_argument('--operation', required=True); args = ap.parse_args()
    ima = None
    try:
        ima = Ima(); print(json.dumps(run(ima, lib.load(args.operation)), ensure_ascii=False)); return 0
    except Exception as e:
        print(json.dumps({'status': 'failed', 'reason': ima.safe_error(e) if ima else 'credentials/arguments unavailable'})); return 1


if __name__ == '__main__': sys.exit(main())
