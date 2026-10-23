import os,sys,time,socket,sqlite3,subprocess,json,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];O=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',R/'outputs'/'NEXT_完全体主动开发'/'evidence'/'NC-ECO-03'/'browser-e2e'));D=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',R/'outputs'/'_next_org_market_e2e.db'));P=8801;B=f'http://127.0.0.1:{P}';PW='OrgMarket-2026!'
def wait(x):
 for _ in range(300):
  with socket.socket() as s:a=s.connect_ex(('127.0.0.1',P))==0
  if a==x:return
  time.sleep(.2)
 raise RuntimeError('port')
def state(q,u,r):q.goto(B+'/login');q.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_student_id',n);localStorage.setItem('edumatrix_onboarded','true')}",[u['token'],u['name'],r])
def main():
 O.mkdir(parents=True,exist_ok=True)
 for x in O.glob('*'):
  if x.is_file():x.unlink()
 for s in ('','-wal','-shm'):
  x=Path(str(D)+s)
  if x.exists():x.unlink()
 e=os.environ.copy();e.update({'EDUMATRIX_DB_PATH':str(D),'EDUMATRIX_AUTH_SECRET_KEY':'eco03','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_MULTIMODAL_LLM_API_KEY':'','EDUMATRIX_MULTIMODAL_LLM_ENDPOINT':'','EDUMATRIX_EMBEDDING_PROVIDER':'hash','EDUMATRIX_RELOAD':'0','EDUMATRIX_PORT':str(P),'PYTHONUNBUFFERED':'1','PYTHON_DOTENV_DISABLED':'1'});rep={'schema_version':'next.nc-eco-03-browser-e2e.v1','checks':{},'screenshots':[]};p=None
 try:
  with (O/'backend.log').open('w',encoding='utf-8') as log:
   p=subprocess.Popen([sys.executable,'run.py'],cwd=R,env=e,stdout=log,stderr=subprocess.STDOUT);wait(1)
   with sync_playwright() as w:
    b=w.chromium.launch(headless=True);c=b.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');q=c.new_page();stamp=str(int(time.time()));us={}
    for k in ('manager','learner','outsider'):
     n=f'eco03_{k}_{stamp}';z=q.request.post(B+'/api/auth/register',data={'username':n,'password':PW,'display_name':k});assert z.ok;us[k]={'name':n,'id':z.json()['user_id']}
    oid1=f'org-a-{stamp}';oid2=f'org-b-{stamp}';cid=f'org-course-{stamp}'
    with sqlite3.connect(D) as d:
     d.execute("update users set role='teacher' where public_id=?",(us['manager']['id'],));d.execute("insert into organizations(id,name,organization_type,status,sharing_policy,created_at) values(?,?,'enterprise','active',?,CURRENT_TIMESTAMP)",(oid1,'合成企业甲','{"copy_enabled":true,"allowed_copy_roles":["learner","manager"]}'));d.execute("insert into organizations(id,name,organization_type,status,sharing_policy,created_at) values(?,?,'enterprise','active',?,CURRENT_TIMESTAMP)",(oid2,'合成企业乙','{"copy_enabled":false,"allowed_copy_roles":["manager"]}'))
     for x in ((f'om1-{stamp}',oid1,us['manager']['id'],'manager'),(f'om2-{stamp}',oid1,us['learner']['id'],'learner'),(f'om3-{stamp}',oid2,us['outsider']['id'],'manager')):d.execute("insert into organization_memberships(id,organization_id,user_public_id,role,status,created_at) values(?,?,?,?,'active',CURRENT_TIMESTAMP)",x)
     d.execute("insert into courses(id,version,title,subject,description,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",(cid,'1.0','企业 AI 内训','AI','合成企业内训','CC BY 4.0','private','published',us['manager']['id'],'eco03-v1','{}'));d.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,? ,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f'cm-{stamp}',cid,us['manager']['id'],'teacher','active'));d.execute("insert into course_documents(id,course_id,chapter_order,filename,file_type,file_size,title,content,tags,chunk_count,content_hash,source_path,license_text,status,created_at,updated_at) values(?,?,1,'a.md','md',10,'A','内训正文','[]',1,'h','repo/a.md','CC BY 4.0','published',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f'doc-{stamp}',cid));d.execute("insert into source_documents(id,course_id,title,filename,file_format,content_hash,source_sha256,processed_sha256,file_size,source_path,license_text,uploader_public_id,parser_version,parser_metadata,parse_warnings,processing_error_code,processing_status,created_at,updated_at) values(?,?,'A','a.md','md','h','s','p',10,'repo/a.md','CC BY 4.0',?,'e2e','{}','[]','','ready',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f'src-{stamp}',cid,us['manager']['id']));d.commit()
    for k,u in us.items():z=q.request.post(B+'/api/auth/login',form={'username':u['name'],'password':PW});u['token']=z.json()['access_token'];u['h']={'Authorization':'Bearer '+u['token']}
    state(q,us['manager'],'teacher');q.goto(B+'/organization-marketplace');q.locator('.org-market h2').wait_for(timeout=30000);q.get_by_label('组织范围').select_option(oid1);q.get_by_label('组织市场课程').select_option(cid);q.get_by_label('组织资源标题').fill('企业 AI 内训资源');q.get_by_role('button',name='发布',exact=True).click();q.get_by_text('组织资源已按当前策略冻结发布',exact=True).wait_for();q.wait_for_timeout(600);q.screenshot(path=str(O/'01-manager-private-catalog.png'),full_page=True);rep['screenshots'].append('01-manager-private-catalog.png');row=q.request.get(B+f'/api/v1/organization-marketplace/organizations/{oid1}',headers=us['manager']['h']).json()['items'][0]
    denied=[q.request.get(B+f'/api/v1/organization-marketplace/organizations/{oid1}',headers=us['outsider']['h']),q.request.post(B+f"/api/v1/organization-marketplace/listings/{row['id']}/acquisitions",headers=us['outsider']['h']),q.request.post(B+f"/api/v1/organization-marketplace/listings/{row['id']}/withdraw",headers=us['outsider']['h'],data={'reason':'跨租户禁止撤回私有资源','expected_version':1})];assert [x.status for x in denied]==[403,403,403];rep['checks']['cross_tenant']=[403,403,403]
    state(q,us['learner'],'student');q.goto(B+'/organization-marketplace');q.locator('.org-market h2').wait_for();q.get_by_text('复制策略 开启',exact=True).wait_for();q.get_by_title('获取组织副本').click();q.get_by_text('组织副本已创建：',exact=False).wait_for();q.wait_for_timeout(600);q.screenshot(path=str(O/'02-learner-policy-copy.png'),full_page=True);rep['screenshots'].append('02-learner-policy-copy.png')
    state(q,us['manager'],'teacher');q.goto(B+'/organization-marketplace');q.locator('.org-market h2').wait_for();q.get_by_role('button',name='撤回',exact=True).click();q.get_by_text('资源已撤回，历史副本保持可用',exact=True).wait_for();q.set_viewport_size({'width':390,'height':844});q.wait_for_timeout(800);width=q.evaluate('document.documentElement.scrollWidth');assert width<=390;q.screenshot(path=str(O/'03-mobile-withdrawn-catalog.png'),full_page=True);rep['screenshots'].append('03-mobile-withdrawn-catalog.png')
    with sqlite3.connect(D) as d:a=d.execute('select derived_course_id,source_status from organization_resource_acquisitions').fetchone();cs=d.execute('select status from courses where id=?',(a[0],)).fetchone()[0];docs=d.execute('select count(*) from course_documents where course_id=?',(a[0],)).fetchone()[0]
    assert(a[1],cs,docs)==('withdrawn','published',1);rep['checks'].update({'policy_snapshot':row['policy'],'history':{'source_status':a[1],'course_status':cs,'documents':docs},'mobile_scroll_width':width,'tenant_count':2});c.close();b.close();rep['result']='passed'
 finally:
  if p and p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True);p.wait();wait(0)
  if D.exists():
   with sqlite3.connect(D) as a,sqlite3.connect(O/'organization_marketplace_evidence.db') as z:a.backup(z);rep['checks']['sqlite']=z.execute('pragma integrity_check').fetchone()[0]
  (O/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8');fs=[]
  for x in O.glob('*'):
   if x.is_file() and x.name!='manifest.json' and not x.name.endswith(('-wal','-shm')):fs.append({'file':x.name,'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()})
  (O/'manifest.json').write_text(json.dumps({'schema_version':'next.nc-eco-03-manifest.v1','files':fs},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
