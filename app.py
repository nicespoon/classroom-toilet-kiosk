from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime
from models import db, Student, Settings, History

app = Flask(__name__)
app.config['SECRET_KEY'] = 'classroom_kiosk_secret_key'  # Change this in production!
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///classroom_kiosk.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialise the database
db.init_app(app)

def init_db():
    """Initialise the database with required tables and default data"""
    with app.app_context():
        # Create all tables
        db.create_all()

        # Create default settings if not exists
        if not Settings.query.first():
            default_settings = Settings(id=1, max_students=2)
            db.session.add(default_settings)
            db.session.commit()

def get_max_students():
    """Get the maximum number of students allowed out"""
    settings = Settings.query.first()
    return settings.max_students if settings else 2

def get_students_out_count():
    """Get count of students currently out"""
    return Student.query.filter_by(is_out=True).count()

@app.route('/')
def index():
    """Main student-facing page"""
    students = Student.query.order_by(Student.name).all()
    max_students = get_max_students()
    students_out_count = get_students_out_count()

    return render_template('index.html',
                         students=students,
                         max_students=max_students,
                         students_out_count=students_out_count,
                         is_full=(students_out_count >= max_students))

@app.route('/sign_out/<int:student_id>')
def sign_out(student_id):
    """Sign out a student"""
    max_students = get_max_students()
    students_out_count = get_students_out_count()

    if students_out_count >= max_students:
        return redirect(url_for('index'))

    student = Student.query.get_or_404(student_id)
    now = datetime.now()

    # Update student status
    student.is_out = True
    student.time_out = now

    # Add to history
    history_record = History(
        student_name=student.name,
        sign_out_time=now
    )

    db.session.add(history_record)
    db.session.commit()

    return redirect(url_for('index'))

@app.route('/sign_in/<int:student_id>')
def sign_in(student_id):
    """Sign in a student"""
    student = Student.query.get_or_404(student_id)

    if student.is_out and student.time_out:
        now = datetime.now()

        # Calculate duration
        duration = now - student.time_out
        duration_minutes = int(duration.total_seconds() / 60)

        # Update history record
        history_record = History.query.filter_by(
            student_name=student.name,
            sign_in_time=None
        ).order_by(History.sign_out_time.desc()).first()

        if history_record:
            history_record.sign_in_time = now
            history_record.duration_minutes = duration_minutes

        # Update student status
        student.is_out = False
        student.time_out = None

        db.session.commit()

    return redirect(url_for('index'))

@app.route('/admin')
def admin():
    """Admin page"""
    students = Student.query.order_by(Student.name).all()
    max_students = get_max_students()

    return render_template('admin.html', 
                         students=students, 
                         max_students=max_students)

@app.route('/admin/add_student', methods=['POST'])
def add_student():
    """Add a new student"""
    name = request.form['name'].strip()

    if name:
        # Check if student already exists
        existing_student = Student.query.filter_by(name=name).first()
        if not existing_student:
            student = Student(name=name)
            db.session.add(student)
            db.session.commit()

    return redirect(url_for('admin'))

@app.route('/admin/remove_student/<int:student_id>')
def remove_student(student_id):
    """Remove a student"""
    student = Student.query.get_or_404(student_id)
    db.session.delete(student)
    db.session.commit()

    return redirect(url_for('admin'))

@app.route('/admin/set_max_students', methods=['POST'])
def set_max_students():
    """Set maximum number of students"""
    max_students = int(request.form['max_students'])

    if max_students > 0:
        settings = Settings.query.first()
        if not settings:
            settings = Settings(id=1, max_students=max_students)
            db.session.add(settings)
        else:
            settings.max_students = max_students

        db.session.commit()

    return redirect(url_for('admin'))

@app.route('/admin/history')
def history():
    """View history page"""
    search = request.args.get('search', '')

    if search:
        history_records = History.query.filter(
            History.student_name.like(f'%{search}%')
        ).order_by(History.sign_out_time.desc()).all()
    else:
        history_records = History.query.order_by(
            History.sign_out_time.desc()
        ).all()

    # Format records for display
    formatted_records = []
    for record in history_records:
        record_dict = {
            'id': record.id,
            'student_name': record.student_name,
            'sign_out_time': record.sign_out_time,
            'sign_in_time': record.sign_in_time,
            'duration_minutes': record.duration_minutes,
            'sign_out_formatted': record.sign_out_time.strftime('%Y-%m-%d %H:%M'),
            'sign_in_formatted': record.sign_in_time.strftime('%Y-%m-%d %H:%M') if record.sign_in_time else 'Still out'
        }
        formatted_records.append(record_dict)

    return render_template('history.html', 
                         records=formatted_records, 
                         search=search)

if __name__ == '__main__':
    # Initialise database
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)