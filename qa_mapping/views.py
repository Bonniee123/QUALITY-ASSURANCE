"""
Views for QA programmes.

The QA checklist -- requirement records, their spreadsheet import and their
attachments -- was removed as out of scope. What remains manages the programmes
themselves, which the rest of the system depends on: a document carries a
programme, and the Program filter on the dashboard and the repository is built
from these rows.
"""
import logging

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from .models import QAProgram
from .forms import QAProgramForm
from documents.models import ActivityLog
from accounts.decorators import qa_staff_required, admin_required

logger = logging.getLogger(__name__)


@login_required
@qa_staff_required
def program_list(request):
    """
    List the QA programmes and how many documents each holds.

    This used to also show "requirements complete", measured against the QA
    checklist. The checklist was removed as out of scope, so there is nothing
    left to measure completion against and the bar would have read 0/0 for every
    programme.
    """
    summaries = [
        {'program': p, 'document_count': p.document_count}
        for p in QAProgram.objects.all()
    ]
    return render(request, 'qa_mapping/program_list.html', {
        'summaries': summaries,
    })


@login_required
@admin_required
def program_create(request):
    """Create a new QA program."""
    if request.method == 'POST':
        form = QAProgramForm(request.POST)
        if form.is_valid():
            prog = form.save()
            ActivityLog.objects.create(
                user=request.user,
                action='create_program',
                description=f'Created QA program: {prog.code} — {prog.name}',
            )
            messages.success(request, f'Program "{prog.name}" created.')
            return redirect('qa_mapping:program_list')
    else:
        form = QAProgramForm()
    return render(request, 'qa_mapping/program_form.html', {
        'form': form,
        'action': 'Create',
    })


@login_required
@admin_required
def program_edit(request, pk):
    """Edit an existing QA program."""
    prog = get_object_or_404(QAProgram, pk=pk)
    if request.method == 'POST':
        form = QAProgramForm(request.POST, instance=prog)
        if form.is_valid():
            form.save()
            messages.success(request, f'Program "{prog.name}" updated.')
            return redirect('qa_mapping:program_list')
    else:
        form = QAProgramForm(instance=prog)
    return render(request, 'qa_mapping/program_form.html', {
        'form': form,
        'action': 'Edit',
        'program_obj': prog,
    })


@login_required
@admin_required
def program_delete(request, pk):
    """Delete a QA program (related documents/requirements keep nullable program=NULL)."""
    prog = get_object_or_404(QAProgram, pk=pk)
    if request.method == 'POST':
        name = prog.name
        prog.delete()
        messages.success(request, f'Program "{name}" deleted.')
        return redirect('qa_mapping:program_list')
    return render(request, 'qa_mapping/program_confirm_delete.html', {
        'program_obj': prog,
    })

