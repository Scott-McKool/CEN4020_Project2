from flask import Flask, render_template, request, jsonify, session, redirect
from functools import wraps
import database as db

app = Flask(__name__)

# secret key for signing tokens
app.secret_key = 'bePzh7bh8k7kUDo4ED9v0hxVBGRFYgAj13BrqxbJMMkZUyOJYOlDNNydvVy'

# set session tokents to http
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


# decorator to look for session token
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

# the search page
@app.route('/search', methods=['GET'])
def search():

    return render_template("search.html")

# the edit page
@app.route('/edit', methods=['GET'])
def edit():

    return render_template("edit.html")

# the login page
@app.route('/login', methods=['GET'])
def login_get():
        
    return render_template('login.html')

# default route
@app.route('/')
def index():
    # redirect to search
    return redirect('/search')


#################
### data API ####
#################

# get session cookie by logging in
@app.route('/login', methods=['POST'])
def login_post():

    username = request.form.get('username')
    password = request.form.get('password')
    
    # test login credentials
    if username == 'debug' and password == 'password':

        # set session cookie and redirect to edit page
        session['logged_in'] = True 
        return redirect('/edit')
    
    else:
        return render_template('login.html', error="Invalid credentials")
    
# get class data from the catalog
@app.route('/api/data', methods=['GET'])
def get_data():

    # look for url parameter
    search_value = request.args.get('q', '')
    search_column = request.args.get('column', '')

    # if present, perform the search
    if search_value:

        data = db.search_db(search_column, search_value)
        return jsonify(data)
    else:

        # if not, return the whole catalog
        return jsonify(db.full_catalog())

# search courses by any combination of filter parameters
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


# add a new class to the catalog
@app.route('/api/data/row/', methods=['POST'])
@login_required
def add_row():

    # attempt to add the row to the database
    data = request.json
    result = db.add_class(data)

    return result


@app.route('/api/data/row/<int:row_id>', methods=['PUT'])
@login_required
def edit_row(row_id):

    
    # attempt to add the row to the database
    data = request.json
    result = db.update_class(row_id, data)

    return result

if __name__ == '__main__':
    app.run(debug=True)