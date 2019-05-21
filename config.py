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

import supybot.conf as conf
import supybot.registry as registry


def configure(advanced):
    # This will be called by supybot to configure this module.  advanced is
    # a bool that specifies whether the user identified themself as an advanced
    # user or not.  You should effect your configuration by manipulating the
    # registry as appropriate.
    from supybot.questions import expect, anything, something, yn
    conf.registerPlugin('PulpTriage', True)


PulpTriage = conf.registerPlugin('PulpTriage')

conf.registerGlobalValue(
    PulpTriage, 'proposal_timeout',
    registry.PositiveFloat(2.0, """Time, in seconds, to ignore proposals
    after a triage user makes a proposal. This prevents multiple simultaneous
    proposals from overlapping."""))
conf.registerGlobalValue(
    PulpTriage, 'quorum_count',
    registry.NonNegativeInteger(2, """Number of users required to reach a
    quorum. New issues will not be submitted for triage if the number of
    triaging users goes below this count."""))
conf.registerGlobalValue(
    PulpTriage, 'proposal_timeout',
    registry.NonNegativeInteger(2, """Number of seconds to wait after
    accepting a proposal before accepting another (prevents confusion
    by only accepting one proposal at a time)"""))
conf.registerGlobalValue(
    PulpTriage, 'report_id',
    registry.NonNegativeInteger(134, """ID of the Redmine report containing
    non-triaged issues"""))

conf.registerChannelValue(
    PulpTriage, 'announce',
    registry.Boolean(False, """Whether or not to announce triage in
    a channel when !triage announce is called"""))
conf.registerChannelValue(
    PulpTriage, 'announce_text',
    registry.String('', """Triage announcement text. Since this is empty
    by default, it must be set appropriately per-channel for announcements
    to be made."""))

# vim:set shiftwidth=4 tabstop=4 expandtab textwidth=99:
