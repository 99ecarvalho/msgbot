/*
 * Copyright (c) 2026 Eduardo Correia <ecorreia@apliant.com.br>
 *
 * This file is part of MsgBot. It is free software, licensed under the GNU
 * Lesser General Public License v3.0 or later. See COPYING.LESSER and
 * COPYING for details.
 *
 * SPDX-License-Identifier: LGPL-3.0-or-later
 */

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
