"""Read-only export of candidates and events from the isolated acceptance DB."""
import argparse
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1] / 'scratch/automatic-generation-r207'


def export(name):
    folder = ROOT / 'runs' / name
    task_id = json.loads((folder / 'submission.json').read_text(encoding='utf-8'))['job_id']
    with sqlite3.connect((ROOT / 'acceptance.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        for filename, query in [('events', 'select * from task_events where task_id=? order by sequence'),
                                ('versions', 'select * from artifact_versions where created_task_id=? order by created_at')]:
            rows = [dict(row) for row in db.execute(query, (task_id,))]
            for row in rows:
                for key in ('payload', 'metadata_json'):
                    if isinstance(row.get(key), str):
                        row[key] = json.loads(row[key])
            (folder / (filename + '.json')).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            print(name, filename, len(rows))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+')
    for name in parser.parse_args().runs:
        export(name)
