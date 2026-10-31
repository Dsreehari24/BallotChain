var emailmsg1 = 'Please verify your institutional email address to proceed.';
var emailmsg2 = 'Click "Send OTP" to receive your one-time verification code.';
var valid_email_pattern = /^[^ ]+@[^ ]+\.[a-z]{2,3}$/;

$(document).ready(function(){
    
    $('.email-alert-msg').addClass('email-alert-msg-slide-fade-in');
    set_email_alert_msg();

    function set_email_alert_msg(){
        if( valid_email_pattern.test($('#email-input').val()) ){
            $('.email-alert-msg').html(emailmsg2);
        }
        else{
            $('.email-alert-msg').html(emailmsg1);
        }
    }

    // Send OTP to email address on button click and display centered modal
    $('#send-otp').click(function(){
        if( valid_email_pattern.test($('#email-input').val()) ){
            show_loading('Sending one-time verification code to your email...');

            $.ajax({
                type: 'POST',
                url: '/send-otp/',
                data: {'email-id': $('#email-input').val()},
                success: function(data){
                    setTimeout(function(){
                        hide_loading_without_reload();
                    }, 800);

                    if(data.success){
                        $('#otp-verfication-email').html($('#email-input').val());
                        document.dispatchEvent(new CustomEvent('ballotchain:otp-reset'));
                        $('.otp-verification').css('display', 'flex');
                        $('.otp-div').show();
                        showAlert('OTP code sent to ' + $('#email-input').val(), 'rgba(136, 255, 156, 0.3)', 'rgb(0, 128, 0)');
                    } else {
                        showAlert(data.error || 'Failed to send OTP code.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                    }
                },
                error: function(xhr){
                    hide_loading_without_reload();
                    showAlert('Failed to connect to authentication service.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                }
            });
        } else {
            $('.email-alert-msg').removeClass('email-alert-msg-slide-fade-in');
            $('.email-alert-msg').addClass('boom');
            setTimeout(function(){
                $('.email-alert-msg').removeClass('boom');
            }, 1000);
        }
    });

    // Verify OTP
    $('#verify').click(function(){
        show_loading('Verifying your identity code...');

        $.ajax({
            type: 'POST',
            url: '/verify-otp/',
            data: {'otp-input': $('#otp-input').val()},
            success: function(data){
                setTimeout(function(){
                    hide_loading_without_reload();
                }, 1000);

                if(data.success){
                    $('.otp-verification').hide();

                    $('#send-otp').hide();
                    $('#verified-badge').css('display', 'inline');
                    $('#vote-now').removeClass('disabled');
                    $('.email-alert-msg').hide();
                    
                    showAlert('Identity verified successfully.', 'rgba(136, 255, 156, 0.3)', 'rgb(0, 128, 0)');
                } else {
                    document.dispatchEvent(new CustomEvent('ballotchain:otp-error'));
                    showAlert('Invalid or expired OTP code.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
                }
            },
            error: function(xhr){
                hide_loading_without_reload();
                showAlert('Error verifying OTP code.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            }
        });
    });

    // Cancel OTP verification and hide verification modal
    $('#cancel-otp').click(function(){
        $('.otp-verification').hide();
    });

    // Proceed to ballot selection
    $('#vote-now').click(function(event){
        show_loading('Initializing secure ballot session...');

        var currentElectionId = $('#current-election-id').val();
        var url = '/get-parties/';
        if (currentElectionId) {
            url += '?election_id=' + encodeURIComponent(currentElectionId);
        }

        $.ajax({
            type: 'GET',
            url: url,
            success: function(data){
                parties_list_json = data.parties;
                $('.main-content').html(data.html);
                hide_loading();
                showAlert('Make your choice. Select your preferred candidate.', 'rgba(201, 136, 255, 0.3)', 'rgb(102, 0, 128)');
            },
            error: function(){
                hide_loading();
                showAlert('Failed to load election candidates.', 'rgba(255, 82, 82, 0.3)', 'rgb(122, 0, 0)', 'vibrate');
            }
        });
    });

});
