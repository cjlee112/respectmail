
RespectMail
-----------

In a world of junk mail, you deserve a little respect...

RespectMail is an automatic email triage tool that works with
any IMAP server(s) you use.  It splits incoming email on the IMAP server
into several triage folders:

* **Requests**: messages that you are likely to answer
* **FYI**: messages that you may need to answer
* **Closed**: messages you've already answered or that require no action.
* **JunkTriage**: messages from addresses that you generally ignore.
* **Blacklist**: messages from addresses that you never want to see again.
* **StrangersINBOX**: messages where no clear determination is possible are
  moved here, for you to screen.  By default, any messages left here
  at the time of the next triage will be *blacklisted*.
  Hence, you should move relevant messages
  to Requests, FYI or Closed, and simply delete any messages that 
  you just want to ignore (but not blacklist).

It bases this on statistical analysis of your email history
(it reconstructs the thread structure of all your email conversations),
currently from the following possible sources:

* Maildir database of old messages;
* Apple Mail database of old messages (by way of converting it to Maildir);
* IMAP server(s);
* your curation of its triage predictions.  You do this simply by moving
  miscategorized messages from a triage folder (e.g. Requests)
  to the correct "final verdict" folder,
  or simply deleting messages that are not
  of interest to you.  You do this using whatever mail client you want.

RespectMail's predictions will get better and better as
it accumulates more and more historical data on what you consider
relevant vs. not.

**WARNING**: this is early stage alpha software, in active development,
likely to crash,
undocumented, not recommended for use by others -- for the moment.
As I keep using and improving this, I'll try to whip
this into a form usable for others.

Here's an example run::

  $ python respectmail/triage.py 
  Enter password for somebody on mail.chem.ucla.edu:
  Enter password for somebodyelse on imap.mbi.ucla.edu:
  getting updates from mail.chem.ucla.edu...
  getting updates from imap.mbi.ucla.edu...
  reanalyzing thread graph...
  updating threads db...
  analyzing addr counts...
  updating addrs db...
  triaging messages on mail.chem.ucla.edu...
  Triaging 1 messages to Closed...
  Triaging 1 messages to Requests...
  Triaging 2 messages to Requests...
  Triaging 5 messages to FYI...
  Triaging 19 messages to Blacklist...
  Triaging 2 messages to JunkTriage...
  Triaging 10 messages to StrangersINBOX...
  triaging messages on imap.mbi.ucla.edu...
  Triaging 10 messages to Blacklist...
  Triaging 1 messages to JunkTriage...
  Triaging 1 messages to StrangersINBOX...
  
  Please review messages in StrangersINBOX, and move or delete
  messages that you do NOT want to blacklist.  By default, messages left
  in StrangersINBOX will be blacklisted.
  
  When ready, enter Y to purge Blacklist and StrangersINBOX
      (or any other key to postpone to later): y
  purging blacklisted messages from mail.chem.ucla.edu...
  purging blacklisted messages from imap.mbi.ucla.edu...

install dependencies
--------------------

Currently

* Python
* imapclient
* it uses scipy for some statistical analysis; I will try to 
  modulate that requirement in future versions.

initial setup
-------------

* create the initial sqlite3 database in your current directory as follows::

    from respectmail import db
    tdb = db.TriageDB(createTables=True, myAddrs=('me@example.com', 'me@gmail.com'))

* write a ``config.py`` file that specifies what IMAP servers you
  want to triage::

    from respectmail import imap
    mailServers = [
      imap.IMAPServer('imap.example.com', 'me')
      imap.IMAPServer('imap.gmail.com', 'me@gmail.com', serverID=2),
      ]

How you use it
--------------

Assuming the sqlite3 database file (by default ``maildir.db``)
is in your current directory, you run a triage on all your IMAP
servers via::

  python -i /path/to/respectmail/triage.py

It will ask you for IMAP server password(s), get INBOX and Sent
mail headers, analyze data and perform the triage.  It tells you
how many messages it triaged to each category, and how many were
indeterminate (moved to StrangersINBOX).  Because I'm a paranoid
software developer, I typically run this in
interactive mode (-i) so I can manually inspect / resume the
triage process if something goes wrong, but that is in no
way necessary.

You should then use your regular email client to look at the
folders Requests, FYI, Closed and StrangersINBOX.  For messages
that were incorrectly categorized, move them to the right
folder.  If a message is not of interest to you, pick between
the following options:

* Blacklist: if you never want to see messages from this sender
  again, move the message to the Blacklist folder.  Note that
  messages left in StrangersINBOX will be *automatically*
  blacklisted at the time of the next triage, so you do not need
  to move them to the Blacklist folder.
* if the message is not of interest to you, but you don't want to
  blacklist the sender, either move it to Junk or simply delete it.

Messages that are unlikely to be of interest to you (but not
blacklisted) are triaged to JunkTriage.  If you wish, you can inspect this 
folder and recategorize messages if necessary.



Rerun the respectmail triage just before viewing your new
incoming mail (using whatever IMAP client you like).


Why Did I Start This?
---------------------

PROBLEM: my various email programs (Apple Mail, Gmail) were so full of
junk mail that it was getting hard to find the messages I actually care
about.  I ended up having to switch from a blacklisting strategy
(list the addresses you don't want to see) to a pure whitelisting
strategy (only show emails from the list of addresses explicitly
cleared as valid).  The blacklist would grow infinitely;
only the whitelist is finite...
The fundamental problem is that essentially every organization we deal with
(in my case ranging
from my employer, UCLA, to every journal, group or company I've ever
had contact with) is vigorously deluging us with junk mail.  But
**Spam** filters are only looking for Viagra ads, phishing attempts
and obvious cons.  Unfortunately that's only the tip of the
junk mail iceberg.

It struck me that these spam filters are ignoring a simple, crucial
piece of information: what's the probability that I'm going to 
*respond* to a message from a given address?  This is an operational
criterion: people that I answer, may need answers in the future.
Emails that I steadfastly ignore (dozens of times) are a pretty safe
bet for ignoring in the future.

It also annoyed me that mail programs are typically take-it-or-leave-it:
a monolithic package of functionality that locks your content
inside itself (in the case of Apple Mail, using a format that is
not even officially documented).  This makes it hard to "get the best
of all worlds" by mixing different best-in-class tools; instead you're
typically stuck with one tool that tries to be a "one stop shop" for
managing all aspects of your email.  This seemed silly to me:
the IMAP standard provides a clean interface where we can mix
whatever tools we want.

I wanted to manage my mail using the power of data mining backends
and statistical algorithms.

I disliked the security risks associated with downloading every
received message to my computer.  Instead I want only headers
to enter my machine.

