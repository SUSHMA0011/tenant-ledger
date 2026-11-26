# Allowed currencies and how many decimal places each has (the "minor unit" exponent).
CURRENCY_EXPONENT = {"INR": 2, "USD": 2, "EUR": 2, "GBP": 2, "JPY": 0}

# Sanity cap per transaction (in minor units) - guards against fat-finger / junk amounts.
MAX_AMOUNT_MINOR = 10**12

# Bulk upload limit per request.
MAX_BULK_ROWS = 1000
