import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime


# Load .env
load_dotenv()
print("Loaded .env")
print("SHEET_ID =", os.environ.get("SHEET_ID"))

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'dev-secret-change-me')


# Google Sheets config
service_account_info = {
    "type": os.environ.get("GOOGLE_TYPE"),
    "project_id": os.environ.get("GOOGLE_PROJECT_ID"),
    "private_key_id": os.environ.get("GOOGLE_PRIVATE_KEY_ID"),
    "private_key": os.environ.get("GOOGLE_PRIVATE_KEY").replace("\\n", "\n"),
    "client_email": os.environ.get("GOOGLE_CLIENT_EMAIL"),
    "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
    "auth_uri": os.environ.get("GOOGLE_AUTH_URI"),
    "token_uri": os.environ.get("GOOGLE_TOKEN_URI"),
    "auth_provider_x509_cert_url": os.environ.get("GOOGLE_AUTH_PROVIDER_X509_CERT_URL"),
    "client_x509_cert_url": os.environ.get("GOOGLE_CLIENT_X509_CERT_URL"),
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

creds = Credentials.from_service_account_info(
    service_account_info,
    scopes=SCOPES
)

client = gspread.authorize(creds)

SHEET_ID = os.environ.get('SHEET_ID')
if not SHEET_ID:
    raise RuntimeError('SHEET_ID must be set as environment variable.')


SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
client = gspread.authorize(creds)


# Open spreadsheet and worksheets. Worksheets names must exist.
sh = client.open_by_key(SHEET_ID)
# Expected worksheets: Patients, Doctors, Nurses, Admin, Appointments, Reports
try:
    patients_ws = sh.worksheet('Patients')
    doctors_ws = sh.worksheet('Doctors')
    nurses_ws = sh.worksheet('Nurses')
    admin_ws = sh.worksheet('Admin')
    appointments_ws = sh.worksheet('Appointments')
    reports_ws = sh.worksheet('Reports')
except Exception as e:
    raise RuntimeError('Make sure the spreadsheet has worksheets named: Patients, Doctors, Nurses, Admin, Appointments, Reports.')
def get_all(ws):
    try:
        return ws.get_all_records()
    except Exception:
        return []




def find_user(ws, email):
    recs = get_all(ws)
    for r in recs:
        if str(r.get('email','')).strip().lower() == str(email).strip().lower():
            return r
    return None


# Simple session guard


def require_role(r):
    def decorator(func):
        def wrapper(*args, **kwargs):
            if session.get('role') != r:
                flash('Please log in with the correct role.')
                return redirect(url_for('login_role', role=r))
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper
    return decorator

def get_name_by_email(ws, email):
    """Return name from a sheet (Patients or Doctors) given an email, or None."""
    try:
        recs = ws.get_all_records()
        for r in recs:
            if str(r.get('email','')).strip().lower() == str(email or '').strip().lower():
                return r.get('name') or None
    except Exception:
        return None
    return None


# ----------------- Routes -----------------


@app.route('/')
def index():
    return render_template('index.html')


# Generic login page per role
@app.route('/login/<role>', methods=['GET','POST'])
def login_role(role):
    role = role.lower()
    if role not in ('patient','doctor','nurse','admin'):
        flash('Unknown role')
        return redirect(url_for('index'))


    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        ws = {'patient': patients_ws, 'doctor': doctors_ws, 'nurse': nurses_ws, 'admin': admin_ws}[role]
        user = find_user(ws, email)
        if user and str(user.get('password','')) == str(password):
            session['role'] = role
            session['email'] = email
            session['name'] = user.get('name') if user.get('name') else ''
            flash(f'Logged in as {role}')
            return redirect(url_for(f'dashboard_{role}'))
        flash('Invalid credentials')


    return render_template('login_role.html', role=role.title())
# Patient registration
@app.route('/register/patient', methods=['GET','POST'])
def register_patient():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone','')
        age = request.form.get('age','')
        if find_user(patients_ws, email):
            flash('Account already exists')
            return redirect(url_for('register_patient'))
        pid = f'P{int(datetime.utcnow().timestamp())}'
        patients_ws.append_row([pid, name, email, password, phone, age], value_input_option='USER_ENTERED')
        flash('Registration successful. Please log in.')
        return redirect(url_for('login_role', role='patient'))
    return render_template('register_patient.html')
# Logout
@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out')
    return redirect(url_for('index'))


# ---------------- Dashboards ----------------


@app.route('/dashboard/patient')
@require_role('patient')
def dashboard_patient():
    email = session.get('email')
    user = find_user(patients_ws, email)
    appts = [a for a in get_all(appointments_ws) if str(a.get('patient_email','')).lower()==email.lower()]
    return render_template('dashboard_patient.html', user=user, appointments=appts)


@app.route('/book_appointment', methods=['GET', 'POST'])
@require_role('patient')
def book_appointment():
    email = session.get('email')
    user = find_user(patients_ws, email)
    doctors = get_all(doctors_ws)

    if request.method == 'POST':
        selected_doctor_email = request.form.get('doctor_email')

        if selected_doctor_email:
            #selected doctor details
            doctor = next((d for d in doctors if str(d.get('email', '')).lower() == selected_doctor_email.lower()), None)

            if doctor:
                doctor_name = doctor.get('name', '')
                specialization = doctor.get('specialization', '')
                available_time = doctor.get('available_time', '')

                
                appointments_ws.append_row([
                    email,                        # patient_email
                    selected_doctor_email,         # doctor_email
                    doctor_name,                   # doctor_name
                    specialization,                # specialization
                    available_time,                # available_time
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # booked_on
                    "Pending"                      # status
                ], value_input_option='USER_ENTERED')

                flash(f"Appointment booked successfully with Dr. {doctor_name}!", "success")
                return redirect(url_for('dashboard_patient'))

            flash("Doctor not found!", "error")
            return redirect(url_for('book_appointment'))

    return render_template('appointments_patient.html', user=user, doctors=doctors)


@app.route('/dashboard/doctor')
@require_role('doctor')
def dashboard_doctor():
    email = session.get('email')
    all_appts = get_all(appointments_ws)

    header = [h.lower() for h in appointments_ws.row_values(1)]

    appts = []
    for i, a in enumerate(all_appts, start=2):  # real sheet row
        # only include this doctor's appointments
        if str(a.get('doctor_email', '')).lower() == str(email).lower():
            a['patient_email'] = a.get('patient_email', '—')
            a['patient_name'] = a.get('patient_name', '—')
            a['available_time'] = a.get('available_time', '—')
            a['booked_on'] = a.get('booked_on', '—')
            a['status'] = a.get('status', 'Pending')
            a['doctor_name'] = a.get('doctor_name', '—')
            a['specialization'] = a.get('specialization', '—')
            a['sheet_row'] = i  
            appts.append(a)

    return render_template('dashboard_doctor.html', appointments=appts)

@app.route('/update_status/<int:row>/<new_status>')
@require_role('doctor')
def update_status(row, new_status):
    try:
        header = [h.lower() for h in appointments_ws.row_values(1)]

        if "status" in header:
            status_col = header.index("status") + 1
        else:
            flash("Couldn't find 'status' column!", "danger")
            return redirect(url_for('dashboard_doctor'))

        # ✅ Update the correct cell
        appointments_ws.update_cell(row, status_col, new_status)

        flash(f"Appointment marked as {new_status}", "success")

    except Exception as e:
        print(f"Error in update_status: {e}")
        flash(f"Error updating status: {e}", "danger")

    return redirect(url_for('dashboard_doctor'))

@app.route('/dashboard/nurse', methods=['GET', 'POST'])
@require_role('nurse')
def dashboard_nurse():
    # POST -> update status
    if request.method == 'POST':
        try:
            row_index = int(request.form.get('row_index'))  
            new_status = request.form.get('status')
            if new_status:
                appointments_ws.update_cell(row_index + 2, 7, new_status)
                flash('Appointment status updated.', 'success')
        except Exception as e:
            flash('Failed to update status: ' + str(e), 'danger')
        return redirect(url_for('dashboard_nurse'))

    # GET -> show appointments
    raw_appts = get_all(appointments_ws)  # returns list of dicts from sheet
    enhanced = []

    for a in raw_appts:
        # read fields from appointment row (use get to avoid KeyError)
        p_email = a.get('patient_email', '')
        d_email = a.get('doctor_email', '')

        # lookup patient name and doctor name in respective sheets if available
        p_name = get_name_by_email(patients_ws, p_email) or p_email
        # prefer doctor_name in appointment row, fallback to lookup in Doctors sheet
        d_name = a.get('doctor_name') or get_name_by_email(doctors_ws, d_email) or d_email

        enhanced.append({
            'patient_email': p_email,
            'patient_name': p_name,
            'doctor_email': d_email,
            'doctor_name': d_name,
            'specialization': a.get('specialization',''),
            'available_time': a.get('available_time',''),
            'booked_on': a.get('booked_on',''),
            'status': a.get('status','')
        })

    # Pass the list to template. The template uses loop.index0 as the row index.
    return render_template('dashboard_nurse.html', appointments=enhanced)


@app.route('/dashboard/admin')
@require_role('admin')
def dashboard_admin():
    patients = get_all(patients_ws)
    doctors = get_all(doctors_ws)
    nurses = get_all(nurses_ws)
    return render_template(
        'dashboard_admin.html',
        patients=patients,
        doctors=doctors,
        nurses=nurses
    )

@app.route('/add_staff', methods=['POST'])
@require_role('admin')
def add_staff():
    role = request.form['role']
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']
    specialization = request.form.get('specialization', '')
    available_time = request.form.get('available_time', '')
    phone = request.form.get('phone', '')

    if role == 'doctor':
        # Generate a new ID
        records = doctors_ws.get_all_records()
        new_id = len(records) + 1
        doctors_ws.append_row([
            new_id, name, email, password, specialization, phone, available_time
        ], value_input_option='USER_ENTERED')

    elif role == 'nurse':
        records = nurses_ws.get_all_records()
        new_id = len(records) + 1
        nurses_ws.append_row([
            new_id, name, email, password, phone
        ], value_input_option='USER_ENTERED')

    flash(f"{role.title()} added successfully!", "success")
    return redirect(url_for('dashboard_admin'))

@app.route('/view')
def view_all():
    sheet = sh.worksheet('Patients')
    data = sheet.get_all_records()
    return render_template('view.html', data=data)

@app.route('/view/patients')
def view_patients():
    sheet = sh.worksheet('Patients')
    data = sheet.get_all_records()
    return render_template('view_patients.html', patients=data)


if __name__ == '__main__':
    app.run(debug=True)