"""Extract full-page text and reference candidates; human review remains required."""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from pypdf import PdfReader

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKC', s).casefold() if c.isalnum())

def locate(raw, pages):
    n = norm(raw)
    first = [p['page'] for p in pages if n[:60] in norm(p['text'])]
    last = [p['page'] for p in pages if n[-60:] in norm(p['text'])]
    if not first or not last or first[0] > last[-1]:
        return [], 'page_locator_unresolved'
    return list(range(first[0], last[-1]+1)), 'text_endpoints_matched_review_required'

def numbered(text):
    matches = list(re.finditer(r'(?m)^\s*(?:\[(\d+)\]|(\d+)\.)\s+', text))
    return [{'number': int(m.group(1) or m.group(2)), 'order': i+1,
             'raw': re.sub(r'\s+', ' ', text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]).strip()}
            for i,m in enumerate(matches)]

def extract(path, sid, legacy=None):
    p = Path(path)
    pages = [{'page': i+1, 'text': page.extract_text() or ''} for i,page in enumerate(PdfReader(p).pages)]
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    result = {'id':sid, 'path':str(p.resolve()), 'sha256':sha, 'pages':pages,
              'references':[], 'status':'candidate_requires_review', 'legacy_reuse':None}
    if legacy:
        old = Path(legacy).read_text(encoding='utf-8-sig')
        found = re.search(r'(?i)SHA(?:-?256)?[^\n]*?([a-f0-9]{64})', old)
        if not found or found.group(1).lower()!=sha: raise ValueError('legacy PDF SHA256 differs/missing; do not reuse')
        section = old.split('## 原文参考文献',1)[-1].split('## 使用约定',1)[0]
        result['references'] = numbered(section)
        result['legacy_reuse'] = {'path':str(Path(legacy).resolve()), 'pdf_hash_matched':True,
                                  'version_review_required':True}
    else:
        starts = [(p['page'],m.end()) for p in pages
                  for m in re.finditer(r'(?im)^\s*(?:REFERENCES|R E F E R E N C E S)\s*$',p['text'])]
        if starts:
            pg,off = starts[-1]
            text = pages[pg-1]['text'][off:]+'\n'+'\n'.join(p['text'] for p in pages[pg:])
            text = re.split(r'(?m)^Disclaimer/Publisher',text)[0]
            text = re.sub(r'(?m)^Technologies \d{4},.*?\d+ of \d+\s*$', '', text)
            result['references'] = numbered(text)
            if not result['references']:
                result['unnumbered_reference_text'] = text
                result['status'] = 'author_year_manual_boundary_review'
    for ref in result['references']:
        ref['pages'],ref['page_status'] = locate(ref['raw'],pages)
        ref['type'] = 'unclassified'
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pdf',required=True);ap.add_argument('--id',required=True)
    ap.add_argument('--output',required=True);ap.add_argument('--legacy')
    args=ap.parse_args()
    result=extract(args.pdf,args.id,args.legacy)
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'id':args.id,'pages':len(result['pages']),'reference_candidates':len(result['references']),
                      'status':result['status'],'unresolved_pages':sum(not x['pages'] for x in result['references'])},ensure_ascii=False))

if __name__=='__main__':main()
