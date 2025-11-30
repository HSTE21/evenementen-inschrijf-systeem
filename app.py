import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from flask import Flask, request, render_template, url_for, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)

app = Flask(__name__)
app.secret_key = "CHANGE_THIS_TO_SOMETHING_RANDOM"  # needed for sessions / flash

# --- DATABASE CONFIG ---
# use a generic filename for the sqlite database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///registrations.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email settings (adjust!)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "your_email@gmail.com"       # <-- change
SMTP_PASSWORD = "your_app_password"      # <-- change

db = SQLAlchemy(app)

# --- LOGIN MANAGER ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"  # redirect here if not logged in

# --- MODELS ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)  # plain for now, later you can hash

class Training(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    datum_sleutel = db.Column(db.String(20), unique=True, nullable=False)
    naam_display = db.Column(db.String(100), nullable=False)
    limiet = db.Column(db.Integer, default=20)
    open_vanaf = db.Column(db.DateTime, nullable=False)
    registrations = db.relationship('Registration', backref='training', lazy=True)

class Registration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    naam = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    is_waitlist = db.Column(db.Boolean, default=False)
    training_id = db.Column(db.Integer, db.ForeignKey('training.id'), nullable=False)

# --- LOGIN LOADER ---

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- HELPERS ---

def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = to_email
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Email error: {e}")

# --- INIT DB ONCE ---

with app.app_context():
    db.create_all()

    # Create initial trainings if none (generic example entries)
    if not Training.query.first():
        t1 = Training(
            datum_sleutel="2025-11-24",
            naam_display="Training 1 - 24 Nov 20:00 to 21:30",
            limiet=20,
            open_vanaf=datetime(2025, 11, 17, 20, 0),
        )
        t2 = Training(
            datum_sleutel="2025-11-25",
            naam_display="Training 2 - 25 Nov 21:00 to 22:30",
            limiet=20,
            open_vanaf=datetime(2025, 11, 18, 21, 0),
        )
        db.session.add_all([t1, t2])
        db.session.commit()

    # Create admin user if not exists
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", password="password123")
        db.session.add(admin)
        db.session.commit()
        print("Created default admin user: admin / password123")

# --- PUBLIC ROUTES ---

@app.route('/')
def index():
    now = datetime.now()
    all_trainings = Training.query.order_by(Training.datum_sleutel).all()
    view_data = []

    for t in all_trainings:
        participants = [r for r in t.registrations if not r.is_waitlist]
        waitlist = [r for r in t.registrations if r.is_waitlist]
        names_list = [p.naam for p in participants]

        view_data.append({
            'id': t.id,
            'datum': t.naam_display,
            'open_tijd_display': t.open_vanaf.strftime('%d-%m %H:%M'),
            'is_open': now >= t.open_vanaf,
            'vol': len(participants) >= t.limiet,
            'totaal_plekken': t.limiet,
            'bezette_plekken': len(participants),
            'beschikbaar': t.limiet - len(participants),
            'wachtlijst_len': len(waitlist),
            'deelnemers_namen': names_list,
        })

    return render_template('index.html', trainingen=view_data)

@app.route('/aanmelden/<int:training_id>', methods=['POST'])
def aanmelden(training_id):
    t = Training.query.get_or_404(training_id)
    naam = request.form['naam']
    email = request.form['email']

    existing = Registration.query.filter_by(training_id=t.id, email=email).first()
    if existing:
        return "You are already registered for this training!"

    participant_count = Registration.query.filter_by(training_id=t.id, is_waitlist=False).count()
    on_waitlist = participant_count >= t.limiet

    new_reg = Registration(
        naam=naam,
        email=email,
        is_waitlist=on_waitlist,
        training_id=t.id,
    )
    db.session.add(new_reg)
    db.session.commit()

    cancel_link = url_for('annuleren', inschrijving_id=new_reg.id, _external=True)

    if on_waitlist:
        send_email(
            email,
            "Waitlist confirmation",
            f"Hello {naam}, the training is currently full. You have been added to the waitlist.",
        )
        return f"Fully booked. You have been added to the waitlist, {naam}. <a href='/'>Back</a>"
    else:
        send_email(
            email,
            "Training registration confirmed",
            f"Hello {naam}, your registration is confirmed!\n\n"
            f"If you cannot attend, you can cancel here: {cancel_link}",
        )
        return f"You are registered, {naam}. <a href='/'>Back</a>"

@app.route('/annuleren/<int:inschrijving_id>')
def annuleren(inschrijving_id):
    reg = Registration.query.get_or_404(inschrijving_id)
    t = reg.training

    db.session.delete(reg)
    db.session.commit()

    msg = f"<h1>Cancelled</h1><p>Your registration has been cancelled, {reg.naam}.</p>"

    first_waiting = Registration.query.filter_by(
        training_id=t.id, is_waitlist=True
    ).order_by(Registration.id).first()

    if first_waiting:
        first_waiting.is_waitlist = False
        db.session.commit()

        new_cancel_link = url_for('annuleren', inschrijving_id=first_waiting.id, _external=True)
        send_email(
            first_waiting.email,
            "Spot available! You are now registered",
            f"Good news {first_waiting.naam}! A spot became available and you are now registered.\n\n"
            f"If you cannot attend, you can cancel here: {new_cancel_link}",
        )
        msg += f"<p>{first_waiting.naam} has been moved from the waitlist to the participants list.</p>"

    return msg + "<a href='/'>Back to overview</a>"

# --- AUTH ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username, password=password).first()
        if user:
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid credentials.", "danger")

    return """
    <h1>Admin Login</h1>
    <form method="post">
        <input type="text" name="username" placeholder="Username" required><br><br>
        <input type="password" name="password" placeholder="Password" required><br><br>
        <button type="submit">Login</button>
    </form>
    """

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out.", "info")
    return redirect(url_for('index'))

# --- SIMPLE ADMIN DASHBOARD ---

@app.route('/admin')
@login_required
def admin_dashboard():
    trainings = Training.query.order_by(Training.datum_sleutel).all()
    return render_template('admin.html', trainings=trainings)

@app.route('/admin/add', methods=['POST'])
@login_required
def admin_add_training():
    datum_sleutel = request.form['datum_sleutel']
    naam_display = request.form['naam_display']
    limiet = int(request.form['limiet'])
    open_vanaf_str = request.form['open_vanaf']

    try:
        open_vanaf = datetime.strptime(open_vanaf_str, "%Y-%m-%d %H:%M")
    except ValueError:
        flash("Invalid date/time format. Use YYYY-MM-DD HH:MM", "danger")
        return redirect(url_for('admin_dashboard'))

    existing = Training.query.filter_by(datum_sleutel=datum_sleutel).first()
    if existing:
        flash("A training with this date key already exists.", "danger")
        return redirect(url_for('admin_dashboard'))

    t = Training(
        datum_sleutel=datum_sleutel,
        naam_display=naam_display,
        limiet=limiet,
        open_vanaf=open_vanaf,
    )
    db.session.add(t)
    db.session.commit()
    flash("Training added.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/training/<int:training_id>/delete')
@login_required
def admin_delete_training(training_id):
    t = Training.query.get_or_404(training_id)
    # delete registrations first
    for r in t.registrations:
        db.session.delete(r)
    db.session.delete(t)
    db.session.commit()
    flash("Training and all registrations deleted.", "info")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/training/<int:training_id>')
@login_required
def admin_training_detail(training_id):
    t = Training.query.get_or_404(training_id)
    participants = [r for r in t.registrations if not r.is_waitlist]
    waitlist = [r for r in t.registrations if r.is_waitlist]

    return render_template(
        'admin_training_detail.html',
        training=t,
        participants=participants,
        waitlist=waitlist,
    )

@app.route('/admin/registration/<int:registration_id>/kick')
@login_required
def admin_kick(registration_id):
    r = Registration.query.get_or_404(registration_id)
    training = r.training

    # send email to removed person
    try:
        send_email(
            r.email,
            "Your training registration has been cancelled",
            (
                f"Hello {r.naam},\n\n"
                f"Your registration for '{training.naam_display}' has been cancelled by the organizer.\n\n"
                "If you think this is a mistake, please contact the organizer."
            )
        )
    except Exception as e:
        print(f"Error sending kick email: {e}")

    db.session.delete(r)
    db.session.commit()
    flash("Registration removed and email sent (if possible).", "info")
    return redirect(url_for('admin_training_detail', training_id=training.id))

@app.route('/admin/training/<int:training_id>/add', methods=['POST'])
@login_required
def admin_add_registration(training_id):
    t = Training.query.get_or_404(training_id)
    name = request.form['name']
    email = request.form['email']
    role = request.form.get('role', 'participant')  # 'participant' or 'waitlist'

    # avoid duplicates
    existing = Registration.query.filter_by(training_id=t.id, email=email).first()
    if existing:
        flash("This email is already registered for this training.", "danger")
        return redirect(url_for('admin_training_detail', training_id=t.id))

    is_waitlist = (role == 'waitlist')
    # if you choose 'participant', respect the limit:
    if not is_waitlist:
        participant_count = Registration.query.filter_by(
            training_id=t.id, is_waitlist=False
        ).count()
        if participant_count >= t.limiet:
            flash("Training is full, cannot add as participant. Add to waitlist instead.", "danger")
            return redirect(url_for('admin_training_detail', training_id=t.id))

    reg = Registration(
        naam=name,
        email=email,
        is_waitlist=is_waitlist,
        training_id=t.id,
    )
    db.session.add(reg)
    db.session.commit()
    flash("Registration added.", "success")
    return redirect(url_for('admin_training_detail', training_id=t.id))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
