import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content, Header
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

sg_client = None


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
    client = get_sendgrid_client()
    if not client:
        logger.error("SendGrid client not available")
        return False

    from_email = from_email or settings.sendgrid_from_email or settings.email_from
    from_name = from_name or "Uniflow"

    if not from_email:
        logger.error("No from email configured")
        return False

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

        # Anti-spam headers
        mail.add_header(Header("Precedence", "bulk"))
        mail.add_header(Header("Auto-Submitted", "auto-generated"))
        mail.add_header(Header("X-Priority", "3"))
        mail.add_header(Header("X-MSMail-Priority", "Normal"))
        mail.add_header(Header("Importance", "Normal"))

        # List-Unsubscribe (required for bulk)
        mail.add_header(Header("List-Unsubscribe", f"<mailto:{from_email}?subject=unsubscribe>"))

        if reply_to:
            mail.reply_to = Email(reply_to)

        # Categories for tracking
        if categories:
            for cat in categories:
                mail.add_category(cat)

        # Custom args for tracking
        if custom_args:
            for key, value in custom_args.items():
                mail.add_custom_arg(key, value)

        response = client.send(mail)
        
        if 200 <= response.status_code < 300:
            logger.info(f"Email sent to {to_email}: {subject} (status: {response.status_code})")
            return True
        else:
            logger.error(f"SendGrid error: {response.status_code} - {response.body}")
            return False

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
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