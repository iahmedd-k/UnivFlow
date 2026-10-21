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
) -> bool:
    """Send email via SendGrid API with spam-reduction best practices"""
    subject = format_email_subject(subject)
    from_email = from_email or settings.sendgrid_from_email or settings.email_from or "noreply@basarat.live"
    from_name = from_name or "Uniflow"

    client = get_sendgrid_client()
    if not client:
        logger.warning(f"SendGrid client not configured, falling back to SMTP for {to_email}")
        return send_smtp_email(to_email, subject, html_content, text_content)

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
            return send_smtp_email(to_email, subject, html_content, text_content)

    except Exception as e:
        logger.warning(f"SendGrid send failed for {to_email}: {e}, falling back to SMTP")
        return send_smtp_email(to_email, subject, html_content, text_content)


def send_smtp_email(to_email: str, subject: str, html_content: str, text_content: str = None) -> bool:
    """Fallback email sender via SMTP (e.g. Gmail)"""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    user = settings.smtp_username or settings.smtp_user or ""
    pwd = (settings.smtp_password or "").replace(" ", "")
    host = settings.smtp_host or "smtp.gmail.com"
    port = settings.smtp_port or 587
    from_email = settings.email_from or user

    if not (user and pwd and host):
        logger.error("SMTP credentials not fully configured")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email

        if text_content:
            msg.attach(MIMEText(text_content, "plain"))
        if html_content:
            msg.attach(MIMEText(html_content, "html"))

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