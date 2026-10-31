from django.db import models
from django.contrib.auth.models import User

class Voters(models.Model):
    uuid = models.CharField(max_length = 20, primary_key=True)
    name = models.CharField(max_length = 100)
    dob = models.DateField()
    pincode = models.CharField(max_length = 6)
    region = models.CharField(max_length = 100)
    profile_pic = models.CharField(max_length = 500, blank=True)
    email = models.CharField(max_length = 100, blank=True)
    vote_done = models.BooleanField(default = False)

class PoliticalParty(models.Model):
    party_id = models.CharField(max_length=10, primary_key=True)
    party_name = models.CharField(max_length=100)
    party_logo = models.CharField(max_length=500)
    candidate_name = models.CharField(max_length=100, blank=True)
    candidate_profile_pic = models.CharField(max_length=500, blank=True)

class Eligibility(models.Model):
    voter = models.ForeignKey(Voters, on_delete=models.CASCADE)
    election = models.ForeignKey('Election', on_delete=models.CASCADE)
    
    class Meta:
        unique_together = ('voter', 'election')

class BallotBatch(models.Model):
    election = models.ForeignKey('Election', on_delete=models.CASCADE)
    batch_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, default='OPEN')
    ballot_count = models.PositiveIntegerField(default=0)
    expected_tx_count = models.PositiveIntegerField(default=0)
    miner_lock_id = models.CharField(max_length=64, null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    sealed_block_id = models.CharField(max_length=10, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('election', 'batch_number')

class Ballot(models.Model):
    voter = models.ForeignKey(Voters, on_delete=models.CASCADE)
    election = models.ForeignKey('Election', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    ballot_nonce = models.CharField(max_length=64, null=True, blank=True)
    ballot_tracker = models.CharField(max_length=64, null=True, blank=True, unique=True, db_index=True)
    signature = models.TextField(null=True, blank=True)
    public_key = models.TextField(null=True, blank=True)
    is_sealed = models.BooleanField(default=False)
    sealed_block_id = models.CharField(max_length=10, null=True, blank=True)
    batch = models.ForeignKey(BallotBatch, null=True, blank=True, on_delete=models.SET_NULL)
    
    class Meta:
        unique_together = [('voter', 'election'), ('election', 'ballot_nonce')]

class Vote(models.Model):
    id = models.BigAutoField(primary_key=True)
    uuid = models.CharField(max_length=20)
    vote_party_id = models.CharField(max_length=10)
    timestamp = models.DateTimeField()
    block_id = models.CharField(null=True, max_length=10)
    election = models.ForeignKey('Election', null=True, blank=True, on_delete=models.CASCADE)
    ballot = models.ForeignKey(Ballot, null=True, blank=True, on_delete=models.CASCADE)
    tx_id = models.CharField(max_length=64, null=True, blank=True, unique=True, db_index=True)
    commitment_salt = models.CharField(max_length=64, null=True, blank=True)
    position = models.ForeignKey('Position', null=True, blank=True, on_delete=models.CASCADE)
    batch = models.ForeignKey(BallotBatch, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-timestamp']

    @property
    def candidate(self):
        try:
            from home.models import Candidate
            return Candidate.objects.get(id=int(self.vote_party_id))
        except (ValueError, Candidate.DoesNotExist):
            return None

class VoteBackup(models.Model):
    id = models.BigAutoField(primary_key=True)
    uuid = models.CharField(max_length=20)
    vote_party_id = models.CharField(max_length=10)
    timestamp = models.DateTimeField()
    block_id = models.CharField(null=True, max_length=10)
    election = models.ForeignKey('Election', null=True, blank=True, on_delete=models.CASCADE)
    ballot = models.ForeignKey(Ballot, null=True, blank=True, on_delete=models.CASCADE)
    tx_id = models.CharField(max_length=64, null=True, blank=True, unique=True, db_index=True)
    commitment_salt = models.CharField(max_length=64, null=True, blank=True)
    position = models.ForeignKey('Position', null=True, blank=True, on_delete=models.CASCADE)
    batch = models.ForeignKey(BallotBatch, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-timestamp']

    @property
    def candidate(self):
        try:
            from home.models import Candidate
            return Candidate.objects.get(id=int(self.vote_party_id))
        except (ValueError, Candidate.DoesNotExist):
            return None

class Block(models.Model):
    prev_hash = models.CharField(max_length=100, blank=True)
    merkle_hash = models.CharField(max_length=100, blank=True)
    this_hash = models.CharField(max_length=100, blank=True)
    nonce = models.IntegerField(null=True)
    timestamp = models.DateTimeField()
    version = models.PositiveSmallIntegerField(default=1)
    election = models.ForeignKey('Election', null=True, blank=True, on_delete=models.SET_NULL)
    batch_number = models.PositiveIntegerField(null=True, blank=True)
    candidate_tx_count = models.PositiveIntegerField(default=1)
    merkle_leaf_count = models.PositiveIntegerField(default=1)

class MiningInfo(models.Model):
    prev_hash = models.CharField(max_length=100, blank=True)
    last_block_id = models.CharField(null=True, max_length=10)

class Organization(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    contact_information = models.TextField(blank=True)

class Election(models.Model):
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('OPEN', 'Open'),
        ('CLOSED', 'Closed'),
    )
    
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    is_published = models.BooleanField(default=False, help_text='Controls whether finalized results are released to voters and the public')
    published_at = models.DateTimeField(null=True, blank=True, help_text='Timestamp when verified results were officially published')
    publication_receipt = models.CharField(max_length=64, null=True, blank=True, help_text='Deterministic SHA3-256 verification receipt certified at publication')
    live_progress_enabled = models.BooleanField(default=False, help_text='Controls whether verified interim tally progress is visible while election is OPEN')

class Position(models.Model):
    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    max_votes_allowed = models.IntegerField(default=1)

class Candidate(models.Model):
    position = models.ForeignKey(Position, on_delete=models.CASCADE)
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='candidacies',
        help_text='Authenticated user account participating as this candidate'
    )
    name = models.CharField(max_length=255)
    bio = models.TextField(blank=True)
    image = models.CharField(max_length=500, blank=True)
    affiliation = models.CharField(max_length=255, blank=True)
    is_nota = models.BooleanField(default=False)

    @property
    def is_nota_choice(self):
        return self.is_nota or (self.name and self.name.strip().upper() in ('NOTA', 'NONE OF THE ABOVE', 'NOTA (NONE OF THE ABOVE)', 'NONE OF THE ABOVE (NOTA)'))

    def save(self, *args, **kwargs):
        if self.name and self.name.strip().upper() in ('NOTA', 'NONE OF THE ABOVE', 'NOTA (NONE OF THE ABOVE)', 'NONE OF THE ABOVE (NOTA)'):
            self.is_nota = True
        super().save(*args, **kwargs)

    @property
    def legacy_vote_party_id(self):
        return str(self.id)

class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('PLATFORM_ADMIN', 'Platform Admin'),
        ('ORGANIZATION_ADMIN', 'Organization Admin'),
        ('ELECTION_OFFICIAL', 'Election Official'),
        ('AUDITOR', 'Auditor'),
    )
    
    from django.contrib.auth.models import User
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES)
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.CASCADE)

class ElectionResultAudit(models.Model):
    election = models.ForeignKey(Election, on_delete=models.CASCADE, related_name='result_audits')
    timestamp = models.DateTimeField(auto_now_add=True)
    verification_passed = models.BooleanField(default=False)
    verification_status = models.CharField(max_length=50)  # 'VERIFIED', 'FAILED', 'ERROR'
    result_receipt = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    blocks_checked = models.PositiveIntegerField(default=0)
    batches_checked = models.PositiveIntegerField(default=0)
    transactions_checked = models.PositiveIntegerField(default=0)
    total_votes_tallied = models.PositiveIntegerField(default=0)
    failure_category = models.CharField(max_length=100, null=True, blank=True)
    failure_details = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-timestamp']

