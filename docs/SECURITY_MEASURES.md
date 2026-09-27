# Security measures in the QA Archiving System

Every item below is in the running system and covered by automated tests. File
paths are given so each one can be shown during a defense. Re-verified
2026-09-27 against the full 982-test suite (all passing), a browser crawl of
every page as Administrator, QA Head and two Faculty accounts, 24 tampering
attempts by a Faculty account against other users' and areas' data (all
refused, nothing changed), and a dependency audit (`pip-audit`).

## A. Accounts and passwords

1. **Passwords are never stored.** Django hashes them with PBKDF2-SHA256 and a
   per-user salt; nothing in the system can read a password back.
2. **Password strength is enforced** on creation, change and reset by four
   validators — similarity to the user's own details, minimum length, a
   common-password list, and numeric-only rejection
   (`AUTH_PASSWORD_VALIDATORS`, `accounts/forms.py`).
3. **Brute-force lockout.** Five failed sign-ins inside 15 minutes lock further
   attempts for 15 minutes, counted **per IP address and per username**, so
   neither guessing one account nor spraying many accounts gets far
   (`accounts/auth_security.py`; limits in `settings.py`).
4. **The lockout cannot be dodged with a forged IP.** `X-Forwarded-For` is
   ignored unless `TRUST_X_FORWARDED_FOR` is on for a real proxy, and even then
   only the proxy's own entry is read, not the part the client can write.
5. **Django's admin sign-in goes through the same locked-down login.**
   `/admin/login/` redirects to `/accounts/login/`, closing the second door that
   had no lockout (`qa_archiving_system/urls.py`).
6. **Deactivated accounts are refused** with an explicit message, and the attempt
   counts as a failure (`accounts/views.py`).
7. **Administrators cannot lock themselves out** — no deleting, deactivating or
   demoting your own account, and the last active administrator is protected
   (`accounts/views.py`, `accounts/tests/test_self_protection.py`).

## B. Sessions

8. **Idle timeout** signs a user out after one hour of inactivity, and a session
   lasts at most eight hours in total (`accounts/middleware.py`,
   `SESSION_IDLE_TIMEOUT`, `SESSION_COOKIE_AGE`).
9. **Session fixation is prevented** — Django issues a new session key on login.
10. **Cookies are hardened** in production: `HttpOnly`, `SameSite=Lax`, and
    `Secure` once HTTPS is enabled.
11. **Signing out requires a POST.** A link or an `<img>` on another site can no
    longer sign a user out (`accounts/views.py` `logout_view`).

## C. Request protection

12. **CSRF protection on every form and AJAX call** — Django's CSRF middleware
    plus an `X-CSRFToken` header on fetch/XHR requests. A failure shows a plain
    "this page has expired" page instead of a technical one.
13. **Open redirects are blocked.** The `?next=` parameter is checked with
    Django's `url_has_allowed_host_and_scheme`, so a crafted sign-in link cannot
    bounce a user to another site (`accounts/views.py`).
14. **Host header validation** — `ALLOWED_HOSTS` is enforced, and startup refuses
    a localhost-only configuration when `DEBUG=False`.
15. **Clickjacking** — `X-Frame-Options: SAMEORIGIN`.
16. **MIME sniffing** — `X-Content-Type-Options: nosniff` on every response, so a
    file can never be re-interpreted as a script by the browser.
17. **Content-Security-Policy** restricts scripts, styles, fonts, images and
    embedded objects to this site and the two CDNs the app actually uses;
    `Permissions-Policy` switches off camera, microphone and geolocation
    (`qa_archiving_system/middleware.py`).

## D. Access control

18. **Every page and download checks the server side, not the interface.**
    Role decorators (`login_required`, `role_required`, `admin_required`,
    `qa_staff_required`, `faculty_required`, `repository_access_required`) guard
    the views themselves (`accounts/decorators.py`).
19. **Three roles** — Admin, QA Head, Faculty — with Faculty scoped to their
    assigned accreditation areas.
20. **Object-level checks stop URL tampering (IDOR).** Changing a document id in
    the address bar does not reveal another area's document:
    `scope_documents_for_user`, `user_can_access_document`,
    `user_can_modify_document` (`accounts/permissions.py`).
21. **Refused attempts are recorded** as "Access denied" in the audit log
    (`accounts/decorators.py`).

## E. Files: storage, serving and validation

22. **Uploaded files are never served from `/media/`.** Direct links are blocked
    in every mode — development included — and documents are delivered only
    through views that check sign-in, role and area. Profile photos are the one
    public exception, and a `..` path cannot be used to reach documents through
    it (`qa_archiving_system/middleware.py`).
23. **Uploads are checked before anything is stored**, on all three upload paths
    (bulk, Faculty single-file, structured) — `documents/upload_validation.py`:

    | Check | What it stops |
    |---|---|
    | Extension allowlist: `.pdf .docx .xlsx .jpg .jpeg .png` | Scripts, executables, archives, HTML, SVG |
    | Size ≤ 25 MB, empty files refused | Storage exhaustion, files that fail later |
    | Declared media type refused if dangerous (`text/html`, `application/javascript`, `image/svg+xml`, executables) | A page or program offered as a document |
    | File signature / magic bytes must match the extension | A renamed `.exe` or `.html` posing as a PDF |
    | Images must **decode** as the format they claim, via Pillow | A file with a correct PNG header and a hostile or broken body |
    | Image pixel budget (50 megapixels) | Decompression bombs — a small file declaring enormous dimensions |
    | Word/Excel must be real Office packages (`[Content_Types].xml` plus `word/` or `xl/`) | A plain ZIP renamed `.docx` |
    | Macro projects (`vbaProject.bin`) refused | Macro malware in a `.docm` renamed `.docx` |
    | Package entries containing `..`, backslashes or absolute paths refused | Zip-slip, where unpacking writes outside the folder |
    | Expansion ratio and unpacked-size caps | Zip bombs |

24. **Profile pictures get the same treatment at their own scale:** 3 MB cap, the
    picture must open as an image, its real format must be one of JPEG/PNG/WebP/GIF
    (not merely what the browser called it), and a 30-megapixel budget applies
    (`accounts/forms.py`).
25. **File names cannot escape the upload folder** — Django's storage layer
    validates them, and ZIP downloads build their entry names through
    `_safe_zip_segment` (`documents/views.py`).
26. **Nothing uploaded is ever executed.** Files are read for text extraction and
    served back as downloads or previews; the web server never runs them.

## F. Abuse and resource limits

27. **Rate limits on the heavy actions**, counted per account *and* per device:
    20 QA Assistant messages a minute, 15 upload batches and 10 ZIP downloads per
    10 minutes. Each block is recorded once per window in the audit log
    (`qa_archiving_system/rate_limit.py`).
28. **Batch and parser caps** — at most 100 files per upload batch, and Django's
    own limits on request size and field counts (`settings.py`).

## G. Injection and output safety

29. **SQL injection** — every query goes through the Django ORM, which
    parameterises values; the application contains no raw SQL.
30. **Cross-site scripting** — templates auto-escape by default. Three places
    output HTML deliberately, and each escapes first: search-term highlighting
    (`search/templatetags/search_extras.py`), the spreadsheet viewer
    (`documents/file_converter.py`), and chart data, which reaches page scripts
    only through Django's `json_script` (AI Processing, Dashboard). The pages'
    own JavaScript builds messages, chat answers and upload lists with escape
    helpers that also escape quotes, because that text is placed in attributes
    too (`qa_archiving_system/tests/test_script_data_escaping.py`).
31. **Command injection** — external tools (LibreOffice for previews) are invoked
    with an argument list and no shell, under a timeout
    (`documents/preview_converters.py`).

## H. Configuration and operations

32. **Secrets come from the environment**, and the system refuses to start in
    production while the development `SECRET_KEY` is still in place.
33. **HTTPS readiness** — setting `USE_TLS=true` turns on the HTTPS redirect,
    secure cookies, HSTS and `CSRF_TRUSTED_ORIGINS`.
34. **Error pages reveal nothing.** A missing page, a refused permission, an
    expired form, a bad request or a crash all show a plain page with no error
    code, no traceback, no URL patterns and no settings — in development as well
    as production. Full details still go to the server console
    (`qa_archiving_system/error_pages.py`).
35. **Audit trail.** Sign-ins, failed sign-ins, sign-outs, access denials,
    uploads, downloads, views, edits, deletions, user management, duplicate
    decisions, AI runs, exports and messages are all recorded with the user, time
    and IP, and are readable by administrators in the Audit Log page
    (`documents/audit.py`, `accounts/views.py`).
36. **Deployment gate** — `manage.py check_production` and Django's
    `check --deploy` must pass before go-live; the full checklist is in
    [`SECURITY_BEFORE_DEPLOYMENT.md`](SECURITY_BEFORE_DEPLOYMENT.md).

## I. Exports

37. **Spreadsheet formula injection is blocked.** A document title or programme
    name beginning with `=`, `+`, `-` or `@` is written into CSV and Excel exports
    as text (with a leading apostrophe), so opening the export in Excel cannot run
    it as a formula — `=HYPERLINK("http://evil...")` in a title stays a title
    (`documents/excel_export.py`).

## J. Dependencies

38. **Known-vulnerability audit.** The pinned libraries are checked with
    `pip-audit -r requirements.txt -r requirements-prod.txt`. On 2026-09-27 this
    moved Pillow to 12.3.0 (image-parser memory bugs), requests to 2.34.2, and
    replaced PyPDF2 — abandoned, with an unfixed infinite-loop bug on crafted
    PDFs — by its maintained successor `pypdf`.

## How each measure is verified

Nothing on this list rests on reading the code alone. Each one is held in place
by at least one automated test, and the end-to-end ones were also exercised
against a running server on an isolated copy of the data.

| Measures | Evidence |
|---|---|
| 1, 2 | `qa_archiving_system/tests/test_security_posture.py` — hash format, salting, weak password refused |
| 3, 4, 6 | `accounts/tests/test_auth_security.py`, `test_client_ip.py`, `test_account_fixes.py`, plus a live brute-force run |
| 5 | `qa_archiving_system/tests/test_production_security.py` (admin login redirect) |
| 7 | `accounts/tests/test_self_protection.py` |
| 8 | `accounts/tests/test_idle_timeout.py` |
| 9, 10 | `test_security_posture.py` — session key changes at sign-in; cookie flags on the real response |
| 11 | `accounts/tests/test_security_fixes.py` (sign-out is POST-only) |
| 12 | `accounts/tests/test_security_fixes.py`, plus a live post with no token |
| 13 | `accounts/tests/test_security_fixes.py` (`NextRedirectTests`) |
| 14 | `test_error_pages.py` (bad host → 400) and `test_security_posture.py` (localhost-only refused in production) |
| 15, 16, 17 | `test_production_security.py`, `test_error_pages.py`, `test_security_posture.py` |
| 18, 19, 20, 21 | `accounts/tests/test_rbac.py`, `test_faculty.py`, `documents/tests/test_detail_scoping.py`, `test_area_rule.py` |
| 22 | `test_production_security.py` (blocked in every mode, photo folder exception, `..` guard) + live checks |
| 23 | `documents/tests/test_upload_validation.py` (19 tests) + a live run of 11 hostile files |
| 24 | `accounts/tests/test_avatars.py` (`AvatarUploadValidationTests`) |
| 25 | `test_security_posture.py` (`StoredFileNameTests`) |
| 26, 29, 31 | `test_security_posture.py` (`SourceGuardTests`) — the source is scanned for shell calls, raw SQL and interpreters |
| 27, 28 | `qa_archiving_system/tests/test_rate_limit.py` + live 429 responses |
| 30 | `test_security_posture.py` (`OutputEscapingTests`), `test_script_data_escaping.py` |
| 32, 33 | `test_security_posture.py` (`ProductionSettingsTests`) — a real process started with deployment settings |
| 34 | `qa_archiving_system/tests/test_error_pages.py` |
| 35 | `accounts/tests/test_audit_log.py` |
| 36 | `qa_archiving_system/tests/test_check_production.py` |
| 37 | `dashboard/tests/test_dashboard_fixes.py` (`ExportEscapingTests`) |
| 38 | `pip-audit` run; the full suite passing on the upgraded libraries |

Live end-to-end scripts (isolated copy, never live data):
`D:\QA-System-Check\t70_security_hardening.py` (26 checks) and
`t72_upload_attacks.py` (18 checks, hostile files and a brute-force attempt).

## What is deliberately *not* claimed

- **PDF contents are not deeply inspected.** A PDF may legitimately contain
  scripts or forms, so refusing them would refuse real evidence files. The
  protection is that PDFs are never executed by the server, are served with
  `nosniff`, and are rendered by the browser's own sandboxed viewer.
- **Antivirus scanning is not built in.** If the institution requires it, the
  natural place is on the upload path, after validation and before saving.
- **Django 4.2 is past its end of support (April 2026).** The seven advisories
  `pip-audit` lists for it concern features this system does not use (page
  caching, GeoDjango, signed cookies, `DomainNameValidator`), but future
  Django fixes will not reach 4.2. Moving to Django 5.2 LTS (supported to April
  2028) is the recommended next step.
- **The Content-Security-Policy allows inline scripts** (`'unsafe-inline'`),
  because the templates use inline `<script>` blocks. It still limits where
  scripts may load from, but it does not stop an injected inline script;
  protection against that rests on output escaping (item 30). A nonce-based
  policy is the stricter future step.
- **Profile photos are public** to anyone who has the link (item 22); documents
  are not.
- **The laptop copy runs in development mode** (`DEBUG` on, the development
  `SECRET_KEY`, plain HTTP). `check_production` refuses exactly this, so it
  must be changed before real use (see the checklist).
- **The default `admin` / `admin123` account still exists** for the laptop
  demonstration and must be changed before deployment (see the checklist).
