"""
The standalone Smart Search page has been removed.

Searching now happens where the documents are: the Smart Search box and the
Program / Area / Year / File format / Cluster / Duplicate filters at the top of
the Document Repository run the same engine over the same records, so a separate
page listing the same results was a second front door to one feature.

What was removed is only the *page*. The search engine itself lives in
``search.search_service`` and is unchanged - ``documents.views.repository`` calls
it directly, so removing this view does not touch search behaviour.

This route is deliberately kept as a redirect rather than deleted outright. Old
bookmarks, the browser history of anyone who used the page, and any link written
before the change would otherwise 404, so ``/search/`` forwards to the repository
and carries the user's query and filters across intact.
"""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse

from accounts.decorators import repository_access_required

# Kept because the repository's own result paging is asserted against it.
SEARCH_PAGE_SIZE = 25

# Both pages named most parameters identically; only the file-type filter differed.
_PARAM_ALIASES = {'document_type': 'file_type'}

# Filters the repository understands. Anything else (the removed accreditation
# PK filters, for instance) is dropped rather than forwarded as a dead parameter.
_FORWARDABLE = {'q', 'year', 'file_type', 'duplicate', 'cluster', 'program', 'area', 'sort', 'dir'}


@login_required
@repository_access_required
def smart_search(request):
    """Forward the old Smart Search URL to the repository, preserving the search."""
    carried = {}
    for key, value in request.GET.items():
        key = _PARAM_ALIASES.get(key, key)
        if key in _FORWARDABLE and value:
            carried[key] = value

    target = reverse('documents:repository')
    if carried:
        target = f'{target}?{urlencode(carried)}'
    return redirect(target)
