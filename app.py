from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
import re
import fitz  # PyMuPDF
from docx import Document
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

app.secret_key = 'your-secret-key'
app.config['UPLOAD_FOLDER'] = 'uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'pdf', 'docx'}



def extract_user_info(text):
    user_info = {
        'full_name': '',
        'first_name': '',
        'middle_name': '',
        'last_name': '',
        'email': 'Not found',
        'phone': 'Not found'
    }

    phone_match = re.search(r'(\+91[\s\-]?[6-9]\d{9})', text)
    if phone_match:
        user_info['phone'] = phone_match.group(1)

    email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
    if email_match:
        user_info['email'] = email_match.group(0)

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


def extract_text_from_pdf(file_path):
    text = ""
    doc = fitz.open(file_path)
    for page in doc:
        text += page.get_text()
    return text

def extract_text_from_docx(file_path):
    doc = Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])

def extract_resume_text(file_path):
    if file_path.endswith('.pdf'):
        return extract_text_from_pdf(file_path)
    elif file_path.endswith('.docx'):
        return extract_text_from_docx(file_path)
    return ""

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
        matched = sum(1 for subs in requirements.values() for kw in subs if kw.lower() in resume_text.lower())
    else:
        total_keywords = len(requirements)
        matched = sum(1 for kw in requirements if kw.lower() in resume_text.lower())
    if total_keywords == 0:
        return 0
    return round((matched / total_keywords) * 10, 1)

@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'resume' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['resume']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF/DOCX allowed'}), 400

resume_text = extract_resume_text(file_path)
user_info = extract_user_info(resume_text)


    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    try:
        with open('requirements.json') as f:
            data = json.load(f)
            requirements = data.get('requirements', {})
            search_mode = data.get('search_mode', 'section')
            threshold = data.get('threshold', 6)
    except Exception:
        return jsonify({'error': 'Requirements load failed'}), 500

    resume_text = extract_resume_text(file_path)
    structure_score = evaluate_resume_structure(file_path)
    content_score = calculate_score(resume_text, requirements, search_mode)
    final_score = round(content_score * 0.7 + structure_score * 0.3, 1)

    candidate_data = {
        **user_info,
        'content_score': content_score,
        'structure_score': structure_score,
        'final_score': final_score,
        'threshold': threshold,
        'status': 'PASS' if final_score >= threshold else 'FAIL',
        'resume_filename': filename
    }

    # Save to candidates.json
    if os.path.exists('candidates.json'):
        with open('candidates.json', 'r') as f:
            all_candidates = json.load(f)
    else:
        all_candidates = []

    all_candidates.append(candidate_data)
    with open('candidates.json', 'w') as f:
        json.dump(all_candidates, f, indent=4)

    return jsonify(candidate_data)

@app.route('/api/candidates', methods=['GET'])
def api_candidates():
    try:
        with open('candidates.json', 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify([])

@app.route('/api/delete_candidate', methods=['POST'])
def delete_candidate():
    try:
        req = request.get_json()
        email = req.get('email')
        phone = req.get('phone')

        with open('candidates.json', 'r') as f:
            data = json.load(f)

        new_data = [d for d in data if not (d['email'] == email and d['phone'] == phone)]

        with open('candidates.json', 'w') as f:
            json.dump(new_data, f, indent=4)

        return jsonify({'message': 'Candidate deleted'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
            with open('requirements.json', 'w') as f:
                json.dump(data, f, indent=4)
            return jsonify({'message': 'Requirements updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
