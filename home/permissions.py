def get_user_profile(user):
    """
    Safely retrieves the UserProfile for a Django User.
    Returns None if the user is unauthenticated or has no profile.
    """
    if not user or not user.is_authenticated:
        return None
    try:
        return user.userprofile
    except Exception:
        # Catch RelatedObjectDoesNotExist safely
        return None

def get_user_role(user):
    """
    Safely retrieves the user's administrative role.
    Defaults superusers without a profile to PLATFORM_ADMIN.
    Returns None if they lack an administrative profile.
    """
    if not user or not user.is_authenticated:
        return None
    profile = get_user_profile(user)
    if profile:
        return profile.role
    if getattr(user, 'is_superuser', False):
        return 'PLATFORM_ADMIN'
    return None

def is_platform_admin(user):
    """
    True if user has global platform-level administrative privileges
    (either Django superuser or UserProfile role == 'PLATFORM_ADMIN').
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return get_user_role(user) == 'PLATFORM_ADMIN'

def is_organization_admin(user, organization_id=None):
    """
    True if user has the ORGANIZATION_ADMIN role.
    If organization_id is provided, also verifies tenant boundary.
    """
    if not user or not user.is_authenticated:
        return False
    if get_user_role(user) != 'ORGANIZATION_ADMIN':
        return False
    if organization_id is not None:
        return belongs_to_organization(user, organization_id)
    return True

def is_election_official(user, organization_id=None):
    """
    True if user has the ELECTION_OFFICIAL role.
    If organization_id is provided, also verifies tenant boundary.
    """
    if not user or not user.is_authenticated:
        return False
    if get_user_role(user) != 'ELECTION_OFFICIAL':
        return False
    if organization_id is not None:
        return belongs_to_organization(user, organization_id)
    return True

def is_auditor(user, organization_id=None):
    """
    True if user has the strictly read-only AUDITOR role.
    If organization_id is provided, also verifies tenant boundary.
    """
    if not user or not user.is_authenticated:
        return False
    if get_user_role(user) != 'AUDITOR':
        return False
    if organization_id is not None:
        return belongs_to_organization(user, organization_id)
    return True

def is_candidate(user):
    """
    True if the user participates as a Candidate in any election.
    """
    if not user or not user.is_authenticated:
        return False
    try:
        from home.models import Candidate
        return hasattr(Candidate, 'user') and Candidate.objects.filter(user=user).exists()
    except Exception:
        return False

def is_candidate_account(user):
    """
    Determines if the authenticated user is recognized as a Candidate account:
    - Excludes Platform Admin, Organization Admin, Election Official, and Auditor.
    - Matches users associated with Candidate objects, or recognized candidate accounts:
      candidate1@ballotchain.com - candidate5@ballotchain.com.
    - Ordinary voters return False.
    """
    if not user or not user.is_authenticated:
        return False
    role = get_user_role(user)
    if role in ['PLATFORM_ADMIN', 'ORGANIZATION_ADMIN', 'ELECTION_OFFICIAL', 'AUDITOR']:
        return False
    if is_candidate(user):
        return True
    email = (getattr(user, 'email', '') or '').lower().strip()
    username = (getattr(user, 'username', '') or '').lower().strip()
    candidate_emails = {
        'candidate1@ballotchain.com',
        'candidate2@ballotchain.com',
        'candidate3@ballotchain.com',
        'candidate4@ballotchain.com',
        'candidate5@ballotchain.com',
    }
    candidate_usernames = {'candidate1', 'candidate2', 'candidate3', 'candidate4', 'candidate5'}
    return (email in candidate_emails or username in candidate_usernames)

def is_voter(user):
    """
    True if the user is an authenticated voter without an administrative profile.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return False
    return get_user_profile(user) is None

def is_authenticated_admin(user):
    """
    Determines whether the user has true administrative authority:
    PLATFORM_ADMIN or ORGANIZATION_ADMIN.
    Does NOT include ELECTION_OFFICIAL (operational only) or AUDITOR (strictly read-only).
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return get_user_role(user) in ['PLATFORM_ADMIN', 'ORGANIZATION_ADMIN']

def has_administrative_access(user):
    """
    Determines if user has any administrative or election management role
    (PLATFORM_ADMIN, ORGANIZATION_ADMIN, ELECTION_OFFICIAL).
    Excludes AUDITOR, CANDIDATE, and standard VOTER.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    return get_user_role(user) in ['PLATFORM_ADMIN', 'ORGANIZATION_ADMIN', 'ELECTION_OFFICIAL']

def has_staff_or_auditor_access(user, organization_id=None):
    """
    Determines if user is an internal staff member or auditor:
    PLATFORM_ADMIN, ORGANIZATION_ADMIN, ELECTION_OFFICIAL, or AUDITOR.
    If organization_id is provided, enforces tenant boundaries.
    """
    if not user or not user.is_authenticated:
        return False
    if is_platform_admin(user):
        return True
    role = get_user_role(user)
    if role not in ['ORGANIZATION_ADMIN', 'ELECTION_OFFICIAL', 'AUDITOR']:
        return False
    if organization_id is not None:
        return belongs_to_organization(user, organization_id)
    return True

def can_perform_administrative_mutation(user, organization_id=None):
    """
    Strict authorization check for administrative mutations:
    - Creating/editing/deleting organizations
    - Creating/deleting elections
    Only PLATFORM_ADMIN (global) or ORGANIZATION_ADMIN (scoped) may perform these.
    NEVER permitted for ELECTION_OFFICIAL, AUDITOR, VOTER, or CANDIDATE.
    """
    if not user or not user.is_authenticated:
        return False
    if is_platform_admin(user):
        return True
    if is_organization_admin(user):
        if organization_id is not None:
            return belongs_to_organization(user, organization_id)
        return True
    return False

def can_manage_election(user, election):
    """
    Determines whether user can configure and operate within an election
    (create/edit positions, candidates, eligibility, ballots, and batch mining).
    Allowed for:
    - PLATFORM_ADMIN (any election)
    - ORGANIZATION_ADMIN (within their organization)
    - ELECTION_OFFICIAL (within their organization)
    Forbidden for AUDITOR (read-only), normal USER/VOTER, and CANDIDATE.
    """
    if not user or not user.is_authenticated or election is None:
        return False
    if is_platform_admin(user):
        return True
    role = get_user_role(user)
    if role in ['ORGANIZATION_ADMIN', 'ELECTION_OFFICIAL']:
        return belongs_to_organization(user, election.organization_id)
    return False

def can_start_election(user, election):
    """
    Strict lifecycle authorization: ONLY Platform Admin or Org Admin (for their org)
    may transition an election from DRAFT to OPEN.
    NEVER available to ELECTION_OFFICIAL, AUDITOR, normal USER, or CANDIDATE.
    """
    if not user or not user.is_authenticated or election is None:
        return False
    if is_platform_admin(user):
        return True
    if is_organization_admin(user):
        return belongs_to_organization(user, election.organization_id)
    return False

def can_end_election(user, election):
    """
    Strict lifecycle authorization: ONLY Platform Admin or Org Admin (for their org)
    may transition an election from OPEN to CLOSED.
    NEVER available to ELECTION_OFFICIAL, AUDITOR, normal USER, or CANDIDATE.
    """
    if not user or not user.is_authenticated or election is None:
        return False
    if is_platform_admin(user):
        return True
    if is_organization_admin(user):
        return belongs_to_organization(user, election.organization_id)
    return False

def can_publish_results(user, election):
    """
    Strict lifecycle authorization: ONLY Platform Admin or Org Admin (for their org)
    may certify and publish election results.
    NEVER available to ELECTION_OFFICIAL, AUDITOR, normal USER, or CANDIDATE.
    """
    if not user or not user.is_authenticated or election is None:
        return False
    if is_platform_admin(user):
        return True
    if is_organization_admin(user):
        return belongs_to_organization(user, election.organization_id)
    return False

def can_view_ledger(user, block=None):
    """
    Ledger visibility check. Per Phase 8C-1, Admin, User, Candidate, Auditor,
    and public auditors may view the shared blockchain ledger explorer.
    Privileged unmasking remains restricted by tenant/auditor isolation.
    """
    return True

def get_account_persona(user):
    """
    Resolves the user's primary product persona:
    - 'PLATFORM_ADMIN'
    - 'ORGANIZATION_ADMIN'
    - 'ELECTION_OFFICIAL'
    - 'AUDITOR'
    - 'CANDIDATE' (if user participates as a candidate in an election)
    - 'VOTER' (standard authenticated user)
    - 'PUBLIC_AUDITOR' (unauthenticated visitor)
    """
    if not user or not user.is_authenticated:
        return 'PUBLIC_AUDITOR'
    
    role = get_user_role(user)
    if role in ['PLATFORM_ADMIN', 'ORGANIZATION_ADMIN', 'ELECTION_OFFICIAL', 'AUDITOR']:
        return role

    try:
        from home.models import Candidate
        if hasattr(Candidate, 'user') and Candidate.objects.filter(user=user).exists():
            return 'CANDIDATE'
    except Exception:
        pass

    return 'VOTER'

def is_organization_scoped(user):
    """
    Determines if the user's role is scoped to a specific organization.
    """
    return get_user_role(user) in ['ORGANIZATION_ADMIN', 'ELECTION_OFFICIAL', 'AUDITOR']

def belongs_to_organization(user, organization_id):
    """
    Determines if the user has access to a specific organization.
    PLATFORM_ADMIN always returns True due to global scope.
    Organization-scoped roles return True only if their profile's organization matches.
    """
    if is_platform_admin(user):
        return True
    
    profile = get_user_profile(user)
    if profile and profile.organization_id is not None:
        return str(profile.organization_id) == str(organization_id)
        
    return False
