/**
 * BallotChain Modern Shell & Core Interaction Scripts
 * Backward-compatible with all existing voting, ledger, and candidate scripts.
 */

var aadhar = "";
var candidate_details_json;
var parties_list_json;

/**
 * Global Alert Notification
 * Renders modern toast or status message within the topbar/status container.
 */
function showAlert(inner_html, bg_color, color, animation = null) {
    var statusBox = $('.status-box');
    if (statusBox.length) {
        var alertEl = $('<div class="status" style="margin-bottom: 6px; color: ' + color + '; background: ' + bg_color + '; border-radius: 9999px; padding: 4px 12px; font-size: 12px; font-weight: 500;">' + inner_html + '</div>');
        statusBox.prepend(alertEl);

        setTimeout(function() {
            alertEl.fadeOut(300, function() {
                alertEl.remove();
            });
        }, 3500);
    }
}

/**
 * Show Modern Full-Screen Loading Overlay
 */
function show_loading(message = 'Please wait...') {
    $('.loading-message').html(message);
    $('.loading-div').css({'display': 'flex', 'opacity': '1'});
}

/**
 * Hide Loading Overlay and Reveal Main Content
 */
function hide_loading() {
    $('.loading-div').animate(
        {'opacity': '0'},
        {
            duration: 300,
            complete: function() {
                $('.loading-div').hide();
                $('.app-content, .main-content').css('display', 'block');
            }
        }
    );
}

/**
 * Hide Loading Overlay Without Altering Content Display
 */
function hide_loading_without_reload() {
    $('.loading-div').animate(
        {'opacity': '0'},
        {
            duration: 300,
            complete: function() {
                $('.loading-div').hide();
            }
        }
    );
}

/**
 * Mobile Sidebar Drawer Controls
 */
function show_drawer() {
    $('#app-sidebar').addClass('sidebar-open');
    $('#sidebar-backdrop').addClass('active');
    $('#sidebar-toggle-btn').attr('aria-expanded', 'true');
}

function hide_drawer() {
    $('#app-sidebar').removeClass('sidebar-open');
    $('#sidebar-backdrop').removeClass('active');
    $('#sidebar-toggle-btn').attr('aria-expanded', 'false');
}

$(document).ready(function() {
    // 1. Mobile Sidebar Toggle & Backdrop
    $('#sidebar-toggle-btn').on('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        show_drawer();
    });

    $('#sidebar-close-btn, #sidebar-backdrop').on('click', function() {
        hide_drawer();
    });

    // 2. TopBar Neutral User Profile Dropdown
    $('#profile-menu-toggle').on('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        var menu = $('#profile-dropdown-menu');
        var isHidden = menu.prop('hidden');
        menu.prop('hidden', !isHidden);
        $(this).attr('aria-expanded', isHidden ? 'true' : 'false');
    });

    // Dismiss Profile Dropdown on Click Outside
    $(document).on('click', function(e) {
        if (!$(e.target).closest('#topbar-profile-container').length) {
            $('#profile-dropdown-menu').prop('hidden', true);
            $('#profile-menu-toggle').attr('aria-expanded', 'false');
        }
    });

    // 3. Escape Key Handler (Dismiss Drawer & Profile Dropdown)
    $(document).on('keydown', function(e) {
        if (e.key === 'Escape' || e.keyCode === 27) {
            hide_drawer();
            $('#profile-dropdown-menu').prop('hidden', true);
            $('#profile-menu-toggle').attr('aria-expanded', 'false');
        }
    });

    // Legacy drawer compatibility hooks
    $('.logo').on('click', function() {
        if (window.innerWidth <= 1024) {
            show_drawer();
        }
    });
});
