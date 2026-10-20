import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from models import db, User
from seed import seed_database

@pytest.fixture(autouse=True)
def setup_db():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with app.app_context():
        db.drop_all()
        db.create_all()
        seed_database()
        yield
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_student_login_valid(client):
    res = client.post('/api/auth/login', json={
        'roll_number': 'cb.sc.u4cse24001', # test case-insensitive using CB roll format
        'password': 'student123'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert 'access_token' in data
    assert data['user']['roll_number'] == 'CB.SC.U4CSE24001'

def test_admin_login_valid(client):
    res = client.post('/api/auth/login', json={
        'roll_number': 'admin',
        'password': 'admin123'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['user']['role'] == 'admin'

def test_login_invalid_password(client):
    res = client.post('/api/auth/login', json={
        'roll_number': 'CB.SC.U4CSE24001',
        'password': 'wrongpassword'
    })
    assert res.status_code == 401
    assert 'Invalid credentials' in res.get_json()['error']

def test_student_lookup_success(client):
    login_res = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token = login_res.get_json()['access_token']
    
    res = client.get('/api/auth/student-lookup/CB.SC.U4CSE24002', headers={'Authorization': f'Bearer {token}'})
    assert res.status_code == 200
    assert res.get_json()['student']['name'] == 'Riya Patel'
