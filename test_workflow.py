import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from models import db, User, Hostel, Application, Group, GroupMember
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

def test_full_booking_invitation_lifecycle(client):
    # 1. Login as CB.SC.U4CSE24001 (Female)
    l1 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token1 = l1.get_json()['access_token']

    # 2. Submit application with roommate invite to CB.SC.U4CSE24002 (Female)
    ananya = Hostel.query.filter_by(code='MYT').first()
    varnika = Hostel.query.filter_by(code='GAR').first()
    res_app = client.post('/api/student/application', headers={'Authorization': f'Bearer {token1}'}, json={
        'roommate_mode': 'group',
        'friend_rolls': ['CB.SC.U4CSE24002'],
        'preferences': [
            {'hostel_id': ananya.id, 'sharing_type': 2},
            {'hostel_id': varnika.id, 'sharing_type': 3}
        ],
        'preferred_floor': 1,
        'flex_floor': True
    })
    assert res_app.status_code == 201
    reg_num = res_app.get_json()['registration_number']
    assert 'SW-2026-' in reg_num

    # 3. Login as CB.SC.U4CSE24002 and view incoming invitations
    l2 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24002', 'password': 'student123'})
    token2 = l2.get_json()['access_token']

    res_inv = client.get('/api/student/invitations', headers={'Authorization': f'Bearer {token2}'})
    assert res_inv.status_code == 200
    invites = res_inv.get_json()['invitations']
    assert len(invites) == 1
    inv_id = invites[0]['invitation_id']

    # 4. Accept invitation
    res_accept = client.post(f'/api/student/invitations/{inv_id}/respond', headers={'Authorization': f'Bearer {token2}'}, json={
        'action': 'accept'
    })
    assert res_accept.status_code == 200
    assert res_accept.get_json()['group_status'] == 'confirmed'

def test_gender_mismatch_invite_rejected(client):
    # CB.SC.U4CSE24001 (Female) attempts to invite CB.SC.U4CSE24003 (Male) -> Must be rejected!
    l1 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token1 = l1.get_json()['access_token']

    ananya = Hostel.query.filter_by(code='MYT').first()
    varnika = Hostel.query.filter_by(code='GAR').first()
    res = client.post('/api/student/application', headers={'Authorization': f'Bearer {token1}'}, json={
        'roommate_mode': 'group',
        'friend_rolls': ['CB.SC.U4CSE24003'],
        'preferences': [
            {'hostel_id': ananya.id, 'sharing_type': 2},
            {'hostel_id': varnika.id, 'sharing_type': 3}
        ]
    })
    assert res.status_code == 400
    assert 'Cross-gender roommate pairing is not permitted' in res.get_json()['error']

def test_sharing_capacity_smaller_than_group_rejected(client):
    # Group of 3 trying to choose 2-sharing room -> Must be rejected!
    l1 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token1 = l1.get_json()['access_token']

    ananya = Hostel.query.filter_by(code='MYT').first()
    varnika = Hostel.query.filter_by(code='GAR').first()
    res = client.post('/api/student/application', headers={'Authorization': f'Bearer {token1}'}, json={
        'roommate_mode': 'group',
        'friend_rolls': ['CB.SC.U4CSE24002', 'CB.SC.P2CSE25001'], # 3 members
        'preferences': [
            {'hostel_id': ananya.id, 'sharing_type': 2}, # 2-sharing cannot fit 3 members!
            {'hostel_id': varnika.id, 'sharing_type': 2}
        ]
    })
    assert res.status_code == 400
    assert 'cannot fit your group of 3' in res.get_json()['error']
