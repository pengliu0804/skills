"""Observable team invariants in isolated projects with an in-memory ima fixture."""
from pathlib import Path
import tempfile
import unittest
import copy
import library as lib
import team_sync as team
import shared_index

class MemoryIma:
    def __init__(self):
        self.objects = {}; self.uploads = 0; self.fail_head_once = False
    def listing(self, kb, folder=None):
        return [{'media_id': k, 'title': x['name'], 'media_type': 7} for k, x in self.objects.items() if x['folder'] == folder]
    def download(self, mid): return self.objects[mid]['data']
    def inventory(self, kb):
        return {'folders': {'知识库更新状态': {'folder_id': 'folder_7512393340974258', 'items': self.listing(kb, 'folder_7512393340974258')},
                            '成果原文': {'folder_id': 'pdf-folder', 'items': [{'media_id': 'original-mid', 'title': 'source.pdf'}]}}}
    def upload(self, kb, folder, path, receipt):
        p = Path(path); data = p.read_bytes()
        same = [(k, x) for k, x in self.objects.items() if x['name'] == p.name and x['folder'] == folder]
        if same:
            mid, x = same[0]
            if x['data'] != data: raise RuntimeError('same name different bytes')
            status = 'reused_verified'
        else:
            mid = 'fixture-' + str(len(self.objects) + 1); self.uploads += 1
            self.objects[mid] = {'data': data, 'name': p.name, 'folder': folder}; status = 'uploaded_verified'
        r = {'status': status, 'media_id': mid, 'sha256': lib.sha(data), 'file': str(p),
             'folder_id': folder, 'knowledge_base_id': kb, 'verified_at': '2026-10-06T16:00:00+08:00'}
        lib.write(receipt, r)
        if p.name.startswith(team.PREFIX) and self.fail_head_once:
            self.fail_head_once = False; raise RuntimeError('fixture added but response lost')
        return r

class TeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name); self.ima = MemoryIma()
        self.cp = self.root / 'writer' / 'paper-library.project.json'; out = self.cp.parent / 'output'
        source = self.cp.parent / 'source.pdf'; source.parent.mkdir(parents=True); source.write_bytes(b'%PDF-fixture')
        card = out / 'cards' / 'S001.md'; card.parent.mkdir(parents=True); card.write_text('PRIVATE_CARD_BODY')
        r = {'id': 'S001', 'roles': ['group'], 'title': 'fixture title', 'adopted_version': 'v1',
             'original': {'local_path': str(source), 'sha256': lib.sha(source.read_bytes()), 'media_id': 'original-mid',
                          'page_count': 2, 'save_status': 'saved_verified'},
             'card_sections': ['PRIVATE_CARD_BODY'] * 7, 'abstract_original': 'PRIVATE_ABSTRACT',
             'artifacts': {'card': {'path': str(card), 'sha256': lib.sha(card.read_bytes()),
                                    'status': 'local_verified', 'save_status': 'save_not_requested', 'source_fingerprint': 'fp'}},
             'reference_count': 1}
        raw = 'PRIVATE_REFERENCE_RAW 2025'
        self.db = {'schema': '1.0.0', 'versions': lib.VERSIONS.copy(), 'last_batch': 'B1',
                   'literature': {'S001': r, 'E00001': {'id': 'E00001', 'roles': ['reference'], 'type': 'journal_article',
                                      'identity_key': 'raw:' + lib.norm(raw), 'source_citation_raw': raw}},
                   'occurrences': {'o1': {'id': 'o1', 'source_id': 'S001', 'source_version': 'v1', 'entity_id': 'E00001',
                                         'raw': raw, 'pages': [2], 'order': 1, 'number': 1, 'state': 'effective'}},
                   'relations': {}, 'searches': {}, 'batches': {'B1': {'id': 'B1', 'scope': ['S001'], 'mode': 'reconstruct',
                     'save_target': 'local', 'papers': {'S001': {'status': 'local_verified'}}, 'shared_state': 'local_candidate'}}}
        self.c = {'schema': '1.0.0', 'project': 'YCX-Group', 'knowledge_base_id': lib.load(team.LOCATOR)['knowledge_base_id'],
                  'folders': {'知识库更新状态': 'folder_7512393340974258', '成果原文': 'pdf-folder'},
                  'state_file': str(out / 'state' / 'library.json'), 'effective_manifest': str(out / 'state' / 'effective.json'),
                  'output_root': str(out), 'runtime_python': 'MACHINE_RUNTIME'}
        lib.write(self.cp, self.c); lib.write(self.c['state_file'], self.db)
    def tearDown(self): self.temp.cleanup()
    def publish(self, **kwargs): return team.publish(self.ima, self.cp, {'initial': True, **kwargs})
    def test_portable_projection_and_no_change_reuse(self):
        first = self.publish(); text = '\n'.join(x['data'].decode() for x in self.ima.objects.values())
        for private in ('PRIVATE_CARD_BODY', 'PRIVATE_REFERENCE_RAW', 'PRIVATE_ABSTRACT', str(self.root), 'MACHINE_RUNTIME'):
            self.assertNotIn(private, text)
        self.assertEqual(first['scope'], 'control_state_only'); self.assertEqual(self.ima.uploads, 2)
        again = self.publish(); self.assertEqual(again['status'], 'reused_verified'); self.assertEqual(self.ima.uploads, 2)
        self.assertEqual(first['head'], again['head'])
    def test_new_machine_init_identity_reuse_and_permissions(self):
        self.publish(); root = self.root / 'member'
        result = team.restore(self.ima, {'root': str(root), 'member_id': 'member-b'})
        c = lib.load(result['project']); db = lib.load(c['state_file'])
        self.assertEqual(len(db['literature']), 2); self.assertEqual(len(db['occurrences']), 1)
        self.assertTrue(db['literature']['S001']['original']['local_path'].startswith(str(root)))
        self.assertEqual(lib.choose_entity(db, {'raw': 'PRIVATE_REFERENCE_RAW 2025', 'type': 'journal_article'})[0], 'E00001')
        self.assertEqual(len(db['literature']), 2)
        self.assertFalse(lib.artifact_ok(db['literature']['S001']['artifacts']['card']))
        with self.assertRaisesRegex(RuntimeError, 'read-only'): team.local_guard(c)
        with self.assertRaisesRegex(RuntimeError, 'another member'): team.begin(self.ima, result['project'], {})
        with self.assertRaisesRegex(RuntimeError, 'project exists'): team.restore(self.ima, {'root': str(root), 'member_id': 'b'})
    def test_explicit_handoff_and_stale_writer(self):
        self.publish(); root = self.root / 'member'
        cp2 = team.restore(self.ima, {'root': str(root), 'member_id': 'member-b'})['project']
        head = self.publish(handoff_to='member-b')['head']; self.assertEqual(head['revision'], 2)
        with self.assertRaisesRegex(RuntimeError, 'shared version changed'): team.begin(self.ima, cp2, {})
        team.restore(self.ima, {'project': cp2}, lib.load(cp2))
        team.begin(self.ima, cp2, {}); team.local_guard(lib.load(cp2), allocating=True)
        with self.assertRaisesRegex(RuntimeError, 'another member'): team.begin(self.ima, self.cp, {})
    def test_lost_head_response_recovery_without_duplicate(self):
        self.ima.fail_head_once = True
        with self.assertRaisesRegex(RuntimeError, 'response lost'): self.publish()
        self.assertTrue(Path(self.c['output_root'], 'team', 'pending.json').exists())
        resumed = self.publish(); self.assertEqual(resumed['status'], 'reused_verified'); self.assertEqual(self.ima.uploads, 2)
        self.assertFalse(Path(self.c['output_root'], 'team', 'pending.json').exists())
    def test_hash_tamper_and_branch_detection(self):
        self.publish(); loc = team.locator({}); h = team.read_head(self.ima, loc)
        sm = h['state_object']['media_id']; original = self.ima.objects[sm]['data']; self.ima.objects[sm]['data'] += b'tampered'
        with self.assertRaisesRegex(RuntimeError, 'hash differs'): team.restore(self.ima, {'root': str(self.root / 'other'), 'member_id': 'x'})
        self.ima.objects[sm]['data'] = original
        for suffix in ('a', 'b'):
            child = {k: v for k, v in h.items() if k not in ('media_id', 'sha256', 'file_name')}
            child.update(parent=team.head_ref(h), revision=2, data_version=suffix * 16)
            self.ima.objects['fork-' + suffix] = {'data': team.encode('fork', child), 'folder': loc['status_folder_id'],
                                                 'name': team.PREFIX + 'r000002_' + suffix * 16 + '.md'}
        with self.assertRaisesRegex(RuntimeError, 'fork'): team.read_head(self.ima, loc)
    def test_dirty_refresh_preserves_local_state(self):
        self.publish(); c = lib.load(self.cp); before = lib.load(c['state_file'])
        before['team_sync_status']['state'] = 'pending_publish'; lib.write(c['state_file'], before)
        with self.assertRaisesRegex(RuntimeError, 'unpublished local changes'): team.restore(self.ima, {'project': str(self.cp)}, c)
        self.assertEqual(lib.load(c['state_file']), before)
        before['team_sync_status']['state'] = 'shared_control_current'; lib.write(c['state_file'], before)
        team.restore(self.ima, {'project': str(self.cp)}, c); db = lib.load(c['state_file'])
        self.assertEqual(db['literature']['S001']['abstract_original'], 'PRIVATE_ABSTRACT')
        self.assertEqual(db['literature']['S001']['card_sections'][0], 'PRIVATE_CARD_BODY')
        self.assertEqual(db['occurrences']['o1']['raw'], 'PRIVATE_REFERENCE_RAW 2025')
    def test_pending_mark_and_control_validation(self):
        self.publish(); c=lib.load(self.cp); db=lib.load(c['state_file'])
        team.mark_pending(c,db); self.assertEqual(db['team_sync_status']['state'],'pending_publish')
        public=team.control(c,db); team.validate_control(public)
        public['occurrences']['o1']['entity_id']='E99999'
        with self.assertRaisesRegex(ValueError,'endpoint'):team.validate_control(public)

    def test_scoped_index_release_and_reuse(self):
        lib.write(self.c['effective_manifest'],{'artifact_release':{'entry':{'media_id':'legacy-entry','sha256':'legacy-hash'}}})
        self.publish();c=lib.load(self.cp);c['folders']['文献目录与索引']='index-folder';lib.write(self.cp,c)
        db=lib.load(c['state_file']);r=copy.deepcopy(db['literature']['S001']);r.update(id='S002',title='second paper')
        db['literature']['S002']=r;db['literature']['E00002']={'id':'E00002','roles':['reference'],'identity_key':'raw:privateother'}
        db['occurrences']['o2']={'id':'o2','source_id':'S002','source_version':'v1','entity_id':'E00002',
            'raw':'PRIVATE_OTHER_RAW','pages':[2],'order':1,'number':1,'state':'effective'}
        lib.write(c['state_file'],db)
        built=shared_index.build_team(c,db,'B1',self.root/'index');m=lib.load(built['manifest'])
        txt=Path(built['path']).read_text(encoding='utf-8')
        for private in ('PRIVATE_CARD_BODY','PRIVATE_REFERENCE_RAW','PRIVATE_OTHER_RAW',str(self.root)):
            self.assertNotIn(private,txt)
        self.assertIn('| o1 |',txt);self.assertNotIn('| o2 |',txt)
        receipt=self.ima.upload(c['knowledge_base_id'],'index-folder',built['path'],m['index']['receipt'])
        result=self.publish(index_manifest=built['manifest']);self.assertEqual(result['head']['revision'],2)
        head=team.read_head(self.ima,team.locator({},c));release=head['artifact_release']
        self.assertEqual(release['index']['media_id'],receipt['media_id'])
        self.assertEqual(release['updated_scope'],['S001']);self.assertEqual(release['full_records_state'],'local_not_published')
        self.assertNotIn('entry',release);self.assertEqual(release['historical_entry']['media_id'],'legacy-entry')
        before=self.ima.uploads;self.assertEqual(self.publish(index_manifest=built['manifest'])['status'],'reused_verified')
        self.assertEqual(self.ima.uploads,before)
        self.ima.objects[receipt['media_id']]['data']+=b'tamper'
        with self.assertRaisesRegex(ValueError,'remote verification'):self.publish(index_manifest=built['manifest'])
if __name__ == '__main__': unittest.main(verbosity=2)
