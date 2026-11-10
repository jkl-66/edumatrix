"""Check the actual runtime archive without displaying development credentials."""
from pathlib import Path
import hashlib
import json
import zipfile
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'outputs/current-runtime-20261110'


def main():
    archive_path=OUT/'EduMatrix_当前运行包.zip'
    secrets=[v.encode() for k,v in dotenv_values(ROOT/'.env').items() if v and len(v)>=12
             and any(word in k.upper() for word in ['KEY','SECRET','TOKEN','PASSWORD'])]
    hits=[]
    with zipfile.ZipFile(archive_path) as archive:
        names=archive.namelist()
        assert len(names)==len(set(names)), 'Duplicate archive paths'
        assert not any(Path(n).name=='.env' or n.endswith(('.db-wal','.db-shm','.local.json'))
                       or any(part in {'.venv','node_modules','.git'} for part in Path(n).parts) for n in names)
        required=['run.py','launch.ps1','install_and_run.bat','stop_services.bat','edumatrix.db',
            'frontend/dist/index.html','frontend/dist/demo-accounts.json','requirements-lock.txt',
            'README_作品运行说明.txt','THIRD_PARTY_RUNTIME.md','data/models/multilingual-e5-small/model.safetensors',
            'packaging/wheels/hipporag-2.0.0a5-py3-none-any.whl']
        assert set(required).issubset(names)
        max_size=max([len(s) for s in secrets] or [1])
        for name in names:
            with archive.open(name) as stream:
                tail=b''
                while block:=stream.read(2*1024*1024):
                    data=tail+block
                    if any(secret in data for secret in secrets):hits.append(name);break
                    tail=data[-max_size:]
        assert not hits, 'Development credentials present in archive entries: '+str(hits)
        lock=archive.read('requirements-lock.txt').decode('utf8')
        assert 'file:///' not in lock and 'hipporag-2.0.0a5' in lock
        assert archive.read('requirements.txt').decode('utf8') == lock
        assert 'EduMatrix2026!' in archive.read('README.md').decode('utf8')
        accounts=json.loads(archive.read('frontend/dist/demo-accounts.json'))
        assert {v['username'] for v in accounts.values()}=={'learner','teacher','admin'}
        manifest=json.loads(archive.read('PACKAGE_MANIFEST.json'))
        vectors=manifest['data']['public_course_vectors']
        assert vectors['count']>0 and not vectors['contains_original_text']
        assert hashlib.sha256(archive.read('embeddings_cache.db')).hexdigest()==vectors['sha256']
        report={'passed':True,'files':len(names),'bytes':archive_path.stat().st_size,
                'public_course_vectors':vectors['count'],
                'development_secret_matches':hits,'required_assets':required,
                'archive_integrity_error':archive.testzip()}
        assert report['archive_integrity_error'] is None
    digest=hashlib.file_digest(archive_path.open('rb'),'sha256').hexdigest()
    assert digest in (OUT/'PACKAGE_SHA256.txt').read_text('utf8')
    report['sha256']=digest
    (OUT/'PACKAGE_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:report[k] for k in ['passed','files','bytes','development_secret_matches']},ensure_ascii=False))


if __name__=='__main__':main()
