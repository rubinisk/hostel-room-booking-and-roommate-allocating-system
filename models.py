from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Program(db.Model):
    __tablename__ = 'programs'
    __table_args__ = (
        db.UniqueConstraint('campus_code', 'department_code', 'program_level', 'program_duration_years', name='uix_program_code_level_dur'),
    )

    id = db.Column(db.Integer, primary_key=True)
    campus_code = db.Column(db.String(10), nullable=False, default='CB') # e.g. 'CB'
    school_code = db.Column(db.String(10), nullable=False, default='SC') # e.g. 'SC'
    program_name = db.Column(db.String(150), nullable=False) # e.g. 'Computer Science and Engineering Core'
    original_reference_code = db.Column(db.String(50), nullable=True) # e.g. 'CSE'
    department_code = db.Column(db.String(3), nullable=False) # exactly 3 uppercase letters, e.g. 'CSE'
    program_level = db.Column(db.String(5), nullable=False, default='U') # 'U' (Undergraduate), 'P' (Postgraduate)
    program_duration_years = db.Column(db.Integer, nullable=False, default=4) # 1, 2, 3, 4, 5
    active_status = db.Column(db.Boolean, nullable=False, default=True)
    configuration_version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    sections = db.relationship('Section', backref='program', cascade='all, delete-orphan', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'campus_code': self.campus_code,
            'school_code': self.school_code,
            'program_name': self.program_name,
            'original_reference_code': self.original_reference_code,
            'department_code': self.department_code,
            'program_level': self.program_level,
            'program_duration_years': self.program_duration_years,
            'prefix': f"{self.campus_code}.{self.school_code}.{self.program_level}{self.program_duration_years}{self.department_code}",
            'active_status': self.active_status,
            'configuration_version': self.configuration_version,
            'sections_count': len(self.sections) if self.sections else 0,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class Section(db.Model):
    __tablename__ = 'sections'
    __table_args__ = (
        db.UniqueConstraint('program_id', 'admission_batch_year', 'section_letter', name='uix_program_batch_section_letter'),
        db.UniqueConstraint('program_id', 'admission_batch_year', 'section_digit', name='uix_program_batch_section_digit'),
    )

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False)
    admission_batch_year = db.Column(db.Integer, nullable=False) # e.g. 2025
    section_letter = db.Column(db.String(2), nullable=False) # 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'
    section_digit = db.Column(db.Integer, nullable=False) # 0 to 7
    capacity = db.Column(db.Integer, nullable=False, default=65) # 60 to 65
    active_status = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        enrolled_count = User.query.filter_by(section_id=self.id).count() if hasattr(self, 'id') and self.id else 0
        return {
            'id': self.id,
            'program_id': self.program_id,
            'program_name': self.program.program_name if self.program else None,
            'department_code': self.program.department_code if self.program else None,
            'admission_batch_year': self.admission_batch_year,
            'section_letter': self.section_letter,
            'section_digit': self.section_digit,
            'capacity': self.capacity,
            'enrolled_students': enrolled_count,
            'remaining_seats': max(0, self.capacity - enrolled_count),
            'active_status': self.active_status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class SequenceAllocation(db.Model):
    __tablename__ = 'sequence_allocations'
    __table_args__ = (
        db.UniqueConstraint('program_id', 'admission_batch_year', 'section_id', name='uix_program_batch_section_alloc'),
    )

    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=False)
    admission_batch_year = db.Column(db.Integer, nullable=False)
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=False)
    next_sequence = db.Column(db.Integer, nullable=False, default=1)
    last_issued_sequence = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'program_id': self.program_id,
            'admission_batch_year': self.admission_batch_year,
            'section_id': self.section_id,
            'next_sequence': self.next_sequence,
            'last_issued_sequence': self.last_issued_sequence,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    roll_number = db.Column(db.String(50), unique=True, nullable=False, index=True) # e.g. 'CB.SC.U4CSE25547'
    legacy_roll_number = db.Column(db.String(50), unique=True, nullable=True, index=True) # e.g. 'STU1001'
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student') # 'student', 'admin'
    gender = db.Column(db.String(20), nullable=False) # 'male', 'female'
    academic_year = db.Column(db.Integer, nullable=False, default=1) # 1, 2, 3, 4
    degree_level = db.Column(db.String(50), nullable=False, default='B.Tech') # 'B.Tech', 'M.Tech', 'PhD'
    
    # Roll-number architecture fields
    program_id = db.Column(db.Integer, db.ForeignKey('programs.id'), nullable=True)
    section_id = db.Column(db.Integer, db.ForeignKey('sections.id'), nullable=True)
    campus_code = db.Column(db.String(10), nullable=True, default='CB')
    school_code = db.Column(db.String(10), nullable=True, default='SC')
    program_level = db.Column(db.String(5), nullable=True) # 'U', 'P'
    program_duration_years = db.Column(db.Integer, nullable=True) # 4, 2, etc.
    department_code = db.Column(db.String(3), nullable=True) # 'CSE', etc.
    admission_batch_year = db.Column(db.Integer, nullable=True) # 2024, 2025
    section_letter = db.Column(db.String(2), nullable=True) # 'A'..'H'
    section_digit = db.Column(db.Integer, nullable=True) # 0..7
    section_sequence = db.Column(db.Integer, nullable=True) # 1..65
    program_level_category = db.Column(db.String(30), nullable=True) # 'undergraduate', 'postgraduate'
    synthetic_demo_record = db.Column(db.Boolean, default=True, nullable=False)
    
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    program = db.relationship('Program', foreign_keys=[program_id], lazy=True)
    section = db.relationship('Section', foreign_keys=[section_id], lazy=True)

    @property
    def is_pg_scholar(self):
        degree = (self.degree_level or '').strip().upper()
        return degree in ['M.TECH', 'PHD', 'POSTGRADUATE']

    def to_dict(self):
        return {
            'id': self.id,
            'roll_number': self.roll_number,
            'legacy_roll_number': self.legacy_roll_number,
            'name': self.name,
            'email': self.email,
            'role': self.role,
            'gender': self.gender,
            'academic_year': self.academic_year,
            'degree_level': getattr(self, 'degree_level', 'B.Tech') or 'B.Tech',
            'is_pg_scholar': self.is_pg_scholar,
            'program_id': self.program_id,
            'program_name': self.program.program_name if self.program else None,
            'section_id': self.section_id,
            'campus_code': self.campus_code,
            'school_code': self.school_code,
            'department_code': self.department_code,
            'admission_batch_year': self.admission_batch_year,
            'section_letter': self.section_letter,
            'section_digit': self.section_digit,
            'section_sequence': self.section_sequence,
            'synthetic_demo_record': self.synthetic_demo_record,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Hostel(db.Model):
    __tablename__ = 'hostels'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(10), unique=True, nullable=True) # GAR, MYT, ADI, SAV, KAP, AGA, GAU, VAS, VYA, NAC, YAG, KAS, BRI
    gender = db.Column(db.String(20), nullable=False) # 'male', 'female'
    description = db.Column(db.Text, nullable=True)
    total_floors = db.Column(db.Integer, default=4, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    sharing_configs = db.relationship('HostelSharingConfig', backref='hostel', cascade='all, delete-orphan', lazy=True)
    rooms = db.relationship('Room', backref='hostel', cascade='all, delete-orphan', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'gender': self.gender,
            'description': self.description,
            'total_floors': self.total_floors,
            'is_active': self.is_active,
            'sharing_configs': [c.to_dict() for c in self.sharing_configs]
        }

class HostelSharingConfig(db.Model):
    __tablename__ = 'hostel_sharing_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    hostel_id = db.Column(db.Integer, db.ForeignKey('hostels.id'), nullable=False)
    sharing_type = db.Column(db.Integer, nullable=False) # 1, 2, 3, 4
    fee_amount = db.Column(db.Float, nullable=False, default=50000.0)
    is_available = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'hostel_id': self.hostel_id,
            'sharing_type': self.sharing_type,
            'fee_amount': self.fee_amount,
            'is_available': self.is_available
        }

class Room(db.Model):
    __tablename__ = 'rooms'
    __table_args__ = (
        db.UniqueConstraint('hostel_id', 'room_number', name='uix_hostel_room_number'),
    )
    
    id = db.Column(db.Integer, primary_key=True)
    hostel_id = db.Column(db.Integer, db.ForeignKey('hostels.id'), nullable=False)
    room_number = db.Column(db.String(50), nullable=False, index=True) # e.g. 'G-101', 'F-200', 'S-300', 'T-400'
    room_code = db.Column(db.String(50), nullable=True, unique=True, index=True) # e.g. 'MYT-G-101', 'GAR-F-200'
    floor = db.Column(db.Integer, nullable=False)
    sharing_capacity = db.Column(db.Integer, nullable=False)
    occupied_beds = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def to_dict(self):
        code = self.room_code or (f"{self.hostel.code}-{self.room_number}" if self.hostel and getattr(self.hostel, 'code', None) else self.room_number)
        return {
            'id': self.id,
            'hostel_id': self.hostel_id,
            'room_number': self.room_number,
            'room_code': code,
            'floor': self.floor,
            'sharing_capacity': self.sharing_capacity,
            'occupied_beds': self.occupied_beds,
            'available_beds': self.sharing_capacity - self.occupied_beds,
            'is_active': self.is_active
        }

class Group(db.Model):
    __tablename__ = 'groups'
    
    id = db.Column(db.Integer, primary_key=True)
    leader_student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    group_size = db.Column(db.Integer, nullable=False) # 1, 2, 3, 4
    status = db.Column(db.String(20), nullable=False, default='pending') # 'pending', 'confirmed', 'rejected', 'cancelled'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    members = db.relationship('GroupMember', backref='group', cascade='all, delete-orphan', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'leader_student_id': self.leader_student_id,
            'group_size': self.group_size,
            'status': self.status,
            'members': [m.to_dict() for m in self.members]
        }

class GroupMember(db.Model):
    __tablename__ = 'group_members'
    
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending') # 'pending', 'accepted', 'rejected'
    responded_at = db.Column(db.DateTime, nullable=True)

    student = db.relationship('User', foreign_keys=[student_id])

    def to_dict(self):
        return {
            'id': self.id,
            'group_id': self.group_id,
            'student_id': self.student_id,
            'student_name': self.student.name if self.student else None,
            'student_roll': self.student.roll_number if self.student else None,
            'status': self.status,
            'responded_at': self.responded_at.isoformat() if self.responded_at else None
        }

class Application(db.Model):
    __tablename__ = 'applications'
    
    id = db.Column(db.Integer, primary_key=True)
    registration_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    cycle_year = db.Column(db.Integer, default=2026, nullable=False)
    
    # Preference 1: hostel, sharing, floor, flex_floor
    pref1_hostel_id = db.Column(db.Integer, db.ForeignKey('hostels.id'), nullable=False)
    pref1_sharing = db.Column(db.Integer, nullable=False)
    pref1_floor = db.Column(db.Integer, default=1, nullable=False)
    pref1_flex_floor = db.Column(db.Boolean, default=True, nullable=False)
    
    # Preference 2: hostel, sharing, floor, flex_floor
    pref2_hostel_id = db.Column(db.Integer, db.ForeignKey('hostels.id'), nullable=True)
    pref2_sharing = db.Column(db.Integer, nullable=True)
    pref2_floor = db.Column(db.Integer, default=1, nullable=True)
    pref2_flex_floor = db.Column(db.Boolean, default=True, nullable=True)
    
    # Preference 3: hostel, sharing, floor, flex_floor
    pref3_hostel_id = db.Column(db.Integer, db.ForeignKey('hostels.id'), nullable=True)
    pref3_sharing = db.Column(db.Integer, nullable=True)
    pref3_floor = db.Column(db.Integer, default=1, nullable=True)
    pref3_flex_floor = db.Column(db.Boolean, default=True, nullable=True)

    roommate_mode = db.Column(db.String(20), nullable=False, default='none') # 'none', 'group'
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True)
    
    status = db.Column(db.String(30), nullable=False, default='submitted') # 'submitted', 'allocated', 'waitlisted', 'cancelled'
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    preferred_rooms = db.relationship('ApplicationPreferredRoom', backref='application', cascade='all, delete-orphan', lazy=True)
    student = db.relationship('User', foreign_keys=[student_id])
    group = db.relationship('Group', foreign_keys=[group_id])

    def to_dict(self):
        prefs = [
            {
                'rank': 1,
                'hostel_id': self.pref1_hostel_id,
                'sharing_type': self.pref1_sharing,
                'floor': self.pref1_floor,
                'flex_floor': self.pref1_flex_floor
            },
            {
                'rank': 2,
                'hostel_id': self.pref2_hostel_id,
                'sharing_type': self.pref2_sharing,
                'floor': self.pref2_floor,
                'flex_floor': self.pref2_flex_floor
            } if self.pref2_hostel_id else None,
            {
                'rank': 3,
                'hostel_id': self.pref3_hostel_id,
                'sharing_type': self.pref3_sharing,
                'floor': self.pref3_floor,
                'flex_floor': self.pref3_flex_floor
            } if self.pref3_hostel_id else None,
        ]
        return {
            'id': self.id,
            'registration_number': self.registration_number,
            'student_id': self.student_id,
            'student': self.student.to_dict() if self.student else None,
            'cycle_year': self.cycle_year,
            'preferences': [p for p in prefs if p is not None],
            'roommate_mode': self.roommate_mode,
            'group_id': self.group_id,
            'group': self.group.to_dict() if self.group else None,
            'preferred_rooms': [r.to_dict() for r in self.preferred_rooms],
            'status': self.status,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None
        }

class ApplicationPreferredRoom(db.Model):
    __tablename__ = 'application_preferred_rooms'
    
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    priority = db.Column(db.Integer, nullable=False) # 1..5

    room = db.relationship('Room')

    def to_dict(self):
        return {
            'id': self.id,
            'application_id': self.application_id,
            'room_id': self.room_id,
            'room_number': self.room.room_number if self.room else None,
            'priority': self.priority
        }

class AllocationRun(db.Model):
    __tablename__ = 'allocation_runs'
    
    id = db.Column(db.Integer, primary_key=True)
    run_code = db.Column(db.String(50), unique=True, nullable=False)
    cycle_year = db.Column(db.Integer, default=2026, nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    total_applications = db.Column(db.Integer, default=0, nullable=False)
    allocated_count = db.Column(db.Integer, default=0, nullable=False)
    waitlisted_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(20), default='completed', nullable=False)
    executed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'run_code': self.run_code,
            'cycle_year': self.cycle_year,
            'total_applications': self.total_applications,
            'allocated_count': self.allocated_count,
            'waitlisted_count': self.waitlisted_count,
            'status': self.status,
            'executed_at': self.executed_at.isoformat() if self.executed_at else None
        }

class Allocation(db.Model):
    __tablename__ = 'allocations'
    
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('allocation_runs.id'), nullable=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), unique=True, nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    hostel_id = db.Column(db.Integer, db.ForeignKey('hostels.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    floor = db.Column(db.Integer, nullable=False)
    sharing_type = db.Column(db.Integer, nullable=False)
    preference_rank_satisfied = db.Column(db.Integer, nullable=False) # 1, 2, 3, or 0 (fallback)
    is_fallback = db.Column(db.Boolean, default=False, nullable=False)
    is_exact_capacity_match = db.Column(db.Boolean, default=True, nullable=False)
    fee_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), nullable=False, default='allocated') # 'allocated', 'payment_completed', 'cancelled'
    allocated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    student = db.relationship('User', foreign_keys=[student_id])
    hostel = db.relationship('Hostel', foreign_keys=[hostel_id])
    room = db.relationship('Room', foreign_keys=[room_id])
    application = db.relationship('Application', foreign_keys=[application_id])

    def to_dict(self):
        return {
            'id': self.id,
            'application_id': self.application_id,
            'student_id': self.student_id,
            'student_name': self.student.name if self.student else None,
            'student_roll': self.student.roll_number if self.student else None,
            'hostel_id': self.hostel_id,
            'hostel_name': self.hostel.name if self.hostel else None,
            'room_id': self.room_id,
            'room_number': self.room.room_number if self.room else None,
            'floor': self.floor,
            'sharing_type': self.sharing_type,
            'preference_rank_satisfied': self.preference_rank_satisfied,
            'is_fallback': self.is_fallback,
            'is_exact_capacity_match': self.is_exact_capacity_match,
            'fee_amount': self.fee_amount,
            'status': self.status,
            'allocated_at': self.allocated_at.isoformat() if self.allocated_at else None
        }

class WaitlistEntry(db.Model):
    __tablename__ = 'waitlist_entries'
    
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('allocation_runs.id'), nullable=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    student = db.relationship('User', foreign_keys=[student_id])
    application = db.relationship('Application', foreign_keys=[application_id])

    def to_dict(self):
        return {
            'id': self.id,
            'application_id': self.application_id,
            'student_id': self.student_id,
            'student_name': self.student.name if self.student else None,
            'student_roll': self.student.roll_number if self.student else None,
            'reason': self.reason,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class ApplicationSettings(db.Model):
    __tablename__ = 'application_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    cycle_year = db.Column(db.Integer, default=2026, nullable=False)
    is_open = db.Column(db.Boolean, default=True, nullable=False)
    opening_time = db.Column(db.DateTime, nullable=True)
    closing_time = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'cycle_year': self.cycle_year,
            'is_open': self.is_open,
            'opening_time': self.opening_time.isoformat() if self.opening_time else None,
            'closing_time': self.closing_time.isoformat() if self.closing_time else None
        }

class Payment(db.Model):
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    allocation_id = db.Column(db.Integer, db.ForeignKey('allocations.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_status = db.Column(db.String(30), nullable=False, default='pending') # 'pending', 'successful', 'failed'
    transaction_id = db.Column(db.String(100), nullable=True)
    receipt_number = db.Column(db.String(100), nullable=True)
    payment_method = db.Column(db.String(50), nullable=True, default='simulated_upi')
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'allocation_id': self.allocation_id,
            'student_id': self.student_id,
            'amount': self.amount,
            'payment_status': self.payment_status,
            'transaction_id': self.transaction_id,
            'receipt_number': self.receipt_number,
            'payment_method': self.payment_method,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(30), nullable=False, default='system') # 'invitation', 'allocation', 'payment', 'system'
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'message': self.message,
            'type': self.type,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(50), nullable=False)
    target_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    admin = db.relationship('User', foreign_keys=[admin_id])

    def to_dict(self):
        return {
            'id': self.id,
            'admin_id': self.admin_id,
            'admin_name': self.admin.name if self.admin else 'System/Scheduler',
            'action': self.action,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'details': self.details,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }
