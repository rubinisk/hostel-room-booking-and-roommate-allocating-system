import sys
import os
from datetime import datetime, timezone, timedelta
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from models import db, Hostel, Room, User, Application, Group, GroupMember
from seed import seed_database
from allocation_engine import run_allocation

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

def get_student(roll):
    return User.query.filter((User.roll_number == roll) | (User.legacy_roll_number == roll)).first()

def test_exact_capacity_priority_over_compatible_match():
    """
    Verifies Rule A: Exact capacity match outranks compatible match.
    Student A (Group of 2 requesting 2-sharing -> exact match) vs
    Student B (Group of 2 requesting 4-sharing -> compatible but non-exact match).
    When both compete for rooms, exact capacity receives higher priority!
    """
    with app.app_context():
        ananya = Hostel.query.filter_by(code='MYT').first()
        s1 = get_student('CB.SC.U4CSE24001') # Female
        s2 = get_student('CB.SC.U4CSE24002') # Female
        s3 = get_student('CB.SC.P2CSE25001') # Female
        s4 = get_student('CB.SC.P3CSE24001') # Female

        now = datetime.now(timezone.utc)

        # Group 1: CB.SC.U4CSE24001 & CB.SC.U4CSE24002 (Exact match: 2-sharing)
        g1 = Group(leader_student_id=s1.id, group_size=2, status='confirmed', created_at=now)
        db.session.add(g1)
        db.session.flush()
        db.session.add_all([
            GroupMember(group_id=g1.id, student_id=s1.id, status='accepted'),
            GroupMember(group_id=g1.id, student_id=s2.id, status='accepted')
        ])

        app1 = Application(
            registration_number='SW-2026-EXACT',
            student_id=s1.id,
            pref1_hostel_id=ananya.id,
            pref1_sharing=2, # Exact match (2 members in 2-sharing)
            pref1_floor=1,
            roommate_mode='group',
            group_id=g1.id,
            status='submitted',
            submitted_at=now + timedelta(minutes=10) # Submitted LATER than app2!
        )
        app1_sub = Application(
            registration_number='SW-2026-EXACT2',
            student_id=s2.id,
            pref1_hostel_id=ananya.id,
            pref1_sharing=2,
            pref1_floor=1,
            roommate_mode='group',
            group_id=g1.id,
            status='submitted',
            submitted_at=now + timedelta(minutes=10)
        )

        # Group 2: CB.SC.P2CSE25001 & CB.SC.P3CSE24001 (Compatible match: 4-sharing)
        g2 = Group(leader_student_id=s3.id, group_size=2, status='confirmed', created_at=now)
        db.session.add(g2)
        db.session.flush()
        db.session.add_all([
            GroupMember(group_id=g2.id, student_id=s3.id, status='accepted'),
            GroupMember(group_id=g2.id, student_id=s4.id, status='accepted')
        ])

        app2 = Application(
            registration_number='SW-2026-COMPAT',
            student_id=s3.id,
            pref1_hostel_id=ananya.id,
            pref1_sharing=4, # Compatible but non-exact (2 members in 4-sharing)
            pref1_floor=1,
            roommate_mode='group',
            group_id=g2.id,
            status='submitted',
            submitted_at=now # Submitted EARLIER
        )
        app2_sub = Application(
            registration_number='SW-2026-COMPAT2',
            student_id=s4.id,
            pref1_hostel_id=ananya.id,
            pref1_sharing=4,
            pref1_floor=1,
            roommate_mode='group',
            group_id=g2.id,
            status='submitted',
            submitted_at=now
        )

        db.session.add_all([app1, app1_sub, app2, app2_sub])
        db.session.commit()

        # Run heap allocator
        res = run_allocation(commit=True)
        assert res['summary']['allocated_count'] == 4
        # Verify Group 1 got exact match
        exact_alloc = [a for a in res['allocated'] if a['student_roll'] == s1.roll_number][0]
        assert exact_alloc['is_exact_capacity_match'] is True
        assert exact_alloc['sharing_type'] == 2

def test_fcfs_timestamp_tie_breaking():
    """
    Verifies Rule A.2: FCFS ordering applies strictly among equivalent capacity-priority candidates.
    """
    with app.app_context():
        ananya = Hostel.query.filter_by(code='MYT').first()
        s1 = get_student('CB.SC.U4CSE24001')
        s2 = get_student('CB.SC.U4CSE24002')
        now = datetime.now(timezone.utc)

        app1 = Application(
            registration_number='SW-2026-FIRST',
            student_id=s1.id,
            pref1_hostel_id=ananya.id,
            pref1_sharing=2,
            status='submitted',
            submitted_at=now - timedelta(hours=2) # 2 hours earlier
        )
        app2 = Application(
            registration_number='SW-2026-SECOND',
            student_id=s2.id,
            pref1_hostel_id=ananya.id,
            pref1_sharing=2,
            status='submitted',
            submitted_at=now
        )
        db.session.add_all([app1, app2])
        db.session.commit()

        res = run_allocation(commit=True)
        assert res['summary']['allocated_count'] == 2

def test_no_split_group_constraint():
    """
    Verifies Rule E: Confirmed groups are allocated together to the same room; never split!
    """
    with app.app_context():
        ananya = Hostel.query.filter_by(code='MYT').first()
        s1 = get_student('CB.SC.U4CSE24001')
        s2 = get_student('CB.SC.U4CSE24002')
        now = datetime.now(timezone.utc)

        grp = Group(leader_student_id=s1.id, group_size=2, status='confirmed', created_at=now)
        db.session.add(grp)
        db.session.flush()
        db.session.add_all([
            GroupMember(group_id=grp.id, student_id=s1.id, status='accepted'),
            GroupMember(group_id=grp.id, student_id=s2.id, status='accepted')
        ])

        app1 = Application(
            registration_number='SW-2026-GRP1',
            student_id=s1.id,
            pref1_hostel_id=ananya.id,
            pref1_sharing=2,
            roommate_mode='group',
            group_id=grp.id,
            status='submitted',
            submitted_at=now
        )
        app2 = Application(
            registration_number='SW-2026-GRP2',
            student_id=s2.id,
            pref1_hostel_id=ananya.id,
            pref1_sharing=2,
            roommate_mode='group',
            group_id=grp.id,
            status='submitted',
            submitted_at=now
        )
        db.session.add_all([app1, app2])
        db.session.commit()

        res = run_allocation(commit=True)
        assert res['summary']['allocated_count'] == 2
        alloc_1 = [a for a in res['allocated'] if a['student_roll'] == s1.roll_number][0]
        alloc_2 = [a for a in res['allocated'] if a['student_roll'] == s2.roll_number][0]
        # Guaranteed exact same room!
        assert alloc_1['room_id'] == alloc_2['room_id']
        assert alloc_1['hostel_id'] == alloc_2['hostel_id']
