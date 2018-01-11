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
from sentry.plugins.base import JSONResponse
from sentry.plugins.bases.issue import IssuePlugin, NewIssueForm
from sentry.utils.http import absolute_uri

from .client import TrelloClient

SETUP_URL = 'https://github.com/getsentry/sentry-trello/blob/master/HOW_TO_SETUP.md'  # NOQA

ISSUES_URL = 'https://github.com/getsentry/sentry-trello/issues'

EMPTY = (('', ''),)


class TrelloError(Exception):
    status_code = None

    def __init__(self, response_text, status_code=None):
        if status_code is not None:
            self.status_code = status_code
        self.text = response_text
        super(TrelloError, self).__init__(response_text[:128])

    @classmethod
    def from_response(cls, response):
        return cls(response.text, response.status_code)


class TrelloUnauthorized(TrelloError):
    status_code = 401


class TrelloSettingsForm(forms.Form):
    key = forms.CharField(label=_('Trello API Key'))
    token = forms.CharField(label=_('Trello API Token'))
    organization = forms.ChoiceField(
        label=_('Trello Organization'), choices=(), required=True)

    error_messages = {
        'invalid_auth': _('Invalid credentials. Please check your key and token and try again.'),
        'api_failure': _('An unknown error occurred while fetching data from Trello.'),
    }

    def __init__(self, *args, **kwargs):
        super(TrelloSettingsForm, self).__init__(*args, **kwargs)
        initial = kwargs['initial']

        organizations = ()

        if initial.get('key') and initial.get('token'):
            trello = TrelloClient(initial['key'], initial['token'])
            try:
                organizations = EMPTY + trello.organizations_to_options()
                self.fields['organization'].choices = organizations
                self.fields['organization'].widget.choices = self.fields['organization'].choices
            except RequestException:
                del self.fields['organization']
        else:
            del self.fields['organization']

    def clean(self):
        key = self.cleaned_data.get('key')
        token = self.cleaned_data.get('token')
        if key and token:
            trello = TrelloClient(key, token)
            try:
                # simply key validation
                trello.organizations_to_options()
            except RequestException as exc:
                if exc.response and exc.response.status_code == 401:
                    msg = self.error_messages['invalid_auth']
                else:
                    msg = self.error_messages['api_failure']
                raise forms.ValidationError(msg)
        return self.cleaned_data


class TrelloForm(NewIssueForm):
    title = forms.CharField(
        label=_('Title'), max_length=200,
        widget=forms.TextInput(attrs={'class': 'span9'}))
    description = forms.CharField(
        label=_('Description'),
        widget=forms.Textarea(attrs={'class': 'span9'}))
    trello_board = forms.CharField(label=_('Board'), max_length=50)
    trello_list = forms.CharField(label=_('List'), max_length=50)

    def __init__(self, data=None, initial=None):
        super(TrelloForm, self).__init__(data=data, initial=initial)
        self.fields['trello_board'].widget = forms.Select(
            choices=EMPTY + initial.get('boards', ())
        )
        self.fields['trello_list'].widget = forms.Select(
            attrs={'disabled': True},
            choices=initial.get('list', ()),
        )


class TrelloCard(IssuePlugin):
    author = 'Damian Zaremba'
    author_url = 'https://sentry.io'
    title = _('Trello')
    description = _('Create Trello cards on exceptions.')
    slug = 'trello'

    resource_links = [
        (_('How do I configure this?'),
            SETUP_URL),
        (_('Bug Tracker'),
            ISSUES_URL),
        (_('Source'), 'https://github.com/getsentry/sentry-trello'),
    ]

    conf_title = title
    conf_key = 'trello'

    version = sentry_trello.VERSION
    project_conf_form = TrelloSettingsForm
    new_issue_form = TrelloForm
    create_issue_template = 'sentry_trello/create_trello_issue.html'
    plugin_misconfigured_template = 'sentry_trello/plugin_misconfigured.html'

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
        return all((
            self.get_option(key, project)
            for key in ('key', 'token')
        ))

    def get_client(self, project):
        return TrelloClient(
            apikey=self.get_option('key', project),
            token=self.get_option('token', project),
        )

    def view(self, request, group, **kwargs):
        if request.is_ajax():
            view = self.view_ajax
        else:
            view = super(TrelloCard, self).view
        try:
            return view(request, group, **kwargs)
        except TrelloError as e:
            if request.is_ajax():
                return JSONResponse({})
            return self.render(self.plugin_misconfigured_template, {
                'text': e.text,
                'title': self.get_new_issue_title(),
            })

    def view_ajax(self, request, group, **kwargs):
        if request.GET.get('action', '') != 'lists':
            return JSONResponse({})
        board_id = request.GET['board_id']
        trello = self.get_client(group.project)
        lists = trello.get_board_list(board_id, fields='name')
        return JSONResponse({'result': lists})

    def get_initial_form_data(self, request, group, event, **kwargs):
        # TODO(dcramer): token is a secret and should be treated like a password
        # i.e. not returned into responses
        initial = super(TrelloCard, self).get_initial_form_data(
            request, group, event, **kwargs)
        trello = self.get_client(group.project)
        organization = self.get_option('organization', group.project)
        options = {}
        if organization:
            options['organization'] = organization
        try:
            boards = trello.boards_to_options(**options)
        except RequestException as e:
            print(e.request.url)
            resp = e.response
            if not resp:
                raise TrelloError('Internal Error')
            if resp.status_code == 401:
                raise TrelloUnauthorized.from_response(resp)
            raise TrelloError.from_response(resp)

        initial.update({
            'boards': boards,
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
                idList=form_data['trello_list'],
            )
        except RequestException as e:
            raise forms.ValidationError(
                _('Error adding Trello card: %s') % str(e))

        return '%s/%s' % (card['id'], card['url'])
