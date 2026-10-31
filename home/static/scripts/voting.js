var selected = null;
var selectedPartyID = null;
var selectedPartyName = '';
var selectedPartyLogo = '';
var selectedPartyPos = '';
var isKeyVerified = false;

function setStepActive(stepNum) {
    $('.flow-steps-tracker .step-pill').removeClass('active');
    if (stepNum === 2) {
        $('#step-otp-pill').addClass('done');
        $('#step-select-pill').addClass('active');
    } else if (stepNum === 3) {
        $('#step-select-pill').addClass('done');
        $('#step-review-pill').addClass('active');
    } else if (stepNum === 4) {
        $('#step-review-pill').addClass('done');
        $('#step-key-pill').addClass('active');
    } else if (stepNum === 5) {
        $('#step-key-pill').addClass('done');
        $('#step-commit-pill').addClass('active');
    }
}

$(document).ready(function() {
    setStepActive(2);

    // Search filter across candidates
    $('#search').on('input', function() {
        var query = $(this).val().toLowerCase();
        if (typeof parties_list_json !== 'undefined' && parties_list_json) {
            for (var party of parties_list_json) {
                var name = (party.candidate_name || party.party_name || '').toLowerCase();
                if (name.includes(query)) {
                    $('#' + party.party_id).css('display', 'flex');
                } else {
                    $('#' + party.party_id).css('display', 'none');
                }
            }
        }
    });

    // Handle candidate selection
    function selectCandidate(id, name, logo, pos) {
        selectedPartyID = id;
        selectedPartyName = name || 'Selected Candidate';
        selectedPartyLogo = logo || '/static/images/logo.png';
        selectedPartyPos = pos || 'Candidate';

        $('#review-candidate-name').text(selectedPartyName);
        $('#review-candidate-logo').attr('src', selectedPartyLogo);
        $('#review-position-title').text(selectedPartyPos);

        $('#step-5-candidate-name').text(selectedPartyName);
        $('#step-5-candidate-logo').attr('src', selectedPartyLogo);
        $('#step-5-position-title').text(selectedPartyPos);

        $('#step-2-selection-view').hide();
        $('#step-3-review-view').fadeIn(200);
        setStepActive(3);
    }

    // Candidate click on fallback option cards
    $('.option').click(function() {
        var id = $(this).attr('id');
        var name = $(this).data('name') || $(this).find('.party-name').text().trim();
        var logo = $(this).data('logo') || $(this).find('img').attr('src') || '/static/images/logo.png';
        var pos = $(this).data('pos') || '';
        selectCandidate(id, name, logo, pos);
    });

    // Listen for React FlipCard selection custom events
    document.addEventListener('ballotchain:candidate-selected', function(e) {
        if (e.detail) {
            selectCandidate(
                e.detail.candidate_id || e.detail.party_id,
                e.detail.candidate_name || e.detail.name,
                e.detail.image || e.detail.logo,
                e.detail.position_title || ''
            );
        }
    });

    // Step 3: Back to Candidate Selection
    $('#btn-back-to-candidates').click(function() {
        $('#step-3-review-view').hide();
        $('#step-2-selection-view').fadeIn(200);
        setStepActive(2);
    });

    // Step 3: Proceed to Private Key Verification
    $('#btn-proceed-to-key').click(function() {
        $('#step-3-review-view').hide();
        $('#step-4-key-view').fadeIn(200);
        setStepActive(4);
    });

    // Step 4: Back to Review
    $('#btn-back-to-review').click(function() {
        $('#step-4-key-view').hide();
        $('#step-3-review-view').fadeIn(200);
        setStepActive(3);
    });

    // Step 4: Toggle key masking
    var isMasked = false;
    $('#btn-toggle-key-mask').click(function() {
        isMasked = !isMasked;
        if (isMasked) {
            $('#private-key-input').css({'-webkit-text-security': 'disc', 'filter': 'blur(3px)'});
            $(this).text('👁 Unmask / Show Key Content');
        } else {
            $('#private-key-input').css({'-webkit-text-security': 'none', 'filter': 'none'});
            $(this).text('👁 Mask / Hide Key Content');
        }
    });

    // Step 4: Verify Private Key via Server
    $('#btn-verify-private-key').click(function() {
        var pkValue = $('#private-key-input').val().trim();
        if (!pkValue) {
            $('#key-verification-alert')
                .css({'display': 'block', 'background': '#fef2f2', 'color': '#991b1b', 'border': '1px solid #fecaca'})
                .text('Please enter or paste your voting private key.');
            return;
        }

        var $btn = $(this);
        $btn.prop('disabled', true).text('Verifying Key...');

        $.ajax({
            type: 'POST',
            url: '/verify-private-key/',
            data: { 'private-key': pkValue },
            success: function(data) {
                $btn.prop('disabled', false).text('Verify Private Key');
                if (data.success) {
                    isKeyVerified = true;
                    $('#key-verification-alert')
                        .css({'display': 'block', 'background': '#f0fdf4', 'color': '#166534', 'border': '1px solid #bbf7d0'})
                        .text('✓ Private key verified successfully.');

                    setTimeout(function() {
                        $('#step-4-key-view').hide();
                        $('#step-5-commit-view').fadeIn(200);
                        setStepActive(5);
                    }, 400);
                } else {
                    isKeyVerified = false;
                    $('#key-verification-alert')
                        .css({'display': 'block', 'background': '#fef2f2', 'color': '#991b1b', 'border': '1px solid #fecaca'})
                        .text(data.error || 'Invalid private key. Please check the key sent to your email.');
                }
            },
            error: function(xhr) {
                $btn.prop('disabled', false).text('Verify Private Key');
                isKeyVerified = false;
                var err = 'Invalid private key format or key does not match this voter session.';
                if (xhr.responseJSON && xhr.responseJSON.error) {
                    err = xhr.responseJSON.error;
                }
                $('#key-verification-alert')
                    .css({'display': 'block', 'background': '#fef2f2', 'color': '#991b1b', 'border': '1px solid #fecaca'})
                    .text(err);
            }
        });
    });

    // Step 5: Cancel confirmation
    $('#cancel-confirm, #btn-error-back-to-candidates').click(function() {
        $('#step-5-commit-view').hide();
        $('#step-5-error').hide();
        $('#step-5-processing').hide();
        $('#step-5-commit-controls').show();
        $('#step-2-selection-view').fadeIn(200);
        setStepActive(2);
    });

    // Step 5: Retry button in error banner
    $('#btn-retry-commit').click(function() {
        $('#step-5-error').hide();
        $('#final-confirm').click();
    });

    // Step 5: Final Submission (triggered directly or via SlideCommit Island)
    $('#final-confirm').click(function() {
        var privateKey = $('#private-key-input').val().trim();
        var currentElectionId = $('#current-election-id').val();

        if (!selectedPartyID) {
            showAlert('Please select a candidate first.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            return;
        }

        if (!privateKey) {
            showAlert('Private key is required to sign your ballot.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            return;
        }

        // Ensure key was verified
        if (!isKeyVerified) {
            showAlert('Please verify your private key first.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            $('#step-5-commit-view').hide();
            $('#step-4-key-view').fadeIn(200);
            setStepActive(4);
            return;
        }

        // Set UI into submitting/processing state
        $('#step-5-error').hide();
        $('#step-5-commit-controls').hide();
        $('#step-5-processing').fadeIn(150);
        $('#final-confirm').prop('disabled', true);

        var postData = {
            'selected-party-id': selectedPartyID,
            'private-key': privateKey
        };
        if (currentElectionId) {
            postData['election_id'] = currentElectionId;
        }

        $.ajax({
            type: 'POST',
            url: '/create-vote/',
            data: postData,
            success: function(data) {
                $('#step-5-processing').hide();
                $('#final-confirm').prop('disabled', false);

                if (data.success) {
                    // Successful commit - transition to modern BallotChain receipt
                    var blockId = data.block_id;
                    if (blockId) {
                        $('#success-block-badge').text('Mined in Block #' + blockId);
                    } else {
                        $('#success-block-badge').text('Queued for Mining');
                    }
                    $('#success-candidate-text').text(data.candidate_name || selectedPartyName);
                    $('#success-tracker-text').text(data.ballot_tracker || 'N/A');

                    $('#step-5-commit-controls').hide();
                    $('#step-5-candidate-summary').hide();
                    $('#step-5-success').fadeIn(200);

                    // Mark Step 5 pill done
                    $('.flow-steps-tracker .step-pill').removeClass('active');
                    $('#step-commit-pill').addClass('done');

                    var statusText = data.status || 'Your vote has been signed and recorded on the blockchain.';
                    showAlert(statusText, 'rgba(136, 255, 156, 0.3)', 'rgb(0, 128, 0)');
                    document.dispatchEvent(new CustomEvent('ballotchain:vote-success', {
                        detail: { success: true, block_id: data.block_id, tracker: data.ballot_tracker }
                    }));
                } else {
                    // Application-level error returned with 200
                    var errMsg = data.status || data.error || 'Voting error occurred.';
                    $('#step-5-error-text').text(errMsg);
                    $('#step-5-error').fadeIn(150);
                    $('#step-5-commit-controls').show();
                    showAlert(errMsg, 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                    document.dispatchEvent(new CustomEvent('ballotchain:vote-error', {
                        detail: { success: false, error: errMsg }
                    }));
                }
            },
            error: function(xhr, status, error) {
                $('#step-5-processing').hide();
                $('#final-confirm').prop('disabled', false);

                var errDetail = 'Network or server error while submitting vote.';
                if (xhr.responseJSON && (xhr.responseJSON.error || xhr.responseJSON.status)) {
                    errDetail = xhr.responseJSON.error || xhr.responseJSON.status;
                }
                $('#step-5-error-text').text(errDetail);
                $('#step-5-error').fadeIn(150);
                $('#step-5-commit-controls').show();

                showAlert(errDetail, 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                document.dispatchEvent(new CustomEvent('ballotchain:vote-error', {
                    detail: { success: false, error: errDetail }
                }));
            }
        });
    });
});
