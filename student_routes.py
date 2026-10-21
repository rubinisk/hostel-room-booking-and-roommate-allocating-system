import random
import string
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, Hostel, HostelSharingConfig, Room, Application, ApplicationPreferredRoom, Group, GroupMember, Allocation, WaitlistEntry, Notification
from dsu import DisjointSetUnion
from scheduler import is_application_period_open

student_bp = Blueprint('student', __name__, url_prefix='/api/student')

# Time complexity - O(G * K * alpha(M)) where G is active groups and K <= 4 is group size
# Justification - Fetches active confirmed groups from database and calls rebuild_from_db to reconstruct disjoint sets with inverse Ackermann complexity.
def get_active_dsu():
    """Initializes and builds DSU from current active confirmed groups in the database."""
    dsu = DisjointSetUnion()
    confirmed_groups = Group.query.filter_by(status='confirmed').all()
    active_records = []
    for grp in confirmed_groups:
        memberships = GroupMember.query.filter_by(group_id=grp.id, status='accepted').all()
        m_ids = [grp.leader_student_id] + [m.student_id for m in memberships if m.student_id != grp.leader_student_id]
        active_records.append({'member_ids': m_ids})
    dsu.rebuild_from_db(active_records)
    return dsu

# Time complexity - O(1)
# Justification - Generating 5 random digits and formatting a string executes in constant time.
def generate_registration_number(year=2026):
    rand_suffix = ''.join(random.choices(string.digits, k=5))
    return f"SW-{year}-{rand_suffix}"

# Time complexity - O(1)
# Justification - Indexed database query by uppercase roll number or legacy roll number runs in constant time.
def find_student_by_roll(roll_str):
    if not roll_str:
        return None
    clean = roll_str.strip().upper()
    return User.query.filter(
        (db.func.upper(User.roll_number) == clean) |
        (db.func.upper(User.legacy_roll_number) == clean)
    ).first()

@student_bp.route('/hostels', methods=['GET'])
@jwt_required()
# Time complexity - O(H * C) where H is the count of active hostels and C is sharing configs per hostel
# Justification - Iterates through active hostels matching student gender and filters sharing configurations based on academic year and PG status.
def get_eligible_hostels():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found.'}), 404

    # Hostels matching student gender & active status
    hostels = Hostel.query.filter_by(gender=user.gender, is_active=True).all()
    result = []
    for h in hostels:
        # Kapila Bhavanam (KAP) is exclusively for female M.Tech and PhD scholars
        if (h.code == 'KAP' or h.name == 'Kapila Bhavanam') and (user.gender != 'female' or not getattr(user, 'is_pg_scholar', False)):
            continue

        h_dict = h.to_dict()
        h_dict['floors'] = list(range(1, h.total_floors + 1))
        # Keep only available sharing configs
        h_dict['sharing_configs'] = [c for c in h_dict['sharing_configs'] if c.get('is_available', True)]

        # Filter out 1-sharing if student academic_year < 3 AND not a PG scholar
        if user.academic_year < 3 and not getattr(user, 'is_pg_scholar', False):
            h_dict['sharing_configs'] = [c for c in h_dict['sharing_configs'] if c['sharing_type'] > 1]

        if not h_dict['sharing_configs']:
            continue

        result.append(h_dict)

    return jsonify({'hostels': result}), 200

@student_bp.route('/rooms/<int:hostel_id>', methods=['GET'])
@jwt_required()
# Time complexity - O(R) where R is the number of rooms in the requested hostel
# Justification - Queries and sorts filtered rooms by floor and room number in linear time relative to room count.
def get_hostel_rooms(hostel_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found.'}), 404

    hostel = Hostel.query.get(hostel_id)
    if not hostel or hostel.gender != user.gender:
        return jsonify({'error': 'Hostel not found or gender mismatched.'}), 404

    # Enforce postgraduate eligibility for Kapila Bhavanam
    if (hostel.code == 'KAP' or hostel.name == 'Kapila Bhavanam') and not getattr(user, 'is_pg_scholar', False):
        return jsonify({'error': 'Kapila Bhavanam is reserved exclusively for female M.Tech and PhD scholars.'}), 403

    sharing_type = request.args.get('sharing_type', type=int)
    floor = request.args.get('floor', type=int)

    query = Room.query.filter_by(hostel_id=hostel_id, is_active=True)
    if sharing_type:
        query = query.filter_by(sharing_capacity=sharing_type)
    if floor:
        query = query.filter_by(floor=floor)

    rooms = query.order_by(Room.floor.asc(), Room.room_number.asc()).all()
    return jsonify({'rooms': [r.to_dict() for r in rooms]}), 200

@student_bp.route('/group/my-group', methods=['GET'])
@jwt_required()
# Time complexity - O(K) where K is the number of members in the student's group (K <= 4)
# Justification - Queries the user's active group and fetches group member user profiles in linear time relative to group size.
def get_my_group():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found.'}), 404

    # 1. Check if user is leader of an active group
    leader_group = Group.query.filter_by(leader_student_id=user_id).filter(Group.status.in_(['pending', 'confirmed'])).first()
    if leader_group:
        memberships = GroupMember.query.filter_by(group_id=leader_group.id).all()
        m_list = []
        for m in memberships:
            u = User.query.get(m.student_id)
            if u:
                m_list.append({
                    'member_id': m.id,
                    'student_id': u.id,
                    'roll_number': u.roll_number,
                    'name': u.name,
                    'gender': u.gender,
                    'status': m.status,
                    'is_leader': (u.id == leader_group.leader_student_id),
                    'responded_at': m.responded_at.isoformat() if m.responded_at else None
                })
        
        all_accepted = (len(m_list) >= 2) and all(m['status'] == 'accepted' for m in m_list)
        has_rejected = any(m['status'] == 'rejected' for m in m_list)
        has_pending = any(m['status'] == 'pending' for m in m_list)

        return jsonify({
            'in_group': True,
            'role': 'leader',
            'group_id': leader_group.id,
            'group_size': leader_group.group_size,
            'status': leader_group.status,
            'all_accepted': all_accepted,
            'has_rejected': has_rejected,
            'has_pending': has_pending,
            'members': m_list
        }), 200

    # 2. Check if user is an accepted or pending member of someone else's group
    member_record = GroupMember.query.filter_by(student_id=user_id).filter(GroupMember.status.in_(['pending', 'accepted'])).first()
    if member_record:
        grp = Group.query.get(member_record.group_id)
        if grp and grp.status in ['pending', 'confirmed']:
            leader = User.query.get(grp.leader_student_id)
            all_mems = GroupMember.query.filter_by(group_id=grp.id).all()
            m_list = []
            for m in all_mems:
                u = User.query.get(m.student_id)
                if u:
                    m_list.append({
                        'member_id': m.id,
                        'student_id': u.id,
                        'roll_number': u.roll_number,
                        'name': u.name,
                        'gender': u.gender,
                        'status': m.status,
                        'is_leader': (u.id == grp.leader_student_id),
                        'responded_at': m.responded_at.isoformat() if m.responded_at else None
                    })
            return jsonify({
                'in_group': True,
                'role': 'member',
                'group_id': grp.id,
                'group_size': grp.group_size,
                'status': grp.status,
                'membership_status': member_record.status,
                'invitation_id': member_record.id,
                'leader_name': leader.name if leader else 'Group Leader',
                'leader_roll': leader.roll_number if leader else '',
                'all_accepted': (len(m_list) >= 2) and all(m['status'] == 'accepted' for m in m_list),
                'members': m_list
            }), 200

    return jsonify({'in_group': False, 'role': 'none', 'group': None}), 200

@student_bp.route('/group/invite', methods=['POST'])
@jwt_required()
# Time complexity - O(K * alpha(N)) where K <= 4 is group size and N is student count
# Justification - Rebuilds active DSU, checks group constraints and acyclicity with can_form_group, and creates pending membership records.
def invite_roommate():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user or user.role != 'student':
        return jsonify({'error': 'Only students can invite roommates.'}), 403

    existing_app = Application.query.filter_by(student_id=user_id).first()
    if existing_app:
        return jsonify({'error': 'You have already submitted an application. New roommate invitations are disabled.'}), 400

    other_mem = GroupMember.query.filter_by(student_id=user_id).filter(GroupMember.status.in_(['pending', 'accepted'])).first()
    if other_mem:
        other_grp = Group.query.get(other_mem.group_id)
        if other_grp and other_grp.leader_student_id != user_id and other_grp.status in ['pending', 'confirmed']:
            return jsonify({'error': 'You are currently part of another roommate group. You cannot initiate invitations.'}), 400

    data = request.get_json() or {}
    roll_number = (data.get('roll_number') or '').strip().upper()
    target_group_size = data.get('target_group_size', 2)

    if not roll_number:
        return jsonify({'error': 'Roll number is required.'}), 400

    if roll_number == user.roll_number.upper() or (user.legacy_roll_number and roll_number == user.legacy_roll_number.upper()):
        return jsonify({'error': 'You cannot invite your own roll number.'}), 400

    target_student = find_student_by_roll(roll_number)
    if not target_student:
        return jsonify({'error': f"Student roll number '{roll_number}' was not found in the student database. Please check the roll number."}), 404

    if not target_student.is_active:
        return jsonify({'error': f"Student account for '{roll_number}' is inactive. Please contact administration."}), 400

    if target_student.role != 'student':
        return jsonify({'error': f"Account '{roll_number}' is not a student account."}), 400

    if target_student.gender.lower() != user.gender.lower():
        gender_hostel = "Girls' Hostels" if user.gender.lower() == 'female' else "Boys' Hostels"
        allowed_gender = "Female" if user.gender.lower() == 'female' else "Male"
        opposite_gender = "Male" if user.gender.lower() == 'female' else "Female"
        return jsonify({
            'error': f"Cross-gender roommate pairing is not permitted. {target_student.name} ({roll_number}) is a {opposite_gender} student, while your booking is for {gender_hostel}. Only {allowed_gender} roommates can be added."
        }), 400

    if Application.query.filter_by(student_id=target_student.id).first():
        return jsonify({'error': f'Student {roll_number} has already submitted an individual application.'}), 400

    target_mem = GroupMember.query.filter_by(student_id=target_student.id).filter(GroupMember.status.in_(['pending', 'accepted'])).first()
    if target_mem:
        t_grp = Group.query.get(target_mem.group_id)
        if t_grp and t_grp.status in ['pending', 'confirmed']:
            if t_grp.leader_student_id == user_id:
                return jsonify({'error': f'Student {roll_number} is already in your group.'}), 400
            return jsonify({'error': f'Student {roll_number} is already part of another roommate group or has a pending invitation.'}), 400

    # Find or create group for leader
    group = Group.query.filter_by(leader_student_id=user_id).filter(Group.status.in_(['pending', 'confirmed'])).first()
    if not group:
        group = Group(
            leader_student_id=user_id,
            group_size=target_group_size,
            status='pending',
            created_at=datetime.now(timezone.utc)
        )
        db.session.add(group)
        db.session.flush()

        db.session.add(GroupMember(
            group_id=group.id,
            student_id=user_id,
            status='accepted',
            responded_at=datetime.now(timezone.utc)
        ))
    else:
        active_count = GroupMember.query.filter_by(group_id=group.id).filter(GroupMember.status.in_(['pending', 'accepted'])).count()
        if active_count >= 4:
            return jsonify({'error': 'Maximum group size is 4 members.'}), 400
        group.group_size = max(group.group_size, target_group_size)

    dsu = get_active_dsu()
    valid, msg = dsu.can_form_group([user_id, target_student.id], max_group_size=4)
    if not valid:
        return jsonify({'error': f'DSU Group Conflict: {msg}'}), 400

    existing_in_group = GroupMember.query.filter_by(group_id=group.id, student_id=target_student.id).first()
    if existing_in_group:
        existing_in_group.status = 'pending'
        existing_in_group.responded_at = None
    else:
        db.session.add(GroupMember(
            group_id=group.id,
            student_id=target_student.id,
            status='pending'
        ))

    group.status = 'pending'

    db.session.add(Notification(
        user_id=target_student.id,
        title='Hostel Roommate Group Invitation',
        message=f"{user.name} ({user.roll_number}) invited you to join their {group.group_size}-person room registration. Please accept or decline.",
        type='invitation',
        is_read=False,
        created_at=datetime.now(timezone.utc)
    ))

    db.session.commit()

    return jsonify({
        'message': f'Invitation sent to {target_student.name} ({roll_number}).',
        'student': {
            'id': target_student.id,
            'name': target_student.name,
            'roll_number': target_student.roll_number,
            'gender': target_student.gender,
            'status': 'pending'
        }
    }), 200

@student_bp.route('/group/remove-member', methods=['POST'])
@jwt_required()
# Time complexity - O(K) where K <= 4 is the number of remaining group members
# Justification - Deletes member record, updates group status and size, and commits to database in bounded constant time.
def remove_group_member():
    user_id = int(get_jwt_identity())
    group = Group.query.filter_by(leader_student_id=user_id).filter(Group.status.in_(['pending', 'confirmed'])).first()
    if not group:
        return jsonify({'error': 'You do not have an active group.'}), 404

    data = request.get_json() or {}
    student_id = data.get('student_id')
    roll_number = (data.get('roll_number') or '').strip().upper()

    target_user = None
    if student_id:
        target_user = User.query.get(student_id)
    elif roll_number:
        target_user = find_student_by_roll(roll_number)

    if not target_user:
        return jsonify({'error': 'Student not found.'}), 404

    if target_user.id == user_id:
        return jsonify({'error': 'Group leader cannot be removed. Use group reset to disband.'}), 400

    mem = GroupMember.query.filter_by(group_id=group.id, student_id=target_user.id).first()
    if mem:
        db.session.delete(mem)

    new_size = data.get('new_group_size')
    remaining = GroupMember.query.filter_by(group_id=group.id).filter(GroupMember.status.in_(['accepted', 'pending'])).all()
    if new_size and new_size in [2, 3, 4]:
        group.group_size = new_size
    else:
        group.group_size = max(2, len(remaining))

    if len(remaining) >= 2 and all(m.status == 'accepted' for m in remaining):
        group.status = 'confirmed'
    else:
        group.status = 'pending'

    db.session.commit()
    return jsonify({'message': f'Removed {target_user.name} from group.', 'group_size': group.group_size}), 200

@student_bp.route('/group/reset', methods=['POST'])
@jwt_required()
# Time complexity - O(K) where K <= 4 is the number of group members
# Justification - Deletes all associated group member records and the parent group in bounded constant time.
def reset_group():
    user_id = int(get_jwt_identity())
    group = Group.query.filter_by(leader_student_id=user_id).filter(Group.status.in_(['pending', 'confirmed'])).first()
    if group:
        GroupMember.query.filter_by(group_id=group.id).delete()
        db.session.delete(group)
        db.session.commit()
    return jsonify({'message': 'Group disbanded successfully. You can book individually or start a new group.'}), 200

@student_bp.route('/application', methods=['GET'])
@jwt_required()
# Time complexity - O(1)
# Justification - Single indexed database query for student application and related group status in constant time.
def get_my_application():
    user_id = int(get_jwt_identity())
    app_rec = Application.query.filter_by(student_id=user_id).first()
    if app_rec:
        return jsonify({
            'has_application': True,
            'can_modify': is_application_period_open() and (app_rec.status == 'submitted'),
            'application': app_rec.to_dict()
        }), 200

    # Check if student is an accepted or pending member of an active group led by someone else
    membership = GroupMember.query.filter_by(student_id=user_id).filter(GroupMember.status.in_(['pending', 'accepted'])).first()
    if membership:
        grp = Group.query.get(membership.group_id)
        if grp and grp.leader_student_id != user_id and grp.status in ['pending', 'confirmed']:
            leader = User.query.get(grp.leader_student_id)
            return jsonify({
                'has_application': False,
                'application': None,
                'in_group_invitation': True,
                'group_role': 'member',
                'membership_status': membership.status,
                'invitation_id': membership.id,
                'leader_name': leader.name if leader else 'Unknown',
                'leader_roll': leader.roll_number if leader else '',
                'group_size': grp.group_size
            }), 200

    return jsonify({'has_application': False, 'application': None}), 200

@student_bp.route('/application', methods=['POST'])
@jwt_required()
# Time complexity - O(K * alpha(N) + P) where K <= 4 is group size and P is the number of preferred rooms
# Justification - Validates deadline, verifies group membership via DSU, saves 3 ranked preferences, and links preferred rooms.
def submit_application():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user or user.role != 'student':
        return jsonify({'error': 'Only active students can submit hostel applications.'}), 403

    # Deadline validation
    if not is_application_period_open():
        return jsonify({'error': 'The application window is currently closed. Submissions are not accepted.'}), 400

    # Prevent duplicate active application
    existing_app = Application.query.filter_by(student_id=user_id).first()
    if existing_app:
        if existing_app.status == 'cancelled':
            ApplicationPreferredRoom.query.filter_by(application_id=existing_app.id).delete()
            db.session.delete(existing_app)
            db.session.flush()
        else:
            return jsonify({'error': f'You have already submitted application {existing_app.registration_number}. You can review, modify, or cancel it before the deadline.'}), 400

    # Prevent non-leader group member from submitting separate application
    other_mem = GroupMember.query.filter_by(student_id=user_id).filter(GroupMember.status.in_(['pending', 'accepted'])).first()
    if other_mem:
        other_grp = Group.query.get(other_mem.group_id)
        if other_grp and other_grp.leader_student_id != user_id and other_grp.status in ['pending', 'confirmed']:
            leader_u = User.query.get(other_grp.leader_student_id)
            leader_name = leader_u.name if leader_u else 'Group Leader'
            leader_roll = leader_u.roll_number if leader_u else ''
            return jsonify({'error': f'You are a member of a roommate group initiated by {leader_name} ({leader_roll}). You cannot initiate a separate registration.'}), 400

    data = request.get_json() or {}
    preferences = data.get('preferences', [])
    if len(preferences) < 2 or len(preferences) > 3:
        return jsonify({'error': 'The first two hostel preferences are mandatory. The third preference is optional.'}), 400

    # Roommate mode & Group validation
    roommate_mode = data.get('roommate_mode', 'none')
    group_id = None
    group_size = 1

    if roommate_mode == 'group':
        # Check if leader already has an active group formed in Step 1
        existing_leader_group = Group.query.filter_by(leader_student_id=user.id).filter(Group.status.in_(['pending', 'confirmed'])).first()
        if existing_leader_group:
            mems = GroupMember.query.filter_by(group_id=existing_leader_group.id).all()
            if not all(m.status == 'accepted' for m in mems):
                return jsonify({'error': 'All invited friends must accept (give Yes) before submitting the application.'}), 400
            
            group_id = existing_leader_group.id
            group_size = existing_leader_group.group_size
            existing_leader_group.status = 'confirmed'

            # DSU Union for accepted group members
            dsu = get_active_dsu()
            for m in mems:
                if m.student_id != user.id:
                    dsu.union(user.id, m.student_id)
        else:
            friend_rolls = data.get('friend_rolls', [])
            group_size = len(friend_rolls) + 1
            if group_size not in [2, 3, 4]:
                return jsonify({'error': 'Group booking size must be 2, 3, or 4 members including applicant.'}), 400

            # Validate friend users
            friend_users = []
            for f_roll in friend_rolls:
                clean_roll = f_roll.strip().upper()
                if clean_roll == user.roll_number.upper() or (user.legacy_roll_number and clean_roll == user.legacy_roll_number.upper()):
                    return jsonify({'error': 'You cannot include your own roll number in the friend list.'}), 400

                f_u = find_student_by_roll(clean_roll)
                if not f_u:
                    return jsonify({'error': f"Student roll number '{clean_roll}' was not found in the student database. Please check the roll number."}), 400

                if not f_u.is_active:
                    return jsonify({'error': f"Student account for '{clean_roll}' is inactive. Please contact administration."}), 400

                if f_u.role != 'student':
                    return jsonify({'error': f"Account '{clean_roll}' is not a student account."}), 400

                # Strict gender validation
                if f_u.gender.lower() != user.gender.lower():
                    gender_hostel = "Girls' Hostels" if user.gender.lower() == 'female' else "Boys' Hostels"
                    allowed_gender = "Female" if user.gender.lower() == 'female' else "Male"
                    opposite_gender = "Male" if user.gender.lower() == 'female' else "Female"
                    return jsonify({
                        'error': f"Cross-gender roommate pairing is not permitted. {f_u.name} ({clean_roll}) is a {opposite_gender} student, while your booking is for {gender_hostel}. Only {allowed_gender} roommates can be added."
                    }), 400

                # Check if friend already in an active group or submitted app
                existing_grp_mem = GroupMember.query.filter_by(student_id=f_u.id, status='accepted').first()
                if existing_grp_mem:
                    return jsonify({'error': f'Student {clean_roll} already belongs to an active confirmed group.'}), 400

                existing_f_app = Application.query.filter_by(student_id=f_u.id).first()
                if existing_f_app:
                    return jsonify({'error': f'Student {clean_roll} already submitted an individual application.'}), 400

                friend_users.append(f_u)

            # DSU Validation: Check for group disjointness and overlaps
            dsu = get_active_dsu()
            candidate_ids = [user.id] + [fu.id for fu in friend_users]
            valid, msg = dsu.can_form_group(candidate_ids, max_group_size=4)
            if not valid:
                return jsonify({'error': f"DSU Group Conflict: {msg}"}), 400

            # Create Group
            new_group = Group(
                leader_student_id=user.id,
                group_size=group_size,
                status='pending',
                created_at=datetime.now(timezone.utc)
            )
            db.session.add(new_group)
            db.session.flush()
            group_id = new_group.id

            # Add Leader
            db.session.add(GroupMember(
                group_id=new_group.id,
                student_id=user.id,
                status='accepted',
                responded_at=datetime.now(timezone.utc)
            ))

            # Send invitations to friends
            for f_u in friend_users:
                db.session.add(GroupMember(
                    group_id=new_group.id,
                    student_id=f_u.id,
                    status='pending'
                ))
                db.session.add(Notification(
                    user_id=f_u.id,
                    title='Roommate Group Invitation',
                    message=f"{user.name} ({user.roll_number}) invited you to join a {group_size}-person hostel booking group.",
                    type='invitation',
                    is_read=False,
                    created_at=datetime.now(timezone.utc)
                ))

    # Validate 3 Preferences (each with hostel, sharing, floor, flex_floor)
    pref_fields = {}
    chosen_combos = []

    for idx, pref in enumerate(preferences[:3], start=1):
        h_id = pref.get('hostel_id')
        s_type = pref.get('sharing_type')
        fl = pref.get('floor', 1)
        fl_flex = pref.get('flex_floor', True)

        if idx <= 2 and (not h_id or not s_type):
            return jsonify({'error': f'Preference #{idx} is mandatory. Please specify both hostel and sharing capacity.'}), 400

        if idx == 3 and (not h_id or not s_type):
            continue

        hostel = Hostel.query.get(h_id)
        if not hostel or hostel.gender != user.gender or not hostel.is_active:
            return jsonify({'error': f'Preference #{idx}: Hostel is invalid or incompatible with your gender.'}), 400

        # Kapila Bhavanam (KAP) is exclusively for female M.Tech and PhD scholars
        if (hostel.code == 'KAP' or hostel.name == 'Kapila Bhavanam'):
            if user.gender != 'female' or not getattr(user, 'is_pg_scholar', False):
                return jsonify({'error': f'Preference #{idx}: Kapila Bhavanam is reserved exclusively for female M.Tech and PhD scholars.'}), 400
            if group_size > 1:
                return jsonify({'error': f'Preference #{idx}: Kapila Bhavanam offers only single-sharing rooms for individual postgraduate scholars.'}), 400

        # Dynamic sharing validation: sharing_type must be >= group_size
        if s_type < group_size:
            return jsonify({'error': f'Preference #{idx}: {s_type}-sharing cannot fit your group of {group_size} members.'}), 400

        # Single-sharing restriction: allowed if academic_year >= 3 OR user is a PG scholar
        if s_type == 1 and user.academic_year < 3 and not getattr(user, 'is_pg_scholar', False):
            return jsonify({'error': f'Preference #{idx}: Single-sharing is reserved only for Year 3+ students and postgraduate scholars.'}), 400

        sharing_cfg = HostelSharingConfig.query.filter_by(hostel_id=h_id, sharing_type=s_type, is_available=True).first()
        if not sharing_cfg:
            return jsonify({'error': f'Preference #{idx}: {s_type}-sharing is not available in {hostel.name}.'}), 400

        chosen_combos.append((h_id, s_type))
        pref_fields[f'pref{idx}_hostel_id'] = h_id
        pref_fields[f'pref{idx}_sharing'] = s_type
        pref_fields[f'pref{idx}_floor'] = fl
        pref_fields[f'pref{idx}_flex_floor'] = fl_flex

    # Validate distinct preferences: same hostel with different sharing capacity is allowed!
    if len(chosen_combos) != len(set(chosen_combos)):
        return jsonify({'error': 'Each preference must be unique. You can select the same hostel with different sharing capacities.'}), 400

    # Create Application
    reg_num = generate_registration_number(year=2026)
    app_rec = Application(
        registration_number=reg_num,
        student_id=user.id,
        cycle_year=2026,
        pref1_hostel_id=pref_fields.get('pref1_hostel_id'),
        pref1_sharing=pref_fields.get('pref1_sharing'),
        pref1_floor=pref_fields.get('pref1_floor', 1),
        pref1_flex_floor=pref_fields.get('pref1_flex_floor', True),
        pref2_hostel_id=pref_fields.get('pref2_hostel_id'),
        pref2_sharing=pref_fields.get('pref2_sharing'),
        pref2_floor=pref_fields.get('pref2_floor', 1),
        pref2_flex_floor=pref_fields.get('pref2_flex_floor', True),
        pref3_hostel_id=pref_fields.get('pref3_hostel_id'),
        pref3_sharing=pref_fields.get('pref3_sharing'),
        pref3_floor=pref_fields.get('pref3_floor', 1),
        pref3_flex_floor=pref_fields.get('pref3_flex_floor', True),
        roommate_mode=roommate_mode,
        group_id=group_id,
        status='submitted',
        submitted_at=datetime.now(timezone.utc)
    )
    db.session.add(app_rec)
    db.session.flush()

    # Preferred Rooms (for Preference 1 alone, up to 5)
    preferred_room_ids = data.get('preferred_room_ids', [])
    for p_idx, r_id in enumerate(preferred_room_ids[:5], start=1):
        r_obj = Room.query.get(r_id)
        if r_obj and r_obj.hostel_id == pref_fields['pref1_hostel_id']:
            db.session.add(ApplicationPreferredRoom(
                application_id=app_rec.id,
                room_id=r_id,
                priority=p_idx
            ))

    db.session.add(Notification(
        user_id=user.id,
        title='Application Submitted Successfully',
        message=f"Your StayWise application Reg #{reg_num} has been recorded.",
        type='system',
        is_read=False,
        created_at=datetime.now(timezone.utc)
    ))

    # For confirmed groups: create mirror Application records for all accepted members
    if roommate_mode == 'group' and group_id:
        accepted_mems = GroupMember.query.filter_by(group_id=group_id, status='accepted').all()
        for mem in accepted_mems:
            if mem.student_id != user.id:
                mem_app = Application.query.filter_by(student_id=mem.student_id).first()
                if not mem_app:
                    m_reg = generate_registration_number(year=2026)
                    m_app = Application(
                        registration_number=m_reg,
                        student_id=mem.student_id,
                        cycle_year=2026,
                        pref1_hostel_id=pref_fields.get('pref1_hostel_id'),
                        pref1_sharing=pref_fields.get('pref1_sharing'),
                        pref1_floor=pref_fields.get('pref1_floor', 1),
                        pref1_flex_floor=pref_fields.get('pref1_flex_floor', True),
                        pref2_hostel_id=pref_fields.get('pref2_hostel_id'),
                        pref2_sharing=pref_fields.get('pref2_sharing'),
                        pref2_floor=pref_fields.get('pref2_floor', 1),
                        pref2_flex_floor=pref_fields.get('pref2_flex_floor', True),
                        pref3_hostel_id=pref_fields.get('pref3_hostel_id'),
                        pref3_sharing=pref_fields.get('pref3_sharing'),
                        pref3_floor=pref_fields.get('pref3_floor', 1),
                        pref3_flex_floor=pref_fields.get('pref3_flex_floor', True),
                        roommate_mode='group',
                        group_id=group_id,
                        status='submitted',
                        submitted_at=datetime.now(timezone.utc)
                    )
                    db.session.add(m_app)
                    db.session.flush()
                    for p_idx, r_id in enumerate(preferred_room_ids[:5], start=1):
                        r_obj = Room.query.get(r_id)
                        if r_obj and r_obj.hostel_id == pref_fields['pref1_hostel_id']:
                            db.session.add(ApplicationPreferredRoom(
                                application_id=m_app.id,
                                room_id=r_id,
                                priority=p_idx
                            ))
                    db.session.add(Notification(
                        user_id=mem.student_id,
                        title='Application Submitted by Group Leader',
                        message=f"Group leader {user.name} ({user.roll_number}) submitted the hostel application (Reg #{m_reg}) for your group.",
                        type='system',
                        is_read=False,
                        created_at=datetime.now(timezone.utc)
                    ))

    db.session.commit()

    return jsonify({
        'message': 'Hostel application submitted successfully.',
        'registration_number': reg_num,
        'application': app_rec.to_dict()
    }), 201

@student_bp.route('/application', methods=['PUT'])
@jwt_required()
# Time complexity - O(P) where P is the number of preferred rooms
# Justification - Verifies submission status and deadline, replaces preferred room selections, and updates preference columns.
def modify_application():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user or user.role != 'student':
        return jsonify({'error': 'Only active students can modify hostel applications.'}), 403

    if not is_application_period_open():
        return jsonify({'error': 'The application window is currently closed. Modifications are disabled.'}), 400

    app_rec = Application.query.filter_by(student_id=user_id).first()
    if not app_rec:
        return jsonify({'error': 'No active application found to modify.'}), 404

    existing_alloc = Allocation.query.filter_by(student_id=user_id, status='allotted').first()
    if existing_alloc or app_rec.status == 'allocated':
        return jsonify({'error': 'Your room has already been allotted by the administrator. Applications cannot be modified after room allocation.'}), 400

    if app_rec.status != 'submitted':
        return jsonify({'error': f'Application has status "{app_rec.status}" and can no longer be edited.'}), 400

    # Non-leader group members cannot modify directly; leader modifies on behalf of group
    if app_rec.group_id:
        grp = Group.query.get(app_rec.group_id)
        if grp and grp.leader_student_id != user_id:
            leader_u = User.query.get(grp.leader_student_id)
            leader_name = leader_u.name if leader_u else 'Group Leader'
            return jsonify({'error': f'Only group leader {leader_name} can modify joint application preferences.'}), 403

    data = request.get_json() or {}
    preferences = data.get('preferences', [])
    if len(preferences) < 2 or len(preferences) > 3:
        return jsonify({'error': 'The first two hostel preferences are mandatory. The third preference is optional.'}), 400

    group_size = 1
    if app_rec.group_id:
        grp = Group.query.get(app_rec.group_id)
        if grp:
            group_size = grp.group_size

    pref_fields = {}
    chosen_combos = []

    for idx, pref in enumerate(preferences[:3], start=1):
        h_id = pref.get('hostel_id')
        s_type = pref.get('sharing_type')
        fl = pref.get('floor', 1)
        fl_flex = pref.get('flex_floor', True)

        if idx <= 2 and (not h_id or not s_type):
            return jsonify({'error': f'Preference #{idx} is mandatory. Please specify both hostel and sharing capacity.'}), 400

        if idx == 3 and (not h_id or not s_type):
            continue

        hostel = Hostel.query.get(h_id)
        if not hostel or hostel.gender != user.gender or not hostel.is_active:
            return jsonify({'error': f'Preference #{idx}: Hostel is invalid or incompatible with your gender.'}), 400

        # Kapila Bhavanam (KAP) is exclusively for female M.Tech and PhD scholars
        if (hostel.code == 'KAP' or hostel.name == 'Kapila Bhavanam'):
            if user.gender != 'female' or not getattr(user, 'is_pg_scholar', False):
                return jsonify({'error': f'Preference #{idx}: Kapila Bhavanam is reserved exclusively for female M.Tech and PhD scholars.'}), 400
            if group_size > 1:
                return jsonify({'error': f'Preference #{idx}: Kapila Bhavanam offers only single-sharing rooms for individual postgraduate scholars.'}), 400

        if s_type < group_size:
            return jsonify({'error': f'Preference #{idx}: {s_type}-sharing cannot fit your group of {group_size} members.'}), 400

        if s_type == 1 and user.academic_year < 3 and not getattr(user, 'is_pg_scholar', False):
            return jsonify({'error': f'Preference #{idx}: Single-sharing is reserved only for Year 3+ students and postgraduate scholars.'}), 400

        sharing_cfg = HostelSharingConfig.query.filter_by(hostel_id=h_id, sharing_type=s_type, is_available=True).first()
        if not sharing_cfg:
            return jsonify({'error': f'Preference #{idx}: {s_type}-sharing is not available in {hostel.name}.'}), 400

        chosen_combos.append((h_id, s_type))
        pref_fields[f'pref{idx}_hostel_id'] = h_id
        pref_fields[f'pref{idx}_sharing'] = s_type
        pref_fields[f'pref{idx}_floor'] = fl
        pref_fields[f'pref{idx}_flex_floor'] = fl_flex

    if len(chosen_combos) != len(set(chosen_combos)):
        return jsonify({'error': 'Each preference must be unique. Choosing the same hostel with different sharing capacity is allowed.'}), 400

    # Update leader application
    app_rec.pref1_hostel_id = pref_fields.get('pref1_hostel_id')
    app_rec.pref1_sharing = pref_fields.get('pref1_sharing')
    app_rec.pref1_floor = pref_fields.get('pref1_floor', 1)
    app_rec.pref1_flex_floor = pref_fields.get('pref1_flex_floor', True)

    app_rec.pref2_hostel_id = pref_fields.get('pref2_hostel_id')
    app_rec.pref2_sharing = pref_fields.get('pref2_sharing')
    app_rec.pref2_floor = pref_fields.get('pref2_floor', 1)
    app_rec.pref2_flex_floor = pref_fields.get('pref2_flex_floor', True)

    app_rec.pref3_hostel_id = pref_fields.get('pref3_hostel_id')
    app_rec.pref3_sharing = pref_fields.get('pref3_sharing')
    app_rec.pref3_floor = pref_fields.get('pref3_floor', 1) if pref_fields.get('pref3_hostel_id') else None
    app_rec.pref3_flex_floor = pref_fields.get('pref3_flex_floor', True) if pref_fields.get('pref3_hostel_id') else None

    # Update preferred rooms for Pref 1
    ApplicationPreferredRoom.query.filter_by(application_id=app_rec.id).delete()
    preferred_room_ids = data.get('preferred_room_ids', [])
    for p_idx, r_id in enumerate(preferred_room_ids[:5], start=1):
        r_obj = Room.query.get(r_id)
        if r_obj and r_obj.hostel_id == pref_fields['pref1_hostel_id']:
            db.session.add(ApplicationPreferredRoom(
                application_id=app_rec.id,
                room_id=r_id,
                priority=p_idx
            ))

    # If group application: also update mirror applications for members
    if app_rec.group_id:
        member_apps = Application.query.filter_by(group_id=app_rec.group_id).filter(Application.student_id != user.id).all()
        for m_app in member_apps:
            m_app.pref1_hostel_id = pref_fields.get('pref1_hostel_id')
            m_app.pref1_sharing = pref_fields.get('pref1_sharing')
            m_app.pref1_floor = pref_fields.get('pref1_floor', 1)
            m_app.pref1_flex_floor = pref_fields.get('pref1_flex_floor', True)

            m_app.pref2_hostel_id = pref_fields.get('pref2_hostel_id')
            m_app.pref2_sharing = pref_fields.get('pref2_sharing')
            m_app.pref2_floor = pref_fields.get('pref2_floor', 1)
            m_app.pref2_flex_floor = pref_fields.get('pref2_flex_floor', True)

            m_app.pref3_hostel_id = pref_fields.get('pref3_hostel_id')
            m_app.pref3_sharing = pref_fields.get('pref3_sharing')
            m_app.pref3_floor = pref_fields.get('pref3_floor', 1)
            m_app.pref3_flex_floor = pref_fields.get('pref3_flex_floor', True)

            ApplicationPreferredRoom.query.filter_by(application_id=m_app.id).delete()
            for p_idx, r_id in enumerate(preferred_room_ids[:5], start=1):
                r_obj = Room.query.get(r_id)
                if r_obj and r_obj.hostel_id == pref_fields['pref1_hostel_id']:
                    db.session.add(ApplicationPreferredRoom(
                        application_id=m_app.id,
                        room_id=r_id,
                        priority=p_idx
                    ))

            db.session.add(Notification(
                user_id=m_app.student_id,
                title='Application Preferences Modified',
                message=f"Group leader {user.name} ({user.roll_number}) updated your hostel application preferences.",
                type='system',
                is_read=False,
                created_at=datetime.now(timezone.utc)
            ))

    db.session.add(Notification(
        user_id=user.id,
        title='Application Modified Successfully',
        message=f"Your StayWise application Reg #{app_rec.registration_number} preferences have been updated.",
        type='system',
        is_read=False,
        created_at=datetime.now(timezone.utc)
    ))

    db.session.commit()
    return jsonify({
        'message': 'Application preferences updated successfully.',
        'registration_number': app_rec.registration_number,
        'application': app_rec.to_dict()
    }), 200

@student_bp.route('/application/cancel', methods=['POST'])
@student_bp.route('/application', methods=['DELETE'])
@jwt_required()
# Time complexity - O(1)
# Justification - Checks deadline, deletes preferred room links, and marks application cancelled in constant time.
def cancel_application():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found.'}), 404

    if not is_application_period_open():
        return jsonify({'error': 'The application window has closed. Applications can no longer be cancelled.'}), 400

    app_rec = Application.query.filter_by(student_id=user_id).first()
    if not app_rec:
        return jsonify({'error': 'No active application found to cancel.'}), 404

    existing_alloc = Allocation.query.filter_by(student_id=user_id, status='allotted').first()
    if existing_alloc or app_rec.status == 'allocated':
        return jsonify({'error': 'Your room has already been allotted by the administrator. Applications cannot be cancelled after room allocation.'}), 400

    if app_rec.status != 'submitted':
        return jsonify({'error': f'Application has status "{app_rec.status}" and cannot be cancelled.'}), 400

    reg_num = app_rec.registration_number

    # If part of a group:
    if app_rec.group_id:
        grp = Group.query.get(app_rec.group_id)
        if grp:
            if grp.leader_student_id == user_id:
                # Leader cancels: also delete mirror applications of all group members
                member_apps = Application.query.filter_by(group_id=grp.id).filter(Application.student_id != user.id).all()
                for m_app in member_apps:
                    ApplicationPreferredRoom.query.filter_by(application_id=m_app.id).delete()
                    db.session.add(Notification(
                        user_id=m_app.student_id,
                        title='Joint Application Cancelled by Leader',
                        message=f"Group leader {user.name} ({user.roll_number}) cancelled your joint room application. You can now apply individually or form another group.",
                        type='system',
                        is_read=False,
                        created_at=datetime.now(timezone.utc)
                    ))
                    db.session.delete(m_app)

                # Disband group so students can group again
                GroupMember.query.filter_by(group_id=grp.id).delete()
                db.session.delete(grp)
            else:
                # Member cancels: remove them from group
                GroupMember.query.filter_by(group_id=grp.id, student_id=user.id).delete()
                remaining = GroupMember.query.filter_by(group_id=grp.id).count()
                grp.group_size = max(1, remaining)

    # Delete application and preferred rooms
    ApplicationPreferredRoom.query.filter_by(application_id=app_rec.id).delete()
    db.session.delete(app_rec)

    db.session.add(Notification(
        user_id=user.id,
        title='Application Cancelled',
        message=f"Your application Reg #{reg_num} has been cancelled. You can book again until the deadline.",
        type='system',
        is_read=False,
        created_at=datetime.now(timezone.utc)
    ))

    db.session.commit()
    return jsonify({
        'message': f'Application {reg_num} has been successfully cancelled. You can now book again.'
    }), 200

@student_bp.route('/invitations', methods=['GET'])
@jwt_required()
# Time complexity - O(I) where I is the number of pending invitations for the student
# Justification - Queries pending group memberships and retrieves leader information for each invitation.
def get_invitations():
    user_id = int(get_jwt_identity())
    pending_m = GroupMember.query.filter_by(student_id=user_id, status='pending').all()
    
    invites = []
    for m in pending_m:
        grp = Group.query.get(m.group_id)
        if grp:
            leader = User.query.get(grp.leader_student_id)
            invites.append({
                'invitation_id': m.id,
                'group_id': grp.id,
                'leader_name': leader.name if leader else 'Unknown',
                'leader_roll': leader.roll_number if leader else '',
                'group_size': grp.group_size,
                'created_at': grp.created_at.isoformat() if grp.created_at else None
            })

    return jsonify({'invitations': invites}), 200

@student_bp.route('/invitations/<int:invitation_id>/respond', methods=['POST'])
@jwt_required()
# Time complexity - O(K * alpha(N)) where K <= 4 is group size
# Justification - Updates invitation status, runs DSU cycle check and capacity validation, and confirms group if all accepted.
def respond_invitation(invitation_id):
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    
    membership = GroupMember.query.filter_by(id=invitation_id, student_id=user_id).first()
    if not membership or membership.status != 'pending':
        return jsonify({'error': 'Pending invitation not found.'}), 404

    data = request.get_json() or {}
    action = data.get('action') # 'accept' or 'reject'
    if action not in ['accept', 'reject']:
        return jsonify({'error': 'Action must be "accept" or "reject".'}), 400

    now = datetime.now(timezone.utc)
    group = Group.query.get(membership.group_id)
    leader = User.query.get(group.leader_student_id)

    if action == 'accept':
        membership.status = 'accepted'
        membership.responded_at = now

        # Check if all members have accepted
        all_members = GroupMember.query.filter_by(group_id=group.id).all()
        if all(m.status == 'accepted' for m in all_members):
            group.status = 'confirmed'
            for m in all_members:
                db.session.add(Notification(
                    user_id=m.student_id,
                    title='Friend Group Confirmed!',
                    message=f"All {group.group_size} members accepted. Your group is confirmed for joint room allocation.",
                    type='invitation',
                    is_read=False,
                    created_at=now
                ))
        else:
            db.session.add(Notification(
                user_id=leader.id,
                title='Roommate Invitation Accepted',
                message=f"{user.name} ({user.roll_number}) accepted your invitation.",
                type='invitation',
                is_read=False,
                created_at=now
            ))
    else:
        membership.status = 'rejected'
        membership.responded_at = now
        # Notify leader of rejection
        db.session.add(Notification(
            user_id=leader.id,
            title='Roommate Invitation Declined',
            message=f"{user.name} ({user.roll_number}) declined the invitation. You can invite a replacement or continue.",
            type='invitation',
            is_read=False,
            created_at=now
        ))

    db.session.commit()
    return jsonify({'message': f'Invitation {action}ed successfully.', 'group_status': group.status}), 200

@student_bp.route('/allocation', methods=['GET'])
@jwt_required()
# Time complexity - O(B) where B is the number of beds in the allocated room (B <= 4)
# Justification - Fetches allocation and waitlist records, and retrieves co-roommates occupying the same room.
def get_my_allocation():
    user_id = int(get_jwt_identity())
    alloc = Allocation.query.filter_by(student_id=user_id).first()
    if not alloc:
        # Check waitlist
        w = WaitlistEntry.query.filter_by(student_id=user_id).first()
        return jsonify({
            'has_allocation': False,
            'is_waitlisted': bool(w),
            'waitlist_reason': w.reason if w else None,
            'allocation': None
        }), 200

    alloc_dict = alloc.to_dict()
    # Fetch co-roommates
    roommates = []
    co_allocs = Allocation.query.filter_by(room_id=alloc.room_id).filter(Allocation.student_id != user_id).all()
    for ca in co_allocs:
        roommates.append({
            'name': ca.student.name if ca.student else 'Unknown',
            'roll_number': ca.student.roll_number if ca.student else ''
        })
    alloc_dict['roommates'] = roommates

    return jsonify({
        'has_allocation': True,
        'is_waitlisted': False,
        'allocation': alloc_dict
    }), 200

@student_bp.route('/notifications', methods=['GET'])
@jwt_required()
# Time complexity - O(N_notif) where N_notif is the number of user notifications
# Justification - Queries and sorts user notifications ordered by creation timestamp in linear time.
def get_notifications():
    user_id = int(get_jwt_identity())
    notifs = Notification.query.filter_by(user_id=user_id).order_by(Notification.created_at.desc()).all()
    return jsonify({'notifications': [n.to_dict() for n in notifs]}), 200

@student_bp.route('/notifications/read', methods=['POST'])
@jwt_required()
# Time complexity - O(N_unread) where N_unread is the number of unread notifications
# Justification - Bulk updates is_read flag for all unread notifications of the logged-in student.
def mark_notifications_read():
    user_id = int(get_jwt_identity())
    Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'message': 'Notifications marked as read.'}), 200
