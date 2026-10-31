import json
import secrets
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from home.models import (
    Organization, Election, Position, Candidate,
    Voters, UserProfile, Eligibility, Ballot, Vote, VoteBackup, Block, BallotBatch
)
from home.methods_module import (
    calculate_verified_election_results,
    ensure_nota_candidate_for_position,
    ensure_nota_candidates_for_election,
    ResultPublicationState,
    generate_keys,
    build_auth_payload,
    sign_auth_payload,
    submit_modern_ballot,
    mine_modern_batch
)


class Phase8Test7ResultsVisibilityAndNotaTests(TestCase):
    """
    Phase 8 — Test 7: Election Progress, Results Visibility, React Bits Standings & NOTA.
    Comprehensive automated verification covering all 27 requirements.
    """

    @classmethod
    def setUpTestData(cls):
        # 1. Organization
        cls.org = Organization.objects.create(name="Test University", description="Academic Testing Org")

        # 2. Users with Profiles
        # Admin
        cls.admin_user = User.objects.create_user(username="admin_test7", email="admin7@test.edu", password="password123")
        UserProfile.objects.create(user=cls.admin_user, role='ORGANIZATION_ADMIN', organization=cls.org)

        # Platform Admin
        cls.platform_admin_user = User.objects.create_user(username="plat_admin_test7", email="platadmin7@test.edu", password="password123", is_superuser=True)
        UserProfile.objects.create(user=cls.platform_admin_user, role='PLATFORM_ADMIN')

        # Voter
        cls.voter_user = User.objects.create_user(username="voter_test7", email="voter7@test.edu", password="password123")
        UserProfile.objects.create(user=cls.voter_user, role='MEMBER', organization=cls.org)
        cls.voter_obj = Voters.objects.create(
            uuid="voter_uuid_test7",
            name="Voter Seven",
            dob="1995-05-05",
            pincode="500001",
            region="Campus A",
            email="voter7@test.edu",
            vote_done=False
        )

        # Additional test voters for casting ballots
        cls.voters_pool = []
        cls.keys_pool = []
        for i in range(1, 10):
            v = Voters.objects.create(
                uuid=f"voter_test7_pool_{i}",
                name=f"Voter Pool {i}",
                dob="1995-01-01",
                pincode="500001",
                region="Campus A",
                email=f"voter_pool_{i}@test.edu",
                vote_done=False
            )
            cls.voters_pool.append(v)
            priv, pub = generate_keys()
            cls.keys_pool.append((priv, pub))

        # Candidate User
        cls.candidate_user = User.objects.create_user(username="cand_user_test7", email="cand7@test.edu", password="password123")
        UserProfile.objects.create(user=cls.candidate_user, role='MEMBER', organization=cls.org)

        # 3. Elections for lifecycle testing
        # DRAFT election
        cls.draft_election = Election.objects.create(
            organization=cls.org,
            title="Draft Election",
            status="DRAFT",
            live_progress_enabled=False,
            is_published=False
        )

        # OPEN election with live progress ENABLED
        cls.open_election = Election.objects.create(
            organization=cls.org,
            title="Active Student Senate Election",
            status="OPEN",
            live_progress_enabled=True,
            is_published=False
        )

        # OPEN election with live progress DISABLED
        cls.open_no_progress_election = Election.objects.create(
            organization=cls.org,
            title="Private Presidential Election",
            status="OPEN",
            live_progress_enabled=False,
            is_published=False
        )

        # CLOSED election NOT published
        cls.closed_unpublished_election = Election.objects.create(
            organization=cls.org,
            title="Closed Interim Election",
            status="CLOSED",
            live_progress_enabled=False,
            is_published=False
        )

        # CLOSED election PUBLISHED
        cls.closed_published_election = Election.objects.create(
            organization=cls.org,
            title="Certified Faculty Board Election",
            status="CLOSED",
            live_progress_enabled=False,
            is_published=True,
            published_at=timezone.now(),
            publication_receipt="b3a9c7d4e5f6a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6"
        )

        # 4. Positions & Candidates setup
        cls.pos_open = Position.objects.create(
            election=cls.open_election,
            title="President",
            max_votes_allowed=1
        )
        cls.cand_open_1 = Candidate.objects.create(
            position=cls.pos_open,
            name="Alice Walker",
            affiliation="Campus Unity",
            user=cls.candidate_user
        )
        cls.cand_open_2 = Candidate.objects.create(
            position=cls.pos_open,
            name="Bob Builder",
            affiliation="Independent Reform"
        )
        # Ensure NOTA for open position
        ensure_nota_candidate_for_position(cls.pos_open)

        # Position for Published Election
        cls.pos_pub = Position.objects.create(
            election=cls.closed_published_election,
            title="Chairperson",
            max_votes_allowed=1
        )
        cls.cand_pub_1 = Candidate.objects.create(
            position=cls.pos_pub,
            name="Carol Danvers",
            affiliation="Science Guild"
        )
        cls.cand_pub_2 = Candidate.objects.create(
            position=cls.pos_pub,
            name="David Copperfield",
            affiliation="Arts Guild"
        )
        nota_pub = ensure_nota_candidate_for_position(cls.pos_pub)
        cls.nota_pub = nota_pub

        # Submit and mine votes for published election:
        # 1 vote for Carol Danvers
        cls._cast_and_mine(cls.closed_published_election, cls.pos_pub, cls.cand_pub_1, cls.voters_pool[0], cls.keys_pool[0])
        # 2 votes for NOTA (NOTA receives the highest vote count)
        cls._cast_and_mine(cls.closed_published_election, cls.pos_pub, nota_pub, cls.voters_pool[1], cls.keys_pool[1])
        cls._cast_and_mine(cls.closed_published_election, cls.pos_pub, nota_pub, cls.voters_pool[2], cls.keys_pool[2])

    @classmethod
    def _cast_and_mine(cls, election, position, candidate, voter, keys):
        priv_key, pub_key = keys
        ballot = Ballot.objects.create(voter=voter, election=election)
        nonce = secrets.token_hex(32)
        ts = timezone.now().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        auth_payload = build_auth_payload(election.id, voter.uuid, nonce, ts)
        sig = sign_auth_payload(priv_key, auth_payload)
        submit_modern_ballot(
            ballot=ballot,
            candidate_selections=[(position, candidate)],
            signature=sig,
            public_key=pub_key,
            ballot_nonce=nonce,
            timestamp_iso=ts,
            auth_payload=auth_payload
        )
        ballot.refresh_from_db()
        mine_modern_batch(batch_id=ballot.batch_id)
        return ballot

    def setUp(self):
        self.client = Client()

    # =========================================================================
    # PART 1: OPEN ELECTION — VOTER & CANDIDATE VIEW & PRIVACY RULES
    # =========================================================================

    def test_01_open_election_voter_view_shows_live_election_progress(self):
        """1. When live progress is enabled, Voter sees Live Election Progress."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.open_election.id}')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn("Live Election Progress", html)
        self.assertNotIn("Live Turnout", html)

    def test_02_open_election_candidate_view_shows_live_election_progress(self):
        """2. When live progress is enabled, Candidate sees Live Election Progress."""
        self.client.force_login(self.candidate_user)
        response = self.client.get(f'/show-result/?election_id={self.open_election.id}')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn("Live Election Progress", html)
        self.assertNotIn("Live Turnout", html)

    def test_03_open_election_displays_ballots_votes_status(self):
        """3. Live Election Progress displays Ballots Submitted, Votes Recorded, and Status."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.open_election.id}')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn("Ballots Submitted", html)
        self.assertIn("Votes Recorded", html)
        self.assertIn("Status", html)

    def test_04_open_election_privacy_rule_candidate_counts_hidden(self):
        """4. Strict Privacy Rule: In OPEN election, non-staff NEVER see candidate vote counts."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.open_election.id}')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get('results_visible'))
        html = response.content.decode('utf-8')
        # Results notice must state privacy
        self.assertIn("Results Currently Unavailable", html)
        self.assertIn("privacy", html.lower())
        # Results data script must be empty [] to prevent leaking
        self.assertIn('id="ballotchain-results-data"', html)
        self.assertIn('[]</script>', html)
        self.assertEqual(response.context.get('results'), [])

    def test_05_open_election_privacy_rule_candidate_rankings_hidden(self):
        """5. Candidate rankings/percentages are hidden during OPEN election."""
        self.client.force_login(self.candidate_user)
        response = self.client.get(f'/show-result/?election_id={self.open_election.id}')
        self.assertFalse(response.context.get('results_visible'))
        self.assertEqual(response.context.get('results'), [])

    def test_06_open_election_live_progress_disabled_shows_no_progress(self):
        """6. When Admin disables live progress on OPEN election, progress stats are hidden."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.open_no_progress_election.id}')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context.get('live_progress_stats'))
        html = response.content.decode('utf-8')
        self.assertNotIn("Ballots Submitted", html)

    def test_07_election_detail_page_uses_live_election_progress_terminology(self):
        """7. Dashboard -> Election -> View uses 'Live Election Progress', not 'Live Turnout'."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/elections/{self.open_election.id}/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn("Live Election Progress", html)
        self.assertNotIn("Live Turnout Progress", html)

    # =========================================================================
    # PART 2: RESULTS HIDDEN BEFORE PUBLICATION (LIFECYCLE)
    # =========================================================================

    def test_08_draft_election_results_hidden(self):
        """8. DRAFT status: Results withheld for non-staff."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.draft_election.id}')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get('results_visible'))

    def test_09_closed_unpublished_results_hidden(self):
        """9. CLOSED but UNPUBLISHED: Results withheld for non-staff."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.closed_unpublished_election.id}')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get('results_visible'))

    def test_10_closed_published_results_visible(self):
        """10. CLOSED + PUBLISHED: Verified candidate results visible to voters & candidates."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.closed_published_election.id}')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context.get('results_visible'))
        self.assertGreater(len(response.context.get('results')), 0)

    # =========================================================================
    # PART 3: REACT BITS CANDIDATE STANDINGS COMPONENT DATA
    # =========================================================================

    def test_11_react_bits_island_mount_point_present_in_published(self):
        """11. React Bits animated candidate roster island root is rendered."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.closed_published_election.id}')
        html = response.content.decode('utf-8')
        self.assertIn('id="ballotchain-roster-island-root"', html)
        self.assertIn('data-island="animated-candidate-roster"', html)

    def test_12_react_bits_results_data_json_contains_all_candidates_and_nota(self):
        """12. Published results JSON script delivers Rank, Candidate Name, Votes, and Share."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.closed_published_election.id}')
        results = response.context.get('results')
        self.assertIsNotNone(results)
        # Should contain Carol, David, and NOTA
        names = [r['candidate_name'] for r in results]
        self.assertIn("Carol Danvers", names)
        self.assertIn("David Copperfield", names)
        self.assertTrue(any("NOTA" in name or "None of the Above" in name for name in names))

        for r in results:
            self.assertIn('rank', r)
            self.assertIn('candidate_name', r)
            self.assertIn('vote_count', r)
            self.assertIn('percentage', r)
            self.assertIn('is_winner', r)
            self.assertIn('is_nota', r)

    # =========================================================================
    # PART 4: REMOVE DUPLICATE POSITION RESULTS TABLE
    # =========================================================================

    def test_13_duplicate_position_results_table_removed_from_dom(self):
        """13. The redundant table aria-label='Position Results Table' is completely removed."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.closed_published_election.id}')
        html = response.content.decode('utf-8')
        self.assertNotIn('aria-label="Position Results Table"', html)
        self.assertNotIn('class="vote-count"', html)

    def test_14_admin_also_sees_no_duplicate_position_results_table(self):
        """14. Position Results Table is absent for admin view as well."""
        self.client.force_login(self.admin_user)
        response = self.client.get(f'/show-result/?election_id={self.closed_published_election.id}')
        html = response.content.decode('utf-8')
        self.assertNotIn('aria-label="Position Results Table"', html)

    # =========================================================================
    # PART 5: NOTA BALLOT CHOICE & IDEMPOTENCE
    # =========================================================================

    def test_15_ensure_nota_candidate_is_idempotent(self):
        """15. Calling ensure_nota_candidate_for_position multiple times creates exactly one NOTA."""
        pos = Position.objects.create(election=self.open_election, title="Treasurer")
        n1 = ensure_nota_candidate_for_position(pos)
        self.assertIsNotNone(n1)
        self.assertTrue(n1.is_nota)

        # Call again
        n2 = ensure_nota_candidate_for_position(pos)
        self.assertEqual(n1.id, n2.id)

        # Call election-wide helper
        ensure_nota_candidates_for_election(self.open_election)
        count = Candidate.objects.filter(position=pos, is_nota=True).count()
        self.assertEqual(count, 1)

    def test_16_get_parties_includes_nota_choice(self):
        """16. Voter ballot API (/get-parties/) includes NOTA with generic styling."""
        self.client.force_login(self.voter_user)
        session = self.client.session
        session['email-verified'] = True
        session['uuid'] = self.voter_obj.uuid
        session.save()

        response = self.client.get(f'/get-parties/?election_id={self.open_election.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        parties = data.get('parties', [])
        nota_parties = [p for p in parties if p.get('is_nota') is True or 'NOTA' in p.get('party_name', '')]
        self.assertGreaterEqual(len(nota_parties), 1)
        nota_item = nota_parties[0]
        self.assertTrue(nota_item.get('is_nota'))
        self.assertNotIn('NOTA.png', nota_item.get('party_logo', ''))
        self.assertEqual(nota_item.get('party_logo'), '')

    # =========================================================================
    # PART 6: NOTA WINNING RULE & WINNER RESOLUTION
    # =========================================================================

    def test_17_nota_never_elected_when_nota_has_highest_votes(self):
        """
        17. NOTA Winning Rule:
        In cls.closed_published_election:
        - NOTA has 2 votes (highest)
        - Carol has 1 vote (second-highest)
        - David has 0 votes
        Rule: NOTA is NEVER elected. The candidate with second-highest votes (Carol) is elected.
        """
        results_data = calculate_verified_election_results(self.closed_published_election.id)
        self.assertTrue(results_data.get('verified'))

        pos_info = results_data['positions'][0]
        cands = pos_info['candidates']

        # Ranked by votes descending: NOTA (2), Carol (1), David (0)
        self.assertEqual(cands[0]['is_nota'], True)
        self.assertEqual(cands[0]['votes_received'], 2)
        self.assertFalse(cands[0]['is_winner'])
        self.assertNotEqual(cands[0]['status'], 'Elected')

        # Real candidate with second-highest vote count must be elected
        self.assertEqual(cands[1]['candidate_name'], "Carol Danvers")
        self.assertEqual(cands[1]['votes_received'], 1)
        self.assertTrue(cands[1]['is_winner'])
        self.assertEqual(cands[1]['status'], 'Elected')

        # Third place candidate not elected
        self.assertEqual(cands[2]['candidate_name'], "David Copperfield")
        self.assertEqual(cands[2]['votes_received'], 0)
        self.assertFalse(cands[2]['is_winner'])

    def test_18_normal_candidate_elected_when_normal_candidate_has_highest_votes(self):
        """18. When a normal candidate has highest votes, that candidate is elected."""
        elec = Election.objects.create(
            organization=self.org,
            title="Normal Win Election",
            status="CLOSED",
            is_published=True
        )
        pos = Position.objects.create(election=elec, title="Secretary")
        c1 = Candidate.objects.create(position=pos, name="Winner Normal")
        c2 = Candidate.objects.create(position=pos, name="Runner Up")
        nota = ensure_nota_candidate_for_position(pos)

        # Winner Normal gets 2 votes, NOTA gets 1 vote, Runner Up gets 0
        self._cast_and_mine(elec, pos, c1, self.voters_pool[3], self.keys_pool[3])
        self._cast_and_mine(elec, pos, c1, self.voters_pool[4], self.keys_pool[4])
        self._cast_and_mine(elec, pos, nota, self.voters_pool[5], self.keys_pool[5])

        res = calculate_verified_election_results(elec.id)
        self.assertTrue(res.get('verified'))
        cands = res['positions'][0]['candidates']

        # Rank 1: Winner Normal
        self.assertEqual(cands[0]['candidate_name'], "Winner Normal")
        self.assertEqual(cands[0]['votes_received'], 2)
        self.assertTrue(cands[0]['is_winner'])
        self.assertEqual(cands[0]['status'], 'Elected')

        # Rank 2: NOTA
        self.assertEqual(cands[1]['is_nota'], True)
        self.assertFalse(cands[1]['is_winner'])

    def test_19_tie_between_normal_candidates_handled_deterministically(self):
        """19. Tie between normal candidates handles cleanly without crashing or results corruption."""
        elec = Election.objects.create(
            organization=self.org,
            title="Tie Election",
            status="CLOSED",
            is_published=True
        )
        pos = Position.objects.create(election=elec, title="Representative")
        c1 = Candidate.objects.create(position=pos, name="Candidate Alpha")
        c2 = Candidate.objects.create(position=pos, name="Candidate Beta")
        nota = ensure_nota_candidate_for_position(pos)

        # Each candidate gets 1 vote
        self._cast_and_mine(elec, pos, c1, self.voters_pool[6], self.keys_pool[6])
        self._cast_and_mine(elec, pos, c2, self.voters_pool[7], self.keys_pool[7])

        res = calculate_verified_election_results(elec.id)
        self.assertTrue(res['verified'])
        cands = res['positions'][0]['candidates']
        self.assertEqual(len(cands), 3)  # c1, c2, NOTA

    # =========================================================================
    # PART 7: ADMIN CANDIDATE CONFIGURATION (NO MAX VOTES AT CANDIDATE LEVEL)
    # =========================================================================

    def test_20_candidate_create_form_does_not_contain_max_votes(self):
        """20. Candidate Add modal / form does not ask for or require Max Votes."""
        self.client.force_login(self.admin_user)
        response = self.client.get(f'/elections/{self.open_election.id}/')
        html = response.content.decode('utf-8')
        # Check inside modal-add-candidate
        cand_modal_start = html.find('id="modal-add-candidate"')
        cand_modal_end = html.find('</form>', cand_modal_start)
        cand_modal_html = html[cand_modal_start:cand_modal_end]
        self.assertNotIn("Max Votes", cand_modal_html)
        self.assertNotIn("max_votes", cand_modal_html)

    def test_21_position_modal_uses_maximum_selections_allowed(self):
        """21. Position modal uses 'Maximum selections allowed' terminology."""
        self.client.force_login(self.admin_user)
        response = self.client.get(f'/elections/{self.open_election.id}/')
        html = response.content.decode('utf-8')
        self.assertIn("Maximum selections allowed", html)

    def test_22_position_create_automatically_creates_nota(self):
        """22. POST /positions/create/ automatically ensures NOTA candidate is created."""
        self.client.force_login(self.admin_user)
        response = self.client.post('/positions/create/', {
            'election_id': self.draft_election.id,
            'title': 'Ombudsperson',
            'max_votes_allowed': 1
        })
        self.assertEqual(response.status_code, 302)
        pos = Position.objects.get(election=self.draft_election, title='Ombudsperson')
        nota_count = Candidate.objects.filter(position=pos, is_nota=True).count()
        self.assertEqual(nota_count, 1)

    def test_23_react_bits_standings_format_calculation(self):
        """23. React Bits results format provides Candidate Name, Verified Vote Count, and Share %."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.closed_published_election.id}')
        results = response.context.get('results')
        self.assertIsNotNone(results)
        carol = next(r for r in results if r['candidate_name'] == 'Carol Danvers')
        # 1 vote out of 3 total = 33.3%
        self.assertEqual(carol['vote_count'], 1)
        self.assertAlmostEqual(carol['percentage'], 33.3, places=1)
        # Formatted string format
        summary = f"{carol['candidate_name']} — {carol['vote_count']} vote — {carol['percentage']:.1f}%"
        self.assertEqual(summary, "Carol Danvers — 1 vote — 33.3%")

    def test_24_closed_with_live_progress_still_withholds_candidate_results_until_published(self):
        """24. If live_progress_enabled was True and election is CLOSED, candidate results remain hidden until published."""
        closed_elec = Election.objects.create(
            organization=self.org,
            title="Closed Previously Live Election",
            status="CLOSED",
            live_progress_enabled=True,
            is_published=False
        )
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={closed_elec.id}')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context.get('results_visible'))
        self.assertEqual(response.context.get('results'), [])
        html = response.content.decode('utf-8')
        self.assertIn("Results Currently Unavailable", html)

    def test_25_tie_between_nota_and_real_candidate_elects_real_candidate(self):
        """25. When NOTA and a real candidate tie for highest votes, NOTA is not elected; real candidate is elected."""
        elec = Election.objects.create(
            organization=self.org,
            title="NOTA Tie Election",
            status="CLOSED",
            is_published=True
        )
        pos = Position.objects.create(election=elec, title="Auditor General")
        c1 = Candidate.objects.create(position=pos, name="Auditor Hopeful")
        nota = ensure_nota_candidate_for_position(pos)

        # 1 vote for c1, 1 vote for NOTA
        self._cast_and_mine(elec, pos, c1, self.voters_pool[0], self.keys_pool[0])
        self._cast_and_mine(elec, pos, nota, self.voters_pool[1], self.keys_pool[1])

        res = calculate_verified_election_results(elec.id)
        self.assertTrue(res['verified'])
        cands = res['positions'][0]['candidates']

        # Both have 1 vote
        c1_data = next(c for c in cands if c['candidate_name'] == "Auditor Hopeful")
        nota_data = next(c for c in cands if c['is_nota'])

        self.assertEqual(c1_data['votes_received'], 1)
        self.assertEqual(nota_data['votes_received'], 1)
        # Real candidate is elected
        self.assertTrue(c1_data['is_winner'])
        self.assertEqual(c1_data['status'], 'Elected')
        # NOTA is NEVER elected
        self.assertFalse(nota_data['is_winner'])
        self.assertNotEqual(nota_data['status'], 'Elected')

    def test_26_nota_with_zero_votes_participates_in_results_cleanly(self):
        """26. NOTA with zero votes has valid rank, 0 votes, and 0.0% share without crashing."""
        elec = Election.objects.create(
            organization=self.org,
            title="Zero NOTA Election",
            status="CLOSED",
            is_published=True
        )
        pos = Position.objects.create(election=elec, title="Dean")
        c1 = Candidate.objects.create(position=pos, name="Dean Candidate")
        nota = ensure_nota_candidate_for_position(pos)

        self._cast_and_mine(elec, pos, c1, self.voters_pool[0], self.keys_pool[0])

        res = calculate_verified_election_results(elec.id)
        self.assertTrue(res['verified'])
        cands = res['positions'][0]['candidates']
        nota_data = next(c for c in cands if c['is_nota'])
        self.assertEqual(nota_data['votes_received'], 0)
        self.assertEqual(nota_data['percentage'], 0.0)
        self.assertFalse(nota_data['is_winner'])
        self.assertEqual(nota_data['rank'], 2)

    def test_27_open_election_no_results_table_rendered_in_dom(self):
        """27. During OPEN election, no Position Results Table or Candidate Roster Island is rendered."""
        self.client.force_login(self.voter_user)
        response = self.client.get(f'/show-result/?election_id={self.open_election.id}')
        html = response.content.decode('utf-8')
        self.assertNotIn('aria-label="Position Results Table"', html)
        self.assertNotIn('data-island="animated-candidate-roster"', html)

    # =========================================================================
    # PART 8: PLATFORM ADMIN VOTING CTA REMOVAL & ROLE-AWARE DETAIL VIEW
    # =========================================================================

    def test_28_platform_admin_does_not_see_voting_is_open_or_cast_ballot_cta(self):
        """28. Platform Admin must NOT see 'Voting is Open' or 'Cast Your Ballot' on open election."""
        self.client.force_login(self.platform_admin_user)
        response = self.client.get(f'/elections/{self.open_election.id}/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        # Voter CTA and card must be absent for Platform Admin
        self.assertNotIn("Voting is Open", html)
        self.assertNotIn("Cast Your Ballot", html)
        self.assertNotIn(f"/elections/{self.open_election.id}/vote/", html)
        self.assertNotIn('<div class="availability-card">', html)
        self.assertFalse(response.context.get('can_vote'))

    def test_29_platform_admin_retains_lifecycle_controls_end_election_and_edit(self):
        """29. Platform Admin keeps Admin lifecycle controls such as End Election and Edit."""
        self.client.force_login(self.platform_admin_user)
        response = self.client.get(f'/elections/{self.open_election.id}/')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        # Admin controls must remain present
        self.assertIn("Lifecycle Controls:", html)
        self.assertIn("End Election", html)
        self.assertIn(f"/elections/{self.open_election.id}/end/", html)
        self.assertIn(f"/elections/{self.open_election.id}/edit/", html)
        self.assertTrue(response.context.get('can_manage'))

    def test_30_normal_eligible_voter_and_candidate_retain_voting_card_and_cta(self):
        """30. Normal eligible Voters and Candidates continue to see 'Voting is Open' and 'Cast Your Ballot'."""
        # Check Voter
        self.client.force_login(self.voter_user)
        response_voter = self.client.get(f'/elections/{self.open_election.id}/')
        self.assertEqual(response_voter.status_code, 200)
        html_voter = response_voter.content.decode('utf-8')
        self.assertIn("Voting is Open", html_voter)
        self.assertIn("Cast Your Ballot", html_voter)
        self.assertIn(f"/elections/{self.open_election.id}/vote/", html_voter)
        self.assertNotIn("End Election", html_voter)

        # Check Candidate (also eligible voter persona)
        # Create voter record for candidate to ensure eligibility
        Voters.objects.create(
            uuid="cand_voter_uuid",
            name="Candidate Alice",
            dob="1992-02-02",
            pincode="500001",
            region="Campus A",
            email="cand7@test.edu",
            vote_done=False
        )
        self.client.force_login(self.candidate_user)
        response_cand = self.client.get(f'/elections/{self.open_election.id}/')
        self.assertEqual(response_cand.status_code, 200)
        html_cand = response_cand.content.decode('utf-8')
        self.assertIn("Voting is Open", html_cand)
        self.assertIn("Cast Your Ballot", html_cand)
        self.assertIn(f"/elections/{self.open_election.id}/vote/", html_cand)
        self.assertNotIn("End Election", html_cand)


