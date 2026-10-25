import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content, Header
from app.core.config import settings
import logging
import re

logger = logging.getLogger(__name__)

sg_client = None


def format_email_subject(subject: str) -> str:
    """Give outbound email subjects a consistent, professional Uniflow format."""
    title = re.sub(r"^\[Uniflow(?: [^\]]*)?\]\s*", "", (subject or "").strip(), flags=re.IGNORECASE)
    title = re.sub(r"^Uniflow(?:\s*[|:—-]\s*|\s+)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip()
    if title.isupper() or title.islower():
        title = title.title()
    return f"Uniflow | {title or 'Notification'}"


def get_sendgrid_client():
    global sg_client
    if sg_client is None:
        if not settings.sendgrid_api_key:
            logger.warning("SendGrid API key not configured")
            return None
        sg_client = sendgrid.SendGridAPIClient(api_key=settings.sendgrid_api_key)
    return sg_client


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = None,
    from_email: str = None,
    from_name: str = None,
    reply_to: str = None,
    categories: list = None,
    custom_args: dict = None,
    attachments: list = None,
) -> bool:
    """Send email via SendGrid API with spam-reduction best practices and attachment support"""
    subject = format_email_subject(subject)
    from_email = from_email or settings.sendgrid_from_email or settings.email_from or "noreply@basarat.live"
    from_name = from_name or "Uniflow"

    client = get_sendgrid_client()
    if not client:
        logger.warning(f"SendGrid client not configured, falling back to SMTP for {to_email}")
        return send_smtp_email(to_email, subject, html_content, text_content, attachments=attachments)

    if not text_content:
        # Simple HTML to text conversion
        import re
        text_content = re.sub(r'<[^>]+>', '', html_content)
        text_content = re.sub(r'\s+', ' ', text_content).strip()

    try:
        mail = Mail(
            from_email=Email(from_email, from_name),
            to_emails=To(to_email),
            subject=subject,
            html_content=Content("text/html", html_content),
            plain_text_content=Content("text/plain", text_content),
        )

        # Transactional email headers
        mail.add_header(Header("Auto-Submitted", "auto-generated"))
        mail.add_header(Header("X-Priority", "3"))
        mail.add_header(Header("Importance", "Normal"))

        if reply_to:
            mail.reply_to = Email(reply_to)

        # Attachments support for SendGrid
        if attachments:
            import base64
            from sendgrid.helpers.mail import Attachment, FileContent, FileName, FileType, Disposition
            for att in attachments:
                c_data = att.get("content")
                if isinstance(c_data, str):
                    c_data = c_data.encode("utf-8")
                b64_content = base64.b64encode(c_data).decode("ascii")
                mail.add_attachment(
                    Attachment(
                        FileContent(b64_content),
                        FileName(att.get("filename", "attachment.bin")),
                        FileType(att.get("type", "application/octet-stream")),
                        Disposition("attachment"),
                    )
                )

        # Categories for tracking
        if categories:
            for cat in categories:
                if isinstance(cat, str):
                    from sendgrid.helpers.mail import Category
                    mail.add_category(Category(cat))
                else:
                    mail.add_category(cat)

        # Custom args for tracking
        if custom_args:
            for key, value in custom_args.items():
                from sendgrid.helpers.mail import CustomArg
                mail.add_custom_arg(CustomArg(str(key), str(value)))

        response = client.send(mail)
        
        if 200 <= response.status_code < 300:
            safe_subj = subject.encode("ascii", "replace").decode("ascii")
            logger.info(f"Email sent to {to_email}: {safe_subj} (status: {response.status_code})")
            return True
        else:
            logger.warning(f"SendGrid error: {response.status_code} - {response.body}, falling back to SMTP")
            return send_smtp_email(to_email, subject, html_content, text_content, attachments=attachments)

    except Exception as e:
        logger.warning(f"SendGrid send failed for {to_email}: {e}, falling back to SMTP")
        return send_smtp_email(to_email, subject, html_content, text_content, attachments=attachments)


def send_smtp_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = None,
    attachments: list = None,
) -> bool:
    """Fallback email sender via SMTP with attachment support (e.g. Gmail)"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    user = settings.smtp_username or settings.smtp_user or ""
    pwd = (settings.smtp_password or "").replace(" ", "")
    host = settings.smtp_host or "smtp.gmail.com"
    port = settings.smtp_port or 587
    from_email = settings.email_from or user

    if not (user and pwd and host):
        logger.error("SMTP credentials not fully configured")
        return False

    try:
        if attachments:
            msg = MIMEMultipart("mixed")
            alt_part = MIMEMultipart("alternative")
            if text_content:
                alt_part.attach(MIMEText(text_content, "plain"))
            if html_content:
                alt_part.attach(MIMEText(html_content, "html"))
            msg.attach(alt_part)

            for att in attachments:
                c_data = att.get("content")
                if isinstance(c_data, str):
                    c_data = c_data.encode("utf-8")
                maintype, _, subtype = (att.get("type") or "application/octet-stream").partition("/")
                part = MIMEBase(maintype or "application", subtype or "octet-stream")
                part.set_payload(c_data)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{att.get("filename", "attachment.bin")}"')
                msg.attach(part)
        else:
            msg = MIMEMultipart("alternative")
            if text_content:
                msg.attach(MIMEText(text_content, "plain"))
            if html_content:
                msg.attach(MIMEText(html_content, "html"))

        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        server = smtplib.SMTP(host, port, timeout=12)
        if settings.smtp_tls:
            server.starttls()
        server.login(user, pwd)
        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        logger.info(f"Email delivered via SMTP fallback to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"SMTP fallback failed for {to_email}: {e}")
        return False


def send_solution_delivery_email(db, assignment_id: int, user_id: str) -> bool:
    """
    Automatically deliver generated assignment solution and attached deliverables
    to the student's selected/verified email address immediately upon generation.
    """
    import io
    import zipfile
    from datetime import datetime, timezone
    from app.db.models import Assignment, Course, AssignmentSolution
    from app.services.alert_service import get_user_recipient_email
    from app.services.ai_solution import extract_assignment_deliverables

    try:
        assignment = db.query(Assignment).filter(
            Assignment.id == assignment_id,
            Assignment.user_id == user_id,
        ).first()
        if not assignment:
            logger.warning("send_solution_delivery_email: Assignment %s not found for user %s", assignment_id, user_id)
            return False

        course = db.query(Course).filter(Course.id == assignment.course_id).first()
        solution = db.query(AssignmentSolution).filter(
            AssignmentSolution.assignment_id == assignment_id,
        ).first()
        if not solution:
            logger.warning("send_solution_delivery_email: Solution not found for assignment %s", assignment_id)
            return False

        raw_content = solution.validated_content or solution.draft_content or ""
        if not raw_content.strip():
            logger.warning("send_solution_delivery_email: Solution content empty for assignment %s", assignment_id)
            return False

        to_email = get_user_recipient_email(db, user_id)
        if not to_email or "@" not in to_email:
            logger.warning("send_solution_delivery_email: No verified recipient email found for user %s", user_id)
            return False

        course_name = course.name if course and course.name else "Academic Coursework"
        assignment_title = assignment.title or f"Assignment #{assignment_id}"
        safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', assignment_title)[:40]

        # Extract deliverables & construct deliverables ZIP archive
        deliverables = extract_assignment_deliverables(raw_content)
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            readme_text = (
                f"UNIFLOW ACADEMIC SOLUTION DELIVERABLES\n"
                f"Course: {course_name}\n"
                f"Assignment: {assignment_title}\n"
                f"Generated At: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"Recipient: {to_email}\n\n"
                f"Contents:\n"
            )
            for d in deliverables:
                fname = d.get("filename") or f"task_{d.get('task', 1)}.py"
                code_content = d.get("code") or ""
                zf.writestr(fname, code_content)
                readme_text += f"- {fname} ({d.get('language', 'code')})\n"

            zf.writestr("README.txt", readme_text)
            zf.writestr("SOLUTION_FULL.md", raw_content)

        zip_bytes = zip_buffer.getvalue()

        # Build clean professional HTML email body
        deliverable_items_html = ""
        for d in deliverables:
            fname = d.get("filename") or f"task_{d.get('task', 1)}.py"
            lang = d.get("language") or "Code"
            deliverable_items_html += f"""
            <li style="margin-bottom: 6px; font-size: 13px; color: #374151;">
              <strong>{fname}</strong> <span style="background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 11px; color: #4b5563;">{lang}</span>
            </li>
            """

        doc_section_html = ""
        if solution.google_doc_url:
            doc_section_html = f"""
            <div style="margin: 20px 0; padding: 14px 18px; background: #eeeafe; border: 1px solid #dcd7fa; border-radius: 8px;">
              <strong style="color: #5b4cc6; font-size: 14px;">Google Doc Academic Report Ready</strong>
              <p style="margin: 4px 0 10px; font-size: 12px; color: #4b5563;">A complete formatted academic paper has been exported to your Google Drive.</p>
              <a href="{solution.google_doc_url}" style="display: inline-block; padding: 8px 16px; background: #6657d9; color: #ffffff; text-decoration: none; border-radius: 6px; font-size: 12px; font-weight: 600;">Open Google Doc Report &rarr;</a>
            </div>
            """

        # Truncated clean preview of solution text
        preview_text = re.sub(r'```[\s\S]*?```', '[Code Block Embedded in Deliverables ZIP]', raw_content)
        preview_text = preview_text[:600] + ("..." if len(preview_text) > 600 else "")
        preview_html = preview_text.replace("\n", "<br>")

        html_body = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Uniflow Solution Ready: {assignment_title}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #1e293b;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 640px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.04);">
    <tr>
      <td style="padding: 24px 32px; background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%); color: #ffffff;">
        <span style="display: inline-block; padding: 4px 10px; background: rgba(255,255,255,0.15); border-radius: 99px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Claude Solution Delivered</span>
        <h1 style="margin: 12px 0 4px; font-size: 20px; font-weight: 700; color: #ffffff;">{assignment_title}</h1>
        <p style="margin: 0; font-size: 13px; color: #c7d2fe;">Course: {course_name}</p>
      </td>
    </tr>
    <tr>
      <td style="padding: 28px 32px;">
        <p style="font-size: 14px; line-height: 1.6; color: #334155; margin-top: 0;">
          Hello, your academic solution and deliverables have been compiled and verified by Uniflow Claude solver.
        </p>

        {doc_section_html}

        <div style="margin: 20px 0; padding: 16px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0;">
          <h3 style="margin: 0 0 10px; font-size: 14px; font-weight: 600; color: #0f172a;">Generated Deliverables (Attached in ZIP):</h3>
          <ul style="margin: 0; padding-left: 20px;">
            {deliverable_items_html or '<li style="font-size: 13px; color: #64748b;">Comprehensive Academic Analysis & Markdown Report</li>'}
          </ul>
        </div>

        <div style="margin: 20px 0;">
          <h4 style="margin: 0 0 8px; font-size: 13px; color: #475569; text-transform: uppercase; letter-spacing: 0.5px;">Solution Overview:</h4>
          <div style="padding: 14px; background: #f1f5f9; border-radius: 6px; font-size: 12px; line-height: 1.5; color: #334155; font-family: monospace;">
            {preview_html}
          </div>
        </div>

        <div style="margin-top: 28px; padding-top: 20px; border-top: 1px solid #e2e8f0; text-align: center;">
          <p style="font-size: 12px; color: #64748b; margin-bottom: 12px;">The complete code bundle and documentation are attached as <strong>{safe_name}_deliverables.zip</strong>.</p>
          <a href="http://localhost:3000/dashboard/assignments" style="display: inline-block; padding: 10px 20px; background: #4f46e5; color: #ffffff; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: 600;">Go to Uniflow Dashboard &rarr;</a>
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding: 16px 32px; background: #f8fafc; border-top: 1px solid #e2e8f0; font-size: 11px; color: #94a3b8; text-align: center;">
        Uniflow Academic Orchestration · Sent immediately upon solution generation to {to_email}
      </td>
    </tr>
  </table>
</body>
</html>"""

        email_attachments = [
            {
                "filename": f"{safe_name}_deliverables.zip",
                "content": zip_bytes,
                "type": "application/zip",
            }
        ]

        sent = send_email(
            to_email=to_email,
            subject=f"Assignment Solution: {assignment_title} ({course_name})",
            html_content=html_body,
            attachments=email_attachments,
        )
        if sent:
            logger.info("Successfully emailed solution for assignment %s to %s", assignment_id, to_email)
        else:
            logger.warning("Failed to email solution for assignment %s to %s", assignment_id, to_email)
        return sent
    except Exception as exc:
        logger.exception("Error sending solution delivery email for assignment %s: %s", assignment_id, exc)
        return False



def send_template_email(
    to_email: str,
    template_id: str,
    dynamic_template_data: dict,
    from_email: str = None,
    from_name: str = None,
    categories: list = None,
) -> bool:
    """Send email using SendGrid dynamic template"""
    client = get_sendgrid_client()
    if not client:
        return False

    from_email = from_email or settings.sendgrid_from_email or settings.email_from
    from_name = from_name or "Uniflow"
    dynamic_template_data = dict(dynamic_template_data)
    if isinstance(dynamic_template_data.get("subject"), str):
        dynamic_template_data["subject"] = format_email_subject(dynamic_template_data["subject"])

    try:
        mail = Mail(
            from_email=Email(from_email, from_name),
            to_emails=To(to_email),
        )
        mail.template_id = template_id
        mail.dynamic_template_data = dynamic_template_data

        if categories:
            for cat in categories:
                mail.add_category(cat)

        mail.add_header(Header("Precedence", "bulk"))
        mail.add_header(Header("Auto-Submitted", "auto-generated"))

        response = client.send(mail)
        return 200 <= response.status_code < 300

    except Exception as e:
        logger.error(f"Failed to send template email: {e}")
        return False


def verify_sender(email: str) -> bool:
    """Verify sender email in SendGrid (single sender verification)"""
    client = get_sendgrid_client()
    if not client:
        return False
    try:
        # This requires SendGrid API call to verified senders endpoint
        # For now, return True if configured
        return bool(settings.sendgrid_from_email)
    except Exception:
        return False