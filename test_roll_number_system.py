import sys
import os
import pytest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from models import (
    db, User, Program, Section, SequenceAllocation, Application, Hostel, Allocation
)
from seed import seed_database
from roll_number_service import (
    validate_department_code,
    validate_roll_number_format,
    parse_roll_number,
    generate_roll_number_atomic,
    RollNumberValidationError,
    SectionCapacityExceededError,
    SECTION_LETTER_TO_DIGIT,
    SECTION_DIGIT_TO_LETTER
)

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

def test_1_parsing_and_generation_of_spec_example():
    """
    Test 1: Verify correct parsing and structure of the reference example CB.SC.U4CSE25547.
    """
    example = "CB.SC.U4CSE25547"
    assert validate_roll_number_format(example) is True
    parsed = parse_roll_number(example)
    assert parsed['campus_code'] == 'CB'
    assert parsed['school_code'] == 'SC'
    assert parsed['program_level'] == 'U'
    assert parsed['program_duration_years'] == 4
    assert parsed['department_code'] == 'CSE'
    assert parsed['admission_batch_year'] == 2025
    assert parsed['section_digit'] == 5
    assert parsed['section_letter'] == 'F' # 5 = Section F
    assert parsed['section_sequence'] == 47

def test_2_support_for_program_prefixes():
    """
    Test 2: Support for U3, U4, U5, P1, P2, P3 and other configured prefixes.
    """
    valid_samples = [
        ("CB.SC.U4ECE25001", "U", 4, "ECE", 2025, 'A', 1),
        ("CB.SC.U5BAL25001", "U", 5, "BAL", 2025, 'A', 1),
        ("CB.SC.P2MBA25001", "P", 2, "MBA", 2025, 'A', 1),
        ("CB.SC.U3BCA25120", "U", 3, "BCA", 2025, 'B', 20),
        ("CB.SC.P1LLM25015", "P", 1, "LLM", 2025, 'A', 15),
        ("CB.SC.P3CSE25005", "P", 3, "CSE", 2025, 'A', 5),
    ]
    for roll, lvl, dur, dept, batch, sec_let, seq in valid_samples:
        assert validate_roll_number_format(roll) is True
        p = parse_roll_number(roll)
        assert p['program_level'] == lvl
        assert p['program_duration_years'] == dur
        assert p['department_code'] == dept
        assert p['admission_batch_year'] == batch
        assert p['section_letter'] == sec_let
        assert p['section_sequence'] == seq

def test_3_three_letter_department_code_validation():
    """
    Test 3: Exactly three uppercase letters required for department code.
    """
    assert validate_department_code('CSE') == 'CSE'
    assert validate_department_code('aid') == 'AID'
    assert validate_department_code('ECE') == 'ECE'
    
    # Invalid codes
    with pytest.raises(RollNumberValidationError):
        validate_department_code('CS') # only 2 letters
    with pytest.raises(RollNumberValidationError):
        validate_department_code('CSEE') # 4 letters
    with pytest.raises(RollNumberValidationError):
        validate_department_code('CS1') # contains number
    with pytest.raises(RollNumberValidationError):
        validate_department_code('') # empty

def test_4_section_digit_mapping():
    """
    Test 4: Section-digit mapping from 0=A through 7=H.
    """
    expected = {
        'A': 0, 'B': 1, 'C': 2, 'D': 3,
        'E': 4, 'F': 5, 'G': 6, 'H': 7
    }
    for letter, digit in expected.items():
        assert SECTION_LETTER_TO_DIGIT[letter] == digit
        assert SECTION_DIGIT_TO_LETTER[digit] == letter

def test_5_sequence_boundaries_and_rejection_of_00():
    """
    Test 5 & 7: Valid sequence 01 to capacity, rejection of sequence 00.
    """
    # 00 is forbidden
    assert validate_roll_number_format("CB.SC.U4CSE25000") is True # matches regex
    with pytest.raises(RollNumberValidationError):
        parse_roll_number("CB.SC.U4CSE25000") # rejected by parser

    # 01 and 65 are valid
    p01 = parse_roll_number("CB.SC.U4CSE25001")
    assert p01['section_sequence'] == 1

    p65 = parse_roll_number("CB.SC.U4CSE25065")
    assert p65['section_sequence'] == 65

def test_6_eight_section_configuration_for_cse_core():
    """
    Test 6 & 8: CSE Core must support 8 sections: A through H.
    """
    cse = Program.query.filter_by(department_code='CSE', program_level='U', program_duration_years=4).first()
    assert cse is not None
    secs_2025 = Section.query.filter_by(program_id=cse.id, admission_batch_year=2025).order_by(Section.section_digit.asc()).all()
    assert len(secs_2025) == 8
    expected_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
    assert [s.section_letter for s in secs_2025] == expected_letters
    for s in secs_2025:
        assert 60 <= s.capacity <= 65

def test_7_atomic_sequence_generation_and_capacity_enforcement():
    """
    Test 7, 10 & 12: Atomic sequence allocation and capacity limits.
    """
    with app.app_context():
        cse = Program.query.filter_by(department_code='CSE', program_level='U').first()
        sec_h = Section.query.filter_by(program_id=cse.id, admission_batch_year=2025, section_letter='H').first()
        sec_h.capacity = 62 # configure custom capacity within 60-65

        # Allocate 62 students sequentially
        for expected_seq in range(1, 63):
            roll, seq = generate_roll_number_atomic(cse.id, 2025, sec_h.id, db.session)
            assert seq == expected_seq
            expected_roll = f"CB.SC.U4CSE257{expected_seq:02d}" # H = digit 7
            assert roll == expected_roll

        # 63rd student should raise SectionCapacityExceededError
        with pytest.raises(SectionCapacityExceededError):
            generate_roll_number_atomic(cse.id, 2025, sec_h.id, db.session)

def test_8_student_registration_generates_roll_number(client):
    """
    Test 8 & 13: Student registration workflow via /api/auth/register generates StayWise roll number.
    """
    cse = Program.query.filter_by(department_code='CSE', program_level='U').first()
    sec_b = Section.query.filter_by(program_id=cse.id, admission_batch_year=2025, section_letter='B').first()

    reg_res = client.post('/api/auth/register', json={
        'name': 'Deepak Verma',
        'email': 'deepak.verma@staywise.edu',
        'password': 'password123',
        'gender': 'male',
        'program_id': cse.id,
        'admission_batch_year': 2025,
        'section_id': sec_b.id,
        'academic_year': 1
    })
    assert reg_res.status_code == 201
    data = reg_res.get_json()
    assert 'roll_number' in data
    # Section B has digit 1
    assert data['roll_number'].startswith("CB.SC.U4CSE251")
    assert data['student']['department_code'] == 'CSE'
    assert data['student']['section_letter'] == 'B'

    # Now verify the newly registered student can log in using the generated roll number
    login_res = client.post('/api/auth/login', json={
        'roll_number': data['roll_number'],
        'password': 'password123'
    })
    assert login_res.status_code == 200
    assert login_res.get_json()['user']['name'] == 'Deepak Verma'

def test_9_configuration_preserves_previously_issued_roll_numbers(client):
    """
    Test 14: Updating program configuration does not rewrite existing roll numbers.
    """
    stu1 = User.query.filter_by(roll_number='CB.SC.U4CSE24001').first()
    original_roll = stu1.roll_number

    # Admin edits program name and campus code
    admin_login = client.post('/api/auth/login', json={'roll_number': 'ADMIN', 'password': 'admin123'})
    token = admin_login.get_json()['access_token']

    edit_res = client.put(f'/api/admin/programs/{stu1.program_id}', headers={'Authorization': f'Bearer {token}'}, json={
        'program_name': 'Advanced Computer Science Engineering',
        'campus_code': 'CO'
    })
    assert edit_res.status_code == 200

    # Verify student's previously issued roll number did NOT change!
    db.session.refresh(stu1)
    assert stu1.roll_number == original_roll

def test_10_allotted_room_cannot_be_modified_or_cancelled(client):
    """
    Verifies Requirement: Once a room is allotted by administrator,
    students CANNOT modify or cancel their application!
    """
    # 1. Login CB.SC.U4CSE24001 and submit application
    login_res = client.post('/api/auth/login', json={'roll_number': 'CB.SC.U4CSE24001', 'password': 'student123'})
    token = login_res.get_json()['access_token']
    user_id = login_res.get_json()['user']['id']

    myt = Hostel.query.filter_by(code='MYT').first()
    gar = Hostel.query.filter_by(code='GAR').first()
    app_res = client.post('/api/student/application', headers={'Authorization': f'Bearer {token}'}, json={
        'roommate_mode': 'none',
        'preferences': [
            {'hostel_id': myt.id, 'sharing_type': 2, 'floor': 1, 'flex_floor': True},
            {'hostel_id': gar.id, 'sharing_type': 3, 'floor': 1, 'flex_floor': True}
        ]
    })
    assert app_res.status_code == 201

    app_rec = Application.query.filter_by(student_id=user_id).first()
    assert app_rec is not None

    # Student can modify while submitted
    mod_ok = client.put('/api/student/application', headers={'Authorization': f'Bearer {token}'}, json={
        'preferences': [
            {'hostel_id': myt.id, 'sharing_type': 2, 'floor': 2, 'flex_floor': True},
            {'hostel_id': gar.id, 'sharing_type': 3, 'floor': 1, 'flex_floor': True}
        ]
    })
    assert mod_ok.status_code == 200

    # 2. Administrator allots room to this student
    room = myt.rooms[0]
    alloc = Allocation(
        application_id=app_rec.id,
        student_id=user_id,
        hostel_id=myt.id,
        room_id=room.id,
        floor=room.floor,
        sharing_type=room.sharing_capacity,
        preference_rank_satisfied=1,
        fee_amount=65000.0,
        status='allotted'
    )
    app_rec.status = 'allocated'
    db.session.add(alloc)
    db.session.commit()

    # 3. Student tries to modify -> MUST BE REJECTED!
    mod_blocked = client.put('/api/student/application', headers={'Authorization': f'Bearer {token}'}, json={
        'preferences': [
            {'hostel_id': myt.id, 'sharing_type': 2, 'floor': 3, 'flex_floor': True}
        ]
    })
    assert mod_blocked.status_code == 400
    assert 'already been allotted' in mod_blocked.get_json()['error']

    # 4. Student tries to cancel -> MUST BE REJECTED!
    cancel_blocked = client.delete('/api/student/application', headers={'Authorization': f'Bearer {token}'})
    assert cancel_blocked.status_code == 400
    assert 'already been allotted' in cancel_blocked.get_json()['error']
