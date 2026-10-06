"""Bounded regression checks; isolated temporary state, no network/uploads/secrets."""
import copy,json,tempfile,io,urllib.error
from pathlib import Path
import unittest
import library as lib
from ima_client import Ima,digest,write_json,run

class InfrastructureTests(unittest.TestCase):
    def test_transport_retries_only_read_operations(self):
        class Opener:
            def __init__(self):self.calls=0
            def open(self,*args,**kwargs):
                self.calls+=1
                if self.calls==1:raise urllib.error.URLError('fixture timeout')
                return io.BytesIO(b'{"code":0,"data":{}}')
        ima=Ima('fixture-id','fixture-key');ima.opener=Opener()
        self.assertEqual(ima.post('/openapi/wiki/v1/get_knowledge_list',{}),{})
        self.assertEqual(ima.opener.calls,2)
        ima.opener=Opener()
        with self.assertRaises(urllib.error.URLError):ima.post('/openapi/wiki/v1/create_media',{})
        self.assertEqual(ima.opener.calls,1)

    def test_download_transport_retry_and_http_failure(self):
        class Opener:
            def __init__(self,http=False):self.calls=0;self.http=http
            def open(self,*args,**kwargs):
                self.calls+=1
                if self.calls==1:
                    if self.http:raise urllib.error.HTTPError('https://fixture.invalid',403,'forbidden',{},None)
                    raise urllib.error.URLError('fixture timeout')
                return io.BytesIO(b'original bytes')
        class Fake(Ima):
            def post(self,*args):return {'url_info':{'url':'https://fixture.invalid/source'}}
        ima=Fake('fixture-id','fixture-key');ima.opener=Opener()
        self.assertEqual(ima.download('fixture-mid'),b'original bytes');self.assertEqual(ima.opener.calls,2)
        ima.opener=Opener(http=True)
        with self.assertRaises(urllib.error.HTTPError):ima.download('fixture-mid')
        self.assertEqual(ima.opener.calls,1)

    def test_cos_retry_same_reserved_key_without_allocation(self):
        class Response(io.BytesIO):status=200
        class Opener:
            def __init__(self):self.requests=[]
            def open(self,req,**kwargs):
                self.requests.append((req.full_url,req.data,req.method))
                if len(self.requests)==1:raise urllib.error.URLError('fixture timeout')
                return Response(b'')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.md';p.write_bytes(b'fixed bytes')
            ima=Ima('fixture-id','fixture-key');ima.opener=Opener()
            cred={'bucket_name':'fixture','region':'fixture','cos_key':'fixed/key','start_time':1,'expired_time':2,
                'secret_key':'fixture-temporary','secret_id':'fixture-temporary-id','token':'fixture-temporary-token'}
            ima.cos_put(p,cred,'text/markdown')
            self.assertEqual(len(ima.opener.requests),2);self.assertEqual(*ima.opener.requests)

    def test_reference_save_card_locator_and_legacy_preservation(self):
        with tempfile.TemporaryDirectory() as d:
            config={'output_root':d,'knowledge_base_id':'kb','folders':{'参考文献清单':'refs',
                '成果原文':'originals','原文笔记卡片/'+lib.CLASS['T01P']:'cards'}}
            refpath=Path(d)/'refs.md';refpath.write_text('verified references',encoding='utf-8')
            r={'id':'S001','title':'fixture','authors':[],'adopted_version':'v1','classification':{'path':lib.CLASS['T01P']},
                'original':{'local_path':str(Path(d)/'private.pdf'),'sha256':'source-hash','media_id':'original-mid','save_status':'saved_verified'},
                'card_sections':['reviewed body']*7,'legacy':{'card':{'media_id':'old-card'},'reference':{'media_id':'old-ref'}},
                'artifacts':{'reference':{'path':str(refpath),'sha256':lib.sha(refpath.read_bytes()),'save_status':'save_pending'}}}
            r['artifacts']['card']=lib.put_artifact(config,'S001','card',lib.card_md(r,r['card_sections']),lib.fingerprint(r,'card'),None,r['title'])
            db={'last_batch':'B1','literature':{'S001':r},'batches':{'B1':{'scope':['S001'],'mode':'reconstruct',
                'save_target':'ima','papers':{'S001':{'unresolved':['代表产物尚未同步ima','外部身份未全部匹配']}}}}}
            receipt=Path(d)/'receipt.json';lib.write(receipt,{'status':'uploaded_verified','file':str(refpath),
                'sha256':r['artifacts']['reference']['sha256'],'folder_id':'refs','knowledge_base_id':'kb','media_id':'new-ref','verified_at':'2026-10-06'})
            lib.record_save(config,db,'S001','reference',receipt)
            result=lib.refresh_card_links(config,db,'S001');self.assertEqual(result['status'],'local_verified')
            text=Path(result['artifact']['path']).read_text(encoding='utf-8')
            self.assertIn('ima参考清单media_id：new-ref',text);self.assertNotIn(d,text)
            self.assertEqual(r['artifacts']['reference']['save_status'],'saved_verified')
            self.assertEqual(lib.refresh_card_links(config,db,'S001')['status'],'reused_valid')
            lib.write(receipt,{'status':'uploaded_verified','file':result['artifact']['path'],'sha256':result['artifact']['sha256'],
                'folder_id':'cards','knowledge_base_id':'kb','media_id':'new-card','verified_at':'2026-10-06'})
            lib.record_save(config,db,'S001','card',receipt)
            self.assertEqual(r['migration_status'],'saved_reconstructed')
            self.assertEqual(r['legacy']['card_status'],'superseded_preserved')
            self.assertEqual(r['legacy']['reference']['media_id'],'old-ref')
            self.assertNotIn('代表产物尚未同步ima',db['batches']['B1']['papers']['S001']['unresolved'])

    def test_scope(self):
        self.assertEqual(lib.scope('S001–S003，S002 S008'),['S001','S002','S003','S008'])
        with self.assertRaises(ValueError):lib.scope('S003-S001')

    def test_title_names_preserve_reuse_and_revision_identity(self):
        with tempfile.TemporaryDirectory() as d:
            c={'output_root':d};title='Contact Force: PCG / ECG?'
            first=lib.put_artifact(c,'S001','card','reviewed body','fp',None,title)
            name=Path(first['path']).name
            self.assertTrue(name.startswith('S001_Contact Force： PCG ／ ECG？_知识卡片_r'))
            first.update(save_status='saved_verified',media_id='verified-mid')
            self.assertIs(lib.put_artifact(c,'S001','card','reviewed body','fp',first,title),first)
            renamed=lib.put_artifact(c,'S001','card','reviewed body','fp',first,'Full Original Title')
            self.assertNotIn('media_id',renamed);self.assertEqual(renamed['supersedes']['media_id'],'verified-mid')
            changed=lib.put_artifact(c,'S001','card','corrected body','fp',renamed,'Full Original Title')
            self.assertNotEqual(changed['path'],renamed['path']);self.assertTrue(Path(renamed['path']).exists())
            long=lib.put_artifact(c,'S002','reference','source raw','fp',None,'Long Paper Title '*80)
            self.assertLessEqual(len(long['path']),245)

    def test_external_reuse_not_fuzzy(self):
        db={'literature':{}}
        a={'raw':'A precise citation 2025','type':'journal_article'}
        eid,stat,_=lib.choose_entity(db,a)
        self.assertEqual(lib.choose_entity(db,a)[0],eid)
        self.assertEqual(stat,'unresolved')
        self.assertNotEqual(lib.choose_entity(db,dict(a,raw='A similar citation 2025'))[0],eid)
        with self.assertRaises(ValueError):lib.choose_entity(db,dict(a,entity_id=eid,identity_evidence=None))

    def test_pagination_guard(self):
        class Fake(Ima):
            def __init__(self):self.i=0
            def post(self,*args):
                self.i+=1
                return {'knowledge_list':[{'id':self.i}],'is_end':False,'next_cursor':'repeat'}
        with self.assertRaises(RuntimeError):Fake().listing('fixture')
        class Good(Fake):
            def post(self,*args):
                self.i+=1
                return {'knowledge_list':[{'id':self.i}],'is_end':self.i==2,'next_cursor':'next'}
        self.assertEqual(len(Good().listing('fixture')),2)

    def test_upload_duplicate_and_unknown_recovery(self):
        class Fake(Ima):
            def __init__(self,data,existing=False):self.data=data;self.existing=existing;self.calls=[]
            def listing(self,*args):return [{'media_id':'fixture-mid','title':'a.md'}] if self.existing else []
            def download(self,*args):return self.data
            def post(self,endpoint,body):
                self.calls.append(endpoint)
                if endpoint.endswith('add_knowledge'):self.existing=True;return {}
                raise AssertionError('unexpected new allocation/check')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.md';p.write_bytes('已核验UTF8\n'.encode());receipt=Path(d)/'r.json'
            f=Fake(p.read_bytes(),True)
            self.assertEqual(f.upload('fixture-kb','fixture-folder',p,receipt)['status'],'reused_verified')
            self.assertEqual(f.calls,[])
            verified=run(f,{'action':'verify','kb':'fixture-kb','folder':'fixture-folder','media_id':'fixture-mid','path':str(p),'receipt':str(receipt)})
            self.assertEqual(verified['status'],'reused_verified')
            self.assertEqual(f.calls,[])
            f=Fake(b'other',True)
            with self.assertRaisesRegex(RuntimeError,'different content'):f.upload('fixture-kb','fixture-folder',p,receipt)
            write_json(receipt,{'sha256':digest(p.read_bytes()),'status':'add_unknown','knowledge_base_id':'fixture-kb',
                'folder_id':'fixture-folder','media_id':'fixture-mid','file_info':{'cos_key':'fixture/key','file_name':'a.md','file_size':p.stat().st_size}})
            f=Fake(p.read_bytes())
            self.assertEqual(f.upload('fixture-kb','fixture-folder',p,receipt)['status'],'recovered_verified')
            self.assertEqual(f.calls,['/openapi/wiki/v1/add_knowledge'])
            self.assertNotIn('create_media',str(f.calls))

    def test_resume_hash_and_rule_change(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'source.pdf';p.write_bytes(b'%PDF-fixture')
            r={'adopted_version':'fixture-v1','original':{'local_path':str(p),'sha256':lib.sha(p.read_bytes())},'artifacts':{}}
            for kind in ['card','reference']:
                a=Path(d)/(kind+'.md');a.write_bytes(b'fixture\n')
                r['artifacts'][kind]={'path':str(a),'sha256':lib.sha(a.read_bytes()),'source_fingerprint':lib.fingerprint(r,kind)}
            self.assertEqual(lib.task_status(r,'reconstruct')['status'],'reusable')
            r['original']['save_status']='saved_verified'
            self.assertEqual(lib.task_status(r,'reconstruct','ima')['next'],['save_card','save_reference'])
            Path(r['artifacts']['card']['path']).write_bytes(b'tampered')
            self.assertEqual(lib.task_status(r,'reconstruct')['next'],['card'])
            Path(r['artifacts']['card']['path']).write_bytes(b'fixture\n')
            v=lib.VERSIONS['classification'];lib.VERSIONS['classification']='fixture-next'
            try:self.assertEqual(lib.task_status(r,'reconstruct')['next'],['card'])
            finally:lib.VERSIONS['classification']=v
            p.write_bytes(b'%PDF-changed')
            self.assertEqual(lib.task_status(r,'reconstruct')['status'],'source_missing_or_changed')

    def test_new_registration_dedup_and_monotonic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'new.pdf';p.write_bytes(b'%PDF-fixture')
            db={'literature':{'S002':{'id':'S002','title':'existing','doi':None,'original':{'sha256':'other'}}}}
            meta={'pdf_path':str(p),'title':'new','version_id':'v1','live_duplicate_check':True}
            first=lib.register(db,meta)
            self.assertEqual(first['id'],'S003')
            self.assertEqual(lib.register(db,meta)['id'],'S003')
            self.assertEqual(len(db['literature']),2)
            db['literature']['S002']['doi']='10.1000/KNOWN'
            with self.assertRaisesRegex(ValueError,'DOI title conflict'):
                lib.register(db,dict(meta,title='different title',doi='https://doi.org/10.1000/known',doi_verified=True))

if __name__=='__main__':unittest.main(verbosity=2)
