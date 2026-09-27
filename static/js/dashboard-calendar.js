/**
 * Dashboard upload-activity calendar — keyboard focus helper for day cells.
 */
(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        var cal = document.getElementById('qaDashboardCalendar');
        if (!cal) {
            return;
        }
        cal.querySelectorAll('.nx-cal-day.has-uploads').forEach(function (cell) {
            cell.setAttribute('role', 'button');
        });
    });
})();
