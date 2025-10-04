from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Student(db.Model):
    __tablename__ = 'students'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    is_out = db.Column(db.Boolean, default=False)
    time_out = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to history records
    history_records = db.relationship('History', 
                                    foreign_keys='History.student_name',
                                    primaryjoin='Student.name == History.student_name',
                                    backref='student_ref', 
                                    lazy=True)

    def __repr__(self):
        return f'<Student {self.name}>'

class Settings(db.Model):
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    max_students = db.Column(db.Integer, default=2)

    def __repr__(self):
        return f'<Settings max_students={self.max_students}>'

class History(db.Model):
    __tablename__ = 'history'

    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    sign_out_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sign_in_time = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<History {self.student_name} - {self.sign_out_time}>'