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


def send_sms(phone_number, message):
    sms_headers = {
        'Authorization': config('SMS_API_KEY'),
        'Content-Type': 'application/json'
    }

    receiver_body = {
        'recipient': f"233{phone_number}",
        'sender_id': 'AutoDash',
        'message': message
    }

    response = requests.request('POST', url=sms_url, params=receiver_body, headers=sms_headers)
    print(response.text)



