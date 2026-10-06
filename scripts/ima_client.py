"""ima file operations. Credentials are held in memory; stdout and receipts are redacted.

Use environment IMA_OPENAPI_CLIENTID/IMA_OPENAPI_APIKEY, or --session: first stdin
line is a credential object, subsequent lines are operations. Never use a PTY.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

def now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def write_json(path, data):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_suffix(p.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(p)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('redirect refused')

class Ima:
    def __init__(self, client_id=None, api_key=None):
        self.client_id = client_id or os.getenv('IMA_OPENAPI_CLIENTID') or os.getenv('IMA_CLIENT_ID')
        self.api_key = api_key or os.getenv('IMA_OPENAPI_APIKEY') or os.getenv('IMA_API_KEY')
        if not self.client_id or not self.api_key:
            raise RuntimeError('missing ima credentials')
        self.opener = urllib.request.build_opener(NoRedirect())

    def safe_error(self, exc):
        msg = str(exc)
        for secret in (self.client_id, self.api_key):
            msg = msg.replace(secret, '[redacted]')
        return re.sub(r'https?://\S+', '[URL redacted]', msg)[:240]

    def post(self, endpoint, body):
        if not re.fullmatch(r'/openapi/(?:wiki/v1/[a-z_]+|note/v1/[a-z_]+|check_skill_update)', endpoint):
            raise ValueError('unsupported endpoint path')
        req = urllib.request.Request('https://ima.qq.com' + endpoint,
            data=json.dumps(body, ensure_ascii=False).encode('utf-8'), method='POST',
            headers={'ima-openapi-clientid': self.client_id, 'ima-openapi-apikey': self.api_key,
                     'ima-openapi-ctx': 'skill_version=1.1.10', 'Content-Type': 'application/json'})
        read_only=endpoint in ('/openapi/wiki/v1/get_knowledge_list','/openapi/wiki/v1/get_media_info',
                              '/openapi/wiki/v1/get_knowledge_base','/openapi/check_skill_update',
                              '/openapi/wiki/v1/check_repeated_names')
        for attempt in range(2 if read_only else 1):
            try:
                with self.opener.open(req, timeout=30 if read_only else 45) as resp:result=json.load(resp)
                break
            except urllib.error.HTTPError:raise
            except (urllib.error.URLError,TimeoutError,ConnectionError):
                if not read_only or attempt==1:raise
                time.sleep(0.25)
        if result.get('code') != 0:
            raise RuntimeError(f"ima code={result.get('code')}: {self.safe_error(result.get('msg', 'unknown'))}")
        return result.get('data', {})

    def listing(self, kb, folder=None):
        items, cursor, seen = [], '', set()
        while True:
            body = {'knowledge_base_id': kb, 'cursor': cursor, 'limit': 50}
            if folder: body['folder_id'] = folder
            data = self.post('/openapi/wiki/v1/get_knowledge_list', body)
            if 'knowledge_list' not in data: raise RuntimeError('listing schema missing knowledge_list')
            items.extend(data['knowledge_list'])
            if data.get('is_end') is True: break
            nxt = data.get('next_cursor')
            if not nxt or nxt in seen: raise RuntimeError('incomplete/repeated pagination cursor')
            seen.add(nxt); cursor = nxt
        return items

    def inventory(self, kb):
        folders, queue, done = {}, [(None, '')], set()
        while queue:
            folder, path = queue.pop(0)
            if folder in done: continue
            done.add(folder)
            items = self.listing(kb, folder)
            folders[path or '/'] = {'folder_id': folder, 'items': items, 'pagination_complete': True}
            for item in items:
                if item.get('media_type') == 99:
                    queue.append((item['media_id'], (path + '/' + item['title']).lstrip('/')))
        return {'checked_at': now(), 'knowledge_base_id': kb, 'folders': folders}

    def download(self, media_id):
        data = self.post('/openapi/wiki/v1/get_media_info', {'media_id': media_id})
        info = data.get('url_info') or {}
        if not info.get('url'): raise RuntimeError('media has no original download URL')
        parsed = urllib.parse.urlparse(info['url'])
        if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname in ('localhost', '127.0.0.1'):
            raise RuntimeError('non-HTTPS or local media URL refused')
        heads = info.get('headers') or {}
        if any(k.lower().startswith('ima-openapi-') for k in heads):
            raise RuntimeError('long-term headers refused on download URL')
        req = urllib.request.Request(info['url'], headers=heads)
        for attempt in range(2):
            try:
                with self.opener.open(req, timeout=90) as resp:return resp.read()
            except urllib.error.HTTPError:raise
            except (urllib.error.URLError,TimeoutError,ConnectionError):
                if attempt==1:raise
                time.sleep(0.25)

    def ensure_folder(self, kb, name, parent=None):
        matches = [x for x in self.listing(kb, parent) if x.get('media_type') == 99 and x.get('title') == name]
        if len(matches) > 1: raise RuntimeError('ambiguous same-name folders')
        if matches: return {'media_id': matches[0]['media_id'], 'status': 'reused'}
        body = {'knowledge_base_id': kb, 'name': name}
        if parent: body['folder_id'] = parent
        # Historically tested endpoint; listing is checked before and after any attempt.
        try: self.post('/openapi/wiki/v1/create_folder', body)
        except Exception as exc:
            matches = [x for x in self.listing(kb, parent) if x.get('media_type') == 99 and x.get('title') == name]
            if len(matches) != 1: raise exc
        matches = [x for x in self.listing(kb, parent) if x.get('media_type') == 99 and x.get('title') == name]
        if len(matches) != 1: raise RuntimeError('folder creation unconfirmed')
        return {'media_id': matches[0]['media_id'], 'status': 'created_verified'}

    def cos_put(self, path, cred, mime):
        content = Path(path).read_bytes()
        host = f"{cred['bucket_name']}.cos.{cred['region']}.myqcloud.com"
        pathname = '/' + cred['cos_key']
        key_time = f"{cred['start_time']};{cred['expired_time']}"
        def hm(key, value): return hmac.new(key.encode(), value.encode(), hashlib.sha1).hexdigest()
        sign_key = hm(cred['secret_key'], key_time)
        heads = {'content-length': str(len(content)), 'host': host}
        encoded = '&'.join(f'{k}={urllib.parse.quote(heads[k], safe="")}' for k in sorted(heads))
        http_string = f'put\n{pathname}\n\n{encoded}\n'
        to_sign = f'sha1\n{key_time}\n{hashlib.sha1(http_string.encode()).hexdigest()}\n'
        auth = '&'.join(['q-sign-algorithm=sha1', f"q-ak={cred['secret_id']}",
            f'q-sign-time={key_time}', f'q-key-time={key_time}', 'q-header-list=content-length;host',
            'q-url-param-list=', f'q-signature={hm(sign_key, to_sign)}'])
        req = urllib.request.Request('https://' + host + urllib.parse.quote(pathname, safe='/'), data=content,
            method='PUT', headers={'Content-Type': mime, 'Content-Length': str(len(content)),
            'Authorization': auth, 'x-cos-security-token': cred['token']})
        # Exact same reserved COS key and bytes: no new media allocation or add.
        for attempt in range(2):
            try:
                with self.opener.open(req, timeout=90) as resp:
                    if not 200 <= resp.status < 300: raise RuntimeError('COS upload failed')
                return
            except urllib.error.HTTPError:raise
            except (urllib.error.URLError,TimeoutError,ConnectionError):
                if attempt==1:raise
                time.sleep(0.25)

    def upload(self, kb, folder, path, receipt_path):
        p = Path(path); content = p.read_bytes(); sha = digest(content)
        ext = p.suffix.lower(); types = {'.pdf': (1, 'application/pdf', 200*1024*1024),
            '.md': (7, 'text/markdown', 10*1024*1024)}
        if ext not in types: raise RuntimeError('only documented PDF/MD uploads supported by this helper')
        media_type, mime, cap = types[ext]
        if not content or len(content) > cap: raise RuntimeError('empty or oversized file')
        if ext == '.pdf' and not content.startswith(b'%PDF-'): raise RuntimeError('invalid PDF signature')
        if ext == '.md': content.decode('utf-8')
        items = self.listing(kb, folder)
        matches = [x for x in items if x.get('title') == p.name]
        if len(matches) > 1: raise RuntimeError('ambiguous same-name objects')
        if matches:
            mid = matches[0]['media_id']; remote = self.download(mid)
            if digest(remote) != sha: raise RuntimeError('same name has different content; cancel, choose new revision name')
            rec = {'status': 'reused_verified', 'file': str(p.resolve()), 'sha256': sha,
                'media_id': mid, 'folder_id': folder, 'knowledge_base_id': kb, 'verified_at': now()}
            write_json(receipt_path, rec); return rec
        old = json.loads(Path(receipt_path).read_text(encoding='utf-8')) if Path(receipt_path).exists() else None
        if old and old.get('sha256') == sha and old.get('status') in ('created', 'cos_uploaded', 'add_unknown', 'added_unverified'):
            if old.get('knowledge_base_id')!=kb or old.get('folder_id')!=folder:
                raise RuntimeError('pending receipt destination differs; reconcile first')
            # Never allocate a second media. Recovery needs the existing staged bytes.
            if old.get('status')=='created' or not old.get('file_info'):
                raise RuntimeError('pending upload reservation; reconcile media_id before retry')
            if digest(self.download(old['media_id']))!=sha:
                raise RuntimeError('pending media bytes differ; cannot recover')
            body={'media_id':old['media_id'],'media_type':media_type,'title':p.name,
                  'knowledge_base_id':kb,'file_info':old['file_info']}
            if folder:body['folder_id']=folder
            self.post('/openapi/wiki/v1/add_knowledge',body)
            found=[x for x in self.listing(kb,folder) if x['media_id']==old['media_id'] and x['title']==p.name]
            if not found or digest(self.download(old['media_id']))!=sha:
                raise RuntimeError('recovered add still unverified; do not create again')
            old.update(status='recovered_verified',verified_at=now(),platform_parsing='not_verified')
            write_json(receipt_path,old);return old
        chkbody = {'params': [{'name': p.name, 'media_type': media_type}], 'knowledge_base_id': kb}
        if folder: chkbody['folder_id'] = folder
        check = self.post('/openapi/wiki/v1/check_repeated_names', chkbody)
        def repeated(x):
            if isinstance(x, dict): return x.get('is_repeated') is True or any(repeated(v) for v in x.values())
            if isinstance(x, list): return any(repeated(v) for v in x)
            return False
        def has_result(x):
            if isinstance(x, dict): return 'is_repeated' in x or any(has_result(v) for v in x.values())
            if isinstance(x, list): return any(has_result(v) for v in x)
            return False
        if not has_result(check): raise RuntimeError('unrecognized duplicate-check response')
        if repeated(check): raise RuntimeError('duplicate name reported; reconcile before upload')
        data = self.post('/openapi/wiki/v1/create_media', {'file_name': p.name, 'file_size': len(content),
            'content_type': mime, 'knowledge_base_id': kb, 'file_ext': ext[1:]})
        mid = data['media_id']; cred = data['cos_credential']
        rec = {'status': 'created', 'file': str(p.resolve()), 'sha256': sha, 'media_id': mid,
               'folder_id': folder, 'knowledge_base_id': kb, 'started_at': now()}
        rec['file_info']={'cos_key':cred['cos_key'],'file_size':len(content),'file_name':p.name}
        write_json(receipt_path, rec)
        self.cos_put(p, cred, mime); rec['status'] = 'cos_uploaded'; write_json(receipt_path, rec)
        body = {'media_id': mid, 'media_type': media_type, 'title': p.name, 'knowledge_base_id': kb,
            'file_info': {'cos_key': cred['cos_key'], 'file_size': len(content), 'file_name': p.name}}
        if folder: body['folder_id'] = folder
        try: self.post('/openapi/wiki/v1/add_knowledge', body)
        except Exception:
            rec['status'] = 'add_unknown'; write_json(receipt_path, rec)
            # Caller must query actual state before retrying.
            raise
        rec['status'] = 'added_unverified'; write_json(receipt_path, rec)
        for attempt in range(3):
            matches = [x for x in self.listing(kb, folder) if x['media_id'] == mid and x['title'] == p.name]
            if matches: break
            time.sleep(1 + attempt)
        if not matches: raise RuntimeError('uploaded object not visible in target folder')
        if digest(self.download(mid)) != sha: raise RuntimeError('downloaded upload hash mismatch')
        rec.update(status='uploaded_verified', verified_at=now(), platform_parsing='not_verified')
        write_json(receipt_path, rec); return rec

def run(ima, op):
    action = op['action']
    if action == 'version':
        data = ima.post('/openapi/check_skill_update', {'version': '1.1.10'})
        result = {'checked_at': now(), 'latest_version': data.get('latest_version'), 'release_desc': data.get('release_desc')}
    elif action == 'inventory': result = ima.inventory(op['kb'])
    elif action == 'list': result = ima.listing(op['kb'], op.get('folder'))
    elif action == 'ensure-folder': result = ima.ensure_folder(op['kb'], op['name'], op.get('parent'))
    elif action == 'download':
        content = ima.download(op['media_id'])
        if op.get('path'):
            p = Path(op['path']); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(content)
        result = {'media_id': op['media_id'], 'sha256': digest(content), 'bytes': len(content), 'checked_at': now()}
        if op.get('expected_sha256'): result['hash_match'] = result['sha256'] == op['expected_sha256']
    elif action == 'verify':
        p=Path(op['path']);sha=digest(p.read_bytes())
        found=[x for x in ima.listing(op['kb'],op.get('folder')) if x['media_id']==op['media_id'] and x['title']==p.name]
        if len(found)!=1 or digest(ima.download(op['media_id']))!=sha:raise RuntimeError('existing object location/name/hash differs')
        result={'status':'reused_verified','file':str(p.resolve()),'sha256':sha,'media_id':op['media_id'],
                'folder_id':op.get('folder'),'knowledge_base_id':op['kb'],'verified_at':now(),'platform_parsing':'not_verified'}
        if op.get('receipt'):write_json(op['receipt'],result)
    elif action == 'upload': result = ima.upload(op['kb'], op.get('folder'), op['path'], op['receipt'])
    elif action == 'team':
        import team_sync
        result = team_sync.run(ima, op)
    else: raise ValueError('unknown action')
    if op.get('output'): write_json(op['output'], result)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', action='store_true')
    parser.add_argument('--operation', help='JSON operation file; contains no credentials')
    args = parser.parse_args()
    ima = None
    try:
        if args.session:
            creds = json.loads(sys.stdin.readline())
            ima = Ima(creds.get('client_id'), creds.get('api_key')); del creds
            print(json.dumps({'status': 'connected_in_memory'}, ensure_ascii=False), flush=True)
            for line in sys.stdin:
                try:
                    op = json.loads(line)
                    if op.get('action') == 'close': break
                    result = run(ima, op)
                    if op.get('summary_only'):
                        result = {'status': 'ok', 'action': op['action'], 'output': op.get('output')}
                    print(json.dumps(result, ensure_ascii=False), flush=True)
                except Exception as exc:
                    print(json.dumps({'status': 'failed', 'reason': ima.safe_error(exc)}, ensure_ascii=False), flush=True)
        else:
            ima = Ima(); result = run(ima, json.loads(Path(args.operation).read_text(encoding='utf-8')))
            print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'reason': ima.safe_error(exc) if ima else 'credentials/arguments unavailable'}))
        return 1
    return 0

if __name__ == '__main__': sys.exit(main())
