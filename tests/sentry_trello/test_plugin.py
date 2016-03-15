from __future__ import absolute_import

import responses

from django.core.urlresolvers import reverse
from exam import fixture
from sentry.models import GroupMeta
from sentry.plugins import register, unregister
from sentry.testutils import TestCase
from sentry.utils import json

from sentry_trello.plugin import TrelloCard


def show_response_error(response):
    if response.context and 'form' in response.context:
        return dict(response.context['form'].errors)
    return (response.status_code, response.content[:128].strip())


def trello_mock():
    # TODO(dcramer): we cannot currently assert on auth, which is pretty damned
    # important

    mock = responses.RequestsMock(assert_all_requests_are_fired=False)
    mock.add(mock.GET, 'https://trello.com/1/members/me/boards',
             json=[{'id': '1', 'name': 'Foo'}])
    mock.add(mock.POST, 'https://trello.com/1/cards',
             json={'id': '2', 'url': 'https://example.trello.com/cards/2'})
    mock.add(mock.GET, 'https://trello.com/1/members/me/organizations',
             json=[{'id': '3', 'name': 'Bar'}])

    return mock


class TrelloPluginTest(TestCase):
    plugin_cls = TrelloCard

    def setUp(self):
        super(TrelloPluginTest, self).setUp()
        register(self.plugin_cls)
        self.group = self.create_group(message='Hello world', culprit='foo.bar')
        self.event = self.create_event(group=self.group, message='Hello world')

    def tearDown(self):
        unregister(self.plugin_cls)
        super(TrelloPluginTest, self).tearDown()

    @fixture
    def plugin(self):
        return self.plugin_cls()

    @fixture
    def action_path(self):
        project = self.project
        return reverse('sentry-group-plugin-action', args=[
            project.organization.slug, project.slug, self.group.id, self.plugin.slug,
        ])

    @fixture
    def configure_path(self):
        project = self.project
        return reverse('sentry-configure-project-plugin', args=[
            project.organization.slug, project.slug, self.plugin.slug,
        ])

    def test_create_issue_renders(self):
        project = self.project
        plugin = self.plugin

        plugin.set_option('key', 'foo', project)
        plugin.set_option('token', 'bar', project)

        self.login_as(self.user)

        with trello_mock(), self.options({'system.url-prefix': 'http://example.com'}):
            response = self.client.get(self.action_path)

        assert response.status_code == 200, vars(response)
        self.assertTemplateUsed(response, 'sentry_trello/create_trello_issue.html')

    def test_create_issue_saves(self):
        project = self.project
        plugin = self.plugin

        plugin.set_option('key', 'foo', project)
        plugin.set_option('token', 'bar', project)

        self.login_as(self.user)

        with trello_mock() as mock:
            response = self.client.post(self.action_path, {
                'title': 'foo',
                'description': 'A ticket description',
                'trello_board': '1',
                'trello_list': '15',
            })

            assert response.status_code == 302, show_response_error(response)
            meta = GroupMeta.objects.get(group=self.group, key='trello:tid')
            assert meta.value == '2/https://example.trello.com/cards/2'

            trello_request = mock.calls[-1].request
            assert trello_request.url == 'https://trello.com/1/cards?token=bar&key=foo'
            assert json.loads(trello_request.body) == {
                'desc': 'A ticket description',
                'idList': '15',
                'name': 'foo',
            }

    @responses.activate
    def test_create_issue_with_fetch_errors(self):
        project = self.project
        plugin = self.plugin

        plugin.set_option('key', 'foo', project)
        plugin.set_option('token', 'bar', project)

        self.login_as(self.user)

        response = self.client.get(self.action_path)

        assert response.status_code == 200, vars(response)
        self.assertTemplateUsed(response, 'sentry_trello/plugin_misconfigured.html')

    def test_configure_renders(self):
        self.login_as(self.user)
        with trello_mock():
            response = self.client.get(self.configure_path)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'sentry/plugins/project_configuration.html')
        assert '<input type="hidden" name="plugin" value="trello" />' in response.content
        assert 'name="trello-token"' in response.content
        assert 'name="trello-key"' in response.content
        assert 'name="trello-organization"' not in response.content

    def test_configure_saves_options(self):
        self.login_as(self.user)
        with trello_mock():
            response = self.client.post(self.configure_path, {
                'plugin': 'trello',
                'trello-token': 'foo',
                'trello-key': 'bar',
            })
        assert response.status_code == 302, show_response_error(response)

        project = self.project
        plugin = self.plugin

        assert plugin.get_option('token', project) == 'foo'
        assert plugin.get_option('key', project) == 'bar'

    def test_configure_renders_with_auth(self):

        project = self.project
        plugin = self.plugin

        plugin.set_option('key', 'foo', project)
        plugin.set_option('token', 'bar', project)

        self.login_as(self.user)

        with trello_mock():
            response = self.client.get(self.configure_path)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'sentry/plugins/project_configuration.html')
        assert '<input type="hidden" name="plugin" value="trello" />' in response.content
        assert 'name="trello-token"' in response.content
        assert 'name="trello-key"' in response.content
        assert 'name="trello-organization"' in response.content
