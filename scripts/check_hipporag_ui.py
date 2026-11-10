"""Read the persisted comparison in the real UI and follow a source citation."""
import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--storage-state', required=True)
    parser.add_argument('--version', default='r190')
    args = parser.parse_args()
    root = Path(args.output)
    screenshots = Path('scratch/validation-20261025/hipporag-ui-'+args.version)
    screenshots.mkdir(parents=True, exist_ok=True)
    report = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(storage_state=args.storage_state,
            viewport={'width': 1707, 'height': 900}, device_scale_factor=1.5)
        page = context.new_page()
        page.set_default_timeout(60000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        for mode in ('hybrid', 'hipporag2'):
            answer = json.loads((root/f'answer-{mode}.json').read_text(encoding='utf-8'))
            url = 'http://127.0.0.1:8944/chat?conversation_id='+answer['conversation_id']
            page.goto(url, wait_until='networkidle')
            expect(page.get_by_test_id('focused-chat-workspace')).to_be_visible()
            stored = page.evaluate('''async id => {
                const r=await fetch('/api/v1/chat/conversations/'+id,
                    {headers:{Authorization:'Bearer '+localStorage.getItem('edumatrix_token')}});
                if(!r.ok)throw Error(r.status);return r.json();
            }''', answer['conversation_id'])
            message = next(item for item in stored['messages'] if item['id'] == answer['assistant_message_id'])
            assert message['status']=='completed' and message['content'].strip()
            expect(page.locator('.assistant-answer').last).to_contain_text(message['content'].splitlines()[0].strip('#* '))
            page.screenshot(path=str(screenshots/f'{mode}-answer.png'), full_page=True)
            page.get_by_role('button', name='参考内容', exact=True).last.click()
            sources = page.get_by_test_id('chat-source-list')
            expect(sources).to_be_visible()
            citations = sources.locator('.source-citation__action')
            assert citations.count() > 0
            page.screenshot(path=str(screenshots/f'{mode}-sources.png'), full_page=True)
            citations.first.click()
            page.wait_for_url('**/knowledge/documents/**')
            expect(page.locator('.reader-main')).to_be_visible()
            query = parse_qs(urlparse(page.url).query)
            assert query.get('source_ref_id')
            assert query.get('char_start')
            page.screenshot(path=str(screenshots/f'{mode}-source-jump.png'), full_page=True)
            report.append({'mode':mode, 'conversation_url':url, 'message_id':message['id'],
                           'persisted_complete':True, 'citation_click':True, 'reader_url':page.url,
                           'screenshots':str(screenshots), 'source_count':len(message['sourceRefs'])})
            page.goto(url, wait_until='networkidle')
            page.reload(wait_until='networkidle')
            expect(page.locator('.assistant-answer').last).not_to_be_empty()
        browser.close()
    report_name = 'ui-verification.json' if args.version == 'r190' else f'ui-verification-{args.version}.json'
    (root/report_name).write_text(json.dumps({'cases':report,'page_errors':errors},
        ensure_ascii=False,indent=2),encoding='utf-8')
    assert not errors, errors


if __name__ == '__main__':
    main()
