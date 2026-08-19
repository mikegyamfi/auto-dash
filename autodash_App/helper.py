import random
import time
import requests
from decouple import config

sms_url = 'https://webapp.usmsgh.com/api/sms/send'


def generate_service_order_number(prefix="ORD"):
    # Get the current time in seconds since epoch, truncated to an integer
    timestamp = int(time.time())

    # Generate a random 4-digit number
    random_number = random.randint(1000, 9999)

    # Combine prefix, timestamp, and random number
    order_number = f"{prefix}{timestamp}{random_number}".upper()

    return order_number


SMS_TIMEOUT = 15  # seconds; keep a hung gateway from blocking the web worker


def _send(phone_number, message, sender_id):
    # The gateway issues Laravel Sanctum tokens ("<id>|<secret>"), which must be
    # sent as a Bearer token. Without the prefix every request 401s.
    api_key = config('SMS_API_KEY')
    if not api_key.startswith('Bearer '):
        api_key = f"Bearer {api_key}"

    sms_headers = {
        'Authorization': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    # Numbers are stored with their leading zero (e.g. "0242442147"); the
    # gateway strips the extra digit after the 233 prefix on its own.
    receiver_body = {
        'recipient': f"233{phone_number}",
        'sender_id': sender_id,
        'message': message
    }

    response = requests.request('POST', url=sms_url, params=receiver_body,
                                headers=sms_headers, timeout=SMS_TIMEOUT)
    print(response.text)

    # Surface failures instead of swallowing them - a 401 or a rejected send
    # used to look exactly like a delivered one. Call sites already wrap this
    # in try/except and report the error to the user.
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"SMS gateway returned a non-JSON response: {response.text[:200]}")
    if payload.get('status') != 'success':
        raise RuntimeError(f"SMS gateway rejected the message: {payload.get('message') or payload}")
    return payload


def send_sms(phone_number, message):
    return _send(phone_number, message, 'AutoDash')


def send_sms_club(phone_number, message):
    return _send(phone_number, message, 'AD WashClub')


