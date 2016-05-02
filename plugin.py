###
# Copyright (c) 2016, Pulp Project
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###
import time
from functools import wraps

import supybot.utils as utils  # NOQA
from supybot.commands import *  # NOQA
import supybot.plugins as plugins  # NOQA
import supybot.ircutils as ircutils  # NOQA
import supybot.callbacks as callbacks
from supybot.ircmsgs import IrcMsg

import simplejson as json


def wrap_chair(func, *args, **kwargs):
    # wrap a function with a "normal" supybot wrap that additionally
    # checks that the caller is a meeting chair
    # this cannot be used as a decorator, and must explicitly be used
    # after the function definition to wrap the function
    @wraps(func)
    def wrapped(self, irc, msg, *wrapped_args, **wrapped_kwargs):
        if msg.nick not in self.chairs:
            irc.error('You are not the meeting chair.', private=True)
        else:
            return func(self, irc, msg, *wrapped_args, **wrapped_kwargs)
    return wrap(wrapped, *args, **kwargs)


priorities = ['low', 'normal', 'high', 'urgent']
severities = ['low', 'medium', 'high', 'urgent']


class PulpTriage(callbacks.Plugin):
    """MeetBot and Redmine come together to form PulpTriage!"""
    threaded = True

    def __init__(self, irc):
        self.__parent = super(PulpTriage, self)
        self.__parent.__init__(irc)
        self._reset()

    def _reset(self):
        # current issue being triaged
        self.current_issue = None
        # nicks participating in the current triage
        self.triagers = set()
        # issues that have already been seen, useful for managing deferred and skipped issues
        self.seen = set()
        # issues that have been deferred, should get handled after all other issues are seen
        self.deferred = set()
        # dict of issues that nicks care about, key is issue int, value is a set of nicks
        self.carers = {}
        # if set, proposal should be a tuple of ('action', 'string'),
        # where action is one of the strings handled in accept,
        # and string is a human-readable description of the action proposed.
        self.proposal = None
        # current list of issues in the triage issues list from redmine
        self.triage_issues = None
        # set of meeting chair nicks
        self.chairs = set()

    # command funcs

    def accept(self, irc, msg, args):
        """Accepts the current proposed triage resolution."""
        if self.proposal is None:
            irc.reply('No action proposed, nothing to accept.')
        else:
            action, proposal_msg = self.proposal
            self.proposal = None

            irc.reply('Current proposal accepted: %s' % proposal_msg)
            self._meetbot_agreed(irc, msg, [proposal_msg])
            if action in ('skip', 'accept', 'triage'):
                # since the bot doesn't touch redmine, all of these do the same thing.
                # if the bot *did* touch redmine, skip would do nothing, whereas accept
                # would mark the bug triaged, and triage would additional set prio, sev,
                # and target release if specified
                self.skip(irc, msg, args)
            elif action == 'defer':
                self.defer(irc, msg, args)

        # action methods should call "next", don't call it here.
    accept = wrap_chair(accept)

    @wrap(['text'])
    def action(self, irc, msg, args, text):
        """<text>

        Record an action item in the meeting log. Any nicks seen in the line will be recorded
        along with the action item in the meeting log."""
        self._meetbot_action(irc, msg, args, text)

    @wrap(['admin', optional('nick')])
    def addchair(self, irc, msg, args, nick):
        """[nick]

        Make yourself or a specified nick to the triage chair.

        This is generally only useful when the existing chair disappears for some reason, and
        someone needs to take over."""
        self.chairs.add(msg.nick)
        self._meetbot_newchair(irc, msg, args)

    @wrap(['admin'])
    def announce(self, irc, msg, args):
        """Announce a future triage session to configured channels. But...currently it does nothing
        and you need to make the announcements yourself. Coming Soon!"""
        pass

    @wrap([many('positiveInt')])
    def care(self, irc, msg, args, issue_ids):
        """<issue_id>

        Express interest in a specific issue that will be triaged. When that issue is up for
        discussion, users that !care about it will be pinged by nick."""
        for issue_id in issue_ids:
            if self.triage_issues and issue_id in self.triage_issues:
                self.carers.setdefault(issue_id, set()).add(msg.nick)

    def defer(self, irc, msg, args):
        """Immediately defer the current issue until later in the current triage session."""
        if self.current_issue:
            self.deferred.add(self.current_issue)
        self.next(irc, msg, args)
    defer = wrap_chair(defer)

    def end(self, irc, msg, args):
        """End the current meeting, if one is happening."""
        self._meetbot_endmeeting(irc, msg)
        self._reset()
    end = wrap_chair(end)

    def issue(self, irc, msg, args, issue_id):
        """<issue_id>

        Immediately switch to a specific redmine issue, abandoning the current issue."""
        self.current_issue = issue_id
        self._redmine_report_issue(irc, msg, set_topic=True)
    issue = wrap_chair(issue, ['positiveInt'])

    @wrap
    def here(self, irc, msg, args):
        """Record a note in the meeting minutes that a user is present for this triage session

        The meeting chair and anyone participating using
        triage bot commands should be automatically added."""
        if msg.nick not in self.triagers:
            self.triagers.add(msg.nick)
            join_msg = "%s has joined triage" % msg.nick
            self._meetbot_info(irc, msg, [join_msg])
            irc.reply(join_msg)
        else:
            irc.reply('You have already joined this triage session.', private=True)

    @wrap(['text'])
    def needhelp(self, irc, msg, args, text):
        """<text>

        Register a call for help in the triage meeting minutes."""
        self._meetbot_help(irc, msg, args, text)

    def next(self, irc, msg, args):
        """Advance to the next triage issue if a quorum is present."""
        # check the quorum
        if not self._quorum:
            irc.error('No quorum, more triagers need to !here to proceed.')
            return

        # take the triage issues list and push the deferred issues to the back
        self._refresh_triage_issues(irc)
        triage_issues = []
        deferred = []
        for issue in self.triage_issues:
            if issue in self.seen or issue == self.current_issue:
                continue
            if issue in self.deferred:
                deferred.append(issue)
            else:
                triage_issues.append(issue)
        triage_issues.extend(deferred)

        # mark the previous issue as seen
        if self.current_issue is not None:
            self.seen.add(self.current_issue)
            self.current_issue = None

        # triage the next issue
        try:
            self.current_issue = triage_issues[0]
            irc.reply('%d issues left to triage.' % len(triage_issues))
            self._redmine_report_issue(irc, msg)
        except IndexError:
            irc.reply('No issues left to triage.')
    next = wrap_chair(next)

    def skip(self, irc, msg, args):
        """Immediately skip the current issue with no resolution."""
        self.next(irc, msg, args)
    skip = wrap_chair(skip)

    @wrap([optional('text')])
    def start(self, irc, msg, args, the_rest):
        """[text] - optional additional text to include in the meeting topic

        Start an IRC triage session. The person calling start becomes the chair."""
        self._reset()
        self.chairs.add(msg.nick)
        self._meetbot_startmeeting(irc, msg, the_rest)
        self._refresh_triage_issues(irc)

    @wrap(['text'])
    def suggest(self, irc, msg, args, text):
        """<text>

        Suggest an idea, which will be recorded into the triage meeting minutes."""
        self._meetbot_idea(irc, msg, args, text)

    @property
    def _quorum(self):
        quorum_count = self.registryValue('quorum_count')
        return len(self.triagers) >= quorum_count

    # subcommands
    class Propose(callbacks.Commands):
        # validation is done in-method since we need to go get the available options
        # for priority, severity, and traget release from Redmine.
        @wrap(['something', 'something', additional('something')])
        def triage(self, irc, msg, args, priority, severity, target_release):
            """<priority> <severity> [target_release]

            Propose triage values including priority, severity, and an optional target release.
            """
            proposal = 'Priority: %s, Severity %s' % (priority, severity)
            if target_release:
                proposal += ' Target Platform Release: %s' % target_release
            self._set_proposal(irc, ('triage', proposal))

        @wrap
        def accept(self, irc, msg, args):
            """Propose accepting the current issue in its current state."""
            self._set_proposal(irc,
                               ('accept', 'Leave the issue as-is, accepting its current state.'))

        @wrap
        def defer(self, irc, msg, args):
            """Propose deferring the current issue until later in triage."""
            self._set_proposal(irc, ('defer', 'Defer this issue until later in triage.'))

        @wrap
        def skip(self, irc, msg, args):
            """Propose skipping the current issue for this triage session."""
            self._set_proposal(irc, ('skip', 'Skip this issue for this triage session.'))

        @wrap
        def needinfo(self, irc, msg, args):
            """Propose that the current issue cannot be triaged without more info."""
            self._set_proposal(irc,
                               ('needinfo', 'This issue cannot be triaged without more info.'))

        def _set_proposal(self, irc, proposal):
            irc.getCallback('PulpTriage').proposal = proposal
            irc.reply('Proposed - %s' % proposal[1])

    propose = Propose

    # meetbot wrappers

    def _meetbot_call(self, irc, msg, new_command, args=None):
        # new_command is a meetbot command string, e.g. "#action user needs to do foo"
        # if args is passed, it needs to be a list.
        # args items will get stringified and concatenated to the new command
        if args:
            # "#command arg arg arg"
            new_command += ' ' + ' '.join(map(str, args))
        meet_bot = irc.getCallback('MeetBot')
        new_msg = IrcMsg(prefix='', args=(msg.args[0], new_command), msg=msg)
        meet_bot.doPrivmsg(irc, new_msg)

        # anyone participating in triage implicitly joins
        if msg.nick not in self.triagers:
            self.here(irc, msg, [])

    def _meetbot_meeting(self, irc, msg):
        import MeetBot
        reload(MeetBot)
        channel = msg.args[0]
        network = irc.msg.tags['receivedOn']
        meeting = MeetBot.meeting_cache.get((channel, network), None)
        if meeting is None:
            irc.reply("No currently active meetings.")
        return meeting

    def _meetbot_action(self, irc, msg, args, text):
        self._meetbot_call(irc, msg, "#action", [text])

    def _meetbot_help(self, irc, msg, args, text):
        self._meetbot_call(irc, msg, "#help", [text])

    def _meetbot_idea(self, irc, msg, args, text):
        self._meetbot_call(irc, msg, "#idea", [text])

    def _meetbot_agreed(self, irc, msg, args):
        self._meetbot_call(irc, msg, "#agreed", args)

    def _meetbot_endmeeting(self, irc, msg):
        self._meetbot_call(irc, msg, "#endmeeting")

    def _meetbot_info(self, irc, msg, args):
        self._meetbot_call(irc, msg, "#info", args)

    def _meetbot_link(self, irc, msg, args):
        self._meetbot_call(irc, msg, "#link", args)

    def _meetbot_topic(self, irc, msg, args):
        self._meetbot_call(irc, msg, "#topic", args)

    def _meetbot_addchair(self, irc, msg, args):
        # anyone needs to be able to run this, so we need to poke at the meeting object directly
        channel = msg.args[0]
        network = irc.msg.tags['receivedOn']
        nick = msg.nick

        meeting_key = (channel, network)
        meeting = meeting_cache.get(meeting_key, None)
        if not M:
            # No meeting, nothing to do.
            return

        meeting.chairs.setdefault(nick, True)
        irc.reply("Chair added: %s on (%s, %s)." % (nick, channel, network))

    def _meetbot_startmeeting(self, irc, msg, the_rest):
        datestamp = time.strftime('%F')
        msgstr = "#startmeeting Pulp Triage " + datestamp
        if the_rest:
            msgstr = msgstr + ' ' + the_rest
        self._meetbot_call(irc, msg, msgstr)

    def _redmine_query(self, irc, url, **kwargs):
        redmine = irc.getCallback('PulpRedmine')
        response = redmine.resource.get(url, **kwargs)
        try:
            result = json.loads(response.body_string())
        except json.JSONDecodeError:
            self.log.error('Unable to parse redmine data:')
            self.log.error(data)
            raise
        return result

    def _redmine_report_issue(self, irc, msg, set_topic=False):
        if self.current_issue:
            redmine = irc.getCallback('PulpRedmine')
            strings = redmine.getBugs([self.current_issue])
            for line in strings:
                irc.reply(line, prefixNick=False)

            # after printing the bug, check to see who explicitly cares
            # this is a bit of a weird place to put this, but works alright
            if self.current_issue in self.carers:
                care_nicks = ', '.join(sorted(self.carers[self.current_issue]))
                irc.reply('%s: Issue %d is currently being discussed.' % (care_nicks,
                                                                          self.current_issue))

            if set_topic and len(strings) > 1:
                self._meetbot_topic(irc, msg, [strings[1]])

    def _redmine_triage_issues(self, irc):
        report_id = self.registryValue('report_id')
        result = self._redmine_query(irc, '/issues.json', query_id=report_id)
        if 'issues' in result:
            for issue in result['issues']:
                yield issue['id']
        else:
            irc.error('Unable to fetch issues list from Redmine.')

    def _refresh_triage_issues(self, irc):
        self.triage_issues = self._redmine_triage_issues(irc)

Class = PulpTriage


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=99:
