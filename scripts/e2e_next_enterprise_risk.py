import os,sys,time,socket,sqlite3,subprocess,json,hashlib
from pathlib import Path
from datetime import datetime,timedelta
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];O=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',R/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-GOV-08'/'browser-e2e'));D=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',R/'outputs'/'_next_enterprise_risk.db'));P=8798;B=f'http://127.0.0.1:{P}'
def wait(x):
 for _ in range(225):
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
 e=os.environ.copy();e.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'g08','EDUMATRIX_DEMO_MODE':'1','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(P),'PYTHONUNBUFFERED':'1'});rep={'schema_version':'next.nc-gov-08-browser-e2e.v1','checks':{},'screenshots':[]};p=None
 try:
  with (O/'backend.log').open('w',encoding='utf-8') as log:
   p=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=e,stdout=log,stderr=subprocess.STDOUT);wait(1)
   with sync_playwright() as w:
    b=w.chromium.launch(headless=True);c=b.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');q=c.new_page();stamp=str(int(time.time()));users={}
    for k in ('admin','l1','l2','l3','l4'):
     n=f'g08_{k}_{stamp}';z=q.request.post(B+'/api/auth/register',data={'username':n,'password':'Risk-2026!','display_name':k});assert z.ok;users[k]=(n,z.json()['access_token'])
    with sqlite3.connect(D) as d:
     d.execute("update users set role='admin' where username=?",(users['admin'][0],));d.commit()
    h={'Authorization':'Bearer '+users['admin'][1]};boot=q.request.post(B+'/api/v1/m6/demo/bootstrap',headers=h);assert boot.ok;identity=boot.json();org=identity['organization_id'];ws=q.request.get(B+f'/api/v1/m6/enterprise/workspace?organization_id={org}',headers=h).json()['selected'];cohort=ws['assignment']['cohort_id'];level=ws['assignment']['standard_snapshot']['job_level_id']
    with sqlite3.connect(D) as d:
     ids={n:i for n,i in d.execute('select username,public_id from users')};learners=[ids[users[k][0]] for k in ('l1','l2','l3','l4')]
     # Replace bootstrap population with four deterministic synthetic learners.
     d.execute("delete from training_assignments where organization_id=?",(org,));d.execute("delete from organization_memberships where organization_id=? and role='learner'",(org,))
     for i,u in enumerate(learners):
      d.execute("insert into organization_memberships(id,organization_id,user_public_id,role,status,created_at) values(?,?,?,?,?,datetime('now','-40 day'))",(f'g08-om-{i}',org,u,'learner','active'))
      d.execute("insert into training_assignments(id,organization_id,cohort_id,learner_public_id,assignment_source,status,assigned_at) values(?,?,?,?,?,?,datetime('now','-20 day'))",(f'g08-ta-{i}',org,cohort,u,'organization','completed' if i==0 else 'assigned'))
     d.execute("insert into certifications(id,organization_id,learner_public_id,job_level_id,standard_snapshot,evidence_ids,status,issued_at,expires_at,retraining_rule,lock_version) values(?,?,?,?,?,'[]','active',datetime('now','-10 day'),datetime('now','+30 day'),'{}',1)",('g08-cert-0',org,learners[0],level,'{"version":"demo"}'))
     d.execute("insert into certifications(id,organization_id,learner_public_id,job_level_id,standard_snapshot,evidence_ids,status,issued_at,expires_at,retraining_rule,lock_version) values(?,?,?,?,?,'[]','expired',datetime('now','-300 day'),datetime('now','-20 day'),'{}',1)",('g08-cert-1',org,learners[1],level,'{"version":"demo"}'))
     d.execute("insert into retraining_tasks(id,certification_id,organization_id,learner_public_id,trigger_type,trigger_key,title,due_at,status,rule_snapshot,created_at) values('g08-task','g08-cert-1',?,?, 'expired','g08','逾期复训',datetime('now','-2 day'),'assigned','{}',datetime('now','-10 day'))",(org,learners[1]))
     d.commit()
    denied=q.request.get(B+f'/api/v1/enterprise-risk/workspace?organization_id={org}',headers={'Authorization':'Bearer '+users['l1'][1]});assert denied.status==403;rep['checks']['learner_forbidden']=403
    q.goto(B+'/login');q.evaluate("([t,n])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_onboarded','true')}",[users['admin'][1],users['admin'][0]]);q.goto(B+'/enterprise-risk');q.locator('.risk-page h2').wait_for(timeout=20000);q.get_by_role('button',name='生成近 30 天冻结报告').click();q.get_by_text('匿名人员下钻',exact=True).wait_for(timeout=20000);body=q.locator('.detail').inner_text();assert all(u not in body for u in learners) and 'EMP-' in body;q.screenshot(path=str(O/'01-anonymous-risk-dashboard.png'),full_page=True);rep['screenshots'].append('01-anonymous-risk-dashboard.png');q.get_by_role('button',name='已知悉').click();q.get_by_text('acknowledge · open → acknowledged',exact=True).wait_for();q.get_by_role('button',name='关闭报告').click();q.get_by_text('close · acknowledged → closed',exact=True).wait_for();q.reload(wait_until='domcontentloaded');q.get_by_text('close · acknowledged → closed',exact=True).wait_for(timeout=20000);q.get_by_role('button',name='刷新企业风险').wait_for(state='visible');q.wait_for_timeout(600);q.screenshot(path=str(O/'02-human-disposition-chain.png'),full_page=True);rep['screenshots'].append('02-human-disposition-chain.png');q.set_viewport_size({'width':390,'height':844});q.wait_for_timeout(700);width=q.evaluate('document.documentElement.scrollWidth');assert width<=390;q.screenshot(path=str(O/'03-mobile-risk-workspace.png'),full_page=True);rep['screenshots'].append('03-mobile-risk-workspace.png');rep['checks']['mobile']={'scroll_width':width};rep['checks']['sufficient_sample']={'population':4,'identities_exposed':False,'decision_count':2}
    with sqlite3.connect(D) as d:
     d.execute("insert into organizations(id,name,organization_type,status,sharing_policy,created_at) values('g08-small','小样本组织','enterprise','active','{}',CURRENT_TIMESTAMP)");d.execute("insert into organization_memberships(id,organization_id,user_public_id,role,status,created_at) values('g08-small-admin','g08-small',?,'admin','active',CURRENT_TIMESTAMP)",(ids[users['admin'][0]],))
     for i,u in enumerate(learners[:2]):d.execute("insert into organization_memberships(id,organization_id,user_public_id,role,status,created_at) values(?, 'g08-small',?,'learner','active',CURRENT_TIMESTAMP)",(f'g08-small-{i}',u))
     d.commit()
    now=datetime.utcnow();period={'period_start':(now-timedelta(days=30)).isoformat(),'period_end':now.isoformat()};small=q.request.post(B+'/api/v1/enterprise-risk/reports',headers=h,data={'organization_id':'g08-small',**period});assert small.ok;small_report=small.json()['report'];assert small_report['privacy']['sample_state']=='suppressed' and not small_report['learners'] and all(m['value'] is None for m in small_report['metrics']);rep['checks']['small_sample']={'population':2,'suppressed':True,'drilldown':0};c.close();b.close();rep['result']='passed'
 finally:
  if p and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True);p.wait();wait(0)
  if D.exists():
   with sqlite3.connect(D) as a,sqlite3.connect(O/'enterprise_risk_evidence.db') as z:a.backup(z);rep['checks']['sqlite']=z.execute('pragma integrity_check').fetchone()[0]
  (O/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8');fs=[]
  for x in O.glob('*'):
   if x.is_file() and x.name!='manifest.json' and not x.name.endswith(('-wal','-shm')):fs.append({'file':x.name,'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()})
  (O/'manifest.json').write_text(json.dumps({'schema_version':'next.nc-gov-08-manifest.v1','files':fs},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
