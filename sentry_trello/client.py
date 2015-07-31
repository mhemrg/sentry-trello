from __future__ import absolute_import

from sentry import http
from sentry.utils import json


class TrelloClient(object):
    base_url = 'https://trello.com/1/'

    def __init__(self, apikey, token=None, timeout=5):
        self._apikey = apikey
        self._token = token
        self._timeout = timeout

    def _request(self, path, method="GET", params=None, data=None):
        path = path.lstrip('/')
        url = '%s/%s' % (self.base_url, path)

        if not params:
            params = {}

        params.setdefault('key', self._apikey)
        params.setdefault('token', self._token)

        session = http.build_session()
        resp = getattr(session, method.lower())(
            url,
            params=params,
            json=data,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return json.loads(resp.content)

    def get_organization_board(self, org_id_or_name, fields=None):
        return self._request(
            path='/organizations/%s/boards' % (org_id_or_name),
            params={
                'fields': fields,
            },
        )

    def get_organization_list(self, member_id_or_username, fields=None):
        return self._request(
            path='/members/%s/organizations' % (member_id_or_username),
            params={
                'fields': fields,
            },
        )

    def get_board_list(self, board_id, fields=None):
        return self._request(
            path='/boards/%s/lists' % (board_id),
            params={
                'fields': fields,
            },
        )

    def new_card(self, name, idList, desc=None):
        return self._request(
            path='/cards',
            method='POST',
            data={
                'name': name,
                'idList': idList,
                'desc': desc,
            },
        )

    def organizations_to_options(self, member_id_or_username='me'):
        organizations = self.get_organization_list(member_id_or_username, fields='name')
        options = tuple()
        for org in organizations:
            options += ((org['id'], org['name']),)
        return options

    def boards_to_options(self, organization):
        boards = self.get_organization_board(organization, fields='name')
        options = tuple()
        for board in boards:
            group = tuple()
            lists = self.get_board_list(board['id'], fields='name')
            for l in lists:
                group += ((l['id'], l['name']),)
            options += ((board['name'], group),)
        return options
