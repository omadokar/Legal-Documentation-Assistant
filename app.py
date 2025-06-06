from flask import Flask, request, render_template, jsonify, send_file
import os
import pdfplumber
import docx
from deep_translator import GoogleTranslator
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.lsa import LsaSummarizer
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from sumy.parsers.plaintext import PlaintextParser
from nltk.tokenize import sent_tokenize
from sumy.nlp.stemmers import Stemmer
from sumy.summarizers.lsa import LsaSummarizer
from sumy.utils import get_stop_words
from textwrap import wrap
import firebase_admin
from firebase_admin import credentials, firestore

# Initialize Flask App

app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize Firebase Admin
cred = credentials.Certificate("translator-d67f1-firebase-adminsdk-fbsvc-3d0c0c79d8.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Register Fonts
FONT_PATH_HINDI = "fonts/Amiko-Regular.ttf"
FONT_PATH_MARATHI = "fonts/AGRAB.TTF"
FONT_PATH_ENGLISH = "fonts/DejaVuSans.ttf"

pdfmetrics.registerFont(TTFont("HindiFont", FONT_PATH_HINDI))
pdfmetrics.registerFont(TTFont("MarathiFont", FONT_PATH_MARATHI))
pdfmetrics.registerFont(TTFont("EnglishFont", FONT_PATH_ENGLISH))

LANGUAGE = "english"
SENTENCES_COUNT = 3
def summarize_text_with_nltk(text):
    # Use nltk.sent_tokenize to split sentences
    sentences = sent_tokenize(text)
    # Create a PlaintextParser manually with pre-tokenized sentences
    parser = PlaintextParser.from_sentences(sentences, Stemmer(LANGUAGE))
    summarizer = LsaSummarizer(Stemmer(LANGUAGE))
    summarizer.stop_words = get_stop_words(LANGUAGE)

    summary = summarizer(parser.document, SENTENCES_COUNT)
    return " ".join(str(sentence) for sentence in summary)
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    filename = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filename)

    text = extract_text(filename)

    doc_ref = db.collection("documents").add({
        "filename": file.filename,
        "file_path": filename,
        "extracted_text": text,
        "is_legal": None,
        "summary": None,
        "translated_text": None,
        "generated_document": None
    })
    document_id = doc_ref[1].id

    return jsonify({"text": text, "document_id": document_id})

def extract_text(filename):
    if filename.endswith(".pdf"):
        with pdfplumber.open(filename) as pdf:
            return "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
    elif filename.endswith(".docx"):
        doc = docx.Document(filename)
        return "\n".join([para.text for para in doc.paragraphs])
    return ""

@app.route("/check_legal", methods=["POST"])
def check_legal():
    data = request.json
    document_id = data.get("document_id")
    text = data.get("text")

    legal_keywords = ["WHEREAS", "IN WITNESS WHEREOF", "THIS AGREEMENT"]
    is_legal = any(keyword in text for keyword in legal_keywords)

    db.collection("documents").document(document_id).update({"is_legal": is_legal})
    return jsonify({"is_legal": is_legal})

@app.route("/summarize", methods=["POST"])
def summarize_text():
    data = request.json
    document_id = data.get("document_id")
    text = data.get("text")

    if not text or text.strip() == "":
        return jsonify({"error": "Empty text received for summarization"}), 400

    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    sentence_count = len(parser.document.sentences)
    print(f"Number of sentences parsed: {sentence_count}")

    if sentence_count == 0:
        return jsonify({"error": "No sentences found to summarize"}), 400

    summarizer = LsaSummarizer()
    summary_sentences = summarizer(parser.document, min(3, sentence_count))  # Summarize max 3 or less
    summary = " ".join(str(sentence) for sentence in summary_sentences)

    # Save summary in Firestore
    db.collection("documents").document(document_id).update({"summary": summary})

    return jsonify({"summary": summary})

@app.route("/translate", methods=["POST"])
def translate_text():
    data = request.json
    document_id = data.get("document_id")
    text = data.get("text")
    target_lang = data.get("lang")

    translated = GoogleTranslator(source='auto', target=target_lang).translate(text)

    db.collection("documents").document(document_id).update({"translated_text": translated})
    return jsonify({"translated_text": translated})

@app.route("/generate_document", methods=["POST"])
def generate_document():
    data = request.json
    document_id = data.get("document_id")
    content = data.get("text")

    pdf_path = generate_pdf(content, document_id)

    db.collection("documents").document(document_id).update({"generated_document": pdf_path})
    return jsonify({"File": "Downloaded Successfully."})

def generate_pdf(content, document_id):
    pdf_path = os.path.join(UPLOAD_FOLDER, f"generated_{document_id}.pdf")
    c = canvas.Canvas(pdf_path, pagesize=letter)
    c.setFont("EnglishFont", 12)

    text = content.strip()
    lines = wrap(text, width=80)

    y_position = 750
    for line in lines:
        c.drawString(50, y_position, line)
        y_position -= 20

    c.save()
    return pdf_path

@app.route("/download/<string:document_id>", methods=["GET"])
def download_document(document_id):
    doc = db.collection("documents").document(document_id).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("generated_document"):
            return send_file(data["generated_document"], as_attachment=True)
    return jsonify({"error": "Generated document not found"}), 404

@app.route("/download_translated/<string:document_id>", methods=["GET"])
def download_translated(document_id):
    doc = db.collection("documents").document(document_id).get()
    if doc.exists:
        data = doc.to_dict()
        if data.get("translated_text"):
            translated_text = data["translated_text"]
            pdf_path = os.path.join(UPLOAD_FOLDER, f"translated_{document_id}.pdf")
            c = canvas.Canvas(pdf_path, pagesize=letter)
            c.setFont("EnglishFont", 12)
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
