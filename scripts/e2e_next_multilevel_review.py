import os,sys,time,socket,sqlite3,subprocess,json,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];O=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',R/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-GOV-06'/'browser-e2e'));D=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',R/'outputs'/'_next_multilevel.db'));P=8796;B=f'http://127.0.0.1:{P}'
def wait(x):
 for _ in range(200):
  with socket.socket() as s:a=s.connect_ex(('127.0.0.1',P))==0
  if a==x:return
  time.sleep(.2)
 raise RuntimeError('port')
def main():
 O.mkdir(parents=True,exist_ok=True)
 for x in O.glob('*'):
  if x.is_file():x.unlink()
 for s in ('','-wal','-shm'):
  x=Path(str(D)+s)
  if x.exists():x.unlink()
 e=os.environ.copy();e.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'g06','EDUMATRIX_DEMO_MODE':'1','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(P),'PYTHONUNBUFFERED':'1'});rep={'checks':{},'screenshots':[]};p=None
 try:
  with (O/'backend.log').open('w') as log:
   p=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=e,stdout=log,stderr=subprocess.STDOUT);wait(1)
   with sync_playwright() as w:
    b=w.chromium.launch(headless=True);c=b.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');q=c.new_page();u={}
    for k in ('author','mentor','manager','admin'):
     n=f'g06_{k}_{int(time.time())}';z=q.request.post(B+'/api/auth/register',data={'username':n,'password':'Review-2026!','display_name':k});u[k]=(n,z.json()['access_token'])
    with sqlite3.connect(D) as d:
     ids={n:i for n,i in d.execute('select username,public_id from users')};d.execute("insert into organizations(id,name,organization_type,status,sharing_policy,created_at) values('g06-org','审核组织','enterprise','active','{}',CURRENT_TIMESTAMP)")
     for k,role in [('author','learner'),('mentor','mentor'),('manager','manager'),('admin','admin')]:d.execute('insert into organization_memberships(id,organization_id,user_public_id,role,status,created_at) values(?,?,?,?,?,CURRENT_TIMESTAMP)',('om-'+k,'g06-org',ids[u[k][0]],role,'active'))
     d.commit()
    h=lambda k:{'Authorization':'Bearer '+u[k][1]};made=q.request.post(B+'/api/v1/multilevel-review/cases',headers=h('author'),data={'organization_id':'g06-org','object_type':'certification','object_id':'cert-demo','object_version':'v1','evidence_snapshot':{'evidence_ids':['e1'],'frozen':True}}).json()['case'];cid=made['id']
    assert q.request.post(f'{B}/api/v1/multilevel-review/cases/{cid}/decisions',headers=h('author'),data={'action':'approve','reason':'作者不能自审','expected_version':1}).status==403
    x=q.request.post(f'{B}/api/v1/multilevel-review/cases/{cid}/decisions',headers=h('mentor'),data={'action':'approve','reason':'一级证据审查通过','expected_version':1}).json();assert q.request.post(f'{B}/api/v1/multilevel-review/cases/{cid}/decisions',headers=h('mentor'),data={'action':'approve','reason':'同人不能跨级','expected_version':2}).status==403
    x=q.request.post(f'{B}/api/v1/multilevel-review/cases/{cid}/decisions',headers=h('manager'),data={'action':'approve','reason':'二级风险复核通过','expected_version':2}).json();x=q.request.post(f'{B}/api/v1/multilevel-review/cases/{cid}/decisions',headers=h('admin'),data={'action':'approve','reason':'最终演示签核通过','expected_version':3}).json();assert x['status']=='signed';rep['checks']={'self_review':403,'repeat_reviewer':403,'status':'signed','decisions':4}
    q.goto(B+'/login');q.evaluate("([t,n])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','teacher');localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_onboarded','true')}",[u['admin'][1],u['admin'][0]]);q.goto(B+'/multilevel-review');q.get_by_text('signed',exact=True).wait_for(timeout=20000);q.screenshot(path=str(O/'01-signed-responsibility-chain.png'),full_page=True);rep['screenshots'].append('01-signed-responsibility-chain.png');q.set_viewport_size({'width':390,'height':844});q.wait_for_timeout(600);assert q.evaluate('document.documentElement.scrollWidth')<=390;q.screenshot(path=str(O/'02-mobile-signed-chain.png'),full_page=True);rep['screenshots'].append('02-mobile-signed-chain.png');c.close();b.close();rep['result']='passed'
 finally:
  if p and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True);p.wait();wait(0)
  if D.exists():
   with sqlite3.connect(D) as a,sqlite3.connect(O/'multilevel_review_evidence.db') as z:a.backup(z);rep['checks']['sqlite']=z.execute('pragma integrity_check').fetchone()[0]
  (O/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8');fs=[]
  for x in O.glob('*'):
   if x.is_file() and x.name!='manifest.json' and not x.name.endswith(('-wal','-shm')):fs.append({'file':x.name,'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()})
  (O/'manifest.json').write_text(json.dumps({'files':fs},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
