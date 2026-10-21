from werkzeug.security import generate_password_hash
from models import (
    db, User, Hostel, HostelSharingConfig, Room, ApplicationPreferredRoom, Allocation,
    Program, Section, SequenceAllocation
)
from scheduler import get_or_create_settings
from roll_number_service import (
    INITIAL_PROGRAMS_CATALOGUE, SECTION_LETTER_TO_DIGIT,
    DEFAULT_SECTION_CAPACITY, DEFAULT_CAMPUS_CODE, DEFAULT_SCHOOL_CODE
)

# Time complexity - O(C_table) where C_table is the number of database schema columns checked
# Justification - Executes PRAGMA table inspection queries and applies missing schema ALTER statements in linear time relative to columns.
def check_and_apply_migrations():
    """Ensure database tables have new columns without breaking SQLite integrity."""
    try:
        with db.engine.connect() as conn:
            # Check users table columns
            u_cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()]
            if 'degree_level' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN degree_level VARCHAR(50) DEFAULT 'B.Tech'")
            if 'legacy_roll_number' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN legacy_roll_number VARCHAR(50)")
            if 'program_id' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN program_id INTEGER")
            if 'section_id' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN section_id INTEGER")
            if 'campus_code' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN campus_code VARCHAR(10) DEFAULT 'CB'")
            if 'school_code' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN school_code VARCHAR(10) DEFAULT 'SC'")
            if 'program_level' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN program_level VARCHAR(5) DEFAULT 'U'")
            if 'program_duration_years' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN program_duration_years INTEGER DEFAULT 4")
            if 'department_code' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN department_code VARCHAR(3) DEFAULT 'CSE'")
            if 'admission_batch_year' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN admission_batch_year INTEGER DEFAULT 2025")
            if 'section_letter' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN section_letter VARCHAR(2) DEFAULT 'A'")
            if 'section_digit' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN section_digit INTEGER DEFAULT 0")
            if 'section_sequence' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN section_sequence INTEGER DEFAULT 1")
            if 'program_level_category' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN program_level_category VARCHAR(30) DEFAULT 'undergraduate'")
            if 'synthetic_demo_record' not in u_cols:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN synthetic_demo_record BOOLEAN DEFAULT 1")
            
            # Check rooms table columns
            r_cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(rooms)").fetchall()]
            if 'room_code' not in r_cols:
                conn.exec_driver_sql("ALTER TABLE rooms ADD COLUMN room_code VARCHAR(50)")

            # Drop old single-column unique index on room_number if present
            try:
                conn.exec_driver_sql("DROP INDEX IF EXISTS ix_rooms_room_number")
            except Exception:
                pass
    except Exception as e:
        print(f"Migration notice: {e}")

# Complete 13 Hostels Specification
HOSTELS_SPEC = [
    # 1. Gargi Bhavanam (GAR) - Girls
    {
        'name': 'Gargi Bhavanam',
        'code': 'GAR',
        'gender': 'female',
        'description': 'Comfortable girls residence with modern study spaces and quiet academic environment.',
        'sharings': [(1, 75000.0), (3, 55000.0)],
        # Floor 1-4: 50 single-sharing (001-050), 50 three-sharing (051-100)
        'room_capacity_fn': lambda floor, r_num: 1 if r_num <= 50 else 3
    },
    # 2. Mythreyi Bhavanam (MYT) - Girls
    {
        'name': 'Mythreyi Bhavanam',
        'code': 'MYT',
        'gender': 'female',
        'description': 'Active campus residence with vibrant student community and spacious rooms.',
        'sharings': [(2, 65000.0), (3, 55000.0), (4, 45000.0)],
        # Floor 1: 46 two-sharing (001-046), 8 three-sharing (047-054), 46 four-sharing (055-100)
        # Floor 2-4: 50 two-sharing (001-050), 50 four-sharing (051-100)
        'room_capacity_fn': lambda floor, r_num: (
            (2 if r_num <= 46 else (3 if r_num <= 54 else 4)) if floor == 1
            else (2 if r_num <= 50 else 4)
        )
    },
    # 3. Adithi Bhavanam (ADI) - Girls
    {
        'name': 'Adithi Bhavanam',
        'code': 'ADI',
        'gender': 'female',
        'description': 'Contemporary residence block with green courtyards and dedicated reading rooms.',
        'sharings': [(1, 75000.0), (4, 45000.0)],
        # Floor 1-4: 50 single-sharing (001-050), 50 four-sharing (051-100)
        'room_capacity_fn': lambda floor, r_num: 1 if r_num <= 50 else 4
    },
    # 4. Savithri Bhavanam (SAV) - Girls
    {
        'name': 'Savithri Bhavanam',
        'code': 'SAV',
        'gender': 'female',
        'description': 'Spacious block featuring single-sharing on Floor 1 and shared suites on upper floors.',
        'sharings': [(1, 75000.0), (2, 65000.0), (4, 45000.0)],
        # Floor 1: 100 single-sharing (001-100)
        # Floor 2-4: 50 two-sharing (001-050), 50 four-sharing (051-100)
        'room_capacity_fn': lambda floor, r_num: 1 if floor == 1 else (2 if r_num <= 50 else 4)
    },
    # 5. Kapila Bhavanam (KAP) - Girls (PG Scholars Only)
    {
        'name': 'Kapila Bhavanam',
        'code': 'KAP',
        'gender': 'female',
        'description': 'Designated research accommodation exclusively for female M.Tech and PhD scholars.',
        'sharings': [(1, 75000.0)],
        # Floor 1-4: 100 single-sharing (001-100)
        'room_capacity_fn': lambda floor, r_num: 1
    },

    # 6. Agasthya Bhavanam (AGA) - Boys
    {
        'name': 'Agasthya Bhavanam',
        'code': 'AGA',
        'gender': 'male',
        'description': 'Spacious 4-sharing accommodation block close to campus sports complex.',
        'sharings': [(4, 45000.0)],
        # Floor 1-4: 100 four-sharing (001-100)
        'room_capacity_fn': lambda floor, r_num: 4
    },
    # 7. Gauthama Bhavanam (GAU) - Boys
    {
        'name': 'Gauthama Bhavanam',
        'code': 'GAU',
        'gender': 'male',
        'description': 'Single-occupancy residence designed for focused individual study and seniors.',
        'sharings': [(1, 75000.0)],
        # Floor 1-4: 100 single-sharing (001-100)
        'room_capacity_fn': lambda floor, r_num: 1
    },
    # 8. Vasishta Bhavanam (VAS) - Boys
    {
        'name': 'Vasishta Bhavanam',
        'code': 'VAS',
        'gender': 'male',
        'description': 'Community living residence with spacious four-sharing rooms and study halls.',
        'sharings': [(4, 45000.0)],
        # Floor 1-4: 100 four-sharing (001-100)
        'room_capacity_fn': lambda floor, r_num: 4
    },
    # 9. Sri Vyasa Maharshi Bhavanam (VYA) - Boys
    {
        'name': 'Sri Vyasa Maharshi Bhavanam',
        'code': 'VYA',
        'gender': 'male',
        'description': 'Quiet single-occupancy residence block situated in the north campus.',
        'sharings': [(1, 75000.0)],
        # Floor 1-4: 100 single-sharing (001-100)
        'room_capacity_fn': lambda floor, r_num: 1
    },
    # 10. Nachiketas Bhavanam (NAC) - Boys
    {
        'name': 'Nachiketas Bhavanam',
        'code': 'NAC',
        'gender': 'male',
        'description': 'Modern single-sharing accommodation with high-speed internet and library access.',
        'sharings': [(1, 75000.0)],
        # Floor 1-4: 100 single-sharing (001-100)
        'room_capacity_fn': lambda floor, r_num: 1
    },
    # 11. Yagnavalkya Bhavanam (YAG) - Boys
    {
        'name': 'Yagnavalkya Bhavanam',
        'code': 'YAG',
        'gender': 'male',
        'description': 'Four-sharing residence featuring recreational lounges and green outdoor areas.',
        'sharings': [(4, 45000.0)],
        # Floor 1-4: 100 four-sharing (001-100)
        'room_capacity_fn': lambda floor, r_num: 4
    },
    # 12. Kashyapa Bhavanam (KAS) - Boys
    {
        'name': 'Kashyapa Bhavanam',
        'code': 'KAS',
        'gender': 'male',
        'description': 'Multi-sharing residence with triple and four-sharing rooms across four floors.',
        'sharings': [(3, 55000.0), (4, 45000.0)],
        # Floor 1: 100 three-sharing (001-100)
        # Floor 2-4: 50 three-sharing (001-050), 50 four-sharing (051-100)
        'room_capacity_fn': lambda floor, r_num: 3 if floor == 1 else (3 if r_num <= 50 else 4)
    },
    # 13. Bhrigu Bhavanam (BRI) - Boys
    {
        'name': 'Bhrigu Bhavanam',
        'code': 'BRI',
        'gender': 'male',
        'description': 'Versatile residence block featuring single, double, and triple-sharing accommodation.',
        'sharings': [(1, 75000.0), (2, 65000.0), (3, 55000.0)],
        # Floor 1: 100 single-sharing (001-100)
        # Floor 2-4: 50 two-sharing (001-050), 50 three-sharing (051-100)
        'room_capacity_fn': lambda floor, r_num: 1 if floor == 1 else (2 if r_num <= 50 else 3)
    },
]

# Time complexity - O(P + H * R + N_seed) where P is programs, H is hostels, R is rooms, and N_seed is initial demo students
# Justification - Idempotently creates tables, inserts programs, hostel room inventory, demo student accounts, and sample applications.
def seed_database():
    db.create_all()
    check_and_apply_migrations()

    # Seed application settings
    get_or_create_settings()

    # 1. Seed Academic Programs Catalogue & Sections (Idempotent)
    programs_map = {}
    for p_spec in INITIAL_PROGRAMS_CATALOGUE:
        prog = Program.query.filter_by(
            campus_code=DEFAULT_CAMPUS_CODE,
            department_code=p_spec['department_code'],
            program_level=p_spec['program_level'],
            program_duration_years=p_spec['program_duration_years']
        ).first()
        if not prog:
            prog = Program(
                campus_code=DEFAULT_CAMPUS_CODE,
                school_code=DEFAULT_SCHOOL_CODE,
                program_name=p_spec['program_name'],
                original_reference_code=p_spec['original_reference_code'],
                department_code=p_spec['department_code'],
                program_level=p_spec['program_level'],
                program_duration_years=p_spec['program_duration_years'],
                active_status=True,
                configuration_version=1
            )
            db.session.add(prog)
            db.session.flush()

        programs_map[(p_spec['department_code'], p_spec['program_level'], p_spec['program_duration_years'])] = prog

        # Seed sections for admission batches 2025, 2024, 2023, 2022
        sections_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
        num_sections = p_spec.get('sections_count', 1)
        for b_year in [2025, 2024, 2023, 2022]:
            for s_idx in range(num_sections):
                s_letter = sections_letters[s_idx]
                s_digit = SECTION_LETTER_TO_DIGIT[s_letter]
                sec = Section.query.filter_by(
                    program_id=prog.id,
                    admission_batch_year=b_year,
                    section_letter=s_letter
                ).first()
                if not sec:
                    sec = Section(
                        program_id=prog.id,
                        admission_batch_year=b_year,
                        section_letter=s_letter,
                        section_digit=s_digit,
                        capacity=DEFAULT_SECTION_CAPACITY,
                        active_status=True
                    )
                    db.session.add(sec)
                    db.session.flush()

                seq_alloc = SequenceAllocation.query.filter_by(
                    program_id=prog.id,
                    admission_batch_year=b_year,
                    section_id=sec.id
                ).first()
                if not seq_alloc:
                    seq_alloc = SequenceAllocation(
                        program_id=prog.id,
                        admission_batch_year=b_year,
                        section_id=sec.id,
                        next_sequence=1,
                        last_issued_sequence=0
                    )
                    db.session.add(seq_alloc)
    db.session.commit()

    # 2. Seed Demo Users (Idempotent, with StayWise Configurable Roll Numbers)
    cse_u4 = programs_map.get(('CSE', 'U', 4))
    cse_p2 = programs_map.get(('CSE', 'P', 2))
    cse_p3 = programs_map.get(('CSE', 'P', 3))

    seed_users = [
        # Admin
        {
            'legacy_roll': 'ADMIN',
            'roll_number': 'ADMIN',
            'name': 'System Administrator',
            'email': 'admin@staywise.edu',
            'password': 'admin123',
            'role': 'admin',
            'gender': 'male',
            'academic_year': 4,
            'degree_level': 'Faculty',
            'program': None,
            'batch': 2022,
            'section_letter': 'A',
            'sequence': 1
        },
        # Female Students (B.Tech & Postgraduate Scholars)
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE24001',
            'name': 'Ananya Sharma',
            'email': 'ananya@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'female',
            'academic_year': 3,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2024,
            'section_letter': 'A',
            'sequence': 1
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE24002',
            'name': 'Riya Patel',
            'email': 'riya@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'female',
            'academic_year': 3,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2024,
            'section_letter': 'A',
            'sequence': 2
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE25001',
            'name': 'Meera Krishnan',
            'email': 'meera@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'female',
            'academic_year': 2,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2025,
            'section_letter': 'A',
            'sequence': 1
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.P2CSE25001',
            'name': 'Priya Singh',
            'email': 'priya@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'female',
            'academic_year': 2,
            'degree_level': 'M.Tech',
            'program': cse_p2,
            'batch': 2025,
            'section_letter': 'A',
            'sequence': 1
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.P3CSE24001',
            'name': 'Sneha Verma',
            'email': 'sneha@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'female',
            'academic_year': 2,
            'degree_level': 'PhD',
            'program': cse_p3,
            'batch': 2024,
            'section_letter': 'A',
            'sequence': 1
        },
        # Male Students
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE24003',
            'name': 'Aarav Gupta',
            'email': 'aarav@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'male',
            'academic_year': 3,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2024,
            'section_letter': 'A',
            'sequence': 3
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE24004',
            'name': 'Rohan Kumar',
            'email': 'rohan@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'male',
            'academic_year': 3,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2024,
            'section_letter': 'A',
            'sequence': 4
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE25002',
            'name': 'Aditya Varma',
            'email': 'aditya@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'male',
            'academic_year': 2,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2025,
            'section_letter': 'A',
            'sequence': 2
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE25547',
            'name': 'Rahul Verma',
            'email': 'rahul@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'male',
            'academic_year': 2,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2025,
            'section_letter': 'F',
            'sequence': 47
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE22001',
            'name': 'Vikram Joshi',
            'email': 'vikram@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'male',
            'academic_year': 4,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2022,
            'section_letter': 'A',
            'sequence': 1
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.U4CSE22002',
            'name': 'Siddharth Nair',
            'email': 'siddharth@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'male',
            'academic_year': 4,
            'degree_level': 'B.Tech',
            'program': cse_u4,
            'batch': 2022,
            'section_letter': 'A',
            'sequence': 2
        },
        # Additional Scholars
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.P3CSE23001',
            'name': 'Divya Sundaram',
            'email': 'divya@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'female',
            'academic_year': 3,
            'degree_level': 'PhD',
            'program': cse_p3,
            'batch': 2023,
            'section_letter': 'A',
            'sequence': 1
        },
        {
            'legacy_roll': None,
            'roll_number': 'CB.SC.P2CSE24001',
            'name': 'Karthik Raja',
            'email': 'karthik@staywise.edu',
            'password': 'student123',
            'role': 'student',
            'gender': 'male',
            'academic_year': 2,
            'degree_level': 'M.Tech',
            'program': cse_p2,
            'batch': 2024,
            'section_letter': 'A',
            'sequence': 1
        },
    ]

    # --- Additional 150 Students (75 Female, 75 Male) ---
    female_first_names = [
        'Aishwarya', 'Akshaya', 'Anusha', 'Aparna', 'Bhavna', 'Charu', 'Deepika', 'Dhanya', 'Divya', 'Gayatri',
        'Geetha', 'Harini', 'Haritha', 'Ishita', 'Janani', 'Kavya', 'Keerthana', 'Krithika', 'Lavanya', 'Madhuri',
        'Malini', 'Mythili', 'Nandini', 'Neha', 'Nithya', 'Pallavi', 'Pavithra', 'Pooja', 'Preethi', 'Rachana',
        'Radhika', 'Rekha', 'Sahana', 'Saranya', 'Shobha', 'Shreya', 'Shruti', 'Sindhu', 'Sowmya', 'Swathi',
        'Tanvi', 'Tejaswini', 'Trisha', 'Uma', 'Vaishnavi', 'Vani', 'Varsha', 'Vidya', 'Yamini', 'Aditi',
        'Bhavani', 'Deepti', 'Gauri', 'Hemalatha', 'Jayanthi', 'Kausalya', 'Lakshmi', 'Manju', 'Padma', 'Revathi',
        'Sudha', 'Usha', 'Vijaya', 'Aarthi', 'Ashwini', 'Kalyani', 'Lata', 'Nirupama', 'Sujatha', 'Tara',
        'Bina', 'Damini', 'Esha', 'Falguni', 'Gitanjali'
    ]
    male_first_names = [
        'Abhinav', 'Ajay', 'Akash', 'Akhil', 'Amrit', 'Arjun', 'Ashwin', 'Balaji', 'Bharat', 'Bharath',
        'Bhuvan', 'Chandan', 'Charan', 'Chetan', 'Darshan', 'Deepak', 'Deva', 'Dinesh', 'Ganesh', 'Gautham',
        'Girish', 'Gokul', 'Guru', 'Hari', 'Harish', 'Harsha', 'Hemanth', 'Jagdish', 'Jayesh', 'Jeevan',
        'Kaushik', 'Kiran', 'Kishore', 'Lokesh', 'Madhav', 'Manoj', 'Mohan', 'Mukund', 'Naresh', 'Naveen',
        'Nikhil', 'Nithin', 'Omkar', 'Parth', 'Pradeep', 'Pranav', 'Praveen', 'Raghu', 'Rajesh', 'Ramesh',
        'Rohit', 'Sachin', 'Sai', 'Sandeep', 'Sanjay', 'Sharath', 'Sriram', 'Surya', 'Tarun', 'Teja',
        'Uday', 'Varun', 'Venkat', 'Vignesh', 'Vishal', 'Vivek', 'Yash', 'Yogesh', 'Anirudh', 'Bhaskar',
        'Chinmay', 'Devesh', 'Eeshan', 'Farhan', 'Govind'
    ]
    last_names = [
        'Sharma', 'Patel', 'Iyer', 'Nair', 'Kumar', 'Reddy', 'Verma', 'Joshi', 'Rao', 'Das',
        'Gupta', 'Sen', 'Pillai', 'Menon', 'Murthy', 'Bhat', 'Kulkarni', 'Hegde', 'Nambiar', 'Deshmukh',
        'Chopra', 'Bansal', 'Agarwal', 'Mittal', 'Mishra', 'Pandey', 'Tripathi', 'Shukla', 'Chatterjee', 'Banerjee',
        'Ghosh', 'Bose', 'Roy', 'Dutta', 'Paul', 'Bhattacharya', 'Shenoy', 'Prabhu', 'Kamath', 'Nayak'
    ]

    batches_config = [
        (2024, 3),
        (2025, 2),
        (2023, 4),
    ]

    f_idx = 0
    for b_year, a_yr in batches_config:
        for seq in range(1, 26):
            fname = female_first_names[f_idx]
            lname = last_names[f_idx % len(last_names)]
            roll = f'CB.SC.U4CSE{str(b_year)[-2:]}2{seq:02d}'
            email = f'{fname.lower()}.{lname.lower()}{b_year}{seq}@staywise.edu'
            seed_users.append({
                'legacy_roll': None,
                'roll_number': roll,
                'name': f'{fname} {lname}',
                'email': email,
                'password': 'student123',
                'role': 'student',
                'gender': 'female',
                'academic_year': a_yr,
                'degree_level': 'B.Tech',
                'program': cse_u4,
                'batch': b_year,
                'section_letter': 'C',
                'sequence': seq
            })
            f_idx += 1

    m_idx = 0
    for b_year, a_yr in batches_config:
        for seq in range(1, 26):
            mname = male_first_names[m_idx]
            lname = last_names[m_idx % len(last_names)]
            roll = f'CB.SC.U4CSE{str(b_year)[-2:]}3{seq:02d}'
            email = f'{mname.lower()}.{lname.lower()}{b_year}{seq}@staywise.edu'
            seed_users.append({
                'legacy_roll': None,
                'roll_number': roll,
                'name': f'{mname} {lname}',
                'email': email,
                'password': 'student123',
                'role': 'student',
                'gender': 'male',
                'academic_year': a_yr,
                'degree_level': 'B.Tech',
                'program': cse_u4,
                'batch': b_year,
                'section_letter': 'D',
                'sequence': seq
            })
            m_idx += 1

    for u_data in seed_users:
        leg = u_data['legacy_roll']
        gen_roll = u_data['roll_number']
        prog = u_data['program']
        batch = u_data['batch']
        sec_letter = u_data['section_letter']
        sec_digit = SECTION_LETTER_TO_DIGIT.get(sec_letter, 0)
        seq_num = u_data['sequence']

        # Find section if program exists
        sec = None
        if prog:
            sec = Section.query.filter_by(
                program_id=prog.id,
                admission_batch_year=batch,
                section_letter=sec_letter
            ).first()

        # Find existing by roll_number or email
        u = User.query.filter(
            (User.roll_number == gen_roll) |
            (User.email == u_data.get('email'))
        ).first()

        if u:
            u.roll_number = gen_roll
            u.legacy_roll_number = leg
            u.academic_year = u_data['academic_year']
            u.gender = u_data['gender']
            u.degree_level = u_data['degree_level']
            if prog and sec:
                u.program_id = prog.id
                u.section_id = sec.id
                u.campus_code = prog.campus_code
                u.school_code = prog.school_code
                u.program_level = prog.program_level
                u.program_duration_years = prog.program_duration_years
                u.department_code = prog.department_code
                u.admission_batch_year = batch
                u.section_letter = sec_letter
                u.section_digit = sec_digit
                u.section_sequence = seq_num
                u.program_level_category = 'postgraduate' if prog.program_level == 'P' else 'undergraduate'
                u.synthetic_demo_record = True
        else:
            user = User(
                roll_number=gen_roll,
                legacy_roll_number=leg,
                name=u_data['name'],
                email=u_data['email'],
                password_hash=generate_password_hash(u_data['password']),
                role=u_data['role'],
                gender=u_data['gender'],
                academic_year=u_data['academic_year'],
                degree_level=u_data.get('degree_level', 'B.Tech'),
                program_id=prog.id if prog else None,
                section_id=sec.id if sec else None,
                campus_code=prog.campus_code if prog else 'CB',
                school_code=prog.school_code if prog else 'SC',
                program_level=prog.program_level if prog else 'U',
                program_duration_years=prog.program_duration_years if prog else 4,
                department_code=prog.department_code if prog else 'CSE',
                admission_batch_year=batch,
                section_letter=sec_letter,
                section_digit=sec_digit,
                section_sequence=seq_num,
                program_level_category='postgraduate' if (prog and prog.program_level == 'P') else 'undergraduate',
                synthetic_demo_record=True,
                is_active=True
            )
            db.session.add(user)

        # Update sequence allocation counter so next registration is higher than seed
        if prog and sec:
            alloc = SequenceAllocation.query.filter_by(
                program_id=prog.id,
                admission_batch_year=batch,
                section_id=sec.id
            ).first()
            if alloc and alloc.last_issued_sequence < seq_num:
                alloc.last_issued_sequence = seq_num
                alloc.next_sequence = seq_num + 1

    db.session.commit()

    # 2. Cleanup legacy/stale hostels and non-standard rooms from prior prototypes
    valid_codes = {h['code'] for h in HOSTELS_SPEC}
    valid_names = {h['name'] for h in HOSTELS_SPEC}
    
    # Remove any rooms not matching the new floor numbering prefixes (G-, F-, S-, T-)
    legacy_rooms = Room.query.filter(
        ~Room.room_number.like('G-%') &
        ~Room.room_number.like('F-%') &
        ~Room.room_number.like('S-%') &
        ~Room.room_number.like('T-%')
    ).all()
    if legacy_rooms:
        l_ids = [r.id for r in legacy_rooms]
        ApplicationPreferredRoom.query.filter(ApplicationPreferredRoom.room_id.in_(l_ids)).delete(synchronize_session=False)
        Allocation.query.filter(Allocation.room_id.in_(l_ids)).delete(synchronize_session=False)
        Room.query.filter(Room.id.in_(l_ids)).delete(synchronize_session=False)
        db.session.commit()

    legacy_hostels = Hostel.query.filter(~Hostel.code.in_(valid_codes) & ~Hostel.name.in_(valid_names)).all()
    if legacy_hostels:
        for lh in legacy_hostels:
            db.session.delete(lh)
        db.session.commit()

    # 3. Seed Exactly 13 Hostels and 5,200 Rooms
    existing_hostels_by_code = {h.code: h for h in Hostel.query.filter(Hostel.code.isnot(None)).all()}
    existing_hostels_by_name = {h.name: h for h in Hostel.query.all()}

    # Cache existing hostel rooms (hostel_id, room_number) and room_codes to guarantee idempotency
    existing_hostel_rooms = {(r.hostel_id, r.room_number) for r in Room.query.all()}

    total_new_rooms = 0

    for h_spec in HOSTELS_SPEC:
        code = h_spec['code']
        name = h_spec['name']

        # Get or create hostel
        hostel = existing_hostels_by_code.get(code) or existing_hostels_by_name.get(name)
        if not hostel:
            hostel = Hostel(
                name=name,
                code=code,
                gender=h_spec['gender'],
                description=h_spec['description'],
                total_floors=4,
                is_active=True
            )
            db.session.add(hostel)
            db.session.flush()
        else:
            hostel.code = code
            hostel.name = name
            hostel.description = h_spec['description']
            hostel.gender = h_spec['gender']
            hostel.total_floors = 4
            hostel.is_active = True

        # Sync sharing configurations (idempotent)
        existing_configs = {c.sharing_type: c for c in HostelSharingConfig.query.filter_by(hostel_id=hostel.id).all()}
        for sharing_type, fee in h_spec['sharings']:
            if sharing_type in existing_configs:
                cfg = existing_configs[sharing_type]
                cfg.fee_amount = fee
                cfg.is_available = True
            else:
                cfg = HostelSharingConfig(
                    hostel_id=hostel.id,
                    sharing_type=sharing_type,
                    fee_amount=fee,
                    is_available=True
                )
                db.session.add(cfg)

        # Deactivate sharing configs not present in this hostel's spec
        spec_sharings = {s[0] for s in h_spec['sharings']}
        for st, cfg in existing_configs.items():
            if st not in spec_sharings:
                cfg.is_available = False

        # Seed 100 rooms per floor across 4 floors (Total 400 rooms per hostel, 5,200 overall)
        # Ground floor: G-101 to G-199 (1..99), G-200 (100)
        # First floor: F-200 to F-299 (1..100)
        # Second floor: S-300 to S-399 (1..100)
        # Third floor: T-400 to T-499 (1..100)
        new_rooms_batch = []
        for floor in range(1, 5):
            for r_num in range(1, 101):
                if floor == 1:
                    r_no = f"G-{100 + r_num}"
                elif floor == 2:
                    r_no = f"F-{200 + (r_num - 1)}"
                elif floor == 3:
                    r_no = f"S-{300 + (r_num - 1)}"
                else: # floor == 4
                    r_no = f"T-{400 + (r_num - 1)}"

                r_code = f"{code}-{r_no}"

                if (hostel.id, r_no) not in existing_hostel_rooms:
                    capacity = h_spec['room_capacity_fn'](floor, r_num)
                    room = Room(
                        hostel_id=hostel.id,
                        room_number=r_no,
                        room_code=r_code,
                        floor=floor,
                        sharing_capacity=capacity,
                        occupied_beds=0,
                        is_active=True
                    )
                    new_rooms_batch.append(room)
                    existing_hostel_rooms.add((hostel.id, r_no))
                    total_new_rooms += 1

        if new_rooms_batch:
            db.session.bulk_save_objects(new_rooms_batch)

    db.session.commit()
    total_db_rooms = Room.query.count()
    print(f"Database seeded: {len(HOSTELS_SPEC)} Hostels, {total_db_rooms} Total Rooms.")

if __name__ == '__main__':
    from app import app
    with app.app_context():
        seed_database()
