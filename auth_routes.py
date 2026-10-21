from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from sqlalchemy import func
from models import db, User, Program, Section, SequenceAllocation
from roll_number_service import (
    generate_roll_number_atomic,
    RollNumberValidationError,
    SectionCapacityExceededError
)

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/academic-options', methods=['GET'])
# Time complexity - O(P * S) where P is the count of programs and S is sections per program
# Justification - Queries all active programs and their configured sections with student seat capacity.
def get_academic_options():
    """
    Returns active programs and their configured sections with seat statistics
    for student registration and roll number allocation.
    """
    programs = Program.query.filter_by(active_status=True).order_by(Program.department_code.asc()).all()
    res_programs = []
    
    for p in programs:
        p_dict = p.to_dict()
        sections = Section.query.filter_by(program_id=p.id, active_status=True).order_by(
            Section.admission_batch_year.desc(),
            Section.section_letter.asc()
        ).all()
        p_dict['sections'] = [s.to_dict() for s in sections]
        res_programs.append(p_dict)

    return jsonify({
        'programs': res_programs,
        'default_campus_code': 'CB',
        'default_school_code': 'SC',
        'batches': [2025, 2024, 2023, 2022]
    }), 200

@auth_bp.route('/register', methods=['POST'])
# Time complexity - O(1)
# Justification - Generates an atomic sequence roll number and inserts the new student record in constant time.
def register():
    """
    Student registration: validates academic choice, atomically generates a StayWise roll number,
    and creates the student user record transactionally.
    """
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    gender = (data.get('gender') or '').strip().lower()
    program_id = data.get('program_id')
    admission_batch_year = data.get('admission_batch_year', 2025)
    section_id = data.get('section_id')
    academic_year = data.get('academic_year', 1)

    if not name or not password or not gender or not program_id:
        return jsonify({'error': 'Name, password, gender, and academic program are required.'}), 400

    if gender not in ['male', 'female']:
        return jsonify({'error': 'Gender must be either male or female.'}), 400

    if email and User.query.filter(func.lower(User.email) == email).first():
        return jsonify({'error': f'An account with email {email} already exists.'}), 400

    program = Program.query.filter_by(id=program_id, active_status=True).first()
    if not program:
        return jsonify({'error': 'Selected program is invalid or inactive.'}), 400

    # If section_id was not explicitly passed, find the first available section with remaining capacity
    section = None
    if section_id:
        section = Section.query.filter_by(id=section_id, program_id=program.id, active_status=True).first()
    else:
        # Auto-pick section for batch year with remaining capacity
        sections = Section.query.filter_by(program_id=program.id, admission_batch_year=admission_batch_year, active_status=True).order_by(Section.section_letter.asc()).all()
        for s in sections:
            enrolled = User.query.filter_by(section_id=s.id).count()
            if enrolled < s.capacity:
                section = s
                break
        if not section and sections:
            section = sections[0]

    if not section:
        return jsonify({'error': f'No active section available for program {program.program_name} (Batch {admission_batch_year}).'}), 400

    try:
        # Atomic roll number generation
        roll_num, seq = generate_roll_number_atomic(program.id, admission_batch_year, section.id, db.session)
        
        degree = 'B.Tech'
        if program.program_level == 'P':
            degree = 'M.Tech' if program.program_duration_years == 2 else ('PhD' if program.program_duration_years == 3 else 'Master')

        new_user = User(
            roll_number=roll_num,
            name=name,
            email=email or None,
            password_hash=generate_password_hash(password),
            role='student',
            gender=gender,
            academic_year=int(academic_year),
            degree_level=degree,
            program_id=program.id,
            section_id=section.id,
            campus_code=program.campus_code,
            school_code=program.school_code,
            program_level=program.program_level,
            program_duration_years=program.program_duration_years,
            department_code=program.department_code,
            admission_batch_year=admission_batch_year,
            section_letter=section.section_letter,
            section_digit=section.section_digit,
            section_sequence=seq,
            program_level_category='postgraduate' if program.program_level == 'P' else 'undergraduate',
            synthetic_demo_record=False,
            is_active=True
        )

        db.session.add(new_user)
        db.session.commit()

        return jsonify({
            'message': 'Registration successful. Roll number generated.',
            'roll_number': roll_num,
            'student': new_user.to_dict()
        }), 201

    except (RollNumberValidationError, SectionCapacityExceededError) as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Registration failed: {str(e)}'}), 500

@auth_bp.route('/login', methods=['POST'])
# Time complexity - O(1)
# Justification - Performs indexed roll number lookup, PBKDF2 hash verification, and JWT creation in constant time.
def login():
    data = request.get_json() or {}
    roll_number = data.get('roll_number', '').strip().upper()
    password = data.get('password', '').strip()

    if not roll_number or not password:
        return jsonify({'error': 'Roll number (or Admin ID) and password are required.'}), 400

    # Dual lookup: support both new generated roll number and legacy demo roll number (e.g. STU1001)
    user = User.query.filter(
        (func.upper(User.roll_number) == roll_number) |
        (func.upper(User.legacy_roll_number) == roll_number)
    ).first()

    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid credentials. Please verify your roll number and password.'}), 401

    if not user.is_active:
        return jsonify({'error': 'This account has been disabled by an administrator.'}), 403

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={
            'role': user.role,
            'roll_number': user.roll_number,
            'legacy_roll_number': user.legacy_roll_number,
            'name': user.name,
            'gender': user.gender
        }
    )

    return jsonify({
        'message': 'Login successful',
        'access_token': access_token,
        'user': user.to_dict()
    }), 200

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
# Time complexity - O(1)
# Justification - Primary key lookup on User table by JWT identity executes in constant time.
def me():
    current_user_id = get_jwt_identity()
    user = User.query.get(int(current_user_id))
    if not user or not user.is_active:
        return jsonify({'error': 'User not found or account disabled.'}), 404
    return jsonify({'user': user.to_dict()}), 200

@auth_bp.route('/student-lookup/<roll_number>', methods=['GET'])
@jwt_required()
# Time complexity - O(1)
# Justification - Performs indexed dual lookup on uppercase roll number and gender validation in constant time.
def student_lookup(roll_number):
    current_user_id = get_jwt_identity()
    target_roll = roll_number.strip().upper()

    current_user = User.query.get(int(current_user_id))
    if current_user and (current_user.roll_number.upper() == target_roll or (current_user.legacy_roll_number and current_user.legacy_roll_number.upper() == target_roll)):
        return jsonify({'error': 'You cannot invite yourself as a roommate.'}), 400

    # Dual lookup: search by generated roll_number or legacy_roll_number
    target_user = User.query.filter(
        (func.upper(User.roll_number) == target_roll) |
        (func.upper(User.legacy_roll_number) == target_roll)
    ).filter_by(role='student').first()

    if not target_user:
        return jsonify({'error': f'Student with roll number {target_roll} was not found.'}), 404

    if not target_user.is_active:
        return jsonify({'error': f'Student account {target_roll} is currently inactive.'}), 400

    if current_user and current_user.gender != target_user.gender:
        return jsonify({'error': f'Roommates must be of the same gender category ({current_user.gender}).'}), 400

    return jsonify({
        'student': {
            'id': target_user.id,
            'roll_number': target_user.roll_number,
            'legacy_roll_number': target_user.legacy_roll_number,
            'name': target_user.name,
            'academic_year': target_user.academic_year,
            'gender': target_user.gender,
            'program_name': target_user.program.program_name if target_user.program else None,
            'department_code': target_user.department_code,
            'synthetic_demo_record': target_user.synthetic_demo_record
        }
    }), 200
