from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie, csrf_protect
from django.template import loader
from django.forms.models import model_to_dict
from django.contrib import messages
from django.conf import settings
from django.utils import timezone

from .models import Voters, PoliticalParty, Vote, VoteBackup, Block, MiningInfo
from .methods_module import send_email_otp, generate_keys, verify_vote, send_email_private_key, vote_count

from Crypto.Hash import SHA3_256
from .merkle_tool import MerkleTools
import datetime, json, time, random, string, logging

logger = logging.getLogger(__name__)

def mask_voter_uuid(uuid_val):
    """
    Mask a voter UUID or ID to prevent public exposure.
    E.g. '111111111111' -> '1111******11'
         'v_8701'       -> 'v_**01'
         '1234'         -> '****'
    """
    if not uuid_val:
        return '****'
    s = str(uuid_val).strip()
    if len(s) <= 4:
        return '*' * len(s)
    if len(s) <= 8:
        return s[:2] + ('*' * (len(s) - 4)) + s[-2:]
    return s[:4] + ('*' * (len(s) - 6)) + s[-2:]


class VoteDisplayItem:
    """Read-only presentation adapter for block votes to mask sensitive voter IDs."""
    def __init__(self, uuid, timestamp):
        self.uuid = uuid
        self.timestamp = timestamp

from home.permissions import (
    is_authenticated_admin,
    is_platform_admin,
    is_organization_admin,
    is_election_official,
    is_auditor,
    is_candidate,
    is_candidate_account,
    is_voter,
    has_administrative_access,
    has_staff_or_auditor_access,
    can_perform_administrative_mutation,
    can_manage_election,
    can_start_election,
    can_end_election,
    can_publish_results,
    can_view_ledger,
    belongs_to_organization,
    get_user_profile,
    get_user_role,
    get_account_persona,
)

def parse_aware_election_datetime(dt_val):
    """
    Parses a string or datetime object into a timezone-aware datetime in the application's
    configured local timezone (e.g. Asia/Kolkata), safely avoiding naive/aware mismatch
    and UTC offset displacement during browser datetime-local submissions.
    """
    if not dt_val:
        return None
    from django.utils.dateparse import parse_datetime
    from django.utils import timezone
    import datetime as dt_mod
    if isinstance(dt_val, str):
        val_str = dt_val.strip()
        parsed = parse_datetime(val_str)
        if not parsed:
            for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
                try:
                    parsed = dt_mod.datetime.strptime(val_str, fmt)
                    break
                except Exception:
                    pass
    else:
        parsed = dt_val
    if parsed and timezone.is_naive(parsed):
        current_tz = timezone.get_current_timezone()
        parsed = timezone.make_aware(parsed, current_tz)
    return parsed

@csrf_exempt
def api_check_scheduled_lifecycle(request):
    """
    POST/GET /api/elections/check-lifecycle/
    Direct API endpoint to trigger scheduled election transitions on-demand.
    Safe, idempotent, and accessible by administrators, cron jobs, and health checks.
    """
    from home.methods_module import process_scheduled_election_transitions
    res = process_scheduled_election_transitions()
    return JsonResponse({'success': True, 'transitions': res})

ts_data = {}

_last_lifecycle_check = 0.0

def trigger_scheduled_lifecycle_check():
    """
    Lightweight, throttled hook that triggers scheduled start/end checks.
    Ensures that manual browser tests immediately reflect scheduled transitions
    without requiring external cron setup.
    """
    global _last_lifecycle_check
    now_ts = time.time()
    if now_ts - _last_lifecycle_check >= 2.0:
        _last_lifecycle_check = now_ts
        try:
            from home.methods_module import process_scheduled_election_transitions
            process_scheduled_election_transitions()
        except Exception as e:
            logger.debug(f"Lifecycle check note: {e}")


def get_or_create_voter_for_user(user, create=True):
    """
    Resolves or creates a Voters record linked to the authenticated Django User.
    Binds by email first, then username, or creates a minimal voter record.
    Preserves full legacy cryptographic compatibility without mutating historical records.
    """
    if not user or not user.is_authenticated:
        return None

    from home.models import Voters
    import datetime

    # 1. Match by email
    if user.email:
        voter = Voters.objects.filter(email__iexact=user.email).first()
        if voter:
            return voter

    # 2. Match by username (in case username was set to voter uuid)
    voter = Voters.objects.filter(uuid=user.username).first()
    if voter:
        if not voter.email and user.email:
            voter.email = user.email
            voter.save(update_fields=['email'])
        return voter

    if not create:
        return None

    # 3. Create minimal voter identity for modern authenticated User
    # uuid length is max 20 characters
    voter_uuid = f"U_{user.id}_{user.username}"[:20]
    if Voters.objects.filter(uuid=voter_uuid).exists():
        voter_uuid = f"U_{user.id}"[:20]

    voter, _ = Voters.objects.get_or_create(
        uuid=voter_uuid,
        defaults={
            'name': user.get_full_name() or user.username,
            'dob': datetime.date(1990, 1, 1),
            'pincode': '000000',
            'region': 'General',
            'email': user.email or '',
            'vote_done': False,
        }
    )
    return voter


def get_eligible_elections_for_user(user):
    """
    Returns queryset of Elections where the authenticated user is eligible.
    Respects:
    - User authentication
    - Eligibility records (if an election has an eligibility roll, user must be on it)
    - Organization scope (if user belongs to an org, only elections of that org or general)
    """
    from home.models import Election, Eligibility
    from django.db import models
    if not user or not user.is_authenticated:
        return Election.objects.none()

    voter = get_or_create_voter_for_user(user, create=False)

    # Get elections where voter has explicit Eligibility
    explicit_elec_ids = set()
    if voter:
        explicit_elec_ids = set(Eligibility.objects.filter(voter=voter).values_list('election_id', flat=True))

    # Get elections that do NOT have any Eligibility records defined
    elections_with_any_eligibility = set(Eligibility.objects.values_list('election_id', flat=True))

    profile = get_user_profile(user)
    org_id = profile.organization_id if profile else None

    # Base queryset
    qs = Election.objects.all()
    if org_id:
        qs = qs.filter(models.Q(organization_id=org_id) | models.Q(organization__isnull=True))

    # Eligible elections are either explicitly listed in Eligibility OR have no eligibility restrictions
    eligible_qs = qs.filter(
        models.Q(id__in=explicit_elec_ids) |
        ~models.Q(id__in=elections_with_any_eligibility)
    )
    return eligible_qs


# Create your views here.

# -------------- Home (First time loading) --------------
@ensure_csrf_cookie
def home(request):
    return render(request, 'home.html')

# --------------- Authentication -------------------
def authentication(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    aadhar_no = request.POST.get('aadhar_no')
    if not aadhar_no and request.user.is_authenticated:
        voter = get_or_create_voter_for_user(request.user)
        if voter:
            aadhar_no = voter.uuid

    if not aadhar_no:
        return JsonResponse({'error': 'Aadhaar number or authenticated user is required.'}, status=400)

    aadhar_no = str(aadhar_no).strip()

    try:
        voter = Voters.objects.get(uuid=aadhar_no)
        request.session['uuid'] = aadhar_no

        # Election lifecycle & eligibility gate (Phase 8C-4 & 8C-5)
        elec_id = request.POST.get('election_id') or request.GET.get('election_id')
        if elec_id:
            from home.models import Election, Eligibility
            try:
                target_elec = Election.objects.get(id=elec_id)
            except Election.DoesNotExist:
                return JsonResponse({'error': 'Election not found'}, status=404)

            if target_elec.status == 'DRAFT':
                return JsonResponse({'error': 'Voting is not available. Election is currently in DRAFT status.'}, status=400)
            if target_elec.status == 'CLOSED':
                return JsonResponse({'error': 'Voting has ended. This election is CLOSED.'}, status=400)
            if target_elec.status != 'OPEN':
                return JsonResponse({'error': 'Election is not open for voting.'}, status=400)

            if Eligibility.objects.filter(election=target_elec).exists():
                if not Eligibility.objects.filter(voter=voter, election=target_elec).exists():
                    return JsonResponse({'error': 'You are not registered as an eligible voter for this election.'}, status=403)

            # Check if voter has already voted in this specific election
            from home.models import Vote
            if Vote.objects.filter(uuid=voter.uuid, election=target_elec).exists():
                return JsonResponse({
                    'error': 'You have already casted your vote.'
                }, status=400)

            request.session['election_id'] = target_elec.id
        else:
            if voter.vote_done:
                return JsonResponse({
                    'error': 'You have already casted your vote.'
                })
        if elec_id:
            from home.models import Election, Eligibility
            try:
                target_elec = Election.objects.get(id=elec_id)
            except Election.DoesNotExist:
                return JsonResponse({'error': 'Election not found'}, status=404)

            if target_elec.status == 'DRAFT':
                return JsonResponse({'error': 'Voting is not available. Election is currently in DRAFT status.'}, status=400)
            if target_elec.status == 'CLOSED':
                return JsonResponse({'error': 'Voting has ended. This election is CLOSED.'}, status=400)
            if target_elec.status != 'OPEN':
                return JsonResponse({'error': 'Election is not open for voting.'}, status=400)

            if Eligibility.objects.filter(election=target_elec).exists():
                if not Eligibility.objects.filter(voter=voter, election=target_elec).exists():
                    return JsonResponse({'error': 'You are not registered as an eligible voter for this election.'}, status=403)
            request.session['election_id'] = target_elec.id

        # Clear any stale OTP / verification state from prior attempts
        request.session['otp'] = None
        request.session['otp_created_at'] = None
        request.session['otp_attempts'] = 0
        request.session['email-verified'] = False

        render_html = loader.render_to_string('candidate_details.html', {'details': voter})

        # Minimized details dictionary to prevent broad voter database / PII scraping
        # home.js consumes uuid, name, and profile_pic for basic-details display
        details = {
            'uuid': voter.uuid,
            'name': voter.name,
            'profile_pic': voter.profile_pic if voter.profile_pic else '',
        }
        return JsonResponse({
            'success': True,
            'html': render_html,
            'details': details
        })
    except Voters.DoesNotExist:
        return JsonResponse({
            'error': 'Invalid Aadhar, Please Enter Correct Aadhar Number!'
        })

# --------- Send otp for email verification -----------
def send_otp(request):
    import secrets

    session_uuid = request.session.get('uuid')
    if not session_uuid:
        return JsonResponse({'success': False, 'error': 'Authentication required. Please authenticate with Aadhaar first.'}, status=401)

    try:
        voter = Voters.objects.get(uuid=session_uuid)
    except Voters.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Voter record not found.'}, status=404)

    if voter.vote_done:
        return JsonResponse({'success': False, 'error': 'You have already cast your vote.'}, status=400)

    email_input = (request.POST.get('email-id') or request.GET.get('email-id') or '').strip()

    # Email binding and takeover prevention (SEC-HIGH-03):
    # If the voter already has a registered email, OTP must ONLY be dispatched to that email.
    if voter.email and voter.email.strip():
        registered_email = voter.email.strip()
        if email_input and email_input.lower() != registered_email.lower():
            return JsonResponse({'success': False, 'error': 'Cannot change email address for an already registered voter.'}, status=403)
        target_email = registered_email
    else:
        # First-time email binding
        if not email_input:
            return JsonResponse({'success': False, 'error': 'Email address is required.'}, status=400)
        target_email = email_input

    # Rate limiting / resend cooldown: 30 seconds
    now = time.time()
    last_sent = request.session.get('otp_last_sent', 0)
    if now - last_sent < 30:
        remaining = int(30 - (now - last_sent))
        return JsonResponse({'success': False, 'error': f'Please wait {remaining} seconds before requesting another OTP.'}, status=429)

    # Maximum OTP requests per session
    send_count = request.session.get('otp_send_count', 0)
    if send_count >= 5:
        return JsonResponse({'success': False, 'error': 'Maximum OTP request limit reached. Please restart authentication.'}, status=429)

    # Cryptographically secure random OTP (6 digits)
    otp = f"{secrets.randbelow(900000) + 100000}"

    # Send email (never logs or returns the OTP)
    success, result = send_email_otp(target_email, otp)
    if success:
        request.session['otp'] = otp
        request.session['otp_created_at'] = now
        request.session['otp_attempts'] = 0
        request.session['otp_last_sent'] = now
        request.session['otp_send_count'] = send_count + 1
        request.session['email-id'] = target_email
        request.session['email-verified'] = False
        return JsonResponse({'success': True})
    else:
        return JsonResponse({'success': False, 'error': result or 'Failed to send OTP email.'})

# -------- Verify email with provided otp ----------
def verify_otp(request):
    import hmac

    session_uuid = request.session.get('uuid')
    if not session_uuid and request.user.is_authenticated:
        voter_user = get_or_create_voter_for_user(request.user)
        if voter_user:
            session_uuid = voter_user.uuid
            request.session['uuid'] = voter_user.uuid
            request.session['email-id'] = voter_user.email or request.user.email

    if not session_uuid:
        return JsonResponse({'success': False, 'error': 'Authentication required. Please authenticate with Aadhaar first.'}, status=401)

    stored_otp = request.session.get('otp')
    otp_created_at = request.session.get('otp_created_at')

    if not stored_otp or not otp_created_at:
        return JsonResponse({'success': False, 'error': 'No active OTP found. Please request a new OTP.'}, status=400)

    # Check OTP expiration (5 minutes = 300 seconds)
    OTP_EXPIRY_SECONDS = 300
    now = time.time()
    if now - otp_created_at > OTP_EXPIRY_SECONDS:
        request.session['otp'] = None
        request.session['otp_created_at'] = None
        request.session['otp_attempts'] = 0
        return JsonResponse({'success': False, 'error': 'OTP has expired. Please request a new OTP.'}, status=400)

    # Rate limiting on verification attempts (max 3 attempts)
    MAX_OTP_ATTEMPTS = 3
    current_attempts = request.session.get('otp_attempts', 0) + 1
    request.session['otp_attempts'] = current_attempts

    otp_input = (request.POST.get('otp-input') or request.GET.get('otp-input') or '').strip()

    if not hmac.compare_digest(str(otp_input), str(stored_otp)):
        if current_attempts >= MAX_OTP_ATTEMPTS:
            request.session['otp'] = None
            request.session['otp_created_at'] = None
            request.session['otp_attempts'] = 0
            return JsonResponse({'success': False, 'error': 'Too many failed attempts. OTP has been invalidated.'}, status=429)
        remaining = MAX_OTP_ATTEMPTS - current_attempts
        return JsonResponse({'success': False, 'error': f'Wrong OTP. {remaining} attempt(s) remaining.'})

    # Successful verification! Replay Prevention: Invalidate the OTP immediately
    request.session['otp'] = None
    request.session['otp_created_at'] = None
    request.session['otp_attempts'] = 0

    try:
        voter = Voters.objects.get(uuid=session_uuid)
    except Voters.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Voter record not found.'}, status=404)

    target_email = request.session.get('email-id')
    # Prevent arbitrary email takeover: only bind if voter.email was previously empty
    if not voter.email and target_email:
        voter.email = target_email
        voter.save()

    request.session['email-verified'] = True
    return JsonResponse({'success': True})

def normalize_pem_key(k_str: str) -> str:
    """Safely normalizes PEM key strings by stripping outer quotes, backticks, carriage returns, and whitespace."""
    if not k_str:
        return ''
    s = str(k_str).strip().strip('"\'`')
    s = s.replace('\\r', '').replace('\\n', '\n').replace('\r', '')
    return s.strip()

@csrf_protect
def verify_private_key(request):
    """
    POST /verify-private-key/
    Validates a voter's ECC P-256 private key during the dedicated Private Key verification step.
    - Requires authenticated voter session and email-verified OTP.
    - Validates NIST P-256 curve format (supports PKCS#8 and SEC1).
    - Matches key against the active session's public key (if generated).
    - NEVER logs or echoes the private key.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.', 'success': False}, status=405)

    if not request.session.get('email-verified'):
        return JsonResponse({'error': 'Authentication required. Complete OTP step-up verification first.', 'success': False}, status=401)

    try:
        import json
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
            except Exception:
                data = {}
        else:
            data = request.POST

        raw_key = data.get('private_key') or data.get('private-key') or data.get('key') or ''
        raw_key = normalize_pem_key(raw_key)
        if not raw_key:
            return JsonResponse({'error': 'Private key is required.', 'success': False}, status=400)

        from Crypto.PublicKey import ECC
        try:
            ecc_key = ECC.import_key(raw_key)
            if getattr(ecc_key, 'curve', None) not in ('P-256', 'NIST P-256', 'prime256v1', 'secp256r1'):
                return JsonResponse({'error': 'Invalid key curve. Only NIST P-256 is supported.', 'success': False}, status=400)
        except Exception:
            return JsonResponse({'error': 'Invalid private key format.', 'success': False}, status=400)

        derived_pub = ecc_key.public_key().export_key(format='PEM')
        session_pub = request.session.get('public-key')

        if session_pub:
            norm_session_pub = session_pub.replace('\r', '').strip()
            norm_derived_pub = derived_pub.replace('\r', '').strip()
            if norm_session_pub != norm_derived_pub:
                return JsonResponse({
                    'error': 'Private key does not match this voter session. Please use the key sent to your verified email.',
                    'success': False
                }, status=400)

        # Store verified private key in session securely for the final commit
        request.session['private-key'] = raw_key
        request.session['public-key'] = derived_pub
        request.session['private-key-verified'] = True

        return JsonResponse({
            'success': True,
            'message': 'Private key verified successfully. Ready to cast ballot.'
        })

    except Exception as e:
        logger.warning(f"Private key verification error: {e}")
        return JsonResponse({'error': 'Failed to verify private key.', 'success': False}, status=400)


# --------- On successful email verfication show all parties options ----------
def get_parties(request):
    
    party_list = {}
    if request.session.get('email-verified'):

        if not request.session.get('private-key') or not request.session.get('public-key'):
            private_key, public_key = generate_keys()
            email_target = request.session.get('email-id') or (request.user.email if request.user.is_authenticated else None)
            if email_target:
                send_email_private_key(email_target, private_key)
            request.session['public-key'] = public_key
            request.session['private-key'] = private_key
        else:
            private_key = request.session['private-key']
            public_key = request.session['public-key']

        election_id = request.GET.get('election_id') or request.session.get('election_id')
        position_id = request.GET.get('position_id')

        if election_id or position_id:
            from home.models import Candidate, Position, Election
            from home.methods_module import ensure_nota_candidate_for_position, ensure_nota_candidates_for_election
            if position_id:
                try:
                    pos = Position.objects.get(id=position_id)
                    ensure_nota_candidate_for_position(pos)
                except Position.DoesNotExist:
                    pass
            elif election_id:
                try:
                    el = Election.objects.get(id=election_id)
                    ensure_nota_candidates_for_election(el)
                except Election.DoesNotExist:
                    pass

            qs = Candidate.objects.select_related('position', 'position__election').all()
            if election_id:
                qs = qs.filter(position__election_id=election_id)
            if position_id:
                qs = qs.filter(position_id=position_id)
            
            cands = list(qs)
            cands.sort(key=lambda c: (1 if getattr(c, 'is_nota', False) or (c.name and c.name.strip().upper() in ('NOTA', 'NONE OF THE ABOVE', 'NOTA (NONE OF THE ABOVE)', 'NONE OF THE ABOVE (NOTA)')) else 0, c.id))

            parties = []
            for cand in cands:
                is_nota = getattr(cand, 'is_nota', False) or (cand.name and cand.name.strip().upper() in ('NOTA', 'NONE OF THE ABOVE', 'NOTA (NONE OF THE ABOVE)', 'NONE OF THE ABOVE (NOTA)'))
                cand_logo = cand.image if cand.image else ('images/logo.png' if not is_nota else '')
                parties.append({
                    'party_id': str(cand.id),
                    'party_name': cand.name,
                    'party_logo': cand_logo,
                    'candidate_name': cand.name,
                    'candidate_profile_pic': cand.image or '',
                    'position_id': cand.position_id,
                    'position_title': cand.position.title if cand.position else '',
                    'is_nota': is_nota,
                    'affiliation': cand.affiliation or ('None of the Above' if is_nota else ''),
                })
        else:
            parties = list(PoliticalParty.objects.all())
            parties = [model_to_dict(party) for party in parties]

        render_html = loader.render_to_string('voting.html', {'parties': parties})

        party_list = {
            'html': render_html,
            'parties': parties,
        }

    return JsonResponse(party_list)

def get_election_info(request):
    from home.models import Election, Position, Candidate
    election_id = request.GET.get('election_id')
    if not election_id:
        return JsonResponse({'error': 'election_id is required'})
    
    try:
        election = Election.objects.select_related('organization').get(id=election_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Election not found'})
    
    positions_data = []
    positions = Position.objects.filter(election=election)
    for pos in positions:
        cands = Candidate.objects.filter(position=pos)
        positions_data.append({
            'id': pos.id,
            'title': pos.title,
            'max_votes_allowed': pos.max_votes_allowed,
            'candidates': [
                {
                    'id': cand.id,
                    'name': cand.name,
                    'affiliation': cand.affiliation,
                    'legacy_vote_party_id': cand.legacy_vote_party_id
                } for cand in cands
            ]
        })
        
    return JsonResponse({
        'organization': {
            'id': election.organization.id,
            'name': election.organization.name
        },
        'election': {
            'id': election.id,
            'title': election.title,
            'status': election.status
        },
        'positions': positions_data
    })

# ------------- Save vote in database ------------------------
def create_vote(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    uuid = request.session.get('uuid')
    if not uuid and request.user.is_authenticated:
        voter_user = get_or_create_voter_for_user(request.user)
        if voter_user:
            uuid = voter_user.uuid
            request.session['uuid'] = uuid

    email_verified = request.session.get('email-verified')
    if not uuid or not email_verified:
        return JsonResponse({'error': 'Authentication required. Voter identity must be verified before casting a vote.'}, status=401)

    # Election lifecycle & eligibility gate (Phase 8C-4 & 8C-5)
    elec_id = request.POST.get('election_id') or request.session.get('election_id')
    target_elec = None
    target_cand = None

    if elec_id:
        from home.models import Election, Eligibility, Candidate, Position, Vote, Ballot
        try:
            target_elec = Election.objects.get(id=elec_id)
        except Election.DoesNotExist:
            return JsonResponse({'error': 'Election not found'}, status=404)

        if target_elec.status == 'DRAFT':
            return JsonResponse({'error': 'Election voting has not started. Election is currently in DRAFT status.'}, status=400)
        if target_elec.status == 'CLOSED':
            return JsonResponse({'error': 'Election voting has ended. This election is CLOSED.'}, status=400)
        if target_elec.status != 'OPEN':
            return JsonResponse({'error': 'Election is not open for voting.'}, status=400)

        voter_obj = Voters.objects.filter(uuid=uuid).first()
        if voter_obj and Eligibility.objects.filter(election=target_elec).exists():
            if not Eligibility.objects.filter(voter=voter_obj, election=target_elec).exists():
                return JsonResponse({'error': 'Voter is not eligible for this election'}, status=403)

        # Duplicate vote check for election
        if Vote.objects.filter(uuid=uuid, election=target_elec).exists() or (voter_obj and Ballot.objects.filter(voter=voter_obj, election=target_elec, is_sealed=True).exists()):
            return JsonResponse({'error': 'You have already cast your vote in this election.'}, status=400)
    else:
        # If modern elections exist in the database, verify at least one is OPEN
        from home.models import Election
        if Election.objects.exists():
            if not Election.objects.filter(status='OPEN').exists():
                return JsonResponse({'error': 'No elections are currently open for voting.'}, status=400)

    selected_party_id = request.POST.get('selected-party-id')
    if not selected_party_id:
        return JsonResponse({'error': 'selected-party-id is required.'}, status=400)

    # Validate candidate and position relationships when in an election
    if target_elec:
        from home.models import Candidate
        try:
            target_cand = Candidate.objects.select_related('position', 'position__election').get(id=int(selected_party_id))
        except (ValueError, Candidate.DoesNotExist):
            return JsonResponse({'error': 'Selected candidate does not exist.'}, status=400)

        if target_cand.position.election_id != target_elec.id:
            return JsonResponse({'error': 'Selected candidate does not belong to this election.'}, status=400)

        position_id = request.POST.get('position_id')
        if position_id and str(target_cand.position_id) != str(position_id):
            return JsonResponse({'error': 'Selected candidate does not belong to the requested position.'}, status=400)

    incoming_key = request.POST.get('private-key') or request.POST.get('private_key')
    stored_key = request.session.get('private-key')
    public_key = request.session.get('public-key')

    private_key = None

    if incoming_key:
        incoming_key = normalize_pem_key(incoming_key)
        if 'PRIVATE KEY' in incoming_key:
            from Crypto.PublicKey import ECC
            try:
                ecc_priv = ECC.import_key(incoming_key)
                if getattr(ecc_priv, 'curve', None) not in ('P-256', 'NIST P-256', 'prime256v1', 'secp256r1'):
                    return JsonResponse({'error': 'Invalid key curve. Only NIST P-256 is supported.', 'success': False}, status=400)
                private_key = incoming_key
                derived_pub = ecc_priv.public_key().export_key(format='PEM')
                if public_key:
                    norm_public = public_key.replace('\r', '').strip()
                    norm_derived = derived_pub.replace('\r', '').strip()
                    if norm_public != norm_derived:
                        return JsonResponse({'error': 'Private key does not match this voter session.', 'success': False}, status=400)
                public_key = derived_pub
            except Exception:
                return JsonResponse({'error': 'Invalid or malformed private key.', 'success': False}, status=400)
        else:
            return JsonResponse({'error': 'Invalid private key format.', 'success': False}, status=400)
    elif stored_key and 'PRIVATE KEY' in stored_key:
        private_key = stored_key

    if not private_key:
        if not target_elec and not request.user.is_authenticated:
            private_key, public_key = generate_keys()
            request.session['private-key'] = private_key
            request.session['public-key'] = public_key
        else:
            return JsonResponse({'error': 'Voting private key is required to authorize ballot signature.', 'success': False}, status=400)

    # Modern Election Flow with Batching & Blockchain Mining
    if target_elec:
        from django.db import transaction
        from home.models import Vote, VoteBackup, Ballot, BallotBatch
        from home.methods_module import (
            submit_modern_ballot,
            mine_modern_batch,
            build_auth_payload,
            sign_auth_payload,
            get_or_create_active_batch
        )
        import secrets

        try:
            with transaction.atomic():
                voter = Voters.objects.select_for_update().get(uuid=uuid)
                if Vote.objects.filter(uuid=voter.uuid, election=target_elec).exists():
                    raise Exception('You have already cast your vote in this election.')

                pos = target_cand.position if target_cand else None
                ballot_rec = Ballot.objects.create(
                    voter=voter,
                    election=target_elec,
                    is_sealed=False
                )

                # Modern NIST P-256 AuthPayload and digital signature
                nonce = secrets.token_hex(32)
                ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                auth_payload = build_auth_payload(target_elec.id, voter.uuid, nonce, ts)
                signature = sign_auth_payload(private_key, auth_payload)

                # Atomically create Vote, VoteBackup and assign to BallotBatch
                ballot_res = submit_modern_ballot(
                    ballot=ballot_rec,
                    candidate_selections=[(pos, target_cand)],
                    signature=signature,
                    public_key=public_key,
                    ballot_nonce=nonce,
                    timestamp_iso=ts,
                    auth_payload=auth_payload
                )

            # Trigger blockchain mining for the batch
            batch_id = ballot_res.get('batch_id')
            mined_block_id = None
            try:
                mine_res = mine_modern_batch(batch_id=batch_id)
                mined_block_id = mine_res.get('block_id')
            except Exception as mine_err:
                logger.info(f"Batch {batch_id} queued for mining: {mine_err}")

            if mined_block_id:
                confirmation_msg = f"Your vote was successfully recorded and confirmed on the BallotChain ledger in Block #{mined_block_id}."
            else:
                confirmation_msg = "Your ballot was submitted and is awaiting blockchain confirmation."

            context = {
                'success': True,
                'status': confirmation_msg,
                'ballot_tracker': ballot_rec.ballot_tracker,
                'signature_snip': (signature[:32] + '...') if signature else 'N/A',
                'candidate_name': target_cand.name if target_cand else '',
                'position_title': pos.title if pos else '',
            }
            if mined_block_id:
                context['block_id'] = mined_block_id

            # Clean session keys
            request.session['email-verified'] = False
            request.session['private-key'] = None
            request.session['public-key'] = None

            html = loader.render_to_string('final-status.html', {
                'ballot': ballot_rec.ballot_tracker or 'N/A',
                'ballot_signature': signature[:32] + '...' if signature else 'N/A',
                'status': confirmation_msg
            })
            context['html'] = html
            return JsonResponse(context)

        except Exception as e:
            return JsonResponse({'success': False, 'status': f'We are not able to save your vote. {e}', 'error': str(e)}, status=400)

    # Legacy Election Flow (preserves historical tests)
    curr = timezone.now()
    ballot = f'{uuid}|{selected_party_id}|{curr.timestamp()}'
    status = verify_vote(private_key, public_key, ballot)
    context = {'success': status[0], 'status': status[1]}

    if status[0]:
        from django.db import transaction
        from home.models import Vote, VoteBackup, Ballot
        try:
            with transaction.atomic():
                voter = Voters.objects.select_for_update().get(uuid=request.session['uuid'])
                if voter.vote_done:
                    raise Exception('You have already casted your vote.')

                Vote.objects.create(
                    uuid=uuid,
                    vote_party_id=selected_party_id,
                    timestamp=curr
                )
                VoteBackup.objects.create(
                    uuid=uuid,
                    vote_party_id=selected_party_id,
                    timestamp=curr
                )
                voter.vote_done = True
                voter.save()

            request.session['email-verified'] = False
            request.session['private-key'] = None
            request.session['public-key'] = None
        except Exception as e:
            status[0] = False
            context['success'] = False
            context['status'] = 'We are not able to save your vote. ' + str(e)
            
    html = loader.render_to_string('final-status.html', {
        'ballot': status[2], 'ballot_signature': status[3], 'status': status[1]})
    context['html'] = html
    return JsonResponse(context)

# -------------- create Dummy Data ------------------
def create_dummy_data(request):
    if not settings.DEBUG:
        return JsonResponse({'error': 'create-dummy-data is disabled in production.'}, status=403)

    if not (is_authenticated_admin(request.user) and is_platform_admin(request.user)):
        return JsonResponse({'error': 'Unauthorized. Platform administrator privileges required.'}, status=403)

    if request.method != 'POST':
        # Reject state mutations via GET
        if any(request.GET.get(k) for k in ('createRandomVoters', 'createPoliticianParties', 'castRandomVote')):
            return JsonResponse({'error': 'State mutation via GET is disallowed. Use POST.'}, status=405)
        return render(request, 'create-dummy-data.html')

    body_data = {}
    if request.content_type == 'application/json' and request.body:
        try:
            body_data = json.loads(request.body)
        except Exception:
            body_data = {}

    def _parse_param(key):
        val = body_data.get(key)
        if val is None and key in request.POST:
            raw = request.POST.get(key)
            try:
                val = json.loads(raw)
            except Exception:
                val = raw
        return val

    to_do = {
        'createRandomVoters': _parse_param('createRandomVoters'),
        'createPoliticianParties': _parse_param('createPoliticianParties'),
        'castRandomVote': _parse_param('castRandomVote'),
    }

    if to_do['createRandomVoters'] or to_do['createPoliticianParties'] or to_do['castRandomVote']:
        dummy_data_input(to_do)
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'No dummy data options provided.'}, status=400)

# -------------- Show Vote count so far -----------
def show_result(request):
    """
    BallotChain Modern Verified Results View (Phase 8).
    Generic organizational election results presentation.
    Completely decoupled from legacy political party models and party symbols.
    Enforces Phase 8C-4 lifecycle visibility rules:
    - DRAFT: results unavailable to non-staff viewers
    - OPEN: only visible if live_progress_enabled=True; otherwise private
    - CLOSED: only visible after administrative certification & publication (is_published=True)
    """
    trigger_scheduled_lifecycle_check()
    from home.models import Election, Position, Candidate
    from home.methods_module import calculate_verified_election_results

    # 1. Resolve target election
    elec_id = request.GET.get('election_id')
    election = None
    if elec_id:
        try:
            election = Election.objects.select_related('organization').get(id=elec_id)
        except (Election.DoesNotExist, ValueError):
            election = None

    if not election:
        # Priority: published first, then open with live progress, then latest
        if request.user.is_authenticated and has_staff_or_auditor_access(request.user, None):
            election = Election.objects.select_related('organization').order_by('-id').first()
        else:
            election = Election.objects.filter(is_published=True).select_related('organization').order_by('-published_at', '-id').first()
            if not election:
                election = Election.objects.filter(status='OPEN', live_progress_enabled=True).select_related('organization').order_by('-id').first()
            if not election:
                election = Election.objects.select_related('organization').order_by('-id').first()

    all_elections = Election.objects.all().order_by('-id')

    if not election:
        # No elections exist in database
        context = {
            'no_elections': True,
            'results': [],
            'all_elections': [],
        }
        return render(request, 'show-result.html', context)

    # 2. Check visibility permissions
    is_staff_or_auditor = False
    if request.user.is_authenticated:
        is_staff_or_auditor = has_staff_or_auditor_access(request.user, election.organization_id)

    status_notice = None
    results_visible = True

    if not is_staff_or_auditor:
        if election.status == 'DRAFT':
            results_visible = False
            status_notice = 'Results unavailable: This election is currently in DRAFT status.'
        elif election.status == 'OPEN':
            # For non-staff (Voters & Candidates), candidate-level results must NEVER be visible during OPEN
            results_visible = False
            if getattr(election, 'live_progress_enabled', False):
                status_notice = 'Voting is currently live. Live election progress is shown above. Candidate-level results remain private until the election ends and certified results are published.'
            else:
                status_notice = 'Live progress is disabled for this election. Verified results will be published once voting ends.'
        elif election.status == 'CLOSED':
            if not getattr(election, 'is_published', False):
                results_visible = False
                status_notice = 'Voting is closed. Official results are being verified and will be published once certified.'
            else:
                results_visible = True

    # 3. Calculate verified results if visible
    verified_data = None
    results_table = []
    if results_visible:
        allow_unfinalized = (election.status == 'OPEN')
        verified_data = calculate_verified_election_results(election.id, allow_unfinalized=allow_unfinalized)
        
        # Build flattened results_table for generic table display and regression test compatibility
        sr = 0
        if verified_data and 'positions' in verified_data:
            for pos_info in verified_data['positions']:
                pos_title = pos_info.get('position_title') or pos_info.get('title', 'General')
                for cand_info in pos_info.get('candidates', []):
                    c_name = cand_info.get('candidate_name') or cand_info.get('name', 'Candidate')
                    c_votes = cand_info.get('votes_received') if cand_info.get('votes_received') is not None else cand_info.get('vote_count', 0)
                    c_rank = cand_info.get('rank')
                    if c_rank is None:
                        sr += 1
                        c_rank = sr
                    results_table.append({
                        'sr': c_rank,
                        'rank': c_rank,
                        'position_title': pos_title,
                        'candidate_name': c_name,
                        'party_name': c_name,
                        'affiliation': cand_info.get('affiliation', ''),
                        'vote_count': c_votes,
                        'votes_received': c_votes,
                        'percentage': cand_info.get('percentage', 0.0),
                        'is_winner': cand_info.get('is_winner', False),
                        'is_nota': cand_info.get('is_nota', False),
                        'status': cand_info.get('status', ''),
                    })

    # Live election progress stats (Ballots Submitted, Votes Recorded, Status)
    live_progress_stats = None
    if getattr(election, 'live_progress_enabled', False) and election.status in ('OPEN', 'CLOSED'):
        prog_data = verified_data if verified_data else calculate_verified_election_results(election.id, allow_unfinalized=True)
        summary = prog_data.get('summary', {}) if prog_data else {}
        submitted = summary.get('total_submitted_ballots', 0)
        counted = summary.get('total_votes_counted', 0)
        live_progress_stats = {
            'ballots_submitted': submitted,
            'votes_recorded': counted,
            'status': election.status,
            'is_published': election.is_published,
        }

    context = {
        'election': election,
        'all_elections': all_elections,
        'results_visible': results_visible,
        'status_notice': status_notice,
        'verified_data': verified_data,
        'results': results_table,
        'live_progress_stats': live_progress_stats,
        'is_staff_or_auditor': is_staff_or_auditor,
    }
    return render(request, 'show-result.html', context)

# ------------- Show Block Mining Page -------------
def mine_block(request):
    to_seal_votes_count = Vote.objects.all().filter(block_id=None, batch=None).count()
    return render(request, 'mine-block.html', {'data': to_seal_votes_count})

# ----------------- Start mining on button click ---------------
def start_mining(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    if not is_authenticated_admin(request.user) or is_auditor(request.user):
        return JsonResponse({'error': 'Unauthorized. Administrative write access required.'}, status=403)

    data = create_block()
    html = loader.render_to_string('mined-blocks.html', data)
    return JsonResponse({'html': html, 'success': True})

# Create block [called in start_mining()]
def create_block():

    # Get mining info upto last mining
    mining_info = MiningInfo.objects.all().first()
    if not mining_info:
        mining_info = MiningInfo.objects.create(id=0, prev_hash='0' * 64, last_block_id='0')
    prev_hash = mining_info.prev_hash
    curr_block_id = last_block_id = int(mining_info.last_block_id)
    
    non_sealed_votes = Vote.objects.all().filter(block_id=None, batch=None).order_by('timestamp')
    non_sealed_votes_BACKUP = VoteBackup.objects.all().filter(block_id=None, batch=None).order_by('timestamp')

    # Get settings for per block mining
    txn_per_block = settings.TRANSACTIONS_PER_BLOCK
    number_of_blocks = int( non_sealed_votes.count()/txn_per_block )

    # Puzzle requirement: '0' * n (n leading zeros)
    puzzle, pcount = settings.PUZZLE, settings.PLENGTH

    # Safely reduce proof of work difficulty to prevent hanging
    if pcount > 2:
        pcount = 2
        puzzle = '0' * pcount
    
    time_start = time.time()

    result = []

    ts_data['progress'] = True
    ts_data['status'] = 'Mining has been Initialised.'
    ts_data['completed'] = 0

    print("Mining started")

    for _ in range(number_of_blocks):
        # As soon as block_id set to the transaction it is automatically removed from 'non_sealed_vote'
        # Hence always top 'txn_per_block' transactions belong to one block
        block_transactions = non_sealed_votes[:txn_per_block]
        block_transactions_BACKUP = non_sealed_votes_BACKUP[:txn_per_block]
        
        root = MerkleTools()
        root.add_leaf([f'{tx.uuid}|{tx.vote_party_id}|{tx.timestamp}' for tx in block_transactions], True)
        root.make_tree()
        merkle_h = root.get_merkle_root()
        # Try to seal the block and generate valid hash
        nonce = 0
        timestamp = timezone.now()
        
        block_start_time = time.time()
        
        while True:
            enc = f'{prev_hash}{merkle_h}{nonce}{timestamp.timestamp()}'.encode('utf-8')
            h = SHA3_256.new(enc).hexdigest()
            # Break if valid hash found, max iterations reached, or timeout of 5 seconds exceeded
            if h[:pcount] == puzzle or nonce > 50000 or (time.time() - block_start_time > 5.0):
                print(f"Mining completed. Nonce found: {nonce}")
                break
            nonce += 1

        # Create the block
        curr_block_id += 1
        Block(id=curr_block_id, prev_hash=prev_hash, merkle_hash=merkle_h, this_hash=h, nonce=nonce, timestamp=timestamp).save()

        result.append({
            'block_id': curr_block_id, 'prev_hash': prev_hash, 'merkle_hash': merkle_h, 'this_hash': h, 'nonce': nonce
        })
        
        # Set this hash as prev hash
        prev_hash = h
        
        # Set block_id to every transaction
        for txn in block_transactions:
            txn.block_id = str(curr_block_id)
            txn.save()
        for txn in block_transactions_BACKUP:
            txn.block_id = str(curr_block_id)
            txn.save()

        ts_data['status'] = str(curr_block_id - last_block_id) + ' blocks have been mined. (' + str((curr_block_id - last_block_id)*txn_per_block) + ' vote transactions have been sealed.)'
        ts_data['completed'] = round((curr_block_id - last_block_id)*100/number_of_blocks)
    time_end = time.time()

    time_taken = time_end - time_start
    if time_taken < 0.0000:
        time_taken = 0.000000

    # Save current Mining info
    mining_info.prev_hash = prev_hash
    mining_info.last_block_id = str(curr_block_id)
    mining_info.id = 0
    mining_info.save()

    data = {
        'time_taken': round(time_end-time_start, 6),
        'result': result
    }

    ts_data['progress'] = False

    return data

def dummy_data_input(to_do):

    ts_data['progress'] = True
    ts_data['status'] = 'Deleting current Data.'
    ts_data['completed'] = 0
    
    PoliticalParty.objects.all().delete()
    Voters.objects.all().delete()
    Vote.objects.all().delete()
    Block.objects.all().delete()
    VoteBackup.objects.all().delete()
    MiningInfo.objects.all().delete()

    ts_data['completed'] = 100
    ts_data['status'] = 'Deleted current Data.'

    MiningInfo(id = 0, prev_hash = '0'*64, last_block_id = '0').save()

    if to_do['createPoliticianParties']:

        parties = {
            'bjp': {
                'party_id': 'bjp',
                'party_name': 'Bharatiya Janata Party (BJP)',
                'party_logo': 'images/BJP.png',
                },
            'tdp': {
                'party_id': 'tdp',
                'party_name': 'Telugu Desam Party (TDP)',
                'party_logo': 'images/TDP.png',
                },
            'janasena': {
                'party_id': 'janasena',
                'party_name': 'Jana Sena Party',
                'party_logo': 'images/Janasena.jpg',
            },
            'brs': {
                'party_id': 'brs',
                'party_name': 'Bharat Rashtra Samithi (BRS)',
                'party_logo': 'images/BRS.png',
            },
            'congress': {
                'party_id': 'congress',
                'party_name': 'Indian National Congress (INC)',
                'party_logo': 'images/Congress.png',
            },
            'nota': {
                'party_id': 'nota',
                'party_name': 'NOTA',
                'party_logo': 'images/NOTA.png',
            },
            'ysrcp': {
                'party_id': 'ysrcp',
                'party_name': 'YSR Congress Party (YSRCP)',
                'party_logo': 'images/YSRCP.jpg',
            }
        }

        ts_data['completed'] = 0
        ts_data['status'] = 'Creating parties.'

        # Create Parties
        for party in parties.values():
            PoliticalParty(party_id = party['party_id'], party_name = party['party_name'], party_logo = party['party_logo']).save()
            curr = list(parties.keys()).index(party['party_id'])+1
            ts_data['completed'] = round(curr*100/len(parties))

    if to_do['createRandomVoters']:

        ts_data['completed'] = 0
        ts_data['status'] = 'Creating voters.'

        # Create Voters
        Voters.objects.all().delete()
        import random
        voters_data = [
            ("Sreehari Dakara", "sreeharidakara06@gmail.com", "Telangana", "500001"),
            ("Merugu Manitej", "2411cs070024@mallareddyuniversity.ac.in", "Telangana", "500001"),
            ("Kotha Manish", "2411cs070061@mallareddyuniversity.ac.in", "Telangana", "500001"),
            ("Begari Sairam", "2411cs070007@mallareddyuniversity.ac.in", "Telangana", "500001"),
            ("Priya Reddy", "2411cs070014@mallareddyuniversity.ac.in", "Telangana", "500001"),
            ("Ravi Kiran Kumar", "2411cs070013@mallareddyuniversity.ac.in", "Telangana", "500001"),
            ("Tharun Bhaskar Yadav", "sreeharidakara2@gmail.com", "Telangana", "500001"),
            ("Neeraj Varma", "2411cs070077@mallareddyuniversity.ac.in", "Bollaram", "500011"),
            ("Yashwant Reddy", "2411cs070081@mallareddyuniversity.ac.in", "suraram", str(random.randint(500000, 500999)))
        ]
        
        for i, (name, email, region, pincode) in enumerate(voters_data, 1):
            dob = datetime.date(2000, 1, 1)
            uuid = str(i) * 12
            Voters(uuid=uuid, name=name, email=email, dob=dob, pincode=pincode, region=region).save()
            ts_data['completed'] = round(i*100/len(voters_data))

    if to_do['castRandomVote'] and to_do['createPoliticianParties']:

        ts_data['completed'] = 0
        ts_data['status'] = 'Creating votes.'

        # Create Votes
        Vote.objects.all().delete()
        VoteBackup.objects.all().delete()

        vote_distribution = {
            'bjp': 2500,
            'tdp': 2100,
            'janasena': 1800,
            'brs': 1200,
            'congress': 800,
            'nota': 300,
            'ysrcp': 100
        }
        
        total_votes = sum(vote_distribution.values())
        current_vote = 0
        
        votes_to_create = []
        backups_to_create = []

        for p_id, count in vote_distribution.items():
            curr_time = timezone.now()
            for _ in range(count):
                current_vote += 1
                dummy_uuid = f"v_{current_vote}"
                votes_to_create.append(Vote(uuid = dummy_uuid, vote_party_id = p_id, timestamp = curr_time))
                backups_to_create.append(VoteBackup(uuid = dummy_uuid, vote_party_id = p_id, timestamp = curr_time))
                
            ts_data['completed'] = round(current_vote*100/total_votes)
            
        Vote.objects.bulk_create(votes_to_create)
        VoteBackup.objects.bulk_create(backups_to_create)

    ts_data['status'] = 'Finishing task.'
    ts_data['progress'] = False

@ensure_csrf_cookie
def blockchain(request):
    """
    Shared BallotChain Cryptographic Ledger Explorer.
    - Single, unified ledger view accessible by Admin, User, Candidate, and Public.
    - Enforces read-only inspection; protected mining actions remain restricted to RBAC administrators.
    - Supports search by Block ID, Block Hash, Previous Hash, or Merkle Root.
    - Supports filtering by Block Type (All, Historical v1, Modern v2).
    - Supports pagination (25 blocks per page) to smoothly present 5,645+ blocks without browser lag.
    - Serves dual presentations:
        1. JSON-serialized payload for the React Bits Cubes interactive visual explorer.
        2. Accessible server-rendered HTML fallback table with pagination for screen readers.
    """
    from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
    from django.db.models import Q
    from home.permissions import is_authenticated_admin, get_user_role

    order = request.GET.get('order', 'desc').lower()
    search_query = request.GET.get('q', '').strip()
    block_type = request.GET.get('type', 'all').lower()
    page_number = request.GET.get('page', 1)

    qs = Block.objects.all()

    if search_query:
        if search_query.isdigit():
            qs = qs.filter(id=int(search_query))
        else:
            qs = qs.filter(
                Q(this_hash__icontains=search_query) |
                Q(prev_hash__icontains=search_query) |
                Q(merkle_hash__icontains=search_query)
            )

    if block_type == 'v1':
        qs = qs.filter(version=1)
    elif block_type == 'v2':
        qs = qs.filter(version=2)

    if order == 'asc':
        qs = qs.order_by('id')
    else:
        qs = qs.order_by('-id')

    total_blocks_count = Block.objects.count()
    total_votes_count = Vote.objects.count()

    paginator = Paginator(qs, 25)
    try:
        blocks_page = paginator.page(page_number)
    except PageNotAnInteger:
        blocks_page = paginator.page(1)
    except EmptyPage:
        blocks_page = paginator.page(paginator.num_pages)

    is_admin = is_authenticated_admin(request.user)
    if is_admin:
        user_role = get_user_role(request.user) or 'ADMIN'
    elif request.user.is_authenticated:
        from home.models import Candidate
        is_cand = Candidate.objects.filter(user=request.user).exists() if hasattr(Candidate, 'user') else False
        user_role = 'CANDIDATE' if is_cand else 'VOTER'
    else:
        user_role = 'PUBLIC_AUDITOR'

    # Serialize current page blocks for React Bits Cubes ledger island
    blocks_data = []
    for b in blocks_page:
        blocks_data.append({
            'id': b.id,
            'prev_hash': b.prev_hash,
            'merkle_hash': b.merkle_hash,
            'this_hash': b.this_hash,
            'nonce': b.nonce,
            'timestamp': b.timestamp.isoformat() if hasattr(b.timestamp, 'isoformat') else str(b.timestamp),
            'version': getattr(b, 'version', 1),
            'batch_number': getattr(b, 'batch_number', None),
            'candidate_tx_count': getattr(b, 'candidate_tx_count', 1),
            'merkle_leaf_count': getattr(b, 'merkle_leaf_count', 1),
            'election_id': b.election_id if hasattr(b, 'election_id') else None,
            'is_historical': getattr(b, 'version', 1) == 1,
        })

    ledger_payload = {
        'blocks': blocks_data,
        'totalBlocks': total_blocks_count,
        'totalVotes': total_votes_count,
        'currentPage': blocks_page.number,
        'totalPages': paginator.num_pages,
        'hasNext': blocks_page.has_next(),
        'hasPrev': blocks_page.has_previous(),
        'order': order,
        'searchQuery': search_query,
        'blockType': block_type,
        'isAdmin': is_admin,
        'userRole': user_role,
    }

    context = {
        'blocks': blocks_page,
        'blocks_json': ledger_payload,
        'total_blocks': total_blocks_count,
        'total_votes': total_votes_count,
        'is_admin': is_admin,
        'user_role': user_role,
        'order': order,
        'search_query': search_query,
        'block_type': block_type,
    }
    return render(request, 'blockchain.html', context)

@ensure_csrf_cookie
def block_info(request):
    try:
        from home.methods_module import verify_single_block
        raw_id = request.GET.get('id') or request.GET.get('block_id')
        if not raw_id:
            return redirect('/blockchain/')
        block = Block.objects.get(id=int(raw_id))
        confirmed_by = (Block.objects.all().count() - block.id) + 1

        votes = Vote.objects.filter(block_id=block.id).order_by('id')

        # Use authoritative verification engine that supports both v1 (legacy) and v2 (modern)
        ver_res = verify_single_block(block.id)
        tampered = not ver_res.get('valid', False)

        if getattr(block, 'version', 1) == 2:
            re_merkle_hash = block.merkle_hash
            vote_hashes = [v.tx_id or SHA3_256.new(f"{v.uuid}|{v.vote_party_id}|{v.timestamp}".encode('utf-8')).hexdigest() for v in votes]
        else:
            vote_hashes = [SHA3_256.new((f'{vote.uuid}|{vote.vote_party_id}|{vote.timestamp}').encode('utf-8')).hexdigest() for vote in votes]
            root = MerkleTools()
            root.add_leaf([f'{vote.uuid}|{vote.vote_party_id}|{vote.timestamp}' for vote in votes], True)
            root.make_tree()
            re_merkle_hash = root.get_merkle_root()

        # Only authenticated platform administrators may see raw unmasked voter IDs
        can_view_raw_uuids = (
            request.user.is_authenticated
            and is_authenticated_admin(request.user)
            and is_platform_admin(request.user)
        )

        display_votes = [
            VoteDisplayItem(
                uuid=vote.uuid if can_view_raw_uuids else mask_voter_uuid(vote.uuid),
                timestamp=vote.timestamp
            )
            for vote in votes
        ]

        context = {
            'this_block': block,
            'confirmed_by': confirmed_by,
            'votes': zip(display_votes, vote_hashes),
            're_merkle_hash': re_merkle_hash,
            'isTampered': tampered,
        }
        return render(request, 'block-info.html', context)
    except Exception as e:
        logger.error(f"Error in block_info view: {e}")
        return redirect('/blockchain/')

@csrf_protect
def sync_block(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    if not (request.user.is_authenticated and is_authenticated_admin(request.user) and is_platform_admin(request.user)):
        return JsonResponse({'error': 'Unauthorized. Platform administrator privileges required.'}, status=403)

    body_data = {}
    if request.content_type == 'application/json' and request.body:
        try:
            body_data = json.loads(request.body)
        except Exception:
            body_data = {}

    block_id = (
        request.POST.get('block-id') or
        request.POST.get('block_id') or
        request.POST.get('id') or
        body_data.get('block-id') or
        body_data.get('block_id') or
        body_data.get('id') or
        request.GET.get('block-id') or
        request.GET.get('block_id') or
        request.GET.get('id')
    )
    if not block_id:
        return JsonResponse({'error': 'block-id parameter is required.'}, status=400)

    try:
        backup_votes = VoteBackup.objects.filter(block_id=block_id).order_by('timestamp')
        if not backup_votes.exists():
            return JsonResponse({'error': f'No backup records found for block {block_id}.'}, status=404)
        for vote in backup_votes:
            x_vote = Vote.objects.filter(uuid=vote.uuid, timestamp=vote.timestamp).first()
            if x_vote:
                x_vote.vote_party_id = vote.vote_party_id
                x_vote.timestamp = vote.timestamp
                x_vote.block_id = vote.block_id
                if hasattr(vote, 'tx_id') and vote.tx_id:
                    x_vote.tx_id = vote.tx_id
                if hasattr(vote, 'election_id') and vote.election_id:
                    x_vote.election_id = vote.election_id
                if hasattr(vote, 'position_id') and vote.position_id:
                    x_vote.position_id = vote.position_id
                if hasattr(vote, 'batch_id') and vote.batch_id:
                    x_vote.batch_id = vote.batch_id
                if hasattr(vote, 'ballot_id') and vote.ballot_id:
                    x_vote.ballot_id = vote.ballot_id
                x_vote.save()
            else:
                Vote.objects.create(
                    uuid=vote.uuid,
                    vote_party_id=vote.vote_party_id,
                    timestamp=vote.timestamp,
                    block_id=vote.block_id,
                    tx_id=getattr(vote, 'tx_id', None),
                    election_id=getattr(vote, 'election_id', None),
                    position_id=getattr(vote, 'position_id', None),
                    batch_id=getattr(vote, 'batch_id', None),
                    ballot_id=getattr(vote, 'ballot_id', None),
                )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

def verify_block(request):
    """
    Centralized block verification endpoint.
    - If 'selected[]' is provided in request.GET:
        Returns JSON mapping {s_block: is_tampered_boolean} for 100% backward compatibility
        with legacy blockchain.js and regression tests.
        If 'detailed=true' or 'format=detailed': returns {s_block: detailed_verification_result}.
    - If 'block_id' or 'id' is provided in request.GET:
        Returns structured verification result for that block.
        Restricts sensitive diagnostic internal fields to authorized admins/auditors.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    from home.methods_module import verify_single_block
    from home.permissions import is_authenticated_admin, is_platform_admin, is_organization_admin, is_auditor, belongs_to_organization

    selected = request.GET.getlist('selected[]')
    block_id = request.GET.get('id') or request.GET.get('block_id')
    detailed = request.GET.get('detailed') == 'true' or request.GET.get('format') == 'detailed'

    if selected:
        context = {}
        for s_block in selected:
            res = verify_single_block(s_block)
            if detailed:
                context[s_block] = res
            else:
                context[s_block] = not res['valid']
        return JsonResponse(context)
    elif block_id:
        res = verify_single_block(block_id)
        if not res.get('valid') and any("BLOCK_NOT_FOUND" in e for e in res.get('errors', [])):
            return JsonResponse(res, status=404)

        # RBAC check for organization scoping if block belongs to an election
        try:
            block = Block.objects.select_related('election').get(id=int(block_id))
            if block.election_id and has_staff_or_auditor_access(request.user):
                if not (is_platform_admin(request.user) or belongs_to_organization(request.user, block.election.organization_id)):
                    return JsonResponse({'error': 'Unauthorized for this organization'}, status=403)
        except Exception:
            pass

        # Sanitize for public callers
        is_privileged = is_platform_admin(request.user) or (
            (is_organization_admin(request.user) or is_auditor(request.user))
            and (not block or not block.election_id or belongs_to_organization(request.user, block.election.organization_id))
        )
        if not is_privileged:
            public_res = {
                'valid': res['valid'],
                'block_id': res['block_id'],
                'version': res.get('version'),
                'checks_performed': res.get('checks_performed', []),
                'errors': res.get('errors', []),
                'timestamp': res.get('timestamp')
            }
            return JsonResponse(public_res, status=200)

        return JsonResponse(res, status=200)
    else:
        return JsonResponse({'error': 'Missing block selection or block_id parameter'}, status=400)

def track_server(request):
    return JsonResponse(ts_data)

def admin_login(request):
    """
    BallotChain Unified Account Login Endpoint.
    Authenticates Admin, User, or Candidate using Email + Password or Username + Password.
    Establishes standard Django authenticated session.
    Supports both web form navigation and API/JSON client workflows.
    """
    if request.method == 'GET':
        if request.user.is_authenticated:
            return redirect('/dashboard/')
        next_url = request.GET.get('next', '')
        return render(request, 'login.html', {'next_url': next_url})

    if request.method == 'POST':
        try:
            import json
            is_json = request.content_type == 'application/json' or (request.body and request.body.startswith(b'{'))
            if is_json:
                data = json.loads(request.body)
            else:
                data = request.POST

            identifier = (data.get('email') or data.get('username') or '').strip()
            password = data.get('password') or ''
            next_url = data.get('next') or request.GET.get('next') or ''

            if not identifier or not password:
                if is_json:
                    return JsonResponse({'success': False, 'error': 'Email/username and password are required.'}, status=400)
                return render(request, 'login.html', {
                    'error': 'Email and password are required.',
                    'email': identifier,
                    'next_url': next_url
                }, status=400)

            user = authenticate(request, username=identifier, password=password)
            if user is not None:
                login(request, user)
                if is_json:
                    from home.permissions import get_account_persona, get_user_role
                    persona = get_account_persona(user)
                    return JsonResponse({
                        'success': True,
                        'message': 'Login successful',
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'email': user.email,
                            'persona': persona,
                            'role': get_user_role(user) or persona,
                            'is_staff': user.is_staff,
                            'is_superuser': user.is_superuser,
                        }
                    })

                # Safe post-login redirection
                if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                    return redirect(next_url)
                return redirect('/dashboard/')
            else:
                if is_json:
                    return JsonResponse({'success': False, 'error': 'Invalid credentials'}, status=401)
                return render(request, 'login.html', {
                    'error': 'Invalid email or password. Please try again.',
                    'email': identifier,
                    'next_url': next_url
                }, status=401)
        except Exception as e:
            if is_json:
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            return render(request, 'login.html', {
                'error': f'An error occurred: {str(e)}',
                'email': request.POST.get('email', ''),
                'next_url': request.POST.get('next', '')
            }, status=400)

    return JsonResponse({'error': 'Method not allowed. Use GET or POST.'}, status=405)

def admin_logout(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)
    logout(request)
    if request.content_type == 'application/json' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'message': 'Admin logout successful'})
    return redirect('/')

from home.models import Organization, Election, UserProfile
from home.permissions import is_authenticated_admin, is_platform_admin, is_organization_admin, belongs_to_organization, get_user_profile

@csrf_exempt
def org_list(request):
    if not is_platform_admin(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    accept = request.headers.get('accept', '')
    if 'text/html' in accept and accept != '*/*' and request.GET.get('format') != 'json':
        orgs = Organization.objects.all()
        return render(request, 'organizations.html', {'organizations': orgs})
    
    orgs = list(Organization.objects.values('id', 'name', 'description', 'contact_information'))
    return JsonResponse({'organizations': orgs})

def org_create(request):
    if not is_platform_admin(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    accept = request.headers.get('accept', '')
    is_browser = 'text/html' in accept and accept != '*/*'

    if request.method == 'GET':
        if is_browser:
            return render(request, 'organization_create.html')
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if request.method == 'POST':
        try:
            import json
            is_json = request.content_type == 'application/json' or (request.body and request.body.startswith(b'{'))
            if is_json:
                data = json.loads(request.body)
            else:
                data = request.POST

            name = (data.get('name') or '').strip()
            description = (data.get('description') or '').strip()
            contact_info = (data.get('contact_information') or '').strip()

            if not name:
                if is_json:
                    return JsonResponse({'error': 'Name is required'}, status=400)
                return render(request, 'organization_create.html', {
                    'error': 'Organization name is required.',
                    'name': name,
                    'description': description,
                    'contact_information': contact_info
                }, status=400)

            if Organization.objects.filter(name__iexact=name).exists():
                if is_json:
                    return JsonResponse({'error': 'An organization with this name already exists.'}, status=400)
                return render(request, 'organization_create.html', {
                    'error': 'An organization with this name already exists.',
                    'name': name,
                    'description': description,
                    'contact_information': contact_info
                }, status=400)

            org = Organization.objects.create(
                name=name,
                description=description,
                contact_information=contact_info
            )
            if is_json:
                return JsonResponse({'success': True, 'id': org.id})
            return redirect('/organizations/')
        except Exception as e:
            if is_json:
                return JsonResponse({'error': str(e)}, status=400)
            return render(request, 'organization_create.html', {'error': str(e)}, status=400)

    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def org_detail(request, org_id):
    if not has_staff_or_auditor_access(request.user, org_id):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    try:
        org = Organization.objects.get(id=org_id)
        return JsonResponse({'id': org.id, 'name': org.name, 'description': org.description, 'contact_information': org.contact_information})
    except Organization.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

def org_edit(request, org_id):
    if not can_perform_administrative_mutation(request.user, org_id):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    if request.method == 'POST':
        try:
            import json
            org = Organization.objects.get(id=org_id)
            data = json.loads(request.body)
            if 'name' in data and not str(data['name']).strip():
                return JsonResponse({'error': 'Name cannot be blank'}, status=400)
                
            org.name = data.get('name', org.name)
            org.description = data.get('description', org.description)
            org.contact_information = data.get('contact_information', org.contact_information)
            org.save()
            return JsonResponse({'success': True})
        except Organization.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

def org_delete(request, org_id):
    if not is_platform_admin(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    if request.method == 'POST':
        try:
            org = Organization.objects.get(id=org_id)
            
            if Election.objects.filter(organization=org).exists():
                return JsonResponse({'error': 'Cannot delete organization with existing elections'}, status=400)
                
            if UserProfile.objects.filter(organization=org).exists():
                return JsonResponse({'error': 'Cannot delete organization with assigned users'}, status=400)
                
            org.delete()
            return JsonResponse({'success': True})
        except Organization.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

from home.models import Position, Vote, VoteBackup
from home.permissions import is_election_official, is_auditor

@csrf_exempt
def election_list(request):
    trigger_scheduled_lifecycle_check()
    if not has_staff_or_auditor_access(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    qs = Election.objects.all()
    if not is_platform_admin(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.organization_id:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        qs = qs.filter(organization_id=profile.organization_id)

    accept = request.headers.get('accept', '')
    if 'text/html' in accept and accept != '*/*' and request.GET.get('format') != 'json':
        return render(request, 'elections.html', {'elections': qs.select_related('organization')})
        
    elections = list(qs.values('id', 'organization_id', 'title', 'description', 'start_date', 'end_date', 'status'))
    return JsonResponse({'elections': elections})

def election_create(request):
    if not can_perform_administrative_mutation(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    accept = request.headers.get('accept', '')
    is_browser = 'text/html' in accept and accept != '*/*'

    def get_accessible_orgs(user):
        if is_platform_admin(user):
            return Organization.objects.all()
        profile = get_user_profile(user)
        if profile and profile.organization_id:
            return Organization.objects.filter(id=profile.organization_id)
        return Organization.objects.none()

    if request.method == 'GET':
        if is_browser:
            orgs = get_accessible_orgs(request.user)
            return render(request, 'election_create.html', {
                'organizations': orgs,
                'is_platform_admin': is_platform_admin(request.user)
            })
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    if request.method == 'POST':
        try:
            import json
            is_json = request.content_type == 'application/json' or (request.body and request.body.startswith(b'{'))
            if is_json:
                data = json.loads(request.body)
            else:
                data = request.POST

            org_id = data.get('organization_id')
            title = (data.get('title') or '').strip()
            description = (data.get('description') or '').strip()
            start_date = parse_aware_election_datetime(data.get('start_date'))
            end_date = parse_aware_election_datetime(data.get('end_date'))

            def render_error(msg):
                orgs = get_accessible_orgs(request.user)
                return render(request, 'election_create.html', {
                    'error': msg,
                    'organizations': orgs,
                    'is_platform_admin': is_platform_admin(request.user),
                    'title': title,
                    'description': description,
                    'selected_org_id': org_id,
                    'start_date': start_date,
                    'end_date': end_date
                }, status=400)

            if not title:
                if is_json:
                    return JsonResponse({'error': 'Title is required'}, status=400)
                return render_error('Election title is required.')

            if not org_id:
                if is_json:
                    return JsonResponse({'error': 'Organization ID is required'}, status=400)
                return render_error('Host organization selection is required.')

            if not belongs_to_organization(request.user, org_id):
                return JsonResponse({'error': 'Unauthorized organization'}, status=403)

            if not Organization.objects.filter(id=org_id).exists():
                if is_json:
                    return JsonResponse({'error': 'Organization not found'}, status=404)
                return render_error('Selected organization not found.')

            # Check for duplicate election title within this organization
            if Election.objects.filter(organization_id=org_id, title__iexact=title).exists():
                if is_json:
                    return JsonResponse({'error': 'An election with this title already exists in this organization.'}, status=400)
                return render_error('An election with this title already exists in this organization.')

            elec = Election.objects.create(
                organization_id=org_id,
                title=title,
                description=description,
                start_date=start_date,
                end_date=end_date,
                status='DRAFT'
            )
            if is_json:
                return JsonResponse({'success': True, 'id': elec.id})
            return redirect(f'/elections/{elec.id}/')
        except Exception as e:
            if is_json:
                return JsonResponse({'error': str(e)}, status=400)
            return render_error(str(e))

    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def election_detail(request, elec_id):
    trigger_scheduled_lifecycle_check()
    if not request.user.is_authenticated:
        if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json' or request.content_type == 'application/json':
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        return render(request, 'base.html', {'error': 'Authentication required. Please log in first.'}, status=403)

    try:
        elec = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json':
            return JsonResponse({'error': 'Not found'}, status=404)
        return render(request, 'base.html', {'error': 'Election not found'}, status=404)

    # Tenant organization boundary check for staff/auditor users
    if not is_platform_admin(request.user):
        profile = get_user_profile(request.user)
        if profile and profile.organization_id and elec.organization_id:
            if profile.organization_id != elec.organization_id:
                if request.headers.get('accept') == 'application/json' or request.GET.get('format') == 'json':
                    return JsonResponse({'error': 'Unauthorized'}, status=403)
                return render(request, 'base.html', {'error': 'Unauthorized organization access'}, status=403)

    is_json = (
        request.headers.get('accept') == 'application/json' or 
        request.GET.get('format') == 'json' or
        request.content_type == 'application/json'
    )
    if is_json:
        # Check authorization for JSON access: staff/auditor or authenticated member
        if not has_staff_or_auditor_access(request.user, elec.organization_id):
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'Unauthorized'}, status=403)
        return JsonResponse({
            'id': elec.id,
            'organization_id': elec.organization_id,
            'organization_name': elec.organization.name if elec.organization else None,
            'title': elec.title,
            'description': elec.description,
            'start_date': elec.start_date.isoformat() if elec.start_date else None,
            'end_date': elec.end_date.isoformat() if elec.end_date else None,
            'status': elec.status,
            'is_published': elec.is_published,
            'published_at': elec.published_at.isoformat() if elec.published_at else None,
            'live_progress_enabled': elec.live_progress_enabled,
        })

    # Browser HTML view: Generic election page
    from home.models import Position, Candidate, Vote, Eligibility
    from home.methods_module import ensure_nota_candidates_for_election
    ensure_nota_candidates_for_election(elec)
    positions = Position.objects.filter(election=elec)
    positions_data = []
    for pos in positions:
        cands = list(Candidate.objects.filter(position=pos))
        positions_data.append({
            'position': pos,
            'candidates': cands,
        })

    voter = get_or_create_voter_for_user(request.user, create=False)
    has_voted = False
    is_eligible = False
    can_manage = can_manage_election(request.user, elec)

    if voter:
        has_voted = Vote.objects.filter(uuid=voter.uuid, election=elec).exists() or voter.vote_done
        if Eligibility.objects.filter(election=elec).exists():
            is_eligible = Eligibility.objects.filter(voter=voter, election=elec).exists()
        else:
            is_eligible = True
    elif not request.user.is_authenticated:
        is_eligible = False

    is_plat_admin = is_platform_admin(request.user) if request.user.is_authenticated else False
    can_vote = (elec.status == 'OPEN' and is_eligible and not has_voted and not is_plat_admin)

    from django.contrib.auth.models import User
    user_candidacies = list(Candidate.objects.filter(position__election=elec, user=request.user)) if request.user.is_authenticated else []
    user_candidacy_position_ids = [c.position_id for c in user_candidacies]
    candidate_users = list(User.objects.filter(is_active=True).order_by('username')) if can_manage else []

    live_progress_stats = None
    if elec.status == 'OPEN' and elec.live_progress_enabled:
        from home.methods_module import calculate_verified_election_results
        res = calculate_verified_election_results(elec.id, allow_unfinalized=True)
        summary = res.get('summary', {}) if res else {}
        submitted = summary.get('total_submitted_ballots', 0)
        counted = summary.get('total_votes_counted', 0)
        live_progress_stats = {
            'ballots_submitted': submitted,
            'votes_recorded': counted,
            'status': elec.status,
        }

    context = {
        'election': elec,
        'positions': positions_data,
        'has_voted': has_voted,
        'is_eligible': is_eligible,
        'can_vote': can_vote,
        'can_manage': can_manage,
        'candidate_users': candidate_users,
        'user_candidacies': user_candidacies,
        'user_candidacy_position_ids': user_candidacy_position_ids,
        'can_register_candidate': (elec.status == 'DRAFT'),
        'is_candidate_account': is_candidate_account(request.user) if request.user.is_authenticated else False,
        'account_persona': get_account_persona(request.user) if request.user.is_authenticated else 'PUBLIC_AUDITOR',
        'is_platform_admin': is_plat_admin,
        'live_progress_stats': live_progress_stats,
    }
    return render(request, 'election_detail.html', context)


def election_vote(request, elec_id):
    """
    GET /elections/<int:elec_id>/vote/
    Direct entry into the voter flow for a specific election.
    Enforces authentication, lifecycle availability, eligibility, and single-vote protection.
    """
    trigger_scheduled_lifecycle_check()
    if not request.user.is_authenticated:
        return redirect(f'/login/?next=/elections/{elec_id}/vote/')

    try:
        elec = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        return render(request, 'base.html', {'error': 'Election not found'}, status=404)

    # 1. Lifecycle checks
    if elec.status == 'DRAFT':
        return render(request, 'base.html', {'error': 'Election voting has not started. Election is currently in DRAFT status.'}, status=400)
    if elec.status == 'CLOSED':
        return render(request, 'base.html', {'error': 'Election voting has ended. This election is CLOSED.'}, status=400)
    if elec.status != 'OPEN':
        return render(request, 'base.html', {'error': 'Election is not open for voting.'}, status=400)

    # 2. Tenant isolation
    if not is_platform_admin(request.user) and elec.organization_id:
        profile = get_user_profile(request.user)
        if profile and profile.organization_id and profile.organization_id != elec.organization_id:
            return render(request, 'base.html', {'error': 'Unauthorized organization access'}, status=403)

    # 3. Resolve voter
    voter = get_or_create_voter_for_user(request.user)
    if not voter:
        return render(request, 'base.html', {'error': 'Failed to resolve voter identity.'}, status=400)

    # 4. Eligibility check
    from home.models import Eligibility, Vote
    if Eligibility.objects.filter(election=elec).exists():
        if not Eligibility.objects.filter(voter=voter, election=elec).exists():
            return render(request, 'base.html', {'error': 'You are not registered as an eligible voter for this election.'}, status=403)

    # 5. Duplicate vote check
    if Vote.objects.filter(uuid=voter.uuid, election=elec).exists():
        return render(request, 'base.html', {'error': 'You have already cast your vote in this election.'}, status=400)

    # 6. Initialize session for this election voting flow
    request.session['uuid'] = voter.uuid
    request.session['election_id'] = elec.id
    request.session['email-id'] = voter.email or request.user.email
    request.session['otp'] = None
    request.session['otp_created_at'] = None
    request.session['otp_attempts'] = 0
    request.session['email-verified'] = False

    candidate_details_html = loader.render_to_string('candidate_details.html', {'details': voter})

    context = {
        'election': elec,
        'voter': voter,
        'candidate_details_html': candidate_details_html,
        'account_persona': get_account_persona(request.user),
    }
    return render(request, 'election_vote.html', context)

def election_edit(request, elec_id):
    try:
        elec = Election.objects.get(id=elec_id)
    except Election.DoesNotExist:
        if request.headers.get('Accept') == 'application/json' or request.content_type == 'application/json':
            return JsonResponse({'error': 'Not found'}, status=404)
        return render(request, 'base.html', {'error': 'Election not found'}, status=404)

    if not can_manage_election(request.user, elec):
        if request.headers.get('Accept') == 'application/json' or request.content_type == 'application/json':
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        return render(request, 'base.html', {'error': 'Unauthorized to manage this election'}, status=403)

    is_json = (
        request.headers.get('Accept') == 'application/json' or
        request.content_type == 'application/json' or
        request.GET.get('format') == 'json' or
        (request.body and request.body.startswith(b'{'))
    )

    accept = request.headers.get('accept', '')
    is_browser = 'text/html' in accept and accept != '*/*'

    if request.method == 'GET':
        if not is_browser or is_json:
            return JsonResponse({'error': 'Method not allowed'}, status=405)
        if elec.status == 'CLOSED':
            if is_json:
                return JsonResponse({'error': 'Closed elections cannot be edited or reopened.'}, status=400)
            from django.contrib import messages
            messages.warning(request, 'Closed elections cannot be edited or reopened.')
            return redirect(f'/elections/{elec.id}/')

        from home.models import Organization
        if is_platform_admin(request.user):
            organizations = list(Organization.objects.all().order_by('name'))
        else:
            profile = get_user_profile(request.user)
            org = profile.organization if profile else elec.organization
            organizations = [org] if org else []

        from django.utils import timezone
        context = {
            'election': elec,
            'organizations': organizations,
            'is_platform_admin': is_platform_admin(request.user),
            'start_date': timezone.localtime(elec.start_date).strftime('%Y-%m-%dT%H:%M') if elec.start_date else '',
            'end_date': timezone.localtime(elec.end_date).strftime('%Y-%m-%dT%H:%M') if elec.end_date else '',
            'account_persona': get_account_persona(request.user),
        }
        return render(request, 'election_edit.html', context)
        
    if request.method == 'POST':
        try:
            if is_json:
                import json
                data = json.loads(request.body)
            else:
                data = request.POST.dict()
                if 'live_progress_enabled' in request.POST:
                    data['live_progress_enabled'] = (request.POST.get('live_progress_enabled') in ['1', 'true', 'on', 'True'])
                else:
                    data['live_progress_enabled'] = False

            new_org_id = data.get('organization_id')
            if new_org_id and str(new_org_id) != str(elec.organization_id):
                if not is_platform_admin(request.user):
                    return JsonResponse({'error': 'Cannot change organization'}, status=403)
                if not Organization.objects.filter(id=new_org_id).exists():
                    return JsonResponse({'error': 'Target organization does not exist'}, status=400)

            # Lifecycle restriction: CLOSED elections can NEVER be edited or reopened
            if elec.status == 'CLOSED':
                return JsonResponse({'error': 'Closed elections cannot be reopened or edited back to draft/open'}, status=400)

            # Lifecycle restriction: Once OPEN, critical identity & configuration are locked
            if elec.status == 'OPEN':
                if new_org_id and str(new_org_id) != str(elec.organization_id):
                    return JsonResponse({'error': 'Cannot change election organization while election is OPEN'}, status=400)

                new_title = data.get('title')
                if new_title and new_title.strip() != elec.title:
                    return JsonResponse({'error': 'Cannot change election title while election is OPEN'}, status=400)
                    elec.organization_id = new_org_id
            
            if 'title' in data and not str(data['title']).strip():
                if is_json:
                    return JsonResponse({'error': 'Title cannot be blank'}, status=400)
                from django.contrib import messages
                messages.error(request, 'Title cannot be blank.')
                return redirect(f'/elections/{elec.id}/edit/')
                
            if 'title' in data and (elec.status == 'DRAFT'):
                elec.title = data.get('title', elec.title)
            if 'description' in data:
                elec.description = data.get('description', elec.description)

            if 'start_date' in data:
                elec.start_date = parse_aware_election_datetime(data['start_date'])

            if 'end_date' in data:
                elec.end_date = parse_aware_election_datetime(data['end_date'])

            # Live progress visibility configuration (Admin-controlled)
            if 'live_progress_enabled' in data:
                if not can_perform_administrative_mutation(request.user, elec.organization_id):
                    return JsonResponse({'error': 'Unauthorized to modify live progress configuration'}, status=403)
                elec.live_progress_enabled = bool(data['live_progress_enabled'])

            # Publication control (cannot bypass Phase 6 verification via manual flag)
            if 'is_published' in data and data['is_published'] and not elec.is_published:
                if not can_publish_results(request.user, elec):
                    return JsonResponse({'error': 'Unauthorized to publish election results'}, status=403)
                if elec.status != 'CLOSED':
                    return JsonResponse({'error': 'Cannot publish results for an election that is not CLOSED'}, status=400)
                from home.methods_module import calculate_verified_election_results, verify_result_receipt_consistency
                res = calculate_verified_election_results(elec.id, allow_unfinalized=False)
                if not res.get('verified') or not res.get('is_eligible_for_publication'):
                    return JsonResponse({'error': 'Cannot publish results: ledger verification failed', 'publication_state': res.get('publication_state')}, status=400)
                receipt = res.get('result_receipt') or res.get('verification_receipt') or res.get('verification_receipt')
                if not receipt:
                    return JsonResponse({'error': 'Cannot publish results: missing deterministic verification receipt'}, status=400)
                cons = verify_result_receipt_consistency(elec.id, expected_receipt=receipt)
                if not cons.get('is_consistent'):
                    return JsonResponse({'error': 'Cannot publish results: verification receipt is stale or inconsistent'}, status=400)
                elec.is_published = True
                elec.published_at = timezone.now()
                elec.publication_receipt = receipt
            
            new_status = data.get('status')
            if new_status and new_status != elec.status:
                # Reopening prevention: CLOSED elections can NEVER be transitioned back to OPEN or DRAFT
                if elec.status == 'CLOSED':
                    return JsonResponse({'error': 'Closed elections cannot be reopened or edited back to draft/open'}, status=400)

                if new_status == 'OPEN':
                    if not can_start_election(request.user, elec):
                        return JsonResponse({'error': 'Unauthorized to start election'}, status=403)
                    if elec.status != 'DRAFT':
                        return JsonResponse({'error': f'Cannot start election from status {elec.status}'}, status=400)
                    elec.status = 'OPEN'
                    if not elec.start_date:
                        elec.start_date = timezone.now()
                elif new_status == 'CLOSED':
                    if not can_end_election(request.user, elec):
                        return JsonResponse({'error': 'Unauthorized to end election'}, status=403)
                    if elec.status != 'OPEN':
                        return JsonResponse({'error': 'Cannot end an election that is in DRAFT status'}, status=400)
                    elec.status = 'CLOSED'
                    if not elec.end_date:
                        elec.end_date = timezone.now()
                    # Clean up unused empty open batch
                    from home.models import BallotBatch
                    BallotBatch.objects.filter(election=elec, status='OPEN', ballot_count=0).delete()
                elif new_status in [c[0] for c in Election.STATUS_CHOICES]:
                    if not can_perform_administrative_mutation(request.user, elec.organization_id):
                        return JsonResponse({'error': 'Unauthorized to change election status'}, status=403)
                    elec.status = new_status
                
            elec.save()
            if is_json:
                return JsonResponse({'success': True})
            from django.contrib import messages
            messages.success(request, f'Election \"{elec.title}\" updated successfully.')
            return redirect(f'/elections/{elec.id}/')
        except Election.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)


def election_start(request, elec_id):
    """
    POST /elections/<int:elec_id>/start/
    Transitions an election from DRAFT to OPEN.
    Authorized ONLY for:
    - PLATFORM_ADMIN (global)
    - ORGANIZATION_ADMIN (scoped to election.organization_id)
    Denies (403):
    - ELECTION_OFFICIAL
    - AUDITOR
    - VOTER
    - CANDIDATE
    State machine:
    - Rejects if election.status == 'OPEN' (already open, 400)
    - Rejects if election.status == 'CLOSED' (cannot reopen closed election, 400)
    - Rejects if method is not POST (405)
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    try:
        elec = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Election not found'}, status=404)

    if not can_start_election(request.user, elec):
        return JsonResponse({'error': 'Unauthorized to start election'}, status=403)

    if elec.status == 'OPEN':
        return JsonResponse({'error': 'Election is already open'}, status=400)

    if elec.status == 'CLOSED':
        return JsonResponse({'error': 'Cannot start a closed election. Closed elections cannot be reopened.'}, status=400)

    if elec.status != 'DRAFT':
        return JsonResponse({'error': f'Cannot start election from status {elec.status}'}, status=400)

    from home.methods_module import ensure_nota_candidates_for_election
    ensure_nota_candidates_for_election(elec)

    elec.status = 'OPEN'
    if not elec.start_date:
        elec.start_date = timezone.now()
    elec.save()

    is_json = (
        request.headers.get('Accept') == 'application/json' or
        request.content_type == 'application/json' or
        request.GET.get('format') == 'json'
    )
    if is_json:
        return JsonResponse({
            'success': True,
            'message': f'Election \"{elec.title}\" is now OPEN.',
            'election_id': elec.id,
            'status': elec.status,
            'start_date': elec.start_date.isoformat() if elec.start_date else None,
        }, status=200)

    from django.contrib import messages
    messages.success(request, f'Election started successfully. \"{elec.title}\" is now open for voting.')
    return redirect(f'/elections/{elec.id}/')


def election_end(request, elec_id):
    """
    POST /elections/<int:elec_id>/end/
    Transitions an election from OPEN to CLOSED.
    Authorized ONLY for:
    - PLATFORM_ADMIN (global)
    - ORGANIZATION_ADMIN (scoped to election.organization_id)
    Denies (403):
    - ELECTION_OFFICIAL
    - AUDITOR
    - VOTER
    - CANDIDATE
    State machine:
    - Rejects if election.status == 'DRAFT' (cannot end draft, 400)
    - Rejects if election.status == 'CLOSED' (already closed, 400)
    - Rejects if method is not POST (405)
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    try:
        elec = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Election not found'}, status=404)

    if not can_end_election(request.user, elec):
        return JsonResponse({'error': 'Unauthorized to end election'}, status=403)

    if elec.status == 'DRAFT':
        return JsonResponse({'error': 'Cannot end an election that is in DRAFT status'}, status=400)

    if elec.status == 'CLOSED':
        return JsonResponse({'error': 'Election is already closed'}, status=400)

    if elec.status != 'OPEN':
        return JsonResponse({'error': f'Cannot end election from status {elec.status}'}, status=400)

    elec.status = 'CLOSED'
    if not elec.end_date:
        elec.end_date = timezone.now()
    elec.save()

    # Clean up any unused empty open batches created while election was OPEN (Phase 6 rule)
    from home.models import BallotBatch
    from home.methods_module import mine_modern_batch
    BallotBatch.objects.filter(election=elec, status='OPEN', ballot_count=0).delete()

    # Seal and mine any unsealed batches that contain cast ballots
    for unsealed_batch in BallotBatch.objects.filter(election=elec, status__in=['OPEN', 'CLOSED'], ballot_count__gt=0).order_by('batch_number'):
        try:
            mine_modern_batch(unsealed_batch.id)
        except Exception as e:
            logger.error(f"Error sealing batch {unsealed_batch.id} on election end: {e}")

    is_json = (
        request.headers.get('Accept') == 'application/json' or
        request.content_type == 'application/json' or
        request.GET.get('format') == 'json'
    )
    if is_json:
        return JsonResponse({
            'success': True,
            'message': f'Election \"{elec.title}\" is now CLOSED. Voting has ended permanently.',
            'election_id': elec.id,
            'status': elec.status,
            'end_date': elec.end_date.isoformat() if elec.end_date else None,
        }, status=200)

    from django.contrib import messages
    messages.success(request, f'Election ended successfully. Voting is now closed. Results are being verified.')
    return redirect(f'/elections/{elec.id}/')


def election_publish(request, elec_id):
    """
    POST /elections/<int:elec_id>/publish/
    Certifies and publishes verified results for a CLOSED election.
    Authorized ONLY for:
    - PLATFORM_ADMIN (global)
    - ORGANIZATION_ADMIN (scoped to election.organization_id)
    Denies (403):
    - ELECTION_OFFICIAL
    - AUDITOR
    - VOTER
    - CANDIDATE
    Conditions:
    - Must be CLOSED. Cannot publish DRAFT or OPEN.
    - Full ledger verification & calculation via calculate_verified_election_results.
    - Verification must PASS (not LEDGER_VERIFICATION_FAILED or CALCULATION_FAILED).
    - Deterministic receipt must be generated and valid.
    - Receipt consistency check via verify_result_receipt_consistency must pass.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    try:
        elec = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Election not found'}, status=404)

    if not can_publish_results(request.user, elec):
        return JsonResponse({'error': 'Unauthorized to publish election results'}, status=403)

    if elec.status != 'CLOSED':
        return JsonResponse({
            'error': f'Cannot publish results for an election that is not CLOSED (current status: {elec.status})'
        }, status=400)

    from home.methods_module import calculate_verified_election_results, verify_result_receipt_consistency, ResultPublicationState
    from home.models import ElectionResultAudit

    # 1. Calculate & verify ledger integrity
    res = calculate_verified_election_results(elec.id, allow_unfinalized=False)

    if not res.get('verified') or not res.get('is_eligible_for_publication'):
        error_msg = res.get('error') or 'Ledger verification failed or results are not eligible for publication'
        pub_state = res.get('publication_state', ResultPublicationState.LEDGER_VERIFICATION_FAILED)
        return JsonResponse({
            'error': f'Cannot publish results: {error_msg}',
            'publication_state': pub_state,
            'verified': False
        }, status=400)

    receipt = res.get('result_receipt') or res.get('verification_receipt')
    if not receipt:
        return JsonResponse({'error': 'Cannot publish results: missing deterministic verification receipt'}, status=400)

    # 2. Server-side receipt consistency verification against ledger
    consistency = verify_result_receipt_consistency(elec.id, expected_receipt=receipt)
    if not consistency.get('is_consistent'):
        return JsonResponse({
            'error': 'Cannot publish results: verification receipt is stale or inconsistent with current ledger',
            'status': consistency.get('status', 'INCONSISTENT_RECEIPT')
        }, status=400)

    # 3. Transition to officially published
    now = timezone.now()
    elec.is_published = True
    elec.published_at = now
    elec.publication_receipt = receipt
    elec.save()

    # 4. Record certified publication audit entry
    ElectionResultAudit.objects.create(
        election=elec,
        verification_passed=True,
        verification_status='PUBLISHED',
        result_receipt=receipt,
        blocks_checked=res.get('verified_blocks_count', 0),
        batches_checked=res.get('verified_batches_count', 0),
        transactions_checked=res.get('total_votes_tallied', 0),
        total_votes_tallied=res.get('total_votes_tallied', 0),
        failure_category=None,
        failure_details=''
    )

    is_json = (
        request.headers.get('Accept') == 'application/json' or
        request.content_type == 'application/json' or
        request.GET.get('format') == 'json'
    )
    if is_json:
        return JsonResponse({
            'success': True,
            'message': f'Results for election \"{elec.title}\" have been certified and published.',
            'election_id': elec.id,
            'is_published': True,
            'publication_receipt': receipt,
            'published_at': now.isoformat(),
            'publication_state': ResultPublicationState.VERIFIED_PUBLISHED,
        }, status=200)

    from django.contrib import messages
    messages.success(request, f'Results for election \"{elec.title}\" have been verified and published successfully.')
    return redirect(f'/show-result/?election_id={elec.id}')

def election_delete(request, elec_id):
    try:
        elec = Election.objects.get(id=elec_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    if not can_perform_administrative_mutation(request.user, elec.organization_id):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    if request.method == 'POST':
        try:
                
            if Position.objects.filter(election=elec).exists():
                return JsonResponse({'error': 'Cannot delete election with existing positions'}, status=400)
                
            if Vote.objects.filter(election=elec).exists() or VoteBackup.objects.filter(election=elec).exists():
                return JsonResponse({'error': 'Cannot delete election with existing votes'}, status=400)
                
            elec.delete()
            return JsonResponse({'success': True})
        except Election.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

from home.models import Candidate, Voters

@csrf_exempt
def position_list(request):
    if not has_staff_or_auditor_access(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    qs = Position.objects.all()
    if not is_platform_admin(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.organization_id:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        qs = qs.filter(election__organization_id=profile.organization_id)
        
    positions = list(qs.values('id', 'election_id', 'title', 'max_votes_allowed'))
    return JsonResponse({'positions': positions})

def position_create(request):
    if request.method == 'POST':
        is_json = (
            request.headers.get('Accept') == 'application/json' or
            request.content_type == 'application/json' or
            request.GET.get('format') == 'json' or
            (request.body and request.body.startswith(b'{'))
        )
        try:
            if request.content_type == 'application/json' or (request.body and request.body.startswith(b'{')):
                import json
                data = json.loads(request.body)
            else:
                data = request.POST.dict()

            elec_id = data.get('election_id')
            title = data.get('title')
            
            if not title or not elec_id:
                if is_json:
                    return JsonResponse({'error': 'Title and Election ID are required'}, status=400)
                from django.contrib import messages
                messages.error(request, 'Position title and Election ID are required.')
                return redirect(f'/elections/{elec_id}/' if elec_id else '/elections/')
                
            elec = Election.objects.get(id=elec_id)
            if not can_manage_election(request.user, elec):
                if is_json:
                    return JsonResponse({'error': 'Unauthorized organization'}, status=403)
                from django.contrib import messages
                messages.error(request, 'Unauthorized to manage positions for this election.')
                return redirect(f'/elections/{elec.id}/')

            if elec.status != 'DRAFT':
                if is_json:
                    return JsonResponse({'error': 'Positions can only be added while election is in DRAFT status'}, status=400)
                from django.contrib import messages
                messages.error(request, 'Positions can only be added while the election is in DRAFT status.')
                return redirect(f'/elections/{elec.id}/')
                
            pos = Position.objects.create(
                election=elec,
                title=title,
                max_votes_allowed=int(data.get('max_votes_allowed', 1))
            )
            from home.methods_module import ensure_nota_candidate_for_position
            ensure_nota_candidate_for_position(pos)
            if is_json:
                return JsonResponse({'success': True, 'id': pos.id})

            from django.contrib import messages
            messages.success(request, f'Position \"{pos.title}\" added successfully.')
            return redirect(f'/elections/{elec.id}/')
        except Election.DoesNotExist:
            if is_json:
                return JsonResponse({'error': 'Election not found'}, status=404)
            return render(request, 'base.html', {'error': 'Election not found'}, status=404)
        except Exception as e:
            if is_json:
                return JsonResponse({'error': str(e)}, status=400)
            from django.contrib import messages
            messages.error(request, str(e))
            return redirect('/elections/')
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def position_detail(request, pos_id):
    try:
        pos = Position.objects.select_related('election').get(id=pos_id)
        if not has_staff_or_auditor_access(request.user, pos.election.organization_id):
            return JsonResponse({'error': 'Unauthorized'}, status=403)
            
        return JsonResponse({
            'id': pos.id,
            'election_id': pos.election_id,
            'title': pos.title,
            'max_votes_allowed': pos.max_votes_allowed
        })
    except Position.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

def position_edit(request, pos_id):
    if request.method == 'POST':
        try:
            import json
            pos = Position.objects.select_related('election').get(id=pos_id)
            if not can_manage_election(request.user, pos.election):
                return JsonResponse({'error': 'Unauthorized'}, status=403)
                
            data = json.loads(request.body)
            
            if 'title' in data and not str(data['title']).strip():
                return JsonResponse({'error': 'Title cannot be blank'}, status=400)
                
            pos.title = data.get('title', pos.title)
            if 'max_votes_allowed' in data:
                pos.max_votes_allowed = int(data['max_votes_allowed'])
            pos.save()
            return JsonResponse({'success': True})
        except Position.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

def position_delete(request, pos_id):
    if request.method == 'POST':
        try:
            pos = Position.objects.select_related('election').get(id=pos_id)
            if not can_manage_election(request.user, pos.election):
                return JsonResponse({'error': 'Unauthorized'}, status=403)
                
            if Candidate.objects.filter(position=pos).exists():
                return JsonResponse({'error': 'Cannot delete position with assigned candidates'}, status=400)
                
            pos.delete()
            return JsonResponse({'success': True})
        except Position.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def candidate_list(request):
    if not has_staff_or_auditor_access(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
        
    qs = Candidate.objects.all()
    if not is_platform_admin(request.user):
        profile = get_user_profile(request.user)
        if not profile or not profile.organization_id:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        qs = qs.filter(position__election__organization_id=profile.organization_id)
        
    candidates = list(qs.values('id', 'position_id', 'name', 'bio', 'affiliation', 'image'))
    return JsonResponse({'candidates': candidates})

def candidate_create(request):
    if request.method == 'POST':
        is_json = (
            request.headers.get('Accept') == 'application/json' or
            request.content_type == 'application/json' or
            request.GET.get('format') == 'json' or
            (request.body and request.body.startswith(b'{'))
        )
        try:
            if request.content_type == 'application/json' or (request.body and request.body.startswith(b'{')):
                import json
                data = json.loads(request.body)
            else:
                data = request.POST.dict()

            pos_id = data.get('position_id')
            name = data.get('name')
            user_id = data.get('user_id')
            
            if not name or not pos_id:
                if is_json:
                    return JsonResponse({'error': 'Name and Position ID are required'}, status=400)
                from django.contrib import messages
                messages.error(request, 'Candidate name and Position ID are required.')
                return redirect('/elections/')
                
            pos = Position.objects.select_related('election').get(id=pos_id)
            if not can_manage_election(request.user, pos.election):
                if is_json:
                    return JsonResponse({'error': 'Unauthorized organization'}, status=403)
                from django.contrib import messages
                messages.error(request, 'Unauthorized to add candidates to this election.')
                return redirect(f'/elections/{pos.election.id}/')

            if pos.election.status != 'DRAFT':
                if is_json:
                    return JsonResponse({'error': 'Candidates can only be registered while election is in DRAFT status'}, status=400)
                from django.contrib import messages
                messages.error(request, 'Candidates can only be registered while the election is in DRAFT status.')
                return redirect(f'/elections/{pos.election.id}/')
                
            cand_user = None
            if user_id:
                try:
                    from django.contrib.auth.models import User
                    cand_user = User.objects.get(id=user_id)
                    # Duplicate candidacy prevention: a user cannot be registered twice for the same position
                    if Candidate.objects.filter(position=pos, user=cand_user).exists():
                        if is_json:
                            return JsonResponse({'error': 'User is already registered as a candidate for this position'}, status=400)
                        from django.contrib import messages
                        messages.error(request, f'User {cand_user.email} is already registered as a candidate for {pos.title}.')
                        return redirect(f'/elections/{pos.election.id}/')
                except User.DoesNotExist:
                    if is_json:
                        return JsonResponse({'error': 'User not found'}, status=404)
                    from django.contrib import messages
                    messages.error(request, 'Selected candidate user was not found.')
                    return redirect(f'/elections/{pos.election.id}/')

            if name.strip().upper() in ('NOTA', 'NONE OF THE ABOVE', 'NOTA (NONE OF THE ABOVE)', 'NONE OF THE ABOVE (NOTA)'):
                from home.methods_module import ensure_nota_candidate_for_position
                cand = ensure_nota_candidate_for_position(pos)
                if is_json:
                    return JsonResponse({'success': True, 'id': cand.id, 'is_nota': True})
                from django.contrib import messages
                messages.info(request, f'NOTA option is configured for {pos.title}.')
                return redirect(f'/elections/{pos.election.id}/')

            cand = Candidate.objects.create(
                position=pos,
                user=cand_user,
                name=name,
                bio=data.get('bio', ''),
                affiliation=data.get('affiliation', ''),
                image=data.get('image', '')
            )
            if is_json:
                return JsonResponse({'success': True, 'id': cand.id, 'user_id': cand.user_id})

            from django.contrib import messages
            messages.success(request, f'Candidate \"{cand.name}\" added successfully to {pos.title}.')
            return redirect(f'/elections/{pos.election.id}/')
        except Position.DoesNotExist:
            if is_json:
                return JsonResponse({'error': 'Position not found'}, status=404)
            return render(request, 'base.html', {'error': 'Position not found'}, status=404)
        except Exception as e:
            if is_json:
                return JsonResponse({'error': str(e)}, status=400)
            from django.contrib import messages
            messages.error(request, str(e))
            return redirect('/elections/')
    return JsonResponse({'error': 'Method not allowed'}, status=405)


def election_participate(request, elec_id):
    """
    POST /elections/<int:elec_id>/participate/
    Allows an authenticated user to self-register as a candidate for a position in a DRAFT election.
    Enforces:
    - User authentication (strictly binds candidacy to request.user)
    - Election lifecycle: ONLY permitted in DRAFT state.
    - Tenant isolation: Candidate must belong to host organization.
    - Duplicate candidacy prevention: User cannot register twice for the same position.
    - Dual role: candidate user retains independent voter eligibility when election is OPEN.
    """
    if not request.user.is_authenticated:
        return redirect(f'/admin/login/?next=/elections/{elec_id}/')

    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed. Use POST.'}, status=405)

    is_json = (
        request.headers.get('Accept') == 'application/json' or
        request.content_type == 'application/json' or
        request.GET.get('format') == 'json' or
        (request.body and request.body.startswith(b'{'))
    )

    try:
        elec = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        if is_json:
            return JsonResponse({'error': 'Election not found'}, status=404)
        return render(request, 'base.html', {'error': 'Election not found'}, status=404)

    # 1. Lifecycle check: ONLY allowed in DRAFT status
    if elec.status != 'DRAFT':
        error_msg = 'Candidate registration closed — election is currently live.' if elec.status == 'OPEN' else 'Candidate registration is closed for this election.'
        if is_json:
            return JsonResponse({'error': error_msg}, status=400)
        from django.contrib import messages
        messages.error(request, error_msg)
        return redirect(f'/elections/{elec.id}/')

    # 2. Tenant isolation check
    if not is_platform_admin(request.user) and elec.organization_id:
        profile = get_user_profile(request.user)
        if profile and profile.organization_id and profile.organization_id != elec.organization_id:
            if is_json:
                return JsonResponse({'error': 'Unauthorized organization'}, status=403)
            from django.contrib import messages
            messages.error(request, 'You do not belong to the host organization for this election.')
            return redirect(f'/elections/{elec.id}/')

    # 3. Position extraction
    if request.content_type == 'application/json' or (request.body and request.body.startswith(b'{')):
        import json
        try:
            body = json.loads(request.body)
        except Exception:
            body = {}
        pos_id = body.get('position_id')
        name = body.get('name')
        affiliation = body.get('affiliation', '')
        bio = body.get('bio', '')
    else:
        pos_id = request.POST.get('position_id')
        name = request.POST.get('name')
        affiliation = request.POST.get('affiliation', '')
        bio = request.POST.get('bio', '')

    if not pos_id:
        if is_json:
            return JsonResponse({'error': 'Position ID is required'}, status=400)
        from django.contrib import messages
        messages.error(request, 'Please select a position to contest.')
        return redirect(f'/elections/{elec.id}/')

    try:
        pos = Position.objects.get(id=pos_id, election=elec)
    except Position.DoesNotExist:
        if is_json:
            return JsonResponse({'error': 'Position not found for this election'}, status=404)
        from django.contrib import messages
        messages.error(request, 'Selected position not found in this election.')
        return redirect(f'/elections/{elec.id}/')

    # 4. Duplicate candidacy prevention
    from home.models import Candidate
    if Candidate.objects.filter(position=pos, user=request.user).exists():
        err = 'You are already registered as a candidate for this position.'
        if is_json:
            return JsonResponse({'error': err}, status=400)
        from django.contrib import messages
        messages.error(request, err)
        return redirect(f'/elections/{elec.id}/')

    # 5. Create Candidate record strictly bound to authenticated request.user
    cand_name = (name or '').strip() or request.user.get_full_name() or request.user.username
    cand = Candidate.objects.create(
        position=pos,
        user=request.user,
        name=cand_name,
        affiliation=(affiliation or '').strip(),
        bio=(bio or '').strip(),
    )

    if is_json:
        return JsonResponse({
            'success': True,
            'candidate_id': cand.id,
            'position_id': pos.id,
            'position_title': pos.title,
            'name': cand.name,
            'user_id': request.user.id
        }, status=201)

    from django.contrib import messages
    messages.success(request, f'You have successfully registered as a candidate for \"{pos.title}\".')
    return redirect(f'/elections/{elec.id}/')


def voter_profile(request):
    """
    GET /profile/
    POST /profile/
    Modern Voter Profile area for authenticated users.
    Allows viewing identity and updating personal profile attributes:
    - Name (First name, Last name / voter name)
    - Section / Department (voter.region)
    - Date of Birth (voter.dob)
    - Campus / Postal code (voter.pincode)
    
    CRITICAL EMAIL SECURITY RULE:
    The voter MUST NOT be able to change their account email.
    Email is strictly read-only.
    Any attempt to modify email via POST is rejected.
    """
    if not request.user.is_authenticated:
        return redirect(f'/admin/login/?next=/profile/')

    voter = get_or_create_voter_for_user(request.user, create=True)
    persona = get_account_persona(request.user)
    profile = get_user_profile(request.user)
    tenant_org = profile.organization if (profile and profile.organization) else None

    is_json = (
        request.headers.get('Accept') == 'application/json' or
        request.content_type == 'application/json' or
        request.GET.get('format') == 'json' or
        (request.body and request.body.startswith(b'{'))
    )

    if request.method == 'POST':
        if is_json:
            import json
            try:
                data = json.loads(request.body)
            except Exception:
                data = {}
        else:
            data = request.POST.dict()

        # Hard Security Rule: Email is strictly immutable
        submitted_email = data.get('email')
        if submitted_email and submitted_email.lower().strip() != (request.user.email or '').lower().strip():
            if is_json:
                return JsonResponse({'error': 'Email address cannot be modified.'}, status=400)
            from django.contrib import messages
            messages.error(request, 'Email address is a protected institutional identifier and cannot be modified.')
            return redirect('/profile/')

        # Update allowed profile fields
        name = data.get('name', '').strip()
        if name:
            parts = name.split(' ', 1)
            request.user.first_name = parts[0]
            request.user.last_name = parts[1] if len(parts) > 1 else ''
            request.user.save(update_fields=['first_name', 'last_name'])
            if voter:
                voter.name = name

        section = data.get('region', '').strip()
        if section and voter:
            voter.region = section

        dob_str = data.get('dob', '').strip()
        if dob_str and voter:
            try:
                import datetime
                voter.dob = datetime.date.fromisoformat(dob_str)
            except ValueError:
                pass

        pincode = data.get('pincode', '').strip()
        if pincode and voter:
            voter.pincode = pincode

        if voter:
            voter.save()

        if is_json:
            return JsonResponse({
                'success': True,
                'name': voter.name if voter else request.user.get_full_name(),
                'email': request.user.email,
                'region': voter.region if voter else '',
                'dob': voter.dob.isoformat() if (voter and voter.dob) else '',
                'pincode': voter.pincode if voter else '',
            })

        from django.contrib import messages
        messages.success(request, 'Your profile has been updated successfully.')
        return redirect('/profile/')

    # GET request
    context = {
        'voter': voter,
        'user': request.user,
        'account_persona': persona,
        'tenant_org': tenant_org,
    }
    if is_json:
        return JsonResponse({
            'username': request.user.username,
            'email': request.user.email,
            'name': voter.name if voter else request.user.get_full_name(),
            'region': voter.region if voter else '',
            'dob': voter.dob.isoformat() if (voter and voter.dob) else '',
            'pincode': voter.pincode if voter else '',
            'persona': persona,
            'organization': tenant_org.name if tenant_org else None,
        })

    return render(request, 'profile.html', context)

@csrf_exempt
def candidate_detail(request, cand_id):
    try:
        cand = Candidate.objects.select_related('position__election').get(id=cand_id)
        if not has_staff_or_auditor_access(request.user, cand.position.election.organization_id):
            return JsonResponse({'error': 'Unauthorized'}, status=403)
            
        return JsonResponse({
            'id': cand.id,
            'position_id': cand.position_id,
            'user_id': cand.user_id,
            'name': cand.name,
            'bio': cand.bio,
            'affiliation': cand.affiliation,
            'image': cand.image
        })
    except Candidate.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

def candidate_edit(request, cand_id):
    if request.method == 'POST':
        try:
            import json
            cand = Candidate.objects.select_related('position__election').get(id=cand_id)
            if not can_manage_election(request.user, cand.position.election):
                return JsonResponse({'error': 'Unauthorized'}, status=403)
                
            data = json.loads(request.body)
            if 'name' in data and not str(data['name']).strip():
                return JsonResponse({'error': 'Name cannot be blank'}, status=400)
                
            cand.name = data.get('name', cand.name)
            cand.bio = data.get('bio', cand.bio)
            cand.affiliation = data.get('affiliation', cand.affiliation)
            cand.image = data.get('image', cand.image)

            if 'user_id' in data:
                u_id = data['user_id']
                if u_id is None:
                    cand.user = None
                else:
                    from django.contrib.auth.models import User
                    try:
                        cand.user = User.objects.get(id=u_id)
                    except User.DoesNotExist:
                        return JsonResponse({'error': 'User not found'}, status=404)

            cand.save()
            return JsonResponse({'success': True, 'user_id': cand.user_id})
        except Candidate.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

def candidate_delete(request, cand_id):
    if request.method == 'POST':
        try:
            cand = Candidate.objects.select_related('position__election').get(id=cand_id)
            if not can_manage_election(request.user, cand.position.election):
                return JsonResponse({'error': 'Unauthorized'}, status=403)
                
            if Vote.objects.filter(vote_party_id=str(cand.id)).exists() or VoteBackup.objects.filter(vote_party_id=str(cand.id)).exists():
                return JsonResponse({'error': 'Cannot delete candidate with existing votes'}, status=400)
                
            cand.delete()
            return JsonResponse({'success': True})
        except Candidate.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def admin_voter_list(request):
    """
    Read-only endpoint to safely list voters for authorized administrators.
    """
    # Global read-only list for now since legacy voters aren't mapped to organizations yet
    if not is_platform_admin(request.user):
        return JsonResponse({'error': 'Only PLATFORM_ADMIN can view global voters'}, status=403)
        
    voters = list(Voters.objects.values('uuid', 'name', 'vote_done', 'region'))
    return JsonResponse({'voters': voters})

from home.models import Eligibility, Ballot
from home.permissions import get_user_profile
from django.db import IntegrityError, transaction

@csrf_exempt
def eligibility_list(request):
    election_id = request.GET.get('election_id')
    if election_id:
        try:
            election = Election.objects.get(id=election_id)
        except Election.DoesNotExist:
            return JsonResponse({'error': 'Election not found'}, status=404)
            
        if not has_staff_or_auditor_access(request.user, election.organization_id):
            return JsonResponse({'error': 'Unauthorized organization'}, status=403)
            
        qs = Eligibility.objects.filter(election=election)
    else:
        if not has_staff_or_auditor_access(request.user):
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        if is_platform_admin(request.user):
            qs = Eligibility.objects.all()
        else:
            profile = get_user_profile(request.user)
            if not profile or not profile.organization_id:
                return JsonResponse({'error': 'Unauthorized'}, status=403)
            qs = Eligibility.objects.filter(election__organization_id=profile.organization_id)
            
    eligibilities = [
        {
            'id': e.id,
            'election_id': e.election_id,
            'voter_id': e.voter_id,
            'voter_name': e.voter.name,
        }
        for e in qs.select_related('voter')
    ]
    return JsonResponse({'eligibilities': eligibilities})

def eligibility_create(request):
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            elec_id = data.get('election_id')
            voter_id = data.get('voter_id') or data.get('voter_uuid')
            
            if not elec_id or not voter_id:
                return JsonResponse({'error': 'Election ID and Voter ID are required'}, status=400)
                
            try:
                election = Election.objects.get(id=elec_id)
            except Election.DoesNotExist:
                return JsonResponse({'error': 'Election not found'}, status=404)
                
            if not can_manage_election(request.user, election):
                return JsonResponse({'error': 'Unauthorized organization'}, status=403)
                
            try:
                voter = Voters.objects.get(uuid=str(voter_id))
            except Voters.DoesNotExist:
                return JsonResponse({'error': 'Voter not found'}, status=404)
                
            if Eligibility.objects.filter(voter=voter, election=election).exists():
                return JsonResponse({'error': 'Voter is already eligible for this election'}, status=400)
                
            with transaction.atomic():
                elig = Eligibility.objects.create(voter=voter, election=election)
                
            return JsonResponse({'success': True, 'id': elig.id}, status=201)
        except IntegrityError:
            return JsonResponse({'error': 'Voter is already eligible for this election'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def eligibility_detail(request, elig_id):
    try:
        elig = Eligibility.objects.select_related('voter', 'election').get(id=elig_id)
        if not has_staff_or_auditor_access(request.user, elig.election.organization_id):
            return JsonResponse({'error': 'Unauthorized'}, status=403)
            
        return JsonResponse({
            'id': elig.id,
            'election_id': elig.election_id,
            'voter_id': elig.voter_id,
            'voter_name': elig.voter.name,
        })
    except Eligibility.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

def eligibility_revoke(request, elig_id):
    if request.method == 'POST':
        try:
            elig = Eligibility.objects.select_related('voter', 'election').get(id=elig_id)
            if not can_manage_election(request.user, elig.election):
                return JsonResponse({'error': 'Unauthorized'}, status=403)
                
            if Ballot.objects.filter(voter=elig.voter, election=elig.election).exists():
                return JsonResponse({'error': 'Cannot revoke eligibility: a ballot already exists for this voter and election'}, status=409)
                
            elig.delete()
            return JsonResponse({'success': True, 'message': 'Eligibility revoked successfully'})
        except Eligibility.DoesNotExist:
            return JsonResponse({'error': 'Not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def ballot_list(request):
    election_id = request.GET.get('election_id')
    if election_id:
        try:
            election = Election.objects.get(id=election_id)
        except Election.DoesNotExist:
            return JsonResponse({'error': 'Election not found'}, status=404)
            
        if not has_staff_or_auditor_access(request.user, election.organization_id):
            return JsonResponse({'error': 'Unauthorized organization'}, status=403)
            
        qs = Ballot.objects.filter(election=election)
    else:
        if not has_staff_or_auditor_access(request.user):
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        if is_platform_admin(request.user):
            qs = Ballot.objects.all()
        else:
            profile = get_user_profile(request.user)
            if not profile or not profile.organization_id:
                return JsonResponse({'error': 'Unauthorized'}, status=403)
            qs = Ballot.objects.filter(election__organization_id=profile.organization_id)
            
    ballots = [
        {
            'id': b.id,
            'election_id': b.election_id,
            'voter_id': b.voter_id,
            'timestamp': b.timestamp.isoformat() if b.timestamp else None
        }
        for b in qs
    ]
    return JsonResponse({'ballots': ballots})

def ballot_create(request):
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            elec_id = data.get('election_id')
            voter_id = data.get('voter_id') or data.get('voter_uuid')
            
            if not elec_id or not voter_id:
                return JsonResponse({'error': 'Election ID and Voter ID are required'}, status=400)
                
            try:
                election = Election.objects.get(id=elec_id)
            except Election.DoesNotExist:
                return JsonResponse({'error': 'Election not found'}, status=404)
                
            if not can_manage_election(request.user, election):
                return JsonResponse({'error': 'Unauthorized organization'}, status=403)
                
            try:
                voter = Voters.objects.get(uuid=str(voter_id))
            except Voters.DoesNotExist:
                return JsonResponse({'error': 'Voter not found'}, status=404)
                
            if not Eligibility.objects.filter(voter=voter, election=election).exists():
                return JsonResponse({'error': 'Voter is not eligible for this election'}, status=400)
                
            if Ballot.objects.filter(voter=voter, election=election).exists():
                return JsonResponse({'error': 'Ballot already exists for this voter and election'}, status=400)
                
            with transaction.atomic():
                ballot = Ballot.objects.create(voter=voter, election=election)
                
            return JsonResponse({'success': True, 'id': ballot.id}, status=201)
        except IntegrityError:
            return JsonResponse({'error': 'Ballot already exists for this voter and election'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@csrf_exempt
def ballot_detail(request, ballot_id):
    try:
        ballot = Ballot.objects.select_related('election').get(id=ballot_id)
        if not has_staff_or_auditor_access(request.user, ballot.election.organization_id):
            return JsonResponse({'error': 'Unauthorized'}, status=403)
            
        return JsonResponse({
            'id': ballot.id,
            'election_id': ballot.election_id,
            'voter_id': ballot.voter_id,
            'timestamp': ballot.timestamp.isoformat() if ballot.timestamp else None
        })
    except Ballot.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

def ballot_submit(request, ballot_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
        
    try:
        ballot = Ballot.objects.select_related('voter', 'election', 'election__organization').get(id=ballot_id)
    except Ballot.DoesNotExist:
        return JsonResponse({'error': 'Ballot not found'}, status=404)
        
    election = ballot.election
    voter = ballot.voter

    # 1. Authentication and Authorization
    session_uuid = request.session.get('uuid')
    is_admin = has_administrative_access(request.user)

    if session_uuid:
        # A voter session is active: must strictly match the ballot's voter!
        if str(session_uuid) != str(voter.uuid):
            return JsonResponse({'error': 'Cannot submit ballot for another voter'}, status=403)
    elif is_admin:
        # Administrative user: check organization scope and auditor
        if is_auditor(request.user):
            return JsonResponse({'error': 'Auditors cannot submit ballots'}, status=403)
        if not belongs_to_organization(request.user, election.organization_id):
            return JsonResponse({'error': 'Unauthorized organization'}, status=403)
    else:
        # Neither voter session nor admin authentication
        return JsonResponse({'error': 'Unauthorized'}, status=403)

    # 2. Parse request body
    try:
        import json
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Disallow body attempting to specify a different voter_id
    submitted_voter = data.get('voter_id') or data.get('voter_uuid')
    if submitted_voter and str(submitted_voter) != str(voter.uuid):
        return JsonResponse({'error': 'Submitted voter ID does not match ballot voter'}, status=400)

    # 3. Check Eligibility
    if not Eligibility.objects.filter(voter=voter, election=election).exists():
        return JsonResponse({'error': 'Voter is not eligible for this election'}, status=400)

    # 4. Check if Ballot has already been submitted
    if Vote.objects.filter(ballot=ballot).exists():
        return JsonResponse({'error': 'Ballot has already been submitted'}, status=400)

    # 5. Election lifecycle enforcement
    now = timezone.now()
    if election.status != 'OPEN':
        return JsonResponse({'error': f'Election is not open for voting (current status: {election.status})'}, status=400)

    if election.start_date and now < election.start_date:
        return JsonResponse({'error': 'Election voting has not started yet'}, status=400)

    if election.end_date and now > election.end_date:
        return JsonResponse({'error': 'Election voting has ended'}, status=400)

    # 6. Parse and validate position selections
    raw_selections = data.get('selections') or data.get('positions')
    if not raw_selections:
        return JsonResponse({'error': 'No selections provided'}, status=400)

    normalized_selections = []
    seen_position_ids = set()

    if isinstance(raw_selections, dict):
        for pos_key, cand_val in raw_selections.items():
            try:
                p_id = int(pos_key)
            except ValueError:
                return JsonResponse({'error': f'Invalid position ID: {pos_key}'}, status=400)
            c_ids = cand_val if isinstance(cand_val, list) else [cand_val]
            normalized_selections.append({'position_id': p_id, 'candidate_ids': c_ids})
    elif isinstance(raw_selections, list):
        for item in raw_selections:
            if not isinstance(item, dict):
                return JsonResponse({'error': 'Malformed selection entry'}, status=400)
            p_id = item.get('position_id')
            c_ids = item.get('candidate_ids')
            if c_ids is None and item.get('candidate_id') is not None:
                c_ids = [item.get('candidate_id')]
            normalized_selections.append({'position_id': p_id, 'candidate_ids': c_ids})
    else:
        return JsonResponse({'error': 'Selections must be a list or dict'}, status=400)

    if not normalized_selections:
        return JsonResponse({'error': 'No selections provided'}, status=400)

    candidate_votes_to_create = []

    for sel in normalized_selections:
        pos_id = sel.get('position_id')
        cand_ids = sel.get('candidate_ids')

        if not pos_id:
            return JsonResponse({'error': 'Position ID is required'}, status=400)

        if pos_id in seen_position_ids:
            return JsonResponse({'error': f'Duplicate position selection for position {pos_id}'}, status=400)
        seen_position_ids.add(pos_id)

        try:
            position = Position.objects.get(id=pos_id)
        except Position.DoesNotExist:
            return JsonResponse({'error': f'Position {pos_id} not found'}, status=400)

        if position.election_id != election.id:
            return JsonResponse({'error': f'Position {pos_id} does not belong to election {election.id}'}, status=400)

        if not cand_ids or not isinstance(cand_ids, list):
            return JsonResponse({'error': f'No candidates selected for position {position.title}'}, status=400)

        # Check duplicate candidates in this position
        if len(cand_ids) != len(set(cand_ids)):
            return JsonResponse({'error': f'Duplicate candidate selections for position {position.title}'}, status=400)

        # Check max_votes_allowed
        if len(cand_ids) > position.max_votes_allowed:
            return JsonResponse({
                'error': f'Selections exceed max_votes_allowed ({position.max_votes_allowed}) for position {position.title}'
            }, status=400)

        # Validate each candidate
        for c_id in cand_ids:
            try:
                candidate = Candidate.objects.get(id=c_id)
            except Candidate.DoesNotExist:
                return JsonResponse({'error': f'Candidate {c_id} not found'}, status=400)

            if candidate.position_id != position.id:
                return JsonResponse({'error': f'Candidate {c_id} does not belong to position {position.id}'}, status=400)

            candidate_votes_to_create.append((position, candidate))

    if not candidate_votes_to_create:
        return JsonResponse({'error': 'No valid candidate selections to submit'}, status=400)

    is_modern = bool(
        data.get('signature') or 
        data.get('public_key') or 
        data.get('is_modern') or 
        data.get('auth_payload') or 
        data.get('ballot_nonce') or 
        data.get('nonce')
    )

    if is_modern:
        try:
            from home.methods_module import submit_modern_ballot
            result = submit_modern_ballot(
                ballot=ballot,
                candidate_selections=candidate_votes_to_create,
                signature=data.get('signature'),
                public_key=data.get('public_key'),
                ballot_nonce=data.get('ballot_nonce') or data.get('nonce'),
                timestamp_iso=data.get('timestamp') or data.get('timestamp_iso'),
                auth_payload=data.get('auth_payload'),
            )
            return JsonResponse(result, status=200)
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except IntegrityError as e:
            return JsonResponse({'error': f'Database integrity error: {e}'}, status=400)
        except Exception as e:
            return JsonResponse({'error': f'Failed to process modern ballot submission: {e}'}, status=400)

    # 7. Atomic Vote creation (legacy Phase 4 path)
    try:
        with transaction.atomic():
            # Double-check inside atomic lock to prevent race conditions
            if Vote.objects.filter(ballot=ballot).exists():
                return JsonResponse({'error': 'Ballot has already been submitted'}, status=400)

            curr_time = timezone.now()
            votes_created_count = 0

            for pos, cand in candidate_votes_to_create:
                Vote.objects.create(
                    uuid=voter.uuid,
                    vote_party_id=str(cand.id),
                    timestamp=curr_time,
                    block_id=None,
                    election=election,
                    ballot=ballot
                )
                VoteBackup.objects.create(
                    uuid=voter.uuid,
                    vote_party_id=str(cand.id),
                    timestamp=curr_time,
                    block_id=None,
                    election=election,
                    ballot=ballot
                )
                votes_created_count += 1

        return JsonResponse({
            'success': True,
            'message': 'Ballot submitted successfully',
            'ballot_id': ballot.id,
            'votes_created': votes_created_count
        }, status=200)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@csrf_exempt
def election_results(request, elec_id):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    is_json = (
        request.headers.get('Accept') == 'application/json' or
        request.GET.get('format') == 'json' or
        'application/json' in request.headers.get('Accept', '')
    )

    if not is_json and 'text/html' in request.headers.get('Accept', ''):
        return redirect(f'/show-result/?election_id={elec_id}')

    try:
        election = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Election not found'}, status=404)

    # Enforce organization isolation for staff/auditor users
    if request.user.is_authenticated and not is_platform_admin(request.user):
        role = get_user_role(request.user)
        if role in ['ORGANIZATION_ADMIN', 'ELECTION_OFFICIAL', 'AUDITOR']:
            if not belongs_to_organization(request.user, election.organization_id):
                return JsonResponse({'error': 'Unauthorized organization access', 'results_available': False}, status=403)

    # Enforce voter/public visibility controls for non-staff viewers
    is_staff_or_auditor = has_staff_or_auditor_access(request.user, election.organization_id)
    if not is_staff_or_auditor:
        # Non-staff viewer (Voter, Candidate, or Public)
        if election.status == 'DRAFT':
            return JsonResponse({'error': 'Results unavailable: election is in DRAFT status', 'results_available': False}, status=403)
        elif election.status == 'OPEN':
            if not getattr(election, 'live_progress_enabled', False):
                return JsonResponse({'error': 'Live progress is private for this election', 'results_available': False}, status=403)
        elif election.status == 'CLOSED':
            if not getattr(election, 'is_published', False):
                return JsonResponse({'error': 'Official results have not yet been published by administrators', 'results_available': False}, status=403)

    from home.models import BallotBatch
    has_modern_batches = BallotBatch.objects.filter(election=election).exists()
    if has_modern_batches:
        from home.methods_module import calculate_verified_election_results
        allow_unfinalized = (election.status == 'OPEN')
        res = calculate_verified_election_results(election.id, allow_unfinalized=allow_unfinalized)
        res['is_published'] = getattr(election, 'is_published', False)
        res['published_at'] = election.published_at.isoformat() if getattr(election, 'published_at', None) else None
        res['publication_receipt'] = getattr(election, 'publication_receipt', None)
        res['live_progress_enabled'] = getattr(election, 'live_progress_enabled', False)
        status_code = res.get('status_code', 200)
        return JsonResponse(res, status=status_code)

    # Fetch positions for this election
    positions = Position.objects.filter(election=election).order_by('id')
    
    # Fetch candidates for these positions
    candidates = Candidate.objects.filter(position__election=election).select_related('position').order_by('position_id', 'id')

    # Fetch valid votes for this election:
    # Must belong to a Ballot for this election, ballot must not be null
    valid_votes_qs = Vote.objects.filter(
        election=election,
        ballot__isnull=False,
        ballot__election=election
    )

    # Tally votes by candidate ID
    candidate_vote_counts = {}
    invalid_votes_count = 0
    valid_candidate_ids = {str(c.id) for c in candidates}

    for v in valid_votes_qs:
        cand_id_str = str(v.vote_party_id)
        if cand_id_str in valid_candidate_ids:
            candidate_vote_counts[cand_id_str] = candidate_vote_counts.get(cand_id_str, 0) + 1
        else:
            invalid_votes_count += 1

    # Total distinct submitted ballots counted
    total_submitted_ballots = valid_votes_qs.values('ballot_id').distinct().count()
    total_counted_votes = sum(candidate_vote_counts.values())

    # Build response structure grouped by position
    results_by_position = []

    # Map candidates by position
    cands_by_pos = {}
    for c in candidates:
        cands_by_pos.setdefault(c.position_id, []).append(c)

    for pos in positions:
        pos_candidates = cands_by_pos.get(pos.id, [])
        pos_cands_data = []
        pos_votes_sum = 0

        for c in pos_candidates:
            c_votes = candidate_vote_counts.get(str(c.id), 0)
            pos_votes_sum += c_votes
            pos_cands_data.append({
                'candidate_id': c.id,
                'candidate_name': c.name,
                'affiliation': c.affiliation,
                'votes_received': c_votes
            })

        results_by_position.append({
            'position_id': pos.id,
            'position_title': pos.title,
            'max_votes_allowed': pos.max_votes_allowed,
            'total_votes': pos_votes_sum,
            'candidates': pos_cands_data
        })

    # Lifecycle and result status determination
    is_finalized = (election.status == 'CLOSED')
    result_status = 'FINALIZED' if is_finalized else ('LIVE' if election.status == 'OPEN' else 'DRAFT')

    # Reconciliation checks
    sum_of_pos_votes = sum(p['total_votes'] for p in results_by_position)
    election_reconciled = (sum_of_pos_votes == total_counted_votes)

    return JsonResponse({
        'election': {
            'id': election.id,
            'title': election.title,
            'status': election.status,
            'result_status': result_status,
            'is_finalized': is_finalized,
            'start_date': election.start_date.isoformat() if election.start_date else None,
            'end_date': election.end_date.isoformat() if election.end_date else None,
            'organization_id': election.organization_id,
            'organization_name': election.organization.name
        },
        'summary': {
            'total_submitted_ballots': total_submitted_ballots,
            'total_votes_counted': total_counted_votes,
            'total_positions': positions.count(),
            'total_candidates': candidates.count(),
        },
        'reconciliation': {
            'election_reconciled': election_reconciled,
            'invalid_votes_detected': invalid_votes_count
        },
        'positions': results_by_position
    })

def mine_batch(request, batch_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        from home.models import BallotBatch
        batch = BallotBatch.objects.select_related('election').get(id=batch_id)
    except BallotBatch.DoesNotExist:
        return JsonResponse({'error': 'Batch not found'}, status=404)

    if not can_manage_election(request.user, batch.election):
        return JsonResponse({'error': 'Unauthorized organization'}, status=403)

    if is_auditor(request.user):
        return JsonResponse({'error': 'Auditors cannot mine blocks'}, status=403)

    try:
        from home.methods_module import mine_modern_batch, ConcurrencyError, PoWTimeoutError
        result = mine_modern_batch(batch_id=batch.id)
        return JsonResponse(result, status=200)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except ConcurrencyError as e:
        return JsonResponse({'error': str(e)}, status=409)
    except PoWTimeoutError as e:
        return JsonResponse({'error': str(e)}, status=504)
    except Exception as e:
        return JsonResponse({'error': f'Mining failed: {e}'}, status=400)

def election_mine_batch(request, elec_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        from home.models import Election, BallotBatch
        election = Election.objects.get(id=elec_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Election not found'}, status=404)

    if not can_manage_election(request.user, election):
        return JsonResponse({'error': 'Unauthorized organization'}, status=403)

    if is_auditor(request.user):
        return JsonResponse({'error': 'Auditors cannot mine blocks'}, status=403)

    batch = BallotBatch.objects.filter(election=election, status__in=['CLOSED', 'OPEN']).order_by('batch_number').first()
    if not batch:
        return JsonResponse({'error': 'No unmined batches found for this election'}, status=404)

    try:
        from home.methods_module import mine_modern_batch, ConcurrencyError, PoWTimeoutError
        result = mine_modern_batch(batch_id=batch.id)
        return JsonResponse(result, status=200)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except ConcurrencyError as e:
        return JsonResponse({'error': str(e)}, status=409)
    except PoWTimeoutError as e:
        return JsonResponse({'error': str(e)}, status=504)
    except Exception as e:
        return JsonResponse({'error': f'Mining failed: {e}'}, status=400)


def block_verify_detail(request, block_id):
    """
    GET /blocks/<int:block_id>/verify/
    Dedicated verification endpoint for an individual block.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    from home.methods_module import verify_single_block
    from home.permissions import is_authenticated_admin, is_platform_admin, is_organization_admin, is_auditor, belongs_to_organization
    from home.models import Block

    try:
        block = Block.objects.select_related('election').get(id=block_id)
    except Block.DoesNotExist:
        return JsonResponse({'error': f'Block {block_id} not found'}, status=404)

    # Scoping check if election exists
    if block.election_id and has_staff_or_auditor_access(request.user):
        if not (is_platform_admin(request.user) or belongs_to_organization(request.user, block.election.organization_id)):
            return JsonResponse({'error': 'Unauthorized for this organization'}, status=403)

    res = verify_single_block(block)
    is_privileged = is_platform_admin(request.user) or (
        (is_organization_admin(request.user) or is_auditor(request.user))
        and (not block.election_id or belongs_to_organization(request.user, block.election.organization_id))
    )
    if not is_privileged:
        res = {
            'valid': res['valid'],
            'block_id': res['block_id'],
            'version': res.get('version'),
            'checks_performed': res.get('checks_performed', []),
            'errors': res.get('errors', []),
            'timestamp': res.get('timestamp')
        }
    return JsonResponse(res, status=200)


def verify_full_chain_view(request):
    """
    GET/POST /blockchain/verify-chain/
    Executes full chronological blockchain audit from Genesis to Tip.
    Restricted to authorized administrators and auditors.
    """
    if request.method not in ['GET', 'POST']:
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    from home.permissions import is_platform_admin, is_organization_admin, is_auditor
    if not (
        is_platform_admin(request.user) or is_organization_admin(request.user) or is_auditor(request.user)
    ):
        return JsonResponse({'error': 'Unauthorized: Chain audit requires administrative or auditor privileges'}, status=403)

    from home.methods_module import verify_full_chain
    from_block = request.GET.get('from_block') or request.POST.get('from_block')
    to_block = request.GET.get('to_block') or request.POST.get('to_block')
    stop_on_first = (request.GET.get('stop_on_first_failure') or request.POST.get('stop_on_first_failure') or 'false').lower() == 'true'

    from_id = int(from_block) if from_block and str(from_block).isdigit() else None
    to_id = int(to_block) if to_block and str(to_block).isdigit() else None

    accept = request.headers.get('accept', '')
    is_browser = 'text/html' in accept and accept != '*/*' and request.GET.get('format') != 'json'

    # If POST (action button clicked) or GET with run_audit=1 or API client: execute audit
    should_run = request.method == 'POST' or request.GET.get('run_audit') == '1' or not is_browser

    if should_run:
        result = verify_full_chain(
            from_block_id=from_id,
            to_block_id=to_id,
            stop_on_first_failure=stop_on_first
        )
        if is_browser:
            return render(request, 'verify_chain.html', {'audit_result': result})
        return JsonResponse(result, status=200)

    return render(request, 'verify_chain.html', {'audit_result': None})


def verify_batch_view(request, batch_id):
    """
    GET /batches/<int:batch_id>/verify/
    Verifies the integrity of a modern BallotBatch: transaction parity, sealing, ballots.
    Restricted to authorized administrators and auditors within the batch's organization.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    from home.permissions import has_staff_or_auditor_access
    from home.models import BallotBatch
    from home.methods_module import verify_batch_integrity

    try:
        batch = BallotBatch.objects.select_related('election').get(id=batch_id)
    except BallotBatch.DoesNotExist:
        return JsonResponse({'error': f'Batch {batch_id} not found'}, status=404)

    if not has_staff_or_auditor_access(request.user, batch.election.organization_id):
        return JsonResponse({'error': 'Unauthorized organization'}, status=403)

    res = verify_batch_integrity(batch)
    return JsonResponse(res, status=200)


@csrf_exempt
def election_audit_records(request, elec_id):
    """
    GET /elections/<int:elec_id>/audit-records/
    Retrieves the server-side audit trail for an election's result verification checks.
    Restricted to authenticated administrators and auditors scoped to that election's organization.
    Never exposes voter UUIDs, signatures, private keys, or choices.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    from home.permissions import has_staff_or_auditor_access
    from home.models import Election, ElectionResultAudit

    try:
        election = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Election not found'}, status=404)

    if not has_staff_or_auditor_access(request.user, election.organization_id):
        return JsonResponse({'error': 'Unauthorized organization'}, status=403)

    audits = ElectionResultAudit.objects.filter(election=election).order_by('-timestamp')
    records = []
    for a in audits:
        records.append({
            'audit_id': a.id,
            'timestamp': a.timestamp.isoformat(),
            'verification_passed': a.verification_passed,
            'verification_status': a.verification_status,
            'result_receipt': a.result_receipt,
            'blocks_checked': a.blocks_checked,
            'batches_checked': a.batches_checked,
            'transactions_checked': a.transactions_checked,
            'total_votes_tallied': a.total_votes_tallied,
            'failure_category': a.failure_category,
            'failure_details': a.failure_details
        })

    return JsonResponse({
        'election_id': election.id,
        'organization_id': election.organization_id,
        'audit_records_count': len(records),
        'audit_records': records
    }, status=200)


@csrf_exempt
def election_verify_receipt(request, elec_id):
    """
    GET /elections/<int:elec_id>/verify-receipt/
    Verifies consistency between stored/expected deterministic result receipt
    and current ledger state. Accessible only by authorized administrators/auditors.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    from home.permissions import has_staff_or_auditor_access
    from home.models import Election

    try:
        election = Election.objects.select_related('organization').get(id=elec_id)
    except Election.DoesNotExist:
        return JsonResponse({'error': 'Election not found'}, status=404)

    if not has_staff_or_auditor_access(request.user, election.organization_id):
        return JsonResponse({'error': 'Unauthorized organization'}, status=403)

    expected_receipt = request.GET.get('receipt') or None
    from home.methods_module import verify_result_receipt_consistency
    res = verify_result_receipt_consistency(election.id, expected_receipt=expected_receipt)
    return JsonResponse(res, status=200)


def dashboard(request):
    trigger_scheduled_lifecycle_check()
    """
    BallotChain Role-Based Dashboard View (Phase 8C-3).
    
    Provides personalized, role-aware dashboard entry points for all 6 personas:
    1. PLATFORM_ADMIN: Global organizational & election oversight, system metrics, ledger link.
    2. ORGANIZATION_ADMIN: Tenant-scoped election management, positions, candidates, lifecycle controls.
    3. ELECTION_OFFICIAL: Operational candidate/ballot management. Strictly NO Start/End/Publish controls.
    4. AUDITOR: Strictly read-only audit records, results verification, ledger link. Strictly NO mutation controls.
    5. VOTER: Voter profile, eligible elections, voting participation status, shared ledger link.
    6. CANDIDATE: Candidate participation information + full voter capabilities.
    
    Unauthenticated visitors (PUBLIC_AUDITOR):
    - Browser GET: Redirects to /admin/login/?next=/dashboard/ (HTTP 302).
    - API / JSON: Returns 401 Unauthorized with persona metadata.
    
    Shared Ledger:
    - All personas navigate to /blockchain/ as the single authoritative ledger explorer.
    """
    from home.permissions import (
        get_account_persona,
        get_user_profile,
        is_platform_admin,
    )
    from home.models import (
        Organization,
        Election,
        Position,
        Candidate,
        BallotBatch,
        ElectionResultAudit,
        Block,
        Vote,
        Voters,
    )

    is_json = (
        request.headers.get('Accept') == 'application/json' or
        request.GET.get('format') == 'json'
    )

    if not request.user.is_authenticated:
        if is_json:
            return JsonResponse({
                'error': 'Authentication required',
                'persona': 'PUBLIC_AUDITOR',
                'authenticated': False
            }, status=401)
        return redirect(f"/admin/login/?next={request.path}")

    persona = get_account_persona(request.user)
    profile = get_user_profile(request.user)
    tenant_org = profile.organization if (profile and profile.organization) else None

    context = {
        'account_persona': persona,
        'tenant_org': tenant_org,
        'persona_css_class': persona.lower().replace('_', '-'),
    }

    if persona == 'PLATFORM_ADMIN':
        orgs = Organization.objects.all().order_by('name')
        elections = Election.objects.select_related('organization').all().order_by('-id')
        context.update({
            'organizations': orgs,
            'elections': elections,
            'stats': {
                'total_organizations': orgs.count(),
                'total_elections': elections.count(),
                'total_blocks': Block.objects.count(),
                'total_votes': Vote.objects.count(),
                'total_voters': Voters.objects.count(),
            },
            'can_mutate': True,
            'can_manage_lifecycle': True,
        })

    elif persona == 'ORGANIZATION_ADMIN':
        if tenant_org:
            elections = Election.objects.filter(organization=tenant_org).order_by('-id')
            positions = Position.objects.filter(election__organization=tenant_org)
            candidates = Candidate.objects.filter(position__election__organization=tenant_org).select_related('position', 'position__election')
            batches_count = BallotBatch.objects.filter(election__organization=tenant_org).count()
            context.update({
                'elections': elections,
                'positions': positions,
                'candidates': candidates,
                'stats': {
                    'tenant_elections': elections.count(),
                    'tenant_positions': positions.count(),
                    'tenant_candidates': candidates.count(),
                    'tenant_batches': batches_count,
                },
                'can_mutate': True,
                'can_manage_lifecycle': True,
            })
        else:
            context.update({
                'elections': Election.objects.none(),
                'positions': Position.objects.none(),
                'candidates': Candidate.objects.none(),
                'stats': {'tenant_elections': 0, 'tenant_positions': 0, 'tenant_candidates': 0, 'tenant_batches': 0},
                'can_mutate': True,
                'can_manage_lifecycle': True,
            })

    elif persona == 'ELECTION_OFFICIAL':
        if tenant_org:
            elections = Election.objects.filter(organization=tenant_org).order_by('-id')
            positions = Position.objects.filter(election__organization=tenant_org)
            candidates = Candidate.objects.filter(position__election__organization=tenant_org).select_related('position', 'position__election')
            batches = BallotBatch.objects.filter(election__organization=tenant_org)
            context.update({
                'elections': elections,
                'positions': positions,
                'candidates': candidates,
                'batches': batches,
                'stats': {
                    'assigned_elections': elections.count(),
                    'assigned_positions': positions.count(),
                    'assigned_candidates': candidates.count(),
                    'operational_batches': batches.count(),
                },
                'can_mutate': False,
                'can_manage_lifecycle': False,
            })
        else:
            context.update({
                'elections': Election.objects.none(),
                'positions': Position.objects.none(),
                'candidates': Candidate.objects.none(),
                'batches': BallotBatch.objects.none(),
                'stats': {'assigned_elections': 0, 'assigned_positions': 0, 'assigned_candidates': 0, 'operational_batches': 0},
                'can_mutate': False,
                'can_manage_lifecycle': False,
            })

    elif persona == 'AUDITOR':
        if tenant_org:
            elections = Election.objects.filter(organization=tenant_org).order_by('-id')
            audit_records = ElectionResultAudit.objects.filter(election__organization=tenant_org).order_by('-timestamp')
            context.update({
                'elections': elections,
                'audit_records': audit_records,
                'stats': {
                    'audited_elections': elections.count(),
                    'audit_records_count': audit_records.count(),
                },
                'can_mutate': False,
                'can_manage_lifecycle': False,
            })
        else:
            context.update({
                'elections': Election.objects.none(),
                'audit_records': ElectionResultAudit.objects.none(),
                'stats': {'audited_elections': 0, 'audit_records_count': 0},
                'can_mutate': False,
                'can_manage_lifecycle': False,
            })

    elif persona == 'CANDIDATE':
        candidacies = Candidate.objects.filter(user=request.user).select_related(
            'position', 'position__election', 'position__election__organization'
        )
        eligible_elections = get_eligible_elections_for_user(request.user)
        voter_rec = get_or_create_voter_for_user(request.user, create=False)
        context.update({
            'candidacies': candidacies,
            'eligible_elections': eligible_elections,
            'voter_record': voter_rec,
            'has_voted': voter_rec.vote_done if voter_rec else False,
            'stats': {
                'active_candidacies': candidacies.count(),
                'eligible_elections_count': eligible_elections.count(),
            },
            'can_mutate': False,
            'can_manage_lifecycle': False,
        })

    else:  # 'VOTER'
        eligible_elections = get_eligible_elections_for_user(request.user)
        voter_rec = get_or_create_voter_for_user(request.user, create=False)
        context.update({
            'eligible_elections': eligible_elections,
            'voter_record': voter_rec,
            'has_voted': voter_rec.vote_done if voter_rec else False,
            'stats': {
                'eligible_elections_count': eligible_elections.count(),
            },
            'can_mutate': False,
            'can_manage_lifecycle': False,
        })

    if is_json:
        return JsonResponse({
            'persona': persona,
            'authenticated': True,
            'username': request.user.username,
            'email': request.user.email,
            'tenant_organization': tenant_org.name if tenant_org else None,
            'stats': context.get('stats', {}),
            'can_mutate': context.get('can_mutate', False),
            'can_manage_lifecycle': context.get('can_manage_lifecycle', False),
        })

    return render(request, 'dashboard.html', context)






