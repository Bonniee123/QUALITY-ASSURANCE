from django import template

from documents.audit import action_label

register = template.Library()


@register.filter
def audit_action_label(action):
    return action_label(action or '')
