/**
 * QAChat -- one conversation: its messages, and the composer underneath.
 *
 * Used by the Messages page and by the floating Messages dock, so the two
 * cannot drift apart: the same bubbles, replies, reactions, pictures, files,
 * voice messages, typing indicator, read receipts and send/retry behaviour.
 *
 * Reliability, in short:
 *
 * - The server is the record. A conversation is loaded once, then the page's
 *   poller passes on every sync answer (applySync), which carries everything
 *   that changed after this conversation's change number (`seq`): new
 *   messages, deletions, reactions. Each change arrives once and in order, and
 *   an older copy of a message never overwrites a newer one.
 * - Every send has a client id made here. It is shown at once as "Sending",
 *   and the same id is sent on every retry, so a send whose answer was lost
 *   does not post twice. A text message waiting to be sent is kept in this
 *   browser, so it survives a reload and goes when the connection is back.
 * - Failures say what happened (window.qaRequestError) and offer Retry when a
 *   retry can help.
 *
 * Everything the server sends is text. It is escaped before it is put into
 * the page; links are made clickable only after escaping.
 */
(function () {
    'use strict';

    var REACTIONS = ['👍', '❤️', '😂', '😮', '😢', '🙏', '🎉', '✅'];
    var EMOJI = ['😀', '😃', '😄', '😁', '😊', '🙂', '😉', '😍', '😘', '🤗', '🤔', '😐',
                 '😅', '😂', '🤣', '😢', '😭', '😮', '😴', '😎', '🥳', '😇', '🙃', '😬',
                 '👍', '👎', '👏', '🙌', '🙏', '👌', '✌️', '🤝', '💪', '👋', '✅', '❌',
                 '❤️', '💙', '💚', '🔥', '⭐', '🎉', '📄', '📎', '📌', '📅', '⏰', '💡'];
    var GROUP_GAP_MS = 5 * 60 * 1000;
    var TIME_GAP_MS = 30 * 60 * 1000;
    var RECORD_MAX_S = 300;
    var OUTBOX_KEY = 'qaChatOutbox:';

    /* ------------------------------------------------------------ helpers */

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    // Links in escaped text. `&amp;` and friends stay inside the URL; quotes
    // cannot appear (they were escaped), so the attribute cannot be broken.
    // A URL ends at whitespace, at a quote or angle bracket (which arrive here
    // already escaped as entities), and before trailing punctuation.
    function linkify(escaped) {
        return escaped.replace(/\bhttps?:\/\/[^\s<]+/g, function (match) {
            var url = match;
            var stop = url.search(/&quot;|&#39;|&lt;|&gt;/);
            if (stop >= 0) { url = url.slice(0, stop); }
            url = url.replace(/[.,;:!?)\]]+$/, '');
            if (!/^https?:\/\/[^\/]/.test(url)) { return match; }
            return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + url + '</a>' + match.slice(url.length);
        });
    }
    function csrf() {
        var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        if (m) { return decodeURIComponent(m[1]); }
        var input = document.querySelector('[name=csrfmiddlewaretoken]');
        return input ? input.value : '';
    }
    function uid() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') { return window.crypto.randomUUID(); }
        return 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
    }
    function fmtSize(n) {
        n = Number(n) || 0;
        if (n < 1024) { return n + ' B'; }
        if (n < 1024 * 1024) { return Math.round(n / 1024) + ' KB'; }
        return (n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0) + ' MB';
    }
    function fmtDuration(s) {
        s = Math.max(0, Math.round(Number(s) || 0));
        return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2);
    }
    function sameDay(a, b) {
        return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }
    function dayLabel(d) {
        var now = new Date();
        var yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
        if (sameDay(d, now)) { return 'Today'; }
        if (sameDay(d, yesterday)) { return 'Yesterday'; }
        var opts = { weekday: 'short', month: 'short', day: 'numeric' };
        if (d.getFullYear() !== now.getFullYear()) { opts = { month: 'short', day: 'numeric', year: 'numeric' }; }
        return d.toLocaleDateString(undefined, opts);
    }
    function timeLabel(d) {
        return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    }
    function fullStamp(d) {
        return d.toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric',
                                             year: 'numeric', hour: 'numeric', minute: '2-digit' });
    }
    function extOf(name) {
        var m = /\.([a-z0-9]{1,8})$/i.exec(name || '');
        return m ? '.' + m[1].toLowerCase() : '';
    }
    function fileIcon(name) {
        var ext = extOf(name);
        return { '.pdf': 'bi-file-earmark-pdf', '.docx': 'bi-file-earmark-word', '.xlsx': 'bi-file-earmark-excel',
                 '.csv': 'bi-file-earmark-spreadsheet', '.pptx': 'bi-file-earmark-ppt',
                 '.txt': 'bi-file-earmark-text' }[ext] || 'bi-file-earmark';
    }
    function hash(s) {
        var h = 5381;
        for (var i = 0; i < s.length; i++) { h = ((h << 5) + h + s.charCodeAt(i)) | 0; }
        return h;
    }
    // Only emoji (one to three of them): shown larger, without a bubble.
    var EMOJI_ONLY = /^(?:\p{Extended_Pictographic}(?:️|‍\p{Extended_Pictographic}|[\u{1F3FB}-\u{1F3FF}])*\s*){1,3}$/u;
    function isJumbo(text) {
        try { return !!text && text.length <= 24 && EMOJI_ONLY.test(text.trim()); } catch (e) { return false; }
    }
    function toast(message, variant) {
        if (typeof window.qaToast === 'function') { window.qaToast(message, variant || 'error'); }
    }
    function describeFailure(status, data, action) {
        if (typeof window.qaRequestError === 'function') { return window.qaRequestError(status, data || {}, action); }
        return (data && data.error) || 'That did not work. Try again.';
    }

    /* --------------------------------------------- one shared voice player */

    var player = {
        audio: null, key: null,
        el: function () {
            if (!this.audio) {
                this.audio = new Audio();
                this.audio.preload = 'metadata';
                var self = this;
                this.audio.addEventListener('timeupdate', function () { self.paint(); });
                this.audio.addEventListener('ended', function () { self.key = null; self.paint(true); });
                this.audio.addEventListener('pause', function () { self.paint(); });
                this.audio.addEventListener('play', function () { self.paint(); });
                this.audio.addEventListener('error', function () {
                    if (self.key) { toast('That voice message could not be played.'); }
                    self.key = null; self.paint(true);
                });
            }
            return this.audio;
        },
        toggle: function (key, src, duration) {
            var a = this.el();
            if (this.key === key) {
                if (a.paused) { a.play().catch(function () {}); } else { a.pause(); }
                return;
            }
            this.key = key;
            this.duration = Number(duration) || 0;
            a.src = src;
            a.play().catch(function () {});
            this.paint(true);
        },
        seek: function (key, fraction) {
            if (this.key !== key || !this.audio) { return; }
            var total = isFinite(this.audio.duration) && this.audio.duration ? this.audio.duration : this.duration;
            if (total) { this.audio.currentTime = Math.max(0, Math.min(total, total * fraction)); }
        },
        // Repaint every player on screen, so a conversation redrawn while a
        // voice message plays shows it still playing.
        paint: function (all) {
            var a = this.audio, key = this.key;
            document.querySelectorAll('.qc-voice').forEach(function (node) {
                var mine = key && node.getAttribute('data-voice-key') === key;
                if (!mine && !all && !node.classList.contains('is-playing')) { return; }
                var playing = mine && a && !a.paused;
                node.classList.toggle('is-playing', !!playing);
                node.classList.toggle('is-active', !!mine);
                var icon = node.querySelector('.qc-voice-play i');
                if (icon) { icon.className = 'bi ' + (playing ? 'bi-pause-fill' : 'bi-play-fill'); }
                var btn = node.querySelector('.qc-voice-play');
                if (btn) { btn.setAttribute('aria-label', playing ? 'Pause voice message' : 'Play voice message'); }
                var total = Number(node.getAttribute('data-duration')) || 0;
                var at = mine && a ? a.currentTime : 0;
                if (mine && a && isFinite(a.duration) && a.duration) { total = a.duration; }
                var fraction = total ? Math.min(1, at / total) : 0;
                node.style.setProperty('--progress', (fraction * 100).toFixed(1) + '%');
                var time = node.querySelector('.qc-voice-time');
                if (time) { time.textContent = mine && at ? fmtDuration(at) + ' / ' + fmtDuration(total) : fmtDuration(total); }
            });
        }
    };

    /* ------------------------------------------------- one shared lightbox */

    var lightbox = {
        root: null, items: [], index: 0, returnFocus: null,
        build: function () {
            if (this.root) { return; }
            var root = document.createElement('div');
            root.className = 'qc-lightbox';
            root.hidden = true;
            root.setAttribute('role', 'dialog');
            root.setAttribute('aria-modal', 'true');
            root.setAttribute('aria-label', 'Picture');
            root.innerHTML =
                '<div class="qc-lightbox-bar">' +
                  '<span class="qc-lightbox-name"></span>' +
                  '<span class="qc-lightbox-count"></span>' +
                  '<a class="qc-lightbox-btn" data-lb="download" href="#" aria-label="Download"><i class="bi bi-download"></i></a>' +
                  '<button type="button" class="qc-lightbox-btn" data-lb="close" aria-label="Close"><i class="bi bi-x-lg"></i></button>' +
                '</div>' +
                '<button type="button" class="qc-lightbox-nav is-prev" data-lb="prev" aria-label="Previous picture"><i class="bi bi-chevron-left"></i></button>' +
                '<img class="qc-lightbox-img" alt="">' +
                '<button type="button" class="qc-lightbox-nav is-next" data-lb="next" aria-label="Next picture"><i class="bi bi-chevron-right"></i></button>';
            document.body.appendChild(root);
            var self = this;
            root.addEventListener('click', function (e) {
                var act = e.target.closest('[data-lb]');
                var what = act && act.getAttribute('data-lb');
                if (what === 'close' || e.target === root) { self.close(); }
                else if (what === 'prev') { self.show(self.index - 1); }
                else if (what === 'next') { self.show(self.index + 1); }
            });
            document.addEventListener('keydown', function (e) {
                if (self.root.hidden) { return; }
                if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); self.close(); }
                if (e.key === 'ArrowLeft') { self.show(self.index - 1); }
                if (e.key === 'ArrowRight') { self.show(self.index + 1); }
            }, true);
            this.root = root;
        },
        open: function (items, index) {
            this.build();
            this.items = items;
            this.returnFocus = document.activeElement;
            this.root.hidden = false;
            this.show(index);
            this.root.querySelector('[data-lb="close"]').focus();
        },
        show: function (i) {
            if (!this.items.length) { return; }
            this.index = (i + this.items.length) % this.items.length;
            var it = this.items[this.index];
            var img = this.root.querySelector('.qc-lightbox-img');
            img.src = it.url;
            img.alt = it.name || '';
            this.root.querySelector('.qc-lightbox-name').textContent = it.name || '';
            this.root.querySelector('.qc-lightbox-count').textContent =
                this.items.length > 1 ? (this.index + 1) + ' / ' + this.items.length : '';
            var dl = this.root.querySelector('[data-lb="download"]');
            dl.href = it.download || it.url;
            dl.hidden = !it.download;
            this.root.querySelectorAll('.qc-lightbox-nav').forEach(function (b) { b.hidden = this.items.length < 2; }, this);
        },
        close: function () {
            this.root.hidden = true;
            this.root.querySelector('.qc-lightbox-img').removeAttribute('src');
            if (this.returnFocus && document.contains(this.returnFocus)) { this.returnFocus.focus({ preventScroll: true }); }
        }
    };

    /* ------------------------------------------------------------ outbox */

    function outboxLoad(viewer) {
        try { return JSON.parse(localStorage.getItem(OUTBOX_KEY + viewer) || '{}') || {}; } catch (e) { return {}; }
    }
    function outboxSave(viewer, all) {
        try { localStorage.setItem(OUTBOX_KEY + viewer, JSON.stringify(all)); } catch (e) { /* storage blocked: kept in memory only */ }
    }

    /* ================================================================== */

    function Chat(opts) {
        this.opts = opts;
        this.viewerId = Number(opts.viewerId) || 0;
        this.root = opts.root;
        this.threadId = null;
        this.reset();
        this.build();
    }

    Chat.prototype.reset = function () {
        // Anything still sending belongs to the conversation being left; it
        // finishes in the background and reports a failure by itself.
        if (this.pending) {
            for (var cid in this.pending) { this.pending[cid].detached = true; }
        }
        this.items = {};          // server messages by id
        this.pending = {};        // unsent messages by client id
        this.seq = 0;
        this.readUpto = 0;
        this.typingNames = [];
        this.firstUnread = null;
        this.replyTo = null;
        this.tray = [];
        this.loaded = false;
        this.loadToken = (this.loadToken || 0) + 1;
        this.unseen = 0;
    };

    /* --------------------------------------------------------- the DOM */

    Chat.prototype.build = function () {
        var o = this.opts;
        var accept = (o.accept || '').trim();
        this.root.classList.add('qc');
        if (o.compact) { this.root.classList.add('is-compact'); }
        this.root.innerHTML =
            '<div class="qc-scroll" tabindex="-1">' +
              '<div class="qc-list" role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation"></div>' +
            '</div>' +
            '<button type="button" class="qc-jump" hidden><i class="bi bi-arrow-down"></i><span>New messages</span></button>' +
            '<div class="qc-typing" hidden aria-live="polite"><span class="qc-dots" aria-hidden="true"><i></i><i></i><i></i></span><span class="qc-typing-text"></span></div>' +
            '<div class="qc-composer">' +
              '<div class="qc-reply" hidden>' +
                '<i class="bi bi-reply-fill" aria-hidden="true"></i>' +
                '<div class="qc-reply-text"><strong></strong><span></span></div>' +
                '<button type="button" class="qc-icon-btn qc-reply-cancel" aria-label="Cancel reply"><i class="bi bi-x-lg"></i></button>' +
              '</div>' +
              '<div class="qc-tray" hidden></div>' +
              '<div class="qc-rec" hidden role="status">' +
                '<button type="button" class="qc-icon-btn qc-rec-cancel" aria-label="Discard the recording"><i class="bi bi-trash3"></i></button>' +
                '<span class="qc-rec-dot" aria-hidden="true"></span>' +
                '<span class="qc-rec-time">0:00</span>' +
                '<span class="qc-rec-level" aria-hidden="true"></span>' +
                '<span class="qc-rec-hint">Recording…</span>' +
              '</div>' +
              '<div class="qc-row">' +
                '<div class="qc-field">' +
                  '<textarea class="qc-input" rows="1" placeholder="Type a message…" aria-label="Message"></textarea>' +
                  '<button type="button" class="qc-icon-btn qc-emoji-btn" aria-label="Insert emoji" aria-expanded="false"><i class="bi bi-emoji-smile"></i></button>' +
                '</div>' +
                '<button type="button" class="qc-icon-btn qc-attach" aria-label="Attach files" title="Attach pictures or files"><i class="bi bi-paperclip"></i></button>' +
                '<input type="file" class="qc-file" multiple hidden' + (accept ? ' accept="' + esc(accept) + '"' : '') + '>' +
                '<button type="button" class="qc-send is-mic" aria-label="Record a voice message" title="Record a voice message"><i class="bi bi-mic-fill"></i></button>' +
              '</div>' +
              '<div class="qc-emoji-pop" hidden role="dialog" aria-label="Emoji"></div>' +
            '</div>' +
            '<div class="qc-pop" hidden></div>' +
            '<div class="qc-drop" hidden><i class="bi bi-cloud-arrow-up"></i><span>Drop to attach</span></div>';

        var q = this.root.querySelector.bind(this.root);
        this.scrollEl = q('.qc-scroll');
        this.listEl = q('.qc-list');
        this.jumpEl = q('.qc-jump');
        this.typingEl = q('.qc-typing');
        this.inputEl = q('.qc-input');
        this.sendEl = q('.qc-send');
        this.fileEl = q('.qc-file');
        this.trayEl = q('.qc-tray');
        this.replyEl = q('.qc-reply');
        this.recEl = q('.qc-rec');
        this.emojiPop = q('.qc-emoji-pop');
        this.popEl = q('.qc-pop');
        this.dropEl = q('.qc-drop');

        this.emojiPop.innerHTML = EMOJI.map(function (e) {
            return '<button type="button" class="qc-emoji" aria-label="' + esc(e) + '">' + e + '</button>';
        }).join('');

        this.bind();
        this.renderComposer();
        this.showPlaceholder('Choose a conversation');
    };

    Chat.prototype.bind = function () {
        var self = this;

        this.inputEl.addEventListener('input', function () {
            self.autosize();
            self.renderComposer();
            self.noteTyping();
        });
        this.inputEl.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
                e.preventDefault();
                self.submit();
            } else if (e.key === 'Escape') {
                if (!self.emojiPop.hidden) { self.toggleEmoji(false); e.stopPropagation(); }
                else if (self.replyTo) { self.setReply(null); e.stopPropagation(); }
            }
        });
        this.inputEl.addEventListener('blur', function () { self.stopTyping(); });
        this.inputEl.addEventListener('paste', function (e) {
            var files = Array.prototype.slice.call((e.clipboardData && e.clipboardData.files) || []);
            if (files.length) { e.preventDefault(); self.addFiles(files); }
        });

        this.sendEl.addEventListener('click', function () {
            if (self.recorder) { self.stopRecording(true); return; }
            if (self.sendEl.classList.contains('is-mic')) { self.startRecording(); return; }
            self.submit();
        });
        this.root.querySelector('.qc-attach').addEventListener('click', function () { self.fileEl.click(); });
        this.fileEl.addEventListener('change', function () {
            self.addFiles(Array.prototype.slice.call(self.fileEl.files || []));
            self.fileEl.value = '';
        });
        this.root.querySelector('.qc-emoji-btn').addEventListener('click', function () { self.toggleEmoji(); });
        this.emojiPop.addEventListener('click', function (e) {
            var b = e.target.closest('.qc-emoji');
            if (b) { self.insertText(b.textContent); }
        });
        this.root.querySelector('.qc-reply-cancel').addEventListener('click', function () { self.setReply(null); self.inputEl.focus(); });
        this.root.querySelector('.qc-rec-cancel').addEventListener('click', function () { self.stopRecording(false); });
        this.trayEl.addEventListener('click', function (e) {
            var rm = e.target.closest('[data-tray-remove]');
            if (!rm) { return; }
            var id = rm.getAttribute('data-tray-remove');
            self.tray = self.tray.filter(function (t) {
                if (t.id === id && t.url) { URL.revokeObjectURL(t.url); }
                return t.id !== id;
            });
            self.renderComposer();
            self.inputEl.focus();
        });

        this.jumpEl.addEventListener('click', function () { self.scrollToBottom(true); });
        this.scrollEl.addEventListener('scroll', function () {
            if (self.atBottom()) { self.unseen = 0; self.jumpEl.hidden = true; }
            self.closePop();
        }, { passive: true });

        this.listEl.addEventListener('click', function (e) { self.onListClick(e); });
        this.popEl.addEventListener('click', function (e) { self.onPopClick(e); });
        document.addEventListener('click', function (e) {
            // A click that replaced its own target (Delete -> "Delete for
            // everyone?") is not a click outside the menu.
            if (!e.target.isConnected) { return; }
            if (!self.popEl.hidden && !self.popEl.contains(e.target) && !e.target.closest('[data-act]')) { self.closePop(); }
            if (!self.emojiPop.hidden && !self.emojiPop.contains(e.target) && !e.target.closest('.qc-emoji-btn')) { self.toggleEmoji(false); }
        });
        this.root.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !self.popEl.hidden) { e.stopPropagation(); self.closePop(); }
        });

        // Drag files onto the conversation to attach them.
        var depth = 0;
        this.root.addEventListener('dragenter', function (e) {
            if (!self.threadId || !e.dataTransfer || Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') < 0) { return; }
            depth += 1;
            self.dropEl.hidden = false;
        });
        this.root.addEventListener('dragover', function (e) {
            if (!self.dropEl.hidden) { e.preventDefault(); }
        });
        this.root.addEventListener('dragleave', function () {
            depth = Math.max(0, depth - 1);
            if (!depth) { self.dropEl.hidden = true; }
        });
        this.root.addEventListener('drop', function (e) {
            if (self.dropEl.hidden) { return; }
            e.preventDefault();
            depth = 0;
            self.dropEl.hidden = true;
            self.addFiles(Array.prototype.slice.call(e.dataTransfer.files || []));
        });

        window.addEventListener('online', function () { self.flushQueued(); });
        document.addEventListener('qa:reconnected', function () { self.flushQueued(); });
    };

    /* ------------------------------------------------------ open / close */

    Chat.prototype.open = function (threadId) {
        var self = this;
        this.stopTyping();
        if (this.recorder) { this.stopRecording(false); }
        this.clearTray();
        this.threadId = Number(threadId);
        this.reset();
        this.setReply(null);
        this.renderComposer();   // the buttons depend on there being a conversation
        this.listEl.innerHTML = '<div class="qc-loading"><span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Loading conversation…</div>';
        var token = this.loadToken;
        return fetch(this.url('thread'), {
            credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (r) {
            if (window.qaActivity && window.qaActivity.expired(r)) { return null; }
            if (r.status === 404) { throw Object.assign(new Error('gone'), { status: 404 }); }
            if (!r.ok) { throw Object.assign(new Error('load'), { status: r.status }); }
            return r.json();
        }).then(function (d) {
            if (!d || token !== self.loadToken) { return null; }
            (d.messages || []).forEach(function (m) { self.upsert(m); });
            self.seq = Number(d.seq) || 0;
            self.firstUnread = d.first_unread || null;
            (d.messages || []).forEach(function (m) {
                if (self.isMine(m) && m.read && m.id > self.readUpto) { self.readUpto = m.id; }
            });
            self.typingNames = d.typing || [];
            self.loaded = true;
            self.restoreOutbox();
            self.render({ initial: true });
            self.renderTyping();
            if (!self.opts.compact || document.activeElement === document.body) { self.inputEl.focus({ preventScroll: true }); }
            return d.thread;
        }).catch(function (err) {
            if (token !== self.loadToken) { return null; }
            if (err && err.status === 404) {
                self.showPlaceholder('This conversation is no longer available.');
                if (self.opts.onGone) { self.opts.onGone(); }
                return null;
            }
            self.listEl.innerHTML = '<div class="qc-empty"><i class="bi bi-wifi-off"></i><p>' +
                esc(describeFailure(err && err.status || 0, {}, 'load')) + '</p>' +
                '<button type="button" class="qc-btn" data-act="reopen">Try again</button></div>';
            return null;
        });
    };

    Chat.prototype.close = function () {
        this.stopTyping();
        if (this.recorder) { this.stopRecording(false); }
        this.clearTray();
        this.threadId = null;
        this.reset();
        this.closePop();
        this.toggleEmoji(false);
        this.renderComposer();
        this.showPlaceholder('Choose a conversation');
    };

    Chat.prototype.showPlaceholder = function (text) {
        this.listEl.innerHTML = '<div class="qc-empty"><i class="bi bi-chat-dots"></i><p>' + esc(text) + '</p></div>';
        this.typingEl.hidden = true;
        this.jumpEl.hidden = true;
    };

    Chat.prototype.url = function (name, messageId) {
        var t = this.opts.urls[name];
        if (name === 'react' || name === 'del') {
            return t.replace(/\/threads\/0\//, '/threads/' + this.threadId + '/').replace(/\/messages\/0\//, '/messages/' + messageId + '/');
        }
        return t.replace(/\/0\//, '/' + this.threadId + '/');
    };

    /* ------------------------------------------------------------- state */

    Chat.prototype.isMine = function (m) {
        if (!m) { return false; }
        if (m.viewer_id != null && this.viewerId && m.viewer_id !== this.viewerId) { return false; }
        if (m.sender_id != null && this.viewerId) { return m.sender_id === this.viewerId; }
        return !!m.mine;
    };

    // Newer wins: a sync answer that left the server before a reaction was
    // made must not undo the reaction when it arrives after it.
    Chat.prototype.upsert = function (m) {
        if (!m || (m.viewer_id != null && this.viewerId && m.viewer_id !== this.viewerId)) { return false; }
        var current = this.items[m.id];
        if (current && (Number(current.seq) || 0) > (Number(m.seq) || 0)) { return false; }
        this.items[m.id] = m;
        if (m.client_id && this.pending[m.client_id]) { this.dropPending(m.client_id); }
        return !current;
    };

    Chat.prototype.remove = function (id, clientId) {
        delete this.items[id];
        if (clientId && this.pending[clientId]) { this.dropPending(clientId); }
    };

    Chat.prototype.maxId = function () {
        var max = 0;
        for (var id in this.items) { if (Number(id) > max) { max = Number(id); } }
        return max;
    };

    Chat.prototype.syncParams = function () {
        if (!this.threadId || !this.loaded) { return null; }
        return { thread: this.threadId, seq: this.seq, after: this.maxId() };
    };

    Chat.prototype.applySync = function (d) {
        var self = this;
        if (!this.threadId || !this.loaded || !d) { return; }
        if (d.thread_gone) {
            this.showPlaceholder('This conversation is no longer available.');
            var gone = this.threadId;
            this.threadId = null;
            if (this.opts.onGone) { this.opts.onGone(gone); }
            return;
        }
        if (d.reload) { this.open(this.threadId); return; }
        var arrived = 0;
        (d.changes || []).forEach(function (c) {
            if (c.deleted) { self.remove(c.id, c.client_id); return; }
            if (self.upsert(c) && !self.isMine(c)) { arrived += 1; }
        });
        if (typeof d.seq === 'number' && d.seq > this.seq) { this.seq = d.seq; }
        if (d.read_upto && Number(d.read_upto) > this.readUpto) { this.readUpto = Number(d.read_upto); }
        if (d.typing) { this.typingNames = d.typing; this.renderTyping(); }
        if ((d.changes || []).length || d.read_upto) { this.render({ arrived: arrived }); }
        if (arrived && this.opts.onIncoming) { this.opts.onIncoming(arrived); }
    };

    /* --------------------------------------------------------- rendering */

    Chat.prototype.entries = function () {
        var self = this;
        var list = Object.keys(this.items).map(function (k) { return self.items[k]; })
            .sort(function (a, b) { return a.id - b.id; })
            .map(function (m) { return self.normalize(m); });
        Object.keys(this.pending).map(function (k) { return self.pending[k]; })
            .sort(function (a, b) { return a.created - b.created; })
            .forEach(function (p) { list.push(self.normalizePending(p)); });
        return list;
    };

    Chat.prototype.normalize = function (m) {
        var mine = this.isMine(m);
        return {
            key: 'm' + m.id, id: m.id, mine: mine, senderId: m.sender_id, sender: m.sender,
            avatar: m.avatar, initials: m.initials, body: m.body || '',
            date: m.iso ? new Date(m.iso) : new Date(), attachments: m.attachments || [],
            reply: m.reply_to, reactions: m.reactions || [], document: m.document,
            withheld: m.document_withheld, edited: m.edited, seq: m.seq || 0,
            state: mine ? (m.id <= this.readUpto || m.read ? 'read' : 'sent') : 'received'
        };
    };

    Chat.prototype.normalizePending = function (p) {
        return {
            key: 'c' + p.client_id, clientId: p.client_id, mine: true, senderId: this.viewerId,
            sender: 'You', avatar: this.opts.me && this.opts.me.avatar, initials: this.opts.me && this.opts.me.initials,
            body: p.body, date: new Date(p.created), attachments: p.local || [], reply: p.reply,
            reactions: [], state: p.state, error: p.error, retryable: p.retryable, progress: p.progress
        };
    };

    Chat.prototype.render = function (how) {
        how = how || {};
        if (!this.threadId) { return; }
        var stick = how.initial || how.mine || this.atBottom();
        var entries = this.entries();
        var desired = [];
        var self = this;

        if (!entries.length) {
            this.listEl.innerHTML = '<div class="qc-empty"><i class="bi bi-chat-heart"></i><p>No messages yet. Say hello.</p></div>';
            return;
        }
        var placeholder = this.listEl.querySelector('.qc-empty, .qc-loading');
        if (placeholder) { this.listEl.innerHTML = ''; }

        entries.forEach(function (e, i) {
            var prev = entries[i - 1], next = entries[i + 1];
            if (!prev || !sameDay(prev.date, e.date)) {
                var label = dayLabel(e.date);
                desired.push({ key: 'd' + e.date.toDateString(), html: '<div class="qc-sep" data-key="d' + esc(e.date.toDateString()) + '"><span>' + esc(label) + '</span></div>' });
            } else if (e.date - prev.date >= TIME_GAP_MS) {
                desired.push({ key: 't' + e.key, html: '<div class="qc-sep is-time" data-key="t' + e.key + '"><span>' + esc(timeLabel(e.date)) + '</span></div>' });
            }
            if (self.firstUnread && e.id === self.firstUnread && !e.mine) {
                desired.push({ key: 'unread', html: '<div class="qc-unread-line" data-key="unread"><span>New messages</span></div>' });
            }
            var first = !prev || !self.sameGroup(prev, e);
            var last = !next || !self.sameGroup(e, next);
            desired.push({ key: e.key, html: self.messageHTML(e, first, last) });
        });
        this.reconcile(desired);

        if (how.initial) {
            var line = this.listEl.querySelector('.qc-unread-line');
            if (line) { line.scrollIntoView({ block: 'center' }); } else { this.scrollToBottom(); }
        } else if (stick) {
            this.scrollToBottom();
        } else if (how.arrived) {
            this.unseen += how.arrived;
            this.jumpEl.hidden = false;
            this.jumpEl.querySelector('span').textContent = this.unseen === 1 ? '1 new message' : this.unseen + ' new messages';
        }
        player.paint(true);
    };

    // Replace only what changed, so a picture is not reloaded and a voice
    // message keeps playing when something else in the conversation changes.
    Chat.prototype.reconcile = function (desired) {
        var existing = {};
        Array.prototype.forEach.call(this.listEl.children, function (node) {
            var k = node.getAttribute('data-key');
            if (k) { existing[k] = node; } else { node.remove(); }
        });
        var cursor = this.listEl.firstElementChild;
        var self = this;
        desired.forEach(function (d) {
            var sig = String(hash(d.html));
            var node = existing[d.key];
            if (node && node.getAttribute('data-sig') !== sig) {
                var fresh = self.nodeFrom(d.html, sig);
                if (node === cursor) { cursor = fresh; }
                node.replaceWith(fresh);
                node = fresh;
            } else if (!node) {
                node = self.nodeFrom(d.html, sig);
            }
            delete existing[d.key];
            if (node === cursor) {
                cursor = cursor.nextElementSibling;
            } else {
                self.listEl.insertBefore(node, cursor);
            }
        });
        Object.keys(existing).forEach(function (k) { existing[k].remove(); });
    };

    Chat.prototype.nodeFrom = function (html, sig) {
        var t = document.createElement('template');
        t.innerHTML = html.trim();
        var node = t.content.firstElementChild;
        node.setAttribute('data-sig', sig);
        return node;
    };

    Chat.prototype.sameGroup = function (a, b) {
        return a.mine === b.mine && a.senderId === b.senderId && sameDay(a.date, b.date) &&
            (b.date - a.date) < GROUP_GAP_MS && !b.reply;
    };

    Chat.prototype.avatarHTML = function (e) {
        if (e.avatar) {
            return '<span class="qc-avatar has-photo"><img src="' + esc(e.avatar) + '" alt="" loading="lazy" decoding="async"></span>';
        }
        return '<span class="qc-avatar" aria-hidden="true">' + esc(e.initials || '') + '</span>';
    };

    Chat.prototype.messageHTML = function (e, first, last) {
        var cls = ['qc-msg', e.mine ? 'is-mine' : 'is-theirs'];
        if (first) { cls.push('is-first'); }
        if (last) { cls.push('is-last'); }
        if (e.state === 'sending' || e.state === 'queued') { cls.push('is-pending'); }
        if (e.state === 'failed') { cls.push('is-failed'); }
        var jumbo = isJumbo(e.body) && !e.attachments.length && !e.reply && !e.document;
        if (jumbo) { cls.push('is-jumbo'); }

        var inner = '';
        if (e.reply) { inner += this.replyQuoteHTML(e.reply); }
        inner += this.attachmentsHTML(e);
        if (e.document) {
            inner += '<div class="qc-doc"><i class="bi bi-file-earmark-text"></i><div class="qc-doc-body">' +
                '<div class="qc-doc-title">' + esc(e.document.title) + '</div>' +
                '<div class="qc-doc-meta">' + esc([e.document.area, e.document.year].filter(Boolean).join(' · ')) + '</div>' +
                '<a class="qc-doc-link" href="' + esc(e.document.view_url) + '" target="_blank" rel="noopener">View document</a>' +
                '</div></div>';
        } else if (e.withheld) {
            inner += '<div class="qc-doc is-withheld"><i class="bi bi-lock"></i><span>A document you don\'t have access to</span></div>';
        }
        if (e.body) { inner += '<div class="qc-text">' + linkify(esc(e.body)) + '</div>'; }

        var hasMedia = e.attachments.some(function (a) { return a.kind === 'image'; }) && !e.body && !e.reply;
        var bubble = '<div class="qc-bubble' + (hasMedia ? ' is-media' : '') + '">' + inner + '</div>';

        var reactions = '';
        if (e.reactions.length) {
            reactions = '<div class="qc-reactions">' + e.reactions.map(function (r) {
                return '<button type="button" class="qc-reaction' + (r.mine ? ' is-mine' : '') + '" data-act="toggle-reaction" data-emoji="' + esc(r.emoji) +
                    '" title="' + esc(r.names.join(', ')) + '" aria-label="' + esc(r.emoji + ' ' + r.count + ': ' + r.names.join(', ')) + '">' +
                    '<span>' + esc(r.emoji) + '</span>' + (r.count > 1 ? '<b>' + r.count + '</b>' : '') + '</button>';
            }).join('') + '</div>';
        }

        var meta = '<div class="qc-meta" title="' + esc(fullStamp(e.date)) + '">' +
            '<time datetime="' + esc(e.date.toISOString()) + '">' + esc(timeLabel(e.date)) + '</time>' +
            (e.edited ? ' · edited' : '') + this.statusHTML(e) + '</div>';

        var actions = '';
        if (e.id) {
            actions = '<div class="qc-actions" role="toolbar" aria-label="Message actions">' +
                '<button type="button" class="qc-act" data-act="react" aria-label="React" title="React"><i class="bi bi-emoji-smile"></i></button>' +
                '<button type="button" class="qc-act" data-act="reply" aria-label="Reply" title="Reply"><i class="bi bi-reply"></i></button>' +
                '<button type="button" class="qc-act" data-act="more" aria-label="More" title="More"><i class="bi bi-three-dots"></i></button>' +
                '</div>';
        }

        var failed = '';
        if (e.state === 'failed') {
            failed = '<div class="qc-failed" role="alert"><i class="bi bi-exclamation-circle-fill"></i><span>' + esc(e.error || 'Not sent.') + '</span>' +
                (e.retryable !== false ? '<button type="button" class="qc-link" data-act="retry">Retry</button>' : '') +
                '<button type="button" class="qc-link" data-act="discard">Remove</button></div>';
        }

        var progress = '';
        if (e.state === 'sending' && e.progress != null) {
            progress = '<div class="qc-progress" aria-label="Uploading"><i style="width:' + Math.round(e.progress * 100) + '%"></i></div>';
        }

        return '<div class="' + cls.join(' ') + '" data-key="' + e.key + '"' + (e.id ? ' data-id="' + e.id + '"' : '') +
               (e.clientId ? ' data-client="' + esc(e.clientId) + '"' : '') + '>' +
                 '<div class="qc-avatar-slot">' + (last ? this.avatarHTML(e) : '') + '</div>' +
                 '<div class="qc-stack">' +
                   (first && !e.mine && this.opts.showNames ? '<div class="qc-name">' + esc(e.sender) + '</div>' : '') +
                   '<div class="qc-line">' + bubble + actions + '</div>' +
                   progress + reactions + failed + meta +
                 '</div>' +
               '</div>';
    };

    Chat.prototype.statusHTML = function (e) {
        if (!e.mine) { return ''; }
        switch (e.state) {
        case 'sending':
            return '<span class="qc-status"><i class="bi bi-clock"></i>' + (e.progress != null ? 'Uploading ' + Math.round(e.progress * 100) + '%' : 'Sending…') + '</span>';
        case 'queued':
            return '<span class="qc-status"><i class="bi bi-wifi-off"></i>Waiting for connection</span>';
        case 'failed':
            return '<span class="qc-status is-failed"><i class="bi bi-exclamation-circle"></i>Not sent</span>';
        case 'read':
            return '<span class="qc-status is-read" title="Seen"><i class="bi bi-check2-all"></i>Seen</span>';
        default:
            return '<span class="qc-status" title="Sent"><i class="bi bi-check2"></i>Sent</span>';
        }
    };

    Chat.prototype.replyQuoteHTML = function (r) {
        if (!r) { return ''; }
        var who = r.mine ? 'You' : r.sender;
        var text = r.deleted ? 'Original message was deleted' : (r.snippet || '');
        return '<button type="button" class="qc-quote' + (r.deleted ? ' is-deleted' : '') + '" data-act="goto" data-target="' + (r.id || '') + '">' +
            '<strong>' + esc(who) + '</strong><span>' + esc(text) + '</span></button>';
    };

    Chat.prototype.attachmentsHTML = function (e) {
        var images = e.attachments.filter(function (a) { return a.kind === 'image'; });
        var others = e.attachments.filter(function (a) { return a.kind !== 'image'; });
        var html = '';
        if (images.length) {
            html += '<div class="qc-gallery is-' + Math.min(images.length, 4) + '">' + images.slice(0, 4).map(function (a, i) {
                var more = (i === 3 && images.length > 4) ? '<span class="qc-more">+' + (images.length - 4) + '</span>' : '';
                var ratio = a.width && a.height ? ' style="aspect-ratio:' + a.width + ' / ' + a.height + '"' : '';
                return '<button type="button" class="qc-img" data-act="image" data-index="' + i + '"' + (images.length === 1 ? ratio : '') +
                    ' aria-label="Open picture ' + esc(a.name || '') + '">' +
                    '<img src="' + esc(a.thumb_url || a.url) + '" alt="' + esc(a.name || 'Picture') + '" loading="lazy" decoding="async">' + more + '</button>';
            }).join('') + '</div>';
        }
        others.forEach(function (a) {
            if (a.kind === 'voice') {
                var key = a.id ? 'a' + a.id : 'l' + a.url;
                var bars = '';
                var seed = hash(String(a.id || a.url || ''));
                for (var b = 0; b < 28; b++) {
                    seed = (seed * 1103515245 + 12345) | 0;
                    bars += '<i style="height:' + (28 + Math.abs(seed % 72)) + '%"></i>';
                }
                html += '<div class="qc-voice" data-voice-key="' + esc(key) + '" data-src="' + esc(a.url) + '" data-duration="' + (Number(a.duration) || 0) + '">' +
                    '<button type="button" class="qc-voice-play" data-act="voice" aria-label="Play voice message"><i class="bi bi-play-fill"></i></button>' +
                    '<div class="qc-voice-wave" data-act="voice-seek" aria-hidden="true">' + bars + '</div>' +
                    '<span class="qc-voice-time">' + esc(fmtDuration(a.duration)) + '</span></div>';
            } else {
                html += '<a class="qc-file-chip"' + (a.download_url ? ' href="' + esc(a.download_url) + '"' : '') + ' download>' +
                    '<i class="bi ' + fileIcon(a.name) + '"></i>' +
                    '<span class="qc-file-text"><span class="qc-file-name">' + esc(a.name) + '</span>' +
                    '<span class="qc-file-size">' + esc(fmtSize(a.size)) + ' · ' + esc(extOf(a.name).slice(1).toUpperCase() || 'File') + '</span></span>' +
                    (a.download_url ? '<i class="bi bi-download qc-file-dl"></i>' : '') + '</a>';
            }
        });
        return html;
    };

    Chat.prototype.renderTyping = function () {
        var names = this.typingNames || [];
        this.typingEl.hidden = !names.length || !this.threadId;
        if (names.length) {
            this.typingEl.querySelector('.qc-typing-text').textContent =
                names.length === 1 ? names[0] + ' is typing…' : names.join(', ') + ' are typing…';
        }
    };

    Chat.prototype.atBottom = function () {
        var s = this.scrollEl;
        return s.scrollHeight - s.scrollTop - s.clientHeight < 80;
    };

    Chat.prototype.scrollToBottom = function (smooth) {
        var s = this.scrollEl;
        if (smooth && s.scrollTo) { s.scrollTo({ top: s.scrollHeight, behavior: 'smooth' }); } else { s.scrollTop = s.scrollHeight; }
        this.unseen = 0;
        this.jumpEl.hidden = true;
    };

    /* ----------------------------------------------- clicks on messages */

    Chat.prototype.entryFor = function (node) {
        var row = node.closest('.qc-msg');
        if (!row) { return null; }
        var id = Number(row.getAttribute('data-id'));
        if (id && this.items[id]) { return { row: row, msg: this.items[id] }; }
        var cid = row.getAttribute('data-client');
        if (cid && this.pending[cid]) { return { row: row, pending: this.pending[cid] }; }
        return { row: row };
    };

    Chat.prototype.onListClick = function (e) {
        var btn = e.target.closest('[data-act]');
        var row = e.target.closest('.qc-msg');
        // On a touch screen there is no hover: a tap on a message shows its actions.
        if (!btn && row && window.matchMedia && window.matchMedia('(hover: none)').matches) {
            this.listEl.querySelectorAll('.qc-msg.is-touched').forEach(function (n) { if (n !== row) { n.classList.remove('is-touched'); } });
            row.classList.toggle('is-touched');
            return;
        }
        if (!btn) { return; }
        var act = btn.getAttribute('data-act');
        if (act === 'reopen') { this.open(this.threadId); return; }
        var ref = this.entryFor(btn);
        if (!ref) { return; }
        var m = ref.msg;
        switch (act) {
        case 'reply': if (m) { this.setReply(m); this.inputEl.focus(); } break;
        case 'react': if (m) { this.openReactions(btn, m); } break;
        case 'more': if (m) { this.openMenu(btn, m); } break;
        case 'toggle-reaction': if (m) { this.react(m, btn.getAttribute('data-emoji')); } break;
        case 'goto': this.gotoMessage(Number(btn.getAttribute('data-target'))); break;
        case 'retry': if (ref.pending) { this.transmit(ref.pending); } break;
        case 'discard': if (ref.pending) { this.dropPending(ref.pending.client_id); this.render(); } break;
        case 'image': this.openImages(ref, Number(btn.getAttribute('data-index'))); break;
        case 'voice':
            var v = btn.closest('.qc-voice');
            player.toggle(v.getAttribute('data-voice-key'), v.getAttribute('data-src'), v.getAttribute('data-duration'));
            break;
        case 'voice-seek':
            var voice = btn.closest('.qc-voice');
            var rect = btn.getBoundingClientRect();
            var key = voice.getAttribute('data-voice-key');
            if (player.key !== key) { player.toggle(key, voice.getAttribute('data-src'), voice.getAttribute('data-duration')); }
            player.seek(key, (e.clientX - rect.left) / rect.width);
            break;
        }
    };

    Chat.prototype.openImages = function (ref, index) {
        var source = ref.msg ? ref.msg.attachments : (ref.pending ? ref.pending.local : []);
        var images = (source || []).filter(function (a) { return a.kind === 'image'; }).map(function (a) {
            return { url: a.url, name: a.name, download: a.download_url };
        });
        if (images.length) { lightbox.open(images, index || 0); }
    };

    Chat.prototype.gotoMessage = function (id) {
        var node = id && this.listEl.querySelector('.qc-msg[data-id="' + id + '"]');
        if (!node) { toast('That message is no longer in this conversation.', 'info'); return; }
        node.scrollIntoView({ block: 'center', behavior: 'smooth' });
        node.classList.remove('is-flash');
        void node.offsetWidth;
        node.classList.add('is-flash');
    };

    /* ------------------------------------------------- popover: react / menu */

    Chat.prototype.placePop = function (anchor) {
        var pop = this.popEl;
        pop.hidden = false;
        var root = this.root.getBoundingClientRect();
        var a = anchor.getBoundingClientRect();
        var w = pop.offsetWidth, h = pop.offsetHeight;
        var left = Math.min(Math.max(8, a.left - root.left + a.width / 2 - w / 2), root.width - w - 8);
        var top = a.top - root.top - h - 6;
        if (top < 8) { top = a.bottom - root.top + 6; }
        pop.style.left = left + 'px';
        pop.style.top = top + 'px';
        var firstBtn = pop.querySelector('button');
        if (firstBtn) { firstBtn.focus({ preventScroll: true }); }
    };

    Chat.prototype.openReactions = function (anchor, m) {
        this.popFor = m.id;
        this.popEl.className = 'qc-pop is-reactions';
        this.popEl.setAttribute('role', 'menu');
        this.popEl.innerHTML = REACTIONS.map(function (r) {
            var mine = (m.reactions || []).some(function (x) { return x.emoji === r && x.mine; });
            return '<button type="button" role="menuitem" class="qc-pop-emoji' + (mine ? ' is-mine' : '') + '" data-pop="react" data-emoji="' + r + '" aria-label="React with ' + r + '">' + r + '</button>';
        }).join('');
        this.placePop(anchor);
    };

    Chat.prototype.openMenu = function (anchor, m) {
        this.popFor = m.id;
        this.popEl.className = 'qc-pop is-menu';
        this.popEl.setAttribute('role', 'menu');
        var items = '<button type="button" role="menuitem" data-pop="reply"><i class="bi bi-reply"></i>Reply</button>';
        if (m.body) { items += '<button type="button" role="menuitem" data-pop="copy"><i class="bi bi-clipboard"></i>Copy text</button>'; }
        (m.attachments || []).forEach(function (a) {
            if (a.download_url) {
                items += '<a role="menuitem" href="' + esc(a.download_url) + '" download><i class="bi bi-download"></i>Download ' + esc(a.kind === 'voice' ? 'recording' : (a.kind === 'image' ? 'picture' : 'file')) + '</a>';
            }
        });
        if (this.isMine(m)) { items += '<button type="button" role="menuitem" class="is-danger" data-pop="delete"><i class="bi bi-trash3"></i>Delete</button>'; }
        this.popEl.innerHTML = items;
        this.placePop(anchor);
    };

    Chat.prototype.closePop = function () {
        if (!this.popEl.hidden) { this.popEl.hidden = true; this.popEl.innerHTML = ''; }
        this.popFor = null;
    };

    Chat.prototype.onPopClick = function (e) {
        var b = e.target.closest('[data-pop]');
        if (!b) { return; }
        var m = this.items[this.popFor];
        var what = b.getAttribute('data-pop');
        if (!m) { this.closePop(); return; }
        if (what === 'react') { this.closePop(); this.react(m, b.getAttribute('data-emoji')); }
        else if (what === 'reply') { this.closePop(); this.setReply(m); this.inputEl.focus(); }
        else if (what === 'copy') {
            this.closePop();
            var text = m.body;
            (navigator.clipboard && window.isSecureContext ? navigator.clipboard.writeText(text) : Promise.reject())
                .then(function () { toast('Copied.', 'success'); })
                .catch(function () { toast('Copying is not available here; select the text instead.', 'info'); });
        } else if (what === 'delete') {
            // Second step in the same menu: deleting is for everyone.
            this.popEl.className = 'qc-pop is-menu is-confirm';
            this.popEl.innerHTML = '<div class="qc-pop-note">Delete this message for everyone?</div>' +
                '<div class="qc-pop-actions"><button type="button" class="qc-btn" data-pop="cancel">Cancel</button>' +
                '<button type="button" class="qc-btn is-danger" data-pop="confirm-delete">Delete</button></div>';
            this.popEl.querySelector('[data-pop="cancel"]').focus();
        } else if (what === 'cancel') { this.closePop(); }
        else if (what === 'confirm-delete') { this.closePop(); this.deleteMessage(m); }
    };

    /* --------------------------------------------------------- actions */

    Chat.prototype.post = function (url, payload) {
        return fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf(), 'X-Requested-With': 'XMLHttpRequest' },
            body: JSON.stringify(payload || {})
        }).then(function (r) {
            if (window.qaActivity && window.qaActivity.expired(r)) { return { status: 401, data: {} }; }
            return r.json().catch(function () { return {}; }).then(function (data) {
                return { status: r.status, ok: r.ok, data: data };
            });
        }, function () { return { status: 0, data: {} }; });
    };

    Chat.prototype.react = function (m, emoji) {
        var self = this;
        if (!m || !emoji) { return; }
        // Shown at once; put back as it was if the server says no.
        var before = JSON.parse(JSON.stringify(m.reactions || []));
        var list = JSON.parse(JSON.stringify(before));
        var entry = list.filter(function (r) { return r.emoji === emoji; })[0];
        if (entry && entry.mine) {
            entry.count -= 1; entry.mine = false;
            entry.names = entry.names.filter(function (n) { return n !== 'You'; });
            if (!entry.count) { list = list.filter(function (r) { return r !== entry; }); }
        } else if (entry) {
            entry.count += 1; entry.mine = true; entry.names.push('You');
        } else {
            list.push({ emoji: emoji, count: 1, mine: true, names: ['You'] });
        }
        m.reactions = list;
        this.render();
        this.post(this.url('react', m.id), { emoji: emoji }).then(function (res) {
            if (res.ok && res.data.message) {
                self.upsert(res.data.message);
            } else {
                var current = self.items[m.id];
                if (current) { current.reactions = before; }
                toast(describeFailure(res.status, res.data, 'react'));
            }
            self.render();
        });
    };

    Chat.prototype.deleteMessage = function (m) {
        var self = this;
        var row = this.listEl.querySelector('.qc-msg[data-id="' + m.id + '"]');
        if (row) { row.classList.add('is-pending'); }
        this.post(this.url('del', m.id), {}).then(function (res) {
            if (res.ok) {
                self.remove(m.id, m.client_id);
                if (res.data.seq) { /* the sync will also report it; nothing else to do */ }
                self.render();
            } else {
                if (row) { row.classList.remove('is-pending'); }
                toast(describeFailure(res.status, res.data, 'delete'));
            }
        });
    };

    Chat.prototype.setReply = function (m) {
        this.replyTo = m || null;
        this.replyEl.hidden = !m;
        if (m) {
            var mine = this.isMine(m);
            this.replyEl.querySelector('strong').textContent = 'Replying to ' + (mine ? 'yourself' : m.sender);
            var snippet = m.body || (m.attachments && m.attachments.length
                ? (m.attachments[0].kind === 'voice' ? 'Voice message' : m.attachments[0].kind === 'image' ? 'Photo' : m.attachments[0].name)
                : 'A document');
            this.replyEl.querySelector('span').textContent = snippet.slice(0, 140);
        }
    };

    /* ---------------------------------------------------------- composer */

    Chat.prototype.autosize = function () {
        var el = this.inputEl;
        el.style.height = 'auto';
        el.style.height = Math.min(el.scrollHeight, 140) + 'px';
    };

    Chat.prototype.insertText = function (text) {
        var el = this.inputEl;
        var start = el.selectionStart != null ? el.selectionStart : el.value.length;
        var end = el.selectionEnd != null ? el.selectionEnd : el.value.length;
        el.value = el.value.slice(0, start) + text + el.value.slice(end);
        el.selectionStart = el.selectionEnd = start + text.length;
        el.focus();
        this.autosize();
        this.renderComposer();
    };

    Chat.prototype.toggleEmoji = function (show) {
        var open = show == null ? this.emojiPop.hidden : show;
        this.emojiPop.hidden = !open;
        var btn = this.root.querySelector('.qc-emoji-btn');
        if (btn) { btn.setAttribute('aria-expanded', open ? 'true' : 'false'); }
    };

    Chat.prototype.canRecord = function () {
        return !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    };

    Chat.prototype.renderComposer = function () {
        var hasText = !!this.inputEl.value.trim();
        var ready = hasText || this.tray.length;
        var mic = !ready && !this.recorder && this.canRecord();
        this.sendEl.classList.toggle('is-mic', mic);
        this.sendEl.classList.toggle('is-recording', !!this.recorder);
        this.sendEl.innerHTML = this.recorder ? '<i class="bi bi-send-fill"></i>' : (mic ? '<i class="bi bi-mic-fill"></i>' : '<i class="bi bi-send-fill"></i>');
        var label = this.recorder ? 'Send the voice message' : (mic ? 'Record a voice message' : 'Send');
        this.sendEl.setAttribute('aria-label', label);
        this.sendEl.title = label;
        this.sendEl.disabled = !this.threadId || (!ready && !mic && !this.recorder);
        this.root.querySelector('.qc-row').classList.toggle('is-recording', !!this.recorder);

        this.trayEl.hidden = !this.tray.length;
        this.trayEl.innerHTML = this.tray.map(function (t) {
            var preview = t.kind === 'image'
                ? '<img src="' + esc(t.url) + '" alt="">'
                : '<i class="bi ' + fileIcon(t.file.name) + '"></i>';
            return '<div class="qc-tray-item' + (t.kind === 'image' ? ' is-image' : '') + '">' + preview +
                '<span class="qc-tray-name" title="' + esc(t.file.name) + '">' + esc(t.file.name) + '</span>' +
                '<span class="qc-tray-size">' + esc(fmtSize(t.file.size)) + '</span>' +
                '<button type="button" class="qc-tray-remove" data-tray-remove="' + esc(t.id) + '" aria-label="Remove ' + esc(t.file.name) + '"><i class="bi bi-x"></i></button></div>';
        }).join('');
    };

    Chat.prototype.clearTray = function () {
        this.tray.forEach(function (t) { if (t.url) { URL.revokeObjectURL(t.url); } });
        this.tray = [];
        this.renderComposer();
    };

    // Checked here first so the person hears at once which file cannot go and
    // why; the server checks everything again.
    Chat.prototype.addFiles = function (files) {
        if (!this.threadId || !files.length) { return; }
        var o = this.opts;
        var maxBytes = (Number(o.maxMb) || 15) * 1024 * 1024;
        var maxFiles = Number(o.maxFiles) || 10;
        var allowed = (o.accept || '').split(',').map(function (s) { return s.trim().toLowerCase(); }).filter(Boolean);
        var self = this;
        var refused = [];
        files.forEach(function (f) {
            var ext = extOf(f.name);
            if (allowed.length && allowed.indexOf(ext) < 0) { refused.push('“' + f.name + '” is not a type that can be sent.'); return; }
            if (!f.size) { refused.push('“' + f.name + '” is empty.'); return; }
            if (f.size > maxBytes) { refused.push('“' + f.name + '” is larger than ' + (o.maxMb || 15) + ' MB.'); return; }
            if (self.tray.length >= maxFiles) { refused.push('At most ' + maxFiles + ' files per message.'); return; }
            var image = /^\.(png|jpe?g|gif|webp)$/.test(ext);
            self.tray.push({ id: uid(), file: f, kind: image ? 'image' : 'file', url: image ? URL.createObjectURL(f) : '' });
        });
        if (refused.length) { toast(refused.slice(0, 2).join(' ') + (refused.length > 2 ? ' (+' + (refused.length - 2) + ' more)' : '')); }
        this.renderComposer();
        this.inputEl.focus();
    };

    /* ----------------------------------------------------------- typing */

    Chat.prototype.noteTyping = function () {
        if (!this.threadId) { return; }
        var now = Date.now();
        if (!this.inputEl.value.trim()) { this.stopTyping(); return; }
        if (this.typingSentAt && now - this.typingSentAt < 3000) { return; }
        this.typingSentAt = now;
        this.typingThread = this.threadId;
        this.post(this.url('typing'), { typing: true });
    };

    Chat.prototype.stopTyping = function () {
        if (!this.typingSentAt || !this.typingThread) { return; }
        var url = this.opts.urls.typing.replace(/\/0\//, '/' + this.typingThread + '/');
        this.typingSentAt = 0;
        this.typingThread = null;
        this.post(url, { typing: false });
    };

    /* ------------------------------------------------------------ sending */

    Chat.prototype.submit = function () {
        if (!this.threadId || this.recorder) { return; }
        var body = this.inputEl.value.trim();
        var files = this.tray.slice();
        if (!body && !files.length) { return; }
        if (body.length > 5000) { toast('A message can be at most 5,000 characters.'); return; }
        var entry = {
            client_id: uid(), thread: this.threadId, body: body, created: Date.now(),
            files: files.map(function (t) { return t.file; }),
            local: files.map(function (t) {
                return { kind: t.kind, name: t.file.name, size: t.file.size, url: t.url || '' };
            }),
            reply: this.replyTo ? this.quoteOf(this.replyTo) : null,
            replyId: this.replyTo ? this.replyTo.id : null,
            state: 'sending', progress: files.length ? 0 : null
        };
        this.inputEl.value = '';
        this.autosize();
        this.tray = [];          // object URLs now belong to the pending message
        this.setReply(null);
        this.toggleEmoji(false);
        this.stopTyping();
        this.enqueue(entry);
    };

    Chat.prototype.quoteOf = function (m) {
        return { id: m.id, mine: this.isMine(m), sender: m.sender, deleted: false,
                 snippet: m.body ? m.body.slice(0, 140) : (m.attachments && m.attachments.length ? (m.attachments[0].kind === 'voice' ? 'Voice message' : m.attachments[0].kind === 'image' ? 'A photo' : m.attachments[0].name) : '') };
    };

    Chat.prototype.enqueue = function (entry) {
        this.pending[entry.client_id] = entry;
        if (!entry.files.length && !entry.voice) { this.persist(entry); }
        this.renderComposer();
        this.render({ mine: true });
        this.transmit(entry);
    };

    Chat.prototype.persist = function (entry) {
        var all = outboxLoad(this.viewerId);
        all[entry.client_id] = { thread: entry.thread, body: entry.body, reply: entry.reply, replyId: entry.replyId, created: entry.created };
        outboxSave(this.viewerId, all);
    };

    Chat.prototype.unpersist = function (clientId) {
        var all = outboxLoad(this.viewerId);
        if (all[clientId]) { delete all[clientId]; outboxSave(this.viewerId, all); }
    };

    // Text messages that were waiting when the page was closed or reloaded go
    // now. Their client ids are the original ones, so any that did reach the
    // server come back as the stored message rather than a second copy.
    Chat.prototype.restoreOutbox = function () {
        var all = outboxLoad(this.viewerId);
        var self = this;
        Object.keys(all).forEach(function (cid) {
            var e = all[cid];
            if (Number(e.thread) !== self.threadId || self.pending[cid]) { return; }
            // Already delivered (the answer was lost): the message is here.
            var delivered = Object.keys(self.items).some(function (id) { return self.items[id].client_id === cid; });
            if (delivered) { self.unpersist(cid); return; }
            var entry = { client_id: cid, thread: self.threadId, body: e.body, created: e.created, files: [], local: [],
                          reply: e.reply, replyId: e.replyId, state: 'sending', progress: null };
            self.pending[cid] = entry;
            self.transmit(entry);
        });
    };

    Chat.prototype.dropPending = function (clientId) {
        var e = this.pending[clientId];
        if (e && e.local) { e.local.forEach(function (a) { if (a.url && a.url.indexOf('blob:') === 0) { setTimeout(function () { URL.revokeObjectURL(a.url); }, 60000); } }); }
        delete this.pending[clientId];
        this.unpersist(clientId);
    };

    Chat.prototype.flushQueued = function () {
        var self = this;
        Object.keys(this.pending).forEach(function (cid) {
            var e = self.pending[cid];
            if (e.state === 'queued' || (e.state === 'failed' && e.networkFailure)) { self.transmit(e); }
        });
    };

    Chat.prototype.transmit = function (entry) {
        var self = this;
        if (entry.inFlight) { return; }
        if (navigator.onLine === false) {
            entry.state = 'queued';
            this.render();
            return;
        }
        entry.state = 'sending';
        entry.error = '';
        entry.inFlight = true;
        if (entry.files.length || entry.voice) { entry.progress = entry.progress || 0; }
        this.render();
        var url = this.opts.urls.send.replace(/\/0\//, '/' + entry.thread + '/');

        var done = function (status, data) {
            entry.inFlight = false;
            if (!self.pending[entry.client_id]) {
                // Delivered already (by the sync), or the conversation was
                // left while this was sending. A failure then still has to be
                // said; a text message is retried when it is opened again.
                if (entry.detached && !(status >= 200 && status < 300)) {
                    toast(entry.files.length || entry.voice
                        ? 'A message with files in another conversation was not sent. Open it and send the files again.'
                        : 'A message in another conversation was not sent yet. It will be sent when you open that conversation.');
                }
                if (entry.detached && status >= 200 && status < 300 && self.opts.onSent) { self.opts.onSent(data.thread); }
                return;
            }
            if (status >= 200 && status < 300 && data && data.message) {
                self.dropPending(entry.client_id);
                if (Number(entry.thread) === self.threadId) {
                    self.upsert(data.message);
                    self.render({ mine: true });
                }
                if (self.opts.onSent) { self.opts.onSent(data.thread); }
                return;
            }
            if (status === 401) { return; }
            entry.networkFailure = status === 0;
            entry.state = (status === 0 && navigator.onLine === false) ? 'queued' : 'failed';
            entry.retryable = status === 0 || status >= 500 || status === 429 || status === 408;
            entry.error = describeFailure(status, data, entry.files.length || entry.voice ? 'upload' : 'send');
            entry.progress = null;
            self.render();
        };

        var form;
        if (entry.files.length || entry.voice) {
            form = new FormData();
            form.append('body', entry.body || '');
            form.append('client_id', entry.client_id);
            if (entry.replyId) { form.append('reply_to', entry.replyId); }
            entry.files.forEach(function (f) { form.append('files', f, f.name); });
            if (entry.voice) {
                form.append('voice', entry.voice, entry.voiceName || 'voice.webm');
                form.append('voice_duration', String(entry.duration || 0));
            }
            var xhr = new XMLHttpRequest();
            xhr.open('POST', url);
            xhr.setRequestHeader('X-CSRFToken', csrf());
            xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
            xhr.upload.addEventListener('progress', function (ev) {
                if (!ev.lengthComputable) { return; }
                entry.progress = ev.loaded / ev.total;
                self.paintProgress(entry);
            });
            xhr.addEventListener('load', function () {
                var data = {};
                try { data = JSON.parse(xhr.responseText || '{}'); } catch (err) { data = {}; }
                if (xhr.status === 401 && window.qaActivity) {
                    window.location.href = xhr.getResponseHeader('X-QA-Login') || '/accounts/login/';
                }
                done(xhr.status, data);
            });
            xhr.addEventListener('error', function () { done(0, {}); });
            xhr.addEventListener('timeout', function () { done(0, {}); });
            xhr.timeout = 5 * 60 * 1000;
            xhr.send(form);
        } else {
            this.post(url, { body: entry.body, client_id: entry.client_id, reply_to: entry.replyId || null })
                .then(function (res) { done(res.status, res.data); });
        }
    };

    // Upload progress is painted in place, not through a full redraw.
    Chat.prototype.paintProgress = function (entry) {
        var node = this.listEl.querySelector('.qc-msg[data-client="' + entry.client_id + '"]');
        if (!node) { return; }
        var bar = node.querySelector('.qc-progress i');
        var pct = Math.round(entry.progress * 100);
        if (bar) { bar.style.width = pct + '%'; }
        var status = node.querySelector('.qc-status');
        if (status) { status.innerHTML = '<i class="bi bi-clock"></i>' + (pct >= 100 ? 'Processing…' : 'Uploading ' + pct + '%'); }
    };

    /* ------------------------------------------------------------- voice */

    Chat.prototype.startRecording = function () {
        var self = this;
        if (!this.threadId || this.recorder) { return; }
        if (!this.canRecord()) {
            toast(window.isSecureContext ? 'This browser cannot record audio.'
                : 'Voice messages need a secure connection (https or this computer).', 'info');
            return;
        }
        navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
            var types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
            var mime = types.filter(function (t) { return MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t); })[0];
            var rec;
            try { rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream); } catch (err) {
                stream.getTracks().forEach(function (t) { t.stop(); });
                toast('This browser cannot record audio.');
                return;
            }
            self.recorder = { rec: rec, stream: stream, chunks: [], started: Date.now(), send: false };
            rec.addEventListener('dataavailable', function (e) { if (e.data && e.data.size) { self.recorder && self.recorder.chunks.push(e.data); } });
            rec.addEventListener('stop', function () { self.finishRecording(); });
            rec.start(250);
            self.recEl.hidden = false;
            self.stopTyping();
            self.renderComposer();
            self.meter(stream);
            self.recTimer = setInterval(function () {
                if (!self.recorder) { return; }
                var secs = (Date.now() - self.recorder.started) / 1000;
                self.recEl.querySelector('.qc-rec-time').textContent = fmtDuration(secs);
                if (secs >= RECORD_MAX_S) { self.stopRecording(true); toast('Voice messages can be up to 5 minutes; this one was sent.', 'info'); }
            }, 250);
        }).catch(function (err) {
            var name = err && err.name;
            toast(name === 'NotAllowedError' || name === 'SecurityError'
                ? 'Microphone access is blocked. Allow it from the icon in the address bar, then try again.'
                : name === 'NotFoundError' ? 'No microphone was found.' : 'The microphone could not be started.');
        });
    };

    Chat.prototype.meter = function (stream) {
        var self = this;
        var Ctx = window.AudioContext || window.webkitAudioContext;
        var level = this.recEl.querySelector('.qc-rec-level');
        if (!Ctx || !level) { return; }
        try {
            var ctx = new Ctx();
            var source = ctx.createMediaStreamSource(stream);
            var analyser = ctx.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);
            var data = new Uint8Array(analyser.frequencyBinCount);
            level.innerHTML = new Array(16).join('<i></i>') + '<i></i>';
            var bars = level.querySelectorAll('i');
            var draw = function () {
                if (!self.recorder) { ctx.close().catch(function () {}); return; }
                analyser.getByteFrequencyData(data);
                for (var i = 0; i < bars.length; i++) {
                    var v = data[Math.floor(i * data.length / bars.length / 2)] / 255;
                    bars[i].style.height = Math.max(12, Math.round(v * 100)) + '%';
                }
                requestAnimationFrame(draw);
            };
            draw();
        } catch (err) { /* the level meter is a nicety */ }
    };

    Chat.prototype.stopRecording = function (send) {
        if (!this.recorder) { return; }
        this.recorder.send = !!send;
        this.recorder.duration = (Date.now() - this.recorder.started) / 1000;
        try { this.recorder.rec.stop(); } catch (err) { this.finishRecording(); }
    };

    Chat.prototype.finishRecording = function () {
        var r = this.recorder;
        if (!r) { return; }
        this.recorder = null;
        clearInterval(this.recTimer);
        r.stream.getTracks().forEach(function (t) { t.stop(); });
        this.recEl.hidden = true;
        this.recEl.querySelector('.qc-rec-time').textContent = '0:00';
        this.renderComposer();
        if (!r.send) { return; }
        if ((r.duration || 0) < 0.8 || !r.chunks.length) { toast('That recording was too short to send.', 'info'); return; }
        var type = (r.rec.mimeType || r.chunks[0].type || 'audio/webm').split(';')[0];
        var ext = type.indexOf('ogg') >= 0 ? '.ogg' : type.indexOf('mp4') >= 0 ? '.m4a' : '.webm';
        var blob = new Blob(r.chunks, { type: type });
        var local = URL.createObjectURL(blob);
        this.enqueue({
            client_id: uid(), thread: this.threadId, body: '', created: Date.now(), files: [],
            voice: blob, voiceName: 'voice' + ext, duration: Math.round(r.duration * 10) / 10,
            local: [{ kind: 'voice', url: local, duration: r.duration, name: 'Voice message' }],
            reply: this.replyTo ? this.quoteOf(this.replyTo) : null, replyId: this.replyTo ? this.replyTo.id : null,
            state: 'sending', progress: 0
        });
        this.setReply(null);
    };

    /* A conversation list's time: "9:58 AM" today, "Yesterday", the weekday
       within a week, the date otherwise. Falls back to the server's text. */
    function shortTime(iso, fallback) {
        var d = iso ? new Date(iso) : null;
        if (!d || isNaN(d)) { return fallback || ''; }
        var now = new Date();
        if (sameDay(d, now)) { return timeLabel(d); }
        var yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
        if (sameDay(d, yesterday)) { return 'Yesterday'; }
        if (now - d < 6 * 24 * 3600 * 1000) { return d.toLocaleDateString(undefined, { weekday: 'short' }); }
        return d.toLocaleDateString(undefined, d.getFullYear() === now.getFullYear()
            ? { month: 'short', day: 'numeric' } : { month: 'short', day: 'numeric', year: 'numeric' });
    }

    window.QAChat = { create: function (opts) { return new Chat(opts); }, REACTIONS: REACTIONS, shortTime: shortTime };
})();
