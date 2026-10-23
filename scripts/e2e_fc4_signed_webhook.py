"""Verify FC4 signed webhook failure, dead-letter recovery and replay-safe receipt UI."""
from __future__ import annotations
import hashlib,json,os,socket,sqlite3,subprocess,sys,time
from pathlib import Path
from playwright.sync_api import Page,sync_playwright

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
OUTPUT=Path(os.environ.get('EDUMATRIX_E2E_OUTPUT_DIR',ROOT/'outputs'/'FC_比赛功能完全体'/'evidence'/'FC4-05A'/'browser-e2e'))
DB_PATH=Path(os.environ.get('EDUMATRIX_E2E_DB_PATH',ROOT/'outputs'/'_fc4_signed_webhook_runtime.db'))
EVIDENCE_DB=OUTPUT/'fc4_signed_webhook_evidence.db';PORT=int(os.environ.get('EDUMATRIX_E2E_PORT','8835'));BASE=f'http://127.0.0.1:{PORT}'
USERNAME='fc4_webhook_admin';PASSWORD='FC4-signed-webhook-e2e-2026!'
def wait_port(open_,timeout=45):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        with socket.socket() as s:s.settimeout(.25);available=s.connect_ex(('127.0.0.1',PORT))==0
        if available is open_:return
        time.sleep(.2)
    raise RuntimeError(f'port {PORT} state timeout')
def stop(process):
    if not process or process.poll() is not None:return
    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,text=True,timeout=15)
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:pass
    wait_port(False,15)
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def shot(page:Page,name):
    path=OUTPUT/f'{name}.png';page.screenshot(path=str(path),full_page=True);return path.name
def manifest():
    files=[{'file':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!='manifest.json' and not p.name.endswith(('-wal','-shm'))]
    (OUTPUT/'manifest.json').write_text(json.dumps({'schema_version':'fc4.signed-webhook-e2e-manifest.v1','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def login(page):
    r=page.request.post(f'{BASE}/api/auth/login',form={'username':USERNAME,'password':PASSWORD});assert r.ok,r.text();return r.json()
def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for p in OUTPUT.iterdir():
        if p.is_file():p.unlink()
    for suffix in ('','-wal','-shm'):
        p=Path(f'{DB_PATH}{suffix}')
        if p.exists():p.unlink()
    env=os.environ.copy();env.update({'EDUMATRIX_DB_PATH':str(DB_PATH),'EDUMATRIX_AUTH_SECRET_KEY':'fc4-webhook-isolated-secret','EDUMATRIX_LLM_PROVIDER':'deterministic','EDUMATRIX_LLM_MODEL':'deterministic','EDUMATRIX_LLM_API_KEY':'','EDUMATRIX_LLM_ENDPOINT':'','EDUMATRIX_RELOAD':'0','EDUMATRIX_HOST':'127.0.0.1','EDUMATRIX_PORT':str(PORT),'PYTHONUNBUFFERED':'1'});os.environ.update(env)
    from app.auth import get_password_hash
    from app.database import DBUser,SessionLocal,init_db
    init_db()
    with SessionLocal() as db:db.add(DBUser(username=USERNAME,hashed_password=get_password_hash(PASSWORD),role='admin',display_name='FC4 Webhook 管理员'));db.commit()
    report={'scope':'signed minimal webhook envelope, HMAC failure, five-attempt dead letter, explicit requeue, local acceptance, refresh and mobile','started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'checks':{},'screenshots':[]};backend=None
    try:
        with (OUTPUT/'backend.log').open('w',encoding='utf-8') as log:
            backend=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={'width':1440,'height':1000},locale='zh-CN');page=context.new_page()
                try:
                    admin=login(page);headers={'Authorization':f"Bearer {admin['access_token']}"};bootstrap=page.request.post(f'{BASE}/api/v1/m6/demo/bootstrap',headers=headers);assert bootstrap.ok,bootstrap.text();org_id=bootstrap.json()['organization_id']
                    from app.database import SessionLocal as RuntimeSession,DBTrainingAssignment
                    with RuntimeSession() as db:
                        assignment=db.query(DBTrainingAssignment).filter_by(organization_id=org_id).order_by(DBTrainingAssignment.assigned_at).first();assert assignment is not None;assignment.status='completed';assignment_id=assignment.id;db.commit()
                    page.goto(f'{BASE}/login',wait_until='networkidle');page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','FC4 Webhook 管理员');localStorage.setItem('edumatrix_onboarded','true')}""",[admin['access_token'],USERNAME]);page.goto(f'{BASE}/integration-sandbox',wait_until='networkidle')
                    page.get_by_text('签名 Webhook',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('尚未建立本地签名接收端',exact=True).wait_for(state='visible');report['screenshots'].append(shot(page,'01-webhook-empty'))
                    page.get_by_role('button',name='初始化接收端').click();page.get_by_text('HMAC-SHA256',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('姓名/邮箱/分数/证据正文均排除',exact=True).wait_for(state='visible');report['screenshots'].append(shot(page,'02-endpoint-ready'))
                    candidate=page.locator('.candidate-command').filter(has_text='training.assignment.completed').filter(has_text=assignment_id);candidate.wait_for(state='visible',timeout=20000);candidate.click();page.get_by_text('training.assignment.completed',exact=True).wait_for(state='visible',timeout=20000)
                    page.locator('.webhook-event-row').filter(has_text='training.assignment.completed').get_by_role('button',name='签名队列').click();page.locator('.webhook-delivery-row').get_by_text('等待发送',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'03-event-queued'))
                    ws=page.request.get(f'{BASE}/api/v1/local-webhooks/workspace?organization_id={org_id}',headers=headers).json();delivery=ws['deliveries'][0];event=ws['events'][0];assert set(event['payload'].keys())=={'id','type','schema_version','occurred_at','organization_id','data'};encoded=json.dumps(event['payload'],ensure_ascii=False);assert not any(term in encoded for term in ('email','score','evidence_body','api_key'))
                    for _ in range(5):
                        r=page.request.post(f"{BASE}/api/v1/local-webhooks/deliveries/{delivery['id']}/send",headers=headers,data={'fault':'invalid_signature'});assert r.ok,r.text()
                    page.reload(wait_until='networkidle');page.locator('.webhook-delivery-row').get_by_text('死信',exact=True).wait_for(state='visible',timeout=20000);assert page.get_by_text('signature_invalid',exact=True).count()>=1;report['screenshots'].append(shot(page,'04-signature-dead-letter'))
                    page.locator('.webhook-delivery-row').get_by_role('button',name='显式重入队').click();page.locator('.webhook-delivery-row').get_by_text('等待发送',exact=True).wait_for(state='visible',timeout=20000);page.locator('.webhook-delivery-row').get_by_role('button',name='签名发送').click();page.get_by_text('已验签接收',exact=True).wait_for(state='visible',timeout=20000);report['screenshots'].append(shot(page,'05-signed-accepted'))
                    page.reload(wait_until='networkidle');page.get_by_text('已验签接收',exact=True).wait_for(state='visible',timeout=20000);page.get_by_text('accepted',exact=True).wait_for(state='visible')
                    final=page.request.get(f'{BASE}/api/v1/local-webhooks/workspace?organization_id={org_id}',headers=headers).json();delivery=final['deliveries'][0];assert delivery['status']=='delivered' and delivery['attempt_count']==6;assert len([x for x in final['receipts'] if x['outcome']=='rejected'])==5;assert len([x for x in final['receipts'] if x['outcome']=='accepted'])==1;assert final['security']['secret_returned_by_api'] is False;assert 'signing_secret' not in json.dumps(final)
                    page.set_viewport_size({'width':390,'height':844});page.reload(wait_until='networkidle');page.get_by_text('已验签接收',exact=True).wait_for(state='visible',timeout=20000);doc=page.evaluate('document.documentElement.scrollWidth');assert doc<=390;report['screenshots'].append(shot(page,'06-mobile-refresh'))
                    report['checks']={'endpoint_count':len(final['endpoints']),'event_type':final['events'][0]['event_type'],'minimal_payload_fields':sorted(final['events'][0]['payload'].keys()),'delivery_status':delivery['status'],'delivery_attempt_count':delivery['attempt_count'],'rejected_receipts':len([x for x in final['receipts'] if x['outcome']=='rejected']),'accepted_receipts':len([x for x in final['receipts'] if x['outcome']=='accepted']),'secret_returned_by_api':final['security']['secret_returned_by_api'],'replay_guards':final['security']['replay_guards'],'refresh_recovered':True,'mobile':{'width':390,'document_width':doc}};report['result']='passed'
                finally:context.close();browser.close()
    except Exception as exc:report['result']='failed';report['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        report['finished_at']=time.strftime('%Y-%m-%dT%H:%M:%S%z');stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source,sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target);report.setdefault('checks',{})['sqlite_integrity']=target.execute('PRAGMA integrity_check').fetchone()[0];report['checks']['migration_052']=target.execute("SELECT COUNT(*) FROM schema_migrations WHERE version='20260805_052'").fetchone()[0]==1;report['checks']['webhook_events']=target.execute('SELECT COUNT(*) FROM webhook_events').fetchone()[0];report['checks']['accepted_nonces']=target.execute('SELECT COUNT(*) FROM webhook_accepted_nonces').fetchone()[0];report['checks']['receipts']=target.execute('SELECT COUNT(*) FROM webhook_receipts').fetchone()[0]
        (OUTPUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');manifest()
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
