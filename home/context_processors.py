"""
BallotChain Context Processors.
Provides persona and role-based metadata to all templates.
"""
from home.permissions import get_account_persona, is_platform_admin

PERSONA_LABELS = {
    'PLATFORM_ADMIN': 'Platform Admin',
    'ORGANIZATION_ADMIN': 'Organization Admin',
    'ELECTION_OFFICIAL': 'Election Official',
    'AUDITOR': 'Auditor',
    'CANDIDATE': 'Candidate',
    'VOTER': 'Voter',
    'PUBLIC_AUDITOR': 'Public Auditor',
}

def ballotchain_context(request):
    """
    Context processor injecting persona and authorization metadata
    into all rendered templates.
    """
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {
            'account_persona': 'PUBLIC_AUDITOR',
            'persona_label': 'Public Auditor',
            'is_platform_admin': False,
        }

    persona = get_account_persona(user)

    # Compute clean initials for neutral profile avatar (e.g. "JD" or "AD")
    initials = ""
    if user.first_name and user.last_name:
        initials = (user.first_name[0] + user.last_name[0]).upper()
    elif user.first_name:
        initials = user.first_name[:2].upper()
    elif user.username:
        initials = user.username[:2].upper()
    else:
        initials = "U"

    return {
        'account_persona': persona,
        'persona_label': PERSONA_LABELS.get(persona, 'User'),
        'is_platform_admin': is_platform_admin(user),
        'user_initials': initials,
    }
