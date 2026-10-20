import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from models import db, User, Hostel, Room, HostelSharingConfig
from seed import seed_database, HOSTELS_SPEC

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

def test_hostel_inventory_exact_counts():
    """
    Validation Rules:
    1. Exactly 13 hostels and 4 floors per hostel.
    2. Exactly 100 rooms on each floor and 5,200 rooms overall.
    3. Every room ID is unique.
    """
    hostels = Hostel.query.all()
    assert len(hostels) == 13, f"Expected 13 hostels, found {len(hostels)}"

    total_rooms = Room.query.count()
    assert total_rooms == 5200, f"Expected 5200 rooms, found {total_rooms}"

    # Global uniqueness: room_code (e.g. MYT-G-101) is unique across all 5,200 rooms
    all_room_codes = [r.room_code for r in Room.query.all()]
    assert len(all_room_codes) == len(set(all_room_codes)), "Duplicate room codes found!"

    floor_prefix_map = {
        1: 'G-',
        2: 'F-',
        3: 'S-',
        4: 'T-'
    }

    for h in hostels:
        assert h.total_floors == 4, f"Hostel {h.name} does not have 4 floors"
        h_rooms = Room.query.filter_by(hostel_id=h.id).all()
        assert len(h_rooms) == 400, f"Hostel {h.name} expected 400 rooms, got {len(h_rooms)}"

        # Within a hostel, all room numbers are unique
        h_room_numbers = [r.room_number for r in h_rooms]
        assert len(h_room_numbers) == len(set(h_room_numbers)), f"Duplicate room numbers in hostel {h.name}!"

        for floor in range(1, 5):
            fl_rooms = [r for r in h_rooms if r.floor == floor]
            assert len(fl_rooms) == 100, f"Hostel {h.name} Floor {floor} expected 100 rooms, got {len(fl_rooms)}"
            
            pfx = floor_prefix_map[floor]
            for r in fl_rooms:
                assert r.room_number.startswith(pfx), f"Invalid room number prefix: {r.room_number} on floor {floor}"
                assert r.room_code == f"{h.code}-{r.room_number}", f"Invalid room_code: {r.room_code}"

def test_mythreyi_bhavanam_distribution():
    """
    Mythreyi Bhavanam (MYT):
    - Floor 1: 46 two-sharing, 8 three-sharing, 46 four-sharing.
    - Floors 2-4: 50 two-sharing, 50 four-sharing.
    - Total: 196 two-sharing, 8 three-sharing (all on Floor 1), 196 four-sharing.
    """
    myt = Hostel.query.filter_by(code='MYT').first()
    assert myt is not None
    assert myt.gender == 'female'

    # Floor 1
    f1_rooms = Room.query.filter_by(hostel_id=myt.id, floor=1).all()
    f1_2share = [r for r in f1_rooms if r.sharing_capacity == 2]
    f1_3share = [r for r in f1_rooms if r.sharing_capacity == 3]
    f1_4share = [r for r in f1_rooms if r.sharing_capacity == 4]
    assert len(f1_2share) == 46
    assert len(f1_3share) == 8
    assert len(f1_4share) == 46

    # Verify three-sharing rooms on Floor 1 have IDs G-147 through G-154 and codes MYT-G-147 through MYT-G-154
    f1_3share_numbers = sorted([r.room_number for r in f1_3share])
    expected_3share_numbers = [f"G-{idx}" for idx in range(147, 155)]
    assert f1_3share_numbers == expected_3share_numbers

    f1_3share_codes = sorted([r.room_code for r in f1_3share])
    expected_3share_codes = [f"MYT-G-{idx}" for idx in range(147, 155)]
    assert f1_3share_codes == expected_3share_codes

    # Floors 2-4
    for fl in [2, 3, 4]:
        fl_rooms = Room.query.filter_by(hostel_id=myt.id, floor=fl).all()
        fl_2share = [r for r in fl_rooms if r.sharing_capacity == 2]
        fl_3share = [r for r in fl_rooms if r.sharing_capacity == 3]
        fl_4share = [r for r in fl_rooms if r.sharing_capacity == 4]
        assert len(fl_2share) == 50
        assert len(fl_3share) == 0, f"Expected 0 three-sharing rooms on MYT floor {fl}"
        assert len(fl_4share) == 50

    # Overall totals
    all_myt_rooms = Room.query.filter_by(hostel_id=myt.id).all()
    assert len([r for r in all_myt_rooms if r.sharing_capacity == 2]) == 196
    assert len([r for r in all_myt_rooms if r.sharing_capacity == 3]) == 8
    assert len([r for r in all_myt_rooms if r.sharing_capacity == 4]) == 196

def test_girls_hostels_distributions():
    """
    Verifies Gargi, Adithi, Savithri, and Kapila room distributions.
    """
    # 1. Gargi (GAR): 200 single, 200 three
    gar = Hostel.query.filter_by(code='GAR').first()
    gar_rooms = Room.query.filter_by(hostel_id=gar.id).all()
    assert len([r for r in gar_rooms if r.sharing_capacity == 1]) == 200
    assert len([r for r in gar_rooms if r.sharing_capacity == 3]) == 200

    # 3. Adithi (ADI): 200 single, 200 four
    adi = Hostel.query.filter_by(code='ADI').first()
    adi_rooms = Room.query.filter_by(hostel_id=adi.id).all()
    assert len([r for r in adi_rooms if r.sharing_capacity == 1]) == 200
    assert len([r for r in adi_rooms if r.sharing_capacity == 4]) == 200

    # 4. Savithri (SAV): 100 single (Floor 1), 150 two, 150 four
    sav = Hostel.query.filter_by(code='SAV').first()
    sav_rooms = Room.query.filter_by(hostel_id=sav.id).all()
    assert len([r for r in sav_rooms if r.sharing_capacity == 1]) == 100
    assert len([r for r in sav_rooms if r.sharing_capacity == 2]) == 150
    assert len([r for r in sav_rooms if r.sharing_capacity == 4]) == 150
    assert len([r for r in sav_rooms if r.sharing_capacity == 3]) == 0

    # 5. Kapila (KAP): 400 single-sharing
    kap = Hostel.query.filter_by(code='KAP').first()
    kap_rooms = Room.query.filter_by(hostel_id=kap.id).all()
    assert len([r for r in kap_rooms if r.sharing_capacity == 1]) == 400

def test_boys_hostels_distributions():
    """
    Verifies Boys' hostels distributions.
    """
    # 6. Agasthya (AGA): 400 four-sharing
    aga = Hostel.query.filter_by(code='AGA').first()
    assert len(Room.query.filter_by(hostel_id=aga.id, sharing_capacity=4).all()) == 400

    # 7. Gauthama (GAU): 400 single-sharing
    gau = Hostel.query.filter_by(code='GAU').first()
    assert len(Room.query.filter_by(hostel_id=gau.id, sharing_capacity=1).all()) == 400

    # 8. Vasishta (VAS): 400 four-sharing
    vas = Hostel.query.filter_by(code='VAS').first()
    assert len(Room.query.filter_by(hostel_id=vas.id, sharing_capacity=4).all()) == 400

    # 9. Sri Vyasa Maharshi (VYA): 400 single-sharing
    vya = Hostel.query.filter_by(code='VYA').first()
    assert len(Room.query.filter_by(hostel_id=vya.id, sharing_capacity=1).all()) == 400

    # 10. Nachiketas (NAC): 400 single-sharing
    nac = Hostel.query.filter_by(code='NAC').first()
    assert len(Room.query.filter_by(hostel_id=nac.id, sharing_capacity=1).all()) == 400

    # 11. Yagnavalkya (YAG): 400 four-sharing
    yag = Hostel.query.filter_by(code='YAG').first()
    assert len(Room.query.filter_by(hostel_id=yag.id, sharing_capacity=4).all()) == 400

    # 12. Kashyapa (KAS): 250 three-sharing, 150 four-sharing
    kas = Hostel.query.filter_by(code='KAS').first()
    kas_rooms = Room.query.filter_by(hostel_id=kas.id).all()
    assert len([r for r in kas_rooms if r.sharing_capacity == 3]) == 250
    assert len([r for r in kas_rooms if r.sharing_capacity == 4]) == 150

    # 13. Bhrigu (BRI): 100 single-sharing (Floor 1), 150 two-sharing, 150 three-sharing
    bri = Hostel.query.filter_by(code='BRI').first()
    bri_rooms = Room.query.filter_by(hostel_id=bri.id).all()
    assert len([r for r in bri_rooms if r.sharing_capacity == 1]) == 100
    assert len([r for r in bri_rooms if r.sharing_capacity == 2]) == 150
    assert len([r for r in bri_rooms if r.sharing_capacity == 3]) == 150

def test_kapila_bhavanam_pg_scholar_restriction(client):
    """
    Rule 6: Verify Kapila is available only to eligible female M.Tech and PhD scholars.
    - CB.SC.U4CSE24001 (female, B.Tech) -> Ineligible, Kapila rejected!
    - CB.SC.P2CSE25001 (female, M.Tech) -> Eligible, Kapila accepted!
    - CB.SC.U4CSE24003 (male, B.Tech) -> Ineligible (gender & PG), Kapila rejected!
    """
    kapila = Hostel.query.filter_by(code='KAP').first()
    assert kapila is not None

    # 1. CB.SC.U4CSE24001 (Female B.Tech) gets eligible hostels
    l1 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    t1 = l1.get_json()['access_token']
    h_res1 = client.get('/api/student/hostels', headers={'Authorization': f'Bearer {t1}'})
    h_data1 = h_res1.get_json()['hostels']
    # Kapila must NOT be in eligible list for B.Tech student
    assert 'Kapila Bhavanam' not in [h['name'] for h in h_data1]

    myt = Hostel.query.filter_by(code='MYT').first()

    # Attempt to submit application for Kapila as B.Tech student
    bad_app = client.post('/api/student/application', headers={'Authorization': f'Bearer {t1}'}, json={
        'roommate_mode': 'none',
        'preferences': [
            {'hostel_id': kapila.id, 'sharing_type': 1, 'floor': 1, 'flex_floor': True},
            {'hostel_id': myt.id, 'sharing_type': 2, 'floor': 1, 'flex_floor': True}
        ]
    })
    assert bad_app.status_code == 400
    assert 'Kapila Bhavanam is reserved exclusively for female M.Tech and PhD scholars' in bad_app.get_json()['error']

    # 2. CB.SC.P2CSE25001 (Female M.Tech Scholar) gets eligible hostels
    l3 = client.post('/api/auth/login', json={'roll_number': 'CB.SC.P2CSE25001', 'password': 'student123'})
    t3 = l3.get_json()['access_token']
    h_res3 = client.get('/api/student/hostels', headers={'Authorization': f'Bearer {t3}'})
    h_data3 = h_res3.get_json()['hostels']
    assert 'Kapila Bhavanam' in [h['name'] for h in h_data3]

    # Submit application for Kapila as M.Tech scholar -> MUST SUCCEED
    good_app = client.post('/api/student/application', headers={'Authorization': f'Bearer {t3}'}, json={
        'roommate_mode': 'none',
        'preferences': [
            {'hostel_id': kapila.id, 'sharing_type': 1, 'floor': 1, 'flex_floor': True},
            {'hostel_id': myt.id, 'sharing_type': 2, 'floor': 1, 'flex_floor': True}
        ]
    })
    assert good_app.status_code == 201
    assert 'registration_number' in good_app.get_json()

def test_idempotent_seeding():
    """
    Rule 7: Rerunning seed_database must not duplicate hostels, floors, or rooms.
    """
    initial_hostel_count = Hostel.query.count()
    initial_room_count = Room.query.count()

    assert initial_hostel_count == 13
    assert initial_room_count == 5200

    # Rerun seed twice
    seed_database()
    seed_database()

    assert Hostel.query.count() == 13
    assert Room.query.count() == 5200
