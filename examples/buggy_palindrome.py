def is_palindrome(s):
    """
    Return True if s reads the same forwards and backwards.

    Ignores spaces, punctuation, and case.
    Example: is_palindrome("A man, a plan, a canal: Panama") == True
    """
    cleaned = "".join(c for c in s if c.isalnum())  # BUG: missing .lower()
    return cleaned == cleaned[::-1]
