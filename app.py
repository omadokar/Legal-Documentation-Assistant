from flask import Flask, request, render_template, jsonify, send_file
import os
import pdfplumber
import docx
from googletrans import Translator
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from textwrap import wrap
import mysql.connector
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics

# ✅ Initialize Flask App
app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ✅ Database Configuration
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "omadokar",
    "database": "legal_assistant"
}

def connect_db():
    return mysql.connector.connect(**DB_CONFIG)

# ✅ Register Unicode Font
FONT_PATH_HINDI = "fonts/Amiko-Regular.ttf"
FONT_PATH_MARATHI = "fonts/AGRAB.TTF"
FONT_PATH_ENGLISH = "fonts/DejaVuSans.ttf"

# ✅ Register Fonts
pdfmetrics.registerFont(TTFont("HindiFont", FONT_PATH_HINDI))
pdfmetrics.registerFont(TTFont("MarathiFont", FONT_PATH_MARATHI))
pdfmetrics.registerFont(TTFont("EnglishFont", FONT_PATH_ENGLISH))


@app.route("/")
def index():
    return render_template("index.html")

# ✅ File Upload and Text Extraction
@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    
    file = request.files["file"]
    filename = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filename)
    
    text = extract_text(filename)
    
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO documents (filename, file_path, extracted_text) VALUES (%s, %s, %s)", 
                   (file.filename, filename, text))
    conn.commit()
    document_id = cursor.lastrowid
    conn.close()

    return jsonify({"text": text, "document_id": document_id})

# ✅ Extract Text from PDF/DOCX
def extract_text(filename):
    if filename.endswith(".pdf"):
        with pdfplumber.open(filename) as pdf:
            return "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
    elif filename.endswith(".docx"):
        doc = docx.Document(filename)
        return "\n".join([para.text for para in doc.paragraphs])
    return ""

# ✅ Check if Document is Legal
@app.route("/check_legal", methods=["POST"])
def check_legal():
    data = request.json
    document_id = data.get("document_id")
    text = data.get("text")
    
    legal_keywords = ["WHEREAS", "IN WITNESS WHEREOF", "THIS AGREEMENT"]
    is_legal = any(keyword in text for keyword in legal_keywords)

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE documents SET is_legal = %s WHERE id = %s", (is_legal, document_id))
    conn.commit()
    conn.close()

    return jsonify({"is_legal": is_legal})

# ✅ Summarize Document
@app.route("/summarize", methods=["POST"])
def summarize_text():
    data = request.json
    document_id = data.get("document_id")
    text = data.get("text")
    
    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    summarizer = LsaSummarizer()
    summary = " ".join(str(sentence) for sentence in summarizer(parser.document, 3))

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE documents SET summary = %s WHERE id = %s", (summary, document_id))
    conn.commit()
    conn.close()

    return jsonify({"summary": summary})

# ✅ Translate Document
@app.route("/translate", methods=["POST"])
def translate_text():
    data = request.json
    document_id = data.get("document_id")
    text, target_lang = data.get("text"), data.get("lang")
    
    translator = Translator()
    translated = translator.translate(text, dest=target_lang).text

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE documents SET translated_text = %s WHERE id = %s", (translated, document_id))
    conn.commit()
    conn.close()

    return jsonify({"translated_text": translated})

# ✅ Generate PDF from Text
@app.route("/generate_document", methods=["POST"])
def generate_document():
    data = request.json
    document_id = data.get("document_id")
    content = data.get("text")
    
    pdf_path = generate_pdf(content, document_id)

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE documents SET generated_document = %s WHERE id = %s", (pdf_path, document_id))
    conn.commit()
    conn.close()

    return jsonify({"File": "Downloaded Successfully."})

# ✅ Generate PDF with Proper Formatting
def generate_pdf(content, document_id):
    pdf_path = os.path.join(UPLOAD_FOLDER, f"generated_{document_id}.pdf")
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.setFont("DejaVu", 12)

    text = content.strip()
    lines = wrap(text, width=80)

    y_position = 750
    for line in lines:
        c.drawString(50, y_position, line)
        y_position -= 20  

    c.save()
    return pdf_path

# ✅ Download Generated PDF
@app.route("/download/<int:document_id>", methods=["GET"])
def download_document(document_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT generated_document FROM documents WHERE id = %s", (document_id,))
    result = cursor.fetchone()
    conn.close()

    if result and result[0]:
        return send_file(result[0], as_attachment=True)
    return jsonify({"File": "Downloaded Successfully."})

# ✅ Download Translated PDF

@app.route("/download_translated/<int:document_id>", methods=["GET"])
def download_translated(document_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT translated_text FROM documents WHERE id = %s", (document_id,))
    result = cursor.fetchone()
    conn.close()

    if result and result[0]:
        translated_text = result[0]
        pdf_path = os.path.join(UPLOAD_FOLDER, f"translated_{document_id}.pdf")
        c = canvas.Canvas(pdf_path, pagesize=letter)

        # Detect language and choose the right font

        # Wrap text properly
        lines = wrap(translated_text, width=80)
        y = 750  
        for line in lines:
            c.drawString(50, y, line)
            y -= 20  

        c.save()
        return send_file(pdf_path, as_attachment=True)

    return jsonify({"error": "Translated text not found"}), 404


if __name__ == "__main__":
    app.run(debug=True)
