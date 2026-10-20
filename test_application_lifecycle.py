import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from models import db, User, Hostel, Application
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

def test_same_hostel_different_sharing_allowed(client):
    """
    Verifies that choosing the SAME hostel with DIFFERENT sharing capacities
    across ranked preferences is valid and accepted.
    Example:
    Pref 1: Mythreyi Bhavanam, 2-Sharing
    Pref 2: Mythreyi Bhavanam, 4-Sharing
    Pref 3: Gargi Bhavanam, 3-Sharing
    """
    l1 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token = l1.get_json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    mythreyi = Hostel.query.filter_by(code='MYT').first()
    gargi = Hostel.query.filter_by(code='GAR').first()

    payload = {
        'roommate_mode': 'none',
        'preferences': [
            {'hostel_id': mythreyi.id, 'sharing_type': 2, 'floor': 1, 'flex_floor': True},
            {'hostel_id': mythreyi.id, 'sharing_type': 4, 'floor': 2, 'flex_floor': True},
            {'hostel_id': gargi.id, 'sharing_type': 3, 'floor': 1, 'flex_floor': True},
        ]
    }

    res = client.post('/api/student/application', headers=headers, json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert 'registration_number' in data
    app_data = data['application']
    assert len(app_data['preferences']) == 3
    assert app_data['preferences'][0]['hostel_id'] == mythreyi.id
    assert app_data['preferences'][0]['sharing_type'] == 2
    assert app_data['preferences'][1]['hostel_id'] == mythreyi.id
    assert app_data['preferences'][1]['sharing_type'] == 4
    assert app_data['preferences'][2]['hostel_id'] == gargi.id
    assert app_data['preferences'][2]['sharing_type'] == 3

def test_identical_preference_duplicate_rejected(client):
    """
    Verifies that identical (hostel, sharing) combinations are rejected.
    """
    l1 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token = l1.get_json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    mythreyi = Hostel.query.filter_by(code='MYT').first()

    payload = {
        'roommate_mode': 'none',
        'preferences': [
            {'hostel_id': mythreyi.id, 'sharing_type': 2},
            {'hostel_id': mythreyi.id, 'sharing_type': 2}, # Duplicate!
        ]
    }

    res = client.post('/api/student/application', headers=headers, json=payload)
    assert res.status_code == 400
    assert 'unique' in res.get_json()['error']

def test_modify_application_before_deadline(client):
    """
    Verifies modifying/editing an existing submitted application.
    """
    l1 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token = l1.get_json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    mythreyi = Hostel.query.filter_by(code='MYT').first()
    gargi = Hostel.query.filter_by(code='GAR').first()

    # Initial submission
    client.post('/api/student/application', headers=headers, json={
        'roommate_mode': 'none',
        'preferences': [
            {'hostel_id': mythreyi.id, 'sharing_type': 2},
            {'hostel_id': gargi.id, 'sharing_type': 3},
        ]
    })

    # Modify preferences using PUT
    res_mod = client.put('/api/student/application', headers=headers, json={
        'preferences': [
            {'hostel_id': mythreyi.id, 'sharing_type': 4}, # Changed from 2 to 4 sharing
            {'hostel_id': mythreyi.id, 'sharing_type': 2}, # Same hostel diff sharing
            {'hostel_id': gargi.id, 'sharing_type': 3},
        ]
    })
    assert res_mod.status_code == 200
    mod_data = res_mod.get_json()['application']
    assert mod_data['preferences'][0]['sharing_type'] == 4
    assert mod_data['preferences'][1]['sharing_type'] == 2

def test_cancel_application_and_reapply(client):
    """
    Verifies cancelling a submitted application and submitting a new booking again.
    """
    l1 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token = l1.get_json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}

    mythreyi = Hostel.query.filter_by(code='MYT').first()
    gargi = Hostel.query.filter_by(code='GAR').first()

    # Initial submission
    res1 = client.post('/api/student/application', headers=headers, json={
        'roommate_mode': 'none',
        'preferences': [
            {'hostel_id': mythreyi.id, 'sharing_type': 2},
            {'hostel_id': gargi.id, 'sharing_type': 3}
        ]
    })
    assert res1.status_code == 201
    reg1 = res1.get_json()['registration_number']

    # Cancel application
    res_cancel = client.post('/api/student/application/cancel', headers=headers)
    assert res_cancel.status_code == 200
    assert 'cancelled' in res_cancel.get_json()['message']

    # Check status: should have no active application
    res_check = client.get('/api/student/application', headers=headers)
    assert res_check.get_json()['has_application'] is False

    # Book again / reapply
    res_reapply = client.post('/api/student/application', headers=headers, json={
        'roommate_mode': 'none',
        'preferences': [
            {'hostel_id': mythreyi.id, 'sharing_type': 4},
            {'hostel_id': gargi.id, 'sharing_type': 3}
        ]
    })
    assert res_reapply.status_code == 201
    reg2 = res_reapply.get_json()['registration_number']
    assert reg2 != reg1
