import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.database import DBStudentProfile, DBUser, SessionLocal
from app.identity import new_public_id
from app.main import app
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def test_display_profile_persists_without_changing_learning_or_other_accounts():
    username = new_public_id('display-profile')
    other = new_public_id('display-other')
    image = BytesIO()
    Image.new('RGB', (360, 280), '#297d88').save(image, format='PNG')
    avatar = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        other_headers = auth_headers(client, other)
        other_before = client.get('/api/auth/me', headers=other_headers).json()
        with SessionLocal() as db:
            profile = db.query(DBStudentProfile).filter_by(student_id=username).one()
            profile.major = '人工智能'
            profile.concept_mastery = {'test-topic': 0.72}
            db.commit()
        response = client.patch('/api/auth/me', headers=headers, json={'display_name': '  学习核验员  ', 'avatar_url': avatar})
        assert response.status_code == 200
        saved = response.json()
        assert saved['display_name'] == '学习核验员'
        assert Image.open(BytesIO(base64.b64decode(saved['avatar_url'].split(',')[1]))).size == (256, 199)
        login = client.post('/api/auth/login', data={'username': username, 'password': TEST_PASSWORD}).json()
        assert login['display_name'] == saved['display_name']
        assert login['avatar_url'] == saved['avatar_url']
        assert client.get('/api/auth/me', headers=other_headers).json() == other_before
        with SessionLocal() as db:
            profile = db.query(DBStudentProfile).filter_by(student_id=username).one()
            assert profile.major == '人工智能'
            assert profile.concept_mastery == {'test-topic': 0.72}
            assert db.query(DBUser).filter_by(username=username).one().role == 'student'
        for bad in [
            {'display_name': ' '},
            {'display_name': '测试', 'avatar_url': 'data:image/png;base64,AAAA'},
            {'display_name': '测试', 'role': 'admin'},
        ]:
            assert client.patch('/api/auth/me', headers=headers, json=bad).status_code == 422
            assert client.get('/api/auth/me', headers=headers).json()['avatar_url'] == saved['avatar_url']
        reset = client.patch('/api/auth/me', headers=headers, json={'display_name': '学习核验员', 'avatar_url': ''})
        assert reset.status_code == 200
        assert client.get('/api/auth/me', headers=headers).json()['avatar_url'] == ''
