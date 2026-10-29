import bcrypt


def hash_password(plain_password: str):
    """Return a salted bcrypt hash to store in the database"""
    # Generate a salt and hash the password
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(plain_password.encode('utf-8'), salt)
    # Store as a string in the database
    return hashed_bytes.decode('utf-8')

def check_password(plain_password: str, password_hash: str) -> bool:
    """Check a login attempt against the stored hash."""
    return bcrypt.checkpw(
        plain_password.encode('utf-8'), 
        password_hash.encode('utf-8')
    )