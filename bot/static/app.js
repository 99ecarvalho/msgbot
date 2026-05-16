/* MsgBot — minimal JS helpers. HTMX handles most dynamic behavior. */

// Auto-hide notice elements after 3 seconds
document.addEventListener('htmx:afterSwap', function(event) {
    const notices = event.detail.target.querySelectorAll('.notice');
    notices.forEach(function(notice) {
        setTimeout(function() {
            notice.style.opacity = '0';
            setTimeout(function() { notice.remove(); }, 300);
        }, 3000);
    });
});
