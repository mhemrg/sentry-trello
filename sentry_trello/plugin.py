#!/usr/bin/env python

"""
Sentry-Trello
=============

License
-------
Copyright 2012 Damian Zaremba

This file is part of Sentry-Trello.

Sentry-Trello is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Sentry-Trello is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Sentry-Trello. If not, see <http://www.gnu.org/licenses/>.
"""
from __future__ import absolute_import

import sentry_trello

from django import forms
from django.utils.translation import ugettext_lazy as _
from requests.exceptions import RequestException
from sentry import http
from sentry.plugins.bases.issue import IssuePlugin, NewIssueForm
from sentry.utils import json
from sentry.utils.http import absolute_uri

from .client import TrelloClient


class TrelloSettingsForm(forms.Form):
    key = forms.CharField(label=_('Trello API Key'))
    token = forms.CharField(label=_('Trello API Token'))
    organization = forms.CharField(label=_('Organization to add a card to'), max_length=50, required=False)

    def __init__(self, *args, **kwargs):
        super(TrelloSettingsForm, self).__init__(*args, **kwargs)
        initial = kwargs['initial']

        organizations = ()

        if initial.get('key'):
            trello = TrelloClient(initial.get('key'), initial.get('token'))
            try:
                organizations = (('', ''),) + trello.organizations_to_options()
            except RequestException:
                disabled = True
            else:
                disabled = False
        else:
            disabled = True

        if disabled:
            attrs = {'disabled': 'disabled'}
            help_text = _('Set correct key and token and save before')
            required = False
        else:
            attrs = None
            help_text = None
            required = True

        self.fields['organization'].widget = forms.Select(attrs=attrs, choices=organizations)
        self.fields['organization'].help_text = help_text
        self.fields['organization'].required = required


class TrelloForm(NewIssueForm):
    title = forms.CharField(label=_('Title'), max_length=200, widget=forms.TextInput(attrs={'class': 'span9'}))
    description = forms.CharField(label=_('Description'), widget=forms.Textarea(attrs={'class': 'span9'}))
    board_list = forms.CharField(label=_('Trello List'), max_length=50)

    def __init__(self, data=None, initial=None):
        super(TrelloForm, self).__init__(data=data, initial=initial)
        self.fields['board_list'].widget = forms.Select(choices=initial.get('trello_list', ()))


class TrelloCard(IssuePlugin):
    author = 'Damian Zaremba'
    author_url = 'http://damianzaremba.co.uk'
    title = _('Trello')
    description = _('Create Trello cards on exceptions.')
    slug = 'trello'

    resource_links = [
        (_('How do I configure this?'),
            'https://github.com/damianzaremba/sentry-trello/blob/master/HOW_TO_SETUP.md'),
        (_('Bug Tracker'), 'https://github.com/damianzaremba/sentry-trello/issues'),
        (_('Source'), 'https://github.com/damianzaremba/sentry-trello'),
    ]

    conf_title = title
    conf_key = 'trello'

    version = sentry_trello.VERSION
    project_conf_form = TrelloSettingsForm

    new_issue_form = TrelloForm

    def _get_group_description(self, request, group, event):
        """
        Return group description in markdown-compatible format.

        This overrides an internal method to IssuePlugin.
        """
        output = [
            absolute_uri(group.get_absolute_url()),
        ]
        body = self._get_group_body(request, group, event)
        if body:
            output.extend([
                '',
                '\n'.join('    ' + line for line in body.splitlines()),
            ])
        return '\n'.join(output)

    def is_configured(self, request, project, **kwargs):
        return all((self.get_option(key, project) for key in ('key', 'token', 'organization')))

    def get_client(self, project):
        return TrelloClient(
            apikey=self.get_option('key', project),
            token=self.get_option('token', project),
        )

    def get_initial_form_data(self, request, group, event, **kwargs):
        initial = super(TrelloCard, self).get_initial_form_data(request, group, event, **kwargs)
        trello = self.get_client(group.project)
        try:
            boards = trello.boards_to_options(self.get_option('organization', group.project))
        except RequestException as e:
            raise forms.ValidationError(_('Error adding Trello card: %s') % str(e))

        initial.update({
            'board_list': self.get_option('board_list', group.project),
            'trello_list': boards
        })
        return initial

    def get_issue_label(self, group, issue_id, **kwargs):
        iid, iurl = issue_id.split('/', 1)
        return _('Trello-%s') % iid

    def get_issue_url(self, group, issue_id, **kwargs):
        iid, iurl = issue_id.split('/', 1)
        return iurl

    def get_new_issue_title(self, **kwargs):
        return _('Create Trello Card')

    def create_issue(self, request, group, form_data, **kwargs):
        trello = self.get_client(group.project)
        try:
            card = trello.new_card(
                name=form_data['title'],
                desc=form_data['description'],
                idList=form_data['board_list'],
            )
        except RequestException as e:
            raise forms.ValidationError(_('Error adding Trello card: %s') % str(e))

        return '%s/%s' % (card['id'], card['url'])
