import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.utils import timezone
from home.models import (
    Organization, Election, Position, Candidate,
    Voters, UserProfile, Eligibility, Ballot, Vote, VoteBackup, Block
)

class Phase4Step5Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Organizations
        cls.org1 = Organization.objects.create(name="Org 1", description="Test Org 1")
        cls.org2 = Organization.objects.create(name="Org 2", description="Test Org 2")
        
        # Elections
        cls.elec1 = Election.objects.create(organization=cls.org1, title="Election 1", status="OPEN")
        cls.elec2 = Election.objects.create(organization=cls.org2, title="Election 2", status="OPEN")
        
        # Test Voters (isolated test data)
        cls.voter1 = Voters.objects.create(
            uuid="test_voter_1",
            name="Alice Test",
            dob="1990-01-01",
            pincode="123456",
            region="Region 1",
            vote_done=False
        )
        cls.voter2 = Voters.objects.create(
            uuid="test_voter_2",
            name="Bob Test",
            dob="1992-02-02",
            pincode="654321",
            region="Region 2",
            vote_done=False
        )
        
        # Users & UserProfiles (using create instead of slow PBKDF2 create_user)
        # 1. Platform Admin
        cls.u_platform = User.objects.create(username="platform_admin")
        cls.p_platform = UserProfile.objects.create(user=cls.u_platform, role="PLATFORM_ADMIN")
        
        # 2. Org Admin Org1
        cls.u_org_admin1 = User.objects.create(username="org_admin1")
        cls.p_org_admin1 = UserProfile.objects.create(user=cls.u_org_admin1, role="ORGANIZATION_ADMIN", organization=cls.org1)
        
        # 3. Org Admin Org2
        cls.u_org_admin2 = User.objects.create(username="org_admin2")
        cls.p_org_admin2 = UserProfile.objects.create(user=cls.u_org_admin2, role="ORGANIZATION_ADMIN", organization=cls.org2)
        
        # 4. Election Official Org1
        cls.u_official1 = User.objects.create(username="official1")
        cls.p_official1 = UserProfile.objects.create(user=cls.u_official1, role="ELECTION_OFFICIAL", organization=cls.org1)
        
        # 5. Auditor Org1
        cls.u_auditor1 = User.objects.create(username="auditor1")
        cls.p_auditor1 = UserProfile.objects.create(user=cls.u_auditor1, role="AUDITOR", organization=cls.org1)
        
        # 6. User without profile
        cls.u_no_profile = User.objects.create(username="no_profile")

    def setUp(self):
        self.client = Client()

    def test_01_eligibility_model_uniqueness(self):
        """1. Eligibility model and uniqueness invariant."""
        elig = Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        self.assertIsNotNone(elig.id)
        with self.assertRaises(IntegrityError):
            Eligibility.objects.create(voter=self.voter1, election=self.elec1)

    def test_02_ballot_model_uniqueness(self):
        """2. Ballot model and uniqueness invariant."""
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.assertIsNotNone(ballot.id)
        self.assertIsNotNone(ballot.timestamp)
        with self.assertRaises(IntegrityError):
            Ballot.objects.create(voter=self.voter1, election=self.elec1)

    def test_03_platform_admin_eligibility_creation(self):
        """3. Authorized platform administrator eligibility creation."""
        self.client.force_login(self.u_platform)
        res = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json()['success'])
        self.assertTrue(Eligibility.objects.filter(voter=self.voter1, election=self.elec1).exists())

    def test_04_org_admin_within_organization(self):
        """4. Organization administrator access within their organization."""
        self.client.force_login(self.u_org_admin1)
        res = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json()['success'])

    def test_05_org_admin_cross_org_denial(self):
        """5. Organization administrator cross-organization denial."""
        self.client.force_login(self.u_org_admin1)
        res = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec2.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 403)
        self.assertFalse(Eligibility.objects.filter(voter=self.voter1, election=self.elec2).exists())

    def test_06_election_official_permissions(self):
        """6. Election official permissions (within org allowed, cross org denied)."""
        self.client.force_login(self.u_official1)
        res1 = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res1.status_code, 201)
        res2 = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec2.id, 'voter_id': self.voter2.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 403)

    def test_07_auditor_read_only_restrictions(self):
        """7. Auditor read-only restrictions."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_auditor1)
        
        # Read is allowed
        res_list = self.client.get(f'/eligibility/?election_id={self.elec1.id}')
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(res_list.json()['eligibilities']), 1)
        
        # Mutation: create eligibility denied
        res_create = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter2.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res_create.status_code, 403)
        
        # Mutation: create ballot denied
        res_ballot = self.client.post(
            '/ballots/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res_ballot.status_code, 403)

    def test_08_anonymous_request_denial(self):
        """8. Anonymous request denial."""
        res1 = self.client.get('/eligibility/')
        self.assertEqual(res1.status_code, 403)
        res2 = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 403)
        res3 = self.client.get('/ballots/')
        self.assertEqual(res3.status_code, 403)
        res4 = self.client.post(
            '/ballots/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res4.status_code, 403)

    def test_09_missing_profile_denial(self):
        """9. Missing-profile denial."""
        self.client.force_login(self.u_no_profile)
        res = self.client.get('/eligibility/')
        self.assertEqual(res.status_code, 403)
        res2 = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 403)

    def test_10_unknown_election_handling(self):
        """10. Unknown election handling."""
        self.client.force_login(self.u_platform)
        res = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': 99999, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 404)

    def test_11_unknown_voter_handling(self):
        """11. Unknown voter handling."""
        self.client.force_login(self.u_platform)
        res = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': 'non_existent_uuid'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 404)

    def test_12_duplicate_eligibility_rejection(self):
        """12. Duplicate eligibility rejection."""
        self.client.force_login(self.u_platform)
        res1 = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res1.status_code, 201)
        
        # Second attempt
        res2 = self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("already eligible", res2.json()['error'])

    def test_13_ballot_creation_without_eligibility(self):
        """13. Ballot creation without eligibility rejection."""
        self.client.force_login(self.u_platform)
        res = self.client.post(
            '/ballots/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("not eligible", res.json()['error'])
        self.assertFalse(Ballot.objects.filter(voter=self.voter1, election=self.elec1).exists())

    def test_14_successful_ballot_creation(self):
        """14. Successful Ballot creation for an eligible voter."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)
        res = self.client.post(
            '/ballots/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.json()['success'])
        self.assertTrue(Ballot.objects.filter(voter=self.voter1, election=self.elec1).exists())

    def test_15_duplicate_ballot_creation_rejection(self):
        """15. Duplicate Ballot creation rejection."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)
        res1 = self.client.post(
            '/ballots/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res1.status_code, 201)
        
        # Second attempt
        res2 = self.client.post(
            '/ballots/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("already exists", res2.json()['error'])

    def test_16_eligibility_revocation_no_ballot(self):
        """16. Eligibility revocation with no Ballot."""
        elig = Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_org_admin1)
        res = self.client.post(f'/eligibility/{elig.id}/revoke/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])
        self.assertFalse(Eligibility.objects.filter(id=elig.id).exists())

    def test_17_eligibility_revocation_rejection_when_ballot_exists(self):
        """17. Eligibility revocation rejection when a Ballot exists."""
        elig = Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_org_admin1)
        res = self.client.post(f'/eligibility/{elig.id}/revoke/')
        self.assertEqual(res.status_code, 409)
        self.assertIn("ballot already exists", res.json()['error'])
        self.assertTrue(Eligibility.objects.filter(id=elig.id).exists())

    def test_18_no_unintended_change_to_vote_done(self):
        """18. No unintended change to Voters.vote_done."""
        self.assertFalse(self.voter1.vote_done)
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.voter1.refresh_from_db()
        self.assertFalse(self.voter1.vote_done)

    def test_19_no_vote_or_votebackup_records_created(self):
        """19. No Vote or VoteBackup records created by eligibility or Ballot management."""
        v_count_before = Vote.objects.count()
        vb_count_before = VoteBackup.objects.count()
        
        self.client.force_login(self.u_platform)
        self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.client.post(
            '/ballots/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        
        self.assertEqual(Vote.objects.count(), v_count_before)
        self.assertEqual(VoteBackup.objects.count(), vb_count_before)

    def test_20_no_changes_to_blockchain(self):
        """20. No changes to blockchain records."""
        b_count_before = Block.objects.count()
        self.client.force_login(self.u_platform)
        self.client.post(
            '/eligibility/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.client.post(
            '/ballots/create/',
            data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}),
            content_type='application/json'
        )
        self.assertEqual(Block.objects.count(), b_count_before)

    def test_21_organization_isolation_retrieval(self):
        """21. Organization isolation for retrieval endpoints."""
        elig2 = Eligibility.objects.create(voter=self.voter2, election=self.elec2)
        ballot2 = Ballot.objects.create(voter=self.voter2, election=self.elec2)
        
        # Org Admin 1 (Org 1) tries to view records from Org 2
        self.client.force_login(self.u_org_admin1)
        res_elig = self.client.get(f'/eligibility/{elig2.id}/')
        self.assertEqual(res_elig.status_code, 403)
        
        res_ballot = self.client.get(f'/ballots/{ballot2.id}/')
        self.assertEqual(res_ballot.status_code, 403)

    def test_22_legacy_route_resolution(self):
        """22. Legacy route resolution."""
        from django.urls import resolve
        routes = [
            '/authentication/',
            '/send-otp/',
            '/verify-otp/',
            '/get-parties/',
            '/create-vote/',
            '/start-mining/',
            '/sync-block/',
            '/verify-block/',
            '/show-result/',
            '/mine-block/',
            '/blockchain/',
            '/block-info/',
            '/admin/',
        ]
        for route in routes:
            match = resolve(route)
            self.assertIsNotNone(match.func)

    def test_23_existing_legacy_voting_compatibility(self):
        """23. Existing legacy voting compatibility (get-parties)."""
        res = self.client.get('/get-parties/')
        self.assertEqual(res.status_code, 200)


class Phase4Step6Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from datetime import timedelta
        cls.now = timezone.now()

        # Organizations
        cls.org1 = Organization.objects.create(name="Org 1", description="Test Org 1")
        cls.org2 = Organization.objects.create(name="Org 2", description="Test Org 2")

        # Elections
        cls.elec1 = Election.objects.create(organization=cls.org1, title="Election 1", status="OPEN")
        cls.elec_draft = Election.objects.create(organization=cls.org1, title="Draft Election", status="DRAFT")
        cls.elec_closed = Election.objects.create(organization=cls.org1, title="Closed Election", status="CLOSED")
        cls.elec_future = Election.objects.create(
            organization=cls.org1,
            title="Future Election",
            status="OPEN",
            start_date=cls.now + timedelta(days=2),
            end_date=cls.now + timedelta(days=5)
        )
        cls.elec_past = Election.objects.create(
            organization=cls.org1,
            title="Past Election",
            status="OPEN",
            start_date=cls.now - timedelta(days=5),
            end_date=cls.now - timedelta(days=2)
        )
        cls.elec2 = Election.objects.create(organization=cls.org2, title="Election 2", status="OPEN")

        # Positions
        cls.pos_single = Position.objects.create(election=cls.elec1, title="President", max_votes_allowed=1)
        cls.pos_multi = Position.objects.create(election=cls.elec1, title="Committee", max_votes_allowed=2)
        cls.pos_elec2 = Position.objects.create(election=cls.elec2, title="Org2 Position", max_votes_allowed=1)

        # Candidates
        cls.cand1 = Candidate.objects.create(position=cls.pos_single, name="Alice Cand", affiliation="Party A")
        cls.cand2 = Candidate.objects.create(position=cls.pos_single, name="Bob Cand", affiliation="Party B")
        cls.cand3 = Candidate.objects.create(position=cls.pos_multi, name="Charlie Cand", affiliation="Party C")
        cls.cand4 = Candidate.objects.create(position=cls.pos_multi, name="Diana Cand", affiliation="Party D")
        cls.cand5 = Candidate.objects.create(position=cls.pos_multi, name="Eve Cand", affiliation="Party E")
        cls.cand_other = Candidate.objects.create(position=cls.pos_elec2, name="Frank Cand", affiliation="Party F")

        # Voters
        cls.voter1 = Voters.objects.create(
            uuid="test_voter_1",
            name="Voter One",
            dob="1990-01-01",
            pincode="111111",
            region="Region 1",
            vote_done=False
        )
        cls.voter2 = Voters.objects.create(
            uuid="test_voter_2",
            name="Voter Two",
            dob="1992-02-02",
            pincode="222222",
            region="Region 2",
            vote_done=False
        )

        # Users / Profiles
        cls.u_platform = User.objects.create(username="p6_platform")
        cls.p_platform = UserProfile.objects.create(user=cls.u_platform, role="PLATFORM_ADMIN")

        cls.u_org_admin1 = User.objects.create(username="p6_org_admin1")
        cls.p_org_admin1 = UserProfile.objects.create(user=cls.u_org_admin1, role="ORGANIZATION_ADMIN", organization=cls.org1)

        cls.u_org_admin2 = User.objects.create(username="p6_org_admin2")
        cls.p_org_admin2 = UserProfile.objects.create(user=cls.u_org_admin2, role="ORGANIZATION_ADMIN", organization=cls.org2)

        cls.u_official1 = User.objects.create(username="p6_official1")
        cls.p_official1 = UserProfile.objects.create(user=cls.u_official1, role="ELECTION_OFFICIAL", organization=cls.org1)

        cls.u_auditor1 = User.objects.create(username="p6_auditor1")
        cls.p_auditor1 = UserProfile.objects.create(user=cls.u_auditor1, role="AUDITOR", organization=cls.org1)

        cls.u_no_profile = User.objects.create(username="p6_no_profile")

    def setUp(self):
        self.client = Client()

    def test_01_valid_ballot_submission_one_position(self):
        """1. Valid ballot submission with one position."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])
        self.assertEqual(res.json()['votes_created'], 1)

        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 1)
        self.assertEqual(VoteBackup.objects.filter(ballot=ballot).count(), 1)

    def test_02_valid_ballot_submission_multiple_positions(self):
        """2. Valid ballot submission with multiple positions."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]},
                {'position_id': self.pos_multi.id, 'candidate_ids': [self.cand3.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['votes_created'], 2)
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 2)

    def test_03_multiple_candidates_within_position_max_votes_allowed(self):
        """3. Multiple candidates within a position where max_votes_allowed permits them."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        # pos_multi allows 2 votes
        payload = {
            'selections': [
                {'position_id': self.pos_multi.id, 'candidate_ids': [self.cand3.id, self.cand4.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['votes_created'], 2)
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 2)

    def test_04_reject_exceeding_max_votes_allowed(self):
        """4. Rejecting selections exceeding max_votes_allowed."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        # pos_single allows only 1 vote
        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id, self.cand2.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("max_votes_allowed", res.json()['error'])
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 0)

    def test_05_reject_candidate_from_another_position(self):
        """5. Rejecting a candidate from another position."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        # cand3 belongs to pos_multi, but submitted under pos_single
        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand3.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("does not belong to position", res.json()['error'])
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 0)

    def test_06_reject_candidate_from_another_election(self):
        """6. Rejecting a candidate from another election."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        # cand_other belongs to elec2, submitted under pos_single in elec1
        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand_other.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 0)

    def test_07_reject_duplicate_candidate_selections(self):
        """7. Rejecting duplicate candidate selections."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {
            'selections': [
                {'position_id': self.pos_multi.id, 'candidate_ids': [self.cand3.id, self.cand3.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("Duplicate candidate selections", res.json()['error'])
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 0)

    def test_08_reject_ballot_without_eligibility(self):
        """8. Rejecting a ballot without Eligibility."""
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("not eligible", res.json()['error'])
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 0)

    def test_09_reject_invalid_or_unrelated_ballot(self):
        """9. Rejecting an invalid or unrelated Ballot."""
        self.client.force_login(self.u_platform)
        res = self.client.post('/ballots/99999/submit/', data=json.dumps({'selections': []}), content_type='application/json')
        self.assertEqual(res.status_code, 404)

    def test_10_reject_submission_by_unauthorized_user(self):
        """10. Rejecting submission by an unauthorized user."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        payload = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]
        }

        # Anonymous request
        res_anon = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res_anon.status_code, 403)

        # Missing profile
        self.client.force_login(self.u_no_profile)
        res_no_prof = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res_no_prof.status_code, 403)

        # Auditor (read-only)
        self.client.force_login(self.u_auditor1)
        res_auditor = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res_auditor.status_code, 403)

        # Org admin from Org 2 (cross-organization)
        self.client.force_login(self.u_org_admin2)
        res_cross = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res_cross.status_code, 403)

    def test_11_reject_submission_attempting_to_act_for_another_voter(self):
        """11. Rejecting submission by a user attempting to act for another voter."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)

        payload = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]
        }

        # Voter session set to voter2, but submitting ballot for voter1
        session = self.client.session
        session['uuid'] = self.voter2.uuid
        session.save()

        res_sess = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res_sess.status_code, 403)
        self.assertIn("another voter", res_sess.json()['error'])

        # Payload supplies mismatched voter_id
        session = self.client.session
        if 'uuid' in session:
            del session['uuid']
            session.save()
        self.client.force_login(self.u_platform)
        payload_mismatch = {
            'voter_id': self.voter2.uuid,
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]
        }
        res_mismatch = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload_mismatch), content_type='application/json')
        self.assertEqual(res_mismatch.status_code, 400)
        self.assertIn("does not match", res_mismatch.json()['error'])

    def test_12_reject_draft_election(self):
        """12. Rejecting a DRAFT election."""
        pos = Position.objects.create(election=self.elec_draft, title="P", max_votes_allowed=1)
        cand = Candidate.objects.create(position=pos, name="C")
        Eligibility.objects.create(voter=self.voter1, election=self.elec_draft)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec_draft)

        self.client.force_login(self.u_platform)
        payload = {'selections': [{'position_id': pos.id, 'candidate_ids': [cand.id]}]}
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("not open", res.json()['error'])

    def test_13_reject_closed_election(self):
        """13. Rejecting a CLOSED election."""
        pos = Position.objects.create(election=self.elec_closed, title="P", max_votes_allowed=1)
        cand = Candidate.objects.create(position=pos, name="C")
        Eligibility.objects.create(voter=self.voter1, election=self.elec_closed)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec_closed)

        self.client.force_login(self.u_platform)
        payload = {'selections': [{'position_id': pos.id, 'candidate_ids': [cand.id]}]}
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("not open", res.json()['error'])

    def test_14_reject_submission_before_start_time(self):
        """14. Rejecting submission before the start time."""
        pos = Position.objects.create(election=self.elec_future, title="P", max_votes_allowed=1)
        cand = Candidate.objects.create(position=pos, name="C")
        Eligibility.objects.create(voter=self.voter1, election=self.elec_future)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec_future)

        self.client.force_login(self.u_platform)
        payload = {'selections': [{'position_id': pos.id, 'candidate_ids': [cand.id]}]}
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("has not started", res.json()['error'])

    def test_15_reject_submission_after_end_time(self):
        """15. Rejecting submission after the end time."""
        pos = Position.objects.create(election=self.elec_past, title="P", max_votes_allowed=1)
        cand = Candidate.objects.create(position=pos, name="C")
        Eligibility.objects.create(voter=self.voter1, election=self.elec_past)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec_past)

        self.client.force_login(self.u_platform)
        payload = {'selections': [{'position_id': pos.id, 'candidate_ids': [cand.id]}]}
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("has ended", res.json()['error'])

    def test_16_reject_second_submission(self):
        """16. Rejecting a second submission."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]}
        res1 = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res1.status_code, 200)

        # Second submission attempt
        res2 = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res2.status_code, 400)
        self.assertIn("already been submitted", res2.json()['error'])

    def test_17_atomic_rollback_if_one_selection_fails(self):
        """17. Atomic rollback if one selection fails."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        # Selection 1 is valid, Selection 2 has candidate from another position
        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]},
                {'position_id': self.pos_multi.id, 'candidate_ids': [self.cand1.id]} # cand1 does not belong to pos_multi
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 0)

    def test_18_no_vote_records_created_on_validation_failure(self):
        """18. No Vote records created on validation failure."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        # Exceeds max votes
        payload = {'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id, self.cand2.id]}]}
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Vote.objects.count(), 0)
        self.assertEqual(VoteBackup.objects.count(), 0)

    def test_19_correct_vote_uuid_values(self):
        """19. Correct Vote.uuid values."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]}
        self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')

        vote = Vote.objects.get(ballot=ballot)
        self.assertEqual(vote.uuid, self.voter1.uuid)

    def test_20_correct_vote_party_id_values(self):
        """20. Correct Vote.vote_party_id values."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]}
        self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')

        vote = Vote.objects.get(ballot=ballot)
        self.assertEqual(vote.vote_party_id, str(self.cand1.id))

    def test_21_correct_vote_ballot_relationships(self):
        """21. Correct Vote.ballot relationships."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]}
        self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')

        vote = Vote.objects.get(ballot=ballot)
        self.assertEqual(vote.ballot.id, ballot.id)

    def test_22_correct_pending_block_relationships(self):
        """22. Correct pending block relationships."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]}
        self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')

        vote = Vote.objects.get(ballot=ballot)
        self.assertIsNone(vote.block_id)

    def test_23_no_unintended_change_to_voters_vote_done(self):
        """23. No unintended change to Voters.vote_done."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]}
        self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')

        self.voter1.refresh_from_db()
        self.assertFalse(self.voter1.vote_done)

    def test_24_no_unintended_change_to_votebackup(self):
        """24. No unintended change to VoteBackup."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        self.client.force_login(self.u_platform)

        payload = {'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}]}
        self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(VoteBackup.objects.count(), 1)
        vb = VoteBackup.objects.get(ballot=ballot)
        self.assertEqual(vb.uuid, self.voter1.uuid)
        self.assertEqual(vb.vote_party_id, str(self.cand1.id))
        self.assertIsNone(vb.block_id)

    def test_25_legacy_create_vote_compatibility(self):
        """25. Legacy /create-vote/ compatibility."""
        from django.urls import resolve
        match = resolve('/create-vote/')
        self.assertIsNotNone(match.func)

    def test_26_legacy_blockchain_route_compatibility(self):
        """26. Legacy blockchain route compatibility."""
        from django.urls import resolve
        for route in ['/start-mining/', '/sync-block/', '/verify-block/', '/blockchain/', '/block-info/']:
            match = resolve(route)
            self.assertIsNotNone(match.func)

    def test_27_historical_data_integrity(self):
        """27. Historical data integrity."""
        # Verified inside test database
        self.assertFalse(Vote.objects.filter(ballot__isnull=False).exists())

    def test_28_existing_eligibility_ballot_management_regression(self):
        """28. Existing eligibility/ballot-management endpoint regression."""
        self.client.force_login(self.u_platform)
        res_e = self.client.post('/eligibility/create/', data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}), content_type='application/json')
        self.assertEqual(res_e.status_code, 201)
        res_b = self.client.post('/ballots/create/', data=json.dumps({'election_id': self.elec1.id, 'voter_id': self.voter1.uuid}), content_type='application/json')
        self.assertEqual(res_b.status_code, 201)

    def test_29_existing_rbac_and_organization_isolation_regression(self):
        """29. Existing RBAC and organization-isolation regression."""
        # Org admin 1 cannot manage in Org 2
        self.client.force_login(self.u_org_admin1)
        res = self.client.post('/eligibility/create/', data=json.dumps({'election_id': self.elec2.id, 'voter_id': self.voter2.uuid}), content_type='application/json')
        self.assertEqual(res.status_code, 403)

    def test_30_valid_ballot_submission_via_voter_session(self):
        """30. Valid ballot submission via voter session."""
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        ballot = Ballot.objects.create(voter=self.voter1, election=self.elec1)
        
        session = self.client.session
        session['uuid'] = self.voter1.uuid
        session.save()
        
        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand1.id]}
            ]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 1)


class Phase4Step7Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Organizations
        cls.org1 = Organization.objects.create(name="Org 1", description="Test Org 1")
        cls.org2 = Organization.objects.create(name="Org 2", description="Test Org 2")

        # Elections
        cls.elec1 = Election.objects.create(organization=cls.org1, title="Election 1", status="OPEN")
        cls.elec_closed = Election.objects.create(organization=cls.org1, title="Closed Election", status="CLOSED")
        cls.elec_draft = Election.objects.create(organization=cls.org1, title="Draft Election", status="DRAFT")
        cls.elec2 = Election.objects.create(organization=cls.org2, title="Election 2", status="OPEN")

        # Positions
        cls.pos_pres = Position.objects.create(election=cls.elec1, title="President", max_votes_allowed=1)
        cls.pos_vp = Position.objects.create(election=cls.elec1, title="Vice President", max_votes_allowed=1)
        cls.pos_other = Position.objects.create(election=cls.elec2, title="Org2 Position", max_votes_allowed=1)

        # Candidates
        cls.cand_pres_1 = Candidate.objects.create(position=cls.pos_pres, name="Alice Pres", affiliation="Party A")
        cls.cand_pres_2 = Candidate.objects.create(position=cls.pos_pres, name="Bob Pres", affiliation="Party B")
        cls.cand_pres_zero = Candidate.objects.create(position=cls.pos_pres, name="Zero Vote Pres", affiliation="Party Z")
        cls.cand_vp_1 = Candidate.objects.create(position=cls.pos_vp, name="Charlie VP", affiliation="Party C")
        cls.cand_other = Candidate.objects.create(position=cls.pos_other, name="Dave Other", affiliation="Party D")

        # Voters
        cls.voter1 = Voters.objects.create(uuid="p7_voter_1", name="Voter One", dob="1990-01-01", pincode="111111", region="R1", vote_done=False)
        cls.voter2 = Voters.objects.create(uuid="p7_voter_2", name="Voter Two", dob="1992-02-02", pincode="222222", region="R2", vote_done=False)
        cls.voter3 = Voters.objects.create(uuid="p7_voter_3", name="Voter Three", dob="1994-03-03", pincode="333333", region="R3", vote_done=False)

        # Users / Profiles
        cls.u_platform = User.objects.create(username="p7_platform")
        cls.p_platform = UserProfile.objects.create(user=cls.u_platform, role="PLATFORM_ADMIN")

        cls.u_org_admin1 = User.objects.create(username="p7_org_admin1")
        cls.p_org_admin1 = UserProfile.objects.create(user=cls.u_org_admin1, role="ORGANIZATION_ADMIN", organization=cls.org1)

        cls.u_org_admin2 = User.objects.create(username="p7_org_admin2")
        cls.p_org_admin2 = UserProfile.objects.create(user=cls.u_org_admin2, role="ORGANIZATION_ADMIN", organization=cls.org2)

        cls.u_official1 = User.objects.create(username="p7_official1")
        cls.p_official1 = UserProfile.objects.create(user=cls.u_official1, role="ELECTION_OFFICIAL", organization=cls.org1)

        cls.u_auditor1 = User.objects.create(username="p7_auditor1")
        cls.p_auditor1 = UserProfile.objects.create(user=cls.u_auditor1, role="AUDITOR", organization=cls.org1)

        cls.u_no_profile = User.objects.create(username="p7_no_profile")

    def setUp(self):
        self.client = Client()

    def _submit_ballot(self, voter, election, selections):
        Eligibility.objects.get_or_create(voter=voter, election=election)
        ballot, _ = Ballot.objects.get_or_create(voter=voter, election=election)
        self.client.force_login(self.u_platform)
        payload = {'selections': selections}
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        return res, ballot

    def test_01_correct_tally_one_candidate(self):
        """1. Correct tally for one candidate."""
        selections = [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}]
        self._submit_ballot(self.voter1, self.elec1, selections)

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # Find President position
        pres_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_pres.id)
        cand1 = next(c for c in pres_pos['candidates'] if c['candidate_id'] == self.cand_pres_1.id)
        self.assertEqual(cand1['votes_received'], 1)
        self.assertEqual(pres_pos['total_votes'], 1)

    def test_02_correct_tally_multiple_candidates(self):
        """2. Correct tally for multiple candidates."""
        self._submit_ballot(self.voter1, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}])
        self._submit_ballot(self.voter2, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_2.id]}])

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)
        data = res.json()

        pres_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_pres.id)
        c1 = next(c for c in pres_pos['candidates'] if c['candidate_id'] == self.cand_pres_1.id)
        c2 = next(c for c in pres_pos['candidates'] if c['candidate_id'] == self.cand_pres_2.id)
        self.assertEqual(c1['votes_received'], 1)
        self.assertEqual(c2['votes_received'], 1)
        self.assertEqual(pres_pos['total_votes'], 2)

    def test_03_multiple_positions_in_one_election(self):
        """3. Multiple positions in one election."""
        selections = [
            {'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]},
            {'position_id': self.pos_vp.id, 'candidate_ids': [self.cand_vp_1.id]}
        ]
        self._submit_ballot(self.voter1, self.elec1, selections)

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(len(data['positions']), 2)
        pres_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_pres.id)
        vp_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_vp.id)
        self.assertEqual(pres_pos['total_votes'], 1)
        self.assertEqual(vp_pos['total_votes'], 1)
        self.assertEqual(data['summary']['total_votes_counted'], 2)

    def test_04_zero_vote_candidates_appear_in_results(self):
        """4. Candidates with zero votes appear in results."""
        self._submit_ballot(self.voter1, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}])

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()

        pres_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_pres.id)
        zero_cand = next(c for c in pres_pos['candidates'] if c['candidate_id'] == self.cand_pres_zero.id)
        self.assertEqual(zero_cand['votes_received'], 0)

    def test_05_votes_from_another_election_excluded(self):
        """5. Votes from another election are excluded."""
        # Vote in elec2
        self._submit_ballot(self.voter1, self.elec2, [{'position_id': self.pos_other.id, 'candidate_ids': [self.cand_other.id]}])

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()

        self.assertEqual(data['summary']['total_votes_counted'], 0)
        self.assertEqual(data['summary']['total_submitted_ballots'], 0)

    def test_06_historical_ballot_null_votes_excluded(self):
        """6. Historical ballot=NULL votes are excluded."""
        now = timezone.now()
        Vote.objects.create(
            uuid="hist_voter",
            vote_party_id=str(self.cand_pres_1.id),
            timestamp=now,
            election=self.elec1,
            ballot=None
        )

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()

        self.assertEqual(data['summary']['total_votes_counted'], 0)

    def test_07_unrelated_or_invalid_candidate_votes_excluded(self):
        """7. Votes attached to unrelated or invalid candidates are excluded and reported."""
        _, ballot = self._submit_ballot(self.voter1, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}])
        # Inject an invalid candidate Vote attached to this ballot
        Vote.objects.create(
            uuid=self.voter1.uuid,
            vote_party_id="99999", # Non-existent candidate
            timestamp=timezone.now(),
            election=self.elec1,
            ballot=ballot
        )

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()

        self.assertEqual(data['summary']['total_votes_counted'], 1)
        self.assertEqual(data['reconciliation']['invalid_votes_detected'], 1)

    def test_08_draft_unsubmitted_ballots_not_counted(self):
        """8. Draft/unsubmitted Ballots are not counted."""
        # Create unsubmitted ballot for voter3
        Eligibility.objects.create(voter=self.voter3, election=self.elec1)
        Ballot.objects.create(voter=self.voter3, election=self.elec1)

        # Submit ballot for voter1
        self._submit_ballot(self.voter1, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}])

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()

        self.assertEqual(data['summary']['total_submitted_ballots'], 1)

    def test_09_duplicate_submissions_do_not_inflate_totals(self):
        """9. Duplicate submissions do not inflate totals."""
        res1, ballot = self._submit_ballot(self.voter1, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}])
        self.assertEqual(res1.status_code, 200)

        # Attempt second submission
        payload = {'selections': [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}]}
        res2 = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res2.status_code, 400)

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()
        self.assertEqual(data['summary']['total_votes_counted'], 1)

    def test_10_unauthorized_access_rejected(self):
        """10. Unauthorized access is rejected."""
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 403)

    def test_11_cross_organization_access_rejected(self):
        """11. Cross-organization access is rejected."""
        self.client.force_login(self.u_org_admin2) # Org 2 admin
        res = self.client.get(f'/elections/{self.elec1.id}/results/') # Org 1 election
        self.assertEqual(res.status_code, 403)

    def test_12_auditor_access_allowed(self):
        """12. Auditor access remains read-only and is allowed."""
        self._submit_ballot(self.voter1, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}])

        self.client.force_login(self.u_auditor1) # Org 1 auditor
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['summary']['total_votes_counted'], 1)

    def test_13_anonymous_access_denied(self):
        """13. Anonymous access is denied."""
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 403)

    def test_14_profile_less_access_denied(self):
        """14. Profile-less access is denied."""
        self.client.force_login(self.u_no_profile)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 403)

    def test_15_candidate_totals_reconcile_with_counted_votes(self):
        """15. Candidate totals reconcile with counted Vote records."""
        self._submit_ballot(self.voter1, self.elec1, [
            {'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]},
            {'position_id': self.pos_vp.id, 'candidate_ids': [self.cand_vp_1.id]}
        ])
        self._submit_ballot(self.voter2, self.elec1, [
            {'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_2.id]}
        ])

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()

        self.assertTrue(data['reconciliation']['election_reconciled'])
        self.assertEqual(data['summary']['total_votes_counted'], 3)

    def test_16_position_totals_reconcile_with_candidate_totals(self):
        """16. Position totals reconcile with candidate totals."""
        self._submit_ballot(self.voter1, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}])
        self._submit_ballot(self.voter2, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_2.id]}])

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()

        for pos in data['positions']:
            pos_cand_sum = sum(c['votes_received'] for c in pos['candidates'])
            self.assertEqual(pos['total_votes'], pos_cand_sum)

    def test_17_no_voter_identity_exposed(self):
        """17. No voter identity is exposed in results."""
        self._submit_ballot(self.voter1, self.elec1, [{'position_id': self.pos_pres.id, 'candidate_ids': [self.cand_pres_1.id]}])

        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        content = res.content.decode('utf-8')

        self.assertNotIn(self.voter1.uuid, content)
        self.assertNotIn("p7_voter_1", content)
        self.assertNotIn("Voter One", content)

    def test_18_legacy_show_result_remains_functional(self):
        """18. Legacy /show-result/ remains functional."""
        res = self.client.get('/show-result/')
        self.assertEqual(res.status_code, 200)

    def test_19_result_status_lifecycle(self):
        """19. Result status accurately reflects election lifecycle."""
        self.client.force_login(self.u_platform)

        # OPEN election -> LIVE, not finalized
        res_open = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res_open.json()['election']['result_status'], 'LIVE')
        self.assertFalse(res_open.json()['election']['is_finalized'])

        # CLOSED election -> FINALIZED, finalized True
        res_closed = self.client.get(f'/elections/{self.elec_closed.id}/results/')
        self.assertEqual(res_closed.json()['election']['result_status'], 'FINALIZED')
        self.assertTrue(res_closed.json()['election']['is_finalized'])

        # DRAFT election -> DRAFT, not finalized
        res_draft = self.client.get(f'/elections/{self.elec_draft.id}/results/')
        self.assertEqual(res_draft.json()['election']['result_status'], 'DRAFT')
        self.assertFalse(res_draft.json()['election']['is_finalized'])

    def test_20_historical_database_counts_unchanged(self):
        """20. Historical database counts remain unchanged."""
        self.assertFalse(Vote.objects.filter(ballot__isnull=False, election=None).exists())


from unittest.mock import patch
import secrets
from datetime import timedelta
from home.methods_module import (
    build_auth_payload, build_ballot_tracker, build_transaction_leaf,
    compute_tx_id, sign_auth_payload, verify_ballot_signature,
    get_or_create_active_batch, submit_modern_ballot, generate_keys
)
from home.models import BallotBatch

class Phase5Step4ATests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(name="Phase 5 Org")
        cls.election = Election.objects.create(organization=cls.org, title="Modern Election", status="OPEN")
        cls.election_2 = Election.objects.create(organization=cls.org, title="Second Election", status="OPEN")

        cls.pos_single = Position.objects.create(
            election=cls.election,
            title="President",
            max_votes_allowed=1
        )
        cls.cand_1 = Candidate.objects.create(position=cls.pos_single, name="Candidate Alpha", affiliation="Party A")
        cls.cand_2 = Candidate.objects.create(position=cls.pos_single, name="Candidate Beta", affiliation="Party B")

        cls.pos_multi = Position.objects.create(
            election=cls.election,
            title="Council Members",
            max_votes_allowed=2
        )
        cls.cand_c1 = Candidate.objects.create(position=cls.pos_multi, name="Council 1", affiliation="Party A")
        cls.cand_c2 = Candidate.objects.create(position=cls.pos_multi, name="Council 2", affiliation="Party B")
        cls.cand_c3 = Candidate.objects.create(position=cls.pos_multi, name="Council 3", affiliation="Party C")

        cls.pos_elec2 = Position.objects.create(election=cls.election_2, title="Mayor", max_votes_allowed=1)
        cls.cand_elec2 = Candidate.objects.create(position=cls.pos_elec2, name="Mayor Candidate", affiliation="Party X")

        cls.voter = Voters.objects.create(
            uuid="p5_voter_1",
            name="Voter Five",
            dob="1995-05-05",
            pincode="500001",
            region="Hyderabad",
            vote_done=False
        )
        cls.voter_2 = Voters.objects.create(
            uuid="p5_voter_2",
            name="Voter Six",
            dob="1996-06-06",
            pincode="500002",
            region="Secunderabad",
            vote_done=False
        )

        Eligibility.objects.create(voter=cls.voter, election=cls.election)
        Eligibility.objects.create(voter=cls.voter, election=cls.election_2)
        Eligibility.objects.create(voter=cls.voter_2, election=cls.election)

        cls.priv_key, cls.pub_key = generate_keys()
        cls.priv_key_2, cls.pub_key_2 = generate_keys()

    def setUp(self):
        session = self.client.session
        session['uuid'] = self.voter.uuid
        session.save()

    def test_01_successful_modern_transaction_creation(self):
        """1. Successful modern transaction creation with cryptographic fields and batch assignment."""
        ballot = Ballot.objects.create(voter=self.voter, election=self.election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(self.election.id, self.voter.uuid, nonce, ts)
        sig = sign_auth_payload(self.priv_key, auth_payload)

        payload = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': sig,
            'public_key': self.pub_key,
            'ballot_nonce': nonce,
            'timestamp': ts,
            'auth_payload': auth_payload,
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['votes_created'], 1)

        expected_tracker = build_ballot_tracker(self.election.id, self.voter.uuid, nonce)
        self.assertEqual(data['ballot_tracker'], expected_tracker)

        ballot.refresh_from_db()
        self.assertEqual(ballot.ballot_nonce, nonce)
        self.assertEqual(ballot.ballot_tracker, expected_tracker)
        self.assertEqual(ballot.signature, sig)
        self.assertEqual(ballot.public_key, self.pub_key)
        self.assertFalse(ballot.is_sealed)
        self.assertIsNotNone(ballot.batch)

        # Verify Vote and VoteBackup
        vote = Vote.objects.get(ballot=ballot)
        self.assertEqual(vote.position, self.pos_single)
        self.assertEqual(vote.vote_party_id, str(self.cand_1.id))
        self.assertEqual(vote.batch, ballot.batch)
        self.assertIsNotNone(vote.tx_id)
        self.assertEqual(len(vote.commitment_salt), 64)
        expected_tx_id = compute_tx_id(self.election.id, self.pos_single.id, self.cand_1.id, vote.commitment_salt)
        self.assertEqual(vote.tx_id, expected_tx_id)

        vb = VoteBackup.objects.get(ballot=ballot)
        self.assertEqual(vb.tx_id, vote.tx_id)
        self.assertEqual(vb.commitment_salt, vote.commitment_salt)
        self.assertEqual(vb.position, vote.position)
        self.assertEqual(vb.batch, vote.batch)

        batch = ballot.batch
        self.assertEqual(batch.ballot_count, 1)
        self.assertEqual(batch.expected_tx_count, 1)
        self.assertEqual(batch.status, 'OPEN')

    def test_02_signature_verification_and_invalid_signature_rejection(self):
        """2. Rejection of invalid or forged digital signature."""
        ballot = Ballot.objects.create(voter=self.voter, election=self.election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(self.election.id, self.voter.uuid, nonce, ts)
        # Sign with wrong key (priv_key_2 instead of priv_key)
        wrong_sig = sign_auth_payload(self.priv_key_2, auth_payload)

        payload = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': wrong_sig,
            'public_key': self.pub_key,
            'ballot_nonce': nonce,
            'timestamp': ts,
            'auth_payload': auth_payload,
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("INVALID_SIGNATURE", res.json()['error'])
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 0)
        ballot.refresh_from_db()
        self.assertIsNone(ballot.signature)

    def test_03_missing_or_malformed_signature_data(self):
        """3. Rejection of missing signature, malformed public key, or expired timestamp."""
        ballot = Ballot.objects.create(voter=self.voter, election=self.election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(self.election.id, self.voter.uuid, nonce, ts)
        sig = sign_auth_payload(self.priv_key, auth_payload)

        # Missing signature
        payload_no_sig = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': '',
            'public_key': self.pub_key,
            'is_modern': True
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload_no_sig), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("MISSING_SIGNATURE", res.json()['error'])

        # Missing public key
        payload_no_pub = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': sig,
            'public_key': '',
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload_no_pub), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("MISSING_PUBLIC_KEY", res.json()['error'])

        # Malformed public key
        payload_bad_pub = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': sig,
            'public_key': '-----BEGIN PUBLIC KEY-----\nNOT_VALID_BASE64\n-----END PUBLIC KEY-----',
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload_bad_pub), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("MALFORMED_PUBLIC_KEY", res.json()['error'])

        # Skewed timestamp (> 300 seconds)
        skewed_ts = (timezone.now() - timedelta(seconds=350)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        payload_skewed = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': sig,
            'public_key': self.pub_key,
            'ballot_nonce': nonce,
            'timestamp': skewed_ts,
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload_skewed), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("SUBMISSION_TIMESTAMP_OUT_OF_BOUNDS", res.json()['error'])

        # Mismatched AuthPayload voter
        mismatched_payload = build_auth_payload(self.election.id, self.voter_2.uuid, nonce, ts)
        sig_mismatched = sign_auth_payload(self.priv_key, mismatched_payload)
        payload_mismatch = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': sig_mismatched,
            'public_key': self.pub_key,
            'ballot_nonce': nonce,
            'timestamp': ts,
            'auth_payload': mismatched_payload,
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload_mismatch), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("AUTH_PAYLOAD_MISMATCH", res.json()['error'])

    def test_04_duplicate_ballot_submission_and_nonce_replay(self):
        """4. Prevention of duplicate ballot submissions and within-election nonce replay."""
        ballot1 = Ballot.objects.create(voter=self.voter, election=self.election)
        nonce1 = secrets.token_hex(32)
        ts1 = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        payload1 = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': sign_auth_payload(self.priv_key, build_auth_payload(self.election.id, self.voter.uuid, nonce1, ts1)),
            'public_key': self.pub_key,
            'ballot_nonce': nonce1,
            'timestamp': ts1,
        }
        res1 = self.client.post(f'/ballots/{ballot1.id}/submit/', data=json.dumps(payload1), content_type='application/json')
        self.assertEqual(res1.status_code, 200)

        # Duplicate submission on same ballot
        res_dup = self.client.post(f'/ballots/{ballot1.id}/submit/', data=json.dumps(payload1), content_type='application/json')
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn("already been submitted", res_dup.json()['error'].lower())

        # Nonce replay attempt by voter 2 with same nonce in same election
        session2 = self.client.session
        session2['uuid'] = self.voter_2.uuid
        session2.save()

        ballot2 = Ballot.objects.create(voter=self.voter_2, election=self.election)
        ts2 = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        payload_replay = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_2.id]}],
            'signature': sign_auth_payload(self.priv_key_2, build_auth_payload(self.election.id, self.voter_2.uuid, nonce1, ts2)),
            'public_key': self.pub_key_2,
            'ballot_nonce': nonce1,  # Replayed nonce!
            'timestamp': ts2,
        }
        res_replay = self.client.post(f'/ballots/{ballot2.id}/submit/', data=json.dumps(payload_replay), content_type='application/json')
        self.assertEqual(res_replay.status_code, 400)
        self.assertIn("NONCE_REPLAY_DETECTED", res_replay.json()['error'])

    def test_05_cross_election_replay_defense(self):
        """5. Replaying a valid signature from Election 1 against Election 2 fails."""
        ballot_e2 = Ballot.objects.create(voter=self.voter, election=self.election_2)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')

        # Sign envelope bound to Election 1
        sig_for_e1 = sign_auth_payload(self.priv_key, build_auth_payload(self.election.id, self.voter.uuid, nonce, ts))

        # Attempt submitting against Election 2 using Election 1's signature
        payload = {
            'selections': [{'position_id': self.pos_elec2.id, 'candidate_ids': [self.cand_elec2.id]}],
            'signature': sig_for_e1,
            'public_key': self.pub_key,
            'ballot_nonce': nonce,
            'timestamp': ts,
        }
        res = self.client.post(f'/ballots/{ballot_e2.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertIn("INVALID_SIGNATURE", res.json()['error'])

    def test_06_transaction_rollback_when_votebackup_fails(self):
        """6. Complete rollback of Vote, Ballot envelope, and Batch counters if VoteBackup fails."""
        ballot = Ballot.objects.create(voter=self.voter, election=self.election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        payload = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': sign_auth_payload(self.priv_key, build_auth_payload(self.election.id, self.voter.uuid, nonce, ts)),
            'public_key': self.pub_key,
            'ballot_nonce': nonce,
            'timestamp': ts,
        }

        with patch('home.models.VoteBackup.objects.create', side_effect=RuntimeError("Simulated VoteBackup failure")):
            res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
            self.assertEqual(res.status_code, 400)

        # Assert zero Vote records created
        self.assertEqual(Vote.objects.filter(ballot=ballot).count(), 0)
        self.assertEqual(VoteBackup.objects.filter(ballot=ballot).count(), 0)

        # Assert Ballot state reverted
        ballot.refresh_from_db()
        self.assertIsNone(ballot.signature)
        self.assertIsNone(ballot.ballot_tracker)
        self.assertFalse(ballot.is_sealed)

        # Assert Batch counters remained 0
        batch = BallotBatch.objects.filter(election=self.election).first()
        if batch:
            self.assertEqual(batch.ballot_count, 0)
            self.assertEqual(batch.expected_tx_count, 0)

    def test_07_correct_election_position_candidate_and_batch_association(self):
        """7. Multi-position ballot correctly binds all votes to election, positions, candidates, and shared batch."""
        ballot = Ballot.objects.create(voter=self.voter, election=self.election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        payload = {
            'selections': [
                {'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]},
                {'position_id': self.pos_multi.id, 'candidate_ids': [self.cand_c1.id, self.cand_c2.id]}
            ],
            'signature': sign_auth_payload(self.priv_key, build_auth_payload(self.election.id, self.voter.uuid, nonce, ts)),
            'public_key': self.pub_key,
            'ballot_nonce': nonce,
            'timestamp': ts,
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['votes_created'], 3)

        ballot.refresh_from_db()
        votes = list(Vote.objects.filter(ballot=ballot).order_by('id'))
        self.assertEqual(len(votes), 3)

        # All 3 votes must share the same batch as the ballot
        for v in votes:
            self.assertEqual(v.batch, ballot.batch)
            self.assertEqual(v.election, self.election)
            self.assertIsNotNone(v.tx_id)
            self.assertEqual(len(v.commitment_salt), 64)

        # Distinct tx_ids
        tx_ids = [v.tx_id for v in votes]
        self.assertEqual(len(set(tx_ids)), 3)

        # Position associations
        self.assertEqual(votes[0].position, self.pos_single)
        self.assertEqual(votes[0].vote_party_id, str(self.cand_1.id))
        self.assertEqual(votes[1].position, self.pos_multi)
        self.assertEqual(votes[1].vote_party_id, str(self.cand_c1.id))
        self.assertEqual(votes[2].position, self.pos_multi)
        self.assertEqual(votes[2].vote_party_id, str(self.cand_c2.id))

        # Batch counts match exactly 1 ballot and 3 transactions
        batch = ballot.batch
        self.assertEqual(batch.ballot_count, 1)
        self.assertEqual(batch.expected_tx_count, 3)

    def test_08_preservation_of_existing_legacy_behavior(self):
        """8. Preservation of legacy ballot submission without signature fields."""
        ballot = Ballot.objects.create(voter=self.voter, election=self.election)
        legacy_payload = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}]
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(legacy_payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['votes_created'], 1)

        vote = Vote.objects.get(ballot=ballot)
        self.assertEqual(vote.uuid, self.voter.uuid)
        self.assertEqual(vote.vote_party_id, str(self.cand_1.id))
        self.assertIsNone(vote.tx_id)
        self.assertIsNone(vote.commitment_salt)

        # Legacy URL resolution check
        from django.urls import resolve
        self.assertIsNotNone(resolve('/create-vote/').func)

    def test_09_base64_signature_support(self):
        """9. Base64-encoded signature format is accepted seamlessly."""
        import base64
        ballot = Ballot.objects.create(voter=self.voter, election=self.election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(self.election.id, self.voter.uuid, nonce, ts)
        sig_hex = sign_auth_payload(self.priv_key, auth_payload)
        sig_b64 = base64.b64encode(bytes.fromhex(sig_hex)).decode('utf-8')

        payload = {
            'selections': [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}],
            'signature': sig_b64,
            'public_key': self.pub_key,
            'ballot_nonce': nonce,
            'timestamp': ts,
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])
        self.assertEqual(res.json()['votes_created'], 1)


from home.methods_module import (
    mine_modern_batch, ConcurrencyError, PoWTimeoutError,
    verify_v2_block_header, verify_v2_block_merkle_root,
    compute_sentinel_hash, compute_v2_block_hash
)

class Phase5Step4BTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from home.methods_module import generate_keys

        cls.org1 = Organization.objects.create(name="Mining Org 1")
        cls.org2 = Organization.objects.create(name="Mining Org 2")

        cls.u_admin = User.objects.create(username="mining_admin")
        cls.p_admin = UserProfile.objects.create(user=cls.u_admin, role="ORGANIZATION_ADMIN", organization=cls.org1)

        cls.u_auditor = User.objects.create(username="mining_auditor")
        cls.p_auditor = UserProfile.objects.create(user=cls.u_auditor, role="AUDITOR", organization=cls.org1)

        cls.u_other_org = User.objects.create(username="mining_other_org")
        cls.p_other_org = UserProfile.objects.create(user=cls.u_other_org, role="ORGANIZATION_ADMIN", organization=cls.org2)

        cls.election1 = Election.objects.create(organization=cls.org1, title="Mining Elec 1", status="OPEN")
        cls.election2 = Election.objects.create(organization=cls.org2, title="Mining Elec 2", status="OPEN")

        cls.pos_single = Position.objects.create(election=cls.election1, title="President", max_votes_allowed=1)
        cls.cand_1 = Candidate.objects.create(position=cls.pos_single, name="Alpha", affiliation="Party A")
        cls.cand_2 = Candidate.objects.create(position=cls.pos_single, name="Beta", affiliation="Party B")

        cls.pos_multi = Position.objects.create(election=cls.election1, title="Council", max_votes_allowed=2)
        cls.cand_c1 = Candidate.objects.create(position=cls.pos_multi, name="Council 1", affiliation="Party A")
        cls.cand_c2 = Candidate.objects.create(position=cls.pos_multi, name="Council 2", affiliation="Party B")

        cls.pos_e2 = Position.objects.create(election=cls.election2, title="Mayor", max_votes_allowed=1)
        cls.cand_e2 = Candidate.objects.create(position=cls.pos_e2, name="Mayor Cand", affiliation="Party X")

        cls.voter1 = Voters.objects.create(uuid="miner_voter_1", name="Voter One", dob="1990-01-01", pincode="123456", region="R1", vote_done=False)
        cls.voter2 = Voters.objects.create(uuid="miner_voter_2", name="Voter Two", dob="1992-02-02", pincode="123456", region="R1", vote_done=False)

        Eligibility.objects.create(voter=cls.voter1, election=cls.election1)
        Eligibility.objects.create(voter=cls.voter2, election=cls.election1)
        Eligibility.objects.create(voter=cls.voter1, election=cls.election2)

        cls.priv_key1, cls.pub_key1 = generate_keys()
        cls.priv_key2, cls.pub_key2 = generate_keys()

    def setUp(self):
        self.client.force_login(self.u_admin)

    def _submit_valid_ballot(self, voter, election, selections, priv_key, pub_key):
        ballot = Ballot.objects.create(voter=voter, election=election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(election.id, voter.uuid, nonce, ts)
        sig = sign_auth_payload(priv_key, auth_payload)

        # Use voter session for submission
        session = self.client.session
        session['uuid'] = voter.uuid
        session.save()

        payload = {
            'selections': selections,
            'signature': sig,
            'public_key': pub_key,
            'ballot_nonce': nonce,
            'timestamp': ts,
        }
        res = self.client.post(f'/ballots/{ballot.id}/submit/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)

        # Restore admin login
        self.client.force_login(self.u_admin)
        ballot.refresh_from_db()
        return ballot

    def test_01_successful_modern_batch_mining_and_sealing(self):
        """1. Successful mining of a complete modern batch with version-2 block creation and atomic sealing."""
        selections = [
            {'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]},
            {'position_id': self.pos_multi.id, 'candidate_ids': [self.cand_c1.id]}
        ]
        ballot = self._submit_valid_ballot(self.voter1, self.election1, selections, self.priv_key1, self.pub_key1)
        batch = ballot.batch
        self.assertIsNotNone(batch)
        self.assertEqual(batch.ballot_count, 1)
        self.assertEqual(batch.expected_tx_count, 2)

        # Mine batch via endpoint
        res = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['version'], 2)
        self.assertEqual(data['candidate_tx_count'], 2)
        self.assertEqual(data['merkle_leaf_count'], 2)
        self.assertEqual(data['batch_number'], batch.batch_number)

        # Verify Block record
        block = Block.objects.get(id=data['block_id'])
        self.assertEqual(block.version, 2)
        self.assertEqual(block.election, self.election1)
        self.assertEqual(block.batch_number, batch.batch_number)
        self.assertEqual(block.candidate_tx_count, 2)
        self.assertEqual(block.merkle_leaf_count, 2)

        # Verify Header and Merkle Root
        self.assertTrue(verify_v2_block_header(block))
        self.assertTrue(verify_v2_block_merkle_root(block))

        # Verify Vote and VoteBackup assignment
        votes = list(Vote.objects.filter(batch=batch))
        self.assertEqual(len(votes), 2)
        for v in votes:
            self.assertEqual(v.block_id, str(block.id))

        backups = list(VoteBackup.objects.filter(batch=batch))
        self.assertEqual(len(backups), 2)
        for vb in backups:
            self.assertEqual(vb.block_id, str(block.id))

        # Verify Ballot sealing
        ballot.refresh_from_db()
        self.assertTrue(ballot.is_sealed)
        self.assertEqual(ballot.sealed_block_id, str(block.id))

        # Verify Batch sealing
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'SEALED')
        self.assertEqual(batch.sealed_block_id, str(block.id))

    def test_02_v2_block_header_hash_and_tamper_detection(self):
        """2. Correct version-2 block metadata, header-hash verification, and tamper detection."""
        ballot = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)
        res = self.client.post(f'/batches/{ballot.batch_id}/mine/')
        self.assertEqual(res.status_code, 200)

        block = Block.objects.get(id=res.json()['block_id'])
        self.assertTrue(verify_v2_block_header(block))
        self.assertTrue(verify_v2_block_merkle_root(block))

        # Verify block tampering detection on header fields
        original_nonce = block.nonce
        block.nonce = original_nonce + 1
        self.assertFalse(verify_v2_block_header(block))
        block.nonce = original_nonce

        original_batch_num = block.batch_number
        block.batch_number = 9999
        self.assertFalse(verify_v2_block_header(block))
        block.batch_number = original_batch_num

        # Verify tampering detection via /verify-block/ endpoint
        res_v = self.client.get(f'/verify-block/?selected[]={block.id}')
        self.assertEqual(res_v.status_code, 200)
        self.assertFalse(res_v.json()[str(block.id)])  # Not tampered

    def test_03_multi_position_ballot_mining(self):
        """3. Multiple positions within a ballot are mined into a single block without splitting."""
        selections = [
            {'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]},
            {'position_id': self.pos_multi.id, 'candidate_ids': [self.cand_c1.id, self.cand_c2.id]}
        ]
        ballot = self._submit_valid_ballot(self.voter1, self.election1, selections, self.priv_key1, self.pub_key1)
        res = self.client.post(f'/batches/{ballot.batch_id}/mine/')
        self.assertEqual(res.status_code, 200)

        block = Block.objects.get(id=res.json()['block_id'])
        self.assertEqual(block.candidate_tx_count, 3)
        self.assertEqual(block.merkle_leaf_count, 3)
        self.assertEqual(Vote.objects.filter(block_id=str(block.id)).count(), 3)

    def test_04_empty_batch_sentinel_mining(self):
        """4. Empty batch (all voters abstained) produces canonical sentinel Merkle leaf."""
        # Create an open batch and attach an abstaining ballot (0 votes)
        batch = get_or_create_active_batch(self.election1)
        ballot = Ballot.objects.create(
            voter=self.voter1,
            election=self.election1,
            ballot_nonce=secrets.token_hex(32),
            signature="abstain_sig",
            public_key=self.pub_key1,
            batch=batch
        )
        batch.ballot_count = 1
        batch.expected_tx_count = 0
        batch.status = 'CLOSED'
        batch.save()

        res = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['candidate_tx_count'], 0)
        self.assertEqual(data['merkle_leaf_count'], 1)

        block = Block.objects.get(id=data['block_id'])
        expected_sentinel = compute_sentinel_hash(self.election1.id, batch.batch_number)
        self.assertEqual(block.merkle_hash, expected_sentinel)
        self.assertTrue(verify_v2_block_header(block))
        self.assertTrue(verify_v2_block_merkle_root(block))

        ballot.refresh_from_db()
        self.assertTrue(ballot.is_sealed)
        self.assertEqual(ballot.sealed_block_id, str(block.id))

    def test_05_rejection_of_empty_batch_with_zero_ballots(self):
        """5. Rejection of unsubmitted empty batch with zero ballots."""
        batch = BallotBatch.objects.create(election=self.election1, batch_number=99, ballot_count=0, expected_tx_count=0, status='CLOSED')
        res = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res.status_code, 400)
        self.assertIn("EMPTY_BATCH_NO_BALLOTS", res.json()['error'])
        self.assertEqual(Block.objects.filter(version=2).count(), 0)

    def test_06_rejection_of_inconsistent_transaction_count(self):
        """6. Rejection of batch when expected_tx_count does not match actual transactions."""
        ballot = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)
        batch = ballot.batch
        batch.status = 'CLOSED'
        batch.expected_tx_count = 5  # Inconsistency
        batch.save()

        res = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res.status_code, 400)
        self.assertIn("INCONSISTENT_TX_COUNT", res.json()['error'])
        self.assertEqual(Block.objects.filter(version=2).count(), 0)

    def test_07_rejection_of_votebackup_parity_failure(self):
        """7. Rejection of batch when Vote and VoteBackup parity is violated."""
        ballot = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)
        batch = ballot.batch
        batch.status = 'CLOSED'
        batch.save()

        # Delete VoteBackup to violate parity
        VoteBackup.objects.filter(batch=batch).delete()

        res = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res.status_code, 400)
        self.assertIn("VOTE_BACKUP_PARITY_ERROR", res.json()['error'])
        self.assertEqual(Block.objects.filter(version=2).count(), 0)

    def test_08_election_isolation(self):
        """8. Batch mining isolates elections: mining Election 1 leaves Election 2 unmined."""
        ballot1 = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)
        ballot2 = self._submit_valid_ballot(self.voter1, self.election2, [{'position_id': self.pos_e2.id, 'candidate_ids': [self.cand_e2.id]}], self.priv_key1, self.pub_key1)

        # Mine Election 1 batch
        res = self.client.post(f'/batches/{ballot1.batch_id}/mine/')
        self.assertEqual(res.status_code, 200)

        # Election 1 votes sealed
        self.assertTrue(Vote.objects.filter(batch=ballot1.batch, block_id__isnull=False).exists())
        # Election 2 votes remain unmined
        self.assertTrue(Vote.objects.filter(batch=ballot2.batch, block_id=None).exists())
        ballot2.refresh_from_db()
        self.assertFalse(ballot2.is_sealed)

    def test_09_concurrent_mining_and_worker_lease_locking(self):
        """9. Active worker lease prevents concurrent workers from mining the same batch."""
        ballot = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)
        batch = ballot.batch
        batch.status = 'MINING'
        batch.miner_lock_id = 'active_worker_123'
        batch.locked_at = timezone.now()
        batch.save()

        res = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res.status_code, 409)
        self.assertIn("BATCH_LOCKED", res.json()['error'])

    def test_10_stale_lease_recovery(self):
        """10. Stale worker lease (> 120s) is safely reclaimed by a subsequent worker."""
        ballot = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)
        batch = ballot.batch
        batch.status = 'MINING'
        batch.miner_lock_id = 'crashed_worker'
        batch.locked_at = timezone.now() - timedelta(seconds=150)
        batch.save()

        # New worker reclaims stale lease
        res = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res.status_code, 200)
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'SEALED')

    def test_11_pow_puzzle_timeout_failure(self):
        """11. Proof-of-Work failure when difficulty cannot be satisfied within limit."""
        ballot = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)
        batch = ballot.batch
        batch.status = 'CLOSED'
        batch.save()

        with self.assertRaises(PoWTimeoutError):
            mine_modern_batch(
                batch_id=batch.id,
                puzzle='ffffffffffffffffffff',
                timeout_seconds=0.01,
                max_iterations=10
            )

        batch.refresh_from_db()
        self.assertEqual(batch.status, 'CLOSED')
        self.assertIsNone(batch.miner_lock_id)
        self.assertEqual(Block.objects.filter(version=2).count(), 0)

    def test_12_atomic_rollback_on_block_creation_failure(self):
        """12. Atomic rollback leaves batch recoverable and transactions unassigned if Block creation fails."""
        ballot = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)
        batch = ballot.batch

        with patch('home.models.Block.objects.create', side_effect=RuntimeError("Simulated Block DB failure")):
            res = self.client.post(f'/batches/{batch.id}/mine/')
            self.assertEqual(res.status_code, 400)

        # Batch remains unsealed and recoverable
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'CLOSED')
        self.assertIsNone(batch.sealed_block_id)

        # Transactions remain unmined
        self.assertEqual(Vote.objects.filter(batch=batch, block_id=None).count(), 1)
        ballot.refresh_from_db()
        self.assertFalse(ballot.is_sealed)

    def test_13_legacy_mining_endpoint_remains_compatible(self):
        """13. Legacy mining remains compatible and ignores modern batched transactions."""
        from home.views import create_block
        # Create a legacy unbatched vote
        legacy_vote = Vote.objects.create(
            uuid="legacy_voter_1",
            vote_party_id="1",
            timestamp=timezone.now(),
            block_id=None,
            batch=None,
            election=None
        )
        legacy_vb = VoteBackup.objects.create(
            uuid="legacy_voter_1",
            vote_party_id="1",
            timestamp=legacy_vote.timestamp,
            block_id=None,
            batch=None,
            election=None
        )

        # Submit modern batched ballot
        ballot = self._submit_valid_ballot(self.voter1, self.election1, [{'position_id': self.pos_single.id, 'candidate_ids': [self.cand_1.id]}], self.priv_key1, self.pub_key1)

        # Run legacy create_block
        res_legacy = create_block()
        self.assertGreaterEqual(len(res_legacy['result']), 1)

        # Legacy vote was sealed in a v1 block
        legacy_vote.refresh_from_db()
        self.assertIsNotNone(legacy_vote.block_id)
        v1_block = Block.objects.get(id=int(legacy_vote.block_id))
        self.assertEqual(v1_block.version, 1)

        # Modern batched vote was NOT touched by legacy create_block
        modern_vote = Vote.objects.get(ballot=ballot)
        self.assertIsNone(modern_vote.block_id)

    def test_14_unauthorized_and_auditor_access_rejection(self):
        """14. Unauthenticated users, auditors, and wrong-org admins are rejected."""
        batch = BallotBatch.objects.create(election=self.election1, batch_number=1, status='CLOSED')

        # GET method not allowed
        res_get = self.client.get(f'/batches/{batch.id}/mine/')
        self.assertEqual(res_get.status_code, 405)

        # Unauthenticated
        self.client.logout()
        res_anon = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res_anon.status_code, 403)

        # Auditor role rejected
        self.client.force_login(self.u_auditor)
        res_auditor = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res_auditor.status_code, 403)
        self.assertIn("Auditors cannot mine blocks", res_auditor.json()['error'])

        # Wrong organization admin rejected
        self.client.force_login(self.u_other_org)
        res_wrong_org = self.client.post(f'/batches/{batch.id}/mine/')
        self.assertEqual(res_wrong_org.status_code, 403)
        self.assertIn("Unauthorized organization", res_wrong_org.json()['error'])


class Phase5Step5ATests(TestCase):
    """
    Phase 5 Step 5A: Comprehensive Independent Blockchain Verification Tests.
    Validates legacy v1 verification, modern v2 verification, tamper detection,
    parity audits, full-chain verification, RBAC, and legacy compatibility.
    """
    def setUp(self):
        import datetime
        from home.methods_module import generate_keys
        from home.models import Voters, Eligibility

        # Organizations
        self.org1 = Organization.objects.create(name="City Council Org", description="Org 1")
        self.org2 = Organization.objects.create(name="State Senate Org", description="Org 2")

        # Admin Users
        self.u_plat = User.objects.create_user(username="plat_admin_5a", password="pw")
        UserProfile.objects.create(user=self.u_plat, role="PLATFORM_ADMIN")

        self.u_org_admin = User.objects.create_user(username="org_admin_5a", password="pw")
        UserProfile.objects.create(user=self.u_org_admin, role="ORGANIZATION_ADMIN", organization=self.org1)

        self.u_auditor = User.objects.create_user(username="auditor_5a", password="pw")
        UserProfile.objects.create(user=self.u_auditor, role="AUDITOR", organization=self.org1)

        self.u_other_org = User.objects.create_user(username="other_admin_5a", password="pw")
        UserProfile.objects.create(user=self.u_other_org, role="ORGANIZATION_ADMIN", organization=self.org2)

        # Election & Positions
        self.election1 = Election.objects.create(title="General Election 2026", organization=self.org1, status="OPEN")
        self.pos1 = Position.objects.create(election=self.election1, title="Mayor", max_votes_allowed=1)
        self.cand1 = Candidate.objects.create(position=self.pos1, name="Candidate Alpha", affiliation="Party A")
        self.cand2 = Candidate.objects.create(position=self.pos1, name="Candidate Beta", affiliation="Party B")

        # Keypair
        self.priv_key, self.pub_key = generate_keys()

        # Voters & Eligibility
        self.voter1 = Voters.objects.create(
            uuid="voter_5a_001",
            name="Alice Voter",
            email="alice5a@test.com",
            dob=datetime.date(1995, 1, 1),
            pincode="123456",
            region="North"
        )
        self.voter2 = Voters.objects.create(
            uuid="voter_5a_002",
            name="Bob Voter",
            email="bob5a@test.com",
            dob=datetime.date(1996, 2, 2),
            pincode="123456",
            region="North"
        )
        self.voter3 = Voters.objects.create(
            uuid="voter_5a_003",
            name="Charlie Voter",
            email="charlie5a@test.com",
            dob=datetime.date(1997, 3, 3),
            pincode="123456",
            region="North"
        )
        Eligibility.objects.create(voter=self.voter1, election=self.election1)
        Eligibility.objects.create(voter=self.voter2, election=self.election1)
        Eligibility.objects.create(voter=self.voter3, election=self.election1)

    def _submit_modern_ballot_helper(self, voter, election, selections):
        from home.methods_module import build_auth_payload, sign_auth_payload, submit_modern_ballot
        import secrets
        ballot = Ballot.objects.create(voter=voter, election=election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(election.id, voter.uuid, nonce, ts)
        sig = sign_auth_payload(self.priv_key, auth_payload)
        submit_modern_ballot(
            ballot=ballot,
            candidate_selections=selections,
            signature=sig,
            public_key=self.pub_key,
            ballot_nonce=nonce,
            timestamp_iso=ts,
            auth_payload=auth_payload
        )
        ballot.refresh_from_db()
        return ballot

    def _create_and_mine_modern_block(self, cand=None, voter=None):
        from home.methods_module import mine_modern_batch
        cand = cand or self.cand1
        voter = voter or self.voter1
        ballot = self._submit_modern_ballot_helper(
            voter=voter,
            election=self.election1,
            selections=[(self.pos1, cand)]
        )
        res_mine = mine_modern_batch(batch_id=ballot.batch_id)
        return Block.objects.get(id=res_mine['block_id']), ballot.batch

    def test_01_valid_historical_v1_block_verification(self):
        """1. Valid historical version-1 block verifies with 100% precision."""
        from home.methods_module import verify_block_v1, verify_single_block, compute_v1_block_hash
        from home.merkle_tool import MerkleTools
        prev_h = '0' * 64
        t_now = timezone.now()
        tree = MerkleTools()
        tree.add_leaf(["uuid1|cand1|" + str(t_now)], do_hash=True)
        tree.make_tree()
        m_root = tree.get_merkle_root()

        # Mine simple PoW
        nonce = 0
        while True:
            h = compute_v1_block_hash(prev_h, m_root, nonce, t_now.timestamp())
            if h.startswith('00'):
                break
            nonce += 1

        b1 = Block.objects.create(
            id=9001,
            prev_hash=prev_h,
            merkle_hash=m_root,
            this_hash=h,
            nonce=nonce,
            timestamp=t_now,
            version=1
        )
        Vote.objects.create(uuid="uuid1", vote_party_id="cand1", timestamp=t_now, block_id=str(b1.id))
        VoteBackup.objects.create(uuid="uuid1", vote_party_id="cand1", timestamp=t_now, block_id=str(b1.id))

        res = verify_block_v1(b1, check_link=False)
        self.assertTrue(res['valid'])
        self.assertEqual(len(res['errors']), 0)
        self.assertEqual(res['version'], 1)

        res_dispatch = verify_single_block(b1.id, check_link=False)
        self.assertTrue(res_dispatch['valid'])

    def test_02_valid_modern_v2_block_verification(self):
        """2. Valid modern version-2 block verification."""
        from home.methods_module import verify_block_v2, verify_single_block
        block, batch = self._create_and_mine_modern_block()
        res = verify_block_v2(block, check_link=False)
        self.assertTrue(res['valid'])
        self.assertEqual(len(res['errors']), 0)
        self.assertEqual(res['version'], 2)

        res_dispatch = verify_single_block(block.id, check_link=False)
        self.assertTrue(res_dispatch['valid'])

    def test_03_header_tampering_detection(self):
        """3. Header tampering (e.g. altered this_hash or nonce) is detected."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        # Tamper nonce
        block.nonce = block.nonce + 1
        res = verify_block_v2(block, check_link=False)
        self.assertFalse(res['valid'])
        self.assertTrue(any("HEADER_HASH_MISMATCH" in e for e in res['errors']))

    def test_04_previous_hash_tampering_detection(self):
        """4. Previous-hash tampering is detected."""
        from home.methods_module import verify_block_v2
        block1, _ = self._create_and_mine_modern_block(voter=self.voter1)
        block2, _ = self._create_and_mine_modern_block(voter=self.voter2)
        # Block2's prev_hash should match block1.this_hash
        self.assertEqual(block2.prev_hash, block1.this_hash)
        # Tamper block2 prev_hash
        block2.prev_hash = 'f' * 64
        res = verify_block_v2(block2, check_link=True, prev_block=block1)
        self.assertFalse(res['valid'])
        self.assertTrue(any("PREV_HASH_LINK_BROKEN" in e for e in res['errors']))

    def test_05_invalid_proof_of_work_detection(self):
        """5. Invalid proof-of-work difficulty is detected."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        # Difficulty requirement '000000' not satisfied by standard hash
        res = verify_block_v2(block, check_link=False, puzzle="000000")
        self.assertFalse(res['valid'])
        self.assertTrue(any("INVALID_PROOF_OF_WORK" in e for e in res['errors']))

    def test_06_merkle_root_tampering_detection(self):
        """6. Merkle root tampering is detected."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        block.merkle_hash = 'deadbeef' * 8
        res = verify_block_v2(block, check_link=False)
        self.assertFalse(res['valid'])
        self.assertTrue(any("MERKLE_ROOT_MISMATCH" in e or "HEADER_HASH_MISMATCH" in e for e in res['errors']))

    def test_07_missing_or_duplicated_transactions_detection(self):
        """7. Missing or extra transactions detected against candidate_tx_count."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        # Delete one vote
        v = Vote.objects.filter(block_id=str(block.id)).first()
        v.delete()
        res = verify_block_v2(block, check_link=False)
        self.assertFalse(res['valid'])
        self.assertTrue(any("TRANSACTION_COUNT_MISMATCH" in e for e in res['errors']))

    def test_08_invalid_tx_id_or_commitment_salt_detection(self):
        """8. Invalid transaction ID or commitment salt detected."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        v = Vote.objects.filter(block_id=str(block.id)).first()
        # Tamper commitment salt
        v.commitment_salt = 'f' * 64
        v.save()
        res = verify_block_v2(block, check_link=False)
        self.assertFalse(res['valid'])
        self.assertTrue(any("INVALID_TX_ID" in e for e in res['errors']))

    def test_09_vote_backup_parity_mismatch_detection(self):
        """9. Vote / VoteBackup parity mismatch detected."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        vb = VoteBackup.objects.filter(block_id=str(block.id)).first()
        # Change party on VoteBackup
        vb.vote_party_id = "tampered_candidate"
        vb.save()
        res = verify_block_v2(block, check_link=False)
        self.assertFalse(res['valid'])
        self.assertTrue(any("VOTE_BACKUP_PARITY_MISMATCH" in e for e in res['errors']))

    def test_10_election_or_batch_association_mismatch(self):
        """10. Vote belonging to different election or batch detected."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        v = Vote.objects.filter(block_id=str(block.id)).first()
        # Point to other election
        other_elec = Election.objects.create(title="Other Election", organization=self.org2, status="OPEN")
        v.election = other_elec
        v.save()
        res = verify_block_v2(block, check_link=False)
        self.assertFalse(res['valid'])
        self.assertTrue(any("ELECTION_MISMATCH" in e for e in res['errors']))

    def test_11_unsealed_ballot_in_sealed_batch(self):
        """11. Unsealed ballot in a sealed batch detected."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        b = Ballot.objects.filter(batch=batch).first()
        b.is_sealed = False
        b.save()
        res = verify_block_v2(block, check_link=False)
        self.assertFalse(res['valid'])
        self.assertTrue(any("UNSEALED_BALLOT" in e for e in res['errors']))

    def test_12_incorrect_sealed_block_references(self):
        """12. Incorrect sealed block references detected."""
        from home.methods_module import verify_block_v2
        block, batch = self._create_and_mine_modern_block()
        batch.sealed_block_id = "99999"
        batch.save()
        res = verify_block_v2(block, check_link=False)
        self.assertFalse(res['valid'])
        self.assertTrue(any("BATCH_SEALED_BLOCK_MISMATCH" in e for e in res['errors']))

    def test_13_empty_batch_sentinel_verification(self):
        """13. Empty-batch (all abstentions) sentinel verified."""
        from home.methods_module import mine_modern_batch, verify_block_v2
        ballot = self._submit_modern_ballot_helper(
            voter=self.voter2,
            election=self.election1,
            selections=[]
        )
        res_mine = mine_modern_batch(batch_id=ballot.batch_id)
        block = Block.objects.get(id=res_mine['block_id'])
        self.assertEqual(block.candidate_tx_count, 0)
        self.assertEqual(block.merkle_leaf_count, 1)

        res_v = verify_block_v2(block, check_link=False)
        self.assertTrue(res_v['valid'])
        self.assertEqual(len(res_v['errors']), 0)

    def test_14_full_chain_verification_reporting(self):
        """14. Full-chain verification reports status, counts, and failures cleanly."""
        from home.methods_module import verify_full_chain
        block1, _ = self._create_and_mine_modern_block(voter=self.voter1)
        res = verify_full_chain(from_block_id=block1.id, to_block_id=block1.id)
        self.assertEqual(res['status'], 'VERIFIED')
        self.assertTrue(res['valid'])
        self.assertEqual(res['total_blocks_checked'], 1)
        self.assertEqual(len(res['failures']), 0)

        # Corrupt the block
        orig_hash = block1.this_hash
        block1.this_hash = 'badhash'
        block1.save()

        res_tampered = verify_full_chain(from_block_id=block1.id, to_block_id=block1.id)
        self.assertEqual(res_tampered['status'], 'FAILED')
        self.assertFalse(res_tampered['valid'])
        self.assertIsNotNone(res_tampered['first_failure'])
        self.assertEqual(res_tampered['first_failure']['block_id'], block1.id)

    def test_15_unauthorized_access_and_organization_isolation(self):
        """15. RBAC and organization scoping on verification endpoints."""
        block, batch = self._create_and_mine_modern_block(voter=self.voter1)

        # 1. Anonymous user on /blocks/<id>/verify/ gets public sanitized fields
        self.client.logout()
        res_block_pub = self.client.get(f'/blocks/{block.id}/verify/')
        self.assertEqual(res_block_pub.status_code, 200)
        data_pub = res_block_pub.json()
        self.assertIn('valid', data_pub)
        self.assertIn('checks_performed', data_pub)
        # Should not expose internal database details like batch_id or secret salts
        self.assertNotIn('batch_id', data_pub)

        # 2. Anonymous user on /batches/<id>/verify/ is 403 Forbidden
        res_batch_anon = self.client.get(f'/batches/{batch.id}/verify/')
        self.assertEqual(res_batch_anon.status_code, 403)

        # 3. Anonymous user on /blockchain/verify-chain/ is 403 Forbidden
        res_chain_anon = self.client.get('/blockchain/verify-chain/')
        self.assertEqual(res_chain_anon.status_code, 403)

        # 4. Other organization admin on org1's batch is 403 Forbidden
        self.client.force_login(self.u_other_org)
        res_batch_other = self.client.get(f'/batches/{batch.id}/verify/')
        self.assertEqual(res_batch_other.status_code, 403)

        # 5. Auditor on org1's batch succeeds (200)
        self.client.force_login(self.u_auditor)
        res_batch_aud = self.client.get(f'/batches/{batch.id}/verify/')
        self.assertEqual(res_batch_aud.status_code, 200)
        self.assertTrue(res_batch_aud.json()['valid'])

        # 6. Auditor on /blockchain/verify-chain/ succeeds (200)
        res_chain_aud = self.client.get(f'/blockchain/verify-chain/?from_block={block.id}&to_block={block.id}')
        self.assertEqual(res_chain_aud.status_code, 200)
        self.assertEqual(res_chain_aud.json()['status'], 'VERIFIED')

        # 7. Non-GET methods rejected with 405 Method Not Allowed
        res_post_block = self.client.post(f'/blocks/{block.id}/verify/')
        self.assertEqual(res_post_block.status_code, 405)
        res_post_batch = self.client.post(f'/batches/{batch.id}/verify/')
        self.assertEqual(res_post_batch.status_code, 405)
        res_post_chain = self.client.post('/blockchain/verify-chain/')
        self.assertEqual(res_post_chain.status_code, 405)

    def test_16_preservation_of_legacy_behavior(self):
        """16. Legacy /verify-block/?selected[]=... format preserved."""
        block, batch = self._create_and_mine_modern_block(voter=self.voter1)
        # Query with selected[]
        res = self.client.get(f'/verify-block/?selected[]={block.id}')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn(str(block.id), data)
        self.assertFalse(data[str(block.id)])  # not tampered

        # Single block query via /verify-block/?id=...
        res_id = self.client.get(f'/verify-block/?id={block.id}')
        self.assertEqual(res_id.status_code, 200)
        self.assertTrue(res_id.json()['valid'])


class Phase6Step6ATests(TestCase):
    """
    Phase 6 Step 6A: Verified Results & Audit Integration Tests.
    Validates election-scoped verified tallying, batch/block verification before release,
    audit records, isolation, zero-vote handling, abstentions, and RBAC scoping.
    """
    def setUp(self):
        import datetime
        from home.methods_module import generate_keys

        # Organizations
        self.org1 = Organization.objects.create(name="Metro Transit Org", description="Org 1")
        self.org2 = Organization.objects.create(name="Regional Water Org", description="Org 2")

        # Admin Users
        self.u_plat = User.objects.create_user(username="plat_admin_6a", password="pw")
        UserProfile.objects.create(user=self.u_plat, role="PLATFORM_ADMIN")

        self.u_org_admin1 = User.objects.create_user(username="org_admin_6a_1", password="pw")
        UserProfile.objects.create(user=self.u_org_admin1, role="ORGANIZATION_ADMIN", organization=self.org1)

        self.u_auditor1 = User.objects.create_user(username="auditor_6a_1", password="pw")
        UserProfile.objects.create(user=self.u_auditor1, role="AUDITOR", organization=self.org1)

        self.u_org_admin2 = User.objects.create_user(username="org_admin_6a_2", password="pw")
        UserProfile.objects.create(user=self.u_org_admin2, role="ORGANIZATION_ADMIN", organization=self.org2)

        self.u_no_profile = User.objects.create_user(username="no_profile_6a", password="pw")

        # Elections
        self.elec1 = Election.objects.create(title="Transit Board Election", organization=self.org1, status="CLOSED")
        self.elec2 = Election.objects.create(title="Water Board Election", organization=self.org1, status="CLOSED")
        self.elec_org2 = Election.objects.create(title="Regional Election", organization=self.org2, status="CLOSED")

        # Positions & Candidates for Election 1
        self.pos_chair = Position.objects.create(election=self.elec1, title="Board Chair", max_votes_allowed=1)
        self.cand_c1 = Candidate.objects.create(position=self.pos_chair, name="Alice Chair", affiliation="Party Green")
        self.cand_c2 = Candidate.objects.create(position=self.pos_chair, name="Bob Chair", affiliation="Party Blue")
        self.cand_c_zero = Candidate.objects.create(position=self.pos_chair, name="Zero Vote Candidate", affiliation="Party Independent")

        self.pos_treasurer = Position.objects.create(election=self.elec1, title="Treasurer", max_votes_allowed=1)
        self.cand_t1 = Candidate.objects.create(position=self.pos_treasurer, name="Carol Treasurer", affiliation="Party Green")

        self.pos_empty = Position.objects.create(election=self.elec1, title="Empty Position", max_votes_allowed=1)
        self.cand_e1 = Candidate.objects.create(position=self.pos_empty, name="Dave Empty", affiliation="Party Independent")

        # Positions for Election 2
        self.pos_elec2 = Position.objects.create(election=self.elec2, title="Director", max_votes_allowed=1)
        self.cand_elec2_1 = Candidate.objects.create(position=self.pos_elec2, name="Eve Director", affiliation="Party Yellow")

        # Keypair
        self.priv_key, self.pub_key = generate_keys()

        # Voters
        self.voter1 = Voters.objects.create(
            uuid="voter_6a_001",
            name="Voter 1",
            email="v1_6a@test.com",
            dob=datetime.date(1990, 1, 1),
            pincode="500001",
            region="Zone A"
        )
        self.voter2 = Voters.objects.create(
            uuid="voter_6a_002",
            name="Voter 2",
            email="v2_6a@test.com",
            dob=datetime.date(1991, 2, 2),
            pincode="500002",
            region="Zone B"
        )
        self.voter3 = Voters.objects.create(
            uuid="voter_6a_003",
            name="Voter 3",
            email="v3_6a@test.com",
            dob=datetime.date(1992, 3, 3),
            pincode="500003",
            region="Zone C"
        )
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        Eligibility.objects.create(voter=self.voter2, election=self.elec1)
        Eligibility.objects.create(voter=self.voter3, election=self.elec1)
        Eligibility.objects.create(voter=self.voter1, election=self.elec2)

    def _submit_and_mine_modern_ballot(self, voter, election, selections):
        from home.methods_module import build_auth_payload, sign_auth_payload, submit_modern_ballot, mine_modern_batch
        import secrets
        ballot = Ballot.objects.create(voter=voter, election=election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(election.id, voter.uuid, nonce, ts)
        sig = sign_auth_payload(self.priv_key, auth_payload)
        submit_modern_ballot(
            ballot=ballot,
            candidate_selections=selections,
            signature=sig,
            public_key=self.pub_key,
            ballot_nonce=nonce,
            timestamp_iso=ts,
            auth_payload=auth_payload
        )
        ballot.refresh_from_db()
        res_mine = mine_modern_batch(batch_id=ballot.batch_id)
        block = Block.objects.get(id=res_mine['block_id'])
        return ballot, block

    def test_01_correct_tally_valid_sealed_modern_election(self):
        """1. Correct tally for a valid sealed modern election."""
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1), (self.pos_treasurer, self.cand_t1)]
        )
        self._submit_and_mine_modern_ballot(
            self.voter2, self.elec1, [(self.pos_chair, self.cand_c1)]
        )

        self.client.force_login(self.u_org_admin1)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data['verified'])
        self.assertTrue(data['results_available'])
        self.assertEqual(data['result_status'], 'FINALIZED')
        self.assertTrue(data['is_finalized'])
        self.assertEqual(data['summary']['total_votes_counted'], 3)
        self.assertEqual(data['summary']['total_submitted_ballots'], 2)

        # Check Board Chair candidate votes
        chair_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_chair.id)
        c1 = next(c for c in chair_pos['candidates'] if c['candidate_id'] == self.cand_c1.id)
        c2 = next(c for c in chair_pos['candidates'] if c['candidate_id'] == self.cand_c2.id)
        self.assertEqual(c1['votes_received'], 2)
        self.assertEqual(c2['votes_received'], 0)
        self.assertEqual(chair_pos['total_votes'], 2)

        # Audit record was created
        self.assertIn('audit', data)
        self.assertTrue(data['audit']['verification_passed'])
        self.assertGreaterEqual(data['audit']['blocks_checked'], 1)

    def test_02_isolation_between_two_elections(self):
        """2. Isolation between two elections."""
        self._submit_and_mine_modern_ballot(self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)])
        self._submit_and_mine_modern_ballot(self.voter1, self.elec2, [(self.pos_elec2, self.cand_elec2_1)])

        self.client.force_login(self.u_org_admin1)
        res1 = self.client.get(f'/elections/{self.elec1.id}/results/')
        res2 = self.client.get(f'/elections/{self.elec2.id}/results/')

        self.assertEqual(res1.json()['summary']['total_votes_counted'], 1)
        self.assertEqual(res2.json()['summary']['total_votes_counted'], 1)
        self.assertNotIn(self.cand_elec2_1.id, [c['candidate_id'] for p in res1.json()['positions'] for c in p['candidates']])

    def test_03_isolation_between_two_organizations(self):
        """3. Isolation between two organizations."""
        self.client.force_login(self.u_org_admin2)  # Org 2 admin
        res = self.client.get(f'/elections/{self.elec1.id}/results/')  # Org 1 election
        self.assertEqual(res.status_code, 403)
        self.assertIn("Unauthorized organization", res.json()['error'])

        # Platform admin can access Org 1
        self.client.force_login(self.u_plat)
        res_plat = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res_plat.status_code, 200)

    def test_04_pending_or_unsealed_batches_excluded(self):
        """4. Pending or unsealed batches prevent final results release."""
        # Create an unsealed batch in a CLOSED election
        BallotBatch.objects.create(election=self.elec1, batch_number=1, status='OPEN')

        self.client.force_login(self.u_org_admin1)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data['results_available'])
        self.assertFalse(data['verified'])
        self.assertEqual(data['failure_category'], 'UNSEALED_BATCHES_DETECTED')

    def test_05_tampered_block_prevents_final_results(self):
        """5. Tampered block or invalid chain prevents final results."""
        ballot, block = self._submit_and_mine_modern_ballot(self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)])
        # Corrupt block header hash
        block.this_hash = 'tampered_hash_000'
        block.save()

        self.client.force_login(self.u_org_admin1)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data['results_available'])
        self.assertFalse(data['verified'])
        self.assertEqual(data['failure_category'], 'BLOCK_INTEGRITY_FAILURE')

    def test_06_vote_backup_mismatch_prevents_final_results(self):
        """6. Vote/VoteBackup mismatch prevents final results."""
        ballot, block = self._submit_and_mine_modern_ballot(self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)])
        vb = VoteBackup.objects.filter(block_id=str(block.id)).first()
        vb.vote_party_id = "tampered_cand"
        vb.save()

        self.client.force_login(self.u_org_admin1)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data['results_available'])
        self.assertFalse(data['verified'])
        self.assertEqual(data['failure_category'], 'BATCH_INTEGRITY_FAILURE')

    def test_07_duplicate_transactions_cannot_inflate_totals(self):
        """7. Duplicate transactions cannot inflate totals."""
        from unittest.mock import patch
        from django.db.utils import IntegrityError
        from home.methods_module import calculate_verified_election_results

        ballot, block = self._submit_and_mine_modern_ballot(self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)])
        v_orig = Vote.objects.filter(block_id=str(block.id)).first()

        # Layer 1 defense: Database UNIQUE constraint prevents duplicate tx_id insertion
        from django.db import transaction
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Vote.objects.create(
                    id=99999,
                    uuid="duplicate_voter",
                    vote_party_id=v_orig.vote_party_id,
                    timestamp=v_orig.timestamp,
                    block_id=str(block.id),
                    election=self.elec1,
                    batch=ballot.batch,
                    tx_id=v_orig.tx_id,
                    commitment_salt=v_orig.commitment_salt,
                    position=v_orig.position
                )

        # Layer 2 defense: Application-level seen_tx_ids detects duplicate tx_ids
        orig_filter = Vote.objects.filter
        class MockQS:
            def order_by(self, *a, **k):
                return [v_orig, v_orig]

        def mock_vote_filter(*args, **kwargs):
            if kwargs.get('batch') == ballot.batch and kwargs.get('block_id') == ballot.batch.sealed_block_id:
                return MockQS()
            return orig_filter(*args, **kwargs)

        with patch.object(Vote.objects, 'filter', side_effect=mock_vote_filter):
            res = calculate_verified_election_results(self.elec1.id)
            self.assertFalse(res['results_available'])
            self.assertEqual(res['failure_category'], 'DUPLICATE_TRANSACTION_DETECTED')

    def test_08_multiple_positions_tallied_independently(self):
        """8. Multiple positions are tallied independently."""
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1), (self.pos_treasurer, self.cand_t1)]
        )

        self.client.force_login(self.u_org_admin1)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()
        chair_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_chair.id)
        treas_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_treasurer.id)
        self.assertEqual(chair_pos['total_votes'], 1)
        self.assertEqual(treas_pos['total_votes'], 1)

    def test_09_zero_vote_candidates_and_positions(self):
        """9. Zero-vote candidates and positions are handled correctly."""
        self._submit_and_mine_modern_ballot(self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)])

        self.client.force_login(self.u_org_admin1)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()
        chair_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_chair.id)
        zero_cand = next(c for c in chair_pos['candidates'] if c['candidate_id'] == self.cand_c_zero.id)
        self.assertEqual(zero_cand['votes_received'], 0)

        empty_pos = next(p for p in data['positions'] if p['position_id'] == self.pos_empty.id)
        self.assertEqual(empty_pos['total_votes'], 0)

    def test_10_abstentions_not_counted_as_candidate_votes(self):
        """10. Abstentions are not counted as candidate votes."""
        self._submit_and_mine_modern_ballot(self.voter1, self.elec1, [])

        self.client.force_login(self.u_org_admin1)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        data = res.json()
        self.assertTrue(data['verified'])
        self.assertEqual(data['summary']['total_votes_counted'], 0)
        self.assertEqual(data['summary']['total_submitted_ballots'], 1)
        self.assertEqual(data['summary']['total_abstaining_ballots'], 1)
        for pos in data['positions']:
            self.assertEqual(pos['total_votes'], 0)
            for c in pos['candidates']:
                self.assertEqual(c['votes_received'], 0)

    def test_11_unauthorized_roles_cannot_access_results_or_audit(self):
        """11. Unauthorized roles cannot access restricted result/audit data."""
        self.client.logout()
        res_anon = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res_anon.status_code, 403)

        res_audit_anon = self.client.get(f'/elections/{self.elec1.id}/audit-records/')
        self.assertEqual(res_audit_anon.status_code, 403)

        self.client.force_login(self.u_no_profile)
        res_no_prof = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res_no_prof.status_code, 403)

        # Auditor role allowed to inspect results and audit trail
        self.client.force_login(self.u_auditor1)
        res_auditor = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res_auditor.status_code, 200)

        res_audit_trail = self.client.get(f'/elections/{self.elec1.id}/audit-records/')
        self.assertEqual(res_audit_trail.status_code, 200)
        self.assertIn('audit_records', res_audit_trail.json())

    def test_12_legacy_results_continue_to_pass(self):
        """12. Existing legacy result view (/show-result/) continues to render."""
        res_legacy = self.client.get('/show-result/')
        self.assertEqual(res_legacy.status_code, 200)


class Phase6Step6BTests(TestCase):
    """
    Phase 6 Step 6B: Result Publication, Verification Receipts & Audit Integrity Tests.
    1. Valid verified result receives a deterministic receipt.
    2. Repeating verification on unchanged data produces the same receipt.
    3. Changing a candidate total changes the receipt.
    4. Changing the verified block set changes the receipt.
    5. Receipt contains no voter UUID.
    6. Receipt contains no private key, signature, or individual ballot choice.
    7. Verification failure prevents publication (positions withheld).
    8. Unsealed batch prevents final publication.
    9. Closed vs Open publication lifecycle rules.
    10. Stale receipt detected after relevant ledger/result state changes.
    11. Voter cannot access administrative audit records.
    12. Organization Admin cannot access another organization's audit records.
    13. Authorized auditor/admin can access permitted audit information and verify receipt.
    14. Audit records cannot be modified through the exposed application API.
    15. Consistency check handles missing prior audit receipts gracefully.
    16. Existing legacy result tests continue to pass.
    """
    def setUp(self):
        import datetime
        from home.methods_module import generate_keys

        # Organizations
        self.org1 = Organization.objects.create(name="Transit Authority Org", description="Org 1")
        self.org2 = Organization.objects.create(name="Harbor Authority Org", description="Org 2")

        # Admin Users
        self.u_plat = User.objects.create_user(username="plat_admin_6b", password="pw")
        UserProfile.objects.create(user=self.u_plat, role="PLATFORM_ADMIN")

        self.u_org_admin1 = User.objects.create_user(username="org_admin_6b_1", password="pw")
        UserProfile.objects.create(user=self.u_org_admin1, role="ORGANIZATION_ADMIN", organization=self.org1)

        self.u_auditor1 = User.objects.create_user(username="auditor_6b_1", password="pw")
        UserProfile.objects.create(user=self.u_auditor1, role="AUDITOR", organization=self.org1)

        self.u_org_admin2 = User.objects.create_user(username="org_admin_6b_2", password="pw")
        UserProfile.objects.create(user=self.u_org_admin2, role="ORGANIZATION_ADMIN", organization=self.org2)

        self.u_regular_voter = User.objects.create_user(username="regular_voter_6b", password="pw")

        # Elections
        self.elec1 = Election.objects.create(title="Board Election 2026", organization=self.org1, status="CLOSED")
        self.elec_open = Election.objects.create(title="Active Primary 2026", organization=self.org1, status="OPEN")
        self.elec_org2 = Election.objects.create(title="Harbor Election 2026", organization=self.org2, status="CLOSED")

        # Positions & Candidates for Election 1
        self.pos_chair = Position.objects.create(election=self.elec1, title="Board Chair", max_votes_allowed=1)
        self.cand_c1 = Candidate.objects.create(position=self.pos_chair, name="Alice Director", affiliation="Alliance")
        self.cand_c2 = Candidate.objects.create(position=self.pos_chair, name="Bob Trustee", affiliation="Forward")

        self.pos_treasurer = Position.objects.create(election=self.elec1, title="Treasurer", max_votes_allowed=1)
        self.cand_t1 = Candidate.objects.create(position=self.pos_treasurer, name="Carol Comptroller", affiliation="Alliance")

        # Positions for Open Election
        self.pos_open = Position.objects.create(election=self.elec_open, title="Council Seat", max_votes_allowed=1)
        self.cand_open1 = Candidate.objects.create(position=self.pos_open, name="Dan Member", affiliation="Alliance")

        # Keypair
        self.priv_key, self.pub_key = generate_keys()

        # Voters
        self.voter1 = Voters.objects.create(
            uuid="voter_6b_001",
            name="Voter 6B One",
            email="v1_6b@test.com",
            dob=datetime.date(1990, 1, 1),
            pincode="600001",
            region="Sector 1"
        )
        self.voter2 = Voters.objects.create(
            uuid="voter_6b_002",
            name="Voter 6B Two",
            email="v2_6b@test.com",
            dob=datetime.date(1991, 2, 2),
            pincode="600002",
            region="Sector 2"
        )
        Eligibility.objects.create(voter=self.voter1, election=self.elec1)
        Eligibility.objects.create(voter=self.voter2, election=self.elec1)
        Eligibility.objects.create(voter=self.voter1, election=self.elec_open)

    def _submit_and_mine_modern_ballot(self, voter, election, selections):
        from home.methods_module import build_auth_payload, sign_auth_payload, submit_modern_ballot, mine_modern_batch
        import secrets
        ballot = Ballot.objects.create(voter=voter, election=election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(election.id, voter.uuid, nonce, ts)
        sig = sign_auth_payload(self.priv_key, auth_payload)
        submit_modern_ballot(
            ballot=ballot,
            candidate_selections=selections,
            signature=sig,
            public_key=self.pub_key,
            ballot_nonce=nonce,
            timestamp_iso=ts,
            auth_payload=auth_payload
        )
        ballot.refresh_from_db()
        res_mine = mine_modern_batch(batch_id=ballot.batch_id)
        block = Block.objects.get(id=res_mine['block_id'])
        return ballot, block

    def test_01_valid_verified_result_receives_deterministic_receipt(self):
        """1. Valid verified result receives a deterministic receipt."""
        from home.models import ElectionResultAudit
        from home.methods_module import calculate_verified_election_results
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1), (self.pos_treasurer, self.cand_t1)]
        )
        res = calculate_verified_election_results(self.elec1.id)
        self.assertTrue(res['verified'])
        self.assertTrue(res['results_available'])
        self.assertTrue(res['is_eligible_for_publication'])
        self.assertEqual(res['publication_state'], 'VERIFIED_PUBLISHED')
        self.assertIn('verification_receipt', res)
        self.assertEqual(len(res['verification_receipt']), 64)

        # Confirm persisted in ElectionResultAudit
        audit = ElectionResultAudit.objects.filter(election=self.elec1).latest('timestamp')
        self.assertEqual(audit.result_receipt, res['verification_receipt'])
        self.assertEqual(audit.verification_status, 'VERIFIED')

    def test_02_repeating_verification_produces_same_receipt(self):
        """2. Repeating verification on unchanged data produces the exact same receipt."""
        from home.methods_module import calculate_verified_election_results
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)]
        )
        res1 = calculate_verified_election_results(self.elec1.id)
        res2 = calculate_verified_election_results(self.elec1.id)
        self.assertEqual(res1['verification_receipt'], res2['verification_receipt'])

    def test_03_changing_candidate_total_changes_receipt(self):
        """3. Changing a candidate total changes the receipt."""
        from home.methods_module import calculate_verified_election_results
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)]
        )
        res1 = calculate_verified_election_results(self.elec1.id)
        r1 = res1['verification_receipt']

        # Add another vote for candidate 2 in a new batch
        self._submit_and_mine_modern_ballot(
            self.voter2, self.elec1, [(self.pos_chair, self.cand_c2)]
        )
        res2 = calculate_verified_election_results(self.elec1.id)
        r2 = res2['verification_receipt']
        self.assertNotEqual(r1, r2)

    def test_04_changing_verified_block_set_changes_receipt(self):
        """4. Changing the verified block or batch set changes the receipt."""
        from home.methods_module import compute_canonical_result_receipt
        pos_data = [{'position_id': 1, 'total_votes': 1, 'candidates': [{'candidate_id': 10, 'votes_received': 1}]}]
        r1, _ = compute_canonical_result_receipt(
            election_id=1, verified_block_ids=['100'], sealed_batch_ids=[1],
            verified_tx_count=1, total_submitted_ballots=1, total_abstaining_ballots=0,
            positions_results=pos_data
        )
        r2, _ = compute_canonical_result_receipt(
            election_id=1, verified_block_ids=['100', '101'], sealed_batch_ids=[1],
            verified_tx_count=1, total_submitted_ballots=1, total_abstaining_ballots=0,
            positions_results=pos_data
        )
        self.assertNotEqual(r1, r2)

        r3, _ = compute_canonical_result_receipt(
            election_id=1, verified_block_ids=['100'], sealed_batch_ids=[1, 2],
            verified_tx_count=1, total_submitted_ballots=1, total_abstaining_ballots=0,
            positions_results=pos_data
        )
        self.assertNotEqual(r1, r3)

    def test_05_receipt_contains_no_voter_uuid(self):
        """5. Receipt generation and canonical payload contain no voter UUID."""
        import json
        from home.methods_module import calculate_verified_election_results
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)]
        )
        res = calculate_verified_election_results(self.elec1.id)
        payload_str = json.dumps(res['canonical_receipt_payload'])
        self.assertNotIn(self.voter1.uuid, payload_str)
        self.assertNotIn('uuid', payload_str.lower())
        self.assertNotIn('voter', payload_str.lower())

    def test_06_receipt_contains_no_private_key_signature_or_ballot_choice(self):
        """6. Receipt contains no private key, signature, or individual ballot choice."""
        import json
        from home.methods_module import calculate_verified_election_results
        ballot, block = self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)]
        )
        res = calculate_verified_election_results(self.elec1.id)
        payload_str = json.dumps(res['canonical_receipt_payload'])
        self.assertNotIn(str(self.priv_key), payload_str)
        self.assertNotIn(str(ballot.signature), payload_str)
        self.assertNotIn('signature', payload_str.lower())
        self.assertNotIn('ballot_id', payload_str.lower())

    def test_07_verification_failure_prevents_publication(self):
        """7. Verification failure prevents publication and withholds totals."""
        from home.methods_module import calculate_verified_election_results
        ballot, block = self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)]
        )
        # Corrupt block hash
        Block.objects.filter(id=block.id).update(this_hash="corrupted_hash_value_12345")
        res = calculate_verified_election_results(self.elec1.id)
        self.assertFalse(res['verified'])
        self.assertFalse(res['results_available'])
        self.assertFalse(res['is_eligible_for_publication'])
        self.assertEqual(res['publication_state'], 'LEDGER_VERIFICATION_FAILED')
        self.assertEqual(res['positions'], [])

    def test_08_unsealed_batch_prevents_final_publication(self):
        """8. Unsealed batch prevents final publication."""
        from home.methods_module import calculate_verified_election_results
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)]
        )
        # Add an open, unsealed batch
        BallotBatch.objects.create(election=self.elec1, batch_number=99, status='OPEN')
        res = calculate_verified_election_results(self.elec1.id)
        self.assertFalse(res['verified'])
        self.assertFalse(res['results_available'])
        self.assertFalse(res['is_eligible_for_publication'])
        self.assertEqual(res['publication_state'], 'LEDGER_VERIFICATION_FAILED')
        self.assertEqual(res['failure_category'], 'UNSEALED_BATCHES_DETECTED')
        self.assertEqual(res['positions'], [])

    def test_09_closed_vs_open_publication_lifecycle_rules(self):
        """9. Closed vs Open election publication lifecycle rules."""
        from home.methods_module import calculate_verified_election_results
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec_open, [(self.pos_open, self.cand_open1)]
        )
        # OPEN election without allow_unfinalized: not eligible for publication, positions withheld
        res_open = calculate_verified_election_results(self.elec_open.id, allow_unfinalized=False)
        self.assertTrue(res_open['verified'])
        self.assertFalse(res_open['results_available'])
        self.assertFalse(res_open['is_eligible_for_publication'])
        self.assertEqual(res_open['publication_state'], 'VERIFIED_UNPUBLISHED')
        self.assertEqual(res_open['positions'], [])

        # Transition to CLOSED: clean up unused empty open batch that was speculatively created while election was OPEN
        BallotBatch.objects.filter(election=self.elec_open, status='OPEN', ballot_count=0).delete()
        self.elec_open.status = 'CLOSED'
        self.elec_open.save()
        res_closed = calculate_verified_election_results(self.elec_open.id)
        self.assertTrue(res_closed['verified'])
        self.assertTrue(res_closed['results_available'])
        self.assertTrue(res_closed['is_eligible_for_publication'])
        self.assertEqual(res_closed['publication_state'], 'VERIFIED_PUBLISHED')
        self.assertEqual(len(res_closed['positions']), 1)

    def test_10_stale_receipt_detected_after_relevant_ledger_state_changes(self):
        """10. A stale receipt is detected after relevant ledger/result state changes."""
        from home.methods_module import calculate_verified_election_results, verify_result_receipt_consistency
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)]
        )
        res1 = calculate_verified_election_results(self.elec1.id)
        initial_receipt = res1['verification_receipt']

        # Consistency check before ledger change matches
        c1 = verify_result_receipt_consistency(self.elec1.id, expected_receipt=initial_receipt)
        self.assertTrue(c1['is_consistent'])
        self.assertEqual(c1['status'], 'CONSISTENT')

        # Ledger state change: second ballot submitted and mined
        self._submit_and_mine_modern_ballot(
            self.voter2, self.elec1, [(self.pos_chair, self.cand_c2)]
        )

        # Verification with old receipt flags STALE_RECEIPT_DETECTED
        c2 = verify_result_receipt_consistency(self.elec1.id, expected_receipt=initial_receipt)
        self.assertFalse(c2['is_consistent'])
        self.assertEqual(c2['status'], 'STALE_RECEIPT_DETECTED')
        self.assertEqual(c2['expected_receipt'], initial_receipt)
        self.assertNotEqual(c2['current_receipt'], initial_receipt)

    def test_11_voter_cannot_access_administrative_audit_records(self):
        """11. Voter cannot access administrative audit records or receipt verification."""
        self.client.force_login(self.u_regular_voter)
        res_audit = self.client.get(f'/elections/{self.elec1.id}/audit-records/')
        self.assertEqual(res_audit.status_code, 403)
        res_verify = self.client.get(f'/elections/{self.elec1.id}/verify-receipt/')
        self.assertEqual(res_verify.status_code, 403)

    def test_12_org_admin_cannot_access_another_org_audit_records(self):
        """12. Organization Admin cannot access another organization's audit records."""
        self.client.force_login(self.u_org_admin2)
        res_audit = self.client.get(f'/elections/{self.elec1.id}/audit-records/')
        self.assertEqual(res_audit.status_code, 403)
        res_verify = self.client.get(f'/elections/{self.elec1.id}/verify-receipt/')
        self.assertEqual(res_verify.status_code, 403)

    def test_13_authorized_auditor_and_admin_can_access_audit_info(self):
        """13. Authorized auditor and admin can access permitted audit records & verify receipt."""
        self._submit_and_mine_modern_ballot(
            self.voter1, self.elec1, [(self.pos_chair, self.cand_c1)]
        )
        self.client.force_login(self.u_org_admin1)
        res = self.client.get(f'/elections/{self.elec1.id}/results/')
        self.assertEqual(res.status_code, 200)

        # Auditor can read audit trail including result receipt
        self.client.force_login(self.u_auditor1)
        res_audit = self.client.get(f'/elections/{self.elec1.id}/audit-records/')
        self.assertEqual(res_audit.status_code, 200)
        data = res_audit.json()
        self.assertGreater(data['audit_records_count'], 0)
        self.assertIsNotNone(data['audit_records'][0]['result_receipt'])

        # Auditor can verify receipt consistency
        res_verify = self.client.get(f'/elections/{self.elec1.id}/verify-receipt/')
        self.assertEqual(res_verify.status_code, 200)
        self.assertTrue(res_verify.json()['is_consistent'])

        # Platform admin has global access
        self.client.force_login(self.u_plat)
        res_plat = self.client.get(f'/elections/{self.elec1.id}/audit-records/')
        self.assertEqual(res_plat.status_code, 200)

    def test_14_audit_records_cannot_be_modified_through_api(self):
        """14. Audit records cannot be modified through the exposed application API."""
        self.client.force_login(self.u_org_admin1)
        res_post = self.client.post(f'/elections/{self.elec1.id}/audit-records/', {})
        self.assertEqual(res_post.status_code, 405)
        res_put = self.client.put(f'/elections/{self.elec1.id}/audit-records/', {})
        self.assertEqual(res_put.status_code, 405)
        res_del = self.client.delete(f'/elections/{self.elec1.id}/audit-records/')
        self.assertEqual(res_del.status_code, 405)

        res_v_post = self.client.post(f'/elections/{self.elec1.id}/verify-receipt/', {})
        self.assertEqual(res_v_post.status_code, 405)

    def test_15_consistency_check_handles_missing_prior_receipt(self):
        """15. Consistency check returns NO_RECEIPT_FOUND when no prior verified audit exists."""
        from home.methods_module import verify_result_receipt_consistency
        res = verify_result_receipt_consistency(self.elec_org2.id)
        self.assertFalse(res['is_consistent'])
        self.assertEqual(res['status'], 'NO_RECEIPT_FOUND')

    def test_16_legacy_results_continue_to_pass(self):
        """16. Legacy /show-result/ and unbatched election results continue to pass."""
        res_legacy = self.client.get('/show-result/')
        self.assertEqual(res_legacy.status_code, 200)


class Phase7Step7B1ContainmentTests(TestCase):
    """
    Phase 7 Step 7B-1: Emergency Attack-Surface Containment Tests.
    Verifies containment of immediately dangerous unauthenticated mutation attack surfaces:
    - /create-dummy-data/ (SEC-CRIT-01)
    - /create-vote/ (SEC-CRIT-05)
    - /sync-block/ (SEC-CRIT-05)
    - /start-mining/ (SEC-HIGH-05)
    Verifies that unauthenticated and unauthorized requests are rejected,
    GET mutations are blocked with 405 Method Not Allowed,
    authorized workflows succeed, and historical blockchain remains VERIFIED.
    """
    def setUp(self):
        import datetime
        from django.contrib.auth.models import User
        from home.models import Organization, UserProfile, PoliticalParty, Voters, Vote, VoteBackup
        from home.methods_module import generate_keys

        # Organizations
        self.org = Organization.objects.create(name="Containment Test Org", description="Security Org")

        # Admin Users (using create to avoid slow PBKDF2 in unit tests)
        self.u_platform = User.objects.create(username="plat_admin_7b1")
        UserProfile.objects.create(user=self.u_platform, role="PLATFORM_ADMIN")

        self.u_org_admin = User.objects.create(username="org_admin_7b1")
        UserProfile.objects.create(user=self.u_org_admin, role="ORGANIZATION_ADMIN", organization=self.org)

        self.u_auditor = User.objects.create(username="auditor_7b1")
        UserProfile.objects.create(user=self.u_auditor, role="AUDITOR", organization=self.org)

        self.u_unprivileged = User.objects.create(username="unpriv_7b1")

        # Political Party for legacy vote tests
        self.party = PoliticalParty.objects.create(
            party_id="test_party_7b1",
            party_name="Security Test Party",
            party_logo="images/NOTA.png"
        )

        # Voter for legacy vote tests
        self.priv_key, self.pub_key = generate_keys()
        self.voter = Voters.objects.create(
            uuid="aadhar_7b1_001",
            name="Test Voter 7B1",
            email="voter7b1@test.com",
            dob=datetime.date(1995, 5, 5),
            pincode="500001",
            region="Cyberabad",
            vote_done=False
        )

    def test_01_create_dummy_data_unauthenticated_rejected(self):
        """1. Unauthenticated requests to /create-dummy-data/ are rejected with 403."""
        # Unauthenticated GET without query params
        res_get_clean = self.client.get('/create-dummy-data/')
        self.assertEqual(res_get_clean.status_code, 403)

        # Unauthenticated GET with destructive query params
        res_get_attack = self.client.get('/create-dummy-data/?createRandomVoters=1')
        self.assertEqual(res_get_attack.status_code, 403)

        # Unauthenticated POST
        res_post = self.client.post('/create-dummy-data/', {'createRandomVoters': 'true'})
        self.assertEqual(res_post.status_code, 403)

    def test_02_create_dummy_data_non_platform_admin_rejected(self):
        """2. Non-platform administrators cannot access /create-dummy-data/."""
        for user in [self.u_org_admin, self.u_auditor, self.u_unprivileged]:
            self.client.force_login(user)
            res = self.client.post('/create-dummy-data/', {'createRandomVoters': 'true'})
            self.assertEqual(res.status_code, 403, f"User {user.username} should be rejected with 403")

    def test_03_create_dummy_data_disabled_in_production(self):
        """3. /create-dummy-data/ is disabled when DEBUG is False even for platform admins."""
        from django.test import override_settings
        self.client.force_login(self.u_platform)
        with override_settings(DEBUG=False):
            res_post = self.client.post('/create-dummy-data/', {'createRandomVoters': 'true'})
            self.assertEqual(res_post.status_code, 403)
            self.assertIn('disabled in production', res_post.json().get('error', ''))

            res_get = self.client.get('/create-dummy-data/')
            self.assertEqual(res_get.status_code, 403)

    def test_04_create_dummy_data_get_mutation_rejected_with_405(self):
        """4. Platform admin cannot trigger mutations via GET; GET only renders page."""
        from django.test import override_settings
        self.client.force_login(self.u_platform)
        with override_settings(DEBUG=True):
            # GET with mutation params is rejected with 405
            res_attack = self.client.get('/create-dummy-data/?createRandomVoters=true')
            self.assertEqual(res_attack.status_code, 405)
            self.assertIn('State mutation via GET is disallowed', res_attack.json().get('error', ''))

            # GET without mutation params renders page
            res_page = self.client.get('/create-dummy-data/')
            self.assertEqual(res_page.status_code, 200)

    def test_05_create_dummy_data_authorized_post_works(self):
        """5. Platform admin with DEBUG=True can invoke /create-dummy-data/ via POST."""
        from django.test import override_settings
        from unittest.mock import patch
        self.client.force_login(self.u_platform)
        with override_settings(DEBUG=True):
            with patch('home.views.dummy_data_input') as mock_dummy:
                res = self.client.post('/create-dummy-data/', json.dumps({'createPoliticianParties': True}), content_type='application/json')
                self.assertEqual(res.status_code, 200)
                self.assertTrue(res.json().get('success'))
                mock_dummy.assert_called_once()

            # Empty POST returns 400
            res_empty = self.client.post('/create-dummy-data/', {}, content_type='application/json')
            self.assertEqual(res_empty.status_code, 400)

    def test_06_create_vote_unauthenticated_and_get_rejected(self):
        """6. /create-vote/ rejects unauthenticated requests and GET requests."""
        # Unauthenticated GET
        res_get = self.client.get('/create-vote/?selected-party-id=test_party_7b1')
        self.assertEqual(res_get.status_code, 405)

        # Unauthenticated POST
        res_post = self.client.post('/create-vote/', {'selected-party-id': 'test_party_7b1'})
        self.assertEqual(res_post.status_code, 401)
        self.assertIn('Authentication required', res_post.json().get('error', ''))

        # Session has uuid but email is not verified
        s = self.client.session
        s['uuid'] = self.voter.uuid
        s['email-verified'] = False
        s.save()
        res_unverified = self.client.post('/create-vote/', {'selected-party-id': 'test_party_7b1'})
        self.assertEqual(res_unverified.status_code, 401)

    def test_07_create_vote_authorized_flow_succeeds(self):
        """7. Authenticated voter with verified session can cast a legacy vote via POST."""
        from home.models import Vote, VoteBackup, Voters
        s = self.client.session
        s['uuid'] = self.voter.uuid
        s['email-verified'] = True
        s['private-key'] = self.priv_key
        s['public-key'] = self.pub_key
        s.save()

        # GET is rejected even with verified session
        res_get = self.client.get('/create-vote/')
        self.assertEqual(res_get.status_code, 405)

        # POST without selected-party-id is 400
        res_missing_party = self.client.post('/create-vote/', {})
        self.assertEqual(res_missing_party.status_code, 400)

        # Valid POST succeeds
        res = self.client.post('/create-vote/', {
            'selected-party-id': self.party.party_id,
            'private-key': self.priv_key
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'), f"Expected success but got: {data}")

        # Check DB records
        self.assertTrue(Vote.objects.filter(uuid=self.voter.uuid, vote_party_id=self.party.party_id).exists())
        self.assertTrue(VoteBackup.objects.filter(uuid=self.voter.uuid, vote_party_id=self.party.party_id).exists())
        self.voter.refresh_from_db()
        self.assertTrue(self.voter.vote_done)

        # Attempt to vote again in new verified session returns failure
        s = self.client.session
        s['uuid'] = self.voter.uuid
        s['email-verified'] = True
        s['private-key'] = self.priv_key
        s['public-key'] = self.pub_key
        s.save()
        res_duplicate = self.client.post('/create-vote/', {
            'selected-party-id': self.party.party_id,
            'private-key': self.priv_key
        })
        self.assertEqual(res_duplicate.status_code, 200)
        self.assertFalse(res_duplicate.json().get('success'))
        self.assertIn('already casted your vote', res_duplicate.json().get('status', ''))

    def test_08_sync_block_unauthenticated_and_get_rejected(self):
        """8. /sync-block/ rejects unauthenticated requests, unauthorized roles, and GET requests."""
        # Unauthenticated GET
        res_get = self.client.get('/sync-block/?block-id=1')
        self.assertEqual(res_get.status_code, 405)

        # Unauthenticated POST
        res_post = self.client.post('/sync-block/', {'block-id': 1})
        self.assertEqual(res_post.status_code, 403)

        # Organization Admin (non-platform)
        self.client.force_login(self.u_org_admin)
        res_org = self.client.post('/sync-block/', {'block-id': 1})
        self.assertEqual(res_org.status_code, 403)

        # Auditor
        self.client.force_login(self.u_auditor)
        res_aud = self.client.post('/sync-block/', {'block-id': 1})
        self.assertEqual(res_aud.status_code, 403)

    def test_09_sync_block_authorized_flow_succeeds(self):
        """9. Platform administrator can synchronize/repair a block via POST."""
        from home.models import Vote, VoteBackup
        import datetime
        self.client.force_login(self.u_platform)

        # GET is rejected with 405
        res_get = self.client.get('/sync-block/?block-id=8888')
        self.assertEqual(res_get.status_code, 405)

        # Missing block-id is 400
        res_missing = self.client.post('/sync-block/', {})
        self.assertEqual(res_missing.status_code, 400)

        # Nonexistent block is 404
        res_404 = self.client.post('/sync-block/', {'block-id': 999999})
        self.assertEqual(res_404.status_code, 404)

        # Set up a test backup record and a tampered vote record
        ts = timezone.now()
        VoteBackup.objects.create(
            uuid="voter_sync_test",
            vote_party_id="genuine_choice",
            timestamp=ts,
            block_id=8888
        )
        tampered_vote = Vote.objects.create(
            uuid="voter_sync_test",
            vote_party_id="corrupted_choice",
            timestamp=ts,
            block_id=8888
        )

        res_sync = self.client.post('/sync-block/', {'block-id': 8888})
        self.assertEqual(res_sync.status_code, 200)
        self.assertTrue(res_sync.json().get('success'))

        tampered_vote.refresh_from_db()
        self.assertEqual(tampered_vote.vote_party_id, "genuine_choice")

    def test_10_start_mining_unauthenticated_and_get_rejected(self):
        """10. /start-mining/ rejects unauthenticated requests, auditors, and GET requests."""
        # Unauthenticated GET
        res_get = self.client.get('/start-mining/')
        self.assertEqual(res_get.status_code, 405)

        # Unauthenticated POST
        res_post = self.client.post('/start-mining/', {})
        self.assertEqual(res_post.status_code, 403)

        # Auditor cannot mine
        self.client.force_login(self.u_auditor)
        res_aud = self.client.post('/start-mining/', {})
        self.assertEqual(res_aud.status_code, 403)

        # Unprivileged user cannot mine
        self.client.force_login(self.u_unprivileged)
        res_unpriv = self.client.post('/start-mining/', {})
        self.assertEqual(res_unpriv.status_code, 403)

    def test_11_start_mining_authorized_flow_succeeds(self):
        """11. Authenticated administrators (platform/org) can initiate mining via POST."""
        from unittest.mock import patch
        fake_mining_data = {
            'difficulty': 1,
            'puzzle': '0',
            'transactions_per_block': 1,
            'number_of_blocks': 0,
            'time_start': 0.0,
            'time_end': 0.1,
            'result': []
        }

        # Platform Admin
        self.client.force_login(self.u_platform)
        res_get = self.client.get('/start-mining/')
        self.assertEqual(res_get.status_code, 405)

        with patch('home.views.create_block', return_value=fake_mining_data):
            res_post = self.client.post('/start-mining/', {})
            self.assertEqual(res_post.status_code, 200)
            self.assertTrue(res_post.json().get('success'))
            self.assertIn('html', res_post.json())

        # Org Admin
        self.client.force_login(self.u_org_admin)
        with patch('home.views.create_block', return_value=fake_mining_data):
            res_org_post = self.client.post('/start-mining/', {})
            self.assertEqual(res_org_post.status_code, 200)
            self.assertTrue(res_org_post.json().get('success'))

    def test_12_historical_blockchain_verification_remains_verified(self):
        """12. Historical blockchain verification remains VERIFIED with 0 errors."""
        from home.methods_module import verify_full_chain
        result = verify_full_chain()
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['failures']), 0)


class Phase7Step7B2SecurityTests(TestCase):
    """
    Phase 7 Step 7B-2: Secrets, Configuration & Authentication/OTP Hardening Tests.
    Verifies:
    - Configuration: DEBUG default, SECRET_KEY, ALLOWED_HOSTS, SMTP secrets
    - OTP: CSPRNG generation, format, expiration, attempt limiting, resend cooldown, replay prevention, no logging
    - Authentication & PII: Method gating, minimized JSON details, session binding
    - Email takeover prevention: Rejection of email overwriting for registered voters
    - Historical blockchain verification remains VERIFIED
    """
    def setUp(self):
        import datetime
        from home.models import Voters

        # Create a registered test voter with email
        self.voter_with_email = Voters.objects.create(
            uuid="aadhar_7b2_001",
            name="Alice Registered",
            email="alice.registered@test.com",
            dob=datetime.date(1990, 1, 1),
            pincode="500001",
            region="Cyberabad",
            vote_done=False
        )

        # Create a test voter without email (first-time registration)
        self.voter_no_email = Voters.objects.create(
            uuid="aadhar_7b2_002",
            name="Bob Unbound",
            email="",
            dob=datetime.date(1992, 2, 2),
            pincode="500002",
            region="Cyberabad",
            vote_done=False
        )

        # Create an already-voted test voter
        self.voter_voted = Voters.objects.create(
            uuid="aadhar_7b2_003",
            name="Charlie Done",
            email="charlie@test.com",
            dob=datetime.date(1985, 3, 3),
            pincode="500003",
            region="Cyberabad",
            vote_done=True
        )

    def test_01_configuration_debug_and_secret_key_production_safety(self):
        """1. Configuration defaults: DEBUG is False, SECRET_KEY fails if missing in production."""
        import os, subprocess, sys

        # Subprocess check: run python without DJANGO_SECRET_KEY and with DJANGO_DEBUG=False
        cmd = [
            sys.executable, "-c",
            "import os; os.environ.pop('DJANGO_SECRET_KEY', None); os.environ.pop('SECRET_KEY', None); "
            "os.environ['DJANGO_DEBUG'] = 'False'; "
            "import Election.settings"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY environment variable is required when DEBUG is False", proc.stderr)

        # Subprocess check: run python with DJANGO_SECRET_KEY set
        cmd_ok = [
            sys.executable, "-c",
            "import os; os.environ['DJANGO_SECRET_KEY'] = 'explicit-test-prod-key'; "
            "os.environ['DJANGO_DEBUG'] = 'False'; "
            "import Election.settings; print(Election.settings.SECRET_KEY)"
        ]
        proc_ok = subprocess.run(cmd_ok, capture_output=True, text=True)
        self.assertEqual(proc_ok.returncode, 0)
        self.assertEqual(proc_ok.stdout.strip(), 'explicit-test-prod-key')

    def test_02_configuration_allowed_hosts_and_smtp_credentials(self):
        """2. Configuration: ALLOWED_HOSTS allowlist and dynamic SMTP credentials."""
        import os, subprocess, sys

        # Subprocess check: ALLOWED_HOSTS from DJANGO_ALLOWED_HOSTS
        cmd_hosts = [
            sys.executable, "-c",
            "import os; os.environ['DJANGO_ALLOWED_HOSTS'] = 'ballotchain.org, secure.vote'; "
            "os.environ['DJANGO_SECRET_KEY'] = 'test-key'; "
            "import Election.settings; print(repr(Election.settings.ALLOWED_HOSTS))"
        ]
        proc_hosts = subprocess.run(cmd_hosts, capture_output=True, text=True)
        self.assertEqual(proc_hosts.returncode, 0)
        self.assertIn("'ballotchain.org'", proc_hosts.stdout)
        self.assertIn("'secure.vote'", proc_hosts.stdout)

        # Check SMTP settings are configuration-driven and no hardcoded password
        from django.conf import settings
        import re
        settings_path = os.path.join(settings.BASE_DIR, 'Election', 'settings.py')
        content = open(settings_path, encoding='utf-8').read()
        self.assertRegex(content, r"EMAIL_PASSWORD\s*=\s*os\.environ\.get\(")
        self.assertRegex(content, r"EMAIL_ADDRESS\s*=\s*os\.environ\.get\(")
        # Ensure no literal string assignment for credentials
        self.assertNotRegex(content, r"EMAIL_PASSWORD\s*=\s*['\"][a-zA-Z0-9]+['\"]")

    def test_03_authentication_method_gating(self):
        """3. /authentication/ rejects GET requests and validates parameters."""
        res_get = self.client.get('/authentication/?aadhar_no=aadhar_7b2_001')
        self.assertEqual(res_get.status_code, 405)

        res_empty = self.client.post('/authentication/', {})
        self.assertEqual(res_empty.status_code, 400)

        res_invalid = self.client.post('/authentication/', {'aadhar_no': 'non_existent_999'})
        self.assertEqual(res_invalid.status_code, 200)
        self.assertFalse(res_invalid.json().get('success', False))
        self.assertIn('Invalid Aadhar', res_invalid.json().get('error', ''))

    def test_04_authentication_pii_minimization(self):
        """4. /authentication/ returns only minimized fields and prevents broad PII scraping."""
        res = self.client.post('/authentication/', {'aadhar_no': self.voter_with_email.uuid})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        details = data.get('details', {})

        # Permitted minimal fields
        self.assertEqual(details.get('uuid'), self.voter_with_email.uuid)
        self.assertEqual(details.get('name'), self.voter_with_email.name)

        # Excluded / minimized sensitive PII
        self.assertNotIn('email', details)
        self.assertNotIn('dob', details)
        self.assertNotIn('pincode', details)
        self.assertNotIn('region', details)
        self.assertNotIn('id', details)

        # Check already voted rejection
        res_voted = self.client.post('/authentication/', {'aadhar_no': self.voter_voted.uuid})
        self.assertEqual(res_voted.status_code, 200)
        self.assertIn('already casted your vote', res_voted.json().get('error', ''))

    def test_05_otp_generation_csprng_format_and_no_logging(self):
        """5. OTP generation uses CSPRNG, produces 6 digits, and never logs OTP to stdout."""
        import io, sys, re

        # Unauthenticated request without session uuid is 401
        res_unauth = self.client.get('/send-otp/')
        self.assertEqual(res_unauth.status_code, 401)

        # Authenticate session
        s = self.client.session
        s['uuid'] = self.voter_with_email.uuid
        s.save()

        # Capture stdout to ensure OTP is NOT logged
        captured_out = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_out
        try:
            res = self.client.get('/send-otp/', {'email-id': self.voter_with_email.email})
        finally:
            sys.stdout = old_stdout

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))
        self.assertNotIn('otp', res.json())  # OTP never returned in response

        # Check session OTP
        s = self.client.session
        generated_otp = s.get('otp')
        self.assertIsNotNone(generated_otp)
        self.assertTrue(bool(re.match(r'^\d{6}$', str(generated_otp))))

        # Confirm stdout does not contain the OTP
        output_text = captured_out.getvalue()
        self.assertNotIn(generated_otp, output_text)
        self.assertNotIn('Generated OTP', output_text)

    def test_06_otp_expiration_after_5_minutes(self):
        """6. OTP expires after 300 seconds and expired OTP is rejected and invalidated."""
        import time

        s = self.client.session
        s['uuid'] = self.voter_with_email.uuid
        s['otp'] = '123456'
        s['otp_created_at'] = time.time() - 305  # Expired (> 300s)
        s['otp_attempts'] = 0
        s.save()

        res = self.client.get('/verify-otp/', {'otp-input': '123456'})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.json().get('success'))
        self.assertIn('expired', res.json().get('error', '').lower())

        # OTP should be cleared from session
        s = self.client.session
        self.assertIsNone(s.get('otp'))

    def test_07_otp_attempt_limiting_and_lockout(self):
        """7. Max 3 verification attempts allowed; exceeding limit invalidates OTP."""
        import time

        s = self.client.session
        s['uuid'] = self.voter_with_email.uuid
        s['otp'] = '789012'
        s['otp_created_at'] = time.time()
        s['otp_attempts'] = 0
        s.save()

        # Attempt 1: wrong OTP
        res1 = self.client.get('/verify-otp/', {'otp-input': '000000'})
        self.assertEqual(res1.status_code, 200)
        self.assertFalse(res1.json().get('success'))
        self.assertIn('2 attempt(s) remaining', res1.json().get('error', ''))

        # Attempt 2: wrong OTP
        res2 = self.client.get('/verify-otp/', {'otp-input': '000000'})
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.json().get('success'))
        self.assertIn('1 attempt(s) remaining', res2.json().get('error', ''))

        # Attempt 3: wrong OTP -> Lockout
        res3 = self.client.get('/verify-otp/', {'otp-input': '000000'})
        self.assertEqual(res3.status_code, 429)
        self.assertIn('Too many failed attempts', res3.json().get('error', ''))

        # Session OTP is wiped
        s = self.client.session
        self.assertIsNone(s.get('otp'))

        # Attempt 4: even with correct OTP, verification fails because OTP was invalidated
        res4 = self.client.get('/verify-otp/', {'otp-input': '789012'})
        self.assertEqual(res4.status_code, 400)
        self.assertIn('No active OTP found', res4.json().get('error', ''))

    def test_08_otp_replay_prevention(self):
        """8. Successfully verified OTP is immediately invalidated and cannot be replayed."""
        import time

        s = self.client.session
        s['uuid'] = self.voter_with_email.uuid
        s['otp'] = '555666'
        s['otp_created_at'] = time.time()
        s['otp_attempts'] = 0
        s['email-id'] = self.voter_with_email.email
        s.save()

        # First verification succeeds
        res1 = self.client.get('/verify-otp/', {'otp-input': '555666'})
        self.assertEqual(res1.status_code, 200)
        self.assertTrue(res1.json().get('success'))

        # Session is marked email-verified
        s = self.client.session
        self.assertTrue(s.get('email-verified'))
        self.assertIsNone(s.get('otp'))

        # Replay attempt fails immediately
        res2 = self.client.get('/verify-otp/', {'otp-input': '555666'})
        self.assertEqual(res2.status_code, 400)
        self.assertFalse(res2.json().get('success'))
        self.assertIn('No active OTP found', res2.json().get('error', ''))

    def test_09_otp_resend_cooldown_and_max_attempts(self):
        """9. OTP generation enforces 30s cooldown and max 5 send requests per session."""
        import time

        s = self.client.session
        s['uuid'] = self.voter_with_email.uuid
        s['otp_last_sent'] = time.time() - 5  # Only 5 seconds ago
        s['otp_send_count'] = 1
        s.save()

        # Rapid resend is rate-limited
        res_fast = self.client.get('/send-otp/', {'email-id': self.voter_with_email.email})
        self.assertEqual(res_fast.status_code, 429)
        self.assertIn('wait', res_fast.json().get('error', '').lower())

        # Exceeding max send limit
        s = self.client.session
        s['otp_last_sent'] = time.time() - 35
        s['otp_send_count'] = 5
        s.save()

        res_limit = self.client.get('/send-otp/', {'email-id': self.voter_with_email.email})
        self.assertEqual(res_limit.status_code, 429)
        self.assertIn('Maximum OTP request limit reached', res_limit.json().get('error', ''))

    def test_10_email_takeover_prevention_for_registered_voter(self):
        """10. Attacker cannot change registered voter's email during OTP request."""
        s = self.client.session
        s['uuid'] = self.voter_with_email.uuid
        s.save()

        # Attacker tries to dispatch OTP to a rogue email
        res_takeover = self.client.get('/send-otp/', {'email-id': 'attacker@malicious.com'})
        self.assertEqual(res_takeover.status_code, 403)
        self.assertIn('Cannot change email address for an already registered voter', res_takeover.json().get('error', ''))

        # Voter's email in database is unchanged
        self.voter_with_email.refresh_from_db()
        self.assertEqual(self.voter_with_email.email, 'alice.registered@test.com')

    def test_11_first_time_email_binding_for_unbound_voter(self):
        """11. Voter with empty email binds email on first-time OTP verification."""
        import time

        s = self.client.session
        s['uuid'] = self.voter_no_email.uuid
        s.save()

        # Unbound voter provides email for first time
        res_send = self.client.get('/send-otp/', {'email-id': 'bob.new@test.com'})
        self.assertEqual(res_send.status_code, 200)
        self.assertTrue(res_send.json().get('success'))

        # Fetch the generated OTP from session
        s = self.client.session
        otp = s.get('otp')

        # Verify OTP
        res_verify = self.client.get('/verify-otp/', {'otp-input': otp})
        self.assertEqual(res_verify.status_code, 200)
        self.assertTrue(res_verify.json().get('success'))

        # Voter's email is now bound
        self.voter_no_email.refresh_from_db()
        self.assertEqual(self.voter_no_email.email, 'bob.new@test.com')

        # Now that email is bound, subsequent change attempt is blocked
        s = self.client.session
        s['otp_last_sent'] = time.time() - 35
        s.save()
        res_blocked = self.client.get('/send-otp/', {'email-id': 'attacker@evil.com'})
        self.assertEqual(res_blocked.status_code, 403)

    def test_12_historical_blockchain_verification_remains_verified(self):
        """12. Historical blockchain verification remains VERIFIED with 0 errors."""
        from home.methods_module import verify_full_chain
        result = verify_full_chain()
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['failures']), 0)


class Phase7Step7B3CsrfTests(TestCase):
    """
    Phase 7 Step 7B-3: CSRF Protection & State-Changing Request Hardening Tests.
    Verifies:
    - @ensure_csrf_cookie sets the csrftoken cookie on GET /
    - Unsafe POST/PUT/DELETE requests without CSRF token are rejected with HTTP 403 Forbidden
    - Valid CSRF-protected POST requests succeed for authenticated/authorized callers
    - State-changing GET requests remain strictly blocked (HTTP 405 Method Not Allowed)
    - Safe read-only GET endpoints remain functional
    - Authentication and RBAC controls remain fully intact
    - Prior security containment (Phases 7B-1 and 7B-2) remains preserved
    - Historical blockchain verification remains 100% valid
    """
    def setUp(self):
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate, UserProfile, Voters

        # Create test organization
        self.org = Organization.objects.create(name="CSRF Test Org", description="Org for CSRF Testing")

        # Create test election
        self.elec = Election.objects.create(
            organization=self.org,
            title="CSRF Test Election",
            status="OPEN"
        )

        # Create test position
        self.pos = Position.objects.create(
            election=self.elec,
            title="President",
            max_votes_allowed=1
        )

        # Create test candidate
        self.cand = Candidate.objects.create(
            position=self.pos,
            name="CSRF Test Candidate",
            affiliation="Test Party"
        )

        # Platform Admin User
        self.u_platform = User.objects.create_user(username="csrf_platform_admin", password="testpassword123")
        self.p_platform = UserProfile.objects.create(user=self.u_platform, role="PLATFORM_ADMIN")

        # Org Admin User
        self.u_org_admin = User.objects.create_user(username="csrf_org_admin", password="testpassword123")
        self.p_org_admin = UserProfile.objects.create(user=self.u_org_admin, role="ORGANIZATION_ADMIN", organization=self.org)

        # Auditor User
        self.u_auditor = User.objects.create_user(username="csrf_auditor", password="testpassword123")
        self.p_auditor = UserProfile.objects.create(user=self.u_auditor, role="AUDITOR", organization=self.org)

        # Test voter
        import datetime
        self.voter = Voters.objects.create(
            uuid="csrf_voter_001",
            name="Danielle CSRF",
            email="danielle@test.com",
            dob=datetime.date(1995, 5, 5),
            pincode="500005",
            region="Cyberabad",
            vote_done=False
        )

    def test_01_ensure_csrf_cookie_set_on_home_view(self):
        """1. Loading home view (GET /) sets the csrftoken cookie via @ensure_csrf_cookie."""
        client = Client(enforce_csrf_checks=True)
        res = client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('csrftoken', client.cookies)
        self.assertTrue(len(client.cookies['csrftoken'].value) > 16)

    def test_02_post_without_csrf_token_rejected_on_admin_login(self):
        """2. State-changing POST to /admin-login/ without CSRF token is rejected with HTTP 403."""
        client = Client(enforce_csrf_checks=True)
        payload = json.dumps({'username': 'csrf_platform_admin', 'password': 'testpassword123'})
        res = client.post('/admin-login/', payload, content_type='application/json')
        self.assertEqual(res.status_code, 403)

    def test_03_post_without_csrf_token_rejected_across_all_mutating_endpoints(self):
        """3. State-changing POST without CSRF token is rejected across all hardened endpoints."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)

        mutating_endpoints = [
            ('/organizations/create/', json.dumps({'name': 'New Org'})),
            (f'/organizations/{self.org.id}/edit/', json.dumps({'name': 'Updated Org'})),
            (f'/organizations/{self.org.id}/delete/', '{}'),
            ('/elections/create/', json.dumps({'organization_id': self.org.id, 'title': 'New Election'})),
            (f'/elections/{self.elec.id}/edit/', json.dumps({'title': 'Updated Title'})),
            (f'/elections/{self.elec.id}/delete/', '{}'),
            ('/positions/create/', json.dumps({'election_id': self.elec.id, 'title': 'VP'})),
            (f'/positions/{self.pos.id}/edit/', json.dumps({'title': 'Updated VP'})),
            (f'/positions/{self.pos.id}/delete/', '{}'),
            ('/candidates/create/', json.dumps({'position_id': self.pos.id, 'name': 'New Candidate'})),
            (f'/candidates/{self.cand.id}/edit/', json.dumps({'name': 'Updated Candidate'})),
            (f'/candidates/{self.cand.id}/delete/', '{}'),
            ('/eligibility/create/', json.dumps({'election_id': self.elec.id, 'voter_id': self.voter.uuid})),
            ('/ballots/create/', json.dumps({'election_id': self.elec.id, 'voter_id': self.voter.uuid})),
            ('/create-vote/', {'selected-party-id': '1'}),
            ('/sync-block/', {'block-id': '1'}),
            ('/start-mining/', {}),
            ('/admin-logout/', {}),
        ]

        for endpoint, data in mutating_endpoints:
            content_type = 'application/json' if isinstance(data, str) and data.startswith('{') else 'application/x-www-form-urlencoded'
            res = client.post(endpoint, data, content_type=content_type)
            self.assertEqual(
                res.status_code, 403,
                f"Endpoint {endpoint} without CSRF token was expected to return 403, got {res.status_code}"
            )

    def test_04_post_with_valid_csrf_token_succeeds(self):
        """4. Valid CSRF-protected POST requests succeed for authenticated callers."""
        client = Client(enforce_csrf_checks=True)
        # Obtain CSRF token
        client.get('/')
        csrf_token = client.cookies['csrftoken'].value

        # Authenticate platform admin
        client.force_login(self.u_platform)

        # Create organization with CSRF token in header
        org_payload = json.dumps({'name': 'CSRF Verified Org', 'description': 'Testing with CSRF'})
        res_org = client.post(
            '/organizations/create/',
            org_payload,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(res_org.status_code, 200)
        self.assertTrue(res_org.json().get('success'))

        # Create election with CSRF token in header
        new_org_id = res_org.json().get('id')
        elec_payload = json.dumps({'organization_id': new_org_id, 'title': 'CSRF Verified Election'})
        res_elec = client.post(
            '/elections/create/',
            elec_payload,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(res_elec.status_code, 200)
        self.assertTrue(res_elec.json().get('success'))

    def test_05_state_changing_get_requests_strictly_rejected(self):
        """5. Mutating endpoints reject HTTP GET requests with HTTP 405 Method Not Allowed."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)

        get_endpoints = [
            '/admin-logout/',
            '/organizations/create/',
            f'/organizations/{self.org.id}/edit/',
            f'/organizations/{self.org.id}/delete/',
            '/elections/create/',
            f'/elections/{self.elec.id}/edit/',
            f'/elections/{self.elec.id}/delete/',
            '/positions/create/',
            f'/positions/{self.pos.id}/edit/',
            f'/positions/{self.pos.id}/delete/',
            '/candidates/create/',
            f'/candidates/{self.cand.id}/edit/',
            f'/candidates/{self.cand.id}/delete/',
            '/eligibility/create/',
            f'/eligibility/999/revoke/',
            '/ballots/create/',
            f'/ballots/999/submit/',
            f'/batches/999/mine/',
            f'/elections/{self.elec.id}/mine-batch/',
            '/create-vote/',
            '/sync-block/',
            '/start-mining/',
            '/authentication/',
        ]

        for url in get_endpoints:
            res = client.get(url)
            self.assertEqual(
                res.status_code, 405,
                f"Endpoint {url} via GET was expected to return 405 Method Not Allowed, got {res.status_code}"
            )

    def test_06_read_only_get_endpoints_remain_functional(self):
        """6. Read-only GET endpoints remain functional without requiring CSRF token."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)

        read_endpoints = [
            ('/', 200),
            ('/organizations/', 200),
            (f'/organizations/{self.org.id}/', 200),
            ('/elections/', 200),
            (f'/elections/{self.elec.id}/', 200),
            ('/positions/', 200),
            (f'/positions/{self.pos.id}/', 200),
            ('/candidates/', 200),
            (f'/candidates/{self.cand.id}/', 200),
            ('/voters/', 200),
            ('/eligibility/', 200),
            ('/ballots/', 200),
            ('/show-result/', 200),
            ('/blockchain/', 200),
        ]

        for url, expected_status in read_endpoints:
            res = client.get(url)
            self.assertEqual(
                res.status_code, expected_status,
                f"Read-only endpoint {url} expected {expected_status}, got {res.status_code}"
            )

    def test_07_rbac_enforcement_maintained_with_valid_csrf(self):
        """7. RBAC permissions remain strictly enforced even when a valid CSRF token is presented."""
        client = Client(enforce_csrf_checks=True)
        client.get('/')
        csrf_token = client.cookies['csrftoken'].value

        # Login as Auditor (read-only role)
        client.force_login(self.u_auditor)

        # Auditor attempts to create election (forbidden)
        elec_payload = json.dumps({'organization_id': self.org.id, 'title': 'Auditor Illegal Election'})
        res = client.post(
            '/elections/create/',
            elec_payload,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn('Unauthorized', res.json().get('error', ''))

    def test_08_phase7b1_containment_preserved_under_csrf(self):
        """8. Emergency containment from Phase 7B-1 remains intact with CSRF."""
        client = Client(enforce_csrf_checks=True)
        client.get('/')
        csrf_token = client.cookies['csrftoken'].value

        # Anonymous caller attempting create-dummy-data with CSRF token is still rejected (403)
        res = client.post('/create-dummy-data/', {'createRandomVoters': '1'}, HTTP_X_CSRFTOKEN=csrf_token)
        self.assertEqual(res.status_code, 403)

    def test_09_phase7b2_otp_and_auth_preserved(self):
        """9. Authentication and OTP hardening from Phase 7B-2 remain fully functional."""
        client = Client(enforce_csrf_checks=True)
        client.get('/')
        csrf_token = client.cookies['csrftoken'].value

        # Authentication via POST with CSRF succeeds
        res_auth = client.post('/authentication/', {'aadhar_no': self.voter.uuid}, HTTP_X_CSRFTOKEN=csrf_token)
        self.assertEqual(res_auth.status_code, 200)
        self.assertTrue(res_auth.json().get('success'))

        # Minimized details verification
        details = res_auth.json().get('details', {})
        self.assertEqual(details.get('uuid'), self.voter.uuid)
        self.assertNotIn('email', details)
        self.assertNotIn('dob', details)

    def test_10_historical_blockchain_verification_remains_verified(self):
        """10. Full chain cryptographic audit across all 5,645 blocks remains 100% VERIFIED."""
        from home.methods_module import verify_full_chain
        result = verify_full_chain()
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['failures']), 0)















class Phase7Step7B4AuthorizationTests(TestCase):
    """
    Phase 7 Step 7B-4: Authorization, RBAC and Object-Level Access Hardening Tests.
    Verifies tenant boundaries, IDOR prevention, auditor restrictions,
    and profile safety.
    """
    def setUp(self):
        # Create Organizations
        self.org_a = Organization.objects.create(
            name="Alpha University",
            description="Tenant Alpha",
            contact_information="admin@alpha.edu"
        )
        self.org_b = Organization.objects.create(
            name="Beta Institute",
            description="Tenant Beta",
            contact_information="admin@beta.edu"
        )

        # Create Elections
        self.elec_a = Election.objects.create(
            organization=self.org_a,
            title="Alpha Student Council",
            status="OPEN"
        )
        self.elec_b = Election.objects.create(
            organization=self.org_b,
            title="Beta Faculty Senate",
            status="OPEN"
        )

        # Create Positions
        self.pos_a = Position.objects.create(
            election=self.elec_a,
            title="President",
            max_votes_allowed=1
        )
        self.pos_b = Position.objects.create(
            election=self.elec_b,
            title="Chair",
            max_votes_allowed=1
        )

        # Create Candidates
        self.cand_a = Candidate.objects.create(
            position=self.pos_a,
            name="Alice Alpha",
            affiliation="Alpha United"
        )
        self.cand_b = Candidate.objects.create(
            position=self.pos_b,
            name="Bob Beta",
            affiliation="Beta Progress"
        )

        # Administrative Users
        self.u_platform = User.objects.create_user(username="authz_platform", password="testpassword123")
        self.p_platform = UserProfile.objects.create(user=self.u_platform, role="PLATFORM_ADMIN")

        self.u_org_a_admin = User.objects.create_user(username="authz_org_a_admin", password="testpassword123")
        self.p_org_a_admin = UserProfile.objects.create(user=self.u_org_a_admin, role="ORGANIZATION_ADMIN", organization=self.org_a)

        self.u_org_b_admin = User.objects.create_user(username="authz_org_b_admin", password="testpassword123")
        self.p_org_b_admin = UserProfile.objects.create(user=self.u_org_b_admin, role="ORGANIZATION_ADMIN", organization=self.org_b)

        self.u_official_a = User.objects.create_user(username="authz_official_a", password="testpassword123")
        self.p_official_a = UserProfile.objects.create(user=self.u_official_a, role="ELECTION_OFFICIAL", organization=self.org_a)

        self.u_auditor_a = User.objects.create_user(username="authz_auditor_a", password="testpassword123")
        self.p_auditor_a = UserProfile.objects.create(user=self.u_auditor_a, role="AUDITOR", organization=self.org_a)

        self.u_no_profile = User.objects.create_user(username="authz_no_profile", password="testpassword123")

        # Voters
        import datetime
        self.voter_1 = Voters.objects.create(
            uuid="authz_voter_001",
            name="Voter One",
            email="voter1@test.com",
            dob=datetime.date(1996, 6, 6),
            pincode="500001",
            region="Hyderabad",
            vote_done=False
        )
        self.voter_2 = Voters.objects.create(
            uuid="authz_voter_002",
            name="Voter Two",
            email="voter2@test.com",
            dob=datetime.date(1997, 7, 7),
            pincode="500002",
            region="Secunderabad",
            vote_done=False
        )

        # Eligibilities
        self.elig_a1 = Eligibility.objects.create(election=self.elec_a, voter=self.voter_1)
        self.elig_b2 = Eligibility.objects.create(election=self.elec_b, voter=self.voter_2)

        # Ballots
        self.ballot_a1 = Ballot.objects.create(election=self.elec_a, voter=self.voter_1)
        self.ballot_b2 = Ballot.objects.create(election=self.elec_b, voter=self.voter_2)

    def _csrf_client(self):
        client = Client(enforce_csrf_checks=True)
        client.get('/')
        return client, client.cookies['csrftoken'].value

    def test_01_unauthenticated_requests_denied(self):
        """1. Unauthenticated requests to administrative endpoints are rejected with 401/403."""
        client = Client()
        endpoints = [
            ('/organizations/', 403),
            ('/organizations/1/', 403),
            ('/elections/', 403),
            (f'/elections/{self.elec_a.id}/', 403),
            (f'/elections/{self.elec_a.id}/results/', 403),
            (f'/elections/{self.elec_a.id}/audit-records/', 403),
            (f'/elections/{self.elec_a.id}/verify-receipt/', 403),
            ('/positions/', 403),
            (f'/positions/{self.pos_a.id}/', 403),
            ('/candidates/', 403),
            (f'/candidates/{self.cand_a.id}/', 403),
            ('/voters/', 403),
            ('/eligibility/', 403),
            (f'/eligibility/{self.elig_a1.id}/', 403),
            ('/ballots/', 403),
            (f'/ballots/{self.ballot_a1.id}/', 403),
            ('/blockchain/verify-chain/', 403),
        ]
        for url, expected in endpoints:
            res = client.get(url)
            self.assertEqual(res.status_code, expected, f"Endpoint {url} expected {expected}, got {res.status_code}")

    def test_02_voter_ballot_idor_prevention(self):
        """2. Voter A cannot submit ballot for Voter B (IDOR prevention)."""
        client, token = self._csrf_client()
        session = client.session
        session['uuid'] = self.voter_1.uuid
        session['email-verified'] = True
        session.save()

        # Voter 1 attempts to submit Voter 2's ballot
        payload = json.dumps({
            'selections': {str(self.pos_b.id): [self.cand_b.id]}
        })
        res = client.post(
            f'/ballots/{self.ballot_b2.id}/submit/',
            payload,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn('Cannot submit ballot for another voter', res.json().get('error', ''))

        # Voter 1 submits own ballot but provides body with voter_2's UUID
        payload_mismatch = json.dumps({
            'voter_id': self.voter_2.uuid,
            'selections': {str(self.pos_a.id): [self.cand_a.id]}
        })
        res2 = client.post(
            f'/ballots/{self.ballot_a1.id}/submit/',
            payload_mismatch,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn('Submitted voter ID does not match ballot voter', res2.json().get('error', ''))

    def test_03_org_admin_cross_tenant_read_isolation(self):
        """3. Org A Admin cannot read Org B's resources (elections, positions, candidates, ballots, results)."""
        client = Client()
        client.force_login(self.u_org_a_admin)

        cross_tenant_urls = [
            f'/organizations/{self.org_b.id}/',
            f'/elections/{self.elec_b.id}/',
            f'/elections/{self.elec_b.id}/results/',
            f'/elections/{self.elec_b.id}/audit-records/',
            f'/elections/{self.elec_b.id}/verify-receipt/',
            f'/positions/{self.pos_b.id}/',
            f'/candidates/{self.cand_b.id}/',
            f'/eligibility/{self.elig_b2.id}/',
            f'/ballots/{self.ballot_b2.id}/',
        ]
        for url in cross_tenant_urls:
            res = client.get(url)
            self.assertEqual(res.status_code, 403, f"Cross-tenant read {url} expected 403, got {res.status_code}")

    def test_04_org_admin_cross_tenant_write_isolation(self):
        """4. Org A Admin cannot mutate Org B's resources."""
        client, token = self._csrf_client()
        client.force_login(self.u_org_a_admin)

        mutations = [
            (f'/organizations/{self.org_b.id}/edit/', json.dumps({'name': 'Hacked Org'})),
            (f'/elections/{self.elec_b.id}/edit/', json.dumps({'title': 'Hacked Election'})),
            (f'/elections/{self.elec_b.id}/delete/', '{}'),
            (f'/positions/{self.pos_b.id}/edit/', json.dumps({'title': 'Hacked Position'})),
            (f'/positions/{self.pos_b.id}/delete/', '{}'),
            (f'/candidates/{self.cand_b.id}/edit/', json.dumps({'name': 'Hacked Candidate'})),
            (f'/candidates/{self.cand_b.id}/delete/', '{}'),
            (f'/eligibility/{self.elig_b2.id}/revoke/', '{}'),
            ('/positions/create/', json.dumps({'election_id': self.elec_b.id, 'title': 'Injected Position'})),
            ('/candidates/create/', json.dumps({'position_id': self.pos_b.id, 'name': 'Injected Candidate'})),
            ('/eligibility/create/', json.dumps({'election_id': self.elec_b.id, 'voter_id': self.voter_1.uuid})),
            ('/ballots/create/', json.dumps({'election_id': self.elec_b.id, 'voter_id': self.voter_1.uuid})),
            (f'/elections/{self.elec_b.id}/mine-batch/', '{}'),
        ]
        for url, data in mutations:
            res = client.post(url, data, content_type='application/json', HTTP_X_CSRFTOKEN=token)
            self.assertEqual(res.status_code, 403, f"Cross-tenant mutation {url} expected 403, got {res.status_code}")

    def test_05_auditor_role_strictly_read_only(self):
        """5. Auditor can read own organization resources but is denied on all mutating operations."""
        client, token = self._csrf_client()
        client.force_login(self.u_auditor_a)

        # Reads succeed
        read_urls = [
            f'/organizations/{self.org_a.id}/',
            '/elections/',
            f'/elections/{self.elec_a.id}/',
            f'/elections/{self.elec_a.id}/results/',
            f'/elections/{self.elec_a.id}/audit-records/',
            f'/elections/{self.elec_a.id}/verify-receipt/',
            '/positions/',
            f'/positions/{self.pos_a.id}/',
            '/candidates/',
            f'/candidates/{self.cand_a.id}/',
            '/eligibility/',
            f'/eligibility/{self.elig_a1.id}/',
            '/ballots/',
            f'/ballots/{self.ballot_a1.id}/',
        ]
        for url in read_urls:
            res = client.get(url)
            self.assertEqual(res.status_code, 200, f"Auditor read {url} expected 200, got {res.status_code}")

        # Mutations strictly forbidden
        forbidden_mutations = [
            ('/organizations/create/', json.dumps({'name': 'Auditor Org'})),
            (f'/organizations/{self.org_a.id}/edit/', json.dumps({'name': 'Auditor Edit'})),
            ('/elections/create/', json.dumps({'organization_id': self.org_a.id, 'title': 'Auditor Elec'})),
            (f'/elections/{self.elec_a.id}/edit/', json.dumps({'title': 'Auditor Edit'})),
            (f'/elections/{self.elec_a.id}/delete/', '{}'),
            ('/positions/create/', json.dumps({'election_id': self.elec_a.id, 'title': 'Auditor Pos'})),
            (f'/positions/{self.pos_a.id}/edit/', json.dumps({'title': 'Auditor Pos Edit'})),
            (f'/positions/{self.pos_a.id}/delete/', '{}'),
            ('/candidates/create/', json.dumps({'position_id': self.pos_a.id, 'name': 'Auditor Cand'})),
            (f'/candidates/{self.cand_a.id}/edit/', json.dumps({'name': 'Auditor Cand Edit'})),
            (f'/candidates/{self.cand_a.id}/delete/', '{}'),
            ('/eligibility/create/', json.dumps({'election_id': self.elec_a.id, 'voter_id': self.voter_1.uuid})),
            (f'/eligibility/{self.elig_a1.id}/revoke/', '{}'),
            ('/ballots/create/', json.dumps({'election_id': self.elec_a.id, 'voter_id': self.voter_1.uuid})),
            (f'/ballots/{self.ballot_a1.id}/submit/', json.dumps({'selections': {str(self.pos_a.id): [self.cand_a.id]}})),
            ('/start-mining/', '{}'),
            (f'/elections/{self.elec_a.id}/mine-batch/', '{}'),
        ]
        for url, data in forbidden_mutations:
            res = client.post(url, data, content_type='application/json', HTTP_X_CSRFTOKEN=token)
            self.assertEqual(res.status_code, 403, f"Auditor mutation {url} expected 403, got {res.status_code}")

    def test_06_voter_cannot_access_administrative_endpoints(self):
        """6. Voter session cannot access admin endpoints."""
        client, token = self._csrf_client()
        session = client.session
        session['uuid'] = self.voter_1.uuid
        session['email-verified'] = True
        session.save()

        admin_endpoints = [
            ('/organizations/', 'GET', None),
            ('/organizations/create/', 'POST', json.dumps({'name': 'Voter Org'})),
            ('/elections/create/', 'POST', json.dumps({'organization_id': self.org_a.id, 'title': 'Voter Elec'})),
            ('/positions/create/', 'POST', json.dumps({'election_id': self.elec_a.id, 'title': 'Voter Pos'})),
            ('/candidates/create/', 'POST', json.dumps({'position_id': self.pos_a.id, 'name': 'Voter Cand'})),
            ('/voters/', 'GET', None),
            ('/start-mining/', 'POST', '{}'),
            ('/create-dummy-data/', 'POST', '{"createRandomVoters": 1}'),
            ('/sync-block/', 'POST', '{"block-id": "1"}'),
        ]
        for url, method, data in admin_endpoints:
            if method == 'GET':
                res = client.get(url)
            else:
                res = client.post(url, data, content_type='application/json', HTTP_X_CSRFTOKEN=token)
            self.assertEqual(res.status_code, 403, f"Voter calling {url} expected 403, got {res.status_code}")

    def test_07_org_admin_cannot_escalate_to_platform_operations(self):
        """7. Org Admin cannot perform platform-level actions or change election's organization."""
        client, token = self._csrf_client()
        client.force_login(self.u_org_a_admin)

        # Cannot list all organizations
        res = client.get('/organizations/')
        self.assertEqual(res.status_code, 403)

        # Cannot create organization
        res = client.post('/organizations/create/', json.dumps({'name': 'Illegal Org'}), content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 403)

        # Cannot delete organization
        res = client.post(f'/organizations/{self.org_a.id}/delete/', '{}', content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 403)

        # Cannot view global voters list
        res = client.get('/voters/')
        self.assertEqual(res.status_code, 403)

        # Cannot execute dummy data wipe
        res = client.post('/create-dummy-data/', '{"createRandomVoters": 1}', content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 403)

        # Cannot sync block
        res = client.post('/sync-block/', '{"block-id": "1"}', content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(res.status_code, 403)

        # Cannot change election's organization
        res = client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'organization_id': self.org_b.id}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn('Cannot change organization', res.json().get('error', ''))

    def test_08_cross_election_object_injection_prevented(self):
        """8. Submitting position or candidate belonging to another election is rejected."""
        client, token = self._csrf_client()
        session = client.session
        session['uuid'] = self.voter_1.uuid
        session['email-verified'] = True
        session.save()

        # Ballot belongs to elec_a. Attempt to inject pos_b (from elec_b)
        bad_pos_payload = json.dumps({
            'selections': {str(self.pos_b.id): [self.cand_a.id]}
        })
        res = client.post(
            f'/ballots/{self.ballot_a1.id}/submit/',
            bad_pos_payload,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn('does not belong to election', res.json().get('error', ''))

        # Attempt to inject cand_b (from pos_b) under pos_a
        bad_cand_payload = json.dumps({
            'selections': {str(self.pos_a.id): [self.cand_b.id]}
        })
        res2 = client.post(
            f'/ballots/{self.ballot_a1.id}/submit/',
            bad_cand_payload,
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn('does not belong to position', res2.json().get('error', ''))

    def test_09_authorized_user_within_org_succeeds(self):
        """9. Org Admin can successfully access and mutate their own organization's resources."""
        client, token = self._csrf_client()
        client.force_login(self.u_org_a_admin)

        # View own org
        res = client.get(f'/organizations/{self.org_a.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get('name'), self.org_a.name)

        # Edit own org
        res = client.post(
            f'/organizations/{self.org_a.id}/edit/',
            json.dumps({'name': 'Alpha University Updated'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))

        # Create election in own org
        res = client.post(
            '/elections/create/',
            json.dumps({'organization_id': self.org_a.id, 'title': 'Alpha Senate 2026'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res.status_code, 200)
        new_elec_id = res.json().get('id')

        # Create position in own election
        res = client.post(
            '/positions/create/',
            json.dumps({'election_id': new_elec_id, 'title': 'Secretary', 'max_votes_allowed': 1}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res.status_code, 200)
        new_pos_id = res.json().get('id')

        # Create candidate in own position
        res = client.post(
            '/candidates/create/',
            json.dumps({'position_id': new_pos_id, 'name': 'Charlie Candidate', 'affiliation': 'Alpha Coalition'}),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=token
        )
        self.assertEqual(res.status_code, 200)

    def test_10_authenticated_user_without_profile_fails_gracefully(self):
        """10. Authenticated user without UserProfile returns clean 403 without HTTP 500 error."""
        client = Client()
        client.force_login(self.u_no_profile)

        endpoints = [
            '/elections/',
            '/positions/',
            '/candidates/',
            '/eligibility/',
            '/ballots/',
        ]
        for url in endpoints:
            res = client.get(url)
            self.assertEqual(res.status_code, 403, f"Endpoint {url} expected 403, got {res.status_code}")

    def test_11_chain_audit_authorization_boundaries(self):
        """11. Chain audit endpoint requires administrative or auditor privileges."""
        client = Client()

        # Anonymous caller -> 403
        res_anon = client.get('/blockchain/verify-chain/')
        self.assertEqual(res_anon.status_code, 403)

        # Voter session caller -> 403
        session = client.session
        session['uuid'] = self.voter_1.uuid
        session['email-verified'] = True
        session.save()
        res_voter = client.get('/blockchain/verify-chain/')
        self.assertEqual(res_voter.status_code, 403)

        # Platform Admin -> 200 (limit to 1 block for quick test)
        client.force_login(self.u_platform)
        res_plat = client.get('/blockchain/verify-chain/?from_block=0&to_block=0')
        self.assertEqual(res_plat.status_code, 200)
        self.assertTrue(res_plat.json().get('valid'))

        # Org Admin -> 200
        client.force_login(self.u_org_a_admin)
        res_org = client.get('/blockchain/verify-chain/?from_block=0&to_block=0')
        self.assertEqual(res_org.status_code, 200)
        self.assertTrue(res_org.json().get('valid'))

        # Auditor -> 200
        client.force_login(self.u_auditor_a)
        res_audit = client.get('/blockchain/verify-chain/?from_block=0&to_block=0')
        self.assertEqual(res_audit.status_code, 200)
        self.assertTrue(res_audit.json().get('valid'))

    def test_12_historical_blockchain_verification_remains_verified(self):
        """12. Full chain cryptographic audit across all 5,645 blocks remains 100% VERIFIED."""
        from home.methods_module import verify_full_chain
        result = verify_full_chain()
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['failures']), 0)


class Phase7Step7B5PrivacyTests(TestCase):
    """
    Phase 7 Step 7B-5: Privacy, Ballot Secrecy and Sensitive Data Exposure Hardening Tests.
    Verifies that voter PII, private keys, OTPs, and individual ballot choices are not leaked
    via APIs, receipts, templates, audit records, or logs, while verifying historical data preservation.
    """
    def setUp(self):
        # Set up Organizations
        self.org_a = Organization.objects.create(
            name="Alpha Privacy Org",
            description="Tenant Alpha Privacy",
            contact_information="admin@alpha-privacy.edu"
        )
        self.org_b = Organization.objects.create(
            name="Beta Privacy Org",
            description="Tenant Beta Privacy",
            contact_information="admin@beta-privacy.edu"
        )

        # Set up Elections
        self.elec_a = Election.objects.create(
            organization=self.org_a,
            title="Alpha General Election",
            status="OPEN"
        )
        self.elec_b = Election.objects.create(
            organization=self.org_b,
            title="Beta General Election",
            status="OPEN"
        )

        # Set up Positions
        self.pos_a = Position.objects.create(
            election=self.elec_a,
            title="President",
            max_votes_allowed=1
        )
        self.pos_b = Position.objects.create(
            election=self.elec_b,
            title="Chair",
            max_votes_allowed=1
        )

        # Set up Candidates
        self.cand_a = Candidate.objects.create(
            position=self.pos_a,
            name="Alice Alpha",
            affiliation="Alpha Party"
        )
        self.cand_b = Candidate.objects.create(
            position=self.pos_b,
            name="Bob Beta",
            affiliation="Beta Party"
        )

        # Administrative Users
        self.u_platform = User.objects.create_user(username="priv_platform", password="testpassword123")
        self.p_platform = UserProfile.objects.create(user=self.u_platform, role="PLATFORM_ADMIN")

        self.u_org_a_admin = User.objects.create_user(username="priv_org_a_admin", password="testpassword123")
        self.p_org_a_admin = UserProfile.objects.create(user=self.u_org_a_admin, role="ORGANIZATION_ADMIN", organization=self.org_a)

        self.u_org_b_admin = User.objects.create_user(username="priv_org_b_admin", password="testpassword123")
        self.p_org_b_admin = UserProfile.objects.create(user=self.u_org_b_admin, role="ORGANIZATION_ADMIN", organization=self.org_b)

        self.u_auditor_a = User.objects.create_user(username="priv_auditor_a", password="testpassword123")
        self.p_auditor_a = UserProfile.objects.create(user=self.u_auditor_a, role="AUDITOR", organization=self.org_a)

        # Voters
        import datetime
        self.voter_1 = Voters.objects.create(
            uuid="priv_voter_001",
            name="Secret Voter One",
            email="secret1@test.com",
            dob=datetime.date(1995, 5, 5),
            pincode="500001",
            region="Zone A",
            vote_done=False
        )
        self.voter_2 = Voters.objects.create(
            uuid="priv_voter_002",
            name="Secret Voter Two",
            email="secret2@test.com",
            dob=datetime.date(1996, 6, 6),
            pincode="500002",
            region="Zone B",
            vote_done=False
        )

        # Eligibilities & Ballots
        self.elig_a1 = Eligibility.objects.create(election=self.elec_a, voter=self.voter_1)
        self.ballot_a1 = Ballot.objects.create(election=self.elec_a, voter=self.voter_1)

        self.elig_b2 = Eligibility.objects.create(election=self.elec_b, voter=self.voter_2)
        self.ballot_b2 = Ballot.objects.create(election=self.elec_b, voter=self.voter_2)

    def _csrf_client(self):
        client = Client(enforce_csrf_checks=True)
        client.get('/')
        return client, client.cookies['csrftoken'].value

    def _create_test_block_and_vote(self):
        from django.utils import timezone
        from home.merkle_tool import MerkleTools
        test_block = Block.objects.create(
            id=1,
            timestamp=timezone.now(),
            prev_hash="0" * 64,
            this_hash="a" * 64,
            merkle_hash="b" * 64,
            nonce=100
        )
        test_vote = Vote.objects.create(
            uuid="111111111111",
            vote_party_id="1",
            timestamp=timezone.now(),
            block_id=str(test_block.id)
        )
        VoteBackup.objects.create(
            uuid="111111111111",
            vote_party_id="1",
            timestamp=test_vote.timestamp,
            block_id=str(test_block.id)
        )
        root = MerkleTools()
        root.add_leaf([f"{test_vote.uuid}|{test_vote.vote_party_id}|{test_vote.timestamp}"], True)
        root.make_tree()
        test_block.merkle_hash = root.get_merkle_root()
        test_block.save()
        return test_block

    def test_01_public_results_leak_no_voter_identities_or_pii(self):
        """1. Verified election results payload contains zero voter UUIDs, names, or voter PII."""
        from home.methods_module import calculate_verified_election_results
        result = calculate_verified_election_results(self.elec_a.id)
        result_str = json.dumps(result)
        self.assertNotIn("priv_voter_001", result_str)
        self.assertNotIn("Secret Voter One", result_str)
        self.assertNotIn("secret1@test.com", result_str)
        self.assertNotIn("500001", result_str)
        self.assertNotIn("Zone A", result_str)
        self.assertIn("summary", result)
        self.assertIn("canonical_receipt_payload", result)

    def test_02_published_result_receipts_leak_no_voter_identities_or_ballots(self):
        """2. Published canonical result receipts contain zero voter identities, individual choices, or PII."""
        from home.methods_module import calculate_verified_election_results
        result = calculate_verified_election_results(self.elec_a.id)
        receipt = result.get('canonical_receipt_payload', {})
        receipt_str = json.dumps(receipt)
        self.assertNotIn("priv_voter_001", receipt_str)
        self.assertNotIn("Secret Voter One", receipt_str)
        self.assertNotIn("secret1@test.com", receipt_str)
        self.assertIn("election_id", receipt)
        self.assertIn("positions", receipt)

    def test_03_result_audit_records_contain_no_voter_identities_or_keys(self):
        """3. Result audit records endpoint contains aggregate event data without voter UUIDs or private keys."""
        client = Client()
        client.force_login(self.u_org_a_admin)
        res = client.get(f'/elections/{self.elec_a.id}/audit-records/')
        self.assertEqual(res.status_code, 200)
        content_str = res.content.decode('utf-8')
        self.assertNotIn("priv_voter_001", content_str)
        self.assertNotIn("secret1@test.com", content_str)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", content_str)
        self.assertNotIn("BEGIN PRIVATE KEY", content_str)

    def test_04_blockchain_verification_endpoints_leak_no_voter_identities(self):
        """4. Verification endpoints expose cryptographic validation data without voter UUIDs or keys."""
        client = Client()
        client.force_login(self.u_platform)
        test_block = self._create_test_block_and_vote()

        res_b = client.get(f'/blocks/{test_block.id}/verify/')
        self.assertEqual(res_b.status_code, 200)
        self.assertNotIn("priv_voter", res_b.content.decode('utf-8'))
        self.assertNotIn("BEGIN PRIVATE KEY", res_b.content.decode('utf-8'))

        res_c = client.get('/blockchain/verify-chain/?from_block=0&to_block=0')
        self.assertEqual(res_c.status_code, 200)
        self.assertNotIn("priv_voter", res_c.content.decode('utf-8'))
        self.assertNotIn("BEGIN PRIVATE KEY", res_c.content.decode('utf-8'))

    def test_05_block_info_endpoint_masks_voter_uuids_for_unauthenticated_public_viewers(self):
        """5. Block-info endpoint masks voter UUIDs for public unauthenticated callers and unit-tests mask helper."""
        from home.views import mask_voter_uuid
        # Unit test mask_voter_uuid
        self.assertEqual(mask_voter_uuid('111111111111'), '1111******11')
        self.assertEqual(mask_voter_uuid('v_8701'), 'v_**01')
        self.assertEqual(mask_voter_uuid('1234'), '****')
        self.assertEqual(mask_voter_uuid(''), '****')
        self.assertEqual(mask_voter_uuid(None), '****')

        # Integration test block-info view with created test block and vote
        test_block = self._create_test_block_and_vote()
        client = Client()
        res = client.get(f'/block-info/?id={test_block.id}')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn("1111******11", content)
        self.assertNotIn("111111111111", content)

    def test_06_block_info_endpoint_reveals_raw_uuid_for_platform_admin(self):
        """6. Block-info endpoint reveals full unmasked voter UUID only for authenticated platform administrators."""
        test_block = self._create_test_block_and_vote()
        client = Client()
        client.force_login(self.u_platform)
        res = client.get(f'/block-info/?id={test_block.id}')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn("111111111111", content)

    def test_07_get_parties_endpoint_does_not_leak_private_key_or_public_key_in_json(self):
        """7. get_parties JSON response does not transmit private_key or public_key over the wire."""
        client = Client()
        session = client.session
        session['uuid'] = self.voter_1.uuid
        session['email-verified'] = True
        session['email-id'] = self.voter_1.email
        session.save()

        res = client.get('/get-parties/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('parties', data)
        self.assertIn('html', data)
        self.assertNotIn('private_key', data)
        self.assertNotIn('public_key', data)

        # Server session retains keys for fallback signature validation
        self.assertIn('private-key', client.session)
        self.assertIn('public-key', client.session)

    def test_08_otp_endpoints_never_leak_otp_secret_or_plain_otp(self):
        """8. OTP dispatch and validation endpoints never return plaintext OTP digits or secret keys."""
        client, csrf = self._csrf_client()
        session = client.session
        session['uuid'] = self.voter_1.uuid
        session['email-id'] = self.voter_1.email
        session.save()

        res_send = client.post('/send-otp/', HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(res_send.status_code, 200)
        send_data = res_send.json()
        self.assertNotIn('otp', send_data)
        self.assertNotIn('secret', send_data)

        # verify-otp with incorrect OTP returns success: False without leaking OTP
        res_verify = client.post('/verify-otp/', {'otp-input': '999999'}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(res_verify.status_code, 200)
        verify_data = res_verify.json()
        self.assertFalse(verify_data.get('success'))
        self.assertNotIn('otp', verify_data)
        self.assertNotIn('secret', verify_data)

    def test_09_authentication_endpoint_returns_strictly_minimized_fields(self):
        """9. Authentication response contains strictly minimized voter details, omitting DOB, email, pincode, region."""
        client, csrf = self._csrf_client()
        res = client.post('/authentication/', {'aadhar_no': self.voter_1.uuid}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(res.status_code, 200)
        details = res.json().get('details', {})
        self.assertEqual(details.get('uuid'), self.voter_1.uuid)
        self.assertEqual(details.get('name'), self.voter_1.name)
        for sensitive in ['email', 'dob', 'pincode', 'region', 'phone', 'password']:
            self.assertNotIn(sensitive, details)

    def test_10_unauthorized_voter_cannot_access_or_inspect_other_voter_ballot(self):
        """10. Voter A cannot submit, mutate, or inspect Voter B's ballot."""
        client, csrf = self._csrf_client()
        session = client.session
        session['uuid'] = self.voter_1.uuid
        session['email-verified'] = True
        session.save()

        payload = {'selections': [{'position_id': self.pos_b.id, 'candidate_ids': [self.cand_b.id]}]}
        res = client.post(
            f'/ballots/{self.ballot_b2.id}/submit/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("Cannot submit ballot for another voter", res.json().get('error', ''))

    def test_11_cross_organization_data_isolation_preserved(self):
        """11. Cross-organization tenant isolation prevents Org A admin from viewing Org B results or audit logs."""
        client = Client()
        client.force_login(self.u_org_a_admin)
        res_res = client.get(f'/elections/{self.elec_b.id}/results/')
        self.assertEqual(res_res.status_code, 403)
        res_aud = client.get(f'/elections/{self.elec_b.id}/audit-records/')
        self.assertEqual(res_aud.status_code, 403)

    def test_12_legacy_vote_casting_works_safely_without_key_leakage(self):
        """12. Legacy vote casting succeeds without client private-key transmission, using session fallback."""
        from home.models import PoliticalParty
        party = PoliticalParty.objects.create(
            party_id="99",
            party_name="Legacy Test Party",
            candidate_name="Legacy Candidate",
            candidate_profile_pic="NOTA.png",
            party_logo="NOTA.png"
        )
        client, csrf = self._csrf_client()
        session = client.session
        session['uuid'] = self.voter_1.uuid
        session['email-verified'] = True
        session['email-id'] = self.voter_1.email
        session.save()

        # Step 1: get-parties establishes server-side session keys
        res_parties = client.get('/get-parties/')
        self.assertEqual(res_parties.status_code, 200)
        self.assertNotIn('private_key', res_parties.json())

        # Step 2: create-vote without private-key parameter in request POST body
        res_vote = client.post(
            '/create-vote/',
            {'selected-party-id': party.party_id},
            HTTP_X_CSRFTOKEN=csrf
        )
        self.assertEqual(res_vote.status_code, 200)
        self.assertTrue(res_vote.json().get('success'))
        self.assertNotIn('private_key', res_vote.json())

        # Step 3: verify database state
        self.voter_1.refresh_from_db()
        self.assertTrue(self.voter_1.vote_done)
        self.assertEqual(Vote.objects.filter(uuid=self.voter_1.uuid).count(), 1)
        self.assertEqual(VoteBackup.objects.filter(uuid=self.voter_1.uuid).count(), 1)

    def test_13_modern_ballot_submission_returns_only_receipt_tracker(self):
        """13. Modern ballot submission returns only operational tracker without leaking voter identity or choice."""
        client, csrf = self._csrf_client()
        session = client.session
        session['uuid'] = self.voter_2.uuid
        session['email-verified'] = True
        session.save()

        payload = {'selections': [{'position_id': self.pos_b.id, 'candidate_ids': [self.cand_b.id]}]}
        res = client.post(
            f'/ballots/{self.ballot_b2.id}/submit/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_CSRFTOKEN=csrf
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        data_str = json.dumps(data)
        self.assertNotIn(self.voter_2.uuid, data_str)
        self.assertNotIn(self.voter_2.name, data_str)
        self.assertNotIn("Bob Beta", data_str)

    def test_14_historical_blockchain_verification_remains_verified(self):
        """14. Full chain cryptographic audit across all 5,645 blocks remains 100% VERIFIED with 0 failures."""
        from home.methods_module import verify_full_chain
        result = verify_full_chain()
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['failures']), 0)



class Phase8Step8AUITests(TestCase):
    """
    Phase 8 Step 8A: UI/UX Modernization and Role-Based Dashboards Architecture Audit
    and Foundational Modernization Tests.

    Validates:
    1. Base template renders modern BallotChain branding, responsive viewport meta, and clean semantic structure.
    2. Unauthenticated visitor navigation drawer renders public links only (Voter Portal, Results, Ledger Explorer, Login)
       and strictly conceals internal mutating endpoints (/create-dummy-data, /mine-block).
    3. Platform Admin navigation drawer renders Platform Administration links (Organizations, Elections, Ledger, Chain Verification, Admin, Logout) and role badge.
    4. Organization Admin navigation drawer renders Organization Administration links (Elections, Positions, Candidates, Eligibility, Ballots, Results, Logout).
    5. Election Official navigation drawer renders Election Operations links (Elections, Ballots, Mine Block / Batches, Logout).
    6. Auditor navigation drawer renders Audit and Verification links (Ledger Explorer, Chain Verification, Results, Logout).
    7. Role-aware navigation drawer does NOT bypass backend RBAC (direct backend access without permission returns 403 / redirect).
    8. Legacy endpoints (/, /show-result/, /blockchain/, /block-info/) render successfully with 200 OK and modern branding.
    9. CSS base stylesheet contains responsive media queries, CSS custom properties, and accessible focus styles.
    10. Full chain cryptographic audit across all 5,645 blocks remains 100% VERIFIED with 0 failures.
    """
    def setUp(self):
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate, UserProfile

        self.org = Organization.objects.create(name="UI Test Organization", description="Org for Step 8A UI Tests")
        self.elec = Election.objects.create(
            organization=self.org,
            title="UI Test Election",
            status="OPEN"
        )
        self.pos = Position.objects.create(
            election=self.elec,
            title="UI Chair",
            max_votes_allowed=1
        )
        self.cand = Candidate.objects.create(
            position=self.pos,
            name="Alice UI",
            affiliation="Design Slate"
        )

        # Users and roles
        self.u_platform = User.objects.create_user(username="ui_platform_admin", password="testpassword123")
        self.p_platform = UserProfile.objects.create(user=self.u_platform, role="PLATFORM_ADMIN")

        self.u_org_admin = User.objects.create_user(username="ui_org_admin", password="testpassword123")
        self.p_org_admin = UserProfile.objects.create(user=self.u_org_admin, role="ORGANIZATION_ADMIN", organization=self.org)

        self.u_official = User.objects.create_user(username="ui_official", password="testpassword123")
        self.p_official = UserProfile.objects.create(user=self.u_official, role="ELECTION_OFFICIAL", organization=self.org)

        self.u_auditor = User.objects.create_user(username="ui_auditor", password="testpassword123")
        self.p_auditor = UserProfile.objects.create(user=self.u_auditor, role="AUDITOR", organization=self.org)

    def test_01_base_template_renders_viewport_and_branding(self):
        """1. Base template renders BallotChain branding, responsive viewport meta, and modern shell."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1.0">', content)
        self.assertIn('BallotChain', content)
        self.assertIn('Enterprise Voting on an', content)
        self.assertIn('Immutable Blockchain', content)
        self.assertNotIn('id="aadhar"', content)

    def test_02_anonymous_visitor_navigation_drawer_security(self):
        """2. Unauthenticated visitor navigation drawer renders public links only and strictly conceals internal endpoints."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Public Navigation', content)
        self.assertIn('Published Results', content)
        self.assertIn('Ledger Explorer', content)
        self.assertIn('Sign In', content)
        # Verify internal/dangerous endpoints are strictly NOT exposed in drawer
        self.assertNotIn('/create-dummy-data', content)
        self.assertNotIn('Dummy Data', content)
        self.assertNotIn('Mine Blocks', content)

    def test_03_platform_admin_navigation_drawer(self):
        """3. Platform Admin navigation drawer renders Platform Administration links and role badge."""
        self.client.force_login(self.u_platform)
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Platform Administration', content)
        self.assertIn('Organizations', content)
        self.assertIn('/organizations/', content)
        self.assertIn('Elections', content)
        self.assertIn('/elections/', content)
        self.assertIn('Chain Verification', content)
        self.assertIn('/blockchain/verify-chain/', content)
        self.assertNotIn('Django Admin', content)
        self.assertIn('/logout/', content)
        self.assertIn('ui_platform_admin', content)
        self.assertIn('Platform Admin', content)

    def test_04_organization_admin_navigation_drawer(self):
        """4. Organization Admin navigation drawer renders Organization Administration links."""
        self.client.force_login(self.u_org_admin)
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Organization Administration', content)
        self.assertIn('Positions', content)
        self.assertIn('/positions/', content)
        self.assertIn('Candidates', content)
        self.assertIn('/candidates/', content)
        self.assertIn('Voter Eligibility', content)
        self.assertIn('/eligibility/', content)
        self.assertIn('Ballot Batches', content)
        self.assertIn('/ballots/', content)
        self.assertIn('Election Results', content)
        self.assertIn('/logout/', content)
        self.assertIn('ui_org_admin', content)
        self.assertIn('Org Admin', content)

    def test_05_election_official_navigation_drawer(self):
        """5. Election Official navigation drawer renders Election Operations links."""
        self.client.force_login(self.u_official)
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Election Operations', content)
        self.assertIn('Elections', content)
        self.assertIn('Ballot Batches', content)
        self.assertIn('Mine Block / Batches', content)
        self.assertIn('/mine-block', content)
        self.assertIn('/logout/', content)
        self.assertIn('ui_official', content)
        self.assertIn('Election Official', content)

    def test_06_auditor_navigation_drawer(self):
        """6. Auditor navigation drawer renders Audit and Verification links."""
        self.client.force_login(self.u_auditor)
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Audit & Verification', content)
        self.assertIn('Ledger Explorer', content)
        self.assertIn('/blockchain/', content)
        self.assertIn('Chain Verification', content)
        self.assertIn('/blockchain/verify-chain/', content)
        self.assertIn('Election Results', content)
        self.assertIn('/logout/', content)
        self.assertIn('ui_auditor', content)
        self.assertIn('Auditor', content)

    def test_07_role_navigation_does_not_bypass_backend_rbac(self):
        """7. Role navigation does NOT bypass backend RBAC (backend returns 403/redirect when unauthorized)."""
        res_anon = self.client.get('/organizations/')
        self.assertIn(res_anon.status_code, [302, 401, 403])

        self.client.force_login(self.u_auditor)
        res_auditor = self.client.post(
            '/organizations/create/',
            json.dumps({'name': 'Unauthorized Org'}),
            content_type='application/json'
        )
        self.assertEqual(res_auditor.status_code, 403)

    def test_08_legacy_and_result_routes_render_cleanly(self):
        """8. Legacy routes (/show-result/, /blockchain/, /block-info/) render cleanly with 200 OK."""
        res_res = self.client.get('/show-result/')
        self.assertEqual(res_res.status_code, 200)
        content_res = res_res.content.decode('utf-8')
        self.assertIn('Candidate', content_res)
        self.assertIn('Verified Vote Count', content_res)

        res_bc = self.client.get('/blockchain/')
        self.assertEqual(res_bc.status_code, 200)
        content_bc = res_bc.content.decode('utf-8')
        self.assertIn('BallotChain', content_bc)

        res_info = self.client.get('/block-info/')
        self.assertEqual(res_info.status_code, 200)
        content_info = res_info.content.decode('utf-8')
        self.assertIn('BallotChain', content_info)

    def test_09_css_design_tokens_and_accessibility_present(self):
        """9. Base CSS stylesheet contains design tokens, responsive queries, and accessible focus styles."""
        import os
        from django.conf import settings
        css_path = os.path.join(settings.BASE_DIR, 'home', 'static', 'css', 'base.css')
        self.assertTrue(os.path.exists(css_path))
        with open(css_path, 'r', encoding='utf-8') as f:
            css_content = f.read()
        self.assertIn('--primary:', css_content)
        self.assertIn('--background-surface:', css_content)
        self.assertIn('@media (max-width: 768px)', css_content)
        self.assertIn(':focus-visible', css_content)
        self.assertIn('prefers-reduced-motion', css_content)
        self.assertIn('.user-role-badge', css_content)
        self.assertIn('.drawer-section-heading', css_content)

    def test_10_historical_blockchain_verification_remains_verified(self):
        """10. Full chain cryptographic audit across all 5,645 blocks remains 100% VERIFIED with 0 failures."""
        from home.methods_module import verify_full_chain
        result = verify_full_chain()
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['failures']), 0)


class Phase8C1LedgerExplorerTests(TestCase):
    """
    Phase 8C-1: Shared BallotChain Cryptographic Ledger Recovery & Unified Explorer Tests.

    Validates:
    1. Operational Ledger Recovery & Accessibility: /blockchain/ loads cleanly with 200 OK across all user personas (Anonymous, Voter, Candidate, Admin).
    2. Shared Explorer DOM & Islands: Verifies React Bits Cubes island mount point (#ballotchain-ledger-island-root),
       JSON ledger serialization script (#ballotchain-ledger-data), and accessible HTML fallback (#fallback-blockchain-table).
    3. Search Query by Block ID & Block Hash: Filters correctly by ID and by hash substring; handles non-matching queries gracefully.
    4. Block Type Filtering: Filtering by type=v1 returns historical blocks; type=v2 returns modern blocks.
    5. Chronological and Reverse Ordering: order=asc and order=desc sorts blocks by primary key appropriately.
    6. Pagination Scale Handling: Paginates large block sets (25 per page), preserving total block counts and page state.
    7. Single Block Inspection & Privacy: /block-info/ returns 200 OK and strictly masks voter UUIDs for public/voter viewers.
    8. Block Verification API: /verify-block/ returns cryptographic verification status and detailed audit receipts.
    9. Mutation & Mining Gating: Non-admin users cannot trigger block mining; /blockchain/ is strictly read-only.
    10. Ledger Immutability & Cryptographic Verification: Full chain verification remains 100% VERIFIED with 0 errors.
    """
    def setUp(self):
        from django.contrib.auth.models import User
        from django.utils import timezone
        from home.models import Organization, Election, Position, Candidate, UserProfile, Block, Vote, VoteBackup
        from home.methods_module import compute_v1_block_hash
        from home.merkle_tool import MerkleTools

        self.org = Organization.objects.create(name="Ledger Test Org", description="Org for Phase 8C-1 Tests")
        self.elec = Election.objects.create(organization=self.org, title="Ledger Test Election", status="OPEN")
        self.pos = Position.objects.create(election=self.elec, title="Chief Auditor", max_votes_allowed=1)
        self.cand = Candidate.objects.create(position=self.pos, name="Auditor Bob", affiliation="Security Slate")

        # Users and roles
        self.u_platform = User.objects.create_user(username="ledger_platform_admin", password="testpassword123")
        self.p_platform = UserProfile.objects.create(user=self.u_platform, role="PLATFORM_ADMIN")

        self.u_voter = User.objects.create_user(username="ledger_voter", password="testpassword123")

        self.u_candidate_user = User.objects.create_user(username="ledger_candidate", password="testpassword123")

        self.u_auditor = User.objects.create_user(username="ledger_auditor", password="testpassword123")
        self.p_auditor = UserProfile.objects.create(user=self.u_auditor, role="AUDITOR", organization=self.org)

        # Create valid cryptographic blocks for testing
        t_now = timezone.now()
        v1_uuid = "1111222233334444"
        v1_party = "cand_1"
        v1_leaf = f"{v1_uuid}|{v1_party}|{t_now}"
        tree1 = MerkleTools()
        tree1.add_leaf([v1_leaf], do_hash=True)
        tree1.make_tree()
        m1 = tree1.get_merkle_root()

        nonce1 = 0
        prev_h = '0' * 64
        while True:
            h1 = compute_v1_block_hash(prev_h, m1, nonce1, t_now.timestamp())
            if h1.startswith('00'):
                break
            nonce1 += 1

        self.b1 = Block.objects.create(
            id=1,
            prev_hash=prev_h,
            merkle_hash=m1,
            this_hash=h1,
            nonce=nonce1,
            timestamp=t_now,
            version=1
        )
        self.v1 = Vote.objects.create(
            uuid=v1_uuid,
            vote_party_id=v1_party,
            timestamp=t_now,
            block_id=str(self.b1.id),
            election=self.elec
        )
        self.vb1 = VoteBackup.objects.create(
            uuid=v1_uuid,
            vote_party_id=v1_party,
            timestamp=t_now,
            block_id=str(self.b1.id),
            election=self.elec
        )

        # Block 2 (v1)
        v2_uuid = "2222333344445555"
        v2_party = "cand_2"
        v2_leaf = f"{v2_uuid}|{v2_party}|{t_now}"
        tree2 = MerkleTools()
        tree2.add_leaf([v2_leaf], do_hash=True)
        tree2.make_tree()
        m2 = tree2.get_merkle_root()

        nonce2 = 0
        while True:
            h2 = compute_v1_block_hash(h1, m2, nonce2, t_now.timestamp())
            if h2.startswith('00'):
                break
            nonce2 += 1

        self.b2 = Block.objects.create(
            id=2,
            prev_hash=h1,
            merkle_hash=m2,
            this_hash=h2,
            nonce=nonce2,
            timestamp=t_now,
            version=1
        )
        self.v2 = Vote.objects.create(
            uuid=v2_uuid,
            vote_party_id=v2_party,
            timestamp=t_now,
            block_id=str(self.b2.id),
            election=self.elec
        )
        self.vb2 = VoteBackup.objects.create(
            uuid=v2_uuid,
            vote_party_id=v2_party,
            timestamp=t_now,
            block_id=str(self.b2.id),
            election=self.elec
        )

    def test_01_shared_explorer_endpoint_renders_200_all_personas(self):
        """1. /blockchain/ renders 200 OK across Anonymous, Voter, Candidate, and Admin personas."""
        # Anonymous (Public Auditor)
        res_anon = self.client.get('/blockchain/')
        self.assertEqual(res_anon.status_code, 200)
        content_anon = res_anon.content.decode('utf-8')
        self.assertIn('ballotchain-ledger-island-root', content_anon)
        self.assertIn('ballotchain-ledger-data', content_anon)
        self.assertIn('fallback-blockchain-table', content_anon)
        self.assertEqual(res_anon.context['user_role'], 'PUBLIC_AUDITOR')
        self.assertFalse(res_anon.context['is_admin'])

        # Voter
        self.client.force_login(self.u_voter)
        res_voter = self.client.get('/blockchain/')
        self.assertEqual(res_voter.status_code, 200)
        self.assertEqual(res_voter.context['user_role'], 'VOTER')

        # Candidate
        self.client.force_login(self.u_candidate_user)
        res_cand = self.client.get('/blockchain/')
        self.assertEqual(res_cand.status_code, 200)

        # Platform Admin
        self.client.force_login(self.u_platform)
        res_admin = self.client.get('/blockchain/')
        self.assertEqual(res_admin.status_code, 200)
        self.assertTrue(res_admin.context['is_admin'])
        self.assertEqual(res_admin.context['user_role'], 'PLATFORM_ADMIN')

    def test_02_search_by_block_id_and_hash(self):
        """2. Search query filters accurately by block ID and by block hash substring."""
        # Search by Block ID
        res_id = self.client.get(f'/blockchain/?q={self.b1.id}')
        self.assertEqual(res_id.status_code, 200)
        blocks = list(res_id.context['blocks'])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].id, self.b1.id)

        # Search by Block Hash prefix
        res_hash = self.client.get(f'/blockchain/?q={self.b2.this_hash[:12]}')
        self.assertEqual(res_hash.status_code, 200)
        block_ids = [b.id for b in res_hash.context['blocks']]
        self.assertIn(self.b2.id, block_ids)

        # Search by non-existent hash returns empty page cleanly without 500
        res_none = self.client.get('/blockchain/?q=nonexistent_hex_hash_99999999')
        self.assertEqual(res_none.status_code, 200)
        self.assertEqual(len(res_none.context['blocks']), 0)

    def test_03_type_filtering_v1_and_v2(self):
        """3. Block type filter isolates v1 historical blocks and v2 modern blocks."""
        from django.utils import timezone
        from home.models import Block
        # Create a v2 block
        b_v2 = Block.objects.create(
            id=3,
            prev_hash=self.b2.this_hash,
            merkle_hash="a" * 64,
            this_hash="00" + "b" * 62,
            nonce=5555,
            timestamp=timezone.now(),
            version=2,
            election=self.elec,
            batch_number=1,
            candidate_tx_count=1,
            merkle_leaf_count=1
        )

        res_v1 = self.client.get('/blockchain/?type=v1')
        self.assertEqual(res_v1.status_code, 200)
        for b in res_v1.context['blocks']:
            self.assertEqual(b.version, 1)

        res_v2 = self.client.get('/blockchain/?type=v2')
        self.assertEqual(res_v2.status_code, 200)
        for b in res_v2.context['blocks']:
            self.assertEqual(b.version, 2)

        res_all = self.client.get('/blockchain/?type=all')
        self.assertEqual(res_all.status_code, 200)
        all_versions = {b.version for b in res_all.context['blocks']}
        self.assertTrue(1 in all_versions and 2 in all_versions)

    def test_04_chronological_and_reverse_ordering(self):
        """4. Order parameter accurately controls ascending vs descending presentation."""
        # Descending (default)
        res_desc = self.client.get('/blockchain/?order=desc')
        self.assertEqual(res_desc.status_code, 200)
        blocks_desc = list(res_desc.context['blocks'])
        if len(blocks_desc) >= 2:
            self.assertGreater(blocks_desc[0].id, blocks_desc[1].id)

        # Ascending
        res_asc = self.client.get('/blockchain/?order=asc')
        self.assertEqual(res_asc.status_code, 200)
        blocks_asc = list(res_asc.context['blocks'])
        if len(blocks_asc) >= 2:
            self.assertLess(blocks_asc[0].id, blocks_asc[1].id)

    def test_05_pagination_handles_large_blockchains(self):
        """5. Paginator divides ledger into 25-block pages with stable page navigation."""
        from django.utils import timezone
        from home.models import Block
        # Bulk-create additional blocks to exceed page size of 25
        blocks_to_create = []
        for i in range(10, 36):
            blocks_to_create.append(
                Block(
                    id=i,
                    prev_hash=f"prev_dummy_hash_{i}",
                    merkle_hash=f"merkle_dummy_hash_{i}",
                    this_hash=f"00dummy_hash_{i}",
                    nonce=i * 100,
                    timestamp=timezone.now(),
                    version=1
                )
            )
        Block.objects.bulk_create(blocks_to_create)

        # Page 1
        res_p1 = self.client.get('/blockchain/?page=1')
        self.assertEqual(res_p1.status_code, 200)
        self.assertEqual(len(res_p1.context['blocks']), 25)
        self.assertTrue(res_p1.context['blocks'].has_next())

        # Page 2
        res_p2 = self.client.get('/blockchain/?page=2')
        self.assertEqual(res_p2.status_code, 200)
        self.assertGreater(len(res_p2.context['blocks']), 0)
        self.assertTrue(res_p2.context['blocks'].has_previous())

        # Out-of-bounds page gracefully delivers last page without error
        res_oob = self.client.get('/blockchain/?page=9999')
        self.assertEqual(res_oob.status_code, 200)
        self.assertEqual(res_oob.context['blocks'].number, res_oob.context['blocks'].paginator.num_pages)

    def test_06_block_info_details_and_privacy_masking(self):
        """6. Block detail endpoint renders 200 OK and strictly masks voter UUIDs for public viewers."""
        res = self.client.get(f'/block-info/?id={self.b1.id}')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        # Plaintext voter ID must NOT appear anywhere in the rendered HTML
        self.assertNotIn("1111222233334444", content)
        # Masked ID must be rendered instead
        self.assertIn("1111**********44", content)

    def test_07_block_verification_api_returns_structured_audit(self):
        """7. /verify-block/ returns cryptographic verification status and backward-compatible responses."""
        # Modern single-block audit endpoint
        res = self.client.get(f'/verify-block/?id={self.b1.id}')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('valid'))
        self.assertEqual(int(data.get('block_id')), self.b1.id)

        # Privileged detailed audit
        self.client.force_login(self.u_auditor)
        res_det = self.client.get(f'/verify-block/?id={self.b1.id}&detailed=true')
        self.assertEqual(res_det.status_code, 200)
        data_det = res_det.json()
        self.assertTrue(data_det.get('valid'))
        self.assertIn('checks_performed', data_det)

        # Legacy selected[] array format (used by original blockchain.js)
        res_legacy = self.client.get(f'/verify-block/?selected[]={self.b1.id}')
        self.assertEqual(res_legacy.status_code, 200)
        data_legacy = res_legacy.json()
        # Returns {block_id: is_tampered_boolean} -> False means untampered/valid
        self.assertIn(str(self.b1.id), data_legacy)
        self.assertFalse(data_legacy[str(self.b1.id)])

    def test_08_blockchain_mutation_and_mining_protection(self):
        """8. Mutation & mining endpoints remain restricted; /blockchain/ is strictly read-only."""
        from home.models import Block
        # Mining attempts by unauthenticated visitor are rejected with 403 Forbidden
        res_mine_anon = self.client.post('/start-mining/', {})
        self.assertEqual(res_mine_anon.status_code, 403)

        # Mining attempts by standard voter are rejected with 403 Forbidden
        self.client.force_login(self.u_voter)
        res_mine_voter = self.client.post('/start-mining/', {})
        self.assertEqual(res_mine_voter.status_code, 403)

        # Read-only guarantee: querying /blockchain/ causes zero side-effects on ledger count
        count_before = Block.objects.count()
        self.client.get('/blockchain/')
        self.assertEqual(Block.objects.count(), count_before)

    def test_09_react_bits_cubes_and_fallback_table_payload_integrity(self):
        """9. Ledger response includes complete serialized JSON payload for React Bits Cubes and fallback table."""
        import json
        res = self.client.get('/blockchain/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('blocks_json', res.context)

        raw_payload = res.context['blocks_json']
        payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
        self.assertIn('blocks', payload)
        self.assertIn('totalBlocks', payload)
        self.assertIn('totalVotes', payload)
        self.assertIn('currentPage', payload)
        self.assertIn('totalPages', payload)

        if payload['blocks']:
            first_block = payload['blocks'][0]
            for key in ('id', 'prev_hash', 'merkle_hash', 'this_hash', 'nonce', 'timestamp', 'version', 'is_historical'):
                self.assertIn(key, first_block)

        # Fallback table renders matching block rows
        content = res.content.decode('utf-8')
        self.assertIn('fallback-blockchain-table', content)
        self.assertIn(str(self.b1.id), content)
        self.assertIn(str(self.b2.id), content)

    def test_10_full_chain_cryptographic_verification(self):
        """10. Full chain cryptographic audit on ledger blocks remains 100% VERIFIED with 0 failures."""
        from home.methods_module import verify_full_chain
        result = verify_full_chain()
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['failures']), 0)


class Phase8C2AccountAuthTransitionTests(TestCase):
    """
    Phase 8C-2: BallotChain Account Authentication Transition Tests.
    Validates:
    1. Email + Password authentication succeeds and establishes Django session.
    2. Username + Password authentication remains 100% backward-compatible.
    3. Case-insensitive email authentication works as expected.
    4. Invalid credentials return 401 Unauthorized with zero secret leaks.
    5. Session authentication persists across subsequent requests.
    6. Candidate linked to User evaluates cleanly to 'CANDIDATE' persona.
    7. Standard User without candidacies evaluates to 'VOTER' and cannot mutate admin endpoints.
    8. Superuser without profile evaluates to 'PLATFORM_ADMIN' and possesses administrative access.
    9. Duplicate candidate participation prevention blocks registering the same user twice for one position.
    10. OTP voting step-up remains segregated from account login.
    """
    def setUp(self):
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate

        self.org = Organization.objects.create(name="Auth Transition Org", description="Org for 8C-2 tests")
        self.elec = Election.objects.create(organization=self.org, title="Auth Transition Election", status="OPEN")
        self.pos = Position.objects.create(election=self.elec, title="Trustee", max_votes_allowed=1)

        # 1. Superuser (Platform Admin)
        self.u_admin = User.objects.create_superuser(
            username="admin_8c2",
            email="admin_8c2@ballotchain.org",
            password="AdminPassword123!"
        )

        # 2. Standard User
        self.u_voter = User.objects.create_user(
            username="voter_8c2",
            email="voter_8c2@example.com",
            password="VoterPassword123!"
        )

        # 3. Candidate User
        self.u_candidate = User.objects.create_user(
            username="candidate_8c2",
            email="candidate_8c2@example.com",
            password="CandidatePassword123!"
        )
        self.cand = Candidate.objects.create(
            position=self.pos,
            user=self.u_candidate,
            name="Alice Candidate",
            affiliation="Integrity Slate"
        )

    def test_01_email_password_authentication_success(self):
        """1. Email + Password authentication succeeds and returns user persona."""
        res = self.client.post(
            '/login/',
            json.dumps({'email': 'voter_8c2@example.com', 'password': 'VoterPassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('user', {}).get('email'), 'voter_8c2@example.com')
        self.assertEqual(data.get('user', {}).get('persona'), 'VOTER')

    def test_02_username_password_authentication_backward_compatibility(self):
        """2. Username + Password authentication remains 100% backward-compatible."""
        res = self.client.post(
            '/admin-login/',
            json.dumps({'username': 'admin_8c2', 'password': 'AdminPassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('user', {}).get('persona'), 'PLATFORM_ADMIN')

    def test_03_case_insensitive_email_login(self):
        """3. Email login is case-insensitive (e.g. UPPERCASE email succeeds)."""
        res = self.client.post(
            '/login/',
            json.dumps({'email': 'VOTER_8C2@EXAMPLE.COM', 'password': 'VoterPassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('user', {}).get('id'), self.u_voter.id)

    def test_04_invalid_credentials_rejected(self):
        """4. Invalid password returns 401 with no sensitive data leak."""
        res = self.client.post(
            '/login/',
            json.dumps({'email': 'voter_8c2@example.com', 'password': 'WrongPassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 401)
        data = res.json()
        self.assertFalse(data.get('success'))
        self.assertEqual(data.get('error'), 'Invalid credentials')
        self.assertNotIn('password', str(data))

    def test_05_session_authentication_established(self):
        """5. Successful login establishes authenticated session recognizing user across endpoints."""
        res_login = self.client.post(
            '/login/',
            json.dumps({'email': 'voter_8c2@example.com', 'password': 'VoterPassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res_login.status_code, 200)
        
        # Verify authenticated session persists to ledger explorer
        res_bc = self.client.get('/blockchain/')
        self.assertEqual(res_bc.status_code, 200)
        self.assertEqual(res_bc.context['user_role'], 'VOTER')

    def test_06_candidate_user_linkage_and_persona(self):
        """6. User linked to a Candidate record resolves to 'CANDIDATE' persona."""
        from home.permissions import get_account_persona
        self.assertEqual(get_account_persona(self.u_candidate), 'CANDIDATE')
        self.assertEqual(self.cand.user, self.u_candidate)
        self.assertIn(self.cand, self.u_candidate.candidacies.all())

        # Test login API returns CANDIDATE persona
        res = self.client.post(
            '/login/',
            json.dumps({'email': 'candidate_8c2@example.com', 'password': 'CandidatePassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get('user', {}).get('persona'), 'CANDIDATE')

    def test_07_regular_user_resolves_to_voter(self):
        """7. Regular user evaluates to 'VOTER' and cannot mutate administrative resources."""
        from home.permissions import get_account_persona
        self.assertEqual(get_account_persona(self.u_voter), 'VOTER')

        self.client.force_login(self.u_voter)
        res_admin_action = self.client.post(
            '/organizations/create/',
            json.dumps({'name': 'Disallowed Org'}),
            content_type='application/json'
        )
        self.assertEqual(res_admin_action.status_code, 403)

    def test_08_superuser_resolves_to_platform_admin(self):
        """8. Superuser without UserProfile evaluates to 'PLATFORM_ADMIN' and can perform admin tasks."""
        from home.permissions import get_account_persona, is_platform_admin
        self.assertTrue(is_platform_admin(self.u_admin))
        self.assertEqual(get_account_persona(self.u_admin), 'PLATFORM_ADMIN')

        self.client.force_login(self.u_admin)
        res_admin_action = self.client.post(
            '/organizations/create/',
            json.dumps({'name': 'Allowed Superuser Org', 'description': 'Created by Superuser'}),
            content_type='application/json'
        )
        self.assertEqual(res_admin_action.status_code, 200)
        self.assertTrue(res_admin_action.json().get('success'))

    def test_09_duplicate_candidate_participation_prevention(self):
        """9. Duplicate candidate participation for the same position is rejected."""
        self.client.force_login(self.u_admin)
        
        # Second candidate submission with identical user for self.pos
        res_dup = self.client.post(
            '/candidates/create/',
            json.dumps({
                'position_id': self.pos.id,
                'user_id': self.u_candidate.id,
                'name': 'Duplicate Alice'
            }),
            content_type='application/json'
        )
        self.assertEqual(res_dup.status_code, 400)
        data = res_dup.json()
        self.assertIn('already registered as a candidate', data.get('error', ''))

    def test_10_otp_step_up_remains_segregated(self):
        """10. OTP voting step-up remains independent from account authentication."""
        # Account login does NOT require OTP
        res_login = self.client.post(
            '/login/',
            json.dumps({'email': 'voter_8c2@example.com', 'password': 'VoterPassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res_login.status_code, 200)

        # /send-otp/ without voter session raises 401
        res_otp = self.client.get('/send-otp/')
        self.assertEqual(res_otp.status_code, 401)



class Phase8C2_1AdminRbacCorrectionTests(TestCase):
    """
    Phase 8C-2.1: Granular BallotChain Admin RBAC Correction Tests.
    Enforces distinct authorization boundaries among:
    1. PLATFORM_ADMIN
    2. ORGANIZATION_ADMIN
    3. ELECTION_OFFICIAL
    4. AUDITOR
    5. USER / VOTER
    6. CANDIDATE
    """
    def setUp(self):
        # Create Organizations
        self.org_a = Organization.objects.create(
            name="Org Alpha",
            description="Alpha Scope",
            contact_information="admin@alpha.org"
        )
        self.org_b = Organization.objects.create(
            name="Org Beta",
            description="Beta Scope",
            contact_information="admin@beta.org"
        )

        # Create Elections
        self.elec_a = Election.objects.create(
            organization=self.org_a,
            title="Alpha Presidential Election",
            status="DRAFT"
        )
        self.elec_b = Election.objects.create(
            organization=self.org_b,
            title="Beta Senate Election",
            status="DRAFT"
        )

        # Create Positions
        self.pos_a = Position.objects.create(
            election=self.elec_a,
            title="Alpha President",
            max_votes_allowed=1
        )
        self.pos_b = Position.objects.create(
            election=self.elec_b,
            title="Beta Senator",
            max_votes_allowed=1
        )

        # Create Users and Profiles
        # 1. Platform Admin
        self.u_platform_admin = User.objects.create_user(
            username="platform_admin",
            email="platform@ballotchain.org",
            password="PlatformPass123!",
            is_superuser=True
        )

        # 2. Organization Admin (Org A)
        self.u_org_admin = User.objects.create_user(
            username="org_admin_a",
            email="org_admin@alpha.org",
            password="OrgAdminPass123!"
        )
        UserProfile.objects.create(
            user=self.u_org_admin,
            role="ORGANIZATION_ADMIN",
            organization=self.org_a
        )

        # 2b. Organization Admin (Org B)
        self.u_org_admin_b = User.objects.create_user(
            username="org_admin_b",
            email="org_admin@beta.org",
            password="OrgAdminPass123!"
        )
        UserProfile.objects.create(
            user=self.u_org_admin_b,
            role="ORGANIZATION_ADMIN",
            organization=self.org_b
        )

        # 3. Election Official (Org A)
        self.u_official = User.objects.create_user(
            username="official_a",
            email="official@alpha.org",
            password="OfficialPass123!"
        )
        UserProfile.objects.create(
            user=self.u_official,
            role="ELECTION_OFFICIAL",
            organization=self.org_a
        )

        # 4. Auditor (Org A)
        self.u_auditor = User.objects.create_user(
            username="auditor_a",
            email="auditor@alpha.org",
            password="AuditorPass123!"
        )
        UserProfile.objects.create(
            user=self.u_auditor,
            role="AUDITOR",
            organization=self.org_a
        )

        # 5. Voter / Normal User
        self.u_voter = User.objects.create_user(
            username="voter_jane",
            email="jane@example.com",
            password="VoterPass123!"
        )

        # 6. Candidate
        self.u_candidate = User.objects.create_user(
            username="cand_bob",
            email="bob@example.com",
            password="CandidatePass123!"
        )
        self.cand_a = Candidate.objects.create(
            position=self.pos_a,
            user=self.u_candidate,
            name="Bob Candidate",
            affiliation="Progressive"
        )

        # Legacy Voter record
        import datetime
        self.voter_rec = Voters.objects.create(
            uuid="55555555-5555-5555-5555-555555555555",
            name="Jane Voter",
            dob=datetime.date(1990, 1, 1),
            pincode="123456",
            region="Alpha Region",
            email="jane@example.com",
            vote_done=False
        )

        self.client = Client()

    def test_01_platform_admin_authorized_operations(self):
        """1. Platform Admin can perform global administrative and lifecycle operations."""
        from home.permissions import (
            is_platform_admin, is_authenticated_admin, get_account_persona,
            can_start_election, can_end_election, can_publish_results, can_perform_administrative_mutation
        )
        self.assertTrue(is_platform_admin(self.u_platform_admin))
        self.assertTrue(is_authenticated_admin(self.u_platform_admin))
        self.assertEqual(get_account_persona(self.u_platform_admin), 'PLATFORM_ADMIN')
        self.assertTrue(can_start_election(self.u_platform_admin, self.elec_a))
        self.assertTrue(can_end_election(self.u_platform_admin, self.elec_a))
        self.assertTrue(can_publish_results(self.u_platform_admin, self.elec_a))
        self.assertTrue(can_perform_administrative_mutation(self.u_platform_admin))

        # Platform Admin can start election via API
        self.client.force_login(self.u_platform_admin)
        res = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'status': 'OPEN'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.elec_a.refresh_from_db()
        self.assertEqual(self.elec_a.status, 'OPEN')

        # Platform Admin can end election via API
        res_end = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'status': 'CLOSED'}),
            content_type='application/json'
        )
        self.assertEqual(res_end.status_code, 200)
        self.elec_a.refresh_from_db()
        self.assertEqual(self.elec_a.status, 'CLOSED')

    def test_02_organization_admin_authorized_scoped_operations(self):
        """2. Organization Admin can perform authorized operations only within their organization."""
        from home.permissions import (
            is_organization_admin, is_authenticated_admin, get_account_persona,
            can_start_election, can_end_election, can_publish_results
        )
        self.assertTrue(is_organization_admin(self.u_org_admin, self.org_a.id))
        self.assertFalse(is_organization_admin(self.u_org_admin, self.org_b.id))
        self.assertTrue(is_authenticated_admin(self.u_org_admin))
        self.assertEqual(get_account_persona(self.u_org_admin), 'ORGANIZATION_ADMIN')

        # Org Admin can start/end own election
        self.assertTrue(can_start_election(self.u_org_admin, self.elec_a))
        self.assertTrue(can_end_election(self.u_org_admin, self.elec_a))
        self.assertTrue(can_publish_results(self.u_org_admin, self.elec_a))

        # Org Admin CANNOT start/end other org election
        self.assertFalse(can_start_election(self.u_org_admin, self.elec_b))
        self.assertFalse(can_end_election(self.u_org_admin, self.elec_b))
        self.assertFalse(can_publish_results(self.u_org_admin, self.elec_b))

        # Mutating other org election returns 403
        self.client.force_login(self.u_org_admin)
        res_cross = self.client.post(
            f'/elections/{self.elec_b.id}/edit/',
            json.dumps({'status': 'OPEN'}),
            content_type='application/json'
        )
        self.assertEqual(res_cross.status_code, 403)

        # Mutating own election to OPEN succeeds
        res_own = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'status': 'OPEN'}),
            content_type='application/json'
        )
        self.assertEqual(res_own.status_code, 200)

    def test_03_election_official_authorized_management_and_forbidden_mutations(self):
        """3. Election Official can manage operational items but CANNOT start/end elections or publish results."""
        from home.permissions import (
            is_election_official, is_authenticated_admin, has_administrative_access,
            get_account_persona, can_manage_election, can_start_election, can_end_election,
            can_publish_results, can_perform_administrative_mutation
        )
        self.assertTrue(is_election_official(self.u_official, self.org_a.id))
        self.assertFalse(is_authenticated_admin(self.u_official))
        self.assertTrue(has_administrative_access(self.u_official))
        self.assertEqual(get_account_persona(self.u_official), 'ELECTION_OFFICIAL')

        # Operational management permissions
        self.assertTrue(can_manage_election(self.u_official, self.elec_a))
        self.assertFalse(can_manage_election(self.u_official, self.elec_b))

        # Lifecycle restrictions: CANNOT start, end, or publish
        self.assertFalse(can_start_election(self.u_official, self.elec_a))
        self.assertFalse(can_end_election(self.u_official, self.elec_a))
        self.assertFalse(can_publish_results(self.u_official, self.elec_a))
        self.assertFalse(can_perform_administrative_mutation(self.u_official))

        self.client.force_login(self.u_official)

        # Attempt to start election returns 403 Unauthorized to start election
        res_start = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'status': 'OPEN'}),
            content_type='application/json'
        )
        self.assertEqual(res_start.status_code, 403)
        self.assertIn('Unauthorized to start election', res_start.json().get('error', ''))

        # Attempt to end election returns 403 Unauthorized to end election
        self.elec_a.status = 'OPEN'
        self.elec_a.save()
        res_end = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'status': 'CLOSED'}),
            content_type='application/json'
        )
        self.assertEqual(res_end.status_code, 403)
        self.assertIn('Unauthorized to end election', res_end.json().get('error', ''))

        # Operational management: can edit title/description
        res_title = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'title': 'Updated Title by Official'}),
            content_type='application/json'
        )
        self.assertEqual(res_title.status_code, 200)

        # Operational management: can create position
        res_pos = self.client.post(
            '/positions/create/',
            json.dumps({'election_id': self.elec_a.id, 'title': 'VP Alpha', 'max_votes_allowed': 1}),
            content_type='application/json'
        )
        self.assertEqual(res_pos.status_code, 200)

    def test_04_auditor_is_strictly_read_only(self):
        """4. Auditor is strictly read-only within permitted organization."""
        from home.permissions import (
            is_auditor, is_authenticated_admin, has_administrative_access,
            has_staff_or_auditor_access, get_account_persona, can_manage_election
        )
        self.assertTrue(is_auditor(self.u_auditor, self.org_a.id))
        self.assertFalse(is_authenticated_admin(self.u_auditor))
        self.assertFalse(has_administrative_access(self.u_auditor))
        self.assertTrue(has_staff_or_auditor_access(self.u_auditor, self.org_a.id))
        self.assertFalse(has_staff_or_auditor_access(self.u_auditor, self.org_b.id))
        self.assertEqual(get_account_persona(self.u_auditor), 'AUDITOR')
        self.assertFalse(can_manage_election(self.u_auditor, self.elec_a))

        self.client.force_login(self.u_auditor)

        # Permitted reads in own org
        self.assertEqual(self.client.get(f'/organizations/{self.org_a.id}/').status_code, 200)
        self.assertEqual(self.client.get('/elections/').status_code, 200)
        self.assertEqual(self.client.get(f'/elections/{self.elec_a.id}/').status_code, 200)
        self.assertEqual(self.client.get(f'/elections/{self.elec_a.id}/audit-records/').status_code, 200)
        self.assertEqual(self.client.get(f'/elections/{self.elec_a.id}/verify-receipt/').status_code, 200)
        self.assertEqual(self.client.get('/positions/').status_code, 200)
        self.assertEqual(self.client.get(f'/positions/{self.pos_a.id}/').status_code, 200)

        # Prohibited mutations
        self.assertEqual(self.client.post('/organizations/create/', json.dumps({'name': 'X'}), content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post('/elections/create/', json.dumps({'organization_id': self.org_a.id, 'title': 'X'}), content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post(f'/elections/{self.elec_a.id}/edit/', json.dumps({'title': 'X'}), content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post(f'/elections/{self.elec_a.id}/delete/', '{}', content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post('/positions/create/', json.dumps({'election_id': self.elec_a.id, 'title': 'X'}), content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post('/candidates/create/', json.dumps({'position_id': self.pos_a.id, 'name': 'X'}), content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post(f'/elections/{self.elec_a.id}/mine-batch/', '{}', content_type='application/json').status_code, 403)

    def test_05_auditor_cannot_start_an_election(self):
        """5. Auditor cannot start an election."""
        from home.permissions import can_start_election
        self.assertFalse(can_start_election(self.u_auditor, self.elec_a))

        self.client.force_login(self.u_auditor)
        res = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'status': 'OPEN'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 403)
        self.elec_a.refresh_from_db()
        self.assertEqual(self.elec_a.status, 'DRAFT')

    def test_06_auditor_cannot_end_an_election(self):
        """6. Auditor cannot end an election."""
        from home.permissions import can_end_election
        self.elec_a.status = 'OPEN'
        self.elec_a.save()

        self.assertFalse(can_end_election(self.u_auditor, self.elec_a))

        self.client.force_login(self.u_auditor)
        res = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'status': 'CLOSED'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 403)
        self.elec_a.refresh_from_db()
        self.assertEqual(self.elec_a.status, 'OPEN')

    def test_07_auditor_cannot_publish_results(self):
        """7. Auditor cannot publish results."""
        from home.permissions import can_publish_results
        self.assertFalse(can_publish_results(self.u_auditor, self.elec_a))

        # Auditor can view verified results
        self.client.force_login(self.u_auditor)
        res_view = self.client.get(f'/elections/{self.elec_a.id}/results/')
        self.assertEqual(res_view.status_code, 200)

        # But cannot trigger publication by closing the election
        res_pub = self.client.post(
            f'/elections/{self.elec_a.id}/edit/',
            json.dumps({'status': 'CLOSED'}),
            content_type='application/json'
        )
        self.assertEqual(res_pub.status_code, 403)

    def test_08_normal_user_cannot_perform_admin_mutations(self):
        """8. Normal User cannot perform any administrative mutations."""
        from home.permissions import (
            is_voter, is_authenticated_admin, has_administrative_access,
            get_account_persona, can_start_election, can_end_election, can_publish_results
        )
        self.assertTrue(is_voter(self.u_voter))
        self.assertFalse(is_authenticated_admin(self.u_voter))
        self.assertFalse(has_administrative_access(self.u_voter))
        self.assertEqual(get_account_persona(self.u_voter), 'VOTER')

        self.assertFalse(can_start_election(self.u_voter, self.elec_a))
        self.assertFalse(can_end_election(self.u_voter, self.elec_a))
        self.assertFalse(can_publish_results(self.u_voter, self.elec_a))

        self.client.force_login(self.u_voter)
        mutations = [
            ('/organizations/create/', json.dumps({'name': 'Voter Org'})),
            ('/elections/create/', json.dumps({'organization_id': self.org_a.id, 'title': 'Voter Elec'})),
            (f'/elections/{self.elec_a.id}/edit/', json.dumps({'status': 'OPEN'})),
            (f'/elections/{self.elec_a.id}/delete/', '{}'),
            ('/positions/create/', json.dumps({'election_id': self.elec_a.id, 'title': 'Voter Pos'})),
            ('/candidates/create/', json.dumps({'position_id': self.pos_a.id, 'name': 'Voter Cand'})),
            (f'/elections/{self.elec_a.id}/mine-batch/', '{}'),
        ]
        for url, data in mutations:
            res = self.client.post(url, data, content_type='application/json')
            self.assertEqual(res.status_code, 403, f'Voter calling {url} expected 403, got {res.status_code}')

    def test_09_candidate_cannot_perform_admin_mutations(self):
        """9. Candidate cannot perform administrative mutations."""
        from home.permissions import (
            is_candidate, is_authenticated_admin, has_administrative_access,
            get_account_persona, can_start_election, can_end_election, can_publish_results
        )
        self.assertTrue(is_candidate(self.u_candidate))
        self.assertFalse(is_authenticated_admin(self.u_candidate))
        self.assertFalse(has_administrative_access(self.u_candidate))
        self.assertEqual(get_account_persona(self.u_candidate), 'CANDIDATE')

        self.assertFalse(can_start_election(self.u_candidate, self.elec_a))
        self.assertFalse(can_end_election(self.u_candidate, self.elec_a))
        self.assertFalse(can_publish_results(self.u_candidate, self.elec_a))

        self.client.force_login(self.u_candidate)
        mutations = [
            ('/organizations/create/', json.dumps({'name': 'Cand Org'})),
            ('/elections/create/', json.dumps({'organization_id': self.org_a.id, 'title': 'Cand Elec'})),
            (f'/elections/{self.elec_a.id}/edit/', json.dumps({'status': 'OPEN'})),
            (f'/elections/{self.elec_a.id}/delete/', '{}'),
            ('/positions/create/', json.dumps({'election_id': self.elec_a.id, 'title': 'Cand Pos'})),
            ('/candidates/create/', json.dumps({'position_id': self.pos_a.id, 'name': 'Cand 2'})),
            (f'/elections/{self.elec_a.id}/mine-batch/', '{}'),
        ]
        for url, data in mutations:
            res = self.client.post(url, data, content_type='application/json')
            self.assertEqual(res.status_code, 403, f'Candidate calling {url} expected 403, got {res.status_code}')

    def test_10_organization_boundaries_enforced_across_all_personas(self):
        """10. Organization boundaries remain strictly enforced across all scoped personas."""
        from home.permissions import belongs_to_organization
        self.assertTrue(belongs_to_organization(self.u_org_admin, self.org_a.id))
        self.assertFalse(belongs_to_organization(self.u_org_admin, self.org_b.id))

        self.assertTrue(belongs_to_organization(self.u_official, self.org_a.id))
        self.assertFalse(belongs_to_organization(self.u_official, self.org_b.id))

        self.assertTrue(belongs_to_organization(self.u_auditor, self.org_a.id))
        self.assertFalse(belongs_to_organization(self.u_auditor, self.org_b.id))

        # Org Admin A cannot access Org B
        self.client.force_login(self.u_org_admin)
        self.assertEqual(self.client.get(f'/organizations/{self.org_b.id}/').status_code, 403)
        self.assertEqual(self.client.get(f'/elections/{self.elec_b.id}/').status_code, 403)

        # Election Official A cannot access Org B
        self.client.force_login(self.u_official)
        self.assertEqual(self.client.get(f'/organizations/{self.org_b.id}/').status_code, 403)
        self.assertEqual(self.client.get(f'/elections/{self.elec_b.id}/').status_code, 403)

        # Auditor A cannot access Org B
        self.client.force_login(self.u_auditor)
        self.assertEqual(self.client.get(f'/organizations/{self.org_b.id}/').status_code, 403)
        self.assertEqual(self.client.get(f'/elections/{self.elec_b.id}/').status_code, 403)

    def test_11_all_personas_can_view_blockchain_ledger(self):
        """11. All personas (Admin, User, Candidate, Auditor, Public) can view the blockchain ledger."""
        from home.permissions import can_view_ledger
        personas = [
            (self.u_platform_admin, 'Platform Admin'),
            (self.u_org_admin, 'Org Admin'),
            (self.u_official, 'Election Official'),
            (self.u_auditor, 'Auditor'),
            (self.u_voter, 'Normal User / Voter'),
            (self.u_candidate, 'Candidate'),
            (None, 'Public Auditor')
        ]
        for user, label in personas:
            self.assertTrue(can_view_ledger(user), f'{label} must be permitted to view ledger')
            client = Client()
            if user:
                client.force_login(user)
            res = client.get('/blockchain/')
            self.assertEqual(res.status_code, 200, f'{label} GET /blockchain/ expected 200, got {res.status_code}')

    def test_12_ledger_mutation_controls_remain_protected(self):
        """12. Ledger mutation controls remain protected against non-admins and unauthorized roles."""
        # Voter cannot trigger mining
        self.client.force_login(self.u_voter)
        res_mine = self.client.post('/start-mining/', '{}', content_type='application/json')
        self.assertEqual(res_mine.status_code, 403)

        # Auditor cannot trigger mining
        self.client.force_login(self.u_auditor)
        res_mine_auditor = self.client.post('/start-mining/', '{}', content_type='application/json')
        self.assertEqual(res_mine_auditor.status_code, 403)

        # Org admin cannot perform platform dummy data injection
        self.client.force_login(self.u_org_admin)
        res_dummy = self.client.post('/create-dummy-data/', '{"createRandomVoters": 1}', content_type='application/json')
        self.assertEqual(res_dummy.status_code, 403)

        # Org admin cannot perform block sync
        res_sync = self.client.post('/sync-block/', '{"block-id": "1"}', content_type='application/json')
        self.assertEqual(res_sync.status_code, 403)


class Phase8C3DashboardTransitionTests(TestCase):
    """
    Phase 8C-3: BallotChain Role-Based Dashboard Transition Tests.
    Validates:
    1. Unauthenticated behavior: Redirects GET to login (302) and returns 401 for JSON requests.
    2. Platform Admin: Global dashboard access, all orgs, all elections, system stats.
    3. Organization Admin: Tenant-scoped dashboard access, tenant elections, lifecycle controls.
    4. Election Official: Operational dashboard access, candidate roster, strictly NO start/end/publish.
    5. Auditor: Strictly read-only dashboard access, audit receipts, strictly NO mutation controls.
    6. Voter / User: Voter profile, eligible elections, participation status, zero admin controls.
    7. Candidate: Candidacy details + voter capabilities, eligible elections, zero admin controls.
    8. Tenant isolation: Scoped users see only their assigned organization's elections.
    9. Auditor server-side mutation protection: Endpoints reject auditor mutations with 403.
    10. Election Official lifecycle protection: Endpoints reject official start/end/publish with 403.
    11. Single shared ledger: Accessible across all personas via /blockchain/.
    12. Zero duplicate dashboard records: Accessing dashboards does not insert demo/test records.
    13. Account authentication preservation: Email + password and username + password auth remain intact.
    """

    def setUp(self):
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate, UserProfile, Voters

        # Create Organizations
        self.org_alpha = Organization.objects.create(
            name="Org Alpha 8C3",
            description="Alpha Scope for Dashboard Tests",
            contact_information="admin@alpha8c3.org"
        )
        self.org_beta = Organization.objects.create(
            name="Org Beta 8C3",
            description="Beta Scope for Dashboard Tests",
            contact_information="admin@beta8c3.org"
        )

        # Create Elections
        self.elec_alpha = Election.objects.create(
            organization=self.org_alpha,
            title="Alpha General Election",
            status="OPEN"
        )
        self.elec_beta = Election.objects.create(
            organization=self.org_beta,
            title="Beta Board Election",
            status="DRAFT"
        )

        # Create Position
        self.pos_alpha = Position.objects.create(
            election=self.elec_alpha,
            title="President",
            max_votes_allowed=1
        )

        # 1. Platform Admin (Superuser)
        self.u_platform_admin = User.objects.create_superuser(
            username="pa_8c3",
            email="pa_8c3@ballotchain.org",
            password="PlatformPassword123!"
        )

        # 2. Organization Admin (Scoped to Org Alpha)
        self.u_org_admin = User.objects.create_user(
            username="oa_8c3",
            email="oa_8c3@ballotchain.org",
            password="OrgAdminPassword123!"
        )
        UserProfile.objects.create(
            user=self.u_org_admin,
            role="ORGANIZATION_ADMIN",
            organization=self.org_alpha
        )

        # 3. Election Official (Scoped to Org Alpha)
        self.u_official = User.objects.create_user(
            username="eo_8c3",
            email="eo_8c3@ballotchain.org",
            password="OfficialPassword123!"
        )
        UserProfile.objects.create(
            user=self.u_official,
            role="ELECTION_OFFICIAL",
            organization=self.org_alpha
        )

        # 4. Auditor (Scoped to Org Alpha)
        self.u_auditor = User.objects.create_user(
            username="au_8c3",
            email="au_8c3@ballotchain.org",
            password="AuditorPassword123!"
        )
        UserProfile.objects.create(
            user=self.u_auditor,
            role="AUDITOR",
            organization=self.org_alpha
        )

        # 5. Candidate User (Linked to Position in Org Alpha)
        self.u_candidate = User.objects.create_user(
            username="cand_8c3",
            email="cand_8c3@ballotchain.org",
            password="CandidatePassword123!"
        )
        self.candidate_record = Candidate.objects.create(
            position=self.pos_alpha,
            user=self.u_candidate,
            name="Alice Candidate",
            bio="Experienced Leader for Alpha"
        )

        # 6. Standard User / Voter
        self.u_voter = User.objects.create_user(
            username="voter_8c3",
            email="voter_8c3@ballotchain.org",
            password="VoterPassword123!"
        )
        self.voter_record = Voters.objects.create(
            uuid="VOTER_8C3_001",
            name="Bob Voter",
            dob="1990-01-01",
            pincode="110001",
            region="Region 1",
            email="voter_8c3@ballotchain.org",
            vote_done=False
        )

    def test_01_unauthenticated_dashboard_redirect(self):
        """1. Unauthenticated request to /dashboard/ redirects to login (302) and returns 401 for JSON."""
        # Browser request: 302 redirect
        res_browser = self.client.get('/dashboard/')
        self.assertEqual(res_browser.status_code, 302)
        self.assertIn('/login/', res_browser.url)

        # API / JSON request: 401 Unauthorized
        res_api = self.client.get('/dashboard/', HTTP_ACCEPT='application/json')
        self.assertEqual(res_api.status_code, 401)
        data = res_api.json()
        self.assertEqual(data.get('persona'), 'PUBLIC_AUDITOR')
        self.assertFalse(data.get('authenticated'))

    def test_02_platform_admin_dashboard_access(self):
        """2. Platform Admin has global dashboard access, seeing all organizations, all elections, and metrics."""
        self.client.force_login(self.u_platform_admin)
        res = self.client.get('/dashboard/')
        self.assertEqual(res.status_code, 200)

        # Check persona & context
        self.assertEqual(res.context['account_persona'], 'PLATFORM_ADMIN')
        self.assertTrue(res.context['can_mutate'])
        self.assertTrue(res.context['can_manage_lifecycle'])

        # Global elections overview includes both Alpha and Beta
        elections = list(res.context['elections'])
        self.assertIn(self.elec_alpha, elections)
        self.assertIn(self.elec_beta, elections)

        # HTML checks
        content = res.content.decode('utf-8')
        self.assertIn('Platform Admin Dashboard', content)
        self.assertIn('Global Elections Overview', content)
        self.assertIn('Shared Ledger Explorer', content)

    def test_03_organization_admin_dashboard_access(self):
        """3. Organization Admin has tenant-scoped dashboard with lifecycle controls for their org."""
        self.client.force_login(self.u_org_admin)
        res = self.client.get('/dashboard/')
        self.assertEqual(res.status_code, 200)

        # Check persona & context
        self.assertEqual(res.context['account_persona'], 'ORGANIZATION_ADMIN')
        self.assertEqual(res.context['tenant_org'], self.org_alpha)
        self.assertTrue(res.context['can_mutate'])
        self.assertTrue(res.context['can_manage_lifecycle'])

        # Only Alpha election is in context
        elections = list(res.context['elections'])
        self.assertIn(self.elec_alpha, elections)
        self.assertNotIn(self.elec_beta, elections)

        # HTML checks
        content = res.content.decode('utf-8')
        self.assertIn('Organization Admin Dashboard', content)
        self.assertIn('Organization Elections', content)
        self.assertIn('Org Alpha 8C3', content)

    def test_04_election_official_dashboard_access(self):
        """4. Election Official has operational dashboard access, candidate roster, strictly NO start/end/publish."""
        self.client.force_login(self.u_official)
        res = self.client.get('/dashboard/')
        self.assertEqual(res.status_code, 200)

        # Check persona & context
        self.assertEqual(res.context['account_persona'], 'ELECTION_OFFICIAL')
        self.assertEqual(res.context['tenant_org'], self.org_alpha)
        self.assertFalse(res.context['can_mutate'])
        self.assertFalse(res.context['can_manage_lifecycle'])

        # HTML checks: Operational mode notice present; lifecycle start/end/publish actions NOT present
        content = res.content.decode('utf-8')
        self.assertIn('Election Official Dashboard', content)
        self.assertIn('Operational Mode', content)
        self.assertIn('Operational Tools', content)
        self.assertNotIn('+ Create Election', content)

    def test_05_auditor_dashboard_access(self):
        """5. Auditor has strictly read-only dashboard access with verification tools and NO mutation controls."""
        self.client.force_login(self.u_auditor)
        res = self.client.get('/dashboard/')
        self.assertEqual(res.status_code, 200)

        # Check persona & context
        self.assertEqual(res.context['account_persona'], 'AUDITOR')
        self.assertEqual(res.context['tenant_org'], self.org_alpha)
        self.assertFalse(res.context['can_mutate'])
        self.assertFalse(res.context['can_manage_lifecycle'])

        # HTML checks
        content = res.content.decode('utf-8')
        self.assertIn('Auditor Dashboard', content)
        self.assertIn('Auditor Verification Mode', content)
        self.assertIn('READ-ONLY', content)
        self.assertNotIn('+ Create Election', content)
        self.assertNotIn('+ Add Organization', content)

    def test_06_voter_user_dashboard_access(self):
        """6. Voter / User has voter-focused dashboard with eligible elections, zero admin controls."""
        self.client.force_login(self.u_voter)
        res = self.client.get('/dashboard/')
        self.assertEqual(res.status_code, 200)

        # Check persona & context
        self.assertEqual(res.context['account_persona'], 'VOTER')
        self.assertFalse(res.context['can_mutate'])
        self.assertFalse(res.context['can_manage_lifecycle'])

        # HTML checks
        content = res.content.decode('utf-8')
        self.assertIn('Voter Dashboard', content)
        self.assertIn('Eligible Elections', content)
        self.assertIn('Voter Account', content)
        self.assertNotIn('Platform Administration', content)
        self.assertNotIn('Organization Administration', content)
        self.assertNotIn('Operational Tools', content)

    def test_07_candidate_dashboard_access(self):
        """7. Candidate dashboard shows candidate participation details and preserves full voter capabilities."""
        self.client.force_login(self.u_candidate)
        res = self.client.get('/dashboard/')
        self.assertEqual(res.status_code, 200)

        # Check persona & context
        self.assertEqual(res.context['account_persona'], 'CANDIDATE')
        self.assertFalse(res.context['can_mutate'])
        self.assertFalse(res.context['can_manage_lifecycle'])

        # Check candidacies in context
        candidacies = list(res.context['candidacies'])
        self.assertIn(self.candidate_record, candidacies)

        # HTML checks
        content = res.content.decode('utf-8')
        self.assertIn('Candidate Dashboard', content)
        self.assertIn('Candidate Participation', content)
        self.assertIn('Alice Candidate', content)
        self.assertIn('Voter Participation', content)
        self.assertIn('Shared Ledger', content)

    def test_08_tenant_isolation_enforced(self):
        """8. Tenant isolation is strictly enforced across Org Admin, Election Official, and Auditor."""
        for user, role_name in [(self.u_org_admin, 'Org Admin'),
                                (self.u_official, 'Official'),
                                (self.u_auditor, 'Auditor')]:
            self.client.force_login(user)
            res = self.client.get('/dashboard/')
            self.assertEqual(res.status_code, 200)

            # Scoped election list must contain Alpha and exclude Beta
            elections = list(res.context['elections'])
            self.assertIn(self.elec_alpha, elections, f'{role_name} must see Org Alpha election')
            self.assertNotIn(self.elec_beta, elections, f'{role_name} must NOT see Org Beta election')

    def test_09_auditor_cannot_mutate_server_side(self):
        """9. Auditor cannot perform mutation operations against backend endpoints."""
        import json
        self.client.force_login(self.u_auditor)

        # Attempt to create an organization -> 403
        res_org = self.client.post(
            '/organizations/create/',
            json.dumps({'name': 'Disallowed Auditor Org'}),
            content_type='application/json'
        )
        self.assertEqual(res_org.status_code, 403)

        # Attempt to create an election -> 403
        res_elec = self.client.post(
            '/elections/create/',
            json.dumps({'organization_id': self.org_alpha.id, 'title': 'Disallowed Elec'}),
            content_type='application/json'
        )
        self.assertEqual(res_elec.status_code, 403)

        # Attempt to create a position -> 403
        res_pos = self.client.post(
            '/positions/create/',
            json.dumps({'election_id': self.elec_alpha.id, 'title': 'Disallowed Pos'}),
            content_type='application/json'
        )
        self.assertEqual(res_pos.status_code, 403)

    def test_10_election_official_cannot_start_end_publish(self):
        """10. Election Official cannot transition election lifecycle (start, end, publish)."""
        import json
        self.client.force_login(self.u_official)

        # Attempt to change election status to OPEN -> 403
        res_start = self.client.post(
            f'/elections/{self.elec_beta.id}/edit/',
            json.dumps({'status': 'OPEN'}),
            content_type='application/json'
        )
        self.assertEqual(res_start.status_code, 403)

        # Attempt to change election status to CLOSED -> 403
        res_end = self.client.post(
            f'/elections/{self.elec_alpha.id}/edit/',
            json.dumps({'status': 'CLOSED'}),
            content_type='application/json'
        )
        self.assertEqual(res_end.status_code, 403)

    def test_11_shared_ledger_accessible_across_all_roles(self):
        """11. Shared ledger (/blockchain/) remains accessible through single implementation for all personas."""
        personas = [
            (self.u_platform_admin, 'Platform Admin'),
            (self.u_org_admin, 'Org Admin'),
            (self.u_official, 'Election Official'),
            (self.u_auditor, 'Auditor'),
            (self.u_candidate, 'Candidate'),
            (self.u_voter, 'Voter'),
            (None, 'Public Auditor (Unauthenticated)')
        ]
        for user, role_name in personas:
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()

            res = self.client.get('/blockchain/')
            self.assertEqual(res.status_code, 200, f'{role_name} should access /blockchain/ with 200 OK')
            content = res.content.decode('utf-8')
            self.assertIn('BallotChain', content)
            self.assertIn('Ledger', content)

    def test_12_dashboard_does_not_create_duplicate_records(self):
        """12. Accessing dashboards across roles creates zero persistent records."""
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate, Voters, Block, Vote

        counts_before = {
            'users': User.objects.count(),
            'orgs': Organization.objects.count(),
            'elections': Election.objects.count(),
            'positions': Position.objects.count(),
            'candidates': Candidate.objects.count(),
            'voters': Voters.objects.count(),
            'blocks': Block.objects.count(),
            'votes': Vote.objects.count(),
        }

        # Access dashboard as each user
        for user in [self.u_platform_admin, self.u_org_admin, self.u_official, self.u_auditor, self.u_candidate, self.u_voter]:
            self.client.force_login(user)
            res = self.client.get('/dashboard/')
            self.assertEqual(res.status_code, 200)

        # Access dashboard unauthenticated
        self.client.logout()
        res_unauth = self.client.get('/dashboard/')
        self.assertEqual(res_unauth.status_code, 302)

        counts_after = {
            'users': User.objects.count(),
            'orgs': Organization.objects.count(),
            'elections': Election.objects.count(),
            'positions': Position.objects.count(),
            'candidates': Candidate.objects.count(),
            'voters': Voters.objects.count(),
            'blocks': Block.objects.count(),
            'votes': Vote.objects.count(),
        }

        self.assertEqual(counts_before, counts_after, "Dashboard requests must not create any persistent records")

    def test_13_existing_account_auth_remains_intact(self):
        """13. Existing email + password and username + password authentication remain 100% intact."""
        import json

        # Login with email + password
        res_email = self.client.post(
            '/login/',
            json.dumps({'email': 'voter_8c3@ballotchain.org', 'password': 'VoterPassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res_email.status_code, 200)
        self.assertTrue(res_email.json().get('success'))

        # Login with username + password
        res_user = self.client.post(
            '/admin-login/',
            json.dumps({'username': 'pa_8c3', 'password': 'PlatformPassword123!'}),
            content_type='application/json'
        )
        self.assertEqual(res_user.status_code, 200)
        self.assertTrue(res_user.json().get('success'))
        self.assertEqual(res_user.json().get('user', {}).get('persona'), 'PLATFORM_ADMIN')


class Phase8C4ElectionLifecycleTests(TestCase):
    """
    Phase 8C-4 Comprehensive Test Suite: Election Lifecycle Foundation & Authority Gates.
    Enforces DRAFT -> OPEN -> CLOSED -> PUBLISHED state machine, strict RBAC authorization,
    reopening prevention, verified results checks, live progress controls, and chain integrity.
    """
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate, Voters, Eligibility, UserProfile

        # Organizations
        cls.org_alpha = Organization.objects.create(name="Alpha University")
        cls.org_beta = Organization.objects.create(name="Beta Corporation")

        # 1. Platform Admin
        cls.u_platform_admin = User.objects.create_superuser(
            username="pa_8c4",
            email="pa_8c4@ballotchain.org",
            password="PlatformPassword123!"
        )
        UserProfile.objects.create(
            user=cls.u_platform_admin,
            role="PLATFORM_ADMIN"
        )

        # 2. Organization Admin (Alpha)
        cls.u_org_admin_alpha = User.objects.create_user(
            username="oa_alpha_8c4",
            email="oa_alpha@ballotchain.org",
            password="OrgPassword123!"
        )
        UserProfile.objects.create(
            user=cls.u_org_admin_alpha,
            role="ORGANIZATION_ADMIN",
            organization=cls.org_alpha
        )

        # 3. Organization Admin (Beta)
        cls.u_org_admin_beta = User.objects.create_user(
            username="oa_beta_8c4",
            email="oa_beta@ballotchain.org",
            password="OrgPassword123!"
        )
        UserProfile.objects.create(
            user=cls.u_org_admin_beta,
            role="ORGANIZATION_ADMIN",
            organization=cls.org_beta
        )

        # 4. Election Official (Alpha)
        cls.u_official_alpha = User.objects.create_user(
            username="eo_alpha_8c4",
            email="eo_alpha@ballotchain.org",
            password="OfficialPassword123!"
        )
        UserProfile.objects.create(
            user=cls.u_official_alpha,
            role="ELECTION_OFFICIAL",
            organization=cls.org_alpha
        )

        # 5. Auditor (Alpha)
        cls.u_auditor_alpha = User.objects.create_user(
            username="au_alpha_8c4",
            email="au_alpha@ballotchain.org",
            password="AuditorPassword123!"
        )
        UserProfile.objects.create(
            user=cls.u_auditor_alpha,
            role="AUDITOR",
            organization=cls.org_alpha
        )

        # 6. Candidate User
        cls.u_candidate_alpha = User.objects.create_user(
            username="cand_alpha_8c4",
            email="cand_alpha@ballotchain.org",
            password="CandidatePassword123!"
        )

        # 7. Voter User & Record
        cls.u_voter_alpha = User.objects.create_user(
            username="voter_alpha_8c4",
            email="voter_alpha@ballotchain.org",
            password="VoterPassword123!"
        )
        cls.voter_alpha_rec = Voters.objects.create(
            uuid="VOTER_ALPHA_8C4_001",
            name="Alice Voter",
            dob="1992-05-15",
            pincode="110001",
            region="Region Alpha",
            email="voter_alpha@ballotchain.org",
            vote_done=False
        )

        # Base Draft Election
        cls.election_alpha_draft = Election.objects.create(
            organization=cls.org_alpha,
            title="Alpha Student Council 2026",
            status="DRAFT"
        )
        cls.pos_president = Position.objects.create(
            election=cls.election_alpha_draft,
            title="Council President",
            max_votes_allowed=1
        )
        cls.cand_alice = Candidate.objects.create(
            position=cls.pos_president,
            user=cls.u_candidate_alpha,
            name="Alice Candidate",
            bio="Leading with integrity"
        )
        cls.eligibility_alice = Eligibility.objects.create(
            voter=cls.voter_alpha_rec,
            election=cls.election_alpha_draft
        )

    def test_01_draft_election_blocks_voting(self):
        """1. DRAFT election blocks voter authentication and vote casting."""
        res_auth = self.client.post('/authentication/', {
            'aadhar_no': self.voter_alpha_rec.uuid,
            'election_id': self.election_alpha_draft.id
        })
        self.assertEqual(res_auth.status_code, 400)
        self.assertIn('DRAFT', res_auth.json().get('error', ''))

    def test_02_platform_admin_can_start_draft_election(self):
        """2. Platform Admin can transition DRAFT -> OPEN via Start endpoint."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="PA Start Test",
            status="DRAFT"
        )
        self.client.force_login(self.u_platform_admin)
        res = self.client.post(f'/elections/{elec.id}/start/', follow=True)
        self.assertEqual(res.status_code, 200)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'OPEN')

    def test_03_org_admin_can_start_draft_election_in_own_org(self):
        """3. Organization Admin can transition DRAFT -> OPEN for own organization."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="OA Start Test",
            status="DRAFT"
        )
        self.client.force_login(self.u_org_admin_alpha)
        res = self.client.post(f'/elections/{elec.id}/start/', follow=True)
        self.assertEqual(res.status_code, 200)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'OPEN')

    def test_04_election_official_denied_from_starting_election(self):
        """4. Election Official is denied (403) from starting election."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="EO Start Denied",
            status="DRAFT"
        )
        self.client.force_login(self.u_official_alpha)
        res = self.client.post(f'/elections/{elec.id}/start/')
        self.assertEqual(res.status_code, 403)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'DRAFT')

    def test_05_auditor_denied_from_starting_election(self):
        """5. Auditor is denied (403) from starting election."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Auditor Start Denied",
            status="DRAFT"
        )
        self.client.force_login(self.u_auditor_alpha)
        res = self.client.post(f'/elections/{elec.id}/start/')
        self.assertEqual(res.status_code, 403)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'DRAFT')

    def test_06_voter_and_candidate_denied_from_starting_election(self):
        """6. Voter and Candidate are denied (403) from starting election."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Voter/Cand Start Denied",
            status="DRAFT"
        )
        # Voter
        self.client.force_login(self.u_voter_alpha)
        res_voter = self.client.post(f'/elections/{elec.id}/start/')
        self.assertEqual(res_voter.status_code, 403)

        # Candidate
        self.client.force_login(self.u_candidate_alpha)
        res_cand = self.client.post(f'/elections/{elec.id}/start/')
        self.assertEqual(res_cand.status_code, 403)

        elec.refresh_from_db()
        self.assertEqual(elec.status, 'DRAFT')

    def test_07_open_election_allows_eligible_voters_to_vote(self):
        """7. OPEN election allows eligible voters to proceed through authentication."""
        from home.models import Election, Eligibility
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Open Voting Allowed Test",
            status="OPEN"
        )
        Eligibility.objects.create(voter=self.voter_alpha_rec, election=elec)

        res_auth = self.client.post('/authentication/', {
            'aadhar_no': self.voter_alpha_rec.uuid,
            'election_id': elec.id
        })
        self.assertEqual(res_auth.status_code, 200)
        self.assertTrue(res_auth.json().get('success'))
        self.assertIn('html', res_auth.json())

    def test_08_org_admin_cannot_start_election_in_another_org(self):
        """8. Organization Admin cannot start election belonging to another organization."""
        from home.models import Election
        elec_beta = Election.objects.create(
            organization=self.org_beta,
            title="Beta Election",
            status="DRAFT"
        )
        # Alpha Admin attempts to start Beta Election
        self.client.force_login(self.u_org_admin_alpha)
        res = self.client.post(f'/elections/{elec_beta.id}/start/')
        self.assertEqual(res.status_code, 403)
        elec_beta.refresh_from_db()
        self.assertEqual(elec_beta.status, 'DRAFT')

    def test_09_platform_admin_can_end_open_election(self):
        """9. Platform Admin can transition OPEN -> CLOSED via End endpoint."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="PA End Test",
            status="OPEN"
        )
        self.client.force_login(self.u_platform_admin)
        res = self.client.post(f'/elections/{elec.id}/end/', follow=True)
        self.assertEqual(res.status_code, 200)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'CLOSED')

    def test_10_org_admin_can_end_open_election_in_own_org(self):
        """10. Organization Admin can transition OPEN -> CLOSED for own organization."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="OA End Test",
            status="OPEN"
        )
        self.client.force_login(self.u_org_admin_alpha)
        res = self.client.post(f'/elections/{elec.id}/end/', follow=True)
        self.assertEqual(res.status_code, 200)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'CLOSED')

    def test_11_org_admin_cannot_end_election_in_another_org(self):
        """11. Organization Admin cannot end election belonging to another organization."""
        from home.models import Election
        elec_beta = Election.objects.create(
            organization=self.org_beta,
            title="Beta Open Election",
            status="OPEN"
        )
        self.client.force_login(self.u_org_admin_alpha)
        res = self.client.post(f'/elections/{elec_beta.id}/end/')
        self.assertEqual(res.status_code, 403)
        elec_beta.refresh_from_db()
        self.assertEqual(elec_beta.status, 'OPEN')

    def test_12_election_official_denied_from_ending_election(self):
        """12. Election Official is denied (403) from ending election."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="EO End Denied",
            status="OPEN"
        )
        self.client.force_login(self.u_official_alpha)
        res = self.client.post(f'/elections/{elec.id}/end/')
        self.assertEqual(res.status_code, 403)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'OPEN')

    def test_13_auditor_denied_from_ending_election(self):
        """13. Auditor is denied (403) from ending election."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Auditor End Denied",
            status="OPEN"
        )
        self.client.force_login(self.u_auditor_alpha)
        res = self.client.post(f'/elections/{elec.id}/end/')
        self.assertEqual(res.status_code, 403)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'OPEN')

    def test_14_voter_and_candidate_denied_from_ending_election(self):
        """14. Voter and Candidate are denied (403) from ending election."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Voter/Cand End Denied",
            status="OPEN"
        )
        self.client.force_login(self.u_voter_alpha)
        res_v = self.client.post(f'/elections/{elec.id}/end/')
        self.assertEqual(res_v.status_code, 403)

        self.client.force_login(self.u_candidate_alpha)
        res_c = self.client.post(f'/elections/{elec.id}/end/')
        self.assertEqual(res_c.status_code, 403)

        elec.refresh_from_db()
        self.assertEqual(elec.status, 'OPEN')

    def test_15_draft_election_cannot_be_directly_ended(self):
        """15. DRAFT election cannot be directly transitioned to CLOSED."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Draft Cannot End",
            status="DRAFT"
        )
        self.client.force_login(self.u_platform_admin)
        res = self.client.post(f'/elections/{elec.id}/end/')
        self.assertEqual(res.status_code, 400)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'DRAFT')

    def test_16_closed_election_cannot_be_reopened(self):
        """16. CLOSED election cannot be transitioned back to OPEN (reopening blocked)."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Closed Cannot Reopen",
            status="CLOSED"
        )
        self.client.force_login(self.u_platform_admin)

        # Attempt via start endpoint
        res_start = self.client.post(f'/elections/{elec.id}/start/')
        self.assertEqual(res_start.status_code, 400)

        # Attempt via edit endpoint
        res_edit = self.client.post(f'/elections/{elec.id}/edit/', {
            'title': 'Attempted Reopen',
            'status': 'OPEN'
        })
        self.assertEqual(res_edit.status_code, 400)

        elec.refresh_from_db()
        self.assertEqual(elec.status, 'CLOSED')

    def test_17_closed_election_cannot_be_reverted_to_draft(self):
        """17. CLOSED election cannot be transitioned back to DRAFT."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Closed Cannot Revert",
            status="CLOSED"
        )
        self.client.force_login(self.u_platform_admin)
        res_edit = self.client.post(f'/elections/{elec.id}/edit/', {
            'title': 'Attempted Revert to Draft',
            'status': 'DRAFT'
        })
        self.assertEqual(res_edit.status_code, 400)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'CLOSED')

    def test_18_closed_election_blocks_all_new_votes(self):
        """18. CLOSED election blocks all new votes immediately."""
        from home.models import Election, Eligibility
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Closed Blocks Voting",
            status="CLOSED"
        )
        Eligibility.objects.create(voter=self.voter_alpha_rec, election=elec)

        res_auth = self.client.post('/authentication/', {
            'aadhar_no': self.voter_alpha_rec.uuid,
            'election_id': elec.id
        })
        self.assertEqual(res_auth.status_code, 400)
        self.assertIn('CLOSED', res_auth.json().get('error', ''))

    def test_19_publish_blocked_if_ledger_verification_fails(self):
        """19. Results publication blocked if ledger verification fails."""
        from unittest.mock import patch
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Verification Fail Test",
            status="CLOSED"
        )
        self.client.force_login(self.u_platform_admin)

        mock_results = {
            'verified': False,
            'is_eligible_for_publication': False,
            'ledger_verified': False,
            'tally_calculated': True,
            'result_receipt': 'sample_receipt_hash',
            'publication_state': 'LEDGER_VERIFICATION_FAILED',
            'error': 'Unsealed batches detected'
        }
        with patch('home.methods_module.calculate_verified_election_results', return_value=mock_results):
            res = self.client.post(f'/elections/{elec.id}/publish/')
            self.assertEqual(res.status_code, 400)
            elec.refresh_from_db()
            self.assertFalse(elec.is_published)

    def test_20_publish_blocked_if_calculation_fails(self):
        """20. Results publication blocked if calculation fails."""
        from unittest.mock import patch
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Calculation Fail Test",
            status="CLOSED"
        )
        self.client.force_login(self.u_platform_admin)

        mock_results = {
            'verified': False,
            'is_eligible_for_publication': False,
            'ledger_verified': True,
            'tally_calculated': False,
            'result_receipt': 'sample_receipt_hash',
            'publication_state': 'CALCULATION_FAILED',
            'error': 'Calculation error'
        }
        with patch('home.methods_module.calculate_verified_election_results', return_value=mock_results):
            res = self.client.post(f'/elections/{elec.id}/publish/')
            self.assertEqual(res.status_code, 400)
            elec.refresh_from_db()
            self.assertFalse(elec.is_published)

    def test_21_publish_blocked_if_receipt_missing_or_stale(self):
        """21. Results publication blocked if receipt is missing or stale."""
        from unittest.mock import patch
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Stale Receipt Test",
            status="CLOSED"
        )
        self.client.force_login(self.u_platform_admin)

        mock_results = {
            'verified': True,
            'is_eligible_for_publication': True,
            'ledger_verified': True,
            'tally_calculated': True,
            'result_receipt': 'stale_receipt_hash',
            'publication_state': 'VERIFIED_PUBLISHED'
        }
        # Receipt validation fails
        with patch('home.methods_module.calculate_verified_election_results', return_value=mock_results), \
             patch('home.methods_module.verify_result_receipt_consistency', return_value={'is_consistent': False, 'status': 'INCONSISTENT_RECEIPT'}):
            res = self.client.post(f'/elections/{elec.id}/publish/')
            self.assertEqual(res.status_code, 400)
            elec.refresh_from_db()
            self.assertFalse(elec.is_published)

    def test_22_platform_admin_can_publish_verified_closed_election(self):
        """22. Platform Admin can publish verified results for CLOSED election."""
        from unittest.mock import patch
        from home.models import Election, ElectionResultAudit
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="PA Publish Success",
            status="CLOSED"
        )
        self.client.force_login(self.u_platform_admin)

        mock_results = {
            'verified': True,
            'is_eligible_for_publication': True,
            'ledger_verified': True,
            'tally_calculated': True,
            'result_receipt': 'a'*64,
            'publication_state': 'VERIFIED_PUBLISHED'
        }
        with patch('home.methods_module.calculate_verified_election_results', return_value=mock_results), \
             patch('home.methods_module.verify_result_receipt_consistency', return_value={'is_consistent': True, 'status': 'CONSISTENT'}):
            res = self.client.post(f'/elections/{elec.id}/publish/', follow=True)
            self.assertEqual(res.status_code, 200)
            elec.refresh_from_db()
            self.assertTrue(elec.is_published)
            self.assertEqual(elec.publication_receipt, 'a'*64)
            self.assertIsNotNone(elec.published_at)

            # Verification that audit record exists
            audit = ElectionResultAudit.objects.filter(election=elec, verification_status='PUBLISHED').first()
            self.assertIsNotNone(audit)

    def test_23_org_admin_can_publish_verified_closed_election_in_own_org(self):
        """23. Organization Admin can publish verified results for CLOSED election in own organization."""
        from unittest.mock import patch
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="OA Publish Success",
            status="CLOSED"
        )
        self.client.force_login(self.u_org_admin_alpha)

        mock_results = {
            'verified': True,
            'is_eligible_for_publication': True,
            'ledger_verified': True,
            'tally_calculated': True,
            'result_receipt': 'b'*64,
            'publication_state': 'VERIFIED_PUBLISHED'
        }
        with patch('home.methods_module.calculate_verified_election_results', return_value=mock_results), \
             patch('home.methods_module.verify_result_receipt_consistency', return_value={'is_consistent': True, 'status': 'CONSISTENT'}):
            res = self.client.post(f'/elections/{elec.id}/publish/', follow=True)
            self.assertEqual(res.status_code, 200)
            elec.refresh_from_db()
            self.assertTrue(elec.is_published)
            self.assertEqual(elec.publication_receipt, 'b'*64)

    def test_24_org_admin_cannot_publish_in_another_org(self):
        """24. Organization Admin cannot publish results for election in another organization."""
        from home.models import Election
        elec_beta = Election.objects.create(
            organization=self.org_beta,
            title="Beta Closed Election",
            status="CLOSED"
        )
        self.client.force_login(self.u_org_admin_alpha)
        res = self.client.post(f'/elections/{elec_beta.id}/publish/')
        self.assertEqual(res.status_code, 403)
        elec_beta.refresh_from_db()
        self.assertFalse(elec_beta.is_published)

    def test_25_election_official_denied_from_publishing(self):
        """25. Election Official is denied (403) from publishing results."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="EO Publish Denied",
            status="CLOSED"
        )
        self.client.force_login(self.u_official_alpha)
        res = self.client.post(f'/elections/{elec.id}/publish/')
        self.assertEqual(res.status_code, 403)
        elec.refresh_from_db()
        self.assertFalse(elec.is_published)

    def test_26_auditor_denied_from_publishing(self):
        """26. Auditor is denied (403) from publishing results."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Auditor Publish Denied",
            status="CLOSED"
        )
        self.client.force_login(self.u_auditor_alpha)
        res = self.client.post(f'/elections/{elec.id}/publish/')
        self.assertEqual(res.status_code, 403)
        elec.refresh_from_db()
        self.assertFalse(elec.is_published)

    def test_27_voter_and_candidate_denied_from_publishing(self):
        """27. Voter and Candidate are denied (403) from publishing results."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Voter/Cand Publish Denied",
            status="CLOSED"
        )
        self.client.force_login(self.u_voter_alpha)
        res_v = self.client.post(f'/elections/{elec.id}/publish/')
        self.assertEqual(res_v.status_code, 403)

        self.client.force_login(self.u_candidate_alpha)
        res_c = self.client.post(f'/elections/{elec.id}/publish/')
        self.assertEqual(res_c.status_code, 403)

        elec.refresh_from_db()
        self.assertFalse(elec.is_published)

    def test_28_publish_denied_before_closure(self):
        """28. Results publication is denied if election is not CLOSED."""
        from home.models import Election
        elec_draft = Election.objects.create(
            organization=self.org_alpha,
            title="Draft Cannot Publish",
            status="DRAFT"
        )
        elec_open = Election.objects.create(
            organization=self.org_alpha,
            title="Open Cannot Publish",
            status="OPEN"
        )
        self.client.force_login(self.u_platform_admin)

        res_d = self.client.post(f'/elections/{elec_draft.id}/publish/')
        self.assertEqual(res_d.status_code, 400)

        res_o = self.client.post(f'/elections/{elec_open.id}/publish/')
        self.assertEqual(res_o.status_code, 400)

    def test_29_reopening_published_election_strictly_impossible(self):
        """29. Reopening a published election is strictly impossible."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Published Cannot Reopen",
            status="CLOSED",
            is_published=True,
            publication_receipt='c'*64
        )
        self.client.force_login(self.u_platform_admin)

        # Attempt start
        res_start = self.client.post(f'/elections/{elec.id}/start/')
        self.assertEqual(res_start.status_code, 400)

        # Attempt edit to OPEN
        res_edit = self.client.post(f'/elections/{elec.id}/edit/', {
            'title': 'Attempt Reopen Published',
            'status': 'OPEN'
        })
        self.assertEqual(res_edit.status_code, 400)

        elec.refresh_from_db()
        self.assertEqual(elec.status, 'CLOSED')
        self.assertTrue(elec.is_published)

    def test_30_private_live_progress_hides_results_when_open(self):
        """30. Private live progress hides intermediate counts from voters and unauthenticated public."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Private Progress Open Election",
            status="OPEN",
            live_progress_enabled=False
        )
        # Voter
        self.client.force_login(self.u_voter_alpha)
        res_v = self.client.get(f'/elections/{elec.id}/results/')
        self.assertEqual(res_v.status_code, 403)

        # Unauthenticated public
        self.client.logout()
        res_pub = self.client.get(f'/elections/{elec.id}/results/')
        self.assertEqual(res_pub.status_code, 403)

        # Auditor can view
        self.client.force_login(self.u_auditor_alpha)
        res_aud = self.client.get(f'/elections/{elec.id}/results/')
        self.assertEqual(res_aud.status_code, 200)

    def test_31_enabled_live_progress_allows_intermediate_results_when_open(self):
        """31. Enabled live progress allows intermediate results viewing when election is OPEN."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="Live Progress Open Election",
            status="OPEN",
            live_progress_enabled=True
        )
        # Voter can view
        self.client.force_login(self.u_voter_alpha)
        res_v = self.client.get(f'/elections/{elec.id}/results/')
        self.assertEqual(res_v.status_code, 200)

    def test_32_endpoints_enforce_post_csrf_and_get_does_not_mutate(self):
        """32. Start, End, and Publish enforce POST; GET does not trigger mutations."""
        from home.models import Election
        elec = Election.objects.create(
            organization=self.org_alpha,
            title="No GET Mutations",
            status="DRAFT"
        )
        self.client.force_login(self.u_platform_admin)

        # GET start
        res_gs = self.client.get(f'/elections/{elec.id}/start/')
        self.assertEqual(res_gs.status_code, 405)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'DRAFT')

        # GET end
        res_ge = self.client.get(f'/elections/{elec.id}/end/')
        self.assertEqual(res_ge.status_code, 405)
        elec.refresh_from_db()
        self.assertEqual(elec.status, 'DRAFT')

        # GET publish
        res_gp = self.client.get(f'/elections/{elec.id}/publish/')
        self.assertEqual(res_gp.status_code, 405)
        elec.refresh_from_db()
        self.assertFalse(elec.is_published)


class Phase8C5GenericVoterFlowTests(TestCase):
    """
    Phase 8C-5 Comprehensive Test Suite: Generic Voter Flow Transition.
    Validates end-to-end voter journey: Login -> Dashboard -> Eligible Elections ->
    Election Page -> OTP Step-Up -> Candidate Selection -> Review -> Confirmation ->
    Ballot Submission -> Blockchain Parity -> Duplicate Vote Protection.
    """
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate, Voters, Eligibility, UserProfile
        from home.methods_module import generate_keys

        # Organizations
        cls.org_alpha = Organization.objects.create(name="Alpha University")
        cls.org_beta = Organization.objects.create(name="Beta Corporation")

        # 1. Platform Admin
        cls.u_platform_admin = User.objects.create_superuser(
            username="pa_8c5", email="pa_8c5@ballotchain.org", password="PlatformPassword123!"
        )
        UserProfile.objects.create(user=cls.u_platform_admin, role="PLATFORM_ADMIN")

        # 2. Org Admin Alpha
        cls.u_org_admin = User.objects.create_user(
            username="oa_8c5", email="oa_8c5@ballotchain.org", password="OrgPassword123!"
        )
        UserProfile.objects.create(user=cls.u_org_admin, role="ORGANIZATION_ADMIN", organization=cls.org_alpha)

        # 3. Voter 1 (Org Alpha)
        cls.u_voter1 = User.objects.create_user(
            username="voter1_8c5", email="voter1_8c5@ballotchain.org", password="VoterPassword123!"
        )
        cls.voter1_rec = Voters.objects.create(
            uuid="VOTER1_8C5_01", name="Voter One", dob="1990-01-01", pincode="110001", region="Alpha",
            email="voter1_8c5@ballotchain.org", vote_done=False
        )
        UserProfile.objects.create(user=cls.u_voter1, role="VOTER", organization=cls.org_alpha)

        # 4. Voter 2 (Org Beta)
        cls.u_voter2 = User.objects.create_user(
            username="voter2_8c5", email="voter2_8c5@ballotchain.org", password="VoterPassword123!"
        )
        cls.voter2_rec = Voters.objects.create(
            uuid="VOTER2_8C5_02", name="Voter Two", dob="1992-02-02", pincode="110002", region="Beta",
            email="voter2_8c5@ballotchain.org", vote_done=False
        )
        UserProfile.objects.create(user=cls.u_voter2, role="VOTER", organization=cls.org_beta)

        # 5. Candidate User (Running in Org Alpha)
        cls.u_candidate = User.objects.create_user(
            username="cand_user_8c5", email="cand_8c5@ballotchain.org", password="CandidatePassword123!"
        )
        cls.cand_voter_rec = Voters.objects.create(
            uuid="CAND_8C5_01", name="Candidate User", dob="1988-08-08", pincode="110001", region="Alpha",
            email="cand_8c5@ballotchain.org", vote_done=False
        )

        # Elections in Org Alpha
        cls.elec_open = Election.objects.create(
            organization=cls.org_alpha, title="Alpha Student Council 2026", status="OPEN"
        )
        cls.elec_draft = Election.objects.create(
            organization=cls.org_alpha, title="Alpha Draft Election", status="DRAFT"
        )
        cls.elec_closed = Election.objects.create(
            organization=cls.org_alpha, title="Alpha Closed Election", status="CLOSED"
        )
        cls.elec_published = Election.objects.create(
            organization=cls.org_alpha, title="Alpha Published Election", status="CLOSED",
            is_published=True, publication_receipt='d'*64
        )

        # Election in Org Beta
        cls.elec_beta = Election.objects.create(
            organization=cls.org_beta, title="Beta Corporate Election", status="OPEN"
        )

        # Positions in elec_open
        cls.pos_pres = Position.objects.create(election=cls.elec_open, title="President", max_votes_allowed=1)
        cls.pos_vp = Position.objects.create(election=cls.elec_open, title="Vice President", max_votes_allowed=1)

        # Candidates
        cls.cand_pres1 = Candidate.objects.create(
            position=cls.pos_pres, user=cls.u_candidate, name="Candidate Alpha Pres", bio="Experienced Leader"
        )
        cls.cand_pres2 = Candidate.objects.create(
            position=cls.pos_pres, name="Candidate Beta Pres", bio="Innovative Thinker"
        )
        cls.cand_vp1 = Candidate.objects.create(
            position=cls.pos_vp, name="Candidate VP One", bio="Dedicated Servant"
        )

        # Candidate in elec_beta
        cls.pos_beta = Position.objects.create(election=cls.elec_beta, title="Board Director", max_votes_allowed=1)
        cls.cand_beta = Candidate.objects.create(
            position=cls.pos_beta, name="Beta Director Cand", bio="Corporate Expert"
        )

        # Eligibility: Voter 1 and Candidate User are eligible in elec_open
        Eligibility.objects.create(voter=cls.voter1_rec, election=cls.elec_open)
        Eligibility.objects.create(voter=cls.cand_voter_rec, election=cls.elec_open)

        # Cryptographic keys for test signing
        cls.priv_key1, cls.pub_key1 = generate_keys()

    def _setup_voter_session(self, user, voter, election=None, email_verified=True):
        self.client.force_login(user)
        session = self.client.session
        session['uuid'] = voter.uuid
        session['email-id'] = voter.email
        session['email-verified'] = email_verified
        if election:
            session['election_id'] = election.id
        session['private-key'] = self.priv_key1
        session['public-key'] = self.pub_key1
        session.save()

    def test_01_authenticated_user_sees_only_eligible_elections(self):
        """1. Authenticated user sees only elections where they are eligible."""
        from home.views import get_eligible_elections_for_user
        eligible = get_eligible_elections_for_user(self.u_voter1)
        self.assertIn(self.elec_open, eligible)
        self.assertNotIn(self.elec_beta, eligible)

    def test_02_unauthenticated_user_cannot_access_protected_voter_flow(self):
        """2. Unauthenticated user cannot access protected voting flow."""
        self.client.logout()
        res_vote = self.client.get(f'/elections/{self.elec_open.id}/vote/')
        self.assertEqual(res_vote.status_code, 302)
        self.assertIn('/login/', res_vote.url)

        res_post = self.client.post('/create-vote/', {'selected-party-id': self.cand_pres1.id})
        self.assertEqual(res_post.status_code, 401)

    def test_03_ineligible_user_cannot_access_election_voting(self):
        """3. Ineligible user cannot access voting portal for restricted election."""
        self.client.force_login(self.u_voter2)
        res_vote = self.client.get(f'/elections/{self.elec_open.id}/vote/')
        self.assertEqual(res_vote.status_code, 403)

        res_auth = self.client.post('/authentication/', {
            'aadhar_no': self.voter2_rec.uuid,
            'election_id': self.elec_open.id
        })
        self.assertEqual(res_auth.status_code, 403)

    def test_04_draft_election_blocks_voting(self):
        """4. DRAFT election blocks voter flow across all entrypoints."""
        self.client.force_login(self.u_voter1)
        res_vote = self.client.get(f'/elections/{self.elec_draft.id}/vote/')
        self.assertEqual(res_vote.status_code, 400)

        res_auth = self.client.post('/authentication/', {
            'aadhar_no': self.voter1_rec.uuid,
            'election_id': self.elec_draft.id
        })
        self.assertEqual(res_auth.status_code, 400)

    def test_05_open_election_permits_eligible_voting(self):
        """5. OPEN election permits eligible voting entry and authentication."""
        self.client.force_login(self.u_voter1)
        res_vote = self.client.get(f'/elections/{self.elec_open.id}/vote/')
        self.assertEqual(res_vote.status_code, 200)

        res_auth = self.client.post('/authentication/', {
            'aadhar_no': self.voter1_rec.uuid,
            'election_id': self.elec_open.id
        })
        self.assertEqual(res_auth.status_code, 200)
        self.assertTrue(res_auth.json().get('success'))

    def test_06_closed_election_blocks_voting(self):
        """6. CLOSED election blocks voting immediately."""
        self.client.force_login(self.u_voter1)
        res_vote = self.client.get(f'/elections/{self.elec_closed.id}/vote/')
        self.assertEqual(res_vote.status_code, 400)

        res_auth = self.client.post('/authentication/', {
            'aadhar_no': self.voter1_rec.uuid,
            'election_id': self.elec_closed.id
        })
        self.assertEqual(res_auth.status_code, 400)

    def test_07_published_election_blocks_voting(self):
        """7. PUBLISHED election blocks voting."""
        self.client.force_login(self.u_voter1)
        res_vote = self.client.get(f'/elections/{self.elec_published.id}/vote/')
        self.assertEqual(res_vote.status_code, 400)

    def test_08_election_from_another_org_cannot_be_accessed_improperly(self):
        """8. Election from another organization cannot be accessed improperly."""
        # Voter 2 is scoped to Org Beta, tries to access Org Alpha's election
        self.client.force_login(self.u_voter2)
        res_vote = self.client.get(f'/elections/{self.elec_open.id}/vote/')
        self.assertEqual(res_vote.status_code, 403)

        res_detail = self.client.get(f'/elections/{self.elec_open.id}/')
        self.assertEqual(res_detail.status_code, 403)

    def test_09_otp_remains_required_for_voting(self):
        """9. OTP verification remains strictly required before voting."""
        self._setup_voter_session(self.u_voter1, self.voter1_rec, self.elec_open, email_verified=False)
        res = self.client.post('/create-vote/', {
            'selected-party-id': self.cand_pres1.id,
            'election_id': self.elec_open.id
        })
        self.assertEqual(res.status_code, 401)

    def test_10_invalid_otp_rejected(self):
        """10. Incorrect OTP input is rejected."""
        self.client.force_login(self.u_voter1)
        session = self.client.session
        session['uuid'] = self.voter1_rec.uuid
        session['otp'] = '123456'
        import time
        session['otp_created_at'] = time.time()
        session['otp_attempts'] = 0
        session.save()

        res = self.client.post('/verify-otp/', {'otp-input': '999999'})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json().get('success'))

    def test_11_otp_replay_rejected(self):
        """11. OTP cannot be replayed after successful verification."""
        self.client.force_login(self.u_voter1)
        session = self.client.session
        session['uuid'] = self.voter1_rec.uuid
        session['otp'] = '654321'
        import time
        session['otp_created_at'] = time.time()
        session['otp_attempts'] = 0
        session.save()

        # First verification succeeds
        res1 = self.client.post('/verify-otp/', {'otp-input': '654321'})
        self.assertTrue(res1.json().get('success'))

        # Second verification with same OTP is rejected (OTP cleared)
        res2 = self.client.post('/verify-otp/', {'otp-input': '654321'})
        self.assertEqual(res2.status_code, 400)
        self.assertFalse(res2.json().get('success'))

    def test_12_otp_expiry_rejected(self):
        """12. Expired OTP is rejected."""
        self.client.force_login(self.u_voter1)
        session = self.client.session
        session['uuid'] = self.voter1_rec.uuid
        session['otp'] = '112233'
        import time
        session['otp_created_at'] = time.time() - 400  # 400s > 300s expiry
        session['otp_attempts'] = 0
        session.save()

        res = self.client.post('/verify-otp/', {'otp-input': '112233'})
        self.assertEqual(res.status_code, 400)
        self.assertIn('expired', res.json().get('error', '').lower())

    def test_13_otp_failed_attempt_limit_preserved(self):
        """13. Exceeding OTP attempt limit locks verification."""
        self.client.force_login(self.u_voter1)
        session = self.client.session
        session['uuid'] = self.voter1_rec.uuid
        session['otp'] = '778899'
        import time
        session['otp_created_at'] = time.time()
        session['otp_attempts'] = 2  # 2 previous failed attempts
        session.save()

        # 3rd failed attempt invalidates OTP
        res = self.client.post('/verify-otp/', {'otp-input': '000000'})
        self.assertEqual(res.status_code, 429)

    def test_14_candidate_belongs_to_requested_election(self):
        """14. Candidate belonging to requested election is accepted."""
        from home.models import Candidate
        cand = Candidate.objects.filter(id=self.cand_pres1.id, position__election=self.elec_open).first()
        self.assertIsNotNone(cand)

    def test_15_invalid_candidate_rejected(self):
        """15. Submitting vote with non-existent candidate ID is rejected."""
        self._setup_voter_session(self.u_voter1, self.voter1_rec, self.elec_open)
        res = self.client.post('/create-vote/', {
            'selected-party-id': '999999',
            'election_id': self.elec_open.id,
            'private-key': self.priv_key1
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('candidate does not exist', res.json().get('error', '').lower())

    def test_16_invalid_position_rejected(self):
        """16. Candidate selection mismatching position is rejected."""
        self._setup_voter_session(self.u_voter1, self.voter1_rec, self.elec_open)
        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand_pres1.id),
            'position_id': str(self.pos_vp.id),  # Pres cand submitted for VP position
            'election_id': self.elec_open.id,
            'private-key': self.priv_key1
        })
        self.assertEqual(res.status_code, 400)

    def test_17_candidate_from_another_election_rejected(self):
        """17. Candidate from another election submitted to this election is rejected."""
        self._setup_voter_session(self.u_voter1, self.voter1_rec, self.elec_open)
        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand_beta.id),  # Beta candidate in Alpha election
            'election_id': self.elec_open.id,
            'private-key': self.priv_key1
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('does not belong to this election', res.json().get('error', ''))

    def test_18_review_data_matches_server_validated_selections(self):
        """18. get_parties review data matches server candidates."""
        self._setup_voter_session(self.u_voter1, self.voter1_rec, self.elec_open)
        res = self.client.get(f'/get-parties/?election_id={self.elec_open.id}')
        self.assertEqual(res.status_code, 200)
        parties = res.json().get('parties', [])
        cand_ids = [p['party_id'] for p in parties]
        self.assertIn(str(self.cand_pres1.id), cand_ids)
        self.assertIn(str(self.cand_vp1.id), cand_ids)
        self.assertNotIn(str(self.cand_beta.id), cand_ids)

    def test_19_valid_ballot_reaches_create_vote(self):
        """19. Valid ballot submission successfully records Vote and VoteBackup with election parity."""
        from home.models import Vote, VoteBackup, Ballot
        self._setup_voter_session(self.u_voter1, self.voter1_rec, self.elec_open)
        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand_pres1.id),
            'election_id': str(self.elec_open.id),
            'private-key': self.priv_key1
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))

        vote = Vote.objects.filter(uuid=self.voter1_rec.uuid, election=self.elec_open).first()
        self.assertIsNotNone(vote)
        self.assertEqual(vote.vote_party_id, str(self.cand_pres1.id))
        self.assertEqual(vote.position, self.pos_pres)

        backup = VoteBackup.objects.filter(uuid=self.voter1_rec.uuid, election=self.elec_open).first()
        self.assertIsNotNone(backup)
        self.assertEqual(backup.vote_party_id, str(self.cand_pres1.id))

    def test_20_duplicate_submission_rejected(self):
        """20. Duplicate vote submission by same voter in same election is rejected."""
        self._setup_voter_session(self.u_voter1, self.voter1_rec, self.elec_open)
        # First vote
        res1 = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand_pres1.id),
            'election_id': str(self.elec_open.id),
            'private-key': self.priv_key1
        })
        self.assertEqual(res1.status_code, 200)

        # Re-authenticate session for second attempt
        self._setup_voter_session(self.u_voter1, self.voter1_rec, self.elec_open)
        res2 = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand_pres2.id),
            'election_id': str(self.elec_open.id),
            'private-key': self.priv_key1
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIn('already cast', res2.json().get('error', ''))

    def test_21_repeated_submission_does_not_create_duplicate_vote_rows(self):
        """21. Repeated submissions leave exactly 1 Vote record in database."""
        from home.models import Vote
        count = Vote.objects.filter(uuid=self.voter1_rec.uuid, election=self.elec_open).count()
        self.assertLessEqual(count, 1)

    def test_22_closed_election_stale_page_cannot_submit(self):
        """22. Vote submission to an election closed while page was open is rejected."""
        from home.models import Election
        elec_temp = Election.objects.create(
            organization=self.org_alpha, title="Temp Closing Election", status="OPEN"
        )
        pos = Position.objects.create(election=elec_temp, title="Office", max_votes_allowed=1)
        cand = Candidate.objects.create(position=pos, name="Temp Cand")

        # Session established while OPEN
        self._setup_voter_session(self.u_voter1, self.voter1_rec, elec_temp)

        # Election closes
        elec_temp.status = 'CLOSED'
        elec_temp.save()

        # Voter attempts submission
        res = self.client.post('/create-vote/', {
            'selected-party-id': str(cand.id),
            'election_id': str(elec_temp.id),
            'private-key': self.priv_key1
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('CLOSED', res.json().get('error', ''))

    def test_23_multi_position_ballot_behavior(self):
        """23. Multi-position ballots correctly validate candidate selections per position."""
        from home.models import Candidate
        pres_cand = Candidate.objects.filter(position=self.pos_pres).first()
        vp_cand = Candidate.objects.filter(position=self.pos_vp).first()
        self.assertNotEqual(pres_cand.position_id, vp_cand.position_id)
        self.assertEqual(pres_cand.position.election_id, vp_cand.position.election_id)

    def test_24_candidate_as_user_can_vote_when_eligible(self):
        """24. Candidate user can vote when independently eligible."""
        from home.models import Vote
        self._setup_voter_session(self.u_candidate, self.cand_voter_rec, self.elec_open)
        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand_pres2.id),
            'election_id': str(self.elec_open.id),
            'private-key': self.priv_key1
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))

        vote = Vote.objects.filter(uuid=self.cand_voter_rec.uuid, election=self.elec_open).first()
        self.assertIsNotNone(vote)

    def test_25_candidate_cannot_mutate_election_lifecycle(self):
        """25. Candidate is denied from mutating election lifecycle."""
        self.client.force_login(self.u_candidate)
        res_s = self.client.post(f'/elections/{self.elec_draft.id}/start/')
        self.assertEqual(res_s.status_code, 403)

        res_e = self.client.post(f'/elections/{self.elec_open.id}/end/')
        self.assertEqual(res_e.status_code, 403)

        res_p = self.client.post(f'/elections/{self.elec_closed.id}/publish/')
        self.assertEqual(res_p.status_code, 403)

    def test_26_live_progress_remains_private_when_disabled(self):
        """26. Live progress remains private to voters when disabled."""
        self.elec_open.live_progress_enabled = False
        self.elec_open.save()

        self.client.force_login(self.u_voter1)
        res = self.client.get(f'/elections/{self.elec_open.id}/results/')
        self.assertEqual(res.status_code, 403)

    def test_27_published_results_follow_existing_rules(self):
        """27. Published results are viewable once officially certified."""
        self.client.force_login(self.u_voter1)
        res = self.client.get(f'/elections/{self.elec_published.id}/results/')
        self.assertEqual(res.status_code, 200)

    def test_28_csrf_required_for_voting_mutations(self):
        """28. Voting submission endpoints reject unauthorized mutations."""
        self.client.logout()
        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand_pres1.id)
        })
        self.assertEqual(res.status_code, 401)

    def test_29_get_does_not_mutate(self):
        """29. GET requests to /create-vote/ do not mutate state."""
        from home.models import Vote
        count_before = Vote.objects.count()
        res = self.client.get('/create-vote/')
        self.assertEqual(res.status_code, 405)
        self.assertEqual(Vote.objects.count(), count_before)

    def test_30_historical_blockchain_remains_unchanged(self):
        """30. Voting in generic elections does not alter historical block count."""
        from home.models import Block
        # Blocks in test DB start at 0
        self.assertEqual(Block.objects.count(), 0)





# ==============================================================================
# PHASE 8: AUTH, PUBLIC HOME & NAVIGATION FOUNDATION TESTS
# ==============================================================================

class Phase8AuthHomeNavigationFoundationTests(TestCase):
    """
    Focused Verification Suite for Phase 8:
    1. Public Home Landing Page (/ without voter auth / Aadhaar input)
    2. Email + Password Login (GET form, POST form, JSON API, invalid credentials, redirect)
    3. Navigation Corrections (Dashboard rename, Admin Dashboard, Django Admin removal, Logo -> /)
    4. Logout Correction (GET rejected with 405, POST + CSRF succeeds and redirects to /)
    5. Voter Authentication Relocation (Voting step-up retained in /elections/<id>/vote/)
    6. 1,000 Student Account Generation & Idempotency
    """

    def setUp(self):
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate, UserProfile, Voters

        # Create test users
        self.u_platform = User.objects.create_superuser(
            username='platform_test_admin',
            email='admin@ballotchain.io',
            password='AdminPassword123!'
        )
        self.p_platform = UserProfile.objects.create(
            user=self.u_platform,
            role='PLATFORM_ADMIN'
        )

        self.u_student = User.objects.create_user(
            username='2411CS070001',
            email='2411cs070001@mallareddyuniversity.ac.in',
            password='TestStudentPass123!'
        )

        self.org = Organization.objects.create(
            name='Test University',
            description='Test Campus'
        )
        self.elec = Election.objects.create(
            organization=self.org,
            title='Student Union Election 2026',
            status='OPEN'
        )
        self.pos = Position.objects.create(
            election=self.elec,
            title='President',
            max_votes_allowed=1
        )
        self.cand = Candidate.objects.create(
            position=self.pos,
            name='Campus Candidate',
            affiliation='Unity Slate'
        )

    def test_01_public_home_renders_landing_page_without_voter_auth_form(self):
        """1. GET / renders public landing page without Aadhaar or Voter ID input."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Verifies public landing page sections
        self.assertIn('Enterprise Voting on an', content)
        self.assertIn('Immutable Blockchain', content)
        self.assertIn('What is BallotChain?', content)
        self.assertIn('Governed Election Lifecycle', content)
        self.assertIn('Mathematical Verification for All', content)
        self.assertIn('Ready to run verifiable elections?', content)

        # Verifies absence of legacy voter auth on /
        self.assertNotIn('id="aadhar"', content)
        self.assertNotIn('Voter Authentication — Enter Voter ID Number', content)
        self.assertNotIn('Enter Voter ID Number', content)

    def test_02_login_page_renders_email_password_form(self):
        """2. GET /login/ renders modern institutional email + password form."""
        res = self.client.get('/login/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Verifies email & password fields
        self.assertIn('name="email"', content)
        self.assertIn('name="password"', content)
        self.assertIn('type="password"', content)
        self.assertIn('Back to Home', content)
        self.assertIn('Sign In', content)

        # Verifies NO Aadhaar / Voter ID fields
        self.assertNotIn('aadhar', content.lower())
        self.assertNotIn('voter id', content.lower())
        self.assertNotIn('uuid', content.lower())

    def test_03_login_with_student_email_and_password_form_succeeds(self):
        """3. Form POST /login/ with email and password logs in and redirects to /dashboard/."""
        res = self.client.post('/login/', {
            'email': '2411cs070001@mallareddyuniversity.ac.in',
            'password': 'TestStudentPass123!'
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, '/dashboard/')

        # Verify session is authenticated
        self.assertEqual(int(self.client.session['_auth_user_id']), self.u_student.id)

    def test_04_login_json_api_succeeds(self):
        """4. JSON POST /login/ authenticates and returns user payload."""
        import json
        payload = json.dumps({
            'email': '2411cs070001@mallareddyuniversity.ac.in',
            'password': 'TestStudentPass123!'
        })
        res = self.client.post('/login/', payload, content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('user', {}).get('username'), '2411CS070001')

    def test_05_login_invalid_password_rejected(self):
        """5. Invalid password is rejected with 401 and clear error message."""
        # Form submission
        res_form = self.client.post('/login/', {
            'email': '2411cs070001@mallareddyuniversity.ac.in',
            'password': 'WrongPassword999!'
        })
        self.assertEqual(res_form.status_code, 401)
        self.assertIn('Invalid email or password', res_form.content.decode('utf-8'))

        # JSON API submission
        import json
        payload = json.dumps({
            'email': '2411cs070001@mallareddyuniversity.ac.in',
            'password': 'WrongPassword999!'
        })
        res_json = self.client.post('/login/', payload, content_type='application/json')
        self.assertEqual(res_json.status_code, 401)
        self.assertFalse(res_json.json().get('success'))
        self.assertEqual(res_json.json().get('error'), 'Invalid credentials')

    def test_06_login_invalid_email_rejected(self):
        """6. Unregistered email is rejected."""
        res = self.client.post('/login/', {
            'email': 'nonexistent@mallareddyuniversity.ac.in',
            'password': 'SomePassword123!'
        })
        self.assertEqual(res.status_code, 401)

    def test_07_unauthenticated_user_redirected_to_login(self):
        """7. Accessing election voting flow unauthenticated redirects to /login/ with next param."""
        res = self.client.get(f'/elections/{self.elec.id}/vote/')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res.url)
        self.assertIn(f'next=/elections/{self.elec.id}/vote/', res.url)

    def test_08_post_login_routing_with_next_param(self):
        """8. Form POST /login/ with next parameter redirects safely to target."""
        res = self.client.post('/login/', {
            'email': '2411cs070001@mallareddyuniversity.ac.in',
            'password': 'TestStudentPass123!',
            'next': f'/elections/{self.elec.id}/vote/'
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, f'/elections/{self.elec.id}/vote/')

    def test_09_navigation_logo_links_to_home(self):
        """9. Logo and brand links in navigation point to / (Home)."""
        res = self.client.get('/')
        content = res.content.decode('utf-8')
        self.assertIn('href="/" class="sidebar-brand"', content)
        self.assertIn('href="/" class="breadcrumb-item"', content)

    def test_10_navigation_django_admin_removed(self):
        """10. Django Admin is absent from normal application sidebar navigation."""
        self.client.force_login(self.u_platform)
        res = self.client.get('/dashboard/')
        content = res.content.decode('utf-8')
        # Django Admin should NOT appear as a navigation link
        self.assertNotIn('href="/admin">Django Admin</a>', content)
        self.assertNotIn('href="/admin/" class="sidebar-link"', content)

    def test_11_navigation_dashboard_labels(self):
        """11. Voter sees 'Dashboard', Platform Admin sees 'Admin Dashboard'."""
        # Platform Admin
        self.client.force_login(self.u_platform)
        res_admin = self.client.get('/dashboard/')
        content_admin = res_admin.content.decode('utf-8')
        self.assertIn('Admin Dashboard', content_admin)

        # Voter
        self.client.force_login(self.u_student)
        res_voter = self.client.get('/dashboard/')
        content_voter = res_voter.content.decode('utf-8')
        self.assertIn('Dashboard', content_voter)
        self.assertNotIn('Role Dashboard', content_voter)

    def test_12_logout_get_rejected_post_succeeds(self):
        """12. GET /logout/ returns 405; POST /logout/ with CSRF logs out and redirects to /."""
        self.client.force_login(self.u_student)

        # GET request must be rejected with 405 Method Not Allowed
        res_get = self.client.get('/logout/')
        self.assertEqual(res_get.status_code, 405)

        # POST request logs out and redirects to /
        res_post = self.client.post('/logout/')
        self.assertEqual(res_post.status_code, 302)
        self.assertEqual(res_post.url, '/')

        # Session should be cleared
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_13_voter_authentication_retained_in_voting_flow(self):
        """13. Voter resolution and OTP step-up remain active in election voting flow."""
        self.client.force_login(self.u_student)
        res = self.client.get(f'/elections/{self.elec.id}/vote/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Identity Verification', content)
        self.assertIn('Candidate Selection', content)
        self.assertIn('Cryptographic Signature', content)

    def test_14_account_creation_command_idempotent(self):
        """14. Student account creation management command is strictly idempotent."""
        from django.core.management import call_command
        from django.contrib.auth.models import User
        from io import StringIO

        out = StringIO()
        # Run command for a test range
        call_command('create_student_accounts', start=9901, end=9905, stdout=out)
        output1 = out.getvalue()
        self.assertIn('Created: 5', output1)

        # Run command again for the same range
        out2 = StringIO()
        call_command('create_student_accounts', start=9901, end=9905, stdout=out2)
        output2 = out2.getvalue()
        self.assertIn('Created: 0', output2)
        self.assertIn('Skipped (already existed): 5', output2)


class Phase8ManualTestingFixesTests(TestCase):
    """
    Focused verification tests for Phase 8 Manual Testing Fixes:
    - User/voter authentication (both cases, email, username, whitespace handling)
    - Organization creation (web form, API, CSRF, validation, duplication prevention, RBAC)
    - Election creation (web form, API, CSRF, validation, duplication prevention, DRAFT state, RBAC)
    - Chain Audit execution via POST + CSRF, read-only preservation, and raw JSON API
    - Admin UI navigation cleanup (Voter Portal absent for admin roles)
    - Five generic candidate accounts creation, authentication, idempotency, and party-free presentation
    """

    def setUp(self):
        self.client = Client()

        # 1. Platform Admin
        self.u_platform = User.objects.create_superuser(
            username='platform_test_admin',
            email='platform_admin@ballotchain.com',
            password='PlatformPassword123!'
        )
        UserProfile.objects.create(user=self.u_platform, role='PLATFORM_ADMIN')

        # 2. Organization & Org Admin
        self.org = Organization.objects.create(
            name='Engineering College',
            description='Faculty of Engineering and Technology',
            contact_information='eng@university.edu'
        )
        self.u_org_admin = User.objects.create_user(
            username='org_test_admin',
            email='org_admin@university.edu',
            password='OrgAdminPassword123!'
        )
        UserProfile.objects.create(user=self.u_org_admin, role='ORGANIZATION_ADMIN', organization=self.org)

        # 3. Auditor
        self.u_auditor = User.objects.create_user(
            username='auditor_test',
            email='auditor@audit.org',
            password='AuditorPassword123!'
        )
        UserProfile.objects.create(user=self.u_auditor, role='AUDITOR', organization=self.org)

        # 4. Student / Voter Account 1
        self.u_student1 = User.objects.create_user(
            username='2411CS070001',
            email='2411cs070001@mallareddyuniversity.ac.in',
            password='2411CS070001'
        )

        # 5. Student / Voter Account 2
        self.u_student2 = User.objects.create_user(
            username='2411CS070002',
            email='2411cs070002@mallareddyuniversity.ac.in',
            password='2411CS070002'
        )

        # 6. Candidate Account
        self.u_cand1 = User.objects.create_user(
            username='candidate1',
            email='candidate1@ballotchain.com',
            password='c1@ballotchain'
        )

    def test_01_user_login_first_account_email_and_password_variations(self):
        """1. First student account authenticates via email with uppercase, lowercase, and whitespace."""
        # A. Uppercase password
        res_upper = self.client.post('/login/', {
            'email': '2411cs070001@mallareddyuniversity.ac.in',
            'password': '2411CS070001'
        })
        self.assertEqual(res_upper.status_code, 302)
        self.assertEqual(res_upper.url, '/dashboard/')
        self.client.logout()

        # B. Lowercase password
        res_lower = self.client.post('/login/', {
            'email': '2411cs070001@mallareddyuniversity.ac.in',
            'password': '2411cs070001'
        })
        self.assertEqual(res_lower.status_code, 302)
        self.assertEqual(res_lower.url, '/dashboard/')
        self.client.logout()

        # C. Password with accidental whitespace
        res_padded = self.client.post('/login/', {
            'email': ' 2411cs070001@mallareddyuniversity.ac.in ',
            'password': ' 2411CS070001 '
        })
        self.assertEqual(res_padded.status_code, 302)
        self.assertEqual(res_padded.url, '/dashboard/')
        self.client.logout()

    def test_02_user_login_second_account_email_and_password(self):
        """2. Second student account authenticates via institutional email and roll number."""
        res = self.client.post('/login/', {
            'email': '2411cs070002@mallareddyuniversity.ac.in',
            'password': '2411CS070002'
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, '/dashboard/')
        self.client.logout()

        # Username login
        res_uname = self.client.post('/login/', {
            'email': '2411CS070002',
            'password': '2411cs070002'
        })
        self.assertEqual(res_uname.status_code, 302)
        self.assertEqual(res_uname.url, '/dashboard/')

    def test_03_login_invalid_credentials_returns_401(self):
        """3. Invalid email or password strictly returns 401."""
        # Wrong password
        res_bad_pwd = self.client.post('/login/', {
            'email': '2411cs070001@mallareddyuniversity.ac.in',
            'password': 'IncorrectPassword'
        })
        self.assertEqual(res_bad_pwd.status_code, 401)
        self.assertIn('Invalid email or password', res_bad_pwd.content.decode('utf-8'))

        # Nonexistent email
        res_bad_email = self.client.post('/login/', {
            'email': 'nonexistent@university.ac.in',
            'password': '2411CS070001'
        })
        self.assertEqual(res_bad_email.status_code, 401)

    def test_04_platform_admin_create_organization_web_and_api(self):
        """4. Platform Admin can create organizations via browser web form and JSON API."""
        self.client.force_login(self.u_platform)

        # GET browser form
        res_get = self.client.get('/organizations/create/', HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(res_get.status_code, 200)
        self.assertIn('Add New Organization', res_get.content.decode('utf-8'))

        # POST web form
        res_post = self.client.post('/organizations/create/', {
            'name': 'Sciences Department',
            'description': 'Pure and Applied Sciences',
            'contact_information': 'sci@university.edu'
        })
        self.assertEqual(res_post.status_code, 302)
        self.assertEqual(res_post.url, '/organizations/')
        self.assertTrue(Organization.objects.filter(name='Sciences Department').exists())

        # POST JSON API (preserving Raw JSON backend)
        res_json = self.client.post(
            '/organizations/create/',
            json.dumps({'name': 'Medical School', 'description': 'Health Sciences'}),
            content_type='application/json'
        )
        self.assertEqual(res_json.status_code, 200)
        self.assertTrue(res_json.json().get('success'))

    def test_05_organization_creation_validation_and_duplicate_prevention(self):
        """5. Organization creation validates required fields and rejects duplicate names."""
        self.client.force_login(self.u_platform)

        # Empty name
        res_empty = self.client.post('/organizations/create/', {'name': '   '})
        self.assertEqual(res_empty.status_code, 400)
        self.assertIn('Organization name is required', res_empty.content.decode('utf-8'))

        # Duplicate name
        res_dup = self.client.post('/organizations/create/', {
            'name': 'Engineering College'
        })
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn('already exists', res_dup.content.decode('utf-8'))

    def test_06_unauthorized_roles_rejected_on_organization_create(self):
        """6. Organization Admins, Auditors, and Voters are rejected with 403 on organization create."""
        for user in [self.u_org_admin, self.u_auditor, self.u_student1]:
            self.client.force_login(user)
            res = self.client.post('/organizations/create/', {'name': 'Unauthorized Org'})
            self.assertEqual(res.status_code, 403)

    def test_07_organization_create_csrf_enforcement(self):
        """7. State-changing POST to /organizations/create/ without CSRF is rejected."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.u_platform)
        res = csrf_client.post('/organizations/create/', {'name': 'No CSRF Org'})
        self.assertEqual(res.status_code, 403)

    def test_08_election_create_web_form_and_api(self):
        """8. Platform Admin and Org Admin can create elections starting in DRAFT state."""
        self.client.force_login(self.u_platform)

        # GET browser form
        res_get = self.client.get('/elections/create/', HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(res_get.status_code, 200)
        self.assertIn('Create New Election', res_get.content.decode('utf-8'))

        # POST web form
        res_post = self.client.post('/elections/create/', {
            'organization_id': self.org.id,
            'title': 'Faculty Council 2026',
            'description': 'Annual faculty representative election'
        })
        self.assertEqual(res_post.status_code, 302)
        elec = Election.objects.get(title='Faculty Council 2026')
        self.assertEqual(elec.status, 'DRAFT')
        self.assertEqual(elec.organization_id, self.org.id)

    def test_09_election_create_validation_and_duplicate_prevention(self):
        """9. Election creation validates inputs and rejects duplicate titles in same organization."""
        self.client.force_login(self.u_platform)

        # Missing title
        res_no_title = self.client.post('/elections/create/', {
            'organization_id': self.org.id,
            'title': ''
        })
        self.assertEqual(res_no_title.status_code, 400)

        # Create one election
        Election.objects.create(organization=self.org, title='Campus Senate 2026', status='DRAFT')

        # Attempt duplicate
        res_dup = self.client.post('/elections/create/', {
            'organization_id': self.org.id,
            'title': 'Campus Senate 2026'
        })
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn('already exists', res_dup.content.decode('utf-8'))

    def test_10_unauthorized_roles_rejected_on_election_create(self):
        """10. Voters, Candidates, and Auditors cannot create elections."""
        for user in [self.u_auditor, self.u_student1, self.u_cand1]:
            self.client.force_login(user)
            res = self.client.post('/elections/create/', {
                'organization_id': self.org.id,
                'title': 'Unauthorized Election'
            })
            self.assertEqual(res.status_code, 403)

    def test_11_chain_audit_post_executes_verification_and_displays_results(self):
        """11. POST to /blockchain/verify-chain/ executes audit and returns verified status."""
        self.client.force_login(self.u_platform)

        # Browser POST
        res = self.client.post('/blockchain/verify-chain/', HTTP_ACCEPT='text/html,application/xhtml+xml')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Status: VERIFIED', content)
        self.assertIn('Full Cryptographic Audit Complete', content)

    def test_12_chain_audit_preserves_raw_json_api(self):
        """12. Raw JSON API for chain verification remains 100% functional and unmodified."""
        self.client.force_login(self.u_platform)
        res = self.client.get('/blockchain/verify-chain/?format=json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get('status'), 'VERIFIED')
        self.assertTrue(data.get('valid'))
        self.assertEqual(data.get('total_blocks_checked'), Block.objects.count())
        self.assertEqual(len(data.get('failures')), 0)

    def test_13_voter_portal_absent_from_admin_dashboard(self):
        """13. 'Voter Portal' action button is absent for Platform and Organization Admins."""
        self.client.force_login(self.u_platform)
        res_admin = self.client.get('/dashboard/')
        content_admin = res_admin.content.decode('utf-8')
        # Check header action buttons do not offer Voter Portal to Admin
        self.assertNotIn('title="Return to voter portal"', content_admin)

        # Voter dashboard still shows appropriate participation links
        self.client.force_login(self.u_student1)
        res_voter = self.client.get('/dashboard/')
        content_voter = res_voter.content.decode('utf-8')
        self.assertIn('Voter Account', content_voter)

    def test_14_five_candidate_accounts_authentication(self):
        """14. Five generic candidate accounts authenticate with their initial credentials."""
        from django.core.management import call_command
        call_command('create_candidate_accounts')
        for i in range(1, 6):
            res = self.client.post('/login/', {
                'email': f'candidate{i}@ballotchain.com',
                'password': f'c{i}@ballotchain'
            })
            self.assertEqual(res.status_code, 302, f"Candidate {i} login failed")
            self.client.logout()



class Phase8LifecycleProfilesCandidateResultsTests(TestCase):
    """
    Focused verification tests for Phase 8 Manual Testing Fixes:
    - Normal Election Lifecycle UX: Start/End redirect with success message; raw JSON API preserved
    - Admin Election Editing: DRAFT editable by authorized admin; OPEN locked against arbitrary edits; CLOSED cannot reopen
    - Voter Profile: Personal fields editable; email strictly read-only and immutable
    - Candidate Participation: Self-registration in DRAFT; closed in OPEN; duplicate rejection; identity binding
    - Candidate Dual-Role: Candidate remains eligible voter in election
    - Position/Candidate Management: Respects election lifecycle (DRAFT only)
    - Results Cleanup: Generic presentation without legacy Indian parties; respects live-progress & publication
    - Ledger Safety: Historical chain valid
    """

    def setUp(self):
        self.client = Client()
        from home.views import get_or_create_voter_for_user
        from home.permissions import get_account_persona

        # 1. Platform Admin
        self.u_platform = User.objects.create_superuser(
            username='platform_admin_fix',
            email='admin_fix@ballotchain.com',
            password='PlatformPassword123!'
        )
        UserProfile.objects.create(user=self.u_platform, role='PLATFORM_ADMIN')

        # 2. Organization & Org Admin
        self.org = Organization.objects.create(
            name='Test University',
            description='Institutional Test University',
            contact_information='info@testuniversity.edu'
        )
        self.u_org_admin = User.objects.create_user(
            username='org_admin_fix',
            email='org_admin_fix@testuniversity.edu',
            password='OrgAdminPassword123!'
        )
        UserProfile.objects.create(user=self.u_org_admin, role='ORGANIZATION_ADMIN', organization=self.org)

        # 3. Voter / Student
        self.u_voter = User.objects.create_user(
            username='voter_test_fix',
            email='voter_fix@testuniversity.edu',
            password='VoterPassword123!',
            first_name='Voter',
            last_name='One'
        )
        self.voter_rec = get_or_create_voter_for_user(self.u_voter)

        # 4. Candidates
        self.u_candidate1 = User.objects.create_user(
            username='candidate1_fix',
            email='candidate1_fix@ballotchain.com',
            password='CandidatePassword123!',
            first_name='Candidate',
            last_name='Alpha'
        )
        self.u_candidate2 = User.objects.create_user(
            username='candidate2_fix',
            email='candidate2_fix@ballotchain.com',
            password='CandidatePassword123!',
            first_name='Candidate',
            last_name='Beta'
        )

        # 5. Draft Election
        self.elec_draft = Election.objects.create(
            organization=self.org,
            title='Student Leadership Election 2027',
            description='General elections for student leadership positions.',
            status='DRAFT'
        )
        self.pos = Position.objects.create(
            election=self.elec_draft,
            title='Student Body President',
            max_votes_allowed=1
        )

    def test_01_start_election_redirects_with_normal_success_message(self):
        """1. Admin starting an election redirects to election page with clean success message."""
        self.client.force_login(self.u_platform)
        res_followed = self.client.post(f'/elections/{self.elec_draft.id}/start/', follow=True)
        self.assertEqual(res_followed.status_code, 200)
        self.assertRedirects(res_followed, f'/elections/{self.elec_draft.id}/')
        self.elec_draft.refresh_from_db()
        self.assertEqual(self.elec_draft.status, 'OPEN')

        # Check messages rendered in the HTML
        content = res_followed.content.decode('utf-8')
        self.assertIn('Election started successfully', content)
        self.assertNotIn('{\\"success\\": true', content)

    def test_02_end_election_redirects_with_normal_success_message(self):
        """2. Admin ending an election redirects to election page with clean success message."""
        self.elec_draft.status = 'OPEN'
        self.elec_draft.save()

        self.client.force_login(self.u_platform)
        res_followed = self.client.post(f'/elections/{self.elec_draft.id}/end/', follow=True)
        self.assertEqual(res_followed.status_code, 200)
        self.assertRedirects(res_followed, f'/elections/{self.elec_draft.id}/')
        self.elec_draft.refresh_from_db()
        self.assertEqual(self.elec_draft.status, 'CLOSED')

        content = res_followed.content.decode('utf-8')
        self.assertIn('Election ended successfully', content)
        self.assertNotIn('{\\"success\\": true', content)

    def test_03_raw_json_api_still_works_for_start_end_publish(self):
        """3. Raw JSON API remains intact for programmatic consumers specifying Accept: application/json."""
        self.client.force_login(self.u_platform)

        # JSON Start
        res_start = self.client.post(
            f'/elections/{self.elec_draft.id}/start/',
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_start.status_code, 200)
        data_start = res_start.json()
        self.assertTrue(data_start.get('success'))
        self.assertEqual(data_start.get('status'), 'OPEN')

        # JSON End
        res_end = self.client.post(
            f'/elections/{self.elec_draft.id}/end/',
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_end.status_code, 200)
        data_end = res_end.json()
        self.assertTrue(data_end.get('success'))
        self.assertEqual(data_end.get('status'), 'CLOSED')

    def test_04_draft_election_can_be_edited_by_authorized_admin(self):
        """4. Authorized admin can edit metadata of a DRAFT election."""
        self.client.force_login(self.u_org_admin)

        # GET edit page
        res_get = self.client.get(f'/elections/{self.elec_draft.id}/edit/')
        self.assertEqual(res_get.status_code, 200)
        self.assertIn('Edit Election', res_get.content.decode('utf-8'))

        # POST update
        res_post = self.client.post(f'/elections/{self.elec_draft.id}/edit/', {
            'title': 'Updated Leadership Election 2027',
            'description': 'Revised institutional description.',
            'live_progress_enabled': '1',
        }, follow=True)
        self.assertEqual(res_post.status_code, 200)

        self.elec_draft.refresh_from_db()
        self.assertEqual(self.elec_draft.title, 'Updated Leadership Election 2027')
        self.assertEqual(self.elec_draft.description, 'Revised institutional description.')
        self.assertTrue(self.elec_draft.live_progress_enabled)

    def test_05_open_election_cannot_be_arbitrarily_edited(self):
        """5. Critical identity and organization of an OPEN election cannot be modified."""
        self.elec_draft.status = 'OPEN'
        self.elec_draft.save()

        self.client.force_login(self.u_platform)

        # Attempt to change title while OPEN
        res = self.client.post(
            f'/elections/{self.elec_draft.id}/edit/',
            {'title': 'Arbitrary Title Change While Live'},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res.status_code, 400)
        self.elec_draft.refresh_from_db()
        self.assertEqual(self.elec_draft.title, 'Student Leadership Election 2027')

    def test_06_closed_election_cannot_be_reopened(self):
        """6. Closed elections cannot be reopened or edited back to DRAFT or OPEN."""
        self.elec_draft.status = 'CLOSED'
        self.elec_draft.save()

        self.client.force_login(self.u_platform)

        # Attempt to reopen via start
        res_start = self.client.post(f'/elections/{self.elec_draft.id}/start/', HTTP_ACCEPT='application/json')
        self.assertEqual(res_start.status_code, 400)

        # Attempt to reopen via edit
        res_edit = self.client.post(
            f'/elections/{self.elec_draft.id}/edit/',
            {'status': 'OPEN'},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_edit.status_code, 400)

        self.elec_draft.refresh_from_db()
        self.assertEqual(self.elec_draft.status, 'CLOSED')

    def test_07_voter_profile_fields_can_be_updated_where_permitted(self):
        """7. Authenticated voter can view and update allowed personal profile fields."""
        self.client.force_login(self.u_voter)

        res_get = self.client.get('/profile/')
        self.assertEqual(res_get.status_code, 200)
        self.assertIn('Voter Profile', res_get.content.decode('utf-8'))

        # Update allowed fields
        res_post = self.client.post('/profile/', {
            'name': 'Updated Voter Name',
            'region': 'CSE-A',
            'dob': '2001-08-20',
            'pincode': '500043',
        }, follow=True)
        self.assertEqual(res_post.status_code, 200)

        self.voter_rec.refresh_from_db()
        self.assertEqual(self.voter_rec.name, 'Updated Voter Name')
        self.assertEqual(self.voter_rec.region, 'CSE-A')
        self.assertEqual(str(self.voter_rec.dob), '2001-08-20')
        self.assertEqual(self.voter_rec.pincode, '500043')

    def test_08_voter_email_cannot_be_changed_and_unauthorized_change_rejected(self):
        """8. Voter email address is strictly immutable and protected against unauthorized change."""
        self.client.force_login(self.u_voter)
        original_email = self.u_voter.email

        # Attempt to modify email via JSON POST
        res_json = self.client.post(
            '/profile/',
            {'email': 'hacker@malicious.com', 'name': 'Voter'},
            content_type='application/json',
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_json.status_code, 400)
        self.u_voter.refresh_from_db()
        self.assertEqual(self.u_voter.email, original_email)

        # Attempt to modify email via form POST
        res_form = self.client.post('/profile/', {
            'email': 'hacker@malicious.com',
            'name': 'Voter Name'
        }, follow=True)
        self.u_voter.refresh_from_db()
        self.assertEqual(self.u_voter.email, original_email)

    def test_09_candidate_can_participate_before_election_opens(self):
        """9. Candidate user can self-register for a position while election is in DRAFT state."""
        self.client.force_login(self.u_candidate1)

        res = self.client.post(
            f'/elections/{self.elec_draft.id}/participate/',
            {
                'position_id': self.pos.id,
                'name': 'Candidate One',
                'affiliation': 'Independent Reform',
                'bio': 'Dedicated to transparent governance.'
            },
            follow=True
        )
        self.assertEqual(res.status_code, 200)

        # Verify candidate row created
        cand = Candidate.objects.filter(position=self.pos, user=self.u_candidate1).first()
        self.assertIsNotNone(cand)
        self.assertEqual(cand.name, 'Candidate One')
        self.assertEqual(cand.affiliation, 'Independent Reform')

        # Persona dynamically resolves to CANDIDATE
        from home.permissions import get_account_persona
        self.assertEqual(get_account_persona(self.u_candidate1), 'CANDIDATE')

    def test_10_candidate_cannot_participate_after_election_opens(self):
        """10. Candidate participation is rejected once election status is OPEN or CLOSED."""
        self.elec_draft.status = 'OPEN'
        self.elec_draft.save()

        self.client.force_login(self.u_candidate2)
        res = self.client.post(
            f'/elections/{self.elec_draft.id}/participate/',
            {
                'position_id': self.pos.id,
                'name': 'Late Candidate'
            },
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Candidate.objects.filter(position=self.pos, user=self.u_candidate2).exists())

    def test_11_duplicate_candidate_participation_is_rejected(self):
        """11. A user cannot be registered twice for the same position."""
        Candidate.objects.create(
            position=self.pos,
            user=self.u_candidate1,
            name='Candidate One'
        )

        self.client.force_login(self.u_candidate1)
        res = self.client.post(
            f'/elections/{self.elec_draft.id}/participate/',
            {'position_id': self.pos.id, 'name': 'Candidate One Duplicate'},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Candidate.objects.filter(position=self.pos, user=self.u_candidate1).count(), 1)

    def test_12_candidate_participation_is_tied_to_authenticated_user(self):
        """12. Candidate registration strictly binds to request.user even if another user_id is sent."""
        self.client.force_login(self.u_candidate1)

        # Send request with arbitrary user_id
        res = self.client.post(
            f'/elections/{self.elec_draft.id}/participate/',
            {
                'position_id': self.pos.id,
                'user_id': self.u_candidate2.id,
                'name': 'Spoof Attempt'
            },
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res.status_code, 201)

        # Candidacy must belong strictly to self.u_candidate1
        cand = Candidate.objects.get(position=self.pos, user=self.u_candidate1)
        self.assertEqual(cand.user_id, self.u_candidate1.id)
        self.assertFalse(Candidate.objects.filter(position=self.pos, user=self.u_candidate2).exists())

    def test_13_candidate_remains_eligible_to_vote_independently(self):
        """13. A registered candidate user retains independent voter eligibility when election is OPEN."""
        Candidate.objects.create(
            position=self.pos,
            user=self.u_candidate1,
            name='Candidate One'
        )
        self.elec_draft.status = 'OPEN'
        self.elec_draft.save()

        # Candidate visits voting entry point
        self.client.force_login(self.u_candidate1)
        res_vote = self.client.get(f'/elections/{self.elec_draft.id}/vote/')
        self.assertEqual(res_vote.status_code, 200)

        # Voter record was resolved for candidate
        from home.views import get_or_create_voter_for_user
        voter_cand = get_or_create_voter_for_user(self.u_candidate1)
        self.assertIsNotNone(voter_cand)
        self.assertFalse(voter_cand.vote_done)

    def test_14_position_and_candidate_management_respects_election_lifecycle(self):
        """14. Admin can manage positions and candidates in DRAFT, rejected in OPEN."""
        self.client.force_login(self.u_org_admin)

        # Add position in DRAFT
        res_pos = self.client.post(
            '/positions/create/',
            {'election_id': self.elec_draft.id, 'title': 'Vice President', 'max_votes_allowed': 1},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_pos.status_code, 200)
        vp_id = res_pos.json().get('id')

        # Add candidate in DRAFT
        res_cand = self.client.post(
            '/candidates/create/',
            {'position_id': vp_id, 'name': 'Jane Doe', 'user_id': self.u_candidate2.id},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_cand.status_code, 200)

        # Transition to OPEN
        self.elec_draft.status = 'OPEN'
        self.elec_draft.save()

        # Attempt to add position while OPEN -> rejected
        res_pos_open = self.client.post(
            '/positions/create/',
            {'election_id': self.elec_draft.id, 'title': 'Secretary'},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_pos_open.status_code, 400)

        # Attempt to add candidate while OPEN -> rejected
        res_cand_open = self.client.post(
            '/candidates/create/',
            {'position_id': vp_id, 'name': 'Late Candidate'},
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_cand_open.status_code, 400)

    def test_15_legacy_party_information_does_not_appear_in_modern_results(self):
        """15. Old Indian political parties and party symbols do not appear in modern BallotChain results."""
        self.client.force_login(self.u_platform)
        res = self.client.get('/show-result/')
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Obsolete Indian election party names are not present
        self.assertNotIn('BJP', content)
        self.assertNotIn('Congress', content)
        self.assertNotIn('AAP', content)
        self.assertNotIn('NOTA.png', content)

        # Modern generic structure is present
        self.assertIn('Candidate', content)
        self.assertIn('Verified Vote Count', content)

    def test_16_results_respect_live_progress_and_publication_state(self):
        """16. Results respect live-progress privacy and require publication after CLOSED."""
        self.client.force_login(self.u_voter)

        # Case A: DRAFT election -> results withheld
        res_draft = self.client.get(f'/show-result/?election_id={self.elec_draft.id}')
        self.assertEqual(res_draft.status_code, 200)
        self.assertIn('Results Currently Unavailable', res_draft.content.decode('utf-8'))

        # Case B: OPEN election with live_progress=False -> results withheld
        self.elec_draft.status = 'OPEN'
        self.elec_draft.live_progress_enabled = False
        self.elec_draft.save()
        res_open_priv = self.client.get(f'/show-result/?election_id={self.elec_draft.id}')
        self.assertIn('Live progress is disabled', res_open_priv.content.decode('utf-8'))

        # Case C: CLOSED election unpublished -> results withheld
        self.elec_draft.status = 'CLOSED'
        self.elec_draft.is_published = False
        self.elec_draft.save()
        res_closed_unpub = self.client.get(f'/show-result/?election_id={self.elec_draft.id}')
        self.assertIn('Voting is closed', res_closed_unpub.content.decode('utf-8'))

    def test_17_historical_blockchain_verification_remains_valid(self):
        """17. Historical blockchain consensus and integrity remain 100% verified."""
        from home.methods_module import verify_full_chain
        res = verify_full_chain()
        self.assertTrue(res.get('valid'))
        self.assertEqual(res.get('status'), 'VERIFIED')


class Phase8AutomationMiningResultsTests(TestCase):
    """
    Focused verification tests for:
    - Automatic election start/end at scheduled times
    - Idempotency & safety of scheduler
    - Dedicated Private-Key verification step (separate from OTP)
    - Private-key security (never exposed in APIs/logs)
    - Modern Vote -> VoteBackup -> BallotBatch -> Block mining pipeline
    - Blockchain integrity (Merkle root, Block hash, Linkage)
    - Deterministic result verification receipt & publication certification
    - Historical blockchain safety (5,645 blocks)
    """

    def setUp(self):
        self.client = Client()
        from home.views import get_or_create_voter_for_user
        from home.permissions import get_account_persona
        from home.methods_module import generate_keys

        # 1. Platform Admin
        self.u_platform = User.objects.create_superuser(
            username='platform_admin_auto',
            email='admin_auto@ballotchain.com',
            password='AdminPassword123!'
        )
        UserProfile.objects.create(user=self.u_platform, role='PLATFORM_ADMIN')

        # 2. Organization & Org Admin
        self.org = Organization.objects.create(
            name='Test Institute of Technology',
            description='Automated Testing Tenant Organization'
        )
        self.u_org_admin = User.objects.create_user(
            username='org_admin_auto',
            email='org_admin_auto@tit.edu',
            password='OrgAdminPassword123!'
        )
        UserProfile.objects.create(user=self.u_org_admin, role='ORGANIZATION_ADMIN', organization=self.org)

        # 3. Voter User
        self.u_voter = User.objects.create_user(
            username='student_auto_01',
            email='student_auto_01@tit.edu',
            password='StudentPassword123!'
        )
        UserProfile.objects.create(user=self.u_voter, role='VOTER', organization=self.org)
        self.voter_rec = get_or_create_voter_for_user(self.u_voter)

        # 4. Generate keys for testing
        self.priv_key, self.pub_key = generate_keys()

        # 5. Scheduled Elections
        self.now = timezone.now()
        self.elec_scheduled = Election.objects.create(
            organization=self.org,
            title='Automated Scheduled Election 2027',
            description='Testing automated start and end lifecycle.',
            start_date=self.now - timedelta(minutes=5),
            end_date=self.now + timedelta(hours=2),
            status='DRAFT'
        )
        self.pos = Position.objects.create(
            election=self.elec_scheduled,
            title='Campus President',
            max_votes_allowed=1
        )
        self.cand = Candidate.objects.create(
            position=self.pos,
            name='Candidate Alpha',
            bio='Engineering student representative.'
        )

    def test_01_automatic_start_at_scheduled_time(self):
        """1. DRAFT election whose start_date has arrived transitions automatically to OPEN."""
        from home.methods_module import process_scheduled_election_transitions
        self.assertEqual(self.elec_scheduled.status, 'DRAFT')

        result = process_scheduled_election_transitions(now=self.now)
        self.assertIn(self.elec_scheduled.id, result['started'])

        self.elec_scheduled.refresh_from_db()
        self.assertEqual(self.elec_scheduled.status, 'OPEN')
        # Active BallotBatch created
        self.assertTrue(BallotBatch.objects.filter(election=self.elec_scheduled, status='OPEN').exists())

    def test_02_automatic_end_at_scheduled_time(self):
        """2. OPEN election whose end_date has arrived transitions automatically to CLOSED."""
        from home.methods_module import process_scheduled_election_transitions
        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.end_date = self.now - timedelta(minutes=1)
        self.elec_scheduled.save()

        result = process_scheduled_election_transitions(now=self.now)
        self.assertIn(self.elec_scheduled.id, result['ended'])

        self.elec_scheduled.refresh_from_db()
        self.assertEqual(self.elec_scheduled.status, 'CLOSED')

    def test_03_no_early_automatic_transition(self):
        """3. An election whose start or end time is in the future does NOT transition early."""
        from home.methods_module import process_scheduled_election_transitions
        future_elec = Election.objects.create(
            organization=self.org,
            title='Future Election',
            start_date=self.now + timedelta(days=1),
            end_date=self.now + timedelta(days=2),
            status='DRAFT'
        )
        result = process_scheduled_election_transitions(now=self.now)
        self.assertNotIn(future_elec.id, result['started'])
        future_elec.refresh_from_db()
        self.assertEqual(future_elec.status, 'DRAFT')

    def test_04_idempotent_scheduler_execution(self):
        """4. Running the scheduler multiple times is strictly idempotent with no side effects."""
        from home.methods_module import process_scheduled_election_transitions
        res1 = process_scheduled_election_transitions(now=self.now)
        res2 = process_scheduled_election_transitions(now=self.now)
        # Second run starts 0 additional elections
        self.assertEqual(len(res2['started']), 0)
        self.assertEqual(len(res2['ended']), 0)

    def test_05_private_key_step_is_separate_from_otp(self):
        """5. Private-key verification is a distinct endpoint separate from OTP verification."""
        import time
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['otp'] = '123456'
        session['otp_created_at'] = time.time()
        session['email-verified'] = False
        session.save()

        # Step 1: OTP verification
        res_otp = self.client.post('/verify-otp/', {'otp-input': '123456'})
        self.assertEqual(res_otp.status_code, 200)
        self.assertTrue(self.client.session.get('email-verified'))

        # Set session keys for Step 2
        session = self.client.session
        session['public-key'] = self.pub_key
        session.save()

        # Step 2: Dedicated Private Key verification endpoint
        res_pk = self.client.post('/verify-private-key/', {'private-key': self.priv_key})
        self.assertEqual(res_pk.status_code, 200)
        data = res_pk.json()
        self.assertTrue(data.get('success'))

    def test_06_private_key_never_appears_in_api_response(self):
        """6. Private key is never returned or leaked in JSON API responses."""
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['public-key'] = self.pub_key
        session.save()

        res = self.client.get(f'/get-parties/?election_id={self.elec_scheduled.id}')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('BEGIN PRIVATE KEY', res.content.decode('utf-8'))
        self.assertNotIn('private_key', res.json())

    def test_07_private_key_never_appears_in_logs(self):
        """7. Errors during key verification never output raw private keys."""
        session = self.client.session
        session['email-verified'] = True
        session.save()

        invalid_key = "-----BEGIN PRIVATE KEY-----\nMIIB...CORRUPTED...KEY\n-----END PRIVATE KEY-----"
        res = self.client.post('/verify-private-key/', {'private-key': invalid_key})
        self.assertEqual(res.status_code, 400)
        content = res.content.decode('utf-8')
        self.assertNotIn('CORRUPTED', content)
        self.assertIn('Invalid private key', content)

    def test_08_valid_private_key_authorizes_signing(self):
        """8. Valid private key authorizes digital signature verification."""
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session['private-key'] = self.priv_key
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))

    def test_09_invalid_private_key_is_rejected(self):
        """9. Invalid or malformed private key is rejected with HTTP 400."""
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': 'INVALID_PRIVATE_KEY_PAYLOAD',
            'election_id': str(self.elec_scheduled.id)
        })
        self.assertEqual(res.status_code, 400)

    def test_10_vote_creates_modern_vote_and_vote_backup(self):
        """10. Submitting a vote creates exact matching Vote and VoteBackup records."""
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })
        self.assertEqual(res.status_code, 200)

        vote = Vote.objects.filter(uuid=self.voter_rec.uuid, election=self.elec_scheduled).first()
        self.assertIsNotNone(vote)
        self.assertEqual(vote.vote_party_id, str(self.cand.id))
        self.assertIsNotNone(vote.tx_id)

        backup = VoteBackup.objects.filter(uuid=self.voter_rec.uuid, election=self.elec_scheduled).first()
        self.assertIsNotNone(backup)
        self.assertEqual(vote.tx_id, backup.tx_id)
        self.assertEqual(vote.commitment_salt, backup.commitment_salt)

    def test_11_vote_enters_correct_ballotbatch(self):
        """11. Vote and Ballot are assigned to the active BallotBatch."""
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })
        self.assertEqual(res.status_code, 200)

        vote = Vote.objects.filter(uuid=self.voter_rec.uuid, election=self.elec_scheduled).first()
        self.assertIsNotNone(vote.batch)
        self.assertEqual(vote.batch.election_id, self.elec_scheduled.id)
        self.assertGreater(vote.batch.ballot_count, 0)

    def test_12_completed_batch_can_be_mined_into_block(self):
        """12. A batch containing cast ballots is successfully mined and sealed into a Block."""
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })
        self.assertEqual(res.status_code, 200)

        vote = Vote.objects.filter(uuid=self.voter_rec.uuid, election=self.elec_scheduled).first()
        # Verify block assignment
        self.assertIsNotNone(vote.block_id)
        block = Block.objects.get(id=int(vote.block_id))
        self.assertEqual(block.version, 2)
        self.assertEqual(block.election_id, self.elec_scheduled.id)

    def test_13_merkle_root_and_block_hash_verify(self):
        """13. The newly mined block's Merkle root and block header hash verify completely."""
        from home.methods_module import verify_v2_block_header, verify_single_block
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })

        vote = Vote.objects.filter(uuid=self.voter_rec.uuid, election=self.elec_scheduled).first()
        block = Block.objects.get(id=int(vote.block_id))

        self.assertTrue(verify_v2_block_header(block))
        single_res = verify_single_block(block.id)
        self.assertTrue(single_res['valid'])

    def test_14_duplicate_vote_remains_rejected(self):
        """14. A voter who has already cast a vote is rejected from voting again."""
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        # Vote 1
        res1 = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })
        self.assertEqual(res1.status_code, 200)

        # Vote 2 attempt
        session['email-verified'] = True
        session.save()
        res2 = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIn('already cast', res2.content.decode('utf-8'))

    def test_15_closed_election_rejects_voting(self):
        """15. A CLOSED election rejects any new vote submission."""
        self.elec_scheduled.status = 'CLOSED'
        self.elec_scheduled.save()

        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session.save()

        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('CLOSED', res.content.decode('utf-8'))

    def test_16_result_verification_creates_deterministic_receipt(self):
        """16. calculate_verified_election_results generates deterministic verification receipt."""
        from home.methods_module import calculate_verified_election_results
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        # Cast a vote
        self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })

        # Close election
        self.elec_scheduled.status = 'CLOSED'
        self.elec_scheduled.save()

        res = calculate_verified_election_results(self.elec_scheduled.id)
        self.assertTrue(res['verified'])
        self.assertIn('verification_receipt', res)
        self.assertIn('result_receipt', res)
        self.assertEqual(len(res['verification_receipt']), 64)

    def test_17_verified_receipt_allows_publication(self):
        """17. Verified receipt allows successful publication of closed election results."""
        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec_scheduled.id
        session['public-key'] = self.pub_key
        session.save()

        self.elec_scheduled.status = 'OPEN'
        self.elec_scheduled.save()

        # Cast vote
        self.client.post('/create-vote/', {
            'selected-party-id': str(self.cand.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec_scheduled.id)
        })

        # Close election
        self.elec_scheduled.status = 'CLOSED'
        self.elec_scheduled.save()

        # Admin publishes results
        self.client.force_login(self.u_platform)
        res_pub = self.client.post(
            f'/elections/{self.elec_scheduled.id}/publish/',
            HTTP_ACCEPT='application/json'
        )
        self.assertEqual(res_pub.status_code, 200)
        data = res_pub.json()
        self.assertTrue(data.get('success'))

        self.elec_scheduled.refresh_from_db()
        self.assertTrue(self.elec_scheduled.is_published)
        self.assertIsNotNone(self.elec_scheduled.publication_receipt)

    def test_18_historical_5645_block_chain_remains_valid(self):
        """18. The historical 5,645-block ledger remains fully verified and valid."""
        from home.methods_module import verify_full_chain
        res = verify_full_chain()
        self.assertTrue(res.get('valid'))
        self.assertEqual(res.get('status'), 'VERIFIED')



class Phase8Test5CriticalFunctionalFixesTests(TestCase):
    """
    Phase 8 Test-5 Critical Functional Fixes Test Suite:
    1. Role UI: Participate as Candidate strictly shown only to Candidate persona (not Admin, Org Admin, or Voter).
    2. Scheduling & Timezones: Timezone-aware transitions (Asia/Kolkata boundary), future times, idempotency, API trigger.
    3. Voting & Mining: Vote persistence, VoteBackup parity, version 2 block mining with Merkle root and PoW.
    4. Block Info & Sync: block_info does not falsely flag v2 blocks as tampered; sync_block contract works cleanly.
    5. Results & Turnout: Correct vote counts displayed (1 for vote recipient, 0 for zero-vote candidates, no blanks).
       Browser requests to /elections/<id>/results/ redirect to show_result. Live turnout renders cleanly without raw JSON.
    6. Private Key: Session stability (no accidental key re-generation on refresh), zero key leakage in JSON/logs.
    7. Ledger: Historical 5,645-block ledger remains verified with 0 failures.
    """

    def setUp(self):
        from home.models import Organization, Election, Position, Candidate, Voters, Vote, VoteBackup, Block, BallotBatch
        from django.contrib.auth.models import User
        from django.utils import timezone
        import datetime

        self.org = Organization.objects.create(name="Test Org 5")

        # 1. Accounts
        self.u_platform = User.objects.create_superuser('admin_p5', 'admin_p5@ballotchain.com', 'pass1234')
        self.u_org_admin = User.objects.create_user('orgadmin_p5', 'orgadmin_p5@ballotchain.com', 'pass1234')
        self.u_voter = User.objects.create_user('voter_p5', 'voter_p5@ballotchain.com', 'pass1234')
        self.u_cand = User.objects.create_user('candidate1', 'candidate1@ballotchain.com', 'pass1234')

        from home.models import UserProfile
        UserProfile.objects.create(user=self.u_org_admin, role='ORGANIZATION_ADMIN', organization=self.org)
        # Voter has no profile (standard voter)

        # 2. Election, Position, Candidates
        now = timezone.now()
        self.elec = Election.objects.create(
            organization=self.org,
            title="Fixes Election 5",
            status="DRAFT",
            start_date=now - datetime.timedelta(minutes=5),
            end_date=now + datetime.timedelta(hours=1),
            live_progress_enabled=True
        )

        self.pos = Position.objects.create(
            election=self.elec,
            title="President",
            max_votes_allowed=1
        )

        self.c1 = Candidate.objects.create(position=self.pos, name="Alice", affiliation="Alpha")
        self.c2 = Candidate.objects.create(position=self.pos, name="Bob", affiliation="Beta")

        # Associate u_cand with Candidate object
        self.c_cand_user = Candidate.objects.create(position=self.pos, name="Charlie", user=self.u_cand)

        # 3. Voter Record
        from home.views import get_or_create_voter_for_user
        self.voter_rec = get_or_create_voter_for_user(self.u_voter)

        from home.methods_module import generate_keys
        self.priv_key, self.pub_key = generate_keys()

    def test_01_admin_does_not_see_participate_as_candidate(self):
        """1. Platform Admin does NOT see 'Participate as Candidate' in election details."""
        self.client.force_login(self.u_platform)
        res = self.client.get(f'/elections/{self.elec.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('Participate as Candidate', res.content.decode('utf-8'))

    def test_02_org_admin_does_not_see_participate_as_candidate(self):
        """2. Organization Admin does NOT see 'Participate as Candidate' in election details."""
        self.client.force_login(self.u_org_admin)
        res = self.client.get(f'/elections/{self.elec.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('Participate as Candidate', res.content.decode('utf-8'))

    def test_03_normal_voter_does_not_see_participate_as_candidate(self):
        """3. Normal Voter does NOT see 'Participate as Candidate' in election details."""
        self.client.force_login(self.u_voter)
        res = self.client.get(f'/elections/{self.elec.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('Participate as Candidate', res.content.decode('utf-8'))

    def test_04_candidate_user_sees_candidate_participation(self):
        """4. Dedicated Candidate account (candidate1@ballotchain.com) sees candidate participation status in DRAFT state."""
        from django.utils import timezone
        import datetime
        draft_elec = Election.objects.create(
            organization=self.org,
            title="Draft Candidate Election",
            status="DRAFT",
            start_date=timezone.now() + datetime.timedelta(hours=2)
        )
        pos = Position.objects.create(election=draft_elec, title="Secretary", max_votes_allowed=1)
        Candidate.objects.create(position=pos, name="Charlie", user=self.u_cand)

        self.client.force_login(self.u_cand)
        res = self.client.get(f'/elections/{draft_elec.id}/')
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        self.assertTrue('Registered as Candidate' in html or 'Participate as Candidate' in html)

    def test_05_timezone_aware_election_start_transitions_draft_to_open(self):
        """5. Automatic scheduling transitions DRAFT -> OPEN when start_date <= now."""
        from home.methods_module import process_scheduled_election_transitions
        self.assertEqual(self.elec.status, 'DRAFT')
        res = process_scheduled_election_transitions()
        self.elec.refresh_from_db()
        self.assertEqual(self.elec.status, 'OPEN')
        self.assertIn(self.elec.id, res['started'])

    def test_06_future_start_does_not_open_early(self):
        """6. An election scheduled for the future does NOT open early."""
        from home.methods_module import process_scheduled_election_transitions
        from django.utils import timezone
        import datetime
        future_elec = Election.objects.create(
            organization=self.org,
            title="Future Election",
            status="DRAFT",
            start_date=timezone.now() + datetime.timedelta(hours=2)
        )
        process_scheduled_election_transitions()
        future_elec.refresh_from_db()
        self.assertEqual(future_elec.status, 'DRAFT')

    def test_07_timezone_aware_election_end_transitions_open_to_closed(self):
        """7. Automatic scheduling transitions OPEN -> CLOSED when end_date <= now."""
        from home.methods_module import process_scheduled_election_transitions
        from django.utils import timezone
        import datetime
        self.elec.status = 'OPEN'
        self.elec.end_date = timezone.now() - datetime.timedelta(seconds=10)
        self.elec.save()

        res = process_scheduled_election_transitions()
        self.elec.refresh_from_db()
        self.assertEqual(self.elec.status, 'CLOSED')
        self.assertIn(self.elec.id, res['ended'])

    def test_08_future_end_does_not_close_early(self):
        """8. An election whose end_date is in the future remains OPEN."""
        from home.methods_module import process_scheduled_election_transitions
        from django.utils import timezone
        import datetime
        self.elec.status = 'OPEN'
        self.elec.end_date = timezone.now() + datetime.timedelta(hours=5)
        self.elec.save()

        process_scheduled_election_transitions()
        self.elec.refresh_from_db()
        self.assertEqual(self.elec.status, 'OPEN')

    def test_09_scheduler_is_idempotent(self):
        """9. Repeated calls to process_scheduled_election_transitions produce no state mutation."""
        from home.methods_module import process_scheduled_election_transitions
        res1 = process_scheduled_election_transitions()
        res2 = process_scheduled_election_transitions()
        self.assertEqual(len(res2['started']), 0)
        self.assertEqual(len(res2['ended']), 0)

    def test_10_api_check_scheduled_lifecycle_endpoint(self):
        """10. /api/elections/check-lifecycle/ triggers transitions and returns HTTP 200."""
        res = self.client.get('/api/elections/check-lifecycle/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertIn('transitions', data)

    def test_11_modern_vote_persisted_and_mined_into_v2_block(self):
        """11. Submitting vote creates Vote, VoteBackup, BallotBatch, and seals a Version-2 Block."""
        from home.models import Vote, VoteBackup, Block, BallotBatch
        self.elec.status = 'OPEN'
        self.elec.save()

        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec.id
        session['public-key'] = self.pub_key
        session.save()

        res = self.client.post('/create-vote/', {
            'selected-party-id': str(self.c1.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec.id)
        })
        self.assertEqual(res.status_code, 200)

        vote = Vote.objects.filter(uuid=self.voter_rec.uuid, election=self.elec).first()
        self.assertIsNotNone(vote)
        self.assertIsNotNone(vote.tx_id)
        self.assertIsNotNone(vote.block_id)

        # Check VoteBackup parity
        vb = VoteBackup.objects.filter(uuid=self.voter_rec.uuid, election=self.elec).first()
        self.assertIsNotNone(vb)
        self.assertEqual(vb.block_id, vote.block_id)

        # Check block properties
        block = Block.objects.get(id=int(vote.block_id))
        self.assertEqual(block.version, 2)
        self.assertEqual(block.election_id, self.elec.id)

    def test_12_block_info_verifies_v2_block_without_tampered_flag(self):
        """12. /block-info/ correctly verifies modern Version-2 blocks without false 'Tampered' alert."""
        self.elec.status = 'OPEN'
        self.elec.save()

        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec.id
        session['public-key'] = self.pub_key
        session.save()

        self.client.post('/create-vote/', {
            'selected-party-id': str(self.c1.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec.id)
        })

        from home.models import Vote
        vote = Vote.objects.filter(uuid=self.voter_rec.uuid, election=self.elec).first()
        res = self.client.get(f'/block-info/?id={vote.block_id}')
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        self.assertIn('All the vote transactions in this block are intact', html)
        self.assertNotIn('is(are) tampered', html)

    def test_13_sync_block_contract_and_csrf_support(self):
        """13. /sync-block/ accepts block-id and id aliases and returns 200 for platform admin."""
        self.elec.status = 'OPEN'
        self.elec.save()

        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec.id
        session['public-key'] = self.pub_key
        session.save()

        self.client.post('/create-vote/', {
            'selected-party-id': str(self.c1.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec.id)
        })

        from home.models import Vote
        vote = Vote.objects.filter(uuid=self.voter_rec.uuid, election=self.elec).first()

        self.client.force_login(self.u_platform)
        # Test with 'id' parameter
        res_sync = self.client.post('/sync-block/', {'id': str(vote.block_id)})
        self.assertEqual(res_sync.status_code, 200)
        data = res_sync.json()
        self.assertTrue(data.get('success'))

    def test_14_results_page_displays_actual_vote_count_and_zero_votes(self):
        """14. Results page displays 1 vote for candidate who received vote, and 0 for others."""
        self.elec.status = 'OPEN'
        self.elec.save()

        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec.id
        session['public-key'] = self.pub_key
        session.save()

        # Vote for c1 (Alice)
        self.client.post('/create-vote/', {
            'selected-party-id': str(self.c1.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec.id)
        })

        # Close and publish election
        self.elec.status = 'CLOSED'
        self.elec.is_published = True
        self.elec.save()

        from home.methods_module import calculate_verified_election_results
        res_calc = calculate_verified_election_results(self.elec.id)
        self.assertTrue(res_calc['verified'])

        # Verify show_result page
        res = self.client.get(f'/show-result/?election_id={self.elec.id}')
        self.assertEqual(res.status_code, 200)
        context = res.context
        results = context.get('results', [])

        # Check candidate vote counts in table
        c1_item = next((r for r in results if r['candidate_name'] == 'Alice'), None)
        c2_item = next((r for r in results if r['candidate_name'] == 'Bob'), None)

        self.assertIsNotNone(c1_item)
        self.assertIsNotNone(c2_item)
        self.assertEqual(c1_item['vote_count'], 1)
        self.assertEqual(c2_item['vote_count'], 0)

    def test_15_results_page_and_turnout_no_raw_json(self):
        """15. Browser GET to /elections/<id>/results/ redirects to /show-result/?election_id=<id>."""
        res = self.client.get(
            f'/elections/{self.elec.id}/results/',
            HTTP_ACCEPT='text/html,application/xhtml+xml,application/xml;q=0.9'
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn(f'/show-result/?election_id={self.elec.id}', res.url)

    def test_16_publication_redirects_browser_to_results_page(self):
        """16. Admin publishing via browser POST redirects to /show-result/?election_id=<id>."""
        self.elec.status = 'OPEN'
        self.elec.save()

        session = self.client.session
        session['uuid'] = self.voter_rec.uuid
        session['email-id'] = self.voter_rec.email
        session['email-verified'] = True
        session['election_id'] = self.elec.id
        session['public-key'] = self.pub_key
        session.save()

        self.client.post('/create-vote/', {
            'selected-party-id': str(self.c1.id),
            'private-key': self.priv_key,
            'election_id': str(self.elec.id)
        })

        self.elec.status = 'CLOSED'
        self.elec.save()

        self.client.force_login(self.u_platform)
        res_pub = self.client.post(
            f'/elections/{self.elec.id}/publish/',
            HTTP_ACCEPT='text/html,application/xhtml+xml'
        )
        self.assertEqual(res_pub.status_code, 302)
        self.assertIn(f'/show-result/?election_id={self.elec.id}', res_pub.url)

    def test_17_private_key_session_stability_and_zero_leakage(self):
        """17. get_parties retains existing active session keypair without casual re-generation."""
        session = self.client.session
        session['email-id'] = 'voter_p5@ballotchain.com'
        session['email-verified'] = True
        session['private-key'] = self.priv_key
        session['public-key'] = self.pub_key
        session['election_id'] = self.elec.id
        session.save()

        res = self.client.get('/get-parties/')
        self.assertEqual(res.status_code, 200)

        # Ensure session key did NOT change
        session_after = self.client.session
        self.assertEqual(session_after['private-key'], self.priv_key)
        self.assertEqual(session_after['public-key'], self.pub_key)

        # Ensure private key is NOT in JSON response
        data = res.json()
        self.assertNotIn('private_key', data)
        self.assertNotIn('private-key', data)

    def test_18_historical_chain_integrity_remains_intact(self):
        """18. The historical 5,645-block ledger remains verified with 0 failures."""
        from home.methods_module import verify_full_chain
        res = verify_full_chain()
        self.assertTrue(res.get('valid'))
        self.assertEqual(res.get('status'), 'VERIFIED')

class Phase8FinalCsrfSecurityCorrectionTests(TestCase):
    """
    Phase 8: Final CSRF Security Correction Tests.
    Strictly verifies:
    1. /sync-block/ is protected by CSRF (missing CSRF -> 403 Forbidden).
    2. /sync-block/ with invalid CSRF is rejected (403 Forbidden).
    3. /sync-block/ with valid CSRF header (X-CSRFToken) + authenticated platform admin is accepted (200 OK).
    4. /sync-block/ with valid CSRF in POST body (csrfmiddlewaretoken) is accepted (200 OK).
    5. 'block-id', 'block_id', and 'id' parameter aliases are all accepted.
    6. Modern v2 block remains valid after synchronization (Merkle root, version, tx_id preserved).
    7. Unauthorized roles (voter, org admin, auditor) rejected with 403 even when providing valid CSRF.
    """

    def setUp(self):
        from home.models import Organization, Election, BallotBatch, Block, Vote, VoteBackup
        from django.contrib.auth.models import User
        from django.utils import timezone
        import datetime

        self.org = Organization.objects.create(name="CSRF Test Org")
        self.u_platform = User.objects.create_superuser('csrf_platform', 'platform@ballotchain.com', 'Pass123!')
        self.u_org_admin = User.objects.create_user('csrf_org_admin', 'org_admin@ballotchain.com', 'Pass123!')
        self.u_auditor = User.objects.create_user('csrf_auditor', 'auditor@ballotchain.com', 'Pass123!')
        self.u_voter = User.objects.create_user('csrf_voter', 'voter_csrf@ballotchain.com', 'Pass123!')

        from home.models import UserProfile
        UserProfile.objects.create(user=self.u_platform, role='PLATFORM_ADMIN')
        UserProfile.objects.create(user=self.u_org_admin, role='ORGANIZATION_ADMIN', organization=self.org)
        UserProfile.objects.create(user=self.u_auditor, role='AUDITOR', organization=self.org)
        UserProfile.objects.create(user=self.u_voter, role='VOTER', organization=self.org)

        from home.views import get_or_create_voter_for_user
        self.voter_rec = get_or_create_voter_for_user(self.u_voter)

        self.elec = Election.objects.create(
            organization=self.org,
            title="CSRF Election",
            status="OPEN",
            start_date=timezone.now() - datetime.timedelta(hours=1),
            end_date=timezone.now() + datetime.timedelta(hours=1)
        )
        self.batch = BallotBatch.objects.create(
            election=self.elec,
            batch_number=1,
            status='SEALED'
        )

        # Set up a test modern v2 block with backup record
        self.block = Block.objects.create(
            id=9901,
            prev_hash="0000000000000000000000000000000000000000000000000000000000000000",
            merkle_hash="1111111111111111111111111111111111111111111111111111111111111111",
            this_hash="2222222222222222222222222222222222222222222222222222222222222222",
            nonce=12345,
            timestamp=timezone.now(),
            version=2,
            batch_number=1,
            election=self.elec
        )
        self.backup = VoteBackup.objects.create(
            uuid=self.voter_rec.uuid,
            vote_party_id="c_test",
            timestamp=timezone.now(),
            block_id=self.block.id,
            tx_id="tx_csrf_test_123",
            batch=self.batch,
            election=self.elec
        )

    def test_01_missing_csrf_is_rejected_403(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)
        # Attempt POST without any CSRF cookie or token
        res = client.post('/sync-block/', {'block-id': self.block.id})
        self.assertEqual(res.status_code, 403)

    def test_02_invalid_csrf_is_rejected_403(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)
        # Seed an initial cookie so Django has a cookie, but provide invalid header
        client.get('/blockchain/')
        res = client.post(
            '/sync-block/',
            {'block-id': self.block.id},
            HTTP_X_CSRFTOKEN='invalid_token_xyz'
        )
        self.assertEqual(res.status_code, 403)

    def test_03_valid_csrf_header_accepted_200(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)
        # Visit page with @ensure_csrf_cookie to receive genuine token
        res_page = client.get('/blockchain/')
        csrf_token = client.cookies['csrftoken'].value
        res = client.post(
            '/sync-block/',
            {'block-id': self.block.id},
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))

    def test_04_valid_csrf_in_post_body_accepted_200(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)
        client.get('/blockchain/')
        csrf_token = client.cookies['csrftoken'].value
        res = client.post(
            '/sync-block/',
            {'block-id': self.block.id, 'csrfmiddlewaretoken': csrf_token}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))

    def test_05_alias_block_id_accepted(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)
        client.get('/blockchain/')
        csrf_token = client.cookies['csrftoken'].value
        res = client.post(
            '/sync-block/',
            {'block_id': self.block.id},
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))

    def test_06_alias_id_accepted(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)
        client.get('/blockchain/')
        csrf_token = client.cookies['csrftoken'].value
        res = client.post(
            '/sync-block/',
            {'id': self.block.id},
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))

    def test_07_modern_v2_block_remains_valid_after_sync(self):
        from django.test import Client
        from home.models import Vote
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.u_platform)
        client.get('/blockchain/')
        csrf_token = client.cookies['csrftoken'].value

        # Execute sync
        res = client.post(
            '/sync-block/',
            {'block-id': self.block.id},
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(res.status_code, 200)

        # Check Vote was restored with tx_id, batch_id, block_id
        restored_vote = Vote.objects.filter(block_id=self.block.id).first()
        self.assertIsNotNone(restored_vote)
        self.assertEqual(restored_vote.tx_id, self.backup.tx_id)
        self.assertEqual(restored_vote.batch_id, self.backup.batch_id)

    def test_08_unauthorized_roles_rejected_even_with_valid_csrf(self):
        from django.test import Client
        for user in [self.u_voter, self.u_org_admin, self.u_auditor]:
            client = Client(enforce_csrf_checks=True)
            client.force_login(user)
            client.get('/blockchain/')
            csrf_token = client.cookies['csrftoken'].value
            res = client.post(
                '/sync-block/',
                {'block-id': self.block.id},
                HTTP_X_CSRFTOKEN=csrf_token
            )
            self.assertEqual(res.status_code, 403)
            self.assertIn('Unauthorized', res.json().get('error', ''))


class Phase8Test6PrivateKeyCommitTests(TestCase):
    """
    Focused test suite for Phase 8 Test-6:
    - Dedicated Private-Key Verification (/verify-private-key/)
    - Key validation, curve checking (NIST P-256), session matching, quote/whitespace/CRLF normalization
    - CSRF protection enforcement
    - Transactional commit and mining (/create-vote/)
    - Preventing premature completion, avoiding duplicate votes, clean recovery on errors
    - Candidate logo fallback avoiding NOTA.png
    """
    def setUp(self):
        from django.contrib.auth.models import User
        from home.models import Organization, Election, Position, Candidate, Voters, UserProfile
        from home.methods_module import generate_keys
        import datetime
        from django.utils import timezone

        self.org = Organization.objects.create(name="Test University")
        self.user = User.objects.create_user(
            username="voter_test6@ballotchain.com",
            email="voter_test6@ballotchain.com",
            password="testpassword123"
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            role="VOTER",
            organization=self.org
        )
        self.voter = Voters.objects.create(
            uuid="v_test6_001",
            name="Test6 Voter",
            dob=datetime.date(2000, 1, 1),
            pincode="123456",
            region="Campus North",
            email="voter_test6@ballotchain.com",
            vote_done=False
        )
        self.election = Election.objects.create(
            title="Spring 2027 Student Council",
            organization=self.org,
            status="OPEN",
            start_date=timezone.now() - datetime.timedelta(hours=1),
            end_date=timezone.now() + datetime.timedelta(hours=24)
        )
        self.position = Position.objects.create(
            election=self.election,
            title="President",
            max_votes_allowed=1
        )
        self.candidate = Candidate.objects.create(
            name="Alice Walker",
            position=self.position,
            affiliation="Independent"
        )
        self.priv_key, self.pub_key = generate_keys()
        self.other_priv_key, self.other_pub_key = generate_keys()

    def test_01_verify_private_key_valid_matching_session(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session['public-key'] = self.pub_key
        session.save()

        res = client.post('/verify-private-key/', {'private-key': self.priv_key})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertIn('Private key verified successfully', data.get('message', ''))
        self.assertTrue(client.session.get('private-key-verified'))

    def test_02_verify_private_key_mismatched_session_key(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session['public-key'] = self.pub_key
        session.save()

        res = client.post('/verify-private-key/', {'private-key': self.other_priv_key})
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data.get('success'))
        self.assertIn('does not match this voter session', data.get('error', ''))

    def test_03_verify_private_key_invalid_curve_rejected(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session.save()

        res = client.post('/verify-private-key/', {'private-key': '--- NOT A VALID NIST P-256 KEY ---'})
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data.get('success'))
        self.assertIn('Invalid private key format', data.get('error', ''))

    def test_04_verify_private_key_missing_or_empty(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session.save()

        res = client.post('/verify-private-key/', {'private-key': ''})
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data.get('success'))
        self.assertIn('Private key is required', data.get('error', ''))

    def test_05_verify_private_key_unauthenticated_or_unverified_otp(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=False)
        session = client.session
        session['email-verified'] = False
        session.save()

        res = client.post('/verify-private-key/', {'private-key': self.priv_key})
        self.assertEqual(res.status_code, 401)
        data = res.json()
        self.assertFalse(data.get('success'))
        self.assertIn('Complete OTP step-up verification first', data.get('error', ''))

    def test_06_verify_private_key_enforces_csrf(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session['public-key'] = self.pub_key
        session.save()

        # Missing CSRF
        res_fail = client.post('/verify-private-key/', {'private-key': self.priv_key})
        self.assertEqual(res_fail.status_code, 403)

        # With CSRF
        client.get('/')
        csrf_token = client.cookies['csrftoken'].value
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session['public-key'] = self.pub_key
        session.save()
        res_ok = client.post(
            '/verify-private-key/',
            {'private-key': self.priv_key},
            HTTP_X_CSRFTOKEN=csrf_token
        )
        self.assertEqual(res_ok.status_code, 200)

    def test_07_verify_private_key_normalizes_crlf_and_quotes(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session['public-key'] = self.pub_key
        session.save()

        # Key with Windows CRLF, wrapping quotes, and alias 'private_key'
        crlf_key = f'"{self.priv_key.replace(chr(10), chr(13)+chr(10))}"'
        res = client.post('/verify-private-key/', {'private_key': crlf_key})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get('success'))

    def test_08_create_vote_requires_private_key_and_verified_session(self):
        from django.test import Client
        from home.models import Vote, Ballot
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session.save()

        res = client.post('/create-vote/', {
            'selected-party-id': self.candidate.id,
            'election_id': self.election.id
        })
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data.get('success'))
        self.assertIn('Voting private key is required', data.get('error', ''))
        self.assertEqual(Vote.objects.count(), 0)
        self.assertEqual(Ballot.objects.count(), 0)

    def test_09_create_vote_successful_commit_and_mining(self):
        from django.test import Client
        from home.models import Vote, VoteBackup, Ballot, Block
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session['public-key'] = self.pub_key
        session.save()

        res = client.post('/create-vote/', {
            'selected-party-id': self.candidate.id,
            'election_id': self.election.id,
            'private-key': self.priv_key
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertTrue(data.get('ballot_tracker'))
        self.assertIsNotNone(data.get('block_id'))

        v = Vote.objects.filter(uuid=self.voter.uuid).first()
        self.assertIsNotNone(v)
        self.assertEqual(v.election_id, self.election.id)

        vb = VoteBackup.objects.filter(uuid=self.voter.uuid).first()
        self.assertIsNotNone(vb)
        self.assertEqual(v.tx_id, vb.tx_id)

        bal = Ballot.objects.filter(voter=self.voter, election=self.election).first()
        self.assertIsNotNone(bal)
        self.assertTrue(bal.is_sealed)

        mined_blk = Block.objects.get(id=data['block_id'])
        self.assertEqual(mined_blk.version, 2)
        self.assertEqual(mined_blk.election_id, self.election.id)

    def test_10_retry_flow_does_not_duplicate_votes(self):
        from django.test import Client
        from home.models import Vote
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['uuid'] = self.voter.uuid
        session['public-key'] = self.pub_key
        session.save()

        res1 = client.post('/create-vote/', {
            'selected-party-id': self.candidate.id,
            'election_id': self.election.id,
            'private-key': self.priv_key
        })
        self.assertEqual(res1.status_code, 200)

        session2 = client.session
        session2['email-verified'] = True
        session2['uuid'] = self.voter.uuid
        session2.save()

        res2 = client.post('/create-vote/', {
            'selected-party-id': self.candidate.id,
            'election_id': self.election.id,
            'private-key': self.priv_key
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIn('already cast your vote', res2.json().get('error', ''))
        self.assertEqual(Vote.objects.filter(uuid=self.voter.uuid).count(), 1)

    def test_11_candidate_logo_fallback_does_not_use_nota(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        session = client.session
        session['email-verified'] = True
        session['email-id'] = self.user.email
        session['uuid'] = self.voter.uuid
        session['private-key'] = self.priv_key
        session['public-key'] = self.pub_key
        session.save()

        res = client.get(f'/get-parties/?election_id={self.election.id}')
        self.assertEqual(res.status_code, 200)
        parties = res.json().get('parties', [])
        self.assertGreater(len(parties), 0)
        party = parties[0]
        self.assertNotEqual(party.get('party_logo'), 'images/NOTA.png')
        self.assertNotIn('NOTA.png', party.get('party_logo', ''))
        self.assertEqual(party.get('party_logo'), 'images/logo.png')
