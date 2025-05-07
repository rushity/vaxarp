from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import os
import json
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.mime.text import MIMEText
from flask_cors import CORS
from docx import Document
from PyPDF2 import PdfReader

app = Flask(__name__)
CORS(app)

app.secret_key = 'your-secret-key'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['HR_EMAIL'] = 'firegg0711@gmail.com'
app.config['SENDER_EMAIL'] = 'rushityadav06@gmail.com'
app.config['EMAIL_PASSWORD'] = 'aelm gfiq vtjz ozfr'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf', 'docx'}

def extract_text_from_pdf(file_path):
    text = ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            if page.extract_text():
                text += page.extract_text()
    except Exception as e:
        print("PDF read error:", e)
    return text

def extract_text_from_docx(file_path):
    try:
        doc = Document(file_path)
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        print("DOCX read error:", e)
        return ""

def extract_resume_text(file_path):
    if file_path.endswith('.pdf'):
        return extract_text_from_pdf(file_path)
    elif file_path.endswith('.docx'):
        return extract_text_from_docx(file_path)
    return ""

def extract_user_info(text):
    user_info = {
        'full_name': '',
        'first_name': '',
        'middle_name': '',
        'last_name': '',
        'email': 'Not found',
        'phone': 'Not found'
    }

    # Extract phone
    phone_match = re.search(r'(\+91[\s\-]?[6-9]\d{9})', text)
    if phone_match:
        user_info['phone'] = phone_match.group(1)

    # Extract email
    email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
    if email_match:
        user_info['email'] = email_match.group(0)

    # Extract name from first clean text line
    for line in text.strip().split('\n'):
        if line.strip() and '@' not in line and not re.search(r'\d', line):
            user_info['full_name'] = line.strip()
            parts = line.strip().split()
            if len(parts) == 3:
                user_info['first_name'] = parts[0]
                user_info['middle_name'] = parts[1]
                user_info['last_name'] = parts[2]
            elif len(parts) == 2:
                user_info['first_name'] = parts[0]
                user_info['last_name'] = parts[1]
            elif len(parts) == 1:
                user_info['first_name'] = parts[0]
            break

    return user_info

def evaluate_resume_structure(file_path):
    text = extract_resume_text(file_path)
    score = 3
    sections = ['skills', 'experience', 'education', 'projects', 'summary']
    score += min(3, sum(1 for s in sections if s in text.lower()))
    if 300 <= len(text.split()) <= 1000:
        score += 1
    if file_path.endswith('.pdf') and "•" in text:
        score += 1
    return min(10, max(1, score))

def calculate_score(resume_text, requirements, search_mode):
    if search_mode == "section":
        total_keywords = sum(len(subs) for subs in requirements.values())
        if total_keywords == 0:
            return 0
        matched = sum(1 for subs in requirements.values() for kw in subs if kw.lower() in resume_text.lower())
    else:
        total_keywords = len(requirements)
        if total_keywords == 0:
            return 0
        matched = sum(1 for kw in requirements if kw.lower() in resume_text.lower())
    return round((matched / total_keywords) * 10, 1)

def send_email(file_path, content_score, structure_score, final_score, threshold, user_info):
    msg = MIMEMultipart()
    msg['From'] = app.config['SENDER_EMAIL']
    msg['To'] = app.config['HR_EMAIL']
    msg['Subject'] = f"Resume Evaluation: {final_score}/10"

    body = f"""Candidate Information:
Full Name: {user_info.get('full_name')}
First Name: {user_info.get('first_name')}
Middle Name: {user_info.get('middle_name')}
Last Name: {user_info.get('last_name')}
Email: {user_info.get('email')}
Phone: {user_info.get('phone')}

Evaluation Results:
Content Score: {content_score}/10
Structure Score: {structure_score}/10
Final Score: {final_score}/10
Threshold: {threshold}/10
Status: {'PASS' if final_score >= threshold else 'FAIL'}
"""
    msg.attach(MIMEText(body, 'plain'))

    with open(file_path, 'rb') as f:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(app.config['SENDER_EMAIL'], app.config['EMAIL_PASSWORD'])
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'resume' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['resume']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF/DOCX allowed'}), 400

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    resume_text = extract_resume_text(file_path)
    if not resume_text.strip():
        return jsonify({'error': 'Could not extract text from resume'}), 400

    user_info = extract_user_info(resume_text)

    try:
        with open('requirements.json') as f:
            data = json.load(f)
            requirements = data.get('requirements', {})
            search_mode = data.get('search_mode', 'section')
            threshold = data.get('threshold', 6)
    except Exception as e:
        return jsonify({'error': 'Requirements load failed'}), 500

    structure_score = evaluate_resume_structure(file_path)
    content_score = calculate_score(resume_text, requirements, search_mode)
    final_score = round(content_score * 0.7 + structure_score * 0.3, 1)

    if final_score >= threshold:
        send_email(file_path, content_score, structure_score, final_score, threshold, user_info)

    return jsonify({
        'user_info': user_info,
        'content_score': content_score,
        'structure_score': structure_score,
        'final_score': final_score,
        'status': 'PASS' if final_score >= threshold else 'FAIL'
    })


@app.route('/api/requirements', methods=['GET', 'POST'])
def api_requirements():
    try:
        if request.method == 'GET':
            with open('requirements.json', 'r') as f:
                return jsonify(json.load(f))
        elif request.method == 'POST':
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No data provided'}), 400

            # Overwrite file safely
            with open('requirements.json', 'w') as f:
                json.dump(data, f, indent=4)
            return jsonify({'message': 'Requirements updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500




if __name__ == '__main__':
    app.run(debug=True)
