"""Assessment content shared by every role (each role can override the voice parts)."""

TYPING_TEXT = (
    "Good customer service starts with listening carefully. When a customer writes to us, "
    "we read the whole message, confirm what they need, and reply in clear and simple words. "
    "If we cannot solve the problem at once, we explain the next step and tell them exactly "
    "when they will hear from us again."
)

CHAT_SCENARIOS = [
    {
        "id": "late-order",
        "customer": "I ordered a phone 10 days ago and it STILL has not arrived. Your app says "
                    "'delivered' but I got nothing. This is the worst service ever. I want my money back!",
        "expects": ["refund|money back|replacement", "order number|order id|order details|tracking",
                    "check|investigate|look into|verify", "24 hours|48 hours|within|by tomorrow|working days|shortly|today"],
    },
    {
        "id": "double-charge",
        "customer": "Hi, I was charged twice for my monthly subscription this morning. "
                    "Can you tell me why and fix it?",
        "expects": ["refund|reverse|reversal|credit", "transaction|payment|charge",
                    "account|registered email|email id|details", "days|hours|within|shortly|today"],
    },
]
