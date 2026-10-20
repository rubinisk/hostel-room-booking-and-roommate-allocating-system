import re
from datetime import datetime, timezone
from sqlalchemy import func
from models import db, Program, Section, SequenceAllocation, User

# Fixed Section-Digit Mapping
SECTION_LETTER_TO_DIGIT = {
    'A': 0,
    'B': 1,
    'C': 2,
    'D': 3,
    'E': 4,
    'F': 5,
    'G': 6,
    'H': 7
}

SECTION_DIGIT_TO_LETTER = {v: k for k, v in SECTION_LETTER_TO_DIGIT.items()}

# Configurable defaults
DEFAULT_CAMPUS_CODE = 'CB'
DEFAULT_SCHOOL_CODE = 'SC'
DEFAULT_SECTION_CAPACITY = 65
MIN_SECTION_CAPACITY = 60
MAX_SECTION_CAPACITY = 65

# Regex: {CAMPUS}.{SCHOOL}.{LEVEL}{DUR}{DEPT}{BATCH_2}{SEC_DIGIT}{SEQ_2}
# e.g. CB.SC.U4CSE25547
ROLL_NUMBER_REGEX = re.compile(
    r'^([A-Z0-9]{2,})\.([A-Z0-9]{2,})\.([UP][1-9])([A-Z]{3})(\d{2})([0-7])(\d{2})$'
)

DEPARTMENT_CODE_REGEX = re.compile(r'^[A-Z]{3}$')

class RollNumberValidationError(Exception):
    pass

class SectionCapacityExceededError(Exception):
    pass

def validate_department_code(code: str) -> str:
    """
    Validates that the department code consists of exactly 3 uppercase letters.
    """
    if not code or not isinstance(code, str):
        raise RollNumberValidationError("Department code must be provided.")
    clean = code.strip().upper()
    if not DEPARTMENT_CODE_REGEX.match(clean):
        raise RollNumberValidationError(f"Department code '{clean}' is invalid. It must contain exactly three uppercase alphabetic characters (e.g. 'CSE').")
    return clean

def validate_roll_number_format(roll_number: str) -> bool:
    """
    Validates whether the roll number matches the StayWise configurable format.
    Example: CB.SC.U4CSE25547
    """
    if not roll_number or not isinstance(roll_number, str):
        return False
    clean = roll_number.strip().upper()
    return bool(ROLL_NUMBER_REGEX.match(clean))

def parse_roll_number(roll_number: str) -> dict:
    """
    Parses a StayWise roll number into its component parts.
    Returns a dictionary of parsed components or raises RollNumberValidationError.
    """
    if not roll_number or not isinstance(roll_number, str):
        raise RollNumberValidationError("Roll number cannot be empty.")
    clean = roll_number.strip().upper()
    match = ROLL_NUMBER_REGEX.match(clean)
    if not match:
        raise RollNumberValidationError(f"Roll number '{roll_number}' does not match the configured StayWise format (e.g. CB.SC.U4CSE25547).")
    
    campus_code, school_code, lvl_dur, dept_code, batch_2, sec_digit_str, seq_2_str = match.groups()
    program_level = lvl_dur[0]
    duration_years = int(lvl_dur[1])
    sec_digit = int(sec_digit_str)
    sec_letter = SECTION_DIGIT_TO_LETTER.get(sec_digit, 'A')
    sequence = int(seq_2_str)
    
    if sequence == 0:
        raise RollNumberValidationError("Student sequence 00 is forbidden.")

    return {
        'campus_code': campus_code,
        'school_code': school_code,
        'program_level': program_level,
        'program_duration_years': duration_years,
        'department_code': dept_code,
        'batch_year_short': batch_2,
        'admission_batch_year': 2000 + int(batch_2),
        'section_digit': sec_digit,
        'section_letter': sec_letter,
        'section_sequence': sequence,
        'full_roll_number': clean
    }

def generate_roll_number_atomic(program_id: int, admission_batch_year: int, section_id: int, session=None) -> tuple[str, int]:
    """
    Atomically allocates a new sequence number and generates a StayWise roll number.
    Ensures concurrency safety, sequence uniqueness, and capacity enforcement.
    Returns (generated_roll_number, sequence_number).
    """
    if session is None:
        session = db.session

    program = session.query(Program).filter_by(id=program_id).first()
    if not program or not program.active_status:
        raise RollNumberValidationError("Invalid or inactive academic program.")

    section = session.query(Section).filter_by(id=section_id, program_id=program_id, admission_batch_year=admission_batch_year).first()
    if not section or not section.active_status:
        raise RollNumberValidationError(f"Invalid or inactive section for program '{program.program_name}' in batch {admission_batch_year}.")

    # Atomic sequence allocation row lock
    try:
        alloc = session.query(SequenceAllocation).filter_by(
            program_id=program.id,
            admission_batch_year=admission_batch_year,
            section_id=section.id
        ).with_for_update().first()
    except Exception:
        # Fallback if with_for_update not supported in certain drivers
        alloc = session.query(SequenceAllocation).filter_by(
            program_id=program.id,
            admission_batch_year=admission_batch_year,
            section_id=section.id
        ).first()

    if not alloc:
        alloc = SequenceAllocation(
            program_id=program.id,
            admission_batch_year=admission_batch_year,
            section_id=section.id,
            next_sequence=1,
            last_issued_sequence=0,
            created_at=datetime.now(timezone.utc)
        )
        session.add(alloc)
        session.flush()

    # Enforce capacity
    if alloc.last_issued_sequence >= section.capacity:
        raise SectionCapacityExceededError(
            f"Section {section.section_letter} capacity of {section.capacity} students has been reached for {program.department_code} (Batch {admission_batch_year})."
        )

    next_seq = alloc.last_issued_sequence + 1
    if next_seq <= 0:
        next_seq = 1
    if next_seq > section.capacity:
        raise SectionCapacityExceededError(f"Sequence {next_seq} exceeds configured section capacity of {section.capacity}.")

    alloc.last_issued_sequence = next_seq
    alloc.next_sequence = next_seq + 1
    alloc.updated_at = datetime.now(timezone.utc)

    # Construct Roll Number
    batch_short = f"{admission_batch_year % 100:02d}"
    sec_digit = section.section_digit
    seq_str = f"{next_seq:02d}"

    roll_number = f"{program.campus_code}.{program.school_code}.{program.program_level}{program.program_duration_years}{program.department_code}{batch_short}{sec_digit}{seq_str}"
    
    return roll_number, next_seq


# Initial Catalogue Spec
INITIAL_PROGRAMS_CATALOGUE = [
    # Engineering & Computing
    {
        'program_name': 'Computer Science and Engineering Core',
        'department_code': 'CSE',
        'original_reference_code': 'CSE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 8, # A to H
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Artificial Intelligence and Data Science',
        'department_code': 'AID',
        'original_reference_code': 'AID',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 2,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'AI and Data Science — Medical Engineering',
        'department_code': 'AIM',
        'original_reference_code': 'AIM',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'AI and Data Science — Autonomous Agents and Robotics',
        'department_code': 'AAR',
        'original_reference_code': 'AAR',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'AI and Data Science — Cyber Physical Systems and Security',
        'department_code': 'ACS',
        'original_reference_code': 'ACS',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'AI and Data Science — Quantum Technologies',
        'department_code': 'AQT',
        'original_reference_code': 'AQT',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Computer and Communication Engineering',
        'department_code': 'CCE',
        'original_reference_code': 'CCE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 2,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Electronics and Communication Engineering',
        'department_code': 'ECE',
        'original_reference_code': 'ECE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 2,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Electronics and Computer Engineering',
        'department_code': 'ENC',
        'original_reference_code': 'ENC',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Electrical and Electronics Engineering',
        'department_code': 'EEE',
        'original_reference_code': 'EEE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 2,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Electrical and Computer Engineering',
        'department_code': 'EAC',
        'original_reference_code': 'EAC',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Mechanical Engineering',
        'department_code': 'MEE',
        'original_reference_code': 'MEE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 2,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Aerospace Engineering',
        'department_code': 'AEE',
        'original_reference_code': 'AEE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Chemical Engineering',
        'department_code': 'CHE',
        'original_reference_code': 'CHE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Civil Engineering',
        'department_code': 'CIE',
        'original_reference_code': 'CIE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Automation and Robotics Engineering',
        'department_code': 'ARE',
        'original_reference_code': 'ARE',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Cyber Security',
        'department_code': 'CYS',
        'original_reference_code': 'CYS',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Robotics and Artificial Intelligence',
        'department_code': 'RAI',
        'original_reference_code': 'RAI',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },

    # Additional School & Program Catalogue
    {
        'program_name': 'Bachelor of Computer Applications',
        'department_code': 'BCA',
        'original_reference_code': 'BCA',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 2,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Business Administration',
        'department_code': 'BBA',
        'original_reference_code': 'BBA',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 2,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Commerce',
        'department_code': 'BCM',
        'original_reference_code': 'BCM',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 2,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'B.A. LL.B. (Hons.)',
        'department_code': 'BAL',
        'original_reference_code': 'BAL',
        'program_level': 'U',
        'program_duration_years': 5,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'B.B.A. LL.B. (Hons.)',
        'department_code': 'BBL',
        'original_reference_code': 'BBL',
        'program_level': 'U',
        'program_duration_years': 5,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Master of Laws',
        'department_code': 'LLM',
        'original_reference_code': 'LLM',
        'program_level': 'P',
        'program_duration_years': 1,
        'sections_count': 1,
        'level_category': 'postgraduate'
    },
    {
        'program_name': 'Architecture',
        'department_code': 'ARC',
        'original_reference_code': 'ARC',
        'program_level': 'U',
        'program_duration_years': 5,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Agriculture',
        'department_code': 'AGR',
        'original_reference_code': 'AGR',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Physics',
        'department_code': 'PHY',
        'original_reference_code': 'PHY',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Chemistry',
        'department_code': 'CHY',
        'original_reference_code': 'CHY',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Mathematics',
        'department_code': 'MAT',
        'original_reference_code': 'MAT',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Data Science',
        'department_code': 'DSC',
        'original_reference_code': 'DSC',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Food Science and Nutrition',
        'department_code': 'FSN',
        'original_reference_code': 'FSN',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Biotechnology',
        'department_code': 'BTC',
        'original_reference_code': 'BTC',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Microbiology',
        'department_code': 'MIC',
        'original_reference_code': 'MIC',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Psychology',
        'department_code': 'PSY',
        'original_reference_code': 'PSY',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Social Work',
        'department_code': 'BSW',
        'original_reference_code': 'BSW',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Mass Communication',
        'department_code': 'MCO',
        'original_reference_code': 'MCO',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'Communication Design',
        'department_code': 'VCD',
        'original_reference_code': 'VCD',
        'program_level': 'U',
        'program_duration_years': 4,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'English',
        'department_code': 'ENG',
        'original_reference_code': 'ENG',
        'program_level': 'U',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'undergraduate'
    },
    {
        'program_name': 'MBA',
        'department_code': 'MBA',
        'original_reference_code': 'MBA',
        'program_level': 'P',
        'program_duration_years': 2,
        'sections_count': 2,
        'level_category': 'postgraduate'
    },
    {
        'program_name': 'Computer Science and Engineering M.Tech',
        'department_code': 'CSE',
        'original_reference_code': 'MTECH-CSE',
        'program_level': 'P',
        'program_duration_years': 2,
        'sections_count': 1,
        'level_category': 'postgraduate'
    },
    {
        'program_name': 'Computer Science and Engineering PhD',
        'department_code': 'CSE',
        'original_reference_code': 'PHD-CSE',
        'program_level': 'P',
        'program_duration_years': 3,
        'sections_count': 1,
        'level_category': 'postgraduate'
    }
]
