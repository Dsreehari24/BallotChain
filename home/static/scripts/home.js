/**
 * BallotChain Voter Portal Authentication Script
 * Updated with enterprise generic terminology and clean notifications.
 */

$(document).ready(function() {
    hide_loading();
    showAlert(
        'Enter your Voter ID Number to authenticate and view eligible elections.',
        'rgba(79, 70, 229, 0.08)', '#4f46e5');
    setTimeout(function() {
        $('.loading-div').css({
            'height': '100vh',
            'top': '0',
        });
    }, 1000);
});

// Voter ID / UID Validation on input
$('#aadhar').on('input', function(event) {
    if ($('#aadhar').val().length > 12) {
        $('#aadhar').val(aadhar);
    }
    if ($.isNumeric($('#aadhar').val())) {
        aadhar = $('#aadhar').val();
    } else {
        if ($('#aadhar').val().length > 0) {
            $('#aadhar').val(aadhar);
        }
    }
});

// Authenticate Voter ID after button click
function submit_aadhar() {
    show_loading('Please wait, authenticating voter credentials...');
    $.ajax({
        type: "POST",
        url: "/authentication/",
        data: {'aadhar_no': $('#aadhar').val()},
        success: function(data) {
            if (data.success) {
                candidate_details_json = data.details;

                showAlert(
                    'Successfully Authenticated. Proceed to voter verification.',
                    'rgba(15, 118, 110, 0.12)', '#0f766e');
                setTimeout(function() {
                    showAlert(
                        'Please verify your registered Email-ID to receive the one-time voting token.',
                        'rgba(79, 70, 229, 0.08)', '#4f46e5', null);
                }, 4000);

                $('.main-content').html(data.html);
                hide_loading();
                showShortDetails();
            } else {
                showAlert(data.error,
                    'rgba(220, 38, 38, 0.12)', '#dc2626', 'vibrate');
                hide_loading();
            }
        }
    });
}

// Show short Details at top right corner after authentication
function showShortDetails() {
    if (candidate_details_json && candidate_details_json.uuid) {
        $('.basic-details').html(candidate_details_json.uuid + ' (' + candidate_details_json.name + ')');
        $('.profile-pic').first().attr('src', candidate_details_json.profile_pic);
        $('.short-details').css('display', 'flex');
    }
}
