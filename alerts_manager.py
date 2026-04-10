import os
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def send_telegram_sync(message):
    load_dotenv(override=True)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.error("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID for sync message.")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}
    try:
        res = requests.post(url, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        logger.error(f"Telegram alert failed: {e}")
        return False

def send_email_sync(subject, body):
    load_dotenv(override=True)
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    receiver = os.getenv("EMAIL_RECEIVER")
    
    if not sender or not password or not receiver:
        logger.error("Missing Email Configuration in .env")
        return False
        
    msg = MIMEMultipart()
    msg['From'] = sender
    msg['To'] = receiver
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
        server.quit()
        logger.info("Email alert sent successfully.")
        return True
    except Exception as e:
        logger.error(f"Email alert failed: {e}")
        return False

def send_sms_sync(message):
    load_dotenv(override=True)
    api_key = os.getenv("SMS_API_KEY")
    phone = os.getenv("PHONE_NUMBER")
    
    # Generic SMS Gateway Integration (Easily adaptable for Twilio, Africa's Talking, or Orange API)
    # E.g. Africa's Talking:
    username = os.getenv("SMS_USERNAME", "sandbox")
    if not api_key or not phone:
        logger.error("Missing SMS configuration (SMS_API_KEY or PHONE_NUMBER) in .env")
        return False
        
    # Example using a generic HTTP POST for Africa's Talking
    url = "https://api.africastalking.com/version1/messaging"
    headers = {
        "ApiKey": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    data = {
        "username": username,
        "to": phone,
        "message": message
    }
    
    try:
        res = requests.post(url, headers=headers, data=data, timeout=10)
        logger.info(f"SMS alert push result: {res.text}")
        return res.status_code in [200, 201]
    except Exception as e:
        logger.error(f"SMS alert failed: {e}")
        return False

def broadcast_alert(message, subject="Scalping Bot Alert"):
    """Sends the alert across all configured and enabled channels."""
    load_dotenv(override=True)
    use_tg = os.getenv("USE_TELEGRAM", "True").lower() == "true"
    use_email = os.getenv("USE_EMAIL", "False").lower() == "true"
    use_sms = os.getenv("USE_SMS", "False").lower() == "true"
    
    if use_tg:
        send_telegram_sync(message)
    if use_email:
        send_email_sync(subject, message)
    if use_sms:
        send_sms_sync(message)
