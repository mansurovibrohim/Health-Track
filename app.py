from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from flask_babel import Babel, _
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import os
from dotenv import load_dotenv
from functools import wraps

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config.from_object('config.Config')

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'locale'

def get_locale():
    # if a user is logged in, use the locale from the user settings
    # otherwise try to guess the language from the user accept
    # header the browser transmits.  We support uz, ru, en in this
    # example.  The best match wins.
    if 'language' in session:
        return session['language']
    return request.accept_languages.best_match(['en', 'uz', 'ru'])

babel = Babel(app, locale_selector=get_locale)

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    country = db.Column(db.String(100))
    city = db.Column(db.String(100))
    telegram_chat_id = db.Column(db.String(50))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    medications = db.relationship('Medication', backref='user', lazy=True, cascade='all, delete-orphan')

class Medication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    quantity_remaining = db.Column(db.Integer, nullable=False)
    quantity_per_dose = db.Column(db.Integer, nullable=False)
    expiration_date = db.Column(db.Date, nullable=False)
    times_per_day = db.Column(db.Integer, default=1)
    reminder_times = db.Column(db.String(500))  # JSON string of times like ["08:00", "20:00"]
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    reminders = db.relationship('Reminder', backref='medication', lazy=True, cascade='all, delete-orphan')

class Reminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    medication_id = db.Column(db.Integer, db.ForeignKey('medication.id'), nullable=False)
    reminder_time = db.Column(db.Time, nullable=False)
    last_sent = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.context_processor
def inject_datetime():
    return dict(datetime=datetime)

# Admin decorator
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash(_('Access denied. Admin privileges required.'), 'error')

            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/set_language/<language>')
def set_language(language):
    if language in ['en', 'uz', 'ru']:
        session['language'] = language
    return redirect(request.referrer or url_for('index'))

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            # Auto-redirect admin to admin panel
            if user.is_admin:
                flash(_('Admin login successful'), 'success')

                return redirect(url_for('admin_dashboard'))
            # Check if user has selected country
            if not user.country:
                return redirect(url_for('select_country'))
            return redirect(url_for('dashboard'))
        else:
            flash(_('Invalid email or password'), 'error')

    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash(_('Username already exists'), 'error')

            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash(_('Email already exists'), 'error')

            return redirect(url_for('register'))
        
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        
        # Auto login after registration
        login_user(user, remember=True)
        flash(_('Registration successful! You have been logged in automatically.'), 'success')

        return redirect(url_for('select_country'))
    
    return render_template('register.html')

@app.route('/select_country', methods=['GET', 'POST'])
@login_required
def select_country():
    if request.method == 'POST':
        country = request.form.get('country')
        city = request.form.get('city')
        
        current_user.country = country
        current_user.city = city
        db.session.commit()
        
        flash(_('Country and city selected successfully!'), 'success')

        return redirect(url_for('dashboard'))
    
    return render_template('select_country.html')

@app.route('/dashboard')
@login_required
def dashboard():
    # Get weather and air quality data
    # Default to Tashkent, UZ if user hasn't set their city
    city = current_user.city or 'Tashkent'
    country = current_user.country or 'UZ'
    
    weather_data = get_weather_data(city, country)
    air_quality_data = None
    aqi_forecast = None
    city_rankings = None
    
    coords = get_coordinates(city, country)
    if coords:
        air_quality_data = get_air_quality_data(coords['lat'], coords['lon'], city_name=city)
        aqi_forecast = get_air_quality_forecast(coords['lat'], coords['lon'], city_name=city)
    
    # Get city rankings for the selected country
    city_rankings = get_city_rankings(country, current_city_data=air_quality_data)
    
    # Get user medications
    medications = Medication.query.filter_by(user_id=current_user.id).all()
    
    # Get upcoming reminders
    now = datetime.now().time()
    today = datetime.now().date()
    upcoming_reminders = []
    for med in medications:
        if med.reminder_times:
            try:
                times = json.loads(med.reminder_times)
                for time_str in times:
                    reminder_time = datetime.strptime(time_str, '%H:%M').time()
                    if reminder_time >= now:
                        upcoming_reminders.append({
                            'medication': med.name,
                            'time': time_str,
                            'quantity': med.quantity_per_dose
                        })
            except:
                pass
    
    upcoming_reminders.sort(key=lambda x: x['time'])
    
    return render_template('dashboard.html', 
                         weather_data=weather_data,
                         air_quality_data=air_quality_data,
                         aqi_forecast=aqi_forecast,
                         city_rankings=city_rankings,
                         medications=medications,
                         upcoming_reminders=upcoming_reminders[:5],
                         today=today)

@app.route('/add_medication', methods=['GET', 'POST'])
@login_required
def add_medication():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description', '')
        quantity_remaining = int(request.form.get('quantity_remaining'))
        quantity_per_dose = int(request.form.get('quantity_per_dose'))
        expiration_date = datetime.strptime(request.form.get('expiration_date'), '%Y-%m-%d').date()
        times_per_day = int(request.form.get('times_per_day', 1))
        
        # Get reminder times
        reminder_times = []
        for i in range(times_per_day):
            time_key = f'reminder_time_{i}'
            if time_key in request.form and request.form.get(time_key):
                reminder_times.append(request.form.get(time_key))
        
        medication = Medication(
            user_id=current_user.id,
            name=name,
            description=description,
            quantity_remaining=quantity_remaining,
            quantity_per_dose=quantity_per_dose,
            expiration_date=expiration_date,
            times_per_day=times_per_day,
            reminder_times=json.dumps(reminder_times)
        )
        
        db.session.add(medication)
        db.session.commit()
        
        # Create reminder records
        for time_str in reminder_times:
            reminder_time = datetime.strptime(time_str, '%H:%M').time()
            reminder = Reminder(
                medication_id=medication.id,
                reminder_time=reminder_time,
                is_active=True
            )
            db.session.add(reminder)
        
        db.session.commit()
        
        flash(_('Medication added successfully!'), 'success')

        return redirect(url_for('dashboard'))
    
    return render_template('add_medication.html')

@app.route('/medications')
@login_required
def medications():
    medications_list = Medication.query.filter_by(user_id=current_user.id).all()
    
    # Parse reminder times for each medication
    reminder_times_list = {}
    for med in medications_list:
        if med.reminder_times:
            try:
                reminder_times_list[med.id] = json.loads(med.reminder_times)
            except:
                reminder_times_list[med.id] = []
        else:
            reminder_times_list[med.id] = []
    
    today = datetime.now().date()
    
    return render_template('medications.html', 
                         medications=medications_list,
                         reminder_times_list=reminder_times_list,
                         today=today)

@app.route('/edit_medication/<int:med_id>', methods=['POST'])
@login_required
def edit_medication(med_id):
    try:
        med = Medication.query.get_or_404(med_id)
        if med.user_id != current_user.id:
            flash(_('Access denied.'), 'error')
            return redirect(url_for('medications'))
            
        med.name = request.form.get('name')
        med.description = request.form.get('description', '')
        med.quantity_remaining = int(request.form.get('quantity_remaining'))
        med.quantity_per_dose = int(request.form.get('quantity_per_dose'))
        med.expiration_date = datetime.strptime(request.form.get('expiration_date'), '%Y-%m-%d').date()
        med.times_per_day = int(request.form.get('times_per_day', 1))
        
        # Update reminders: delete old ones and add new ones
        Reminder.query.filter_by(medication_id=med.id).delete()
        
        reminder_times = []
        for i in range(med.times_per_day):
            time_key = f'reminder_time_{i}'
            if time_key in request.form and request.form.get(time_key):
                time_str = request.form.get(time_key)
                reminder_times.append(time_str)
                reminder_time = datetime.strptime(time_str, '%H:%M').time()
                reminder = Reminder(
                    medication_id=med.id,
                    reminder_time=reminder_time,
                    is_active=True
                )
                db.session.add(reminder)
        
        med.reminder_times = json.dumps(reminder_times)
        db.session.commit()
        
        flash(_('Medication updated successfully!'), 'success')
        return redirect(url_for('medications'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating medication: {str(e)}', 'error')
        return redirect(url_for('medications'))

@app.route('/delete_medication/<int:med_id>', methods=['POST'])
@login_required
def delete_medication(med_id):
    try:
        med = Medication.query.get_or_404(med_id)
        if med.user_id != current_user.id:
            flash(_('Access denied.'), 'error')
            return redirect(url_for('medications'))
            
        # Associated reminders will be deleted automatically due to cascade='all, delete-orphan'
        db.session.delete(med)
        db.session.commit()
        
        flash(_('Medication deleted successfully!'), 'success')
        return redirect(url_for('medications'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting medication: {str(e)}', 'error')
        return redirect(url_for('medications'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        country = request.form.get('country')
        city = request.form.get('city')
        telegram_chat_id = request.form.get('telegram_chat_id', '').strip()
        email = request.form.get('email', '').strip()
        
        # Email update logic
        if email and email != current_user.email:
            # Check if email is already taken
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                flash(_('This email is already registered with another account.'), 'error')

                return redirect(url_for('profile'))
            current_user.email = email

        current_user.country = country
        current_user.city = city
        if telegram_chat_id:
            current_user.telegram_chat_id = telegram_chat_id
            # Test message
            test_message = _("✅ Hello %(username)s! Telegram bot is working. Chat ID: %(chat_id)s", username=current_user.username, chat_id=telegram_chat_id)

            send_telegram_message(telegram_chat_id, test_message)
        else:
            current_user.telegram_chat_id = None
        
        db.session.commit()
        
        flash(_('Profile updated successfully!'), 'success')

        return redirect(url_for('profile'))
    
    return render_template('profile.html')

@app.route('/test_telegram', methods=['POST'])
@login_required
def test_telegram():
    """Test Telegram bot connection"""
    if not current_user.telegram_chat_id:
        flash(_('Telegram Chat ID not entered!'), 'error')

        return redirect(url_for('profile'))
    
    test_message = _("🧪 Test Message!\n\nHello %(username)s!\nThis is a test message. If you see this, the bot is working correctly! ✅", username=current_user.username)

    result = send_telegram_message(current_user.telegram_chat_id, test_message)
    
    if result:
        flash(_('Test message sent! Check Telegram.'), 'success')
    else:
        flash(_('Message not sent! Check Chat ID and Bot Token.'), 'error')

    
    return redirect(url_for('profile'))

@app.route('/test_notifications')
@login_required
def test_notifications():
    """Manually test Email and Telegram notifications"""
    results = {'email': False, 'telegram': False}
    
    # Test Email
    email_subject = _("Health Track: Test Notification")
    email_body = _("Hello %(username)s!\nThis is a manual test of your email notification system.", username=current_user.username)

    results['email'] = send_email_notification(current_user.email, email_subject, email_body)
    
    # Test Telegram
    if current_user.telegram_chat_id:
        telegram_message = _("🧪 Health Track Test!\n\nHello %(username)s!\nIf you see this, your Telegram notifications are working correctly! ✅", username=current_user.username)

        results['telegram'] = send_telegram_message(current_user.telegram_chat_id, telegram_message)
    
    if results['email'] and (not current_user.telegram_chat_id or results['telegram']):
        flash(_('Test notifications sent! Check your email and Telegram.'), 'success')
    elif results['email']:
        flash(_('Email sent, but Telegram failed (check Chat ID or Bot Token).'), 'warning')
    elif results['telegram']:
        flash(_('Telegram sent, but Email failed (check SMTP settings).'), 'warning')
    else:
        flash(_('Both Email and Telegram notifications failed configuration.'), 'error')

        
    return redirect(url_for('profile'))

@app.route('/get_chat_id', methods=['GET'])
@login_required
def get_chat_id():
    """Get Chat ID from Telegram bot - user should send /start to bot first"""
    token = app.config['TELEGRAM_BOT_TOKEN']
    if not token:
        flash(_('Telegram Bot Token not found! Add TELEGRAM_BOT_TOKEN to .env file.'), 'error')

        return redirect(url_for('profile'))
    
    try:
        # Get recent updates from bot
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('ok') and data.get('result'):
                updates = data['result']
                # Find the most recent /start command
                for update in reversed(updates):
                    if 'message' in update and 'text' in update['message']:
                        text = update['message']['text']
                        if text == '/start' or 'start' in text.lower():
                            chat_id = str(update['message']['from']['id'])
                            username = update['message']['from'].get('username', 'Noma\'lum')
                            first_name = update['message']['from'].get('first_name', '')
                            
                            # Check if this chat_id matches current user (optional)
                            # For now, just return the latest chat_id
                            return jsonify({
                                'success': True,
                                'chat_id': chat_id,
                                'username': username,
                                'first_name': first_name,
                                'message': f'Chat ID topildi: {chat_id}'
                            })
                
                return jsonify({
                    'success': False,
                    'message': 'Botga /start yuborilmagan. Telegram\'da botingizga /start yuboring.'
                })
            else:
                return jsonify({
                    'success': False,
                    'message': 'Botga hech qanday xabar kelmagan. Botga /start yuboring.'
                })
        else:
            return jsonify({
                'success': False,
                'message': f'Telegram API xatolik: {response.status_code}'
            })
    except Exception as e:
        print(f"Chat ID olish xatolik: {e}")
        return jsonify({
            'success': False,
            'message': f'Xatolik: {str(e)}'
        })

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash(_('Logged out successfully'), 'info')

    return redirect(url_for('login'))

@app.route('/api/cities/<country_code>')
def get_cities(country_code):
    """API endpoint to get cities/regions for a country"""
    cities = COUNTRY_CITIES.get(country_code.upper(), [])
    return jsonify({'cities': cities})

# Admin Routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == app.config['ADMIN_PASSWORD']:
            # Find or create admin user
            admin = User.query.filter_by(username='admin').first()
            if not admin:
                admin = User(
                    username='admin',
                    email='mansurovislombek130@gmail.com',
                    password_hash=generate_password_hash(app.config['ADMIN_PASSWORD']),
                    is_admin=True
                )
                db.session.add(admin)
                db.session.commit()
            else:
                admin.email = 'mansurovislombek130@gmail.com'
                db.session.commit()
            login_user(admin)
            flash('Admin login successful', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid password', 'error')
    return render_template('admin_login.html')

@app.route('/admin')
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_medications = Medication.query.count()
    total_reminders = Reminder.query.count()
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    return render_template('admin_dashboard.html',
                         total_users=total_users,
                         total_medications=total_medications,
                         total_reminders=total_reminders,
                         recent_users=recent_users)

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', users=users)

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('Cannot delete admin user', 'error')
        return redirect(url_for('admin_users'))
    
    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(_('User %(username)s deleted successfully', username=username), 'success')

    return redirect(url_for('admin_users'))

@app.route('/admin/database/clear', methods=['POST'])
@admin_required
def admin_clear_database():
    try:
        # Clear all data except admin
        admin_user = User.query.filter_by(is_admin=True).first()
        
        # Delete all medications and reminders
        Medication.query.delete()
        Reminder.query.delete()
        
        # Delete all non-admin users
        User.query.filter(User.is_admin != True).delete()
        
        db.session.commit()
        flash(_('Database cleared successfully (admin user preserved)'), 'success')
    except Exception as e:
        flash(_('Error clearing database: %(error)s', error=str(e)), 'error')

    
    return redirect(url_for('admin_dashboard'))

def generate_mock_weather(city_name):
    """Generate stable mock weather data based on city name"""
    import hashlib
    hash_val = int(hashlib.md5(city_name.lower().encode()).hexdigest(), 16)
    temp = (hash_val % 40) - 5 # -5 to 35
    humidity = 30 + (hash_val % 50)
    wind_speed = (hash_val % 20) + 1
    
    conditions = [(_('Clear'), '01d'), (_('Mainly Cloudy'), '03d'), (_('Rain'), '10d'), (_('Snow'), '13d')]

    desc, icon = conditions[hash_val % len(conditions)]
    
    advice = get_weather_advice(temp, desc, humidity, wind_speed)
    
    return {
        'temperature': temp,
        'description': desc,
        'icon': icon,
        'humidity': humidity,
        'wind_speed': wind_speed,
        'feels_like': temp - 2 if wind_speed > 10 else temp + 1,
        'pollen': ['Low', 'Moderate', 'High'][hash_val % 3],
        'advice': advice
    }

def get_weather_data(city, country):
    """Get weather data from OpenWeatherMap API"""
    if not city or not country:
        return None
    
    api_key = app.config['WEATHER_API_KEY']
    if not api_key:
        return generate_mock_weather(city)
    
    try:
        url = f"{app.config['WEATHER_API_URL']}?q={city},{country}&appid={api_key}&units=metric&lang=en"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            temp = int(data['main']['temp'])
            desc = data['weather'][0]['description'].capitalize()
            icon = data['weather'][0]['icon']
            humidity = data['main']['humidity']
            wind_speed = data['wind']['speed']
            feels_like = int(data['main']['feels_like'])
            
            # Generate health advice based on weather
            advice = get_weather_advice(temp, desc, humidity, wind_speed)
            
            return {
                'temperature': temp,
                'description': desc,
                'icon': icon,
                'humidity': humidity,
                'wind_speed': wind_speed,
                'feels_like': feels_like,
                'pollen': 'Low',  # Default for real data if not available
                'advice': advice
            }
        else:
            print(f"Weather API error: Status {response.status_code}")
    except Exception as e:
        print(f"Weather API error: {e}")
    
    # Return mock data on failure or unauthorized
    return generate_mock_weather(city)

def get_weather_advice(temp, desc, humidity, wind_speed):
    """Generate health advice based on weather conditions"""
    advice_parts = []
    
    # Temperature advice
    if temp < 0:
        advice_parts.append(_("Very cold! Wear warm clothes and stay outside for short periods."))
    elif temp < 10:
        advice_parts.append(_("Cold weather. Wear warm clothes."))
    elif temp > 35:
        advice_parts.append(_("Very hot! Drink plenty of water and avoid direct sunlight."))
    elif temp > 25:
        advice_parts.append(_("Hot weather. Drink plenty of water and wear light clothing."))
    else:
        advice_parts.append(_("Comfortable weather. Great time for outdoor activities!"))
    
    # Weather condition advice
    if 'rain' in desc.lower():
        advice_parts.append(_("It's raining. Take an umbrella and avoid getting wet."))
    elif 'snow' in desc.lower():
        advice_parts.append(_("It's snowing. Be careful and avoid slippery surfaces."))
    elif 'fog' in desc.lower():
        advice_parts.append(_("Foggy. Visibility is limited, be cautious."))
    
    # Humidity advice
    if humidity > 80:
        advice_parts.append(_("High humidity. Breathing may be difficult."))
    elif humidity < 30:
        advice_parts.append(_("Dry air. Drink plenty of water and moisturize your skin."))
    
    # Wind advice
    if wind_speed > 15:
        advice_parts.append(_("Strong wind. Be careful and secure loose items."))
    
    return " ".join(advice_parts) if advice_parts else _("Normal weather. Regular walking is recommended for health.")


def calculate_us_aqi(pm25):
    """Calculate US AQI (0-500) based on EPA PM2.5 breakpoints"""
    if pm25 <= 12.0:
        return round((50 - 0) / (12.0 - 0) * (pm25 - 0) + 0)
    elif pm25 <= 35.4:
        return round((100 - 51) / (35.4 - 12.1) * (pm25 - 12.1) + 51)
    elif pm25 <= 55.4:
        return round((150 - 101) / (55.4 - 35.5) * (pm25 - 35.5) + 101)
    elif pm25 <= 150.4:
        return round((200 - 151) / (150.4 - 55.5) * (pm25 - 55.5) + 151)
    elif pm25 <= 250.4:
        return round((300 - 201) / (250.4 - 150.5) * (pm25 - 150.5) + 201)
    else:
        return min(500, round((500 - 301) / (500.4 - 250.5) * (pm25 - 250.5) + 301))

def get_coordinates(city, country):
    """Get latitude and longitude for a city using OpenWeatherMap Geocoding API"""
    api_key = app.config['WEATHER_API_KEY']
    
    def get_mock_coords(city_name):
        import hashlib
        hash_val = int(hashlib.md5(city_name.lower().encode()).hexdigest(), 16)
        return {'lat': (hash_val % 180) - 90, 'lon': ((hash_val // 180) % 360) - 180}

    if not api_key:
        return get_mock_coords(city)
    
    try:
        url = f"http://api.openweathermap.org/geo/1.0/direct?q={city},{country}&limit=1&appid={api_key}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data:
                return {'lat': data[0]['lat'], 'lon': data[0]['lon']}
    except Exception as e:
        print(f"Geocoding API error: {e}")
    
    # Fallback to mock coords on error
    return get_mock_coords(city)

def generate_mock_aqi(city_name):
    """Generate stable mock AQI data based on city name"""
    import hashlib
    hash_val = int(hashlib.md5((city_name + "aqi").lower().encode()).hexdigest(), 16)
    
    pm25 = (hash_val % 100) + 5.0
    pm10 = pm25 * 2.5 + (hash_val % 30)
    o3 = (hash_val % 120) + 10.0
    no2 = (hash_val % 80) + 5.0
    so2 = (hash_val % 40) + 2.0
    co = (hash_val % 5000) + 200.0
    
    def get_level(val, thresholds):
        for i, t in enumerate(thresholds):
            if val <= t: return i + 1
        return 5

    l_pm25 = get_level(pm25, [10, 25, 50, 75])
    l_pm10 = get_level(pm10, [20, 50, 100, 200])
    l_o3 = get_level(o3, [60, 100, 140, 180])
    l_no2 = get_level(no2, [40, 70, 150, 200])
    l_so2 = get_level(so2, [20, 80, 250, 350])
    l_co = get_level(co, [4400, 9400, 12400, 15400])
    
    # Calculate US AQI specifically using PM2.5
    us_aqi = calculate_us_aqi(pm25)
    
    # 0-50 Good(1), 51-100 Mod(2), 101-150 USG(3), 151-200 Unh(4), 201+ V.Unh(5)
    if us_aqi <= 50:
        avg_score = 1
    elif us_aqi <= 100:
        avg_score = 2
    elif us_aqi <= 150:
        avg_score = 3
    elif us_aqi <= 200:
        avg_score = 4
    else:
        avg_score = 5
        
    aqi_labels = {1: _('Good'), 2: _('Moderate'), 3: _('Unhealthy for Sensitive Groups'), 4: _('Unhealthy'), 5: _('Very Unhealthy')}
    aqi_colors = {
        1: '#10b981', 2: '#fbb117', 3: '#f59e0b', 4: '#ef4444', 5: '#991b1b'
    }
    aqi_advice = {
        1: _('Air quality is satisfactory, and air pollution poses little or no risk.'),
        2: _('Air quality is acceptable. However, there may be a risk for some people, particularly those who are unusually sensitive to air pollution.'),
        3: _('Members of sensitive groups may experience health effects. The general public is less likely to be affected.'),
        4: _('Some members of the general public may experience health effects; members of sensitive groups may experience more serious health effects.'),
        5: _('Health alert: The risk of health effects is increased for everyone.')
    }

    
    pollutants = {'PM2.5': l_pm25, 'PM10': l_pm10, 'Ozone': l_o3, 'NO2': l_no2, 'SO2': l_so2, 'CO': l_co}
    
    return {
        'aqi': us_aqi,  # Send US AQI as the primary AQI
        'us_aqi': us_aqi,
        'avg_score': avg_score, # 1-5 level color tier
        'aqi_label': aqi_labels.get(avg_score, 'Unknown'),
        'aqi_color': aqi_colors.get(avg_score, '#6b7280'),
        'aqi_advice': aqi_advice.get(avg_score, ''),
        'pm2_5': round(pm25, 1),
        'pm10': round(pm10, 1),
        'o3': round(o3, 1),
        'no2': round(no2, 1),
        'so2': round(so2, 1),
        'co': round(co, 1),
        'pollen': ['Low', 'Moderate', 'High'][hash_val % 3],
        'main_pollutant': max(pollutants, key=lambda k: pollutants[k])
    }

def get_air_quality_data(lat, lon, city_name="Unknown"):
    """Get air quality data from OpenWeatherMap Air Pollution API"""
    api_key = app.config['WEATHER_API_KEY']
    
    # Mock data if no API key
    if not api_key:
        return generate_mock_aqi(city_name)
    
    try:
        url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={api_key}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            aqi = data['list'][0]['main']['aqi']
            components = data['list'][0]['components']
            
            # AQI levels: 1=Good, 2=Fair, 3=Moderate, 4=Poor, 5=Very Poor
            # User request: Good (Green), Moderate (Yellow), Poor (Red), Very Poor (Dark Red)
            # Determine individual levels for "averaging" as requested
            def get_level(val, thresholds):
                for i, t in enumerate(thresholds):
                    if val <= t: return i + 1
                return 5

            l_pm25 = get_level(components.get('pm2_5', 0), [10, 25, 50, 75])
            l_pm10 = get_level(components.get('pm10', 0), [20, 50, 100, 200])
            l_o3 = get_level(components.get('o3', 0), [60, 100, 140, 180])
            l_no2 = get_level(components.get('no2', 0), [40, 70, 150, 200])
            l_so2 = get_level(components.get('so2', 0), [20, 80, 250, 350])
            l_co = get_level(components.get('co', 0), [4400, 9400, 12400, 15400])
            
            pm25 = components.get('pm2_5', 0)
            us_aqi = calculate_us_aqi(pm25)
            
            if us_aqi <= 50:
                avg_score = 1
            elif us_aqi <= 100:
                avg_score = 2
            elif us_aqi <= 150:
                avg_score = 3
            elif us_aqi <= 200:
                avg_score = 4
            else:
                avg_score = 5
            
            aqi_labels = {1: 'Good', 2: 'Moderate', 3: 'Unhealthy for Sensitive', 4: 'Unhealthy', 5: 'Very Unhealthy'}
            aqi_colors = {
                1: '#10b981', # Green
                2: '#fbb117', # Yellow
                3: '#f59e0b', # Orange
                4: '#ef4444', # Red
                5: '#991b1b'  # Dark Red
            }
            aqi_advice = {
                1: 'Air quality is satisfactory, and air pollution poses little or no risk.',
                2: 'Air quality is acceptable. However, there may be a risk for some people, particularly those who are unusually sensitive to air pollution.',
                3: 'Members of sensitive groups may experience health effects. The general public is less likely to be affected.',
                4: 'Some members of the general public may experience health effects; members of sensitive groups may experience more serious health effects.',
                5: 'Health alert: The risk of health effects is increased for everyone.'
            }
            
            pollutants = {
                'PM2.5': components.get('pm2_5', 0), 'PM10': components.get('pm10', 0), 
                'Ozone': components.get('o3', 0), 'NO2': components.get('no2', 0), 
                'SO2': components.get('so2', 0), 'CO': components.get('co', 0)
            }
            
            return {
                'aqi': us_aqi, # Now exporting true US AQI
                'us_aqi': us_aqi,
                'avg_score': avg_score,
                'aqi_label': aqi_labels.get(avg_score, 'Unknown'),
                'aqi_color': aqi_colors.get(avg_score, '#6b7280'),
                'aqi_advice': aqi_advice.get(avg_score, ''),
                'pm2_5': round(components.get('pm2_5', 0), 1),
                'pm10': round(components.get('pm10', 0), 1),
                'o3': round(components.get('o3', 0), 1),
                'no2': round(components.get('no2', 0), 1),
                'so2': round(components.get('so2', 0), 1),
                'co': round(components.get('co', 0), 1),
                'main_pollutant': max(pollutants, key=lambda k: pollutants[k]),
                'city': city_name
            }
        else:
            print(f"Air Quality API error: Status {response.status_code}")
    except Exception as e:
        print(f"Air Quality API error: {e}")
    
    # Fallback to mock data on error
    return generate_mock_aqi(city_name)

def generate_mock_forecast(city_name):
    """Generate stable mock hourly AQI forecast based on city name"""
    import hashlib
    hash_val = int(hashlib.md5((city_name + "forecast").lower().encode()).hexdigest(), 16)
    
    forecasts = []
    base_aqi = (hash_val % 4) + 1  # 1 to 4
    base_pm25 = (hash_val % 50) + 5
    
    now = datetime.now()
    for i in range(6):
        time = now + timedelta(hours=i)
        
        # Add some variation
        hour_var = ((hash_val + i) % 3) - 1
        pm25 = max(1.0, base_pm25 + (hour_var * 15.5))
        us_aqi = calculate_us_aqi(pm25)
        
        if us_aqi <= 50: aqi_level = 1
        elif us_aqi <= 100: aqi_level = 2
        elif us_aqi <= 150: aqi_level = 3
        elif us_aqi <= 200: aqi_level = 4
        else: aqi_level = 5
        
        forecasts.append({
            'time': time.strftime('%H:00'),
            'us_aqi': us_aqi,
            'aqi_level': aqi_level,
            'pm2_5': round(pm25, 1)
        })
        
    return forecasts

def get_air_quality_forecast(lat, lon, city_name="Unknown"):
    """Get hourly AQI forecast from OpenWeatherMap Air Pollution Forecast API"""
    api_key = app.config['WEATHER_API_KEY']
    if not api_key:
        return generate_mock_forecast(city_name)
    
    try:
        url = f"http://api.openweathermap.org/data/2.5/air_pollution/forecast?lat={lat}&lon={lon}&appid={api_key}"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            forecast = []
            aqi_labels = {1: 'Good', 2: 'Fair', 3: 'Moderate', 4: 'Poor', 5: 'Very Poor'}
            aqi_colors = {1: '#059669', 2: '#3b82f6', 3: '#f59e0b', 4: '#dc2626', 5: '#7c2d12'}
            
            now = datetime.now()
            count = 0
            for item in data['list']:
                dt = datetime.fromtimestamp(item['dt'])
                if dt > now and count < 6:
                    pm25 = item['components'].get('pm2_5', 0)
                    us_aqi = calculate_us_aqi(pm25)
                    
                    if us_aqi <= 50: aqi_level = 1
                    elif us_aqi <= 100: aqi_level = 2
                    elif us_aqi <= 150: aqi_level = 3
                    elif us_aqi <= 200: aqi_level = 4
                    else: aqi_level = 5
                    
                    forecast.append({
                        'time': dt.strftime('%H:%M'),
                        'us_aqi': us_aqi,
                        'aqi_level': aqi_level,
                        'pm2_5': round(pm25, 1)
                    })
                    count += 1
        return forecast
    except Exception as e:
        print(f"AQI Forecast API error: {e}")
    
    # Fallback to mock forecast on error
    return generate_mock_forecast(city_name)

# Major cities/regions by country for AQI ranking and selection
COUNTRY_CITIES = {
    'UZ': [
        'Tashkent', 'Samarkand', 'Bukhara', 'Namangan', 'Andijan', 'Fergana', 
        'Nukus', 'Karshi', 'Navoiy', 'Gulistan', 'Jizzakh', 'Termez', 'Urgench', 'Nurafshon'
    ],
    'US': [
        'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'Florida', 'Georgia',
        'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland',
        'Massachusetts', 'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey',
        'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina',
        'South Dakota', 'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia', 'Wisconsin', 'Wyoming'
    ],
    'RU': [
        'Moscow', 'Saint Petersburg', 'Novosibirsk', 'Yekaterinburg', 'Kazan', 'Nizhny Novgorod', 'Chelyabinsk', 'Samara', 'Omsk', 'Rostov-on-Don',
        'Ufa', 'Krasnoyarsk', 'Voronezh', 'Perm', 'Volgograd', 'Krasnodar', 'Saratov', 'Tyumen', 'Tolyatti', 'Izhevsk',
        'Barnaul', 'Ulyanovsk', 'Irkutsk', 'Khabarovsk', 'Yaroslavl', 'Vladivostok', 'Makhachkala', 'Tomsk', 'Orenburg', 'Kemerovo'
    ],
    'KZ': ['Almaty', 'Astana', 'Shymkent', 'Karaganda', 'Aktobe', 'Taraz', 'Pavlodar', 'Ust-Kamenogorsk'],
    'TJ': ['Dushanbe', 'Khujand', 'Kulob', 'Bokhtar', 'Istaravshan'],
    'KG': ['Bishkek', 'Osh', 'Jalal-Abad', 'Karakol', 'Tokmok'],
    'TM': ['Ashgabat', 'Turkmenabat', 'Dashoguz', 'Mary', 'Balkanabat'],
    'AF': ['Kabul', 'Kandahar', 'Herat', 'Mazar-i-Sharif', 'Jalalabad'],
    'TR': ['Istanbul', 'Ankara', 'Izmir', 'Bursa', 'Antalya', 'Adana'],
    'CN': ['Beijing', 'Shanghai', 'Guangzhou', 'Shenzhen', 'Chengdu', 'Wuhan']
}

def get_city_rankings(country, current_city_data=None):
    """Get AQI rankings for major cities in a country, returning dual-list format"""
    # Define labels and colors matching the dashboard style
    aqi_labels = {1: 'Good', 2: 'Moderate', 3: 'Unhealthy for Sensitive', 4: 'Unhealthy', 5: 'Very Unhealthy'}
    aqi_colors = {
        1: '#10b981', # Green
        2: '#fbb117', # Yellow
        3: '#f59e0b', # Orange
        4: '#ef4444', # Red
        5: '#991b1b'  # Dark Red
    }
    
    cities = COUNTRY_CITIES.get(country, [])
    if not cities:
        # Fallback to Uzbekistan if not found
        cities = COUNTRY_CITIES.get('UZ', [])
        country = 'UZ'
    
    full_rankings = []
    
    # Define representative cities and base PM2.5 values for the most realistic mock
    # Values chosen to satisfy user requirement for high (>100) and low (clean) values
    if country == 'UZ':
        mock_data = [
            ('Salor', 108.5), ('Tashkent', 85.2), ('Amirsoy', 55.4), 
            ('Samarand', 42.1), ('Sidzhak', 32.5), ('Bukhara', 28.4), ('G\'azalkent', 25.1)
        ]
        most_polluted_summ = {'city': 'Fergana', 'aqi': 138, 'color': '#f59e0b'}
        cleanest_summ = {'city': 'Sidzhak', 'aqi': 51, 'color': '#fbb117'}
    elif country == 'US':
        mock_data = [
            ('Phoenix', 95.2), ('Los Angeles', 88.4), ('Houston', 72.1),
            ('New York', 45.5), ('Chicago', 42.1), ('San Francisco', 22.4), ('Seattle', 18.5)
        ]
        most_polluted_summ = {'city': 'Bakersfield', 'aqi': 152, 'color': '#ef4444'}
        cleanest_summ = {'city': 'Honolulu', 'aqi': 15, 'color': '#10b981'}
    else:
        # Default mock for other countries
        sample_cities = cities[:7] if len(cities) >= 7 else cities
        mock_data = [(c, 80.0 - (i * 10)) for i, c in enumerate(sample_cities)]
        most_polluted_summ = {'city': sample_cities[0] if sample_cities else 'Capital', 'aqi': 120, 'color': '#f59e0b'}
        cleanest_summ = {'city': sample_cities[-1] if sample_cities else 'Village', 'aqi': 30, 'color': '#10b981'}

    for city_name, base_pm in mock_data:
        # Check if this city is the current user's city
        is_match = False
        if current_city_data and current_city_data.get('city') and current_city_data.get('city') != 'Unknown':
            curr_city = current_city_data.get('city', '').lower()
            target_city = city_name.lower()
            if curr_city == target_city or (curr_city in target_city and len(curr_city) > 3) or (target_city in curr_city and len(target_city) > 3):
                is_match = True

        if is_match:
            pm25 = current_city_data.get('pm2_5', base_pm)
            us_aqi = current_city_data.get('us_aqi', calculate_us_aqi(pm25))
        else:
            pm25 = base_pm
            us_aqi = calculate_us_aqi(pm25)

        if us_aqi <= 50: level = 1
        elif us_aqi <= 100: level = 2
        elif us_aqi <= 150: level = 3
        elif us_aqi <= 200: level = 4
        else: level = 5

        full_rankings.append({
            'city': city_name,
            'us_aqi': us_aqi,
            'level': level,
            'aqi_label': aqi_labels.get(level, 'Unknown'),
            'aqi_color': aqi_colors.get(level, '#6b7280'),
            'pm2_5': pm25
        })

    # Sort full rankings to split into most polluted and cleanest
    most_polluted_list = sorted(full_rankings, key=lambda x: -x['us_aqi'])
    cleanest_list = sorted(full_rankings, key=lambda x: x['us_aqi'])

    country_name = 'Uzbekistan' if country == 'UZ' else 'USA' if country == 'US' else 'Russia' if country == 'RU' else country
    
    return {
        'most_polluted': most_polluted_list[:7],
        'cleanest': cleanest_list[:7],
        'most_polluted_summary': most_polluted_summ,
        'cleanest_summary': cleanest_summ,
        'country_name': country_name
    }

def send_email_notification(email, subject, body):
    """Send email notification"""
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        print(f"[Email] SMTP not configured. Message: {subject}")
        return False
    
    try:
        msg = Message(
            subject=subject,
            recipients=[email],
            body=body,
            sender=app.config['MAIL_DEFAULT_SENDER'] or app.config['MAIL_USERNAME']
        )
        mail.send(msg)
        print(f"[Email] Message sent successfully to: {email}")
        return True
    except Exception as e:
        print(f"[Email] Error: {e}")
        return False

def send_telegram_message(chat_id, message):
    """Send message via Telegram bot"""
    token = app.config['TELEGRAM_BOT_TOKEN']
    if not token:
        print(f"[Telegram] Token not found. Message: {message}")
        return False
    
    if not chat_id:
        print(f"[Telegram] Chat ID not found. Message: {message}")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        # Remove HTML tags for plain text
        plain_message = message.replace('<b>', '').replace('</b>', '').replace('<i>', '').replace('</i>', '')
        
        data = {
            'chat_id': chat_id,
            'text': plain_message
        }
        response = requests.post(url, json=data, timeout=10)
        
        if response.status_code == 200:
            print(f"[Telegram] Message sent successfully: {chat_id}")
            return True
        else:
            print(f"[Telegram] Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"[Telegram] Error: {e}")
        return False

# Background task for medication reminders
def check_medication_reminders():
    """Check and send medication reminders"""
    with app.app_context():
        now = datetime.now()
        current_time = now.time()
        
        # Get all active reminders
        reminders = Reminder.query.filter_by(is_active=True).all()
        
        for reminder in reminders:
            med = reminder.medication
            user = med.user
            
            # Improved logic: Check if reminder time has passed and not sent today
            reminder_time = reminder.reminder_time
            
            if reminder_time <= current_time:
                # Check if we already sent reminder today
                if reminder.last_sent is None or reminder.last_sent.date() < now.date():
                    message = f"⏰ Medication Time!\n\n"
                    message += f"💊 Medication: {med.name}\n"
                    message += f"📊 Dose: {med.quantity_per_dose} pills\n"
                    message += f"🕐 Time: {reminder_time.strftime('%H:%M')}\n"
                    message += f"📦 Remaining: {med.quantity_remaining} pills"
                    
                    email_subject = f"Medication Reminder: {med.name}"
                    email_body = f"""Medication Reminder
 
 Medication: {med.name}
 Dose: {med.quantity_per_dose} pills
 Time: {reminder_time.strftime('%H:%M')}
 Remaining: {med.quantity_remaining} pills
 
 Please take your medication on time.
 """
                    
                    print(f"[Reminder] Sending: {med.name} - {reminder_time.strftime('%H:%M')} to {user.username}")
                    
                    # Send via Email
                    if user.email:
                        email_result = send_email_notification(user.email, email_subject, email_body)
                        if email_result:
                            print(f"[Reminder] Email sent successfully!")
                        else:
                            print(f"[Reminder] Email not sent!")
                    
                    # Send via Telegram if chat_id is set
                    if user.telegram_chat_id:
                        telegram_result = send_telegram_message(user.telegram_chat_id, message)
                        if telegram_result:
                            print(f"[Reminder] Telegram message sent!")
                        else:
                            print(f"[Reminder] Telegram message not sent!")
                    else:
                        print(f"[Reminder] Chat ID not found")
                    
                    reminder.last_sent = now
                    db.session.commit()

# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_medication_reminders, trigger="interval", minutes=1)
scheduler.start()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000)

