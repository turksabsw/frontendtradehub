frappe.ui.form.on('Mock Generation Request', {
    refresh: function(frm) {
        // Clear all existing buttons first
        frm.clear_custom_buttons();
        
        // Start Generation butonu (sadece Draft durumunda)
        if (frm.doc.status === 'Draft' && !frm.is_new()) {
            frm.add_custom_button(__('Start Generation'), function() {
                frappe.confirm(
                    __('Are you sure you want to start mock data generation?'),
                    function() {
                        frm.call({
                            method: 'start_generation',
                            doc: frm.doc,
                            freeze: true,
                            freeze_message: __('Queueing generation...'),
                            callback: function(r) {
                                if (r.message && r.message.success) {
                                    frappe.show_alert({
                                        message: __('Generation queued successfully!'),
                                        indicator: 'green'
                                    });
                                    frm.reload_doc();
                                }
                            }
                        });
                    }
                );
            }).addClass('btn-primary');
        }

        // Cancel butonu (Queued veya Processing durumunda)
        if (frm.doc.status === 'Queued' || frm.doc.status === 'Processing') {
            frm.add_custom_button(__('Cancel Generation'), function() {
                frappe.confirm(
                    __('Are you sure you want to cancel this generation request?'),
                    function() {
                        frm.call({
                            method: 'cancel_generation',
                            doc: frm.doc,
                            freeze: true,
                            callback: function(r) {
                                if (r.message && r.message.success) {
                                    frappe.show_alert({
                                        message: __('Generation cancelled successfully'),
                                        indicator: 'orange'
                                    });
                                    frm.reload_doc();
                                } else {
                                    frappe.show_alert({
                                        message: __('Failed to cancel generation'),
                                        indicator: 'red'
                                    });
                                }
                            },
                            error: function(r) {
                                frappe.show_alert({
                                    message: __('Error cancelling generation: ' + (r.message || 'Unknown error')),
                                    indicator: 'red'
                                });
                            }
                        });
                    }
                );
            }).addClass('btn-danger');
        }

        // Retry butonu (sadece Failed durumunda)
        if (frm.doc.status === 'Failed') {
            frm.add_custom_button(__('Retry'), function() {
                frm.call({
                    method: 'retry_generation',
                    doc: frm.doc,
                    freeze: true,
                    callback: function(r) {
                        if (r.message && r.message.success) {
                            frm.reload_doc();
                        }
                    }
                });
            }, null).addClass('btn-warning');
        }

        // İlerleme çubuğu (Processing durumunda)
        if (frm.doc.status === 'Processing' || frm.doc.status === 'Queued') {
            // Clear any existing progress
            if (frm.dashboard && frm.dashboard.progress_area) {
                frm.dashboard.progress_area.empty();
            }
            
            var progress_percent = parseFloat(frm.doc.progress_percent) || 0;
            var records_created = frm.doc.records_created || 0;
            var records_failed = frm.doc.records_failed || 0;
            var current_batch = frm.doc.current_batch || 0;
            var total_batches = frm.doc.total_batches || 0;
            
            frm.dashboard.add_progress(__('Generation Progress'), [
                {
                    title: records_created + ' created, ' + records_failed + ' failed' + 
                           (total_batches > 0 ? ' (Batch ' + current_batch + '/' + total_batches + ')' : ''),
                    width: progress_percent + '%',
                    progress_class: progress_percent >= 100 ? 'progress-bar-success' : 'progress-bar-info'
                }
            ]);

            // Real-time progress updates via socket
            if (!frm._progress_listener) {
                frm._progress_listener = frappe.realtime.on('mock_generation_progress', function(data) {
                    if (data.request_name === frm.doc.name) {
                        frm.doc.progress_percent = data.progress_percent || 0;
                        frm.doc.records_created = data.records_created || 0;
                        frm.doc.records_failed = data.records_failed || 0;
                        frm.doc.current_batch = data.current_batch || 0;
                        frm.doc.total_batches = data.total_batches || 0;
                        frm.refresh();
                    }
                });
                
                frm._completion_listener = frappe.realtime.on('mock_generation_complete', function(data) {
                    if (data.request_name === frm.doc.name) {
                        frm.reload_doc();
                    }
                });
            }

            // Her 2 saniyede bir yenile (fallback if realtime fails) - log'ları görmek için
            if (!frm._auto_refresh) {
                frm._auto_refresh = setInterval(function() {
                    // Force reload to see logs
                    frm.reload_doc();
                }, 2000);
            }
            
            // Also refresh when form becomes visible (user switches tabs)
            if (!frm._visibility_refresh) {
                $(document).on('visibilitychange', function() {
                    if (!document.hidden && (frm.doc.status === 'Processing' || frm.doc.status === 'Queued')) {
                        frm.reload_doc();
                    }
                });
                frm._visibility_refresh = true;
            }
        } else {
            // Clean up listeners when not processing
            if (frm._progress_listener) {
                frappe.realtime.off('mock_generation_progress', frm._progress_listener);
                frm._progress_listener = null;
            }
            if (frm._completion_listener) {
                frappe.realtime.off('mock_generation_complete', frm._completion_listener);
                frm._completion_listener = null;
            }
            if (frm._auto_refresh) {
                clearInterval(frm._auto_refresh);
                frm._auto_refresh = null;
            }
        }

        // Durum renkleri
        frm.page.set_indicator(
            frm.doc.status === 'Completed' ? 'green' :
            frm.doc.status === 'Processing' ? 'blue' :
            frm.doc.status === 'Queued' ? 'orange' :
            frm.doc.status === 'Failed' ? 'red' :
            frm.doc.status === 'Cancelled' ? 'grey' : ''
        );
    }
});
