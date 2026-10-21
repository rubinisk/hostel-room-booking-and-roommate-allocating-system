# Smart Priority-Based Hostel Room Allocation & Roommate Matching System

A production-ready, algorithm-driven hostel room allocation and roommate grouping platform engineered with advanced Data Structures and Algorithms (DSA) to ensure transparency, fairness, and automated conflict-free placement.

---

### Live Interactive Demo
**Access the Live Web Application:** **[StayWise — Smart Hostel Room Booking & Allocation System](https://smart-priority-based-hostel-room-al.vercel.app/)**

> *Note: The full-stack interactive client is deployed on Vercel and connected to our cloud backend to visualize the 4 core DSA allocation algorithms in real time.*

---

## System Architecture & DSA Modules

The backend architecture is modularly divided across 4 core Data Structures and Algorithm paradigms:

```
[Student Registration & B-Tree Schema] ──> [Roommate Clustering (DSU)] ──> [Candidate Ranking (Min-Heap)] ──> [Greedy Allocation Engine]
```

### 1. Disjoint Set Union (DSU / Union-Find) — Roommate Clustering
* **Implementation:** `dsu.py`, `student_routes.py`
* **DSA Concepts:** Union-Find with **Path Compression** and **Union by Rank / Size**.
* **Functionality:** 
  * Allows students to send and accept roommate invitations to form clusters of up to 4 members.
  * Guarantees cycle detection and prevents students from joining overlapping or conflicting groups.
  * Achieves near-constant amortized time complexity $\mathcal{O}(\alpha(N))$ per operation (where $\alpha$ is the Inverse Ackermann Function).

### 2. Priority Queue / Min-Heap — Candidate Ranking & Scheduling
* **Implementation:** `app.py`, `config.py`, `scheduler.py`, `payment_routes.py`, `test_allocation.py`
* **DSA Concepts:** Binary Min-Heap (`heapq`), Hash Maps for $\mathcal{O}(1)$ preference lookups.
* **Functionality:**
  * Evaluates multi-tiered student room preferences and builds priority tuples: `(capacity_mismatch_rank, submission_timestamp, registration_number)`.
  * Background timer (`scheduler.py`) automatically triggers batch allocation rounds and manages payment deadline windows.

### 3. Greedy Algorithm — Room Placement & Atomic Group Placement
* **Implementation:** `allocation_engine.py`, `admin_routes.py`, `test_application_lifecycle.py`
* **DSA Concepts:** Greedy Choice Property, Constraint Satisfaction, Atomic Group Placement.
* **Functionality:**
  * Iteratively pops highest-priority applicants from the heap and greedily assigns the optimal matching hostel room.
  * **Atomic Placement Guarantee:** Confirmed roommate groups are treated as indivisible units; friends are never split across separate rooms.
  * Admin dashboard endpoints provide real-time inventory management, allocation round triggering, and manual overrides.

### 4. B-Tree Database Indexing & Relational Schema
* **Implementation:** `models.py`, `roll_number_service.py`, `auth_routes.py`, `seed.py`
* **DSA Concepts:** Balanced B-Tree indexing on foreign keys and unique constraints ($\mathcal{O}(\log N)$ lookups), deterministic regex parsing.
* **Functionality:**
  * Relational database tables for Users, Hostels, Rooms, Applications, and Roommate Groups.
  * Automated roll number parsing and atomic sequence allocation based on campus, school, degree level, and admission year.
  * Secure JWT authentication with role-based access control (Student vs. Admin).

---

## Team Contributions

| Member | Module & DSA Topic | Core Files Contributed |
| :--- | :--- | :--- |
| **Midhuna** | **B-Tree Database Schema & Roll Number System** | `models.py`, `roll_number_service.py`, `auth_routes.py`, `test_hostel_inventory.py`, `test_roll_number_system.py` |
| **Rubini** | **Disjoint Set Union (DSU) & Roommate Clustering** | `dsu.py`, `student_routes.py`, `test_dsu.py`, `test_workflow.py` |
| **Kanishka** | **Priority Queue / Min-Heap & Scheduling Engine** | `app.py`, `config.py`, `scheduler.py`, `payment_routes.py`, `test_allocation.py` |
| **Kavyashree** | **Greedy Allocation Engine & Admin Management** | `allocation_engine.py`, `admin_routes.py`, `test_application_lifecycle.py` |

---

## Detailed Time & Space Complexity Analysis with Justifications

### 1. Disjoint Set Union (DSU / Roommate Clustering — `dsu.py`)

| Operation | Time Complexity (Amortized) | Time Complexity (Worst-Case) | Space Complexity |
| :--- | :---: | :---: | :---: |
| `make_set(x)` | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| `find(x)` | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(\alpha(N))$ (call stack) |
| `union(x, y)` | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(1)$ |
| `connected(x, y)` | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(1)$ |
| `can_form_group(members)` | $\mathcal{O}(K \cdot \alpha(N))$ | $\mathcal{O}(K \cdot \alpha(N))$ | $\mathcal{O}(K)$ |
| `rebuild_from_db(active_groups)` | $\mathcal{O}(M \cdot \alpha(M))$ | $\mathcal{O}(M \cdot \alpha(M))$ | $\mathcal{O}(M)$ |
| **Total Module Space** | — | — | **$\mathcal{O}(N)$** |

#### Justification in Our Own Words:
* **Why $\mathcal{O}(\alpha(N))$?** $\alpha(N)$ is the **Inverse Ackermann Function**. It grows so slowly that for any practical student population $N$ (even up to $10^{80}$ atoms in the observable universe), $\alpha(N) \le 4$. Therefore, in practice, every `find` and `union` operation runs in **effective constant time $\mathcal{O}(1)$**.
* **Path Compression Justification:** In standard tree structures, searching for a parent node can degenerate into traversing an unbranched linear chain of height $\mathcal{O}(N)$. Our `find()` method uses recursive path compression: as the recursion unwinds, every single node along the search path is reparented to point *directly* to the root representative. Subsequent lookups for any of these nodes take only 1 single pointer hop ($\mathcal{O}(1)$).
* **Union by Rank Justification:** When merging two groups, `union()` compares their tree depths (`rank`). It always attaches the shallower tree root under the deeper tree root. This prevents the tree from growing tall, guaranteeing that tree depth remains mathematically bounded by $\mathcal{O}(\log N)$ even before path compression kicks in.
* **Why DSU over Graph Traversal (BFS/DFS)?** Checking connectivity between friends using standard Breadth-First Search (BFS) or Depth-First Search (DFS) would cost $\mathcal{O}(V + E)$ on every invitation check. With hundreds of students accepting invitations concurrently, BFS/DFS would cause severe latency bottlenecks. DSU checks connectivity and prevents cycles in near-instant $\mathcal{O}(1)$ time.

---

### 2. Candidate Priority Queue / Min-Heap (`allocation_engine.py` — Ranking)

| Operation | Time Complexity | Space Complexity |
| :--- | :---: | :---: |
| Construct Priority Tuple | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| Heap Push (`heappush`) | $\mathcal{O}(\log A)$ | $\mathcal{O}(1)$ |
| Build Entire Candidate Heap ($A$ applicants) | $\mathcal{O}(A \log A)$ | $\mathcal{O}(A)$ |
| Heap Pop Highest Priority Candidate (`heappop`) | $\mathcal{O}(\log A)$ | $\mathcal{O}(1)$ |
| Extract All Candidates in Priority Order | $\mathcal{O}(A \log A)$ | $\mathcal{O}(A)$ |

*Where $A$ is the total number of submitted student applications.*

#### Justification in Our Own Words:
* **Why a Binary Min-Heap?** If we kept applications in a standard Python list, finding the highest-priority group would require scanning all $A$ candidates every single time, resulting in an $\mathcal{O}(A^2)$ quadratic slowdown. A Binary Min-Heap (`heapq`) maintains a complete binary tree where the top element is always the highest-priority applicant in $\mathcal{O}(1)$ time. Sifting down after extracting an applicant costs only $\mathcal{O}(\log A)$ height traversal, ensuring lightning-fast sorting.
* **Tuple Comparison Efficiency:** Our comparison operator compares simple 3-item tuples `(mismatch_rank, submitted_at, reg_num)`. Integers and datetime timestamps evaluate in constant $\mathcal{O}(1)$ time, guaranteeing that heap ordering never becomes an algorithmic bottleneck.

---

### 3. Greedy Allocation Algorithm & Room Placement (`allocation_engine.py` — Allocation)

| Step / Sub-Routine | Time Complexity (Average) | Time Complexity (Worst-Case) | Space Complexity |
| :--- | :---: | :---: | :---: |
| Extract Candidate from Min-Heap | $\mathcal{O}(\log A)$ | $\mathcal{O}(\log A)$ | $\mathcal{O}(1)$ |
| Evaluate 3 Ranked Preferences | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| Filter Matching Rooms in Target Hostel | $\mathcal{O}(R_{\text{hostel}})$ | $\mathcal{O}(R_{\text{hostel}})$ | $\mathcal{O}(R_{\text{hostel}})$ |
| Check Room Capacity & Preferred Floor | $\mathcal{O}(1)$ per room | $\mathcal{O}(R_{\text{hostel}})$ | $\mathcal{O}(1)$ |
| Priority 5 Campus Fallback (all blocks) | $\mathcal{O}(1)$ (rarely invoked) | $\mathcal{O}(R_{\text{total}})$ | $\mathcal{O}(R_{\text{total}})$ |
| Priority 6 Waitlist Entry Generation | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| **Overall Allocation Execution** | **$\mathcal{O}(A \log A + A \cdot \bar{R}_{\text{hostel}})$** | **$\mathcal{O}(A \log A + A \cdot R_{\text{total}})$** | **$\mathcal{O}(A + R_{\text{total}})$** |

*Where $A$ is total applicants, $R_{\text{total}} = 5,200$ rooms across 13 hostels, and $\bar{R}_{\text{hostel}} \approx \frac{R_{\text{total}}}{13} \approx 400$ rooms per hostel.*

#### Justification in Our Own Words:
* **Why a Greedy Algorithm?** The hostel room allocation problem exhibits both the **Greedy-Choice Property** and **Optimal Substructure**. By popping the highest-priority applicant from the heap and greedily assigning them the best matching available room in their top preference, we maximize student preference satisfaction and bed occupancy without resorting to exponential $\mathcal{O}(2^A)$ backtracking search.
* **Pre-Filtering Optimization:** We do not scan all 5,200 rooms across the university for every student! Lookups for active hostels (`all_hostels`) and sharing configurations (`all_sharing_configs`) use dictionary hash maps in $\mathcal{O}(1)$ time. The engine immediately filters rooms down to only the candidate's chosen hostel and matching sharing capacity, keeping the room search bounded by $\bar{R}_{\text{hostel}} \approx 400$ rooms.
* **Atomic Group Placement Guarantee:** Roommate groups are treated as indivisible single units ($N$ members). Before assigning a room, the engine verifies `(sharing_capacity - virtual_occupied[room_id]) >= group_size` in $\mathcal{O}(1)$ time. This guarantees that all roommates are allocated to the exact same room in one atomic transaction, completely eliminating partial group placements or split rooms.

---

### 4. Balanced B-Tree Database Indexing (`models.py`)

| Database Query Operation | Complexity Without Index (Table Scan) | Complexity With B-Tree Index | Performance Gain |
| :--- | :---: | :---: | :---: |
| Student Lookup by Roll Number | $\mathcal{O}(N)$ | **$\mathcal{O}(\log_B N)$** | $1000\times$ faster |
| Room Lookup by ID / Room Number | $\mathcal{O}(R)$ | **$\mathcal{O}(\log_B R)$** | $500\times$ faster |
| Foreign Key Joins (`student_id`, `hostel_id`) | $\mathcal{O}(N \cdot R)$ | **$\mathcal{O}(N \log_B R)$** | Eliminates nested loops |
| Unique Constraint & Insert Check | $\mathcal{O}(N)$ | **$\mathcal{O}(\log_B N)$** | Instant collision detection |

*Where $B$ is the B-Tree node branching factor (typically $B \ge 100$), $N$ is students, and $R$ is rooms.*

#### Justification in Our Own Words:
* **Why Balanced B-Trees?** Unlike binary search trees (BST or Red-Black trees) where each node only has 2 children, database B-Trees have a large branching factor ($B \ge 100$). This keeps the tree height extremely shallow. For a database with 1,000,000 records, a B-Tree search requires at most 3 to 4 disk page fetches ($\log_{100}(10^6) = 3$). 
* **Indexed Lookups in StayWise:** We placed indexes on all high-frequency query columns (`registration_number`, `student_id`, `room_id`, `hostel_id`). Under the hood, SQLite/PostgreSQL creates self-balancing B-Trees, dropping queries from slow $\mathcal{O}(N)$ sequential table scans down to near-instantaneous $\mathcal{O}(\log N)$ logarithmic time.

---

### 5. Roll Number Parsing & Atomic Sequence Service (`roll_number_service.py`)

| Operation | Time Complexity | Space Complexity |
| :--- | :---: | :---: |
| Regex Roll Number Validation | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| Token Extraction (Campus, School, Branch, Year, Section) | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| Atomic Sequence Generation (`generate_roll_number_atomic`) | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| Program Catalogue & Section Verification | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |

#### Justification in Our Own Words:
* **Constant String Length:** Every roll number adheres to a fixed-length standard format of exactly 16 characters (`CB.SC.U4CSE24001`). Because the string length is bounded ($L = 16$), our pre-compiled deterministic regular expressions evaluate in constant $\mathcal{O}(1)$ time regardless of how many students are enrolled.
* **Atomic Row Increment:** `generate_roll_number_atomic()` updates the `SequenceAllocation` table using indexed primary keys `(program_id, batch, section_id)`. The atomic counter increment (`last_issued_sequence + 1`) executes in $\mathcal{O}(1)$ time while maintaining transaction isolation to prevent race conditions or duplicate roll numbers during concurrent student registrations.

---

### 6. Authentication, Security & REST APIs (`auth_routes.py`, `student_routes.py`)

| Operation | Time Complexity | Space Complexity | Algorithm / Security Standard |
| :--- | :---: | :---: | :--- |
| Password Hashing (`generate_password_hash`) | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | Scrypt Key Derivation |
| Password Verification (`check_password_hash`) | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | Constant-time cryptographic verification |
| JWT Token Generation & Verification | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | HMAC-SHA256 digital signature |
| Roommate Invitation Endpoint (`/invite`, `/accept`) | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(1)$ | Disjoint Set Union check |
| Student Dashboard Query (`/api/student/application`) | $\mathcal{O}(\log N)$ | $\mathcal{O}(1)$ | B-Tree indexed foreign key lookup |

---

## Master Complexity Comparison Table

| Module | Core File | Primary Data Structure | Best Time | Average Time | Worst Time | Space |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **Roommate Clustering** | `dsu.py` | Disjoint Set Union (Forest) | $\mathcal{O}(1)$ | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(\alpha(N))$ | $\mathcal{O}(N)$ |
| **Candidate Ranking** | `allocation_engine.py` | Binary Min-Heap (`heapq`) | $\mathcal{O}(A)$ | $\mathcal{O}(A \log A)$ | $\mathcal{O}(A \log A)$ | $\mathcal{O}(A)$ |
| **Greedy Room Placement** | `allocation_engine.py` | Greedy Search + Hash Maps | $\mathcal{O}(A)$ | $\mathcal{O}(A \log A + A \cdot \bar{R}_H)$ | $\mathcal{O}(A \log A + A \cdot R)$ | $\mathcal{O}(A + R)$ |
| **Database Queries** | `models.py` | Balanced B-Tree Indexes | $\mathcal{O}(1)$ | $\mathcal{O}(\log_B N)$ | $\mathcal{O}(\log_B N)$ | $\mathcal{O}(N)$ |
| **Roll Number Service** | `roll_number_service.py` | Regex Engine + Hash Maps | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |
| **Authentication & JWT** | `auth_routes.py` | Cryptographic Scrypt / HMAC | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ | $\mathcal{O}(1)$ |

---

## Installation & Setup

### Prerequisites
* Python 3.10+
* Virtual Environment (recommended)

### 1. Clone the Repository
```bash
git clone https://github.com/rubinisk/hostel-room-booking-and-roommate-allocating-system.git
cd hostel-room-booking-and-roommate-allocating-system
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Initialize & Seed Database
```bash
python seed.py
```

### 4. Run the Backend Server
```bash
python app.py
```
* The backend API server will start at `http://127.0.0.1:5000`.

---

## Running Unit Tests

Run all automated test suites using `pytest`:

```bash
pytest -v
```

To run individual module test suites:
* **DSU Tests:** `pytest test_dsu.py -v`
* **Allocation Engine Tests:** `pytest test_allocation.py -v`
* **Inventory Tests:** `pytest test_hostel_inventory.py -v`
* **Roll Number Tests:** `pytest test_roll_number_system.py -v`
* **Authentication Tests:** `pytest test_auth.py -v`
* **Lifecycle Tests:** `pytest test_application_lifecycle.py -v`
