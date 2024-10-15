import random
import time


def generate_service_order_number(prefix="ORD"):
    # Get the current time in seconds since epoch, truncated to an integer
    timestamp = int(time.time())

    # Generate a random 4-digit number
    random_number = random.randint(1000, 9999)

    # Combine prefix, timestamp, and random number
    order_number = f"{prefix}{timestamp}{random_number}".upper()

    return order_number

