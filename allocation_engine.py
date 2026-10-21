"""
StayWise — Advanced Algorithm: Priority-Based Greedy Hostel Allocation Engine

Features:
- Min-Heap / Priority Queue (Python heapq) candidate prioritization.
- Priority 1: Exact group-size-to-sharing-capacity match (Rank 0) over compatible match (Rank 1).
- Priority 2: Strict First-Come-First-Served (FCFS) by server submission timestamp.
- Priority 3: Ranked hostel preferences (Preference 1 -> 2 -> 3).
- Every preference has its own: Hostel, Sharing type, Preferred Floor, and Floor Flexibility checkbox.
- Preference 1 alone has preferred room numbers selection.
- Priority 5: Fallback to all other eligible active hostels for that gender/year.
- Priority 6: Transparent waitlisting with recorded diagnostic reasons.
- Atomic group placement: Confirmed groups are always allocated into the same room together.
"""

import heapq
import random
import string
from datetime import datetime, timezone
from models import db, Application, User, Hostel, HostelSharingConfig, Room, Group, GroupMember, Allocation, AllocationRun, WaitlistEntry, Payment, Notification, AuditLog

class CandidateGroup:
    """
    Candidate element inserted into Min-Heap.
    Implements comparison operator to guarantee deterministic heap ordering.
    """
    # Time complexity - O(1)
    # Justification - Initializing scalar and list reference fields takes constant time.
    def __init__(self, mismatch_rank, submitted_at, reg_num, app_ids, member_ids, requested_sharing, group_size, leader_app):
        self.mismatch_rank = mismatch_rank  # 0 for exact match, 1 for compatible
        self.submitted_at = submitted_at      # datetime or ISO string
        self.reg_num = reg_num                # Tie-breaker string
        self.app_ids = app_ids                # List of application IDs in this group
        self.member_ids = member_ids          # List of student user IDs
        self.requested_sharing = requested_sharing
        self.group_size = group_size
        self.leader_app = leader_app

    # Time complexity - O(1)
    # Justification - Constant-time scalar comparisons across integer mismatch rank, timestamp, and string registration number tie-breakers.
    def __lt__(self, other):
        # 1. Exact capacity match (0) outranks compatible match (1)
        if self.mismatch_rank != other.mismatch_rank:
            return self.mismatch_rank < other.mismatch_rank
        # 2. Earlier server-generated submission timestamp (FCFS)
        if self.submitted_at != other.submitted_at:
            return self.submitted_at < other.submitted_at
        # 3. Deterministic tie-breaker by registration number
        return self.reg_num < other.reg_num


# Time complexity - O(A log A + A * R_hostel) where A is the number of candidate applications/groups and R_hostel is the rooms per hostel
# Justification - Building and draining the candidate min-heap takes O(A log A) time, and for each candidate, scanning candidate rooms across preferences takes O(R_hostel) time.
def run_allocation(admin_id=None, cycle_year=2026, commit=False):
    """
    Executes the StayWise Priority-Based Greedy Heap Allocation Algorithm.
    If commit=False: Returns simulated dry-run preview.
    If commit=True: Transactionally persists AllocationRun, Allocations, updates beds, creates Payments.
    """
    now = datetime.now(timezone.utc)
    run_code = f"RUN-{cycle_year}-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    results = {
        'run_code': run_code,
        'allocated': [],
        'waitlisted': [],
        'summary': {
            'total_applications': 0,
            'allocated_count': 0,
            'waitlisted_count': 0,
            'exact_matches': 0,
            'compatible_matches': 0,
            'fallback_matches': 0
        }
    }

    # Fetch submitted applications
    submitted_apps = Application.query.filter_by(status='submitted').all()
    results['summary']['total_applications'] = len(submitted_apps)

    if not submitted_apps:
        return results

    # Virtual bed occupancy tracking to simulate without early committing
    virtual_occupied = {}
    active_rooms = Room.query.filter_by(is_active=True).all()
    for r in active_rooms:
        virtual_occupied[r.id] = r.occupied_beds

    # Map student to application
    app_by_student = {app.student_id: app for app in submitted_apps}
    processed_app_ids = set()

    # Build candidates list and push into Min-Heap
    candidate_heap = []

    # 1. Confirmed Groups
    confirmed_groups = Group.query.filter_by(status='confirmed').all()
    for grp in confirmed_groups:
        memberships = GroupMember.query.filter_by(group_id=grp.id, status='accepted').all()
        member_ids = [grp.leader_student_id] + [m.student_id for m in memberships if m.student_id != grp.leader_student_id]
        
        # Check if all members submitted applications
        group_apps = [app_by_student[m_id] for m_id in member_ids if m_id in app_by_student]
        if len(group_apps) < len(member_ids):
            continue  # Group incomplete or missing submissions

        leader_app = app_by_student.get(grp.leader_student_id)
        if not leader_app:
            continue

        for app in group_apps:
            processed_app_ids.add(app.id)

        # Check requested sharing from preference 1
        req_sharing = leader_app.pref1_sharing
        mismatch_rank = 0 if req_sharing == grp.group_size else 1

        cand = CandidateGroup(
            mismatch_rank=mismatch_rank,
            submitted_at=leader_app.submitted_at,
            reg_num=leader_app.registration_number,
            app_ids=[app.id for app in group_apps],
            member_ids=member_ids,
            requested_sharing=req_sharing,
            group_size=grp.group_size,
            leader_app=leader_app
        )
        heapq.heappush(candidate_heap, cand)

    # 2. Individual Applications
    for app in submitted_apps:
        if app.id in processed_app_ids:
            continue

        req_sharing = app.pref1_sharing
        mismatch_rank = 0 if req_sharing == 1 else 1

        cand = CandidateGroup(
            mismatch_rank=mismatch_rank,
            submitted_at=app.submitted_at,
            reg_num=app.registration_number,
            app_ids=[app.id],
            member_ids=[app.student_id],
            requested_sharing=req_sharing,
            group_size=1,
            leader_app=app
        )
        heapq.heappush(candidate_heap, cand)

    # Cache active hostels and sharing configs for fast hash lookups
    all_hostels = {h.id: h for h in Hostel.query.filter_by(is_active=True).all()}
    all_sharing_configs = {}
    for cfg in HostelSharingConfig.query.filter_by(is_available=True).all():
        all_sharing_configs[(cfg.hostel_id, cfg.sharing_type)] = cfg

    # Process candidates from Min-Heap
    while candidate_heap:
        cand = heapq.heappop(candidate_heap)
        leader = cand.leader_app.student
        group_size = cand.group_size
        allocated_group = False

        # Evaluate 3 Ranked Preferences with per-preference floor and flex_floor
        prefs = [
            (1, cand.leader_app.pref1_hostel_id, cand.leader_app.pref1_sharing, cand.leader_app.pref1_floor, cand.leader_app.pref1_flex_floor),
            (2, cand.leader_app.pref2_hostel_id, cand.leader_app.pref2_sharing, cand.leader_app.pref2_floor, cand.leader_app.pref2_flex_floor),
            (3, cand.leader_app.pref3_hostel_id, cand.leader_app.pref3_sharing, cand.leader_app.pref3_floor, cand.leader_app.pref3_flex_floor),
        ]

        for rank, hostel_id, requested_sharing, preferred_floor, flex_floor in prefs:
            if allocated_group or not hostel_id or not requested_sharing:
                continue

            hostel = all_hostels.get(hostel_id)
            if not hostel or hostel.gender != leader.gender:
                continue

            # Kapila Bhavanam (KAP) is exclusively for female M.Tech and PhD scholars
            if (hostel.code == 'KAP' or hostel.name == 'Kapila Bhavanam') and (leader.gender != 'female' or not getattr(leader, 'is_pg_scholar', False)):
                continue

            # Academic year single-sharing restriction: only year >= 3 or PG scholar can have 1-sharing
            if requested_sharing == 1 and leader.academic_year < 3 and not getattr(leader, 'is_pg_scholar', False):
                continue

            # Check sharing capacity supports group size
            if requested_sharing < group_size:
                continue

            cfg = all_sharing_configs.get((hostel_id, requested_sharing))
            if not cfg:
                continue

            # Candidate rooms in this hostel with matching sharing capacity
            hostel_rooms = [r for r in active_rooms if r.hostel_id == hostel_id and r.sharing_capacity == requested_sharing]
            # Must have available beds >= group_size
            avail_rooms = [r for r in hostel_rooms if (r.sharing_capacity - virtual_occupied[r.id]) >= group_size]

            if not avail_rooms:
                continue

            chosen_room = None

            # Preference 1 Preferred Rooms Check (for rank 1 alone)
            if rank == 1 and cand.leader_app.preferred_rooms:
                pref_room_ids = [pr.room_id for pr in cand.leader_app.preferred_rooms]
                matches = [r for r in avail_rooms if r.id in pref_room_ids]
                if matches:
                    chosen_room = matches[0]

            # Preferred Floor Check for this preference
            if not chosen_room and preferred_floor:
                floor_matches = [r for r in avail_rooms if r.floor == preferred_floor]
                if floor_matches:
                    chosen_room = floor_matches[0]

            # Alternate Floor (Floor flexibility for this preference)
            if not chosen_room and flex_floor:
                chosen_room = avail_rooms[0]

            if chosen_room:
                virtual_occupied[chosen_room.id] += group_size
                is_exact = (chosen_room.sharing_capacity == group_size)
                fee = cfg.fee_amount

                for app_id, s_id in zip(cand.app_ids, cand.member_ids):
                    st = User.query.get(s_id)
                    results['allocated'].append({
                        'application_id': app_id,
                        'student_id': s_id,
                        'student_name': st.name if st else '',
                        'student_roll': st.roll_number if st else '',
                        'hostel_id': hostel.id,
                        'hostel_name': hostel.name,
                        'room_id': chosen_room.id,
                        'room_number': chosen_room.room_number,
                        'floor': chosen_room.floor,
                        'sharing_type': requested_sharing,
                        'preference_rank_satisfied': rank,
                        'is_fallback': False,
                        'is_exact_capacity_match': is_exact,
                        'fee_amount': fee,
                        'group_size': group_size
                    })

                allocated_group = True
                if is_exact:
                    results['summary']['exact_matches'] += 1
                else:
                    results['summary']['compatible_matches'] += 1

        # Priority 5: Fallback to Other Eligible Hostels
        if not allocated_group:
            # Search all other active hostels matching gender (excluding Kapila if not eligible PG scholar)
            fallback_hostels = [
                h for h in all_hostels.values()
                if h.gender == leader.gender and not ((h.code == 'KAP' or h.name == 'Kapila Bhavanam') and not getattr(leader, 'is_pg_scholar', False))
            ]
            
            # Allowed requested sharings from candidate preferences
            candidate_sharings = set([p[2] for p in prefs if p[2] and p[2] >= group_size])
            if not candidate_sharings:
                candidate_sharings = {group_size}

            for f_hostel in fallback_hostels:
                if allocated_group:
                    break
                for f_sharing in sorted(candidate_sharings):
                    if allocated_group:
                        break
                    if f_sharing == 1 and leader.academic_year < 3 and not getattr(leader, 'is_pg_scholar', False):
                        continue

                    cfg = all_sharing_configs.get((f_hostel.id, f_sharing))
                    if not cfg:
                        continue

                    f_rooms = [r for r in active_rooms if r.hostel_id == f_hostel.id and r.sharing_capacity == f_sharing]
                    f_avail = [r for r in f_rooms if (r.sharing_capacity - virtual_occupied[r.id]) >= group_size]

                    if f_avail:
                        chosen_room = f_avail[0]
                        virtual_occupied[chosen_room.id] += group_size
                        is_exact = (chosen_room.sharing_capacity == group_size)

                        for app_id, s_id in zip(cand.app_ids, cand.member_ids):
                            st = User.query.get(s_id)
                            results['allocated'].append({
                                'application_id': app_id,
                                'student_id': s_id,
                                'student_name': st.name if st else '',
                                'student_roll': st.roll_number if st else '',
                                'hostel_id': f_hostel.id,
                                'hostel_name': f_hostel.name,
                                'room_id': chosen_room.id,
                                'room_number': chosen_room.room_number,
                                'floor': chosen_room.floor,
                                'sharing_type': f_sharing,
                                'preference_rank_satisfied': 0, # 0 denotes fallback
                                'is_fallback': True,
                                'is_exact_capacity_match': is_exact,
                                'fee_amount': cfg.fee_amount,
                                'group_size': group_size
                            })

                        allocated_group = True
                        results['summary']['fallback_matches'] += 1

        # Priority 6: Waitlist Entry if still unallocated
        if not allocated_group:
            reason = f"No compatible {group_size}-bed capacity available across submitted 3 preferences or fallback {leader.gender} hostels."
            for app_id, s_id in zip(cand.app_ids, cand.member_ids):
                st = User.query.get(s_id)
                results['waitlisted'].append({
                    'application_id': app_id,
                    'student_id': s_id,
                    'student_name': st.name if st else '',
                    'student_roll': st.roll_number if st else '',
                    'reason': reason
                })

    results['summary']['allocated_count'] = len(results['allocated'])
    results['summary']['waitlisted_count'] = len(results['waitlisted'])

    # Commit results if requested
    if commit:
        # Create AllocationRun record
        alloc_run = AllocationRun(
            run_code=run_code,
            cycle_year=cycle_year,
            admin_id=admin_id,
            total_applications=results['summary']['total_applications'],
            allocated_count=results['summary']['allocated_count'],
            waitlisted_count=results['summary']['waitlisted_count'],
            status='completed',
            executed_at=now
        )
        db.session.add(alloc_run)
        db.session.flush()

        # Commit Allocations & update rooms
        for item in results['allocated']:
            alloc = Allocation(
                run_id=alloc_run.id,
                application_id=item['application_id'],
                student_id=item['student_id'],
                hostel_id=item['hostel_id'],
                room_id=item['room_id'],
                floor=item['floor'],
                sharing_type=item['sharing_type'],
                preference_rank_satisfied=item['preference_rank_satisfied'],
                is_fallback=item['is_fallback'],
                is_exact_capacity_match=item['is_exact_capacity_match'],
                fee_amount=item['fee_amount'],
                status='allocated',
                allocated_at=now
            )
            db.session.add(alloc)
            db.session.flush()

            # Update Room occupied beds
            room = Room.query.get(item['room_id'])
            if room:
                room.occupied_beds += 1

            # Update Application status
            app_rec = Application.query.get(item['application_id'])
            if app_rec:
                app_rec.status = 'allocated'

            # Create Payment record (pending)
            pmt = Payment(
                allocation_id=alloc.id,
                student_id=item['student_id'],
                amount=item['fee_amount'],
                payment_status='pending',
                payment_method='simulated_upi',
                updated_at=now
            )
            db.session.add(pmt)

            # Notification
            pref_text = f"Preference #{item['preference_rank_satisfied']}" if item['preference_rank_satisfied'] > 0 else "Fallback Accommodation"
            notif = Notification(
                user_id=item['student_id'],
                title='Room Allocation Confirmed!',
                message=f"You have been allocated Room {item['room_number']} in {item['hostel_name']} (Floor {item['floor']}, {item['sharing_type']}-Sharing, {pref_text}).",
                type='allocation',
                is_read=False,
                created_at=now
            )
            db.session.add(notif)

        # Commit Waitlist entries
        for w_item in results['waitlisted']:
            entry = WaitlistEntry(
                run_id=alloc_run.id,
                application_id=w_item['application_id'],
                student_id=w_item['student_id'],
                reason=w_item['reason'],
                created_at=now
            )
            db.session.add(entry)

            app_rec = Application.query.get(w_item['application_id'])
            if app_rec:
                app_rec.status = 'waitlisted'

            notif = Notification(
                user_id=w_item['student_id'],
                title='Application Waitlisted',
                message=f"Your room application is on the waitlist: {w_item['reason']}",
                type='allocation',
                is_read=False,
                created_at=now
            )
            db.session.add(notif)

        # Audit Log
        audit = AuditLog(
            admin_id=admin_id,
            action='EXECUTE_ALLOCATION_RUN',
            target_type='allocation_run',
            target_id=alloc_run.id,
            details=f"Run {run_code}: Allocated {results['summary']['allocated_count']}, Waitlisted {results['summary']['waitlisted_count']}.",
            timestamp=now
        )
        db.session.add(audit)
        db.session.commit()

    return results
