# 🏨 Smart Priority-Based Hostel Room Allocation & Roommate Matching System

A production-ready, algorithm-driven hostel room allocation and roommate grouping platform engineered with advanced Data Structures and Algorithms (DSA) to ensure transparency, fairness, and automated conflict-free placement.

---

## 🎯 System Architecture & DSA Modules

The backend architecture is modularly divided across 4 core Data Structures and Algorithm paradigms:

```
[Student Registration & Schema] ──> [Roommate Clustering (DSU)] ──> [Candidate Ranking (Min-Heap)] ──> [Greedy Allocation Engine]
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

## 👥 Team Contributions

| Member | Module & DSA Topic | Core Files Contributed |
| :--- | :--- | :--- |
| **Midhuna** | **B-Tree Database Schema & Roll Number System** | `models.py`, `roll_number_service.py`, `auth_routes.py`, `test_hostel_inventory.py`, `test_roll_number_system.py` |
| **Rubini** | **Disjoint Set Union (DSU) & Roommate Clustering** | `dsu.py`, `student_routes.py`, `test_dsu.py`, `test_workflow.py` |
| **Kanishka** | **Priority Queue / Min-Heap & Scheduling Engine** | `app.py`, `config.py`, `scheduler.py`, `payment_routes.py`, `test_allocation.py` |
| **Kavyashree** | **Greedy Allocation Engine & Admin Management** | `allocation_engine.py`, `admin_routes.py`, `test_application_lifecycle.py` |

---

## 🛠️ Installation & Setup

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

## 🧪 Running Unit Tests

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
