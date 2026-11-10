"""Read-only display check of already completed concept experiments."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'
BASE = 'http://127.0.0.1:8944'


def verify(run, persona):
    versions = json.loads((ROOT / 'runs' / run / 'versions.json').read_text(encoding='utf8'))
    version = next(v for v in reversed(versions) if v['metadata_json']['resource_type'] == 'interactive_model')
    out = ROOT / 'browser' / run
    prior = json.loads((out / 'interactive_model-r208-learning.json').read_text(encoding='utf8'))
    assert prior['version_id'] == version['id'] and prior['passed']
    credentials = json.loads((ROOT / 'credentials.local.json').read_text(encoding='utf8'))[persona]
    manifest = json.loads((ROOT / 'inputs.json').read_text(encoding='utf8'))
    result = {'version_id': version['id'], 'checks': [], 'errors': [],
              'scope': 'Read-only expanded content and saved observation; no new model or learning submission.'}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1707, 'height': 900})
        page.on('pageerror', lambda error: result['errors'].append(str(error)))
        auth = page.request.post(BASE + '/api/auth/login', form=credentials)
        assert auth.ok
        auth = auth.json()
        state = {'edumatrix_token': auth['access_token'], 'edumatrix_username': credentials['username'],
                 'edumatrix_student_id': auth.get('student_id') or credentials['username'],
                 'edumatrix_role': 'student', 'edumatrix_onboarded': 'true',
                 'edumatrix_course_id': manifest['course_id']}
        page.add_init_script('Object.entries(' + json.dumps(state) + ').forEach(([k,v])=>localStorage.setItem(k,v))')
        page.goto(BASE + '/workspace/resources/models/' + version['artifact_id'], wait_until='networkidle')
        page.get_by_text('概念与示例', exact=True).click()
        tables = page.locator('details[open] .inc-table')
        expect(tables.first).to_be_visible()
        widest = max(range(tables.count()), key=lambda i: tables.nth(i).locator('thead th').count())
        table = tables.nth(widest)
        for width in [1707, 1100]:
            page.set_viewport_size({'width': width, 'height': 900})
            table.scroll_into_view_if_needed()
            table.evaluate('(t)=>t.parentElement.scrollLeft=0')
            assert table.locator('th').evaluate_all('(hs)=>hs.every(h=>getComputedStyle(h).whiteSpace==="nowrap")')
            page.screenshot(path=str(out / f'expanded-table-r208k-{width}.png'))
            table.evaluate('(t)=>t.parentElement.scrollLeft=t.parentElement.scrollWidth')
            last = table.locator('thead th').last.bounding_box()
            bounds = table.locator('..').bounding_box()
            assert last['x'] + last['width'] <= bounds['x'] + bounds['width'] + 1
            assert last['x'] >= bounds['x'] - 1
            page.screenshot(path=str(out / f'expanded-table-end-r208k-{width}.png'))
            overflow = page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
            assert not overflow
            meta = page.locator('.observation-meta > span').first.inner_text()
            assert '/' not in meta and '字' in meta
            result['checks'].append({'width': width, 'table_columns': table.locator('th').count(),
                'headers_horizontal': True, 'last_column_accessible': True,
                'page_horizontal_overflow': overflow, 'observation_count': meta})
        browser.close()
    assert not result['errors']
    result['passed'] = True
    (out / 'expanded-content-r208k.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--persona', default='software_developer')
    args = parser.parse_args()
    verify(args.run, args.persona)
