import os
import csv
import json
import time
import smtplib
from datetime import datetime
from email.message import EmailMessage

import pandas as pd
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    send_file
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv


# =========================================================
# CONFIGURATION
# =========================================================

load_dotenv()

app = Flask(__name__)

app.secret_key = "emailpro-secret-key-change-this"

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ATTACHMENT_FOLDER = os.path.join(BASE_DIR, "attachments")
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed")
REPORT_FOLDER = os.path.join(BASE_DIR, "reports")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ATTACHMENT_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(REPORT_FOLDER, exist_ok=True)


ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".doc",
    ".docx"
}


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def allowed_attachment(filename):
    if not filename:
        return False

    extension = os.path.splitext(filename)[1].lower()

    return extension in ALLOWED_ATTACHMENT_EXTENSIONS


def find_email_column(df):
    possible_columns = [
        "email",
        "emails",
        "email_address",
        "email address",
        "mail",
        "recipient",
        "recipient_email"
    ]

    for column in df.columns:
        cleaned = str(column).strip().lower()

        if cleaned in possible_columns:
            return column

    return None


def read_recipient_csv():

    possible_files = [
        os.path.join(PROCESSED_FOLDER, "classified_emails.csv"),
        os.path.join(PROCESSED_FOLDER, "cleaned_emails.csv"),
        os.path.join(UPLOAD_FOLDER, "emails.csv")
    ]

    selected_file = None

    for file in possible_files:
        if os.path.exists(file):
            selected_file = file
            break

    if not selected_file:
        return []

    try:
        df = pd.read_csv(selected_file)

        email_column = find_email_column(df)

        if email_column is None:
            return []

        recipients = []

        for _, row in df.iterrows():

            email = str(row[email_column]).strip()

            if not email or email.lower() == "nan":
                continue

            category = "Unknown"

            # Try to detect classification column
            for column in df.columns:

                column_name = str(column).strip().lower()

                if column_name in [
                    "category",
                    "classification",
                    "type",
                    "class"
                ]:
                    value = str(row[column]).strip()

                    if value and value.lower() != "nan":
                        category = value

            recipients.append({
                "email": email,
                "category": category
            })

        return recipients

    except Exception as e:

        print("CSV reading error:", e)

        return []


def filter_recipients(audience):

    recipients = read_recipient_csv()

    audience = str(audience).strip().lower()

    if audience == "individual recipients":

        return [
            r for r in recipients
            if r["category"].lower() == "individual"
        ]

    if audience == "business recipients":

        return [
            r for r in recipients
            if r["category"].lower() == "business"
        ]

    return recipients


def save_report(results):

    report_path = os.path.join(
        REPORT_FOLDER,
        "campaign_report.csv"
    )

    with open(
        report_path,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.writer(file)

        writer.writerow([
            "emails",
            "status"
        ])

        for result in results:

            writer.writerow([
                result["email"],
                result["status"]
            ])

    return report_path


def save_report_json(results, subject, audience, attachment):

    json_path = os.path.join(
        REPORT_FOLDER,
        "campaign_data.json"
    )

    data = {
        "subject": subject,
        "audience": audience,
        "attachment": attachment,
        "date": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "results": results
    }

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=4
        )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def index():

    recipients = read_recipient_csv()

    business_count = sum(
        1
        for r in recipients
        if r["category"].lower() == "business"
    )

    individual_count = sum(
        1
        for r in recipients
        if r["category"].lower() == "individual"
    )

    unknown_count = sum(
        1
        for r in recipients
        if r["category"].lower() == "unknown"
    )

    total_count = len(recipients)

    return render_template(
        "index.html",
        business_count=business_count,
        individual_count=individual_count,
        unknown_count=unknown_count,
        total_count=total_count
    )


# =========================================================
# UPLOAD
# =========================================================

@app.route("/upload", methods=["GET", "POST"])
def upload():

    if request.method == "POST":

        file = request.files.get("file")

        if not file or file.filename == "":

            flash(
                "Please select a CSV file.",
                "error"
            )

            return redirect(
                url_for("upload")
            )

        if not file.filename.lower().endswith(".csv"):

            flash(
                "Only CSV files are allowed.",
                "error"
            )

            return redirect(
                url_for("upload")
            )

        filename = secure_filename(
            file.filename
        )

        # Always save as emails.csv
        # after removing old version
        destination = os.path.join(
            UPLOAD_FOLDER,
            "emails.csv"
        )

        try:

            file.save(destination)

        except PermissionError:

            flash(
                "The CSV file is being used by another program. "
                "Close it in Excel and try again.",
                "error"
            )

            return redirect(
                url_for("upload")
            )

        # Remove old processed files
        for old_file in [
            "cleaned_emails.csv",
            "classified_emails.csv"
        ]:

            old_path = os.path.join(
                PROCESSED_FOLDER,
                old_file
            )

            if os.path.exists(old_path):

                try:
                    os.remove(old_path)

                except PermissionError:
                    pass

        flash(
            "CSV uploaded successfully.",
            "success"
        )

        return redirect(
            url_for("classify")
        )

    return render_template(
        "uploads.html"
    )


# =========================================================
# CLASSIFY PAGE
# =========================================================

@app.route("/classify")
def classify():

    recipients = read_recipient_csv()

    business_count = sum(
        1
        for r in recipients
        if r["category"].lower() == "business"
    )

    individual_count = sum(
        1
        for r in recipients
        if r["category"].lower() == "individual"
    )

    return render_template(
        "classify.html",
        business_count=business_count,
        individual_count=individual_count,
        total_count=len(recipients)
    )


# =========================================================
# RUN CLASSIFICATION
# =========================================================

@app.route("/run-classification", methods=["POST"])
def run_classification():

    source = os.path.join(
        UPLOAD_FOLDER,
        "emails.csv"
    )

    destination = os.path.join(
        PROCESSED_FOLDER,
        "classified_emails.csv"
    )

    if not os.path.exists(source):

        flash(
            "Please upload a CSV file first.",
            "error"
        )

        return redirect(
            url_for("upload")
        )

    try:

        df = pd.read_csv(source)

        email_column = find_email_column(df)

        if email_column is None:

            flash(
                "No email column found in CSV.",
                "error"
            )

            return redirect(
                url_for("upload")
            )

        # Remove empty emails
        df[email_column] = (
            df[email_column]
            .astype(str)
            .str.strip()
        )

        df = df[
            (df[email_column] != "") &
            (df[email_column].str.lower() != "nan")
        ]

        # Remove duplicates
        df = df.drop_duplicates(
            subset=[email_column]
        )

        # Classification
        def classify_email(email):

            email = str(email).lower()

            personal_domains = [
                "gmail.com",
                "yahoo.com",
                "outlook.com",
                "hotmail.com",
                "rediffmail.com",
                "icloud.com"
            ]

            domain = email.split("@")[-1]

            if domain in personal_domains:
                return "Individual"

            return "Business"

        df["category"] = df[
            email_column
        ].apply(classify_email)

        df.to_csv(
            destination,
            index=False
        )

        # Also save cleaned CSV
        cleaned_path = os.path.join(
            PROCESSED_FOLDER,
            "cleaned_emails.csv"
        )

        df.to_csv(
            cleaned_path,
            index=False
        )

        return redirect(
            url_for("classification_result")
        )

    except Exception as e:

        print("Classification error:", e)

        flash(
            f"Classification failed: {e}",
            "error"
        )

        return redirect(
            url_for("classify")
        )


# =========================================================
# CLASSIFICATION RESULT
# =========================================================

@app.route("/classification-result")
def classification_result():

    recipients = read_recipient_csv()

    business = [
        r for r in recipients
        if r["category"].lower() == "business"
    ]

    individual = [
        r for r in recipients
        if r["category"].lower() == "individual"
    ]

    return render_template(
        "classification_result.html",
        business=business,
        individual=individual,
        total=len(recipients)
    )


# =========================================================
# SEND PAGE
# =========================================================

@app.route("/send")
def send():

    recipients = read_recipient_csv()

    business_count = sum(
        1
        for r in recipients
        if r["category"].lower() == "business"
    )

    individual_count = sum(
        1
        for r in recipients
        if r["category"].lower() == "individual"
    )

    return render_template(
        "send.html",
        total_count=len(recipients),
        business_count=business_count,
        individual_count=individual_count
    )


# =========================================================
# ATTACHMENT UPLOAD + CAMPAIGN FORM
# =========================================================

@app.route("/launch-campaign", methods=["POST"])
def launch_campaign():

    # -----------------------------------------------------
    # Get values from the campaign form
    # IMPORTANT: these names must match send.html
    # -----------------------------------------------------

    subject = request.form.get("subject", "").strip()
    content = request.form.get("content", "").strip()
    audience = request.form.get(
        "audience",
        "All Recipients"
    ).strip()

    attachment = request.files.get("attachment")

    # -----------------------------------------------------
    # Validate Gmail configuration
    # -----------------------------------------------------

    if not EMAIL_ADDRESS or not EMAIL_APP_PASSWORD:
        flash(
            "Gmail connection failed. "
            "Check EMAIL_ADDRESS and EMAIL_APP_PASSWORD in your .env file.",
            "error"
        )
        return redirect(url_for("send"))

    # -----------------------------------------------------
    # Validate subject
    # -----------------------------------------------------

    if not subject:
        flash(
            "Please enter an email subject.",
            "error"
        )
        return redirect(url_for("send"))

    # -----------------------------------------------------
    # Validate content
    # -----------------------------------------------------

    if not content:
        flash(
            "Please enter email content.",
            "error"
        )
        return redirect(url_for("send"))

    # -----------------------------------------------------
    # Validate audience
    # -----------------------------------------------------

    allowed_audiences = {
        "Individual Recipients",
        "Business Recipients",
        "All Recipients"
    }

    if audience not in allowed_audiences:
        flash(
            "Please select a valid target audience.",
            "error"
        )
        return redirect(url_for("send"))

    # -----------------------------------------------------
    # Select recipients based on dropdown
    # -----------------------------------------------------

    recipients = filter_recipients(audience)

    if not recipients:
        flash(
            "No recipients found for the selected audience.",
            "error"
        )
        return redirect(url_for("send"))

    print("\n===================================")
    print("TARGET AUDIENCE:", audience)
    print("RECIPIENT COUNT:", len(recipients))
    print("===================================")

    for recipient in recipients:
        print(
            f"Selected recipient: "
            f"{recipient['email']} "
            f"({recipient['category']})"
        )

    print("===================================\n")

    # -----------------------------------------------------
    # Save attachment
    # -----------------------------------------------------

    attachment_path = None
    attachment_name = ""

    if attachment and attachment.filename:

        if not allowed_attachment(
            attachment.filename
        ):
            flash(
                "Unsupported attachment. "
                "Use PDF, PPT, PPTX, DOC or DOCX.",
                "error"
            )
            return redirect(url_for("send"))

        attachment_name = secure_filename(
            attachment.filename
        )

        attachment_path = os.path.join(
            ATTACHMENT_FOLDER,
            attachment_name
        )

        try:
            attachment.save(
                attachment_path
            )

        except Exception as e:
            flash(
                f"Attachment upload failed: {e}",
                "error"
            )
            return redirect(url_for("send"))

    # -----------------------------------------------------
    # Prepare result list
    # -----------------------------------------------------

    results = []
    server = None

    try:

        # -------------------------------------------------
        # Connect to Gmail SMTP
        # -------------------------------------------------

        # -------------------------------------------------
        # Connect to Gmail SMTP using SSL
        # -------------------------------------------------
        # Gmail SMTP SSL uses port 465.
        # Keep this connection open while all campaign
        # emails are being sent.

        server = smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465,
            timeout=30
        )

        server.login(
            EMAIL_ADDRESS,
            EMAIL_APP_PASSWORD
        )

        print("\n===================================")
        print("GMAIL SMTP CONNECTION SUCCESSFUL")
        print("===================================")
        print(
            f"Sending to {len(recipients)} "
            f"selected recipient(s)"
        )
        print("===================================\n")

        # -------------------------------------------------
        # Send one email at a time
        # -------------------------------------------------

        for index, recipient in enumerate(recipients):

            email_address = recipient["email"]

            try:

                message = EmailMessage()

                message["From"] = EMAIL_ADDRESS
                message["To"] = email_address
                message["Subject"] = subject

                message.set_content(
                    content
                )

                # -----------------------------------------
                # Add attachment
                # -----------------------------------------

                if attachment_path:

                    with open(
                        attachment_path,
                        "rb"
                    ) as file:

                        file_data = file.read()

                    extension = os.path.splitext(
                        attachment_name
                    )[1].lower()

                    mime_types = {
                        ".pdf": (
                            "application",
                            "pdf"
                        ),
                        ".ppt": (
                            "application",
                            "vnd.ms-powerpoint"
                        ),
                        ".pptx": (
                            "application",
                            "vnd.openxmlformats-officedocument.presentationml.presentation"
                        ),
                        ".doc": (
                            "application",
                            "msword"
                        ),
                        ".docx": (
                            "application",
                            "vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )
                    }

                    maintype, subtype = mime_types[
                        extension
                    ]

                    message.add_attachment(
                        file_data,
                        maintype=maintype,
                        subtype=subtype,
                        filename=attachment_name
                    )

                # -----------------------------------------
                # Send email
                # -----------------------------------------

                refused = server.send_message(
                    message
                )

                # Empty refused dictionary means the SMTP
                # server accepted the recipient.
                if email_address in refused:

                    error_text = str(
                        refused[email_address]
                    )

                    results.append({
                        "email": email_address,
                        "status": "failed",
                        "error": error_text
                    })

                    print(
                        f"FAILED / REFUSED: "
                        f"{email_address} -> {error_text}"
                    )

                else:

                    results.append({
                        "email": email_address,
                        "status": "sent",
                        "error": ""
                    })

                    print(
                        f"SENT / SMTP ACCEPTED: "
                        f"{email_address}"
                    )

            except Exception as e:

                results.append({
                    "email": email_address,
                    "status": "failed",
                    "error": str(e)
                })

                print(
                    f"FAILED: "
                    f"{email_address} -> {e}"
                )

            # -----------------------------------------
            # Wait 5 seconds before next email
            # -----------------------------------------

            if index < len(recipients) - 1:
                time.sleep(5)

        # -------------------------------------------------
        # Summary
        # -------------------------------------------------

        sent_count = sum(
            1
            for result in results
            if result["status"] == "sent"
        )

        failed_count = sum(
            1
            for result in results
            if result["status"] == "failed"
        )

        print("\n===================================")
        print("CAMPAIGN SENDING FINISHED")
        print("===================================")
        print("Selected:", len(recipients))
        print("SMTP accepted:", sent_count)
        print("Failed:", failed_count)
        print("===================================\n")

    except Exception as e:

        print(
            "SMTP connection/login error:",
            e
        )

        results = [
            {
                "email": r["email"],
                "status": "failed",
                "error": str(e)
            }
            for r in recipients
        ]

        flash(
            "Gmail connection failed. "
            "Check EMAIL_ADDRESS and EMAIL_APP_PASSWORD in your .env file.",
            "error"
        )

    finally:

        # Always close the SMTP connection
        if server is not None:

            try:
                server.quit()
            except Exception:
                pass

    # -----------------------------------------------------
    # Save reports
    # -----------------------------------------------------

    # save_report() uses only email/status columns, so the
    # report remains compatible with your existing dashboard.
    save_report(
        results
    )

    save_report_json(
        results,
        subject,
        audience,
        attachment_name
    )

    # -----------------------------------------------------
    # Open report dashboard
    # -----------------------------------------------------

    return redirect(
        url_for("reports")
    )


# =========================================================
# REPORTS
# =========================================================

@app.route("/reports")
@app.route("/report")
def reports():

    report_path = os.path.join(
        REPORT_FOLDER,
        "campaign_report.csv"
    )

    results = []

    if os.path.exists(report_path):

        try:

            with open(
                report_path,
                "r",
                encoding="utf-8"
            ) as file:

                reader = csv.DictReader(file)

                for row in reader:

                    results.append({
                        "email": row.get(
                            "emails",
                            ""
                        ),

                        "status": row.get(
                            "status",
                            ""
                        )
                    })

        except Exception as e:

            print(
                "Report reading error:",
                e
            )

    total = len(results)

    # "sent" means Gmail SMTP accepted the message.
    # It does not guarantee final inbox delivery.
    delivered = sum(
        1
        for r in results
        if r["status"].lower()
        in ["sent", "delivered"]
    )

    failed = sum(
        1
        for r in results
        if r["status"].lower()
        == "failed"
    )

    delivery_rate = (
        round(
            (delivered / total) * 100,
            1
        )
        if total > 0
        else 0
    )

    delivered_emails = [
        r["email"]
        for r in results
        if r["status"].lower()
        in ["sent", "delivered"]
    ]

    failed_emails = [
        r["email"]
        for r in results
        if r["status"].lower()
        == "failed"
    ]

    return render_template(
        "reports.html",

        results=results,

        total=total,

        delivered=delivered,

        failed=failed,

        delivery_rate=delivery_rate,

        delivered_emails=delivered_emails,

        failed_emails=failed_emails
    )


# =========================================================
# DOWNLOAD REPORT
# =========================================================

@app.route("/download-report")
def download_report():

    report_path = os.path.join(
        REPORT_FOLDER,
        "campaign_report.csv"
    )

    if not os.path.exists(
        report_path
    ):

        flash(
            "No campaign report is available yet.",
            "error"
        )

        return redirect(
            url_for("reports")
        )

    return send_file(
        report_path,
        as_attachment=True,
        download_name="campaign_report.csv",
        mimetype="text/csv"
    )


# =========================================================
# SETTINGS
# =========================================================

@app.route("/settings")
def settings():

    return render_template(
        "settings.html"
    )


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print("=" * 50)
    print("EMAILPRO APPLICATION")
    print("=" * 50)

    print(
        "Gmail configured:",
        bool(EMAIL_ADDRESS and EMAIL_APP_PASSWORD)
    )

    print(
        "Starting Flask server..."
    )

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )
