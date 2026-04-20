import re
import sqlite3
import json
import datetime

###################################
### For accounts and logging in ###
###################################

def migrate_users_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT DEFAULT ''
        )
    ''')
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def get_user_info(username: str) -> dict:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, email FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'username': row[0], 'email': row[1] or ''}
    return None


def try_login(username, password) -> bool:

    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT DEFAULT ''
        )
    ''')

    cursor.execute('SELECT password FROM users WHERE username = ?', (username,))
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return False
    
    passwd = row[0]

    if passwd == password:
        return True
    return False

#################################
### Course catalog data        ###
#################################

# [CRN, Name, Subject, CourseNum, Level (UG/GR), Instructor, Time, Room, Enrolled, Semester]
# Loaded from: Bellini Classes F25.xlsx, S25.xlsx, S26_NewClassesToBeAdded.xlsx
COURSES = [
]


# --- private helpers ---------------------------------------------------------

def _parse_start_minutes(time_str):
    '''Return start time in minutes since midnight from a string like "MWF 09:00 AM - 09:50 AM", or None.'''
    m = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.IGNORECASE)
    if not m:
        return None
    h, mins, meridiem = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if meridiem == 'PM' and h != 12:
        h += 12
    elif meridiem == 'AM' and h == 12:
        h = 0
    return h * 60 + mins


def _parse_days(time_str):
    '''Return the day-letter string (e.g. "MWF") from a time string, or empty string.'''
    tokens = time_str.strip().split()
    if tokens and all(c in 'MTWRF' for c in tokens[0].upper()):
        return tokens[0].upper()
    return ''


def _parse_end_minutes(time_str):
    matches = re.findall(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.IGNORECASE)
    if len(matches) < 2:
        return None
    h, mins, meridiem = int(matches[1][0]), int(matches[1][1]), matches[1][2].upper()
    if meridiem == 'PM' and h != 12:
        h += 12
    elif meridiem == 'AM' and h == 12:
        h = 0
    return h * 60 + mins


def _times_overlap(time_a, time_b):
    days_a = _parse_days(time_a)
    days_b = _parse_days(time_b)
    if not days_a or not days_b:
        return False
    if not any(d in days_b for d in days_a):
        return False
    s_a = _parse_start_minutes(time_a)
    e_a = _parse_end_minutes(time_a)
    s_b = _parse_start_minutes(time_b)
    e_b = _parse_end_minutes(time_b)
    if None in (s_a, e_a, s_b, e_b):
        return False
    return s_a < e_b and s_b < e_a


# TA assignments keyed by CRN
TA_MAP = {}


def check_conflicts(crn: int, instructor: str, room: str,
                    time: str, semester: str) -> list:
    TBA = {'TBA', 'TBAT TBA', 'OFFT OFF', ''}
    warnings = []
    for row in COURSES:
        c_crn, _, _, _, _, c_instr, c_time, c_room, _, c_sem = row
        if c_crn == crn or c_sem != semester:
            continue
        if not _times_overlap(time, c_time):
            continue
        if room and room.upper() not in TBA and c_room.upper() not in TBA and c_room == room:
            warnings.append(f"Room conflict: {room} is already used by CRN {c_crn} at overlapping time.")
        if instructor and c_instr.lower() == instructor.lower():
            warnings.append(f"Instructor conflict: {instructor} already teaches CRN {c_crn} at overlapping time.")
    return warnings


def _match_course_code(code_query, subj, course_num):
    '''Match a query like "CDA" or "CDA 4205" against a course's subject code and number.
    The subject part uses substring matching; the number part uses substring matching too.'''
    if not code_query:
        return True
    parts = code_query.strip().upper().split(None, 1)
    subj_q = parts[0]
    num_q  = parts[1].strip() if len(parts) > 1 else ''
    if subj_q not in subj.upper():
        return False
    if num_q and num_q not in str(course_num):
        return False
    return True


#################################
### Functions used by the API ###
#################################

def search_courses(professor='', subject='', level='', course_code='',
                   semester='', days='', crn='') -> list:
    '''Search the course catalog. All parameters are optional; empty string means match all.

    days -- string of day letters (e.g. "MWF"); a course matches if it meets on ANY listed day.
    crn  -- exact CRN number to look up.
    Returns a list of dicts.'''
    results = []
    for row in COURSES:
        c_crn, name, subj, course_num, lvl, instr, time, room, enrolled, sem = row

        # exact CRN lookup
        if crn and str(c_crn) != crn.strip():
            continue

        # partial instructor match
        if professor and professor.lower() not in instr.lower():
            continue

        # subject filter — supports plain code ("CIS") or code+number ("CIS 4930")
        if subject and not _match_course_code(subject, subj, course_num):
            continue

        # exact level match
        if level and level.upper() != lvl:
            continue

        # course code match (e.g. "CDA" or "CDA 4205")
        if not _match_course_code(course_code, subj, course_num):
            continue

        # exact semester match
        if semester and semester != sem:
            continue

        # days filter — course must meet on at least one of the requested days
        if days:
            course_days = _parse_days(time)
            if not any(d in course_days for d in days.upper()):
                continue

        results.append({
            'crn':        c_crn,
            'name':       name,
            'subject':    subj,
            'course_num': course_num,
            'level':      lvl,
            'instructor': instr,
            'time':       time,
            'room':       room,
            'enrolled':   enrolled,
            'semester':   sem,
            'ta':         TA_MAP.get(c_crn, ''),
        })
    return results


def full_catalog() -> list:
    '''Returns the entire course catalog as a list of dicts'''
    return search_courses()


def import_excel(filepath: str, semester: str) -> int:
    '''Import courses from a Bellini Classes Excel file into COURSES.
    Detects column layout automatically (F25 vs S25 vs S26 format).
    Returns the number of rows imported.'''
    from openpyxl import load_workbook
    wb = load_workbook(filepath, read_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0

    headers = [str(h).strip() if h else '' for h in rows[0]]

    def col(name):
        for h in headers:
            if name.lower() in h.lower().replace(' ', '_').replace(' ', ''):
                return headers.index(h)
        return None

    # find key columns by partial name match
    def find(keywords):
        for kw in keywords:
            for i, h in enumerate(headers):
                if kw.lower() in h.lower().replace(' ', ''):
                    return i
        return None

    idx_crn   = find(['crn'])
    idx_subj  = find(['subj'])
    idx_num   = find(['crse_numb', 'crsenumb', 'crse numb'])
    idx_title = find(['crse_title', 'crsetitle', 'crse title'])
    idx_levl  = find(['crse_levl', 'crselevl', 'crse levl'])
    idx_days  = find(['meeting_days', 'meetingdays', 'meeting days'])
    idx_times = find(['meeting_times1', 'meeting_times', 'meetingtimes'])
    idx_room  = find(['meeting_room', 'meetingroom'])
    idx_instr = find(['instructor'])
    idx_enrl  = find(['enrollment'])

    imported = 0
    for row in rows[1:]:
        try:
            crn   = int(row[idx_crn]) if idx_crn is not None and row[idx_crn] else None
            if not crn:
                continue
            subj  = str(row[idx_subj] or '').strip()
            num   = str(row[idx_num]  or '').strip()
            title = str(row[idx_title] or '').strip()
            levl  = str(row[idx_levl]  or '').strip()
            days  = str(row[idx_days]  or '').strip()
            times = str(row[idx_times] or '').strip()
            time  = f'{days} {times}'.strip() if days and days != 'None' else times
            room  = str(row[idx_room]  or '').strip()
            instr = str(row[idx_instr] or '').strip()
            enrl  = int(row[idx_enrl]) if idx_enrl is not None and row[idx_enrl] and str(row[idx_enrl]).isdigit() else 0

            # skip if CRN already loaded
            if any(c[0] == crn for c in COURSES):
                continue

            COURSES.append([crn, title, subj, num, levl, instr, time, room, enrl, semester])
            imported += 1
        except Exception:
            continue
    return imported


def add_class(class_data: dict) -> tuple[dict, int]:
    '''Add a new class to the in-memory catalog.
    Returns a ({"message": ..., "warnings": [...]}, status_code) tuple.'''

    try:
        crn = int(class_data.get('crn', 0))
    except (ValueError, TypeError):
        return ({"message": "Invalid CRN — must be a number.", "warnings": []}, 400)

    if not crn:
        return ({"message": "CRN is required.", "warnings": []}, 400)

    if any(c[0] == crn for c in COURSES):
        return ({"message": f"A course with CRN {crn} already exists.", "warnings": []}, 409)

    instr    = str(class_data.get('instructor', '')).strip()
    room     = str(class_data.get('room',        '')).strip()
    time     = str(class_data.get('time',        '')).strip()
    semester = str(class_data.get('semester',    '')).strip()
    warnings = check_conflicts(crn, instr, room, time, semester)

    COURSES.append([
        crn,
        str(class_data.get('name',       '')).strip(),
        str(class_data.get('subject',    '')).strip(),
        str(class_data.get('course_num', '')).strip(),
        str(class_data.get('level',      'UG')).strip(),
        instr, time, room,
        int(class_data.get('enrolled', 0)),
        semester,
    ])
    ta = str(class_data.get('ta', '')).strip()
    if ta:
        TA_MAP[crn] = ta
    return ({"message": f"Course {crn} added successfully.", "warnings": warnings}, 201)


def update_class(class_id: int, class_data: dict) -> tuple[dict, int]:
    '''Update the course whose CRN matches class_id.
    Returns a ({"message": ..., "warnings": [...]}, status_code) tuple.'''

    for i, row in enumerate(COURSES):
        if row[0] == class_id:
            crn, name, subj, num, lvl, instr, time, room, enrolled, sem = row
            new_instr    = str(class_data.get('instructor', instr)).strip()
            new_room     = str(class_data.get('room',       room)).strip()
            new_time     = str(class_data.get('time',       time)).strip()
            new_semester = str(class_data.get('semester',   sem)).strip()
            warnings = check_conflicts(class_id, new_instr, new_room, new_time, new_semester)
            COURSES[i] = [
                crn,
                str(class_data.get('name',       name)).strip(),
                str(class_data.get('subject',    subj)).strip(),
                str(class_data.get('course_num', num)).strip(),
                str(class_data.get('level',      lvl)).strip(),
                new_instr, new_time, new_room,
                int(class_data.get('enrolled', enrolled)),
                new_semester,
            ]
            ta = str(class_data.get('ta', TA_MAP.get(class_id, ''))).strip()
            TA_MAP[class_id] = ta
            return ({"message": f"Course {class_id} updated successfully.", "warnings": warnings}, 200)

    return ({"message": f"No course found with CRN {class_id}.", "warnings": []}, 404)


def delete_class(crn: int) -> tuple[dict, int]:
    global COURSES
    before = len(COURSES)
    COURSES = [c for c in COURSES if c[0] != crn]
    if len(COURSES) == before:
        return ({"message": f"No course found with CRN {crn}.", "warnings": []}, 404)
    TA_MAP.pop(crn, None)
    return ({"message": f"Course {crn} deleted.", "warnings": []}, 200)


def generate_audit_report() -> dict:
    TBA_VALS = {'TBA', 'TBAT TBA', 'OFFT OFF', ''}
    report = {
        'duplicate_crns':        [],
        'room_conflicts':        [],
        'instructor_conflicts':  [],
        'unreasonable_times':    [],
        'missing_data':          [],
    }

    # Duplicate CRNs
    seen = {}
    for row in COURSES:
        crn = row[0]
        if crn in seen:
            report['duplicate_crns'].append({'crn': crn, 'name': row[1], 'semester': row[9]})
        seen[crn] = True

    # Per-course checks + pairwise conflict detection
    for i, row_a in enumerate(COURSES):
        crn_a, name_a, subj_a, num_a, lvl_a, instr_a, time_a, room_a, enrl_a, sem_a = row_a

        # Missing data
        issues = []
        if not instr_a or not instr_a.strip():
            issues.append('Missing instructor')
        if not time_a or time_a.strip().upper() in TBA_VALS:
            issues.append('Time is TBA/not set')
        if not room_a or room_a.strip().upper() in TBA_VALS:
            issues.append('Room is TBA/not set')
        if issues:
            report['missing_data'].append({
                'crn': crn_a, 'name': name_a, 'semester': sem_a, 'issues': issues
            })

        # Unreasonable times
        if time_a and time_a.strip().upper() not in TBA_VALS:
            start = _parse_start_minutes(time_a)
            end   = _parse_end_minutes(time_a)
            if start is not None and start < 7 * 60:
                report['unreasonable_times'].append({
                    'crn': crn_a, 'name': name_a, 'time': time_a,
                    'semester': sem_a, 'reason': 'Starts before 7:00 AM'
                })
            elif end is not None and end > 22 * 60:
                report['unreasonable_times'].append({
                    'crn': crn_a, 'name': name_a, 'time': time_a,
                    'semester': sem_a, 'reason': 'Ends after 10:00 PM'
                })

        # Pairwise conflicts (only compare later rows to avoid duplicates)
        for row_b in COURSES[i+1:]:
            crn_b, name_b, _, _, _, instr_b, time_b, room_b, _, sem_b = row_b
            if sem_a != sem_b or not _times_overlap(time_a, time_b):
                continue
            if (room_a.upper() not in TBA_VALS and room_b.upper() not in TBA_VALS
                    and room_a == room_b):
                report['room_conflicts'].append({
                    'semester': sem_a, 'room': room_a,
                    'crn1': crn_a, 'name1': name_a, 'time1': time_a,
                    'crn2': crn_b, 'name2': name_b, 'time2': time_b,
                })
            if (instr_a and instr_b
                    and instr_a.strip() and instr_b.strip()
                    and instr_a.lower() == instr_b.lower()):
                report['instructor_conflicts'].append({
                    'semester': sem_a, 'instructor': instr_a,
                    'crn1': crn_a, 'name1': name_a, 'time1': time_a,
                    'crn2': crn_b, 'name2': name_b, 'time2': time_b,
                })

    report['summary'] = {
        'total_courses':        len(COURSES),
        'duplicate_crns':       len(report['duplicate_crns']),
        'room_conflicts':       len(report['room_conflicts']),
        'instructor_conflicts': len(report['instructor_conflicts']),
        'unreasonable_times':   len(report['unreasonable_times']),
        'missing_data':         len(report['missing_data']),
    }
    return report


def init_history_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS change_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action    TEXT NOT NULL,
            crn       INTEGER NOT NULL,
            old_vals  TEXT,
            new_vals  TEXT NOT NULL,
            username  TEXT NOT NULL,
            email     TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()


def log_change(action: str, crn: int, old_values, new_values, username: str, email: str):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO change_history (timestamp,action,crn,old_vals,new_vals,username,email) VALUES (?,?,?,?,?,?,?)',
        (datetime.datetime.utcnow().isoformat(), action, crn,
         json.dumps(old_values) if old_values else None,
         json.dumps(new_values), username, email)
    )
    conn.commit()
    conn.close()


def get_history(limit: int = 100) -> list:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute(
        'SELECT id,timestamp,action,crn,old_vals,new_vals,username,email FROM change_history ORDER BY id DESC LIMIT ?',
        (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{'id': r[0], 'timestamp': r[1], 'action': r[2], 'crn': r[3],
             'old_values': json.loads(r[4]) if r[4] else None,
             'new_values': json.loads(r[5]) if r[5] else {},
             'username': r[6], 'email': r[7]} for r in rows]


def undo_change(history_id: int) -> tuple[dict, int]:
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('SELECT action,crn,old_vals FROM change_history WHERE id=?', (history_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return ({"message": "History entry not found.", "warnings": []}, 404)
    action, crn, old_json = row
    if action == 'add':
        global COURSES
        before = len(COURSES)
        COURSES = [c for c in COURSES if c[0] != crn]
        if len(COURSES) == before:
            return ({"message": f"Course {crn} not found.", "warnings": []}, 404)
        return ({"message": f"Undone: removed course {crn}.", "warnings": []}, 200)
    elif action == 'edit':
        old = json.loads(old_json) if old_json else None
        if not old:
            return ({"message": "Cannot undo: no previous values stored.", "warnings": []}, 400)
        return update_class(crn, old)
    return ({"message": "Unknown action.", "warnings": []}, 400)


def get_instructor_conflicts(courses: list) -> list:
    conflict_crns = set()
    for i, a in enumerate(courses):
        for b in courses[i+1:]:
            if a['semester'] == b['semester'] and _times_overlap(a['time'], b['time']):
                conflict_crns.add(a['crn'])
                conflict_crns.add(b['crn'])
    return list(conflict_crns)
