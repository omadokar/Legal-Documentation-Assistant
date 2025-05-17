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
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from textwrap import wrap
from pymongo import MongoClient
from bson.objectid import ObjectId

# ✅ Initialize Flask App
app = Flask(__name__)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ✅ MongoDB Configuration
client = MongoClient("mongodb+srv://omadokar2003:omadokar@cluster0.mongodb.net/legal_assistant?retryWrites=true&w=majority")
db = client["legal_assistant"]
documents_collection = db["documents"]

# ✅ Register Unicode Fonts
FONT_PATH_HINDI = "fonts/Amiko-Regular.ttf"
FONT_PATH_MARATHI = "fonts/AGRAB.TTF"
FONT_PATH_ENGLISH = "fonts/DejaVuSans.ttf"

pdfmetrics.registerFont(TTFont("HindiFont", FONT_PATH_HINDI))
pdfmetrics.registerFont(TTFont("MarathiFont", FONT_PATH_MARATHI))
pdfmetrics.registerFont(TTFont("EnglishFont", FONT_PATH_ENGLISH))


@app.route("/")
def index():
    return render_template("index.html")


# ✅ Upload File and Extract Text
@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    filename = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filename)

    text = extract_text(filename)

    document = {
        "filename": file.filename,
        "file_path": filename,
        "extracted_text": text,
        "is_legal": None,
        "summary": None,
        "translated_text": None,
        "generated_document": None
    }
    result = documents_collection.insert_one(document)
    document_id = str(result.inserted_id)

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

    documents_collection.update_one(
        {"_id": ObjectId(document_id)},
        {"$set": {"is_legal": is_legal}}
    )

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

    documents_collection.update_one(
        {"_id": ObjectId(document_id)},
        {"$set": {"summary": summary}}
    )

    return jsonify({"summary": summary})


# ✅ Translate Document
@app.route("/translate", methods=["POST"])
def translate_text():
    data = request.json
    document_id = data.get("document_id")
    text = data.get("text")
    target_lang = data.get("lang")

    translator = Translator()
    translated = translator.translate(text, dest=target_lang).text

    documents_collection.update_one(
        {"_id": ObjectId(document_id)},
        {"$set": {"translated_text": translated}}
    )

    return jsonify({"translated_text": translated})


# ✅ Generate PDF from Text
@app.route("/generate_document", methods=["POST"])
def generate_document():
    data = request.json
    document_id = data.get("document_id")
    content = data.get("text")

    pdf_path = generate_pdf(content, document_id)

    documents_collection.update_one(
        {"_id": ObjectId(document_id)},
        {"$set": {"generated_document": pdf_path}}
    )

    return jsonify({"File": "Downloaded Successfully."})


# ✅ Generate PDF with Proper Formatting
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


# ✅ Download Generated PDF
@app.route("/download/<string:document_id>", methods=["GET"])
def download_document(document_id):
    doc = documents_collection.find_one({"_id": ObjectId(document_id)})
    if doc and doc.get("generated_document"):
        return send_file(doc["generated_document"], as_attachment=True)
    return jsonify({"error": "Generated document not found"}), 404


# ✅ Download Translated PDF
@app.route("/download_translated/<string:document_id>", methods=["GET"])
def download_translated(document_id):
    doc = documents_collection.find_one({"_id": ObjectId(document_id)})
    if doc and doc.get("translated_text"):
        translated_text = doc["translated_text"]
        pdf_path = os.path.join(UPLOAD_FOLDER, f"translated_{document_id}.pdf")
        c = canvas.Canvas(pdf_path, pagesize=letter)

        # You can add font logic based on language here if needed
        c.setFont("EnglishFont", 12)

        lines = wrap(translated_text, width=80)
        y = 750
        for line in lines:
            c.drawString(50, y, line)
            y -= 20

        c.save()
        return send_file(pdf_path, as_attachment=True)

    return jsonify({"error": "Translated text not found"}), 404


# ✅ Run Flask App
if __name__ == "__main__":
    app.run(debug=True)
