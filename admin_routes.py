import csv
import io
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, Response
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from models import db, User, Hostel, HostelSharingConfig, Room, Application, Group, Allocation, AllocationRun, WaitlistEntry, Payment, AuditLog, ApplicationSettings, Program, Section, SequenceAllocation
from allocation_engine import run_allocation
from scheduler import get_or_create_settings, trigger_deadline_allocation
from roll_number_service import (
    validate_department_code,
    validate_roll_number_format,
    generate_roll_number_atomic,
    SECTION_LETTER_TO_DIGIT,
    SECTION_DIGIT_TO_LETTER,
    DEFAULT_CAMPUS_CODE,
    DEFAULT_SCHOOL_CODE,
    DEFAULT_SECTION_CAPACITY,
    MIN_SECTION_CAPACITY,
    MAX_SECTION_CAPACITY,
    RollNumberValidationError,
    SectionCapacityExceededError
)

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

def admin_required():
    claims = get_jwt()
    if claims.get('role') != 'admin':
        return jsonify({'error': 'Admin privileges required.'}), 403
    return None

@admin_bp.route('/overview', methods=['GET'])
@jwt_required()
def get_overview_metrics():
    auth_err = admin_required()
    if auth_err: return auth_err

    total_students = User.query.filter_by(role='student').count()
    total_apps = Application.query.count()
    pending_apps = Application.query.filter_by(status='submitted').count()
    confirmed_groups = Group.query.filter_by(status='confirmed').count()
    
    total_rooms = Room.query.filter_by(is_active=True).count()
    all_rooms = Room.query.filter_by(is_active=True).all()
    total_capacity = sum(r.sharing_capacity for r in all_rooms)
    total_occupied = sum(r.occupied_beds for r in all_rooms)
    available_beds = total_capacity - total_occupied

    completed_allocations = Allocation.query.count()
    waitlisted_count = WaitlistEntry.query.count()
    pending_payments = Payment.query.filter_by(payment_status='pending').count()

    settings = get_or_create_settings()

    return jsonify({
        'total_students': total_students,
        'total_applications': total_apps,
        'pending_applications': pending_apps,
        'confirmed_groups': confirmed_groups,
        'total_rooms': total_rooms,
        'total_capacity': total_capacity,
        'occupied_beds': total_occupied,
        'available_beds': available_beds,
        'completed_allocations': completed_allocations,
        'waitlisted_count': waitlisted_count,
        'pending_payments': pending_payments,
        'settings': settings.to_dict()
    }), 200

@admin_bp.route('/settings', methods=['POST'])
@jwt_required()
def update_settings():
    auth_err = admin_required()
    if auth_err: return auth_err

    data = request.get_json() or {}
    settings = get_or_create_settings()

    if 'is_open' in data:
        settings.is_open = bool(data['is_open'])
    if 'closing_time' in data and data['closing_time']:
        settings.closing_time = datetime.fromisoformat(data['closing_time'].replace('Z', '+00:00'))

    settings.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({'message': 'Application window settings updated.', 'settings': settings.to_dict()}), 200

@admin_bp.route('/students', methods=['GET'])
@jwt_required()
def get_students():
    auth_err = admin_required()
    if auth_err: return auth_err

    students = User.query.filter_by(role='student').order_by(User.roll_number.asc()).all()
    return jsonify({'students': [s.to_dict() for s in students]}), 200

@admin_bp.route('/students/<int:student_id>/toggle-status', methods=['POST'])
@jwt_required()
def toggle_student_status(student_id):
    auth_err = admin_required()
    if auth_err: return auth_err

    student = User.query.get(student_id)
    if not student or student.role != 'student':
        return jsonify({'error': 'Student record not found.'}), 404

    student.is_active = not student.is_active
    admin_id = int(get_jwt_identity())
    db.session.add(AuditLog(
        admin_id=admin_id,
        action='TOGGLE_STUDENT_STATUS',
        target_type='user',
        target_id=student.id,
        details=f"Set active status of {student.roll_number} to {student.is_active}."
    ))
    db.session.commit()

    return jsonify({'message': f"Student {student.roll_number} active status set to {student.is_active}.", 'student': student.to_dict()}), 200

@admin_bp.route('/hostels', methods=['GET'])
@jwt_required()
def get_all_hostels():
    auth_err = admin_required()
    if auth_err: return auth_err

    hostels = Hostel.query.order_by(Hostel.id.asc()).all()
    return jsonify({'hostels': [h.to_dict() for h in hostels]}), 200

@admin_bp.route('/rooms', methods=['GET'])
@jwt_required()
def get_all_rooms():
    auth_err = admin_required()
    if auth_err: return auth_err

    hostel_id = request.args.get('hostel_id', type=int)
    floor = request.args.get('floor', type=int)
    sharing_type = request.args.get('sharing_type', type=int)

    query = Room.query
    if hostel_id:
        query = query.filter_by(hostel_id=hostel_id)
    if floor:
        query = query.filter_by(floor=floor)
    if sharing_type:
        query = query.filter_by(sharing_capacity=sharing_type)

    rooms = query.order_by(Room.hostel_id.asc(), Room.floor.asc(), Room.room_number.asc()).all()
    return jsonify({'rooms': [r.to_dict() for r in rooms]}), 200

@admin_bp.route('/applications', methods=['GET'])
@jwt_required()
def get_applications():
    auth_err = admin_required()
    if auth_err: return auth_err

    search_roll = request.args.get('roll_number', '').strip().upper()
    status_filter = request.args.get('status', '').strip()

    query = Application.query
    if search_roll:
        user = User.query.filter_by(roll_number=search_roll).first()
        if user:
            query = query.filter_by(student_id=user.id)
        else:
            return jsonify({'applications': []}), 200

    if status_filter:
        query = query.filter_by(status=status_filter)

    apps = query.order_by(Application.submitted_at.desc()).all()
    return jsonify({'applications': [a.to_dict() for a in apps]}), 200

@admin_bp.route('/allocation/preview', methods=['POST'])
@jwt_required()
def preview_allocation():
    auth_err = admin_required()
    if auth_err: return auth_err

    preview_result = run_allocation(commit=False)
    return jsonify({'preview': preview_result}), 200

@admin_bp.route('/allocation/confirm', methods=['POST'])
@jwt_required()
def confirm_allocation():
    auth_err = admin_required()
    if auth_err: return auth_err

    admin_id = int(get_jwt_identity())
    res = trigger_deadline_allocation(admin_id=admin_id, force=True)
    return jsonify(res), 200

@admin_bp.route('/waitlist', methods=['GET'])
@jwt_required()
def get_waitlist():
    auth_err = admin_required()
    if auth_err: return auth_err

    entries = WaitlistEntry.query.order_by(WaitlistEntry.created_at.desc()).all()
    return jsonify({'waitlist': [e.to_dict() for e in entries]}), 200

@admin_bp.route('/audit-logs', methods=['GET'])
@jwt_required()
def get_audit_logs():
    auth_err = admin_required()
    if auth_err: return auth_err

    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).all()
    return jsonify({'audit_logs': [l.to_dict() for l in logs]}), 200

# =========================================================================
# STAYWISE ACADEMIC PROGRAM & ROLL NUMBER MANAGEMENT ENDPOINTS
# =========================================================================

@admin_bp.route('/programs', methods=['GET'])
@jwt_required()
def get_programs():
    auth_err = admin_required()
    if auth_err: return auth_err

    active_only = request.args.get('active_only', 'false').lower() == 'true'
    query = Program.query
    if active_only:
        query = query.filter_by(active_status=True)

    programs = query.order_by(Program.department_code.asc(), Program.program_name.asc()).all()
    res = []
    for p in programs:
        p_dict = p.to_dict()
        p_dict['sections'] = [s.to_dict() for s in p.sections]
        p_dict['total_enrolled_students'] = User.query.filter_by(program_id=p.id).count()
        res.append(p_dict)

    return jsonify({'programs': res}), 200

@admin_bp.route('/programs', methods=['POST'])
@jwt_required()
def create_program():
    auth_err = admin_required()
    if auth_err: return auth_err

    admin_id = int(get_jwt_identity())
    data = request.get_json() or {}
    
    name = (data.get('program_name') or '').strip()
    dept_code = (data.get('department_code') or '').strip().upper()
    ref_code = (data.get('original_reference_code') or dept_code).strip().upper()
    campus_code = (data.get('campus_code') or DEFAULT_CAMPUS_CODE).strip().upper()
    school_code = (data.get('school_code') or DEFAULT_SCHOOL_CODE).strip().upper()
    prog_level = (data.get('program_level') or 'U').strip().upper()
    duration = int(data.get('program_duration_years') or 4)
    init_sections = int(data.get('sections_count') or 1)
    batch_year = int(data.get('batch_year') or 2025)

    if not name:
        return jsonify({'error': 'Program name is required.'}), 400

    try:
        dept_code = validate_department_code(dept_code)
    except RollNumberValidationError as e:
        return jsonify({'error': str(e)}), 400

    if prog_level not in ['U', 'P']:
        return jsonify({'error': "Program level must be 'U' (Undergraduate) or 'P' (Postgraduate)."}), 400

    if duration < 1 or duration > 6:
        return jsonify({'error': 'Program duration must be between 1 and 6 years.'}), 400

    # Check duplicate
    existing = Program.query.filter_by(
        campus_code=campus_code,
        department_code=dept_code,
        program_level=prog_level,
        program_duration_years=duration
    ).first()
    if existing:
        return jsonify({'error': f"Program with department code '{dept_code}' ({prog_level}{duration}) already exists for campus {campus_code}."}), 400

    program = Program(
        campus_code=campus_code,
        school_code=school_code,
        program_name=name,
        original_reference_code=ref_code,
        department_code=dept_code,
        program_level=prog_level,
        program_duration_years=duration,
        active_status=True,
        configuration_version=1
    )
    db.session.add(program)
    db.session.flush()

    # Automatically create initial section(s)
    sections_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
    num_to_create = min(len(sections_letters), max(1, init_sections))
    for i in range(num_to_create):
        let = sections_letters[i]
        digit = SECTION_LETTER_TO_DIGIT[let]
        sec = Section(
            program_id=program.id,
            admission_batch_year=batch_year,
            section_letter=let,
            section_digit=digit,
            capacity=DEFAULT_SECTION_CAPACITY,
            active_status=True
        )
        db.session.add(sec)
        db.session.flush()

        # Initialize sequence allocation
        seq_alloc = SequenceAllocation(
            program_id=program.id,
            admission_batch_year=batch_year,
            section_id=sec.id,
            next_sequence=1,
            last_issued_sequence=0
        )
        db.session.add(seq_alloc)

    db.session.add(AuditLog(
        admin_id=admin_id,
        action='CREATE_PROGRAM',
        target_type='program',
        target_id=program.id,
        details=f"Created program {program.program_name} ({program.department_code}) with {num_to_create} sections for batch {batch_year}."
    ))
    db.session.commit()

    return jsonify({'message': 'Program created successfully.', 'program': program.to_dict()}), 201

@admin_bp.route('/programs/<int:program_id>', methods=['PUT'])
@jwt_required()
def update_program(program_id):
    auth_err = admin_required()
    if auth_err: return auth_err

    admin_id = int(get_jwt_identity())
    program = Program.query.get(program_id)
    if not program:
        return jsonify({'error': 'Program not found.'}), 404

    data = request.get_json() or {}
    if 'program_name' in data and data['program_name'].strip():
        program.program_name = data['program_name'].strip()
    if 'original_reference_code' in data:
        program.original_reference_code = data['original_reference_code'].strip().upper()
    if 'campus_code' in data and data['campus_code'].strip():
        program.campus_code = data['campus_code'].strip().upper()
    if 'school_code' in data and data['school_code'].strip():
        program.school_code = data['school_code'].strip().upper()
    if 'active_status' in data:
        program.active_status = bool(data['active_status'])

    program.configuration_version += 1
    program.updated_at = datetime.now(timezone.utc)

    db.session.add(AuditLog(
        admin_id=admin_id,
        action='UPDATE_PROGRAM',
        target_type='program',
        target_id=program.id,
        details=f"Updated program {program.program_name} (v{program.configuration_version}). Existing student roll numbers are preserved."
    ))
    db.session.commit()

    return jsonify({'message': 'Program updated successfully.', 'program': program.to_dict()}), 200

@admin_bp.route('/programs/<int:program_id>/toggle-status', methods=['POST'])
@jwt_required()
def toggle_program_status(program_id):
    auth_err = admin_required()
    if auth_err: return auth_err

    admin_id = int(get_jwt_identity())
    program = Program.query.get(program_id)
    if not program:
        return jsonify({'error': 'Program not found.'}), 404

    program.active_status = not program.active_status
    program.updated_at = datetime.now(timezone.utc)

    db.session.add(AuditLog(
        admin_id=admin_id,
        action='TOGGLE_PROGRAM_STATUS',
        target_type='program',
        target_id=program.id,
        details=f"Set active status of program {program.program_name} to {program.active_status}."
    ))
    db.session.commit()

    return jsonify({'message': f"Program active status set to {program.active_status}.", 'program': program.to_dict()}), 200

@admin_bp.route('/sections', methods=['GET'])
@jwt_required()
def get_sections():
    auth_err = admin_required()
    if auth_err: return auth_err

    program_id = request.args.get('program_id', type=int)
    batch_year = request.args.get('batch_year', type=int)

    query = Section.query
    if program_id:
        query = query.filter_by(program_id=program_id)
    if batch_year:
        query = query.filter_by(admission_batch_year=batch_year)

    sections = query.order_by(Section.admission_batch_year.desc(), Section.section_letter.asc()).all()
    return jsonify({'sections': [s.to_dict() for s in sections]}), 200

@admin_bp.route('/sections', methods=['POST'])
@jwt_required()
def create_section():
    auth_err = admin_required()
    if auth_err: return auth_err

    admin_id = int(get_jwt_identity())
    data = request.get_json() or {}

    program_id = data.get('program_id')
    batch_year = data.get('admission_batch_year', 2025)
    section_letter = (data.get('section_letter') or '').strip().upper()
    capacity = int(data.get('capacity') or DEFAULT_SECTION_CAPACITY)

    if not program_id or not section_letter:
        return jsonify({'error': 'Program ID and section letter are required.'}), 400

    if section_letter not in SECTION_LETTER_TO_DIGIT:
        return jsonify({'error': f"Section letter '{section_letter}' is invalid. Only sections A through H (digits 0 to 7) are supported."}), 400

    if capacity < MIN_SECTION_CAPACITY or capacity > MAX_SECTION_CAPACITY:
        return jsonify({'error': f'Section capacity must be configured between {MIN_SECTION_CAPACITY} and {MAX_SECTION_CAPACITY} students (default 65).'}), 400

    program = Program.query.get(program_id)
    if not program:
        return jsonify({'error': 'Program not found.'}), 404

    existing = Section.query.filter_by(
        program_id=program_id,
        admission_batch_year=batch_year,
        section_letter=section_letter
    ).first()
    if existing:
        return jsonify({'error': f"Section {section_letter} already exists for {program.department_code} (Batch {batch_year})."}), 400

    section_digit = SECTION_LETTER_TO_DIGIT[section_letter]
    sec = Section(
        program_id=program_id,
        admission_batch_year=batch_year,
        section_letter=section_letter,
        section_digit=section_digit,
        capacity=capacity,
        active_status=True
    )
    db.session.add(sec)
    db.session.flush()

    seq_alloc = SequenceAllocation(
        program_id=program.id,
        admission_batch_year=batch_year,
        section_id=sec.id,
        next_sequence=1,
        last_issued_sequence=0
    )
    db.session.add(seq_alloc)

    db.session.add(AuditLog(
        admin_id=admin_id,
        action='CREATE_SECTION',
        target_type='section',
        target_id=sec.id,
        details=f"Created section {section_letter} (Digit {section_digit}, Capacity {capacity}) for {program.department_code} (Batch {batch_year})."
    ))
    db.session.commit()

    return jsonify({'message': 'Section created successfully.', 'section': sec.to_dict()}), 201

@admin_bp.route('/sections/<int:section_id>', methods=['PUT'])
@jwt_required()
def update_section(section_id):
    auth_err = admin_required()
    if auth_err: return auth_err

    sec = Section.query.get(section_id)
    if not sec:
        return jsonify({'error': 'Section not found.'}), 404

    data = request.get_json() or {}
    if 'capacity' in data:
        cap = int(data['capacity'])
        if cap < MIN_SECTION_CAPACITY or cap > MAX_SECTION_CAPACITY:
            return jsonify({'error': f'Capacity must be between {MIN_SECTION_CAPACITY} and {MAX_SECTION_CAPACITY}.'}), 400
        sec.capacity = cap

    if 'active_status' in data:
        sec.active_status = bool(data['active_status'])

    db.session.commit()
    return jsonify({'message': 'Section updated successfully.', 'section': sec.to_dict()}), 200

@admin_bp.route('/roll-numbers/search', methods=['GET'])
@jwt_required()
def search_roll_numbers():
    auth_err = admin_required()
    if auth_err: return auth_err

    term = (request.args.get('query') or '').strip().upper()
    if not term:
        return jsonify({'students': []}), 200

    students = User.query.filter(
        (User.role == 'student') & (
            User.roll_number.like(f"%{term}%") |
            (User.legacy_roll_number.isnot(None) & User.legacy_roll_number.like(f"%{term}%")) |
            User.name.like(f"%{term}%")
        )
    ).limit(50).all()

    return jsonify({'students': [s.to_dict() for s in students]}), 200

@admin_bp.route('/students/import-csv', methods=['POST'])
@jwt_required()
def import_students_csv():
    """
    Imports authorized student rosters from CSV.
    Validates provided roll numbers or automatically generates atomic roll numbers if missing.
    Returns counts of successful imports, duplicates, and invalid entries.
    """
    auth_err = admin_required()
    if auth_err: return auth_err

    admin_id = int(get_jwt_identity())
    csv_text = ''
    
    if 'file' in request.files:
        uploaded_file = request.files['file']
        csv_text = uploaded_file.read().decode('utf-8', errors='ignore')
    else:
        data = request.get_json() or {}
        csv_text = data.get('csv_content', '')

    if not csv_text.strip():
        return jsonify({'error': 'No CSV content provided.'}), 400

    reader = csv.DictReader(io.StringIO(csv_text))
    created = []
    errors = []
    skipped_duplicates = []

    for row_idx, row in enumerate(reader, start=2): # start at 2 considering header
        clean_row = {k.strip().lower(): (v or '').strip() for k, v in row.items() if k}
        name = clean_row.get('name')
        email = clean_row.get('email')
        gender = clean_row.get('gender', 'male').lower()
        dept_code = clean_row.get('department_code') or clean_row.get('department') or clean_row.get('program') or 'CSE'
        dept_code = dept_code.upper()
        batch_year = int(clean_row.get('batch_year') or clean_row.get('admission_batch_year') or 2025)
        sec_letter = (clean_row.get('section_letter') or clean_row.get('section') or 'A').upper()
        supplied_roll = clean_row.get('roll_number') or clean_row.get('roll_no')

        if not name:
            errors.append({'row': row_idx, 'error': 'Missing student name.'})
            continue

        if gender not in ['male', 'female']:
            gender = 'male'

        # Check existing email
        if email and User.query.filter(func.lower(User.email) == email.lower()).first():
            skipped_duplicates.append({'row': row_idx, 'name': name, 'reason': f'Email {email} already exists.'})
            continue

        # If roll number supplied, validate format and uniqueness
        if supplied_roll:
            clean_roll = supplied_roll.strip().upper()
            if not validate_roll_number_format(clean_roll):
                errors.append({'row': row_idx, 'roll_number': clean_roll, 'error': 'Supplied roll number does not match StayWise format.'})
                continue
            if User.query.filter_by(roll_number=clean_roll).first():
                skipped_duplicates.append({'row': row_idx, 'roll_number': clean_roll, 'reason': 'Roll number already exists.'})
                continue
            roll_to_use = clean_roll
            seq_to_use = int(clean_roll[-2:])
            program = Program.query.filter_by(department_code=dept_code, active_status=True).first()
            section = Section.query.filter_by(program_id=program.id if program else 1, admission_batch_year=batch_year, section_letter=sec_letter).first()
        else:
            # Generate roll number
            program = Program.query.filter_by(department_code=dept_code, active_status=True).first()
            if not program:
                errors.append({'row': row_idx, 'error': f"Program with department code '{dept_code}' not found."})
                continue

            section = Section.query.filter_by(program_id=program.id, admission_batch_year=batch_year, section_letter=sec_letter).first()
            if not section:
                errors.append({'row': row_idx, 'error': f"Section {sec_letter} not configured for {dept_code} (Batch {batch_year})."})
                continue

            try:
                roll_to_use, seq_to_use = generate_roll_number_atomic(program.id, batch_year, section.id, db.session)
            except Exception as e:
                errors.append({'row': row_idx, 'error': str(e)})
                continue

        user = User(
            roll_number=roll_to_use,
            name=name,
            email=email or None,
            password_hash=generate_password_hash('student123'),
            role='student',
            gender=gender,
            academic_year=1,
            degree_level='B.Tech',
            program_id=program.id if program else None,
            section_id=section.id if section else None,
            campus_code=program.campus_code if program else 'CB',
            school_code=program.school_code if program else 'SC',
            program_level=program.program_level if program else 'U',
            program_duration_years=program.program_duration_years if program else 4,
            department_code=program.department_code if program else dept_code,
            admission_batch_year=batch_year,
            section_letter=sec_letter,
            section_digit=SECTION_LETTER_TO_DIGIT.get(sec_letter, 0),
            section_sequence=seq_to_use,
            synthetic_demo_record=True,
            is_active=True
        )
        db.session.add(user)
        created.append(roll_to_use)

    db.session.commit()

    db.session.add(AuditLog(
        admin_id=admin_id,
        action='IMPORT_STUDENTS_CSV',
        target_type='users',
        target_id=None,
        details=f"Imported {len(created)} students from CSV. {len(skipped_duplicates)} duplicates skipped, {len(errors)} errors."
    ))
    db.session.commit()

    return jsonify({
        'message': f"Import complete: {len(created)} students added.",
        'imported_count': len(created),
        'created_roll_numbers': created[:20],
        'skipped_duplicates': skipped_duplicates,
        'errors': errors
    }), 200

@admin_bp.route('/students/export-csv', methods=['GET'])
@jwt_required()
def export_students_csv():
    auth_err = admin_required()
    if auth_err: return auth_err

    students = User.query.filter_by(role='student').order_by(User.roll_number.asc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'roll_number', 'legacy_roll_number', 'name', 'email', 'gender',
        'academic_year', 'degree_level', 'department_code', 'batch_year',
        'section_letter', 'section_sequence', 'synthetic_demo_record', 'active_status'
    ])

    for s in students:
        writer.writerow([
            s.roll_number,
            s.legacy_roll_number or '',
            s.name,
            s.email or '',
            s.gender,
            s.academic_year,
            s.degree_level,
            s.department_code or '',
            s.admission_batch_year or '',
            s.section_letter or '',
            s.section_sequence or '',
            s.synthetic_demo_record,
            s.is_active
        ])

    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=staywise_students_roster.csv'}
    )

