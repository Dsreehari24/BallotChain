from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q


class EmailOrUsernameModelBackend(ModelBackend):
    """
    BallotChain Unified Authentication Backend.
    Allows authentication using either an email address or a username.
    Lookup is strictly case-insensitive for email addresses and usernames.
    Preserves all standard Django user permissions, active status checks,
    and PBKDF2 password verification.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('email')

        if not username or not password:
            return None

        clean_identifier = str(username).strip()
        clean_password = str(password).strip()

        # Find user by case-insensitive email or case-insensitive username
        user = User.objects.filter(
            Q(email__iexact=clean_identifier) | Q(username__iexact=clean_identifier)
        ).first()

        if user and self.user_can_authenticate(user):
            # 1. Standard exact password verification
            if user.check_password(password):
                return user

            # 2. Check whitespace-stripped password (handles accidental copy-paste spaces)
            if password != clean_password and user.check_password(clean_password):
                return user

            # 3. For student accounts whose initial password matches their roll number (e.g. 2411CS070001),
            # allow case-insensitive match against the roll number format.
            if clean_password.upper() == user.username.upper():
                if user.check_password(user.username.upper()) or user.check_password(user.username.lower()):
                    return user

        return None
