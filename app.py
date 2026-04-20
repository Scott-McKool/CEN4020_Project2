import os
import tempfile
from flask import Flask, render_template, request, jsonify, session, redirect
from functools import wraps
import database as db

app = Flask(__name__)

app.secret_key = 'bePzh7bh8k7kUDo4ED9v0hxVBGRFYgAj13BrqxbJMMkZUyOJYOlDNNydvVy'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


##################
### HTML PAGES ###
##################

@app.route('/')
def index():
    return redirect('/search')

@app.route('/search', methods=['GET'])
def search():
    return render_template("search.html")

@app.route('/edit', methods=['GET'])
def edit():
    return render_template("edit.html")

@app.route('/login', methods=['GET'])
def login_get():
    return render_template('login.html')

@app.route('/instructor', methods=['GET'])
def instructor():
    return render_template('instructor.html')

@app.route('/report', methods=['GET'])
def report():
    return render_template('report.html')


#################
### AUTH API  ###
#################

@app.route('/login', methods=['POST'])
def login_post():
    username = request.form.get('username')
    password = request.form.get('password')
    if db.try_login(username, password):
        session['logged_in'] = True
        session['username']  = username
        return redirect('/edit')
    return render_template('login.html', error="Invalid credentials")


#################
### DATA API  ###
#################

@app.route('/api/search', methods=['GET'])
def search_courses():
    professor   = request.args.get('professor',   '').strip()
    subject     = request.args.get('subject',     '').strip()
    level       = request.args.get('level',       '').strip()
    course_code = request.args.get('course_code', '').strip()
    semester    = request.args.get('semester',    '').strip()
    days        = request.args.get('days',        '').strip()
    crn         = request.args.get('crn',         '').strip()
    results = db.search_courses(
        professor=professor, subject=subject, level=level,
        course_code=course_code, semester=semester, days=days, crn=crn,
    )
    return jsonify(results)


@app.route('/api/data/row/', methods=['POST'])
@login_required
def add_row():
    data = request.json
    result_dict, status_code = db.add_class(data)
    if status_code == 201:
        username = session.get('username', 'unknown')
        user = db.get_user_info(username) or {}
        db.log_change('add', data.get('crn'), None, data,
                      username, user.get('email', ''))
    return jsonify(result_dict), status_code


@app.route('/api/data/row/<int:row_id>', methods=['DELETE'])
@login_required
def delete_row(row_id):
    old_course = next((c for c in db.COURSES if c[0] == row_id), None)
    old_values = None
    if old_course:
        old_values = {
            'name': old_course[1], 'subject': old_course[2],
            'course_num': old_course[3], 'level': old_course[4],
            'instructor': old_course[5], 'time': old_course[6],
            'room': old_course[7], 'enrolled': old_course[8],
            'semester': old_course[9],
        }
    result_dict, status_code = db.delete_class(row_id)
    if status_code == 200:
        username = session.get('username', 'unknown')
        user = db.get_user_info(username) or {}
        db.log_change('delete', row_id, old_values, {},
                      username, user.get('email', ''))
    return jsonify(result_dict), status_code


@app.route('/api/data/row/<int:row_id>', methods=['PUT'])
@login_required
def edit_row(row_id):
    data = request.json
    old_course = next((c for c in db.COURSES if c[0] == row_id), None)
    old_values = None
    if old_course:
        old_values = {
            'name': old_course[1], 'subject': old_course[2],
            'course_num': old_course[3], 'level': old_course[4],
            'instructor': old_course[5], 'time': old_course[6],
            'room': old_course[7], 'enrolled': old_course[8],
            'semester': old_course[9],
        }
    result_dict, status_code = db.update_class(row_id, data)
    if status_code == 200:
        username = session.get('username', 'unknown')
        user = db.get_user_info(username) or {}
        db.log_change('edit', row_id, old_values, data,
                      username, user.get('email', ''))
    return jsonify(result_dict), status_code


######################
### HISTORY API    ###
######################

@app.route('/api/history', methods=['GET'])
@login_required
def get_history():
    return jsonify(db.get_history())


@app.route('/api/history/<int:history_id>/undo', methods=['POST'])
@login_required
def undo_history(history_id):
    result_dict, status_code = db.undo_change(history_id)
    return jsonify(result_dict), status_code


######################
### IMPORT EXCEL   ###
######################

@app.route('/api/import-excel', methods=['POST'])
@login_required
def import_excel_route():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided."}), 400
    f = request.files['file']
    semester = request.form.get('semester', '').strip()
    if not semester:
        return jsonify({"error": "Semester is required."}), 400
    suffix = os.path.splitext(f.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name
    try:
        count = db.import_excel(tmp_path, semester)
    finally:
        os.unlink(tmp_path)
    return jsonify({"imported": count, "message": f"{count} course(s) imported for {semester}."})


####################
### REPORT API   ###
####################

@app.route('/api/report', methods=['GET'])
def audit_report():
    return jsonify(db.generate_audit_report())


######################
### INSTRUCTOR API ###
######################

@app.route('/api/instructor', methods=['GET'])
def instructor_data():
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({"courses": [], "conflicts": []})
    courses = db.search_courses(professor=name)
    conflict_crns = db.get_instructor_conflicts(courses)
    return jsonify({"courses": courses, "conflicts": conflict_crns})


# initialise DB tables and run
db.migrate_users_db()
db.init_history_db()

if __name__ == '__main__':
    app.run(debug=True)
