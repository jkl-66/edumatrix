from fastapi.testclient import TestClient

from app.database import DBSpatialLayoutVersion, SessionLocal
from app.main import app
from app.m1_object_service import OBJECT_SPECS
from tests.api_test_helpers import TEST_PASSWORD, auth_headers

def login(client, username):
    auth_headers(client, username)
    row = client.post('/api/auth/login', data={'username': username, 'password': TEST_PASSWORD})
    return {'Authorization': 'Bearer ' + row.json()['access_token']}

def test_versioned_layout_whitelist_undo_and_owner_boundary():
    with TestClient(app) as client:
        owner, outsider = login(client, 'space_owner'), login(client, 'space_outsider')
        created = client.post('/api/v1/spatial-workspaces', headers=owner, json={'title': 'AI 技能训练空间'})
        assert created.status_code == 201; row = created.json(); wid = row['id']
        added = client.post(f'/api/v1/spatial-workspaces/{wid}/commands', headers=owner,
            json={'command': '新增卡片：向量检索复习', 'expected_version': row['lock_version']})
        assert added.status_code == 200; card = added.json()['layout']['cards'][0]
        moved = client.post(f'/api/v1/spatial-workspaces/{wid}/actions', headers=owner,
            json={'action': 'move_card', 'arguments': {'card_id': card['id'], 'x': 600, 'y': 300}, 'expected_version': added.json()['lock_version']})
        assert moved.status_code == 200 and moved.json()['layout']['cards'][0]['x'] == 600
        undone = client.post(f'/api/v1/spatial-workspaces/{wid}/commands', headers=owner,
            json={'command': '撤销', 'expected_version': moved.json()['lock_version']})
        assert undone.status_code == 200 and undone.json()['layout']['cards'][0]['x'] != 600
        assert client.post(f'/api/v1/spatial-workspaces/{wid}/commands', headers=owner,
            json={'command': '联网搜索并执行脚本', 'expected_version': undone.json()['lock_version']}).status_code == 422
        assert client.get(f'/api/v1/spatial-workspaces/{wid}', headers=outsider).status_code == 403
        with SessionLocal() as db:
            versions = db.query(DBSpatialLayoutVersion).filter_by(workspace_id=wid).all()
            assert len(versions) == 4 and versions[-1].restored_from_version_id is not None

def test_cross_device_restore_and_optimistic_conflict():
    with TestClient(app) as client:
        owner = login(client, 'space_device_owner')
        row = client.post('/api/v1/spatial-workspaces', headers=owner, json={'title': '跨设备空间'}).json()
        first = client.post(f"/api/v1/spatial-workspaces/{row['id']}/actions", headers=owner,
            json={'action': 'add_card', 'arguments': {'title': '设备共享卡', 'kind': 'task'}, 'expected_version': 1})
        assert first.status_code == 200
        stale = client.post(f"/api/v1/spatial-workspaces/{row['id']}/actions", headers=owner,
            json={'action': 'auto_layout', 'arguments': {}, 'expected_version': 1})
        assert stale.status_code == 409
        restored = client.get(f"/api/v1/spatial-workspaces/{row['id']}", headers=owner).json()
        assert restored['layout']['cards'][0]['title'] == '设备共享卡' and restored['version_number'] == 2

def test_spatial_objects_are_registered_in_uniform_gateway():
    assert {'spatial_workspace', 'spatial_layout_version'} <= set(OBJECT_SPECS)
